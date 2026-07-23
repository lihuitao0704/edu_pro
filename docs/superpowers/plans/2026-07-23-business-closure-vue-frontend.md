# Financial Agent Business Closure and Vue Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the authenticated customer/advisor/operations/risk/work-order data flow and deliver a Vue 3 management frontend that consumes the real FastAPI APIs.

**Architecture:** Preserve the current FastAPI, SQLAlchemy, Agent, RAG, Neo4j, Milvus, Redis, and MySQL layers. Add small orchestration and authorization boundaries instead of redesigning existing Agents. Create a separate `frontend/` Vue 3 application with a typed API client, role-aware routing, and SSE chat transport.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, Pydantic 2, Redis Pub/Sub, pytest/unittest, Vue 3, TypeScript, Vite, Element Plus, Pinia, Vue Router, ECharts.

## Global Constraints

- Do not overwrite the existing `static/` or `streamlit_app.py` prototypes.
- All business pages must call real APIs; mock data is allowed only in deterministic seed scripts and automated tests.
- Existing API paths remain backward-compatible.
- Production code changes follow RED → GREEN → REFACTOR.
- Existing user change in `ARCHITECTURE.html` must remain untouched.

---

### Task 1: Authentication and role enforcement

**Files:**
- Create: `app/security/passwords.py`
- Create: `app/security/authorization.py`
- Modify: `app/api/auth.py`
- Modify: `app/api/chat.py`
- Test: `tests/test_auth_and_rbac.py`

**Interfaces:**
- Produces: `hash_password(password: str) -> str`
- Produces: `verify_password(password: str, encoded: str) -> bool`
- Produces: `require_roles(*roles: str)` FastAPI dependency
- Produces: `POST /api/auth/register`

- [ ] Write tests proving login uses `employee_role`, invalid passwords are rejected, registration hashes passwords, and the operator role comes from JWT state.
- [ ] Run `python -m unittest tests.test_auth_and_rbac -v`; expect failures for missing password and role helpers.
- [ ] Implement PBKDF2 password hashing, registration, corrected login SQL, and request-state role enforcement.
- [ ] Run the authentication tests; expect all cases to pass.

### Task 2: Transaction-to-risk-to-work-order orchestration

**Files:**
- Create: `app/service/transaction_flow_service.py`
- Modify: `app/model/schemas.py`
- Modify: `app/api/risk.py`
- Modify: `app/api/operations/purchase.py`
- Modify: `app/api/operations/redeem.py`
- Modify: `app/api/operations/transfer.py`
- Modify: `app/service/risk_monitor_service.py`
- Test: `tests/test_transaction_flow.py`

**Interfaces:**
- Produces: `TransactionFlowService.enrich_context(db, event) -> dict`
- Produces: `TransactionFlowService.monitor(db, event) -> dict`
- `TransactionEvent` preserves supported extended AML context fields.
- Successful business operations return `data.risk_monitor`.

- [ ] Write tests showing extended AML fields survive validation, a risky operation creates an alert/work order, and resolving an alert updates its linked work order and pending set.
- [ ] Run `python -m unittest tests.test_transaction_flow -v`; expect the flow assertions to fail.
- [ ] Extract the shared monitor orchestration, enrich events from customer and transaction history, and call it from purchase/redeem/transfer.
- [ ] Synchronize alert handling with work-order status and Redis pending state.
- [ ] Run transaction flow and existing risk tests; expect all cases to pass.

### Task 3: Read APIs required by role workspaces

**Files:**
- Create: `app/api/customers.py`
- Modify: `app/api/operations/workorder.py`
- Modify: `app/api/knowledge.py`
- Modify: `app/api/profile.py`
- Modify: `main.py`
- Test: `tests/test_workspace_apis.py`

**Interfaces:**
- Produces: `GET /api/customers`
- Produces: `GET /api/customers/{customer_id}`
- Produces: `GET /api/customers/{customer_id}/holdings`
- Produces: work-order list/detail/handle APIs
- Produces: `GET /api/knowledge/status`

- [ ] Write route and response-shape tests for customer search, holdings, work orders, knowledge status, and `risk_flag`.
- [ ] Run `python -m unittest tests.test_workspace_apis -v`; expect missing-route failures.
- [ ] Implement read APIs with pagination and consistent response envelopes.
- [ ] Apply role dependencies to employee-only endpoints.
- [ ] Run workspace API tests and inspect `/openapi.json`.

### Task 4: SSE chat transport

