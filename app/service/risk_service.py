"""
风险评估服务
风评问卷 / 答题评分 / 适当性匹配
"""

from datetime import date, datetime, timedelta
from typing import List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.model.entities import CustomerTag, RiskAssessment, FinCustomerProfile
from app.model.schemas import QuestionnaireItem, AssessmentAnswer, AssessmentResult, SuitabilityCheckResult
from app.engine.score_mapper import check_suitability, map_score_to_risk_level
from app.memory.profile_cache import ProfileCache
from app.memory.long_term import LongTermMemory
from app.tool.neo4j_sync import sync_risk_level
from app.utils.exceptions import ProfileNotFound, SuitabilityMismatch


# 16 道风评问卷（Mock）
QUESTIONNAIRE = [
    {"q": 1, "question": "您的年龄是？",
     "options": [{"A": "18-25岁", "score": 8}, {"B": "26-35岁", "score": 10}, {"C": "36-50岁", "score": 6}, {"D": "50岁以上", "score": 4}]},
    {"q": 2, "question": "您的年收入水平？",
     "options": [{"A": "10万以下", "score": 3}, {"B": "10-30万", "score": 5}, {"C": "30-100万", "score": 7}, {"D": "100万以上", "score": 10}]},
    {"q": 3, "question": "您的投资经验？",
     "options": [{"A": "无经验", "score": 2}, {"B": "1-3年", "score": 5}, {"C": "3-10年", "score": 7}, {"D": "10年以上", "score": 10}]},
    {"q": 4, "question": "您能承受的最大亏损比例？",
     "options": [{"A": "不能承受亏损", "score": 2}, {"B": "5%以内", "score": 4}, {"C": "10%-20%", "score": 6}, {"D": "20%以上", "score": 10}]},
    {"q": 5, "question": "您的投资目标是？",
     "options": [{"A": "保本保值", "score": 3}, {"B": "稳健增值", "score": 5}, {"C": "较高收益", "score": 7}, {"D": "追求高收益", "score": 10}]},
    {"q": 6, "question": "您偏好的投资期限？",
     "options": [{"A": "半年以内", "score": 3}, {"B": "半年-1年", "score": 5}, {"C": "1-3年", "score": 7}, {"D": "3年以上", "score": 10}]},
    {"q": 7, "question": "您的可投资资产规模？",
     "options": [{"A": "5万以下", "score": 3}, {"B": "5-20万", "score": 5}, {"C": "20-100万", "score": 7}, {"D": "100万以上", "score": 10}]},
    {"q": 8, "question": "您是否持有过股票或基金？",
     "options": [{"A": "从未持有", "score": 2}, {"B": "仅货币基金", "score": 4}, {"C": "持有基金", "score": 7}, {"D": "持有股票+基金", "score": 10}]},
    {"q": 9, "question": "市场下跌20%时，您会？",
     "options": [{"A": "全部赎回", "score": 2}, {"B": "部分赎回", "score": 4}, {"C": "继续持有", "score": 7}, {"D": "追加买入", "score": 10}]},
    {"q": 10, "question": "您的学历是？",
     "options": [{"A": "高中及以下", "score": 4}, {"B": "大专", "score": 6}, {"C": "本科", "score": 8}, {"D": "硕士及以上", "score": 10}]},
    {"q": 11, "question": "您的职业稳定性？",
     "options": [{"A": "无固定职业", "score": 3}, {"B": "自由职业", "score": 5}, {"C": "企业员工", "score": 7}, {"D": "公务员/国企", "score": 10}]},
    {"q": 12, "question": "您每月可用于投资的比例？",
     "options": [{"A": "5%以下", "score": 3}, {"B": "5%-15%", "score": 5}, {"C": "15%-30%", "score": 7}, {"D": "30%以上", "score": 10}]},
    {"q": 13, "question": "您对金融产品的了解程度？",
     "options": [{"A": "不了解", "score": 2}, {"B": "了解基础", "score": 5}, {"C": "比较了解", "score": 7}, {"D": "非常了解", "score": 10}]},
    {"q": 14, "question": "您是否接受本金损失？",
     "options": [{"A": "绝不接受", "score": 2}, {"B": "可接受小幅", "score": 5}, {"C": "可接受一定", "score": 7}, {"D": "完全接受", "score": 10}]},
    {"q": 15, "question": "您的投资信息来源？",
     "options": [{"A": "朋友推荐", "score": 3}, {"B": "银行/理财顾问", "score": 5}, {"C": "财经媒体", "score": 7}, {"D": "自己研究", "score": 10}]},
    {"q": 16, "question": "近三年您的投资平均收益？",
     "options": [{"A": "亏损", "score": 3}, {"B": "持平", "score": 5}, {"C": "盈利5%-15%", "score": 7}, {"D": "盈利15%以上", "score": 10}]},
]


