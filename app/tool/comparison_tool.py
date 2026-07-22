"""
Comparison Tool — 客户对比分析工具（LangChain BaseTool）

供 Agent 调用：输入两个客户 ID，返回结构化的对比报告 JSON。
内部委托给 ComparisonService 进行业务编排。
"""

from typing import Type
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from langchain_core.tools import BaseTool

from app.service.comparison_service import ComparisonService


class ComparisonToolInput(BaseModel):
    """Comparison Tool 的输入 Schema"""
    customer_id_1: int = Field(description="第一个客户的ID")
    customer_id_2: int = Field(description="第二个客户的ID")


class ComparisonTool(BaseTool):
    """
    客户对比分析工具

    当用户要求对比两个客户的画像、持仓、行业偏好差异时调用此工具。
    内部编排流程：画像获取 → 差异提取 → 共同持仓查询（Neo4j） → 对比报告生成。
    """

    name: str = "compare_customers"
    description: str = (
        "对比两个客户的画像、持仓和行业偏好差异。"
        "输入两个客户ID（整数），返回结构化的对比报告 JSON，包含："
        "两客户基本信息与风险画像、"
        "各维度差异列表（风险等级、风险评分、总资产、投资经验、持仓等）、"
        "共同持仓产品列表（通过 Neo4j 图谱查询）、"
        "行业偏好分布及重叠分析、"
        "人类可读的对比摘要。"
        '当用户要求「对比两个客户」「看有什么不同」「比较张三和李四」时调用此工具。'
    )
    args_schema: Type[BaseModel] = ComparisonToolInput

    # --- 非 Pydantic 字段 ---
    db: AsyncSession = Field(exclude=True)

    def __init__(self, db: AsyncSession, **kwargs):
        super().__init__(db=db, **kwargs)

    async def _arun(self, customer_id_1: int, customer_id_2: int) -> str:
        """
        异步执行客户对比分析并返回 JSON 字符串。

        流程:
        1. ComparisonService.compare() 执行完整编排
        2. 返回 LLM 友好的结构化 JSON
        """
        service = ComparisonService(self.db)

        try:
            report = await service.compare(customer_id_1, customer_id_2)
        except Exception as e:
            import json
            return json.dumps(
                {
                    "error": True,
                    "message": f"客户对比分析失败：{str(e)}",
                    "customer_id_1": customer_id_1,
                    "customer_id_2": customer_id_2,
                },
                ensure_ascii=False,
            )

        import json
        return json.dumps(report, ensure_ascii=False, indent=2, default=str)

    def _run(self, customer_id_1: int, customer_id_2: int) -> str:
        """同步入口（未使用，保留抽象方法实现）"""
        raise NotImplementedError("ComparisonTool 仅支持异步调用，请使用 _arun")
