# Financial Multi-Agent Platform Design

## Goal

Evolve the existing FastAPI financial assistant into a multi-agent platform in
which context, safety, traceability, feedback, and analytics are shared
services rather than responsibilities of individual agents.

## Boundaries

`ChatOrchestrator` owns the request lifecycle: session ownership, input
inspection, context construction, router dispatch, response enhancement,
output inspection, durable turn persistence, and trace completion. Existing
business agents remain domain adapters and continue to be selected by
`RouterAgent`.

`AgentExecutionContext` is the single object shared across the route. It
contains actor identity, server-owned session ID, sanitized message, entity
state, short memory, session summary, and trace ID. Agents must not write
conversation archives, safety records, or trace rows themselves.

## Context

`EntityTracker` uses explicit entity references and product-name extraction;
it resolves pronouns such as `它` from the latest product entity held in the
session context. `MemoryManager` keeps a bounded Redis short memory and
persists the context JSON and summary in the session record. Long-term chat
history remains in MySQL.

## Safety

Input inspection blocks passwords and masks detected identity-card, bank-card,
and telephone strings before routing. Blocked content is neither sent to an
agent nor persisted as raw chat/trace content. Output inspection rejects
guaranteed-return language and appends a suitability notice for investment
recommendations.

## Persistence and observability

MySQL tables hold sessions, messages, entities, feedback, request traces,
trace spans, and daily metrics. The existing `conversation_archive` remains
the compatibility history table. The first delivery creates all new ORM tables
through the project’s current metadata initialization and exposes API-level
services. Event aggregation is represented by an in-process service now and
can later move to a durable outbox consumer without changing API contracts.

## APIs

- `POST /api/chat`: existing interface, enriched with entity/context metadata
  while retaining `UnifiedChatResponse` fields.
- `POST /api/chat/customer/feedback`: authenticated owner feedback.
- `GET /api/chat/history`: owner-scoped history with optional session, time,
  intent, and agent filters.
- `GET /api/analytics/chat/stats`: role-protected aggregate metrics.
- `GET /api/analytics/chat/traces/{trace_id}`: role-protected masked trace.

All return the current `{code, message, data, trace_id}` envelope.

## Security constraints

- A session is reusable only by its authenticated owner.
- User-provided IDs and roles are never trusted.
- Trace and safety records retain masked values only.
- Customers may access only their feedback, sessions, histories, and traces.

## Delivery order

1. Shared models, context, safety, trace and orchestrator contracts.
2. Integrate both normal and SSE unified-chat routes.
3. Add session/message/entity/feedback/trace models and APIs.
4. Add analytics aggregation and management endpoints.
5. Add API, isolation, safety, context, trace, and regression tests.