class RiskService:
    """风险评估服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.cache = ProfileCache()
        self.long_term = LongTermMemory(db)

    def get_questionnaire(self) -> List[QuestionnaireItem]:
        """获取风评问卷"""
        return [QuestionnaireItem(**item) for item in QUESTIONNAIRE]

    async def submit_assessment(self, customer_id: int, answers: List[AssessmentAnswer]) -> AssessmentResult:
        """提交风评答卷，计算风险等级"""
        # 验证客户存在
        profile_stmt = select(FinCustomerProfile).where(FinCustomerProfile.customer_id == customer_id)
        result = await self.db.execute(profile_stmt)
        profile = result.scalar_one_or_none()

        # 计算总分
        total = 0
        score_by_question: dict[int, int] = {}
        question_map = {q["q"]: q for q in QUESTIONNAIRE}
        answer_detail = []
        for ans in answers:
            question = question_map.get(ans.q)
            if question:
                for opt in question["options"]:
                    if ans.a in opt:
                        score = opt["score"]
                        total += score
                        score_by_question[ans.q] = score
                        answer_detail.append({"q": ans.q, "a": ans.a, "score": score})
                        break

        # 等级判定：将问卷原始分（16题，约34-160分）归一化到0-100，使用标准阈值
        # 最小可能分 ≈ 34（每题最低2-3分），最大可能分 ≈ 160（每题满分10分）
        QUESTIONNAIRE_MIN = 34
        QUESTIONNAIRE_MAX = 160
        normalized = round((total - QUESTIONNAIRE_MIN) / (QUESTIONNAIRE_MAX - QUESTIONNAIRE_MIN) * 100)
        normalized = max(0, min(100, normalized))
        risk_level, risk_level_name = map_score_to_risk_level(normalized)

        valid_until = date.today() + timedelta(days=365)

        # 保存评估记录
        assessment = RiskAssessment(
            customer_id=customer_id,
            assessment_date=date.today(),
            total_score=normalized,
            risk_level=risk_level,
            answers={"details": answer_detail},
            assessor_type="AI评估",
            valid_until=valid_until,
        )
        self.db.add(assessment)

        # 更新画像
        if profile:
            profile.risk_level = risk_level
            profile.risk_score = normalized
            profile.update_time = datetime.now()
        else:
            profile = FinCustomerProfile(
                customer_id=customer_id,
                risk_level=risk_level,
                risk_score=normalized,
                confidence_score=0.9,
            )
            self.db.add(profile)

        await self.db.flush()
        await self._upsert_questionnaire_risk_tag(customer_id, risk_level_name, valid_until)
        await self.long_term.archive_rating_record(
            customer_id=customer_id,
            dimension_scores=self._questionnaire_dimension_scores(score_by_question),
            total_score=normalized,
            risk_level=risk_level,
            circuit_breakers=[],
            trigger_type="manual",
        )
        await self.db.flush()
        await self.cache.invalidate(customer_id)
        await self.db.commit()
        try:
            await sync_risk_level(customer_id, risk_level)
        except Exception as exc:
            # Graph synchronization is eventual; questionnaire persistence remains authoritative.
            import logging
            logging.getLogger(__name__).warning("Neo4j risk-level sync failed for customer %s: %s", customer_id, exc)

        return AssessmentResult(
            customer_id=customer_id,
            total_score=normalized,
            risk_level=risk_level,
            valid_until=valid_until,
        )

    async def _upsert_questionnaire_risk_tag(self, customer_id: int, risk_level: str, valid_until: date) -> None:
        stmt = select(CustomerTag).where(
            CustomerTag.customer_id == customer_id,
            CustomerTag.tag_name == "risk_preference",
        )
        tag = (await self.db.execute(stmt)).scalar_one_or_none()
        if tag:
            tag.tag_value = risk_level
            tag.source = "questionnaire"
            tag.valid_until = valid_until
            tag.update_time = datetime.now()
            return
        self.db.add(CustomerTag(
            customer_id=customer_id,
            tag_name="risk_preference",
            tag_value=risk_level,
            source="questionnaire",
            confidence=1,
            valid_until=valid_until,
        ))

    @staticmethod
    def _questionnaire_dimension_scores(score_by_question: dict[int, int]) -> dict:
        groups = {
            "basic": (1, 2, 7, 10, 11),
            "experience": (3, 8, 13, 15, 16),
            "risk_pref": (4, 5, 6, 9, 12, 14),
            "behavior": (9, 12, 14),
        }
        result = {}
        for name, questions in groups.items():
            answers = [score_by_question[q] for q in questions if q in score_by_question]
            result[name] = {"score": round(sum(answers) / (len(answers) * 10) * 100, 2) if answers else 0}
        return result

    async def check_suitability(self, customer_id: int, product_code: str) -> SuitabilityCheckResult:
        """适当性匹配校验"""
        profile = await self._get_profile(customer_id)
        if not profile or not profile.risk_level:
            raise ProfileNotFound(customer_id)

        # 简化：通过 product_code 匹配产品等级
        # 实际应从产品表查询
        product_level = self._infer_product_level(product_code)
        matched = check_suitability(profile.risk_level, product_level)

        warning = None
        if not matched:
            warning = f"适当性不匹配：客户等级 {profile.risk_level} 不允许购买 {product_level} 等级产品"

        return SuitabilityCheckResult(
            match=matched,
            customer_level=profile.risk_level,
            product_level=product_level,
            warning=warning,
        )

    async def _get_profile(self, customer_id: int):
        stmt = select(FinCustomerProfile).where(FinCustomerProfile.customer_id == customer_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    def _infer_product_level(product_code: str) -> str:
        """通过产品代码推断产品风险等级（Mock实现）"""
        code_prefix = product_code[:2] if len(product_code) >= 2 else ""
        mapping = {"F1": "R1", "F2": "R2", "F3": "R3", "F4": "R4", "F5": "R5"}
        return mapping.get(code_prefix, "R3")
