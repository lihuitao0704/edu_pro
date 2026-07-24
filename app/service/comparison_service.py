"""
Comparison Service — 客户对比分析业务编排层

编排流程：
  1. 获取两客户画像 → 2. 提取差异（风险、资产、偏好）
  → 3. 查询共同持仓（Neo4j COMMON_HOLDINGS 模板）→ 4. 生成对比报告
"""

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.service.profile_service import ProfileService
from app.tool.graph_tool import GraphTool
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ComparisonService:
    """客户对比分析编排服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._profile_service = ProfileService(db)
        self._graph_tool = GraphTool()

    # ═══════════════════════════════════════════════════════════════
    # 主入口
    # ═══════════════════════════════════════════════════════════════

    async def compare(self, customer_id_1: int, customer_id_2: int) -> dict:
        """
        对比两个客户的画像、持仓及行业偏好。

        Returns:
            结构化的对比报告 dict，包含画像差异、共同/独特持仓、行业偏好对比
        """
        # Step 1: 获取两客户画像
        profile_a = await self._get_profile_summary(customer_id_1)
        profile_b = await self._get_profile_summary(customer_id_2)

        # Step 2: 提取差异
        diff = self._extract_diff(profile_a, profile_b)

        # Step 3: 查询共同持仓（Neo4j COMMON_HOLDINGS Cypher）
        common = await self._get_common_holdings(customer_id_1, customer_id_2)

        # Step 4: 查询各自持仓行业分布
        industry_a = await self._graph_tool.get_industry_distribution(customer_id_1)
        industry_b = await self._graph_tool.get_industry_distribution(customer_id_2)

        # Step 5: 生成对比报告
        return {
            "customer_a": profile_a,
            "customer_b": profile_b,
            "comparison": diff,
            "holdings": {
                "common": common,
                "industry_a": [{"industry": r.get("industry"), "count": r.get("count")} for r in industry_a],
                "industry_b": [{"industry": r.get("industry"), "count": r.get("count")} for r in industry_b],
                "industry_overlap": self._calc_industry_overlap(industry_a, industry_b),
            },
            "summary": self._generate_summary(diff, common, industry_a, industry_b),
        }

    # ═══════════════════════════════════════════════════════════════
    # 画像汇总
    # ═══════════════════════════════════════════════════════════════

    async def _get_profile_summary(self, customer_id: int) -> dict:
        """获取客户画像摘要（风险等级 + 基础信息 + 持仓概要）"""
        try:
            assess = await self._profile_service.assess(customer_id, trigger_type="comparison")
        except Exception as e:
            logger.warning(f"获取客户 {customer_id} 画像失败: {e}")
            return {"customer_id": customer_id, "error": str(e)}

        # 查询用户基础信息
        from sqlalchemy import select
        from app.model.entities import SysUser, FinCustomerProfile

        user_stmt = select(SysUser).where(SysUser.id == customer_id)
        user_result = await self.db.execute(user_stmt)
        user = user_result.scalar_one_or_none()

        profile_stmt = select(FinCustomerProfile).where(FinCustomerProfile.customer_id == customer_id)
        profile_result = await self.db.execute(profile_stmt)
        profile = profile_result.scalar_one_or_none()

        # 持仓汇总
        from sqlalchemy import text
        holdings_result = await self.db.execute(
            text(
                "SELECT COUNT(*) AS count, COALESCE(SUM(current_value), 0) AS total "
                "FROM fin_holdings WHERE customer_id = :cid AND status = '持有中'"
            ),
            {"cid": customer_id},
        )
        holdings_row = holdings_result.fetchone()

        return {
            "customer_id": customer_id,
            "name": user.real_name if user else "未知",
            "age": user.age if user else None,
            "occupation": user.occupation if user else None,
            "risk_level": assess.risk_level if not isinstance(assess, dict) else None,
            "risk_score": assess.total_score if not isinstance(assess, dict) else None,
            "total_assets": str(profile.total_assets) if (profile and profile.total_assets) else None,
            "annual_income_range": profile.annual_income_range if profile else None,
            "investment_experience": profile.investment_experience if profile else None,
            "holdings_count": holdings_row[0] if holdings_row else 0,
            "holdings_value": round(float(holdings_row[1]), 2) if holdings_row and holdings_row[1] else 0,
        }

    # ═══════════════════════════════════════════════════════════════
    # 差异提取
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _extract_diff(profile_a: dict, profile_b: dict) -> list:
        """提取两客户在上述维度的差异列表"""
        diffs = []

        # 风险等级
        ra = profile_a.get("risk_level", "N/A")
        rb = profile_b.get("risk_level", "N/A")
        if ra != rb:
            diffs.append({
                "dimension": "风险等级",
                "customer_a": ra,
                "customer_b": rb,
                "note": f"风险偏好差距：{ra} vs {rb}",
            })

        # 风险评分
        sa = profile_a.get("risk_score", 0) or 0
        sb = profile_b.get("risk_score", 0) or 0
        score_gap = abs(sa - sb)
        if score_gap > 10:
            diffs.append({
                "dimension": "风险评分",
                "customer_a": f"{sa:.1f}分" if sa else "N/A",
                "customer_b": f"{sb:.1f}分" if sb else "N/A",
                "note": f"评分差距 {score_gap:.1f} 分，差异显著",
            })

        # 总资产
        ta = profile_a.get("total_assets", "N/A")
        tb = profile_b.get("total_assets", "N/A")
        if ta != tb:
            diffs.append({
                "dimension": "总资产",
                "customer_a": ta or "未知",
                "customer_b": tb or "未知",
                "note": "资产规模不同，配置策略需差异化",
            })

        # 投资经验（数据库存字符串，需映射为数值后再比较）
        exp_map = {"1年以下": 0.5, "1-3年": 2, "3-5年": 4, "5-10年": 7, "10年以上": 10}
        ea_str = profile_a.get("investment_experience") or "1年以下"
        eb_str = profile_b.get("investment_experience") or "1年以下"
        ea = exp_map.get(ea_str, 0)
        eb = exp_map.get(eb_str, 0)
        if abs(ea - eb) >= 3:
            diffs.append({
                "dimension": "投资经验",
                "customer_a": ea_str,
                "customer_b": eb_str,
                "note": "经验差异明显，产品推荐需区别对待",
            })

        # 持仓数量
        ha = profile_a.get("holdings_count", 0)
        hb = profile_b.get("holdings_count", 0)
        if ha != hb:
            diffs.append({
                "dimension": "持仓产品数",
                "customer_a": ha,
                "customer_b": hb,
                "note": "持仓分散度不同",
            })

        # 持仓市值
        va = profile_a.get("holdings_value", 0)
        vb = profile_b.get("holdings_value", 0)
        if va or vb:
            diffs.append({
                "dimension": "持仓市值",
                "customer_a": f"{va:,.0f}元" if va else "N/A",
                "customer_b": f"{vb:,.0f}元" if vb else "N/A",
                "note": "持仓规模对比",
            })

        return diffs

    # ═══════════════════════════════════════════════════════════════
    # 共同持仓（Neo4j Cypher）
    # ═══════════════════════════════════════════════════════════════

    async def _get_common_holdings(self, id1: int, id2: int) -> list:
        """通过 Neo4j 执行 COMMON_HOLDINGS Cypher 查询"""
        from app.config.database import get_neo4j_driver
        from app.config.settings import get_settings

        try:
            driver = get_neo4j_driver()
            settings = get_settings()
            async with driver.session(database=settings.neo4j.database) as session:
                result = await session.run(
                    """MATCH (c1:Customer {id: $id1})-[:INVESTS_IN]->(p:Product)<-[:INVESTS_IN]-(c2:Customer {id: $id2})
                       RETURN p.code AS product_code, p.type AS product_type, p.name AS product_name""",
                    id1=id1, id2=id2,
                )
                return await result.data()
        except Exception as e:
            logger.warning(f"Neo4j 共同持仓查询失败: {e}")
            return []

    # ═══════════════════════════════════════════════════════════════
    # 行业重叠计算
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _calc_industry_overlap(industries_a: list, industries_b: list) -> dict:
        """计算两个客户持仓行业的重叠情况"""
        set_a = {r.get("industry", "") for r in industries_a}
        set_b = {r.get("industry", "") for r in industries_b}

        common = set_a & set_b
        only_a = set_a - set_b
        only_b = set_b - set_a

        return {
            "common_industries": sorted(common),
            "only_a_industries": sorted(only_a),
            "only_b_industries": sorted(only_b),
            "overlap_ratio": round(len(common) / max(len(set_a | set_b), 1), 2),
        }

    # ═══════════════════════════════════════════════════════════════
    # 摘要生成
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _generate_summary(
        diffs: list,
        common_holdings: list,
        industry_a: list,
        industry_b: list,
    ) -> str:
        """生成人类可读的对比摘要"""
        parts = []

        # 差异数量
        if diffs:
            parts.append(f"两客户在 {len(diffs)} 个维度上存在差异："
                         + "、".join(d["dimension"] for d in diffs))

        # 共同持仓
        if common_holdings:
            codes = [h.get("product_code", "?") for h in common_holdings]
            parts.append(f"共同持仓 {len(common_holdings)} 个产品：{', '.join(codes)}")
        else:
            parts.append("两客户无共同持仓产品")

        # 行业重叠
        industries_a_set = {r.get("industry") for r in industry_a}
        industries_b_set = {r.get("industry") for r in industry_b}
        overlap = industries_a_set & industries_b_set
        if overlap:
            parts.append(f"共同偏好行业：{'、'.join(sorted(overlap))}")

        return "；".join(parts) if parts else "两客户暂无可对比数据"
