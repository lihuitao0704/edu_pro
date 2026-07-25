"""Whitelist conversion from analytics rows to safe cross-Agent insights."""

from __future__ import annotations

from app.service.agent_event_service import AgentDomainEvent


def extract_analytics_insights(query: str, rows: list[dict]) -> list[AgentDomainEvent]:
    """Emit only verifiable customer P&L or high-frequency facts.

    Free-form NL2SQL explanations never become Agent inputs. The source rows
    must identify one customer and contain the numeric evidence used below.
    """
    if not isinstance(rows, list):
        return []
    events: list[AgentDomainEvent] = []
    for row in rows:
        customer_id = row.get("customer_id")
        if not isinstance(customer_id, int) or customer_id <= 0:
            continue

        profit_ratio = row.get("profit_ratio")
        if isinstance(profit_ratio, (int, float)) and profit_ratio <= -0.10:
            events.append(
                AgentDomainEvent.create(
                    "analytics_insight",
                    "analytics",
                    customer_id,
                    {
                        "kind": "pnl_drawdown",
                        "profit_ratio": float(profit_ratio),
                        "period_days": int(row.get("period_days") or 0),
                        "query": query[:200],
                    },
                )
            )
            continue

        weekly_count = row.get("weekly_count")
        weekly_total = row.get("weekly_total")
        if isinstance(weekly_count, int) and weekly_count >= 10 and isinstance(weekly_total, (int, float)):
            events.append(
                AgentDomainEvent.create(
                    "analytics_insight",
                    "analytics",
                    customer_id,
                    {
                        "kind": "trading_frequency",
                        "weekly_count": weekly_count,
                        "weekly_total": float(weekly_total),
                        "query": query[:200],
                    },
                )
            )
    return events
