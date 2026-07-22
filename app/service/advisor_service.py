"""
投顾推荐服务
产品推荐 + 资产配置 + 风控事件订阅
"""

import asyncio
import json
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.model.schemas import ProductRecommend, AllocationResult
from app.model.entities import ProductRecommendation, FinCustomerProfile
from app.service.profile_service import ProfileService
from app.tool.graph_tool import GraphTool
from app.config.rules_config import (
    SUITABILITY_MATRIX, ASSET_ALLOCATION_TEMPLATES, RECOMMENDATION_WEIGHTS,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


# Mock 产品数据（实际应从数据库获取）
MOCK_PRODUCTS = [
    {"product_code": "F100001", "product_name": "现金宝货币A", "risk_level": "R1", "expected_return": 2.5, "product_type": "货币基金", "term_days": 0},
    {"product_code": "F100002", "product_name": "天添利货币B", "risk_level": "R1", "expected_return": 2.8, "product_type": "货币基金", "term_days": 0},
    {"product_code": "F200001", "product_name": "XX稳健增利债券A", "risk_level": "R2", "expected_return": 4.5, "product_type": "债券基金", "term_days": 180},
    {"product_code": "F200002", "product_name": "XX纯债优选", "risk_level": "R2", "expected_return": 4.0, "product_type": "债券基金", "term_days": 90},
    {"product_code": "F300001", "product_name": "XX平衡混合基金", "risk_level": "R3", "expected_return": 6.5, "product_type": "混合基金", "term_days": 365},
    {"product_code": "F300002", "product_name": "XX灵活配置混合", "risk_level": "R3", "expected_return": 7.0, "product_type": "混合基金", "term_days": 365},
    {"product_code": "F400001", "product_name": "XX价值成长股票", "risk_level": "R4", "expected_return": 10.0, "product_type": "股票基金", "term_days": 365},
    {"product_code": "F400002", "product_name": "XX行业精选ETF", "risk_level": "R4", "expected_return": 12.0, "product_type": "股票基金", "term_days": 365},
    {"product_code": "F500001", "product_name": "XX量化对冲私募", "risk_level": "R5", "expected_return": 15.0, "product_type": "私募产品", "term_days": 730},
]


class AdvisorService:
    """投顾推荐服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.profile_service = ProfileService(db)
        self._graph_tool = GraphTool()
        from app.tool.llm_tool import get_llm_tool
        self._llm = get_llm_tool()

    async def recommend_products(
        self, customer_id: int, top_n: int = 3, risk_level: Optional[str] = None
    ) -> dict:
        """产品推荐"""
        # 获取画像
        profile = await self.profile_service.get_profile(customer_id)
        if not profile:
            return {"recommendations": [], "customer_profile": None, "reasoning": "客户画像不存在，请先创建画像"}

        customer_risk = risk_level or profile.risk_level or "C2"
        allowed_levels = SUITABILITY_MATRIX.get(customer_risk, ["R1", "R2"])

        # 筛选
        candidates = [p for p in MOCK_PRODUCTS if p["risk_level"] in allowed_levels]

        # ── 图谱增强：获取客户当前持仓行业分布 ──
        customer_industries = await self._get_customer_industry_counts(customer_id)

        # ── 风控检查：高风险标记客户限制 R3+ 产品 ──
        is_high_risk = await self._check_risk_flag(customer_id)

        # 打分排序
        for p in candidates:
            risk_match = 1.0 if p["risk_level"] in allowed_levels[:2] else 0.6
            pref_match = 0.7  # 简化
            diversity = 0.8
            return_term = p["expected_return"] / 15.0  # 归一化

            # ── 图谱增强：行业集中度惩罚 ──
            graph_signal = await self._calc_graph_signal(
                product_code=p["product_code"],
                customer_industries=customer_industries,
            )

            # ── 风控惩罚：高风险标记客户 → R3+ 产品降权 ──
            risk_penalty = 1.0
            if is_high_risk and p["risk_level"] in ("R3", "R4", "R5"):
                risk_penalty = 0.3  # 高风险客户 R3+ 产品匹配分降至 30%

            p["match_score"] = (
                RECOMMENDATION_WEIGHTS["risk_match"] * risk_match
                + RECOMMENDATION_WEIGHTS["preference"] * pref_match
                + RECOMMENDATION_WEIGHTS["diversification"] * diversity
                + RECOMMENDATION_WEIGHTS["return_term"] * return_term
                + RECOMMENDATION_WEIGHTS["graph_signal"] * graph_signal
            ) * risk_penalty

        candidates.sort(key=lambda x: x["match_score"], reverse=True)
        top = candidates[:top_n]

        recommendations = [
            ProductRecommend(
                product_code=p["product_code"],
                product_name=p["product_name"],
                risk_level=p["risk_level"],
                expected_return=p["expected_return"],
                match_score=round(p["match_score"], 2),
                reason=await self._generate_reason(p, customer_risk, profile),
            )
            for p in top
        ]

        profile_dict = {
            "risk_level": customer_risk,
            "risk_score": profile.risk_score if hasattr(profile, "risk_score") else None,
        }

        reasoning = f"基于客户 {customer_risk} 风险等级，从 {len(candidates)} 个候选产品中推荐 Top{len(top)}"

        # ── 持久化推荐记录 ──
        await self._persist_recommendations(customer_id, recommendations)

        return {
            "recommendations": recommendations,
            "customer_profile": profile_dict,
            "reasoning": reasoning,
        }

    async def get_allocation(self, customer_id: int) -> AllocationResult:
        """资产配置建议"""
        profile = await self.profile_service.get_profile(customer_id)
        risk_level = profile.risk_level if profile else "C2"

        template = ASSET_ALLOCATION_TEMPLATES.get(risk_level, ASSET_ALLOCATION_TEMPLATES["C2"])

        explanations = {
            "C1": "保守型配置：以货币基金和债券为主，确保本金安全和稳定收益",
            "C2": "稳健型配置：债券为主，辅以少量混合基金，追求适度增值",
            "C3": "平衡型配置：股债平衡，兼顾收益与风险控制",
            "C4": "进取型配置：股票为主，追求较高收益，承受一定波动",
            "C5": "激进型配置：高比例权益类资产，追求超额收益",
        }

        return AllocationResult(
            customer_id=customer_id,
            risk_level=risk_level,
            allocation={k: round(v * 100, 0) for k, v in template.items()},
            explanation=explanations.get(risk_level, "标准配置"),
        )

    async def _persist_recommendations(self, customer_id: int, recommendations: list) -> None:
        """将推荐结果持久化到 product_recommendation 表"""
        for rec in recommendations:
            record = ProductRecommendation(
                customer_id=customer_id,
                product_code=rec.product_code,
                match_score=rec.match_score,
                score_detail={
                    "risk_level": rec.risk_level,
                    "expected_return": rec.expected_return,
                },
                reasoning=rec.reason,
            )
            self.db.add(record)
        await self.db.flush()

    # ═══════════════════════════════════════════════════════════════
    # 图谱增强 — 行业集中度
    # ═══════════════════════════════════════════════════════════════

    async def _get_customer_industry_counts(self, customer_id: int) -> dict:
        """
        获取客户当前持仓的行业分布计数。

        Returns:
            {"行业名": 产品数量, ...}，如 {"新能源": 3, "消费": 1}
        """
        try:
            dist = await self._graph_tool.get_industry_distribution(customer_id)
            return {r.get("industry", "未知"): r.get("product_count", r.get("count", 0))
                    for r in dist}
        except Exception as e:
            logger.warning(f"获取客户 {customer_id} 持仓行业分布失败: {e}")
            return {}

    async def _calc_graph_signal(self, product_code: str, customer_industries: dict) -> float:
        """
        计算图谱增强信号（行业集中度惩罚）。

        逻辑：
        1. 通过 Neo4j 查询该候选产品所属行业
        2. 如果客户该行业已有持仓，计算该行业在客户持仓中的占比
        3. 占比越高，graph_signal 越低（行业集中度惩罚）
        4. 如果该产品属于客户未涉及的新行业，给予正向信号（鼓励分散化）

        Returns:
            0.0 ~ 1.0 的图谱信号得分
        """
        try:
            industry = await self._graph_tool.get_product_industry(product_code)
        except Exception as e:
            logger.warning(f"查询产品 {product_code} 行业失败: {e}")
            return 0.5  # 查询失败时给中性分

        # 新行业 → 鼓励分散化，给高分
        if not industry or industry not in customer_industries:
            return 0.9

        # 已有行业 → 计算集中度惩罚
        total_products = sum(customer_industries.values())
        if total_products == 0:
            return 0.9

        industry_count = customer_industries.get(industry, 0)
        concentration_ratio = industry_count / total_products

        # 行业集中度惩罚曲线：
        #   ratio 0~25%     → 0.80（轻微惩罚）
        #   ratio 25~50%    → 0.55（中度惩罚）
        #   ratio 50~75%    → 0.30（显著惩罚）
        #   ratio >75%      → 0.10（严重惩罚 — 几乎只有这一个行业）
        if concentration_ratio <= 0.25:
            return 0.80
        elif concentration_ratio <= 0.50:
            return 0.55
        elif concentration_ratio <= 0.75:
            return 0.30
        else:
            return 0.10

    # ═══════════════════════════════════════════════════════════════
    # 风控事件订阅 & 风险标记检查
    # ═══════════════════════════════════════════════════════════════

    async def _check_risk_flag(self, customer_id: int) -> bool:
        """
        检查客户是否具有高风险标记。

        查询优先级：Redis 实时标记 > fin_customer_profile.risk_flag 字段

        Returns:
            True 表示客户有高风险标记，需在推荐中降权
        """
        # 1) 先查 Redis（实时、最新）
        try:
            from app.config.database import get_redis
            r = await get_redis()
            flag = await r.get(f"risk_flag:{customer_id}")
            if flag:
                logger.info(f"Redis 风险标记命中 | customer_id={customer_id} | flag={flag}")
                return flag == "high"
        except Exception as e:
            logger.warning(f"Redis 风险标记查询失败: {e}")

        # 2) 回退到数据库
        try:
            from sqlalchemy import select
            stmt = select(FinCustomerProfile).where(FinCustomerProfile.customer_id == customer_id)
            result = await self.db.execute(stmt)
            profile = result.scalar_one_or_none()
            if profile and profile.risk_flag == "high":
                logger.info(f"DB 风险标记命中 | customer_id={customer_id} | risk_flag=high")
                return True
        except Exception as e:
            logger.warning(f"DB 风险标记查询失败: {e}")

        return False

    @staticmethod
    async def set_risk_flag(customer_id: int, flag: str, ttl: int = 86400) -> None:
        """
        在 Redis 中设置客户风险标记，并异步持久化到 fin_customer_profile 表。

        Args:
            customer_id: 客户ID
            flag: 风险标记值（normal / warning / high）
            ttl: Redis 过期时间（秒），默认 86400（24小时）
        """
        # 写入 Redis
        try:
            from app.config.database import get_redis
            r = await get_redis()
            await r.set(f"risk_flag:{customer_id}", flag, ex=ttl)
            logger.info(f"风险标记已设置 | customer_id={customer_id} | flag={flag} | ttl={ttl}s")
        except Exception as e:
            logger.warning(f"Redis 风险标记写入失败: {e}")

    @staticmethod
    async def subscribe_risk_alerts(stop_event: Optional[asyncio.Event] = None):
        """
        订阅 event_bus 的 risk_alert 事件，自动为涉事客户打上风险标记。

        监听 Redis Pub/Sub 频道 "event:risk_alert"。
        收到 high 级别警报时，调用 set_risk_flag() 标记客户。

        用法（在应用启动时执行一次）：
            asyncio.create_task(AdvisorService.subscribe_risk_alerts())
        """
        logger.info("投顾风控事件订阅者启动，监听 event:risk_alert …")

        while not (stop_event and stop_event.is_set()):
            try:
                from app.config.database import get_redis
                r = await get_redis()
                pubsub = r.pubsub()
                await pubsub.subscribe("event:risk_alert")

                async for message in pubsub.listen():
                    if stop_event and stop_event.is_set():
                        break
                    if message["type"] != "message":
                        continue

                    try:
                        data = json.loads(message["data"])
                        payload = data.get("payload", {})
                        action = payload.get("action", "")
                        customer_id = payload.get("arguments", {}).get("customer_id")
                        result = payload.get("result", {})
                        alert_level = result.get("alert_level", "")

                        if not customer_id:
                            continue

                        # 仅 high 级别警报触发风险标记
                        if alert_level == "high":
                            await AdvisorService.set_risk_flag(customer_id, "high")
                            logger.info(
                                f"风控事件触发风险标记 | customer_id={customer_id} "
                                f"| action={action} | alert_level={alert_level}"
                            )
                    except Exception as e:
                        logger.error(f"处理风控事件失败: {e}")
                        continue

            except Exception as e:
                logger.error(f"风控事件订阅异常（5秒后重连）: {e}")
                await asyncio.sleep(5)

    # ═══════════════════════════════════════════════════════════════
    # LLM 个性化推荐理由
    # ═══════════════════════════════════════════════════════════════

    async def _generate_reason(self, product: dict, customer_risk: str, profile) -> str:
        """
        使用 LLM 生成个性化推荐理由。

        Prompt 包含客户画像信息（风险等级、资产规模、偏好）和产品信息，
        要求 LLM 引用画像说明为什么适合该客户，语气专业亲切，50字以内。
        """
        risk_map = {"C1": "保守型", "C2": "稳健型", "C3": "平衡型", "C4": "进取型", "C5": "激进型"}
        risk_name = risk_map.get(customer_risk, customer_risk)

        total_assets = "未知"
        if profile and hasattr(profile, "total_assets") and profile.total_assets:
            total_assets = f"{float(profile.total_assets):,.0f}元"

        product_preference = "均衡配置"
        if customer_risk in ("C1", "C2"):
            product_preference = "偏好低风险稳健收益"
        elif customer_risk in ("C4", "C5"):
            product_preference = "偏好高风险高收益"

        prompt = (
            f"根据以下客户画像信息，为推荐的产品生成个性化推荐理由：\n"
            f"客户风险等级：{risk_name}（{customer_risk}级）\n"
            f"资产规模：{total_assets}\n"
            f"投资偏好：{product_preference}\n"
            f"推荐产品：{product['product_name']}（{product['risk_level']}级{product['product_type']}"
            f"，预期年化{product['expected_return']}%）\n"
            f"\n"
            f"要求：引用画像信息说明为什么适合该客户，语气专业亲切，50字以内。"
        )

        try:
            reason = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=128,
            )
            # 清理：去掉可能的引号、换行
            reason = reason.strip().strip('"').strip("'").replace("\n", " ")
            if not reason:
                raise ValueError("LLM 返回空推荐理由")
        except Exception as e:
            logger.warning(f"LLM 生成推荐理由失败: {e}，回退为模板")
            # 回退：仍用原来的拼接方式
            reason = (
                f"该产品为{product['risk_level']}级{product['product_type']}，"
                f"预期年化{product['expected_return']}%，"
                f"与您的{risk_name}风险偏好匹配"
            )

        return reason
