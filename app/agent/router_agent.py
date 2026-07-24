"""
Router Agent — 统一路由层

职责：只做路由，不解决业务问题。
- 理解用户需求 → 意图分类
- 提取关键参数 → 分发给对应业务 Agent
- 聚合响应 → 统一返回

禁止：Router Agent 不包含任何业务逻辑。
所有业务问题由下游 Agent 处理。
"""

import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.service.intent_service import get_intent_service
from app.model.schemas import UnifiedChatResponse
from app.utils.logger import get_logger

logger = get_logger("agent.router")

# 意图 → Agent 名称映射
INTENT_TO_AGENT = {
    "product_faq": "customer_service",
    "chitchat": "customer_service",       # 闲聊自动转客服
    "investment_recommendation": "advisor",
    "risk_control": "risk_monitor",
    "data_analysis": "nl2sql",
    "business_operation": "operator",
}


class RouterAgent:
    """统一路由 Agent — 意图分类 + 分发 + 聚合"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.intent_service = get_intent_service()

    async def route(
        self,
        message: str,
        session_id: str = "",
        user_id: int = 0,
        user_role: str = "客户",
    ) -> UnifiedChatResponse:
        """
        统一路由入口

        流程：
        1. 意图分类（关键词快速通道 + LLM）
        2. 参数提取
        3. 分发给对应业务 Agent
        4. 聚合为统一响应

        Args:
            message: 用户自然语言消息
            session_id: 会话ID
            user_id: 用户ID
            user_role: 用户角色
        """
        if not session_id:
            session_id = uuid.uuid4().hex

        # ── Step 1: 意图分类 ──
        intent, confidence, params = await self.intent_service.classify_router(message)
        agent_name = INTENT_TO_AGENT.get(intent, "customer_service")

        logger.info(
            f"Router分发 | intent={intent} | agent={agent_name} | "
            f"confidence={confidence:.2f} | user={user_id} | msg={message[:50]}..."
        )

        # ── Step 2: 参数补全（从消息中提取 customer_id）──
        customer_id = params.get("customer_id")
        if not customer_id and params.get("customer_name"):
            try:
                from app.tool.graph_query_tool import resolve_customer_id
                customer_id = await resolve_customer_id(params["customer_name"])
            except Exception:
                pass

        # ── Step 3: 分发给业务 Agent ──
        try:
            if agent_name == "customer_service":
                result = await self._dispatch_customer_service(
                    message, session_id, user_id
                )
            elif agent_name == "advisor":
                result = await self._dispatch_advisor(
                    message, session_id, user_id, customer_id
                )
            elif agent_name == "risk_monitor":
                result = await self._dispatch_risk_control(
                    message, user_id, params
                )
            elif agent_name == "nl2sql":
                result = await self._dispatch_data_analysis(
                    message, session_id, user_id
                )
            elif agent_name == "operator":
                result = await self._dispatch_operator(
                    message, session_id, user_id, user_role
                )
            else:
                result = {"reply": f"未知Agent: {agent_name}", "data": None}
        except Exception as e:
            logger.error(f"Agent分发执行失败 [{agent_name}]: {e}", exc_info=True)
            return UnifiedChatResponse(
                intent=intent,
                agent=agent_name,
                confidence=confidence,
                session_id=session_id,
                reply=f"抱歉，{agent_name} 服务暂时不可用，请稍后重试。",
                data={"error": str(e)},
            )

        # ── Step 4: 聚合为统一响应 ──
        reply = result.get("reply", "") if isinstance(result, dict) else str(result)
        agent_data = result.get("data") if isinstance(result, dict) else None
        # 如果 result 本身就是 data（如 operator），则整个作为 data
        if isinstance(result, dict) and "reply" not in result:
            reply = ""
            agent_data = result

        return UnifiedChatResponse(
            intent=intent,
            agent=agent_name,
            confidence=confidence,
            session_id=session_id,
            reply=reply,
            data=agent_data,
        )

    # ═══════════════════════════════════════════════════════════════
    # 分发方法（每个方法内部调用现有业务Agent，不做重复实现）
    # ═══════════════════════════════════════════════════════════════

    async def _dispatch_customer_service(
        self, message: str, session_id: str, user_id: int
    ) -> dict:
        """分发到客服 Agent"""
        from app.agent.customer_agent import get_customer_service_agent
        agent = get_customer_service_agent(self.db)
        response = await agent.handle(session_id, user_id, message)
        return {
            "reply": response.reply,
            "data": {
                "sources": [s.model_dump() for s in response.sources],
                "intent": response.intent,
                "confidence": response.confidence,
            },
        }

    async def _dispatch_advisor(
        self, message: str, session_id: str, user_id: int,
        customer_id: Optional[int] = None,
    ) -> dict:
        """分发到投顾 Agent"""
        from app.agent.advisor_agent import AdvisorAgent
        agent = AdvisorAgent(self.db, session_id)
        # 如果消息中没有 customer_id 上下文，自动注入
        enhanced_message = message
        if customer_id:
            enhanced_message = message  # AdvisorAgent 内部会注入 customer_id
        result = await agent.execute(enhanced_message, customer_id=customer_id)
        return {
            "reply": result.get("reply", ""),
            "data": {
                "recommendations": result.get("recommendations", []),
                "customer_profile": result.get("customer_profile"),
                "reasoning": result.get("reasoning"),
            },
        }

    async def _dispatch_risk_control(
        self, message: str, user_id: int, params: dict
    ) -> dict:
        """分发到风控 Agent"""
        # 风控Agent目前通过 event_bus / risk_monitor_service 运作
        # 对于对话式风控查询，调用 RiskMonitorService
        from app.service.risk_monitor_service import RiskMonitorService

        monitor = RiskMonitorService()
        customer_id = params.get("customer_id")

        if customer_id:
            # 查询该客户的预警列表
            _, alerts = await monitor.get_alerts(
                self.db, customer_id=customer_id, days=30, page_size=10
            )
            return {
                "reply": f"客户 #{customer_id} 近30天有 {len(alerts)} 条预警记录。",
                "data": {
                    "customer_id": customer_id,
                    "alert_count": len(alerts),
                    "alerts": alerts[:5] if alerts else [],
                },
            }

        return {
            "reply": "风控监测系统运行中。请指定客户ID查询预警，或通过业务操作触发风控检测。",
            "data": {"status": "operational"},
        }

    async def _dispatch_data_analysis(
        self, message: str, session_id: str, user_id: int
    ) -> dict:
        """分发到数据分析 Agent (NL2SQL)"""
        from app.service.nl2sql_service import NL2SQLService

        service = NL2SQLService()
        result = service.query_and_explain(message, user_id=user_id)

        if result.get("success"):
            return {
                "reply": result.get("explanation", ""),
                "data": {
                    "sql": result.get("sql"),
                    "query_result": result.get("query_result"),
                    "safety": result.get("safety"),
                    "truncated": result.get("truncated", False),
                    "timing": result.get("timing"),
                },
            }
        else:
            return {
                "reply": result.get("error", "数据分析查询失败"),
                "data": {
                    "sql": result.get("sql"),
                    "error": result.get("error"),
                    "rejected": result.get("rejected", False),
                },
            }

    async def _dispatch_operator(
        self, message: str, session_id: str, user_id: int, user_role: str
    ) -> dict:
        """分发到业务操作 Agent"""
        from app.agent.operator_agent import operator_chat

        result = await operator_chat(
            message=message,
            session_id=session_id,
            user_id=user_id,
            user_role=user_role,
        )
        return {
            "reply": result.get("reply", ""),
            "data": {
                "action": result.get("action"),
                "params": result.get("params", {}),
                "status": result.get("status", "ok"),
            },
        }
