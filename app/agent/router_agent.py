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

from app.model.route_decision import RouteDecision, RoutePlan, RouteTask
from app.service.intent_service import get_intent_service
from app.service.route_validator import get_route_validator
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
    "clarification": "router",
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
        context: Optional[dict] = None,
        route_decision: RouteDecision | None = None,
        route_plan: RoutePlan | None = None,
    ) -> UnifiedChatResponse:
        """
        统一路由入口

        流程：
        0. 风控预检（C4联动）— 有预警客户的敏感操作强制走客服Agent
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
        if context and context.get("entities", {}).get("product_name"):
            product_name = context["entities"]["product_name"]
            message = f"{message}\n\n[平台上下文：当前产品={product_name}]"

        if not session_id:
            session_id = uuid.uuid4().hex

        # ── Step 0: 风控预检（C4联动）──
        # 对于有预警的客户，敏感操作强制走客服Agent路径，确保风控提示能触达
        risk_intercept = await self._risk_precheck(message, user_id)
        if risk_intercept:
            logger.info(
                f"风控预检拦截 | user={user_id} | msg={message[:50]}... | "
                f"risk_flag={risk_intercept.get('risk_flag')}"
            )
            # 强制走客服Agent，由客服Agent的C4联动逻辑处理风控提示
            result = await self._dispatch_customer_service(message, session_id, user_id)
            return UnifiedChatResponse(
                intent="risk_intercepted",
                agent="customer_service",
                confidence=1.0,
                session_id=session_id,
                reply=result.get("reply", ""),
                data=result.get("data"),
            )

        # ── Step 1: 生成一次顶层计划；单任务沿用原执行链，多任务安全汇总 ──
        import re
        if route_plan is None:
            if route_decision is not None:
                route_plan = RoutePlan(
                    original_message=message,
                    tasks=[route_decision],
                    execution_mode="single",
                    decision_source=route_decision.decision_source,
                )
            else:
                route_plan = await self.intent_service.plan_route(
                    message,
                    user_role=user_role,
                    context=context,
                )
        if route_plan.is_multi_intent:
            return await self._execute_route_plan(
                route_plan,
                session_id=session_id,
                user_id=user_id,
                user_role=user_role,
                context=context,
            )

        decision = route_plan.tasks[0]
        decision = get_route_validator().validate(
            decision,
            user_role=user_role,
            context=context,
        )

        if decision.blocked:
            return UnifiedChatResponse(
                intent="access_denied",
                agent="router",
                confidence=decision.confidence,
                session_id=session_id,
                reply=decision.block_reason or "当前身份无权使用该能力。",
                data={"route_decision": decision.model_dump(mode="json")},
            )

        if decision.needs_clarification:
            return UnifiedChatResponse(
                intent="clarification",
                agent="router",
                confidence=decision.confidence,
                session_id=session_id,
                reply=decision.clarification_question or "请补充说明你的具体目标。",
                data={
                    "route_decision": decision.model_dump(mode="json"),
                    "clarification": {
                        "question": decision.clarification_question,
                        "choices": decision.clarification_choices,
                    },
                },
            )

        intent = decision.intent
        confidence = decision.confidence
        params = decision.legacy_params()
        # ── 从消息中直接提取客户ID ──
        _id = re.search(
            r'客户(?:ID|编号)\s*(?:是|为|=|[:：])?\s*(\d+)',
            message,
            re.I,
        )
        if _id:
            params["customer_id"] = int(_id.group(1))

        agent_name = decision.target_agent

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

        # 客户本人咨询投资时，使用已认证身份作为可信客户上下文。
        # 员工角色必须显式选择或解析客户，不能误用自己的员工账号。
        if agent_name == "advisor" and not customer_id and user_role == "客户":
            customer_id = user_id

        # ── Step 3: 分发给业务 Agent ──
        try:
            if agent_name == "customer_service":
                result = await self._dispatch_customer_service(
                    message, session_id, user_id, decision
                )
            elif agent_name == "advisor":
                result = await self._dispatch_advisor(
                    message, session_id, user_id, customer_id, user_role
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
                data={
                    "error": str(e),
                    "route_decision": decision.model_dump(mode="json"),
                },
            )

        # ── Step 4: 聚合为统一响应 ──
        reply = result.get("reply", "") if isinstance(result, dict) else str(result)
        agent_data = result.get("data") if isinstance(result, dict) else None
        # 如果 result 本身就是 data（如 operator），则整个作为 data
        if isinstance(result, dict) and "reply" not in result:
            reply = ""
            agent_data = result

        response_data = dict(agent_data or {}) if isinstance(agent_data, dict) else {}
        response_data["route_decision"] = decision.model_dump(mode="json")
        return UnifiedChatResponse(
            intent=intent,
            agent=agent_name,
            confidence=confidence,
            session_id=session_id,
            reply=reply,
            data=response_data,
        )

    async def _execute_route_plan(
        self,
        plan: RoutePlan,
        *,
        session_id: str,
        user_id: int,
        user_role: str,
        context: dict | None,
    ) -> UnifiedChatResponse:
        """Execute validated read-only subtasks sequentially and aggregate safely."""
        task_results: list[dict] = []
        sections: list[str] = []
        merged_data: dict = {}

        for index, raw_decision in enumerate(plan.tasks, start=1):
            decision = get_route_validator().validate(
                raw_decision,
                user_role=user_role,
                context=context,
            )
            title = f"{decision.task.value} · {decision.domain.value}"

            if decision.task == RouteTask.EXECUTE:
                reply = (
                    "该子任务会修改业务数据。为避免复合指令误操作，请将这项操作"
                    "单独发送，系统会展示参数并要求二次确认。"
                )
                task_results.append(
                    {
                        "index": index,
                        "status": "requires_separate_confirmation",
                        "reply": reply,
                        "route_decision": decision.model_dump(mode="json"),
                    }
                )
                sections.append(f"### {index}. {title}\n{reply}")
                continue

            response = await self.route(
                decision.request_text,
                session_id=session_id,
                user_id=user_id,
                user_role=user_role,
                context=context,
                route_decision=decision,
            )
            status = (
                "blocked"
                if response.intent == "access_denied"
                else "needs_clarification"
                if response.intent == "clarification"
                else "completed"
            )
            task_results.append(
                {
                    "index": index,
                    "status": status,
                    "intent": response.intent,
                    "agent": response.agent,
                    "reply": response.reply,
                    "data": response.data,
                    "route_decision": decision.model_dump(mode="json"),
                }
            )
            sections.append(f"### {index}. {title}\n{response.reply}")

            if isinstance(response.data, dict):
                for key in (
                    "recommendations",
                    "allocation",
                    "customer_profile",
                    "query_result",
                    "sql",
                    "safety",
                    "truncated",
                ):
                    if key in response.data and key not in merged_data:
                        merged_data[key] = response.data[key]

        merged_data.update(
            {
                "route_plan": plan.model_dump(mode="json"),
                "task_results": task_results,
                "partial_success": any(
                    item["status"] != "completed" for item in task_results
                ),
            }
        )
        confidence = min(
            (task.confidence for task in plan.tasks),
            default=0.0,
        )
        return UnifiedChatResponse(
            intent="multi_intent",
            agent="router_supervisor",
            confidence=confidence,
            session_id=session_id,
            reply="\n\n".join(sections),
            data=merged_data,
        )

    # ═══════════════════════════════════════════════════════════════
    # 分发方法（每个方法内部调用现有业务Agent，不做重复实现）
    # ═══════════════════════════════════════════════════════════════

    async def _dispatch_customer_service(
        self,
        message: str,
        session_id: str,
        user_id: int,
        route_decision: RouteDecision | None = None,
    ) -> dict:
        """分发到客服 Agent"""
        from app.agent.customer_agent import get_customer_service_agent
        agent = get_customer_service_agent(self.db)
        response = await agent.handle(
            session_id,
            user_id,
            message,
            actor_id=user_id,
            route_task=route_decision.task.value if route_decision else None,
            route_domain=route_decision.domain.value if route_decision else None,
        )
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
        user_role: str = "",
    ) -> dict:
        """分发到投顾 Agent"""
        from app.agent.advisor_agent import AdvisorAgent
        agent = AdvisorAgent(self.db, session_id, actor_id=user_id)
        # 如果消息中没有 customer_id 上下文，自动注入
        enhanced_message = message
        if customer_id:
            enhanced_message = message  # AdvisorAgent 内部会注入 customer_id
        result = await agent.execute(
            enhanced_message,
            customer_id=customer_id,
            audience_role=user_role,
        )
        return {
            "reply": result.get("reply", ""),
            "data": {
                "recommendations": result.get("recommendations", []),
                "allocation": result.get("allocation"),
                "customer_profile": result.get("customer_profile"),
                "holdings_analysis": result.get("holdings_analysis"),
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

    # ═══════════════════════════════════════════════════════════════
    # C4 风控预检
    # ═══════════════════════════════════════════════════════════════

    # 敏感操作关键词（与客服Agent的 SENSITIVE_KEYWORDS 保持一致）
    _SENSITIVE_PATTERNS = [
        "大额转账", "转账", "汇款", "大额",
        "赎回", "取出", "提现",
        "大额申购", "大额买入", "大笔买入",
    ]

    async def _risk_precheck(self, message: str, user_id: int) -> Optional[dict]:
        """
        C4 风控预检：在路由前检查是否需要拦截

        拦截条件（同时满足）：
        1. 用户角色为客户（员工不拦截）
        2. 消息包含敏感操作关键词
        3. 客户的 risk_flag 不为 normal（即 warning 或 high）

        Returns:
            命中时返回 {"risk_flag": "high"|"warning"}，未命中返回 None
        """
        # 1. 检查消息是否包含敏感关键词
        has_sensitive = any(kw in message for kw in self._SENSITIVE_PATTERNS)
        if not has_sensitive:
            return None

        # 2. 查询客户 risk_flag
        try:
            from sqlalchemy import text
            row = await self.db.execute(
                text(
                    "SELECT risk_flag FROM fin_customer_profile "
                    "WHERE customer_id = :cid"
                ),
                {"cid": user_id},
            )
            profile_row = row.first()
            if not profile_row:
                return None
            risk_flag = profile_row[0]
            # 只有 warning / high 才拦截
            if risk_flag in ("warning", "high"):
                return {"risk_flag": risk_flag}
        except Exception as e:
            logger.debug(f"风控预检查询失败(非阻断): {e}")

        return None
