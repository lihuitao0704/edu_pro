# 六 Agent 联动闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将六类 Agent 的跨域协作收敛为可幂等、可测试的领域事件闭环，并补齐推荐反馈、分析洞察、情绪、到期提醒和可疑上报链路。

**Architecture:** 新增版本化事件信封、MySQL outbox 和消费者幂等记录；Redis 仅作为投递媒介。风控是风险事实唯一生产者，画像持有行为信号，投顾从画像读取策略约束；业务操作在写交易前调用风控预检。

**Tech Stack:** Python 3、FastAPI、SQLAlchemy Async、MySQL、Redis Pub/Sub、Vue 3、pytest。

## Global Constraints

- 仅改智能客服、客户画像、投顾推荐、风控、数据分析、业务操作六类 Agent 的协作。
- 不接入 Kafka、WebSocket、短信、邮件、知识库、ExplanationAgent 或审计自动扫描。
- 盈亏、频率、情绪、拒绝反馈不得自动修改正式风险等级。
- 所有跨 Agent 写入必须带 `event_id` 幂等保护，并携带 `customer_id` 与 `correlation_id`。
- 高风险预检必须在交易流水和余额变更之前终止执行。

---

## File structure

- `app/service/agent_event_service.py`：事件信封创建、outbox 写入、投递与消费幂等。
- `app/service/event_bus.py`：单一事件通道的订阅与按 `event_type` 分发；移除 C1/C2/C4 多播语义。
- `app/service/risk_monitor_service.py`：风险告警的唯一事件出口。
- `app/service/transaction_flow_service.py`：交易预检与后验监控。
- `app/service/profile_service.py`：行为信号持久化、缓存失效和推荐偏好计算。
- `app/service/insight_extractor.py`：将分析结果转换为允许的结构化洞察。
- `app/agent/customer_agent.py`：情绪识别、客服待触达任务读取。
- `app/service/advisor_service.py`：拒绝类型过滤及 P&L 策略约束读取。
- `app/api/advisor.py`、`app/api/chat.py`、`app/api/operations/suspicious_report.py`、`app/service/risk_scheduler.py`：各 Agent 的事件生产入口。
- `app/model/entities.py` 与 `migrations/20260725_six_agent_linkage.sql`：反馈字段、outbox、消费记录。
- `frontend/src/components/RecommendationGrid.vue`、`frontend/src/views/AdvisorWorkspaceView.vue`：推荐拒绝反馈交互。
- `tests/test_agent_event_service.py`、`tests/test_six_agent_linkage.py`：新行为回归测试。

### Task 1: Durable canonical event contract

**Files:**
- Create: `app/service/agent_event_service.py`
- Modify: `app/model/entities.py`
- Create: `migrations/20260725_six_agent_linkage.sql`
- Test: `tests/test_agent_event_service.py`

**Interfaces:**
- Produces `AgentDomainEvent`, `AgentEventService.enqueue(db, event)`, `AgentEventService.consume_once(db, event_id, consumer, handler)`.
- Consumers receive `event_type`, `customer_id`, `correlation_id`, `payload` only through `AgentDomainEvent`.

- [ ] **Step 1: Write failing event-contract tests**

```python
async def test_duplicate_event_is_consumed_once(db):
    event = AgentDomainEvent.create("risk_alert_created", "risk", 27, {"level": "high"})
    calls = []
    await service.consume_once(db, event, "profile", lambda _: calls.append(1))
    await service.consume_once(db, event, "profile", lambda _: calls.append(1))
    assert calls == [1]

def test_event_requires_customer_and_correlation():
    event = AgentDomainEvent.create("analytics_insight", "analytics", 27, {"kind": "pnl_drawdown"})
    assert event.customer_id == 27
    assert event.correlation_id
```

- [ ] **Step 2: Run the focused test and verify it fails because the module does not exist**

Run: `python -m pytest tests/test_agent_event_service.py -q`  
Expected: import failure for `app.service.agent_event_service`.

- [ ] **Step 3: Add migration, models and minimal event service**

