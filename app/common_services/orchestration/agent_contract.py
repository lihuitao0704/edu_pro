from typing import Protocol

from app.common_services.context_manager.models import AgentExecutionContext, AgentResult


class FinancialAgent(Protocol):
    name: str

    async def run(self, context: AgentExecutionContext) -> AgentResult:
        ...
