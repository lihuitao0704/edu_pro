"""Top-level routing decision contract for the unified wealth assistant."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RouteTask(str, Enum):
    CHAT = "CHAT"
    FAQ = "FAQ"
    QUERY = "QUERY"
    ANALYZE = "ANALYZE"
    RECOMMEND = "RECOMMEND"
    EXECUTE = "EXECUTE"
    RISK_CHECK = "RISK_CHECK"
    TRANSFER_HUMAN = "TRANSFER_HUMAN"
    UNKNOWN = "UNKNOWN"


class RouteDomain(str, Enum):
    GENERAL = "GENERAL"
    PRODUCT = "PRODUCT"
    HOLDING = "HOLDING"
    TRANSACTION = "TRANSACTION"
    CUSTOMER = "CUSTOMER"
    WORK_ORDER = "WORK_ORDER"
    RISK = "RISK"
    POLICY = "POLICY"
    UNKNOWN = "UNKNOWN"


class RouteDecision(BaseModel):
    """A single, auditable decision shared by the API, orchestrator and router."""

    request_text: str = Field(default="", description="The sub-request this decision routes")
    intent: str = Field(description="Legacy top-level intent exposed by the API")
    task: RouteTask
    domain: RouteDomain
    target_agent: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    decision_source: str = Field(default="rule")
    alternatives: list[str] = Field(default_factory=list)
    entities: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str | None = None
    clarification_choices: list[str] = Field(default_factory=list)
    requires_confirmation: bool = False
    blocked: bool = False
    block_reason: str | None = None
    validation_notes: list[str] = Field(default_factory=list)

    def legacy_params(self) -> dict[str, Any]:
        keys = (
            "customer_name",
            "customer_id",
            "product_name",
            "amount",
            "transaction_type",
        )
        return {key: self.entities.get(key) for key in keys}


class RoutePlan(BaseModel):
    """A bounded plan for one or more independently validated user requests."""

    original_message: str
    tasks: list[RouteDecision] = Field(default_factory=list)
    execution_mode: str = Field(default="single")
    decision_source: str = Field(default="single")

    @property
    def is_multi_intent(self) -> bool:
        return len(self.tasks) > 1