```sql
ALTER TABLE product_recommendation
  ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'pending',
  ADD COLUMN feedback_reason VARCHAR(255) NULL,
  ADD COLUMN feedback_at DATETIME NULL,
  ADD INDEX idx_rec_customer_status (customer_id, status);

CREATE TABLE agent_event_outbox (... event_id CHAR(36) PRIMARY KEY, event_type VARCHAR(64), customer_id BIGINT, correlation_id VARCHAR(64), payload JSON, status VARCHAR(16), created_at DATETIME ...);
CREATE TABLE agent_event_consumption (... event_id CHAR(36), consumer VARCHAR(64), consumed_at DATETIME, PRIMARY KEY (event_id, consumer));
```

Implement `AgentDomainEvent.create()` with UUID, UTC timestamp and non-empty validation. Implement outbox insert in the caller transaction and `consume_once()` by inserting the composite idempotency key before invoking the handler.

- [ ] **Step 4: Run focused tests and verify green**

Run: `python -m pytest tests/test_agent_event_service.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/service/agent_event_service.py app/model/entities.py migrations/20260725_six_agent_linkage.sql tests/test_agent_event_service.py
git commit -m "feat: add durable agent event contract"
```

### Task 2: Replace split C1/C2/C4 dispatch with typed consumers

**Files:**
- Modify: `app/service/event_bus.py`
- Modify: `app/service/risk_monitor_service.py`
- Modify: `main.py`
- Test: `tests/test_agent_event_service.py`

**Interfaces:**
- Consumes `risk_alert_created`, `transaction_completed`, `suspicious_reported`, `risk_assessment_expiring`.
- Produces `dispatch_event(event: AgentDomainEvent) -> None` and `RiskMonitorService.emit_alert_event(db, alert) -> None`.

- [ ] **Step 1: Add failing routing tests**

```python
async def test_risk_alert_dispatches_once_to_profile_advisor_and_customer(monkeypatch):
    event = AgentDomainEvent.create("risk_alert_created", "risk", 27, {"alert_level": "high"})
    delivered = []
    monkeypatch.setattr(event_bus, "PROFILE_CONSUMER", lambda e: delivered.append("profile"))
    monkeypatch.setattr(event_bus, "ADVISOR_CONSUMER", lambda e: delivered.append("advisor"))
    monkeypatch.setattr(event_bus, "CUSTOMER_CONSUMER", lambda e: delivered.append("customer"))
    await event_bus.dispatch_event(event)
    assert delivered == ["profile", "advisor", "customer"]
```

- [ ] **Step 2: Run test and verify it fails because typed dispatch is absent**

Run: `python -m pytest tests/test_agent_event_service.py::test_risk_alert_dispatches_once_to_profile_advisor_and_customer -q`  
Expected: FAIL with missing `dispatch_event`.

- [ ] **Step 3: Implement single-channel dispatch**

Remove `EVENT_C1_ADVISOR`, `EVENT_C2_MONITOR`, `EVENT_C4_CUSTOMER` from production publishing. Keep a one-release legacy adapter that converts only `event:risk_alert` messages to `risk_alert_created`; it must not invoke three handlers for a single legacy message. Change `RiskMonitorService.save_alert()` to enqueue `risk_alert_created` after alert persistence, rather than publish a hand-built payload.

- [ ] **Step 4: Run routing and existing risk tests**

Run: `python -m pytest tests/test_agent_event_service.py tests/test_risk_monitor.py tests/test_transaction_flow.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/service/event_bus.py app/service/risk_monitor_service.py main.py tests/test_agent_event_service.py
git commit -m "refactor: dispatch typed risk linkage events"
```

### Task 3: Enforce risk preflight in business operations

**Files:**
- Modify: `app/service/transaction_flow_service.py`
- Modify: `app/api/operations/purchase.py`
- Modify: `app/api/operations/redeem.py`
- Modify: `app/api/operations/transfer.py`
- Test: `tests/test_six_agent_linkage.py`

**Interfaces:**
- Produces `TransactionFlowService.assess_pre_execution(db, event) -> {"decision": "allow|review|block", "alert": dict | None}`.
- `purchase_product`, `redeem_product`, `transfer_funds` must call it before the first mutation SQL statement.

