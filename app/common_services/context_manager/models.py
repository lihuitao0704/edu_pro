from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class AgentExecutionContext:
    trace_id: str
    session_id: str
    actor_id: int
    actor_role: str
    message: str
    entities: dict[str, Any] = field(default_factory=dict)
    short_memory: list[dict[str, Any]] = field(default_factory=list)
    session_context: dict[str, Any] = field(default_factory=dict)
    summary: str | None = None
    request_time: datetime = field(default_factory=datetime.now)


@dataclass
class AgentResult:
    reply: str
    intent: str
    agent_name: str
    confidence: float = 0.0
    data: dict[str, Any] | None = None
    source_count: int = 0
    fallback_used: bool = False
    suggested_questions: list[str] = field(default_factory=list)


@dataclass
class SafetyDecision:
    blocked: bool = False
    sanitized_text: str = ""
    user_message: str = ""
    matched_rules: list[str] = field(default_factory=list)
