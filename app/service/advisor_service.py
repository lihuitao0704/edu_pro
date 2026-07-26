"""
投顾推荐服务
产品推荐 + 资产配置 + 风控事件订阅
"""

import asyncio
import json
from datetime import datetime
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.model.schemas import ProductRecommend, AllocationResult
from app.model.entities import FinProduct, ProductRecommendation, FinCustomerProfile
from app.service.profile_service import ProfileService
from app.service.agent_event_service import AgentDomainEvent, EventDispatcher
from app.tool.graph_tool import GraphTool
from app.config.rules_config import (
    SUITABILITY_MATRIX, ASSET_ALLOCATION_TEMPLATES, RECOMMENDATION_WEIGHTS,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class AdvisorService:
    """投顾推荐服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.profile_service = ProfileService(db)
        self._graph_tool = GraphTool()
        from app.tool.llm_tool import get_llm_tool
        self._llm = get_llm_tool()

    @staticmethod
    def filter_candidates_by_preferences(candidates: list[dict], preference: Optional[dict]) -> list[dict]:
        """Apply non-regulatory feedback constraints to the candidate pool."""
        avoided = set((preference or {}).get("avoid_product_types") or [])
        return [dict(product) for product in candidates if product.get("product_type") not in avoided]

    @classmethod
    def _product_quality_issue(cls, product: dict) -> str | None:
        """Reject internally inconsistent or implausible product master data."""
        risk_text = str(product.get("risk_level") or "").strip().upper()
        if len(risk_text) != 2 or not risk_text.startswith("R") or not risk_text[1].isdigit():
            return "invalid_risk_level"
        risk_num = int(risk_text[1])
        if risk_num < 1 or risk_num > 5:
            return "invalid_risk_level"

        product_type = str(product.get("product_type") or "")
        product_name = str(product.get("product_name") or "")
        category_text = f"{product_type} {product_name}".lower()
        expected_return = float(product.get("expected_return") or 0)
        if expected_return < 0:
            return "negative_expected_return"

        if any(word in category_text for word in ("股票", "权益", "equity", "etf")):
            if risk_num < 4:
                return "equity_risk_level_too_low"
            max_return = 35.0
        elif any(word in category_text for word in ("混合", "mixed")):
            if risk_num < 3:
                return "mixed_risk_level_too_low"
            max_return = 20.0
        elif any(word in category_text for word in ("债券", "固收", "bond")):
            if risk_num < 2:
                return "fixed_income_risk_level_too_low"
            max_return = 8.0
        elif any(word in category_text for word in ("货币", "现金", "cash", "money")):
            max_return = 6.0
        else:
            max_return = 20.0

        if expected_return > max_return:
            return "expected_return_outlier"
        return None

    @classmethod
    def _filter_product_quality(cls, products: list[dict]) -> list[dict]:
        safe_products: list[dict] = []
        for product in products:
            issue = cls._product_quality_issue(product)
            if issue:
                logger.warning(
                    "推荐候选产品数据质量拦截 | product_id=%s | code=%s | issue=%s",
                    product.get("product_id"),
                    product.get("product_code"),
                    issue,
                )
                continue
            safe_products.append(product)
        return safe_products

    async def _load_active_products(self, allowed_levels: list[str]) -> list[dict]:
        """Load an isolated snapshot of currently saleable products."""
        result = await self.db.execute(
            select(FinProduct).where(
                FinProduct.status == "在售",
                FinProduct.risk_level.in_(allowed_levels),
            )
        )
        products = result.scalars().all()
        snapshots: list[dict] = []
        for product in products:
            snapshot_time = product.update_time or product.create_time
            snapshots.append({
                "product_id": int(product.id),
                "product_code": product.product_code,
                "product_name": product.product_name,
                "risk_level": product.risk_level,
                "expected_return": float(product.expected_return or 0),
                "product_type": product.product_type,
                "min_amount": float(product.min_amount) if product.min_amount is not None else None,
                "term_days": product.term_days,
                "data_source": "fin_product",
                "product_snapshot_time": snapshot_time.isoformat() if snapshot_time else None,
                "rule_version": "suitability-v1",
            })
        return snapshots

    async def recommend_products(
        self, customer_id: int, top_n: int = 3, risk_level: Optional[str] = None,
        fallback_risk: Optional[str] = None,
    ) -> dict:
        """产品推荐。

        Args:
            fallback_risk: 画像不存在时的回退风险等级。传入 "C1" 则回退推荐R1产品。
        """
        # 获取画像
        profile = await self.profile_service.get_profile(customer_id)
        profile_not_found = False
        if not profile:
            if fallback_risk:
                # 画像不存在但有回退等级 → 推荐最低风险产品 + 提示
                profile_not_found = True
                customer_risk = fallback_risk
            else:
                return {"recommendations": [], "customer_profile": None,
                        "reasoning": "客户画像不存在，请先创建画像"}

        if not profile_not_found:
            customer_risk = risk_level or (
                profile.get("risk_level") if isinstance(profile, dict)
                else getattr(profile, "risk_level", None)
            ) or "C2"
        allowed_levels = SUITABILITY_MATRIX.get(customer_risk, ["R1", "R2"])

        # 只从当前在售产品中筛选，不再使用演示产品回退。
        candidates = await self._load_active_products(allowed_levels)
        candidates = self._filter_product_quality(candidates)
        preference = (
            profile.get("product_preference") if isinstance(profile, dict)
            else getattr(profile, "product_preference", None)
        ) if profile else None
        candidates = self.filter_candidates_by_preferences(candidates, preference)
        drawdown = ((preference or {}).get("analytics_signals") or {}).get("pnl_drawdown", {})
        is_drawdown = float(drawdown.get("profit_ratio", 0) or 0) <= -0.10

        # ── 风控检查：高风险标记客户限制 R3+ 产品 ──
        is_high_risk = await self._check_risk_flag(customer_id)

        # ── 图谱增强：并行查询 3 路多跳图信号 ──
        graph_collab_map: dict[str, float] = {}      # product_code → 协同过滤分
        graph_diversify_set: set[str] = set()         # 行业分散产品
        graph_peer_map: dict[str, float] = {}         # product_code → 同风险偏好分
        graph_ok = True   # 降级标记

        try:
            collab_recs = await self._graph_tool.get_collaborative_recommendations(customer_id)
            if collab_recs:
                max_peer = max(r.get("peer_count", 1) for r in collab_recs)
                for r in collab_recs:
                    graph_collab_map[r["product_code"]] = r["peer_count"] / max_peer
        except Exception:
            logger.warning(f"协同过滤图查询失败 customer={customer_id}，降级")

        try:
            diversify_recs = await self._graph_tool.get_industry_diversify(customer_id)
            graph_diversify_set = {r["product_code"] for r in diversify_recs if r.get("product_code")}
        except Exception:
            logger.warning(f"行业分散图查询失败 customer={customer_id}，降级")

        try:
            peer_recs = await self._graph_tool.get_peer_purchases(customer_id)
            if peer_recs:
                max_buyer = max(r.get("buyer_count", 1) for r in peer_recs)
                for r in peer_recs:
                    graph_peer_map[r["product_code"]] = r["buyer_count"] / max_buyer
        except Exception:
            logger.warning(f"同风险偏好图查询失败 customer={customer_id}，降级")

        # 如果三路查询全部失败，标记降级
        if not graph_collab_map and not graph_diversify_set and not graph_peer_map:
            graph_ok = False

        # ── 动态计算有效权重（图查询失败时等比放大其他权重）──
        weights = dict(RECOMMENDATION_WEIGHTS)
        if not graph_ok:
            # 降级：图信号权重归零，其他权重等比放大
            active_weight = sum(
                v for k, v in weights.items() if k not in ("graph_collab", "graph_diversify", "graph_peer")
            )
            scale = 1.0 / active_weight if active_weight > 0 else 1.0
            for k in ("graph_collab", "graph_diversify", "graph_peer"):
                weights[k] = 0.0
            for k, v in weights.items():
                if v > 0:
                    weights[k] = v * scale

        # 打分排序
        for p in candidates:
            risk_match = 1.0 if p["risk_level"] in allowed_levels[:2] else 0.6
            pref_match = 0.7
            return_term = min(p["expected_return"] / 15.0, 1.0)

            # 图信号：取三路中的最高分
            graph_collab = graph_collab_map.get(p["product_code"], 0.5)
            graph_diversify = 1.0 if p["product_code"] in graph_diversify_set else 0.3
            graph_peer = graph_peer_map.get(p["product_code"], 0.5)

            # ── 风控惩罚 ──
            risk_penalty = 1.0
            if is_high_risk and p["risk_level"] in ("R3", "R4", "R5"):
                risk_penalty = 0.3
            if is_drawdown and p["risk_level"] in ("R4", "R5"):
                risk_penalty *= 0.5

            p["match_score"] = (
                weights["risk_match"] * risk_match
                + weights["graph_collab"] * graph_collab
                + weights["preference"] * pref_match
                + weights["graph_diversify"] * graph_diversify
                + weights["graph_peer"] * graph_peer
                + weights["return_term"] * return_term
            ) * risk_penalty

        candidates.sort(key=lambda x: x["match_score"], reverse=True)
        top = candidates[:top_n]

        @staticmethod
        def _score_to_match_level(score: float) -> str:
            if score >= 0.8:
                return "高度匹配"
            elif score >= 0.6:
                return "中度匹配"
            elif score >= 0.4:
                return "一般匹配"
            return "低度匹配"

        recommendations = [
            ProductRecommend(
                product_id=p["product_id"],
                product_code=p["product_code"],
                product_name=p["product_name"],
                risk_level=p["risk_level"],
                product_type=p.get("product_type"),
                expected_return=p["expected_return"],
                min_amount=p.get("min_amount"),
                term_days=p.get("term_days"),
                match_score=round(p["match_score"], 2),
                match_level=_score_to_match_level(p["match_score"]),
                reason=await self._generate_reason(p, customer_risk, profile),
                data_source=p["data_source"],
                product_snapshot_time=p.get("product_snapshot_time"),
                rule_version=p["rule_version"],
            ).model_dump()
            for p in top
        ]

        profile_dict = {
            "risk_level": customer_risk,
            "risk_score": profile.risk_score if hasattr(profile, "risk_score") else None,
        }

        reasoning = f"基于客户 {customer_risk} 风险等级，从 {len(candidates)} 个候选产品中推荐 Top{len(top)}"

        # ── 持久化推荐记录（失败不影响推荐结果）──
        try:
            await self._persist_recommendations(customer_id, recommendations)
        except Exception as e:
            logger.warning(f"推荐记录持久化失败(不影响推荐结果): {e}")

        return {
            "recommendations": recommendations,
            "customer_profile": profile_dict,
            "reasoning": reasoning,
        }

    async def get_allocation(self, customer_id: int) -> AllocationResult:
        """资产配置建议"""
        profile = await self.profile_service.get_profile(customer_id)
        risk_level = (
            profile.get("risk_level") if isinstance(profile, dict)
            else getattr(profile, "risk_level", None)
        ) if profile else "C2"

        template = ASSET_ALLOCATION_TEMPLATES.get(risk_level, ASSET_ALLOCATION_TEMPLATES["C2"])

        explanations = {
            "C1": "保守型配置：以货币基金和债券为主，确保本金安全和稳定收益",
            "C2": "稳健型配置：债券为主，辅以少量混合基金，追求适度增值",
            "C3": "平衡型配置：股债平衡，兼顾收益与风险控制",
            "C4": "积极型配置：股票为主，追求较高收益，承受一定波动",
            "C5": "激进型配置：高比例权益类资产，追求超额收益",
        }

        return AllocationResult(
            customer_id=customer_id,
            risk_level=risk_level,
            allocation={k: round(v * 100, 0) for k, v in template.items()},
            explanation=explanations.get(risk_level, "标准配置"),
        ).model_dump()

    async def _persist_recommendations(self, customer_id: int, recommendations: list) -> None:
        """将推荐结果持久化到 product_recommendation 表"""
        records = []
        for rec in recommendations:
            record = ProductRecommendation(
                customer_id=customer_id,
                product_code=rec["product_code"],
                match_score=rec["match_score"],
                score_detail={
                    "product_id": rec.get("product_id"),
                    "risk_level": rec["risk_level"],
                    "expected_return": rec["expected_return"],
                    "product_type": rec.get("product_type", ""),
                    "min_amount": rec.get("min_amount"),
                    "term_days": rec.get("term_days"),
                    "data_source": rec.get("data_source", "fin_product"),
                    "product_snapshot_time": rec.get("product_snapshot_time"),
                    "rule_version": rec.get("rule_version", "suitability-v1"),
                },
                reasoning=rec["reason"],
            )
            self.db.add(record)
            records.append((rec, record))
        await self.db.flush()
        for rec, record in records:
            rec["recommendation_id"] = record.id

    async def record_recommendation_feedback(
        self, customer_id: int, recommendation_id: int, status: str, reason: str = ""
    ) -> ProductRecommendation | None:
        """Record feedback and update only behavioral preference constraints."""
        if status not in {"accepted", "rejected", "ignored"}:
            raise ValueError("反馈状态必须是 accepted、rejected 或 ignored")
        result = await self.db.execute(
            select(ProductRecommendation).where(
                ProductRecommendation.id == recommendation_id,
                ProductRecommendation.customer_id == customer_id,
            )
        )
        record = result.scalar_one_or_none()
        if not record:
            return None
        # Replayed clicks or client retries must not compound a behavioral
        # preference signal for the same recommendation.
        if record.status == status and record.feedback_at:
            return record

        record.status = status
        record.feedback_reason = reason[:255] or None
        record.feedback_at = datetime.now()

        product_type = (record.score_detail or {}).get("product_type") or "未知类型"
        await EventDispatcher.enqueue(
            self.db,
            AgentDomainEvent.create(
                event_type="recommendation_feedback",
                source_agent="advisor",
                customer_id=customer_id,
                correlation_id=f"recommendation:{recommendation_id}",
                payload={
                    "product_type": product_type,
                    "status": status,
                    "reason": reason,
                    "recommendation_id": recommendation_id,
                },
            ),
        )
        await self.db.flush()
        return record

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
        """Generate a deterministic user-facing reason without prompt leakage."""
        risk_map = {"C1": "保守型", "C2": "稳健型", "C3": "平衡型", "C4": "积极型", "C5": "激进型"}
        risk_name = risk_map.get(customer_risk, customer_risk)
        product_type = str(product.get("product_type") or "产品")
        reason = (
            f"该{product_type}风险等级为{product['risk_level']}，"
            f"与您的{risk_name}风险承受能力相匹配，可作为分散配置参考。"
        )
        return reason[:80]