- [ ] **Step 1: Write failing preflight tests**

```python
async def test_high_risk_transfer_blocks_before_balance_update(client, monkeypatch):
    monkeypatch.setattr(TransactionFlowService, "assess_pre_execution", AsyncMock(return_value={"decision": "block", "alert": {"alert_level": "high"}}))
    response = await transfer_funds({"from_customer_id": 1, "to_customer_id": 2, "amount": 1_000_000}, db, user=advisor)
    assert response.code == 409
    db.execute.assert_not_awaited()
```

- [ ] **Step 2: Run test and verify it fails**

Run: `python -m pytest tests/test_six_agent_linkage.py::test_high_risk_transfer_blocks_before_balance_update -q`  
Expected: FAIL because `assess_pre_execution` is missing and transfer mutates first.

- [ ] **Step 3: Implement decision gate and post-completion event**

Use the existing AML rules to grade the preflight context. `high` returns HTTP 409, `medium` returns HTTP 202 with a persisted pending alert, and only `allow` executes the transaction. After a successful commit enqueue `transaction_completed`; do not use `publish_operation_event()` for risk semantics.

- [ ] **Step 4: Run focused and existing operator tests**

Run: `python -m pytest tests/test_six_agent_linkage.py tests/test_transaction_flow.py tests/test_operator_agent.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/service/transaction_flow_service.py app/api/operations/purchase.py app/api/operations/redeem.py app/api/operations/transfer.py tests/test_six_agent_linkage.py
git commit -m "feat: gate business operations with risk preflight"
```

### Task 4: Add recommendation feedback and profile-driven filtering

**Files:**
- Modify: `app/service/advisor_service.py`
- Modify: `app/service/profile_service.py`
- Modify: `app/api/advisor.py`
- Modify: `frontend/src/components/RecommendationGrid.vue`
- Modify: `frontend/src/views/AdvisorWorkspaceView.vue`
- Test: `tests/test_six_agent_linkage.py`

**Interfaces:**
- Produces `AdvisorService.record_recommendation_feedback(customer_id, recommendation_id, status, reason)`.
- Produces `ProfileService.apply_recommendation_feedback(event)` and `ProfileService.get_recommendation_constraints(customer_id)`.

- [ ] **Step 1: Write failing feedback tests**

```python
async def test_three_rejections_exclude_product_type_without_changing_risk_level(service):
    for _ in range(3):
        await service.apply_recommendation_feedback(rejected_mixed_fund_event)
    constraints = await service.get_recommendation_constraints(27)
    assert "混合基金" in constraints["avoid_product_types"]
    assert (await service.get_profile(27)).risk_level == "C3"
```

- [ ] **Step 2: Run test and verify it fails**

Run: `python -m pytest tests/test_six_agent_linkage.py::test_three_rejections_exclude_product_type_without_changing_risk_level -q`  
Expected: FAIL because feedback APIs and constraints are absent.

- [ ] **Step 3: Implement feedback lifecycle**

Persist `pending` records with returned recommendation IDs. Add an authenticated advisor endpoint that permits only `accepted/rejected/ignored`; enqueue `recommendation_feedback`. Store aggregate signals under `product_preference.feedback_signals`, invalidate cache, and filter candidate products by `avoid_product_types`. Add one “不感兴趣” action per recommendation card; it calls the endpoint and disables after success.

- [ ] **Step 4: Run backend and frontend tests**

Run: `python -m pytest tests/test_six_agent_linkage.py -q`  
Run: `pnpm --dir frontend test -- --run`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/service/advisor_service.py app/service/profile_service.py app/api/advisor.py frontend/src/components/RecommendationGrid.vue frontend/src/views/AdvisorWorkspaceView.vue tests/test_six_agent_linkage.py
git commit -m "feat: link recommendation feedback to profile constraints"
```

### Task 5: Connect analytics, customer sentiment, expiry and suspicious-report events

**Files:**
- Create: `app/service/insight_extractor.py`
- Modify: `app/api/chat.py`
- Modify: `app/agent/customer_agent.py`
- Modify: `app/service/profile_service.py`
- Modify: `app/service/risk_scheduler.py`
- Modify: `app/api/operations/suspicious_report.py`
- Test: `tests/test_six_agent_linkage.py`

**Interfaces:**
- Produces `extract_insights(query, rows) -> list[AgentDomainEvent]`.
- Produces `detect_customer_sentiment(message) -> {"level", "evidence"}`.

- [ ] **Step 1: Write failing signal tests**

```python
def test_only_verifiable_drawdown_query_produces_pnl_event():
    events = extract_insights("客户27近30日亏损", [{"customer_id": 27, "profit_ratio": -0.12}])
    assert events[0].event_type == "analytics_insight"
    assert events[0].payload["kind"] == "pnl_drawdown"

