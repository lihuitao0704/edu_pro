from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TraceRecord:
    trace_id: str
    session_id: str
    user_id: int
    masked_input: str
    status: str = "running"
    masked_output: str = ""
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: datetime | None = None
    spans: list[dict] = field(default_factory=list)

    def finish(self, status: str, masked_output: str) -> None:
        self.status = status
        self.masked_output = masked_output
        self.ended_at = datetime.now()

    @property
    def total_latency_ms(self) -> int:
        end = self.ended_at or datetime.now()
        return int((end - self.started_at).total_seconds() * 1000)

    def add_span(self, component_name: str, status: str = "ok", token_input: int = 0, token_output: int = 0) -> None:
        self.spans.append({
            "component_name": component_name, "status": status,
            "latency_ms": self.total_latency_ms,
            "token_input": token_input, "token_output": token_output,
        })


class TraceService:
    _records: dict[str, TraceRecord] = {}

    def start(self, trace_id: str, session_id: str, user_id: int, masked_input: str) -> TraceRecord:
        record = TraceRecord(trace_id, session_id, user_id, masked_input)
        self._records[trace_id] = record
        return record

    def get(self, trace_id: str) -> TraceRecord | None:
        return self._records.get(trace_id)