**Files:**
- Create: `app/utils/sse.py`
- Modify: `app/api/chat.py`
- Modify: `app/api/advisor.py`
- Test: `tests/test_sse_transport.py`

**Interfaces:**
- Produces: `POST /api/chat/customer/stream`
- Produces: `POST /api/chat/advisor/stream`
- SSE event types: `meta`, `delta`, `sources`, `done`, `error`.

- [ ] Write generator tests for ordered events and terminal `done`.
- [ ] Run `python -m unittest tests.test_sse_transport -v`; expect missing helper failures.
- [ ] Implement UTF-8-safe chunking and EventSourceResponse endpoints.
- [ ] Run SSE tests and retain existing JSON chat endpoints.

### Task 5: Deterministic demo data

**Files:**
- Create: `scripts/seed_demo_data.py`
- Create: `tests/test_demo_seed.py`

**Interfaces:**
- Produces idempotent upserts for at least 20 customers, 30 products, holdings, assessments, and normal/large/frequent/abnormal transactions.
- Produces five documented test accounts with PBKDF2 hashes.

- [ ] Write tests for generated record counts, role coverage, risk categories, and product categories.
- [ ] Run `python -m unittest tests.test_demo_seed -v`; expect the generator import to fail.
- [ ] Implement deterministic builders and an explicit `--apply` database mode.
- [ ] Run generator tests without mutating the database.
- [ ] Run `python scripts/seed_demo_data.py --apply` once and verify table counts.

### Task 6: Vue 3 application foundation

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/src/main.ts`
- Create: `frontend/src/App.vue`
- Create: `frontend/src/api/http.ts`
- Create: `frontend/src/api/types.ts`
- Create: `frontend/src/stores/auth.ts`
- Create: `frontend/src/router/index.ts`
- Create: `frontend/src/styles/index.css`
- Test: `frontend/src/api/http.test.ts`

**Interfaces:**
- API base defaults to `/api` and is configurable with `VITE_API_BASE_URL`.
- Typed client unwraps `{code,message,data,trace_id}` and raises business errors when `code != 200`.
- Router metadata declares allowed roles.

- [ ] Create client tests for token headers, envelope errors, and 401 logout.
- [ ] Run `npm test`; expect missing client failures.
- [ ] Implement the Vite application shell, API client, auth store, and route guards.
- [ ] Run frontend unit tests and TypeScript build.

### Task 7: Role pages and real API integration

**Files:**
- Create: `frontend/src/layouts/AppLayout.vue`
- Create: `frontend/src/views/LoginView.vue`
- Create: `frontend/src/views/ChatView.vue`
- Create: `frontend/src/views/ProfileView.vue`
- Create: `frontend/src/views/AdvisorWorkspaceView.vue`
- Create: `frontend/src/views/RiskManagementView.vue`
- Create: `frontend/src/views/AnalyticsView.vue`
- Create: `frontend/src/views/KnowledgeView.vue`
- Create: `frontend/src/components/EmptyState.vue`
- Create: `frontend/src/components/LoadingPanel.vue`
- Create: `frontend/src/components/ErrorAlert.vue`

**Interfaces:**
- Login uses `/api/auth/login`.
- Chat consumes customer/advisor SSE and renders Agent name and citations.
- Advisor workspace uses customer search, profile, holdings, recommendations, and allocation.
- Risk page uses alert list/detail/handle and work-order APIs.
- Analytics renders SQL, table, and ECharts visualization.
- Knowledge page uses upload/list/delete/status APIs.

- [ ] Add component tests for loading, empty, error, role menu, and SSE message rendering.
- [ ] Run `npm test`; expect missing-component failures.
- [ ] Implement all seven requested pages with real API calls and accessible responsive states.
- [ ] Run tests and `npm run build`; expect a clean production build.

### Task 8: End-to-end verification and documentation

**Files:**
- Create: `tests/test_business_journeys.py`
- Create: `docs/DEMO.md`
- Modify: `.env.example`

**Interfaces:**
- Covers retail investor, high-net-worth client, advisor, relationship manager, and risk specialist journeys.
- Documents three final demos with accounts, steps, expected evidence, and reset procedure.

- [ ] Write API-level journey tests before final wiring fixes.
- [ ] Run the journey tests and record each failing transition.
- [ ] Fix only failures required for the documented flows.
- [ ] Run backend tests, frontend tests, frontend build, and a final Git diff review.
- [ ] Document changed files, reasons, verification, known environmental dependencies, and three demo scripts.
