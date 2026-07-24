"""NLP 服务 — 投顾产品智能解读
对产品进行自然语言处理：生成产品介绍、产品优势等
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.security.authorization import require_roles
from app.tool.llm_tool import get_llm_tool
from app.utils.response import success, error
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


class ProductInsightRequest(BaseModel):
    """产品洞察请求"""
    product_name: str = Field(..., description="产品名称")
    product_type: str = Field("", description="产品类型（如 货币基金/债券基金/混合基金/股票基金/私募产品）")
    risk_level: str = Field("", description="风险等级（R1-R5）")
    expected_return: float | None = Field(None, description="预期年化收益率")
    rationale: str = Field("", description="推荐理由")
    customer_risk_level: str = Field("", description="客户风险等级（C1-C5）")
    insight_type: str = Field("intro", description="洞察类型：intro(产品介绍) | advantage(产品优势) | brief(简要总结)")


# ---------- 提示词模板 ----------

_INTRO_SYSTEM = """你是一位资深金融分析师，擅长将复杂的金融产品转化为通俗易懂的介绍。
请基于提供的产品信息，撰写一段专业但易读的产品介绍。
要求：
1. 语言亲切，避免生硬术语堆砌
2. 点出产品类型、风险定位和适合的投资者画像
3. 控制在 120-180 字之间
4. 不要出现任何投资建议或承诺收益字样"""

_ADVANTAGE_SYSTEM = """你是一位资深金融分析师。
请基于产品信息，从 3-4 个维度提炼该产品的核心优势。
输出格式：使用 "• " 开头的列表项，每项 1-2 句话。
要求：
1. 突出差异化特征（如流动性、风险控制、收益潜力、管理方式）
2. 用数据或事实支撑（如预期收益区间、风险等级含义）
3. 避免夸大宣传，保持客观专业
4. 总字数控制在 150-220 字"""

_BRIEF_SYSTEM = """你是一位资深金融分析师。
请用 1-2 句话高度凝练地概括该产品的核心特点与适用场景。
要求：简洁、准确、专业，控制在 60 字以内。"""


def _format_product_context(req: ProductInsightRequest) -> str:
    """构造产品信息上下文"""
    lines = [
        f"产品名称：{req.product_name}",
    ]
    if req.product_type:
        lines.append(f"产品类型：{req.product_type}")
    if req.risk_level:
        risk_desc = {
            "R1": "低风险（保守型）", "R2": "中低风险（稳健型）",
            "R3": "中风险（平衡型）", "R4": "中高风险（进取型）", "R5": "高风险（激进型）",
        }.get(req.risk_level, req.risk_level)
        lines.append(f"风险等级：{req.risk_level}（{risk_desc}）")
    if req.expected_return is not None:
        lines.append(f"预期年化收益：{req.expected_return}%")
    if req.rationale:
        lines.append(f"推荐理由：{req.rationale}")
    if req.customer_risk_level:
        lines.append(f"匹配客户等级：{req.customer_risk_level}")
    return "\n".join(lines)


@router.post("/product-insight")
async def generate_product_insight(
    req: ProductInsightRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_roles("理财顾问", "客户经理", "风控专员", "管理员", "客户")),
):
    """
    基于产品信息生成 NLP 洞察（产品介绍 / 产品优势 / 简要总结）

    - intro: 120-180 字的产品介绍段落
    - advantage: 3-4 条核心优势列表
    - brief: 60 字以内的简要总结
    """
    system_prompt = {
        "intro": _INTRO_SYSTEM,
        "advantage": _ADVANTAGE_SYSTEM,
        "brief": _BRIEF_SYSTEM,
    }.get(req.insight_type, _INTRO_SYSTEM)

    product_context = _format_product_context(req)
    user_prompt = f"请基于以下产品信息，生成【{'产品介绍' if req.insight_type == 'intro' else '产品优势' if req.insight_type == 'advantage' else '简要总结'}】：\n\n{product_context}"

    try:
        llm = get_llm_tool()
        content = await llm.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=512,
        )
        return success(data={
            "insight_type": req.insight_type,
            "product_name": req.product_name,
            "content": content,
        })
    except Exception as e:
        logger.error(f"NLP 产品洞察生成失败: {e}", exc_info=True)
        # 降级：基于产品信息的模板生成
        fallback = _fallback_insight(req)
        return success(data={
            "insight_type": req.insight_type,
            "product_name": req.product_name,
            "content": fallback,
            "fallback": True,
        })


def _fallback_insight(req: ProductInsightRequest) -> str:
    """当 LLM 不可用时，基于模板生成降级内容"""
    risk_desc = {
        "R1": "低风险稳健之选", "R2": "中低风险安心配置",
        "R3": "中风险平衡之选", "R4": "中高风险进取配置", "R5": "高风险高收益之选",
    }.get(req.risk_level, "")

    if req.insight_type == "advantage":
        lines = []
        if req.product_type:
            lines.append(f"• {req.product_type}品类，定位清晰，便于资产配置组合构建")
        if req.risk_level:
            lines.append(f"• 风险等级 {req.risk_level}（{risk_desc}），匹配相应风险承受能力客户")
        if req.expected_return is not None:
            lines.append(f"• 预期年化收益 {req.expected_return}%，为资产增值提供参考锚点")
        if req.rationale:
            lines.append(f"• 推荐理由：{req.rationale}")
        if not lines:
            lines.append(f"• {req.product_name}是一款经过专业筛选的金融产品，供参考配置")
        return "\n".join(lines)
    elif req.insight_type == "brief":
        return f"{req.product_name}：{req.product_type or '金融产品'}，{risk_desc or '风险适配'}，预期收益 {req.expected_return or '—'}%"
    else:  # intro
        parts = [f"{req.product_name}"]
        if req.product_type:
            parts.append(f"属于{req.product_type}品类")
        if req.risk_level:
            parts.append(f"风险等级为{req.risk_level}（{risk_desc}）")
        if req.expected_return is not None:
            parts.append(f"预期年化收益为 {req.expected_return}%")
        base = "，".join(parts) + "。"
        if req.rationale:
            base += f"推荐理由：{req.rationale}"
        return base