def test_free_text_analysis_does_not_produce_event():
    assert extract_insights("市场怎么样", [{"summary": "波动"}]) == []
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `python -m pytest tests/test_six_agent_linkage.py -q`  
Expected: FAIL because extractor and emotion detector are absent.

- [ ] **Step 3: Implement allowed signal producers and consumers**

Publish only validated P&L and weekly-frequency insights after NL2SQL success. Map high-frequency insight to one risk evaluation request, P&L to a profile strategy signal and advisor constraint. Add deterministic negative/high-distress keyword detection in CustomerServiceAgent and enqueue `customer_sentiment`. Make scheduler emit `risk_assessment_expiring` after the alert insert. Make suspicious-report enqueue `suspicious_reported` after commit; its risk consumer creates a standard alert. Customer consumer writes a Redis/customer-service pending-task record only; it does not push externally.

- [ ] **Step 4: Run targeted suite**

Run: `python -m pytest tests/test_six_agent_linkage.py tests/test_risk_monitor.py tests/test_chat_orchestration.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/service/insight_extractor.py app/api/chat.py app/agent/customer_agent.py app/service/profile_service.py app/service/risk_scheduler.py app/api/operations/suspicious_report.py tests/test_six_agent_linkage.py
git commit -m "feat: connect analytics and customer signals"
```

### Task 6: Run end-to-end contract verification

**Files:**
- Modify: `tests/test_business_journeys.py`
- Modify: `tests/test_e2e_10users_full_flow.py`

**Interfaces:**
- Consumes the completed six-Agent event contract through live API requests.
- Produces deterministic assertions for operation→risk, feedback→profile, analytics→strategy, sentiment→profile and expiry→customer task.

- [ ] **Step 1: Write opt-in live tests for each closed loop**

```python
@unittest.skipUnless(LIVE, "set RUN_LIVE_E2E=1")
def test_rejected_recommendation_changes_next_candidate_pool(self):
    # Create three rejected feedback records for one product type, then request recommendations.
    self.assertNotIn("混合基金", returned_product_types)
```

- [ ] **Step 2: Run without live flag and verify tests are safely skipped**

Run: `python -m pytest tests/test_business_journeys.py -q`  
Expected: SKIPPED, no database mutation.

- [ ] **Step 3: Execute live suite only after local MySQL and Redis are confirmed running**

Run: `RUN_LIVE_E2E=1 python -m pytest tests/test_business_journeys.py tests/test_e2e_10users_full_flow.py -q`  
Expected: PASS for all enabled journeys.

- [ ] **Step 4: Run full non-live regression suite**

Run: `python -m pytest tests/test_agent_event_service.py tests/test_six_agent_linkage.py tests/test_transaction_flow.py tests/test_risk_monitor.py tests/test_operator_agent.py tests/test_chat_orchestration.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_business_journeys.py tests/test_e2e_10users_full_flow.py
git commit -m "test: cover six-agent linkage journeys"
```

## Self-review

- Spec coverage: Tasks 1-2 cover durable typed events; Task 3 covers business-to-risk; Task 4 covers recommendation feedback; Task 5 covers analytics, sentiment, expiry and suspicious reports; Task 6 covers end-to-end acceptance.
- Placeholder scan: no deferred requirements or unspecified implementation steps remain.
- Interface consistency: all producers use `AgentDomainEvent`; all consumers use `event_type`, `customer_id`, `correlation_id` and immutable `payload`.
