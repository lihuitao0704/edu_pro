# Financial Multi-Agent Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add shared context, dual safety filtering, trace, feedback, analytics, and queryable session history to the financial multi-agent platform.

**Architecture:** The unified chat API delegates to a `ChatOrchestrator`; it creates `AgentExecutionContext`, invokes the existing router, applies common services, and persists a normalized turn. Business agents retain domain dispatch only. MySQL is the durable system of record and Redis is bounded short-term context storage.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic v2, MySQL, Redis, Vue 3 test suite.

## Global Constraints

- Preserve `/api/chat` normal and SSE compatibility.
- Use JWT-derived actor identity and server-owned session authorization.
- Never persist raw blocked sensitive input in messages or traces.
- Keep platform services outside `app/agent/`.
- Return the existing unified JSON envelope.

---

### Task 1: Shared platform contracts

**Files:** Create `app/common_services/context_manager/models.py`, `app/common_services/orchestration/agent_contract.py`; test `tests/test_platform_contracts.py`.

- [ ] Write failing tests for execution-context defaults and normalized result fields.
- [ ] Implement Pydantic/dataclass contracts for context, entity, safety decision, trace data, and agent result.
- [ ] Run `python -m unittest tests.test_platform_contracts -v` and commit `feat: add platform contracts`.

### Task 2: Context and safety services

**Files:** Create `app/common_services/context_manager/{entity_tracker.py,session_context.py,memory_manager.py}`, `app/common_services/safety_guard/{input_filter.py,output_filter.py,risk_rule.py}`; test `tests/test_context_and_safety.py`.

- [ ] Write failing product-pronoun, PII-block, PII-mask, and guaranteed-return tests.
- [ ] Implement deterministic extraction, Redis-safe fallback, and rule-based filters.
- [ ] Run `python -m unittest tests.test_context_and_safety -v` and commit `feat: add shared context and safety`.

### Task 3: Durable data and platform services

**Files:** Modify `app/model/entities.py`; create trace, feedback, analytics services; test `tests/test_platform_persistence.py`.

- [ ] Write failing table-model and metric aggregation tests.
- [ ] Add session/message/entity/feedback/trace tables plus service APIs.
- [ ] Run persistence tests and commit `feat: add platform persistence services`.

### Task 4: Unified orchestration

**Files:** Create `app/common_services/orchestration/{chat_orchestrator.py,response_enhancer.py}`; modify `app/api/unified_chat.py`; test `tests/test_chat_orchestration.py`.

- [ ] Write failing tests for blocked input, entity carryover, enhancement, actor-owned archive, normal and SSE paths.
- [ ] Integrate the orchestrator around existing `RouterAgent` without putting common logic in agents.
- [ ] Run orchestration and regression tests; commit `feat: orchestrate shared agent capabilities`.

### Task 5: Feedback, analytics, and trace APIs

**Files:** Create `app/api/{feedback.py,analytics.py}`; modify `main.py`; test `tests/test_platform_apis.py`.

- [ ] Write failing authorization and response-envelope tests.
- [ ] Implement owner-scoped feedback/history and privileged analytics/trace endpoints.
- [ ] Run API and frontend regression suites; commit `feat: expose platform feedback analytics and traces`.
