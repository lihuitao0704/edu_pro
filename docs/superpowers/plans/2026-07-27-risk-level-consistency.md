# 风险等级数据一致性整改 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让客户风险等级在评估、画像、Agent、API、前端和历史数据中只使用受约束的 C1—C5 / 标准中文名配对，并消除跨表错配。

**Architecture:** 使用 `app.config.risk_level_mapping` 作为 code/name 的唯一来源；所有客户风险等级写入收敛到专用写入服务。数据库以 code/name 配对约束为最终防线，前端按明确的 code/name 契约展示。

**Tech Stack:** Python 3、FastAPI、SQLAlchemy Async、MySQL 8、Pydantic、Vue 3、Vitest、pytest。

## Global Constraints

- 标准映射固定为 C1 保守型、C2 稳健型、C3 平衡型、C4 积极型、C5 激进型。
- `进取型` 只能被标准化函数作为历史输入接受，禁止写库或对外输出。
- `fin_risk_assessment.risk_level` 只保存 C1—C5；`fin_customer_profile` 只保存 `risk_level_code` 和 `risk_level_name`。
- 不变更 `fin_product.risk_level` 的 R1—R5 产品风险语义。
- 两表重建脚本只在显式 `--apply --confirm-reset-risk-profile-data` 下写库，并在删除前完成预检。

---

### Task 1: 建立风险等级领域映射与测试

**Files:**
- Create: `app/config/risk_level_mapping.py`
- Create: `tests/test_risk_level_mapping.py`
- Modify: `app/engine/score_mapper.py`

**Interfaces:**
- Produces `NormalizedRiskLevel(code: str, name: str)`。
- Produces `normalize_risk_level(value: str) -> NormalizedRiskLevel`。
- Produces `risk_level_from_score(score: float) -> NormalizedRiskLevel`。

- [ ] **Step 1: Write failing mapping tests**

```python
def test_normalize_code_name_and_legacy_alias():
    assert normalize_risk_level(" c3 ").model_dump() == {
        "risk_level_code": "C3", "risk_level_name": "平衡型"
    }
    assert normalize_risk_level("积极型").risk_level_code == "C4"
    assert normalize_risk_level("进取型").risk_level_name == "积极型"

def test_rejects_unknown_risk_level():
    with pytest.raises(RiskLevelNormalizationError):
        normalize_risk_level("R3")
```

- [ ] **Step 2: Run the tests to verify RED**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_risk_level_mapping.py -q`

Expected: FAIL because `app.config.risk_level_mapping` does not exist.

- [ ] **Step 3: Implement the immutable mapping and update score mapper**

```python
RISK_LEVEL_MAPPING = {
    "C1": "保守型", "C2": "稳健型", "C3": "平衡型",
    "C4": "积极型", "C5": "激进型",
}
RISK_LEVEL_ALIASES = {**RISK_LEVEL_MAPPING, **{name: code for code, name in RISK_LEVEL_MAPPING.items()}, "进取型": "C4"}
```

`map_score_to_risk_level` remains as a compatibility adapter returning `(code, name)` derived exclusively from `risk_level_from_score`.

- [ ] **Step 4: Run the tests to verify GREEN**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_risk_level_mapping.py -q`

Expected: PASS.

### Task 2: Add schema migration and ORM fields

**Files:**
- Create: `migrations/20260727_risk_level_consistency.sql`
- Modify: `app/model/entities.py`
- Create: `tests/test_risk_level_migration_contract.py`

**Interfaces:**
- `FinCustomerProfile.risk_level_code` and `.risk_level_name` replace the legacy ORM column.
- Migration validates every permitted `(code, name)` pair and code-only assessment values.

- [ ] **Step 1: Write migration contract tests**

```python
def test_migration_adds_customer_code_name_and_removes_legacy_column():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "ADD COLUMN risk_level_code" in sql
    assert "ADD COLUMN risk_level_name" in sql
    assert "DROP COLUMN risk_level" in sql

def test_migration_contains_every_standard_pair_and_no_legacy_output_name():
    sql = MIGRATION.read_text(encoding="utf-8")
    for code, name in RISK_LEVEL_MAPPING.items():
        assert f"risk_level_code = '{code}' AND risk_level_name = '{name}'" in sql
    assert "'进取型'" not in sql
```

- [ ] **Step 2: Run RED**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_risk_level_migration_contract.py -q`

Expected: FAIL because the migration does not exist.

- [ ] **Step 3: Implement a phased, idempotent MySQL migration**

The migration must add nullable fields, backfill from old code/name/`进取型`, fail if unknown values remain, add pair and code `CHECK` constraints, make the new fields non-null, then drop only `fin_customer_profile.risk_level`. It must not alter `fin_product.risk_level`.

- [ ] **Step 4: Update ORM and run GREEN**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_risk_level_migration_contract.py -q`

Expected: PASS.

### Task 3: Centralize write operations

**Files:**
- Create: `app/service/risk_profile_writer.py`
- Create: `tests/test_risk_profile_writer.py`
- Modify: `app/service/risk_service.py`
- Modify: `app/service/profile_service.py`
- Modify: `app/engine/calibration_trend.py`

**Interfaces:**
- `RiskProfileWriter.write_current_profile(customer_id, risk_level, risk_score, dimensions, assessment=None)` writes matching assessment/profile records.
- `RiskProfileWriter.write_calibration_adjustment(customer_id, risk_level, risk_score, dimensions, detail)` creates an audit assessment and updates the current profile.

- [ ] **Step 1: Write failing transactional behavior tests**

```python
async def test_writer_normalizes_alias_and_writes_matching_profile_fields(db):
    result = await writer.write_current_profile(7, "进取型", 70, dimensions)
    assert profile.risk_level_code == assessment.risk_level == result.risk_level_code == "C4"
    assert profile.risk_level_name == result.risk_level_name == "积极型"

async def test_writer_rejects_invalid_name_before_any_flush(db):
    with pytest.raises(RiskLevelNormalizationError):
        await writer.write_current_profile(7, "R4", 70, dimensions)
    db.flush.assert_not_awaited()
```

- [ ] **Step 2: Run RED**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_risk_profile_writer.py -q`

Expected: FAIL because the writer module does not exist.

- [ ] **Step 3: Implement the one write boundary**

The writer normalizes before mutation, verifies `sum(dimensions[*]["score"]) == risk_score`, verifies score band/code consistency, writes `risk_level` to assessments and code/name to profiles, serializes both explicit fields into profile JSON, updates the `risk_preference` tag with code, and invalidates cache after flush.

- [ ] **Step 4: Route questionnaire, full assessment and calibration through the writer**

Questionnaire answers retain `questionnaire_score`; the canonical stored assessment score and code are the final four-dimension result. Remove direct profile risk-level assignments from the three callers.

- [ ] **Step 5: Run GREEN**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_risk_profile_writer.py tests/test_risk_assessment_consistency.py -q`

Expected: PASS.

### Task 4: Update code-consuming services, Agent contracts and graph synchronization

**Files:**
- Modify: `app/service/suitability_policy.py`
- Modify: `app/service/advisor_service.py`
- Modify: `app/service/comparison_service.py`
- Modify: `app/tool/profile_tool.py`
- Modify: `app/tool/neo4j_sync.py`
- Modify: `app/service/graph_sync.py`
- Modify: `app/agent/profile_agent.py`
- Modify: `app/agent/advisor_agent.py`
- Modify: `app/agent/customer_agent.py`
- Modify: `app/agent/explanation_agent.py`
- Modify: `app/agent/operator_agent.py`
- Create: `tests/test_customer_risk_level_contract.py`

**Interfaces:**
- Customer-risk consumers receive `risk_level_code`; user-facing payloads may additionally receive `risk_level_name`.
- Agent prompts demand `risk_level_code` and forbid direct persistence instructions.

- [ ] **Step 1: Write failing contract/guard tests**

```python
def test_customer_risk_consumers_use_profile_code_field():
    assert "FinCustomerProfile.risk_level" not in customer_risk_source_text

def test_agent_prompts_require_code_not_chinese_label():
    assert "risk_level_code" in PROFILE_AGENT_SYSTEM_PROMPT
    assert "不得直接写入" in PROFILE_AGENT_SYSTEM_PROMPT
```

- [ ] **Step 2: Run RED**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_customer_risk_level_contract.py -q`

Expected: FAIL because code consumers and prompts still use the legacy field.

- [ ] **Step 3: Replace customer-level reads and writes**

Use `profile.risk_level_code` for suitability, allocation, comparison and Neo4j. Normalize incoming external customer-risk values before use. Keep `FinProduct.risk_level` reads unchanged because they are R1—R5 product classifications.

- [ ] **Step 4: Run GREEN**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_customer_risk_level_contract.py tests/test_suitability_disclosure.py -q`

Expected: PASS.

### Task 5: Change backend API contracts

**Files:**
- Modify: `app/model/schemas.py`
- Modify: `app/api/profile.py`
- Modify: `app/api/risk.py`
- Modify: `app/api/operations/purchase.py`
- Modify: `app/service/profile_service.py`
- Modify: `tests/test_workspace_apis.py`
- Create: `tests/test_risk_level_api_contract.py`

**Interfaces:**
- Profile and assessment responses expose `risk_level_code` and `risk_level_name`.
- Customer-risk requests reject ambiguous `risk_level`.

- [ ] **Step 1: Write failing response tests**

```python
def test_profile_payload_has_code_and_name_without_legacy_risk_level():
    payload = ProfileService._profile_to_dict(profile)
    assert payload["risk_level_code"] == "C3"
    assert payload["risk_level_name"] == "平衡型"
    assert "risk_level" not in payload
```

- [ ] **Step 2: Run RED**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_risk_level_api_contract.py -q`

Expected: FAIL because the old key is currently returned.

- [ ] **Step 3: Implement explicit Pydantic and API fields**

Change `ProfileResult`, `AssessmentResult`, suitability responses and customer-profile payloads to explicit code/name fields. Retain product recommendation `risk_level` as R1—R5 and document it as a product field.

- [ ] **Step 4: Run GREEN**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_risk_level_api_contract.py tests/test_workspace_apis.py -q`

Expected: PASS.

### Task 6: Replace front-end compatibility maps

**Files:**
- Create: `frontend/src/utils/risk-level.ts`
- Create: `frontend/src/utils/risk-level.test.ts`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/views/ProfileView.vue`
- Modify: `frontend/src/views/AdvisorWorkspaceView.vue`
- Modify: `frontend/src/components/RiskAssessmentModal.vue`
- Modify: `frontend/src/components/RecommendationCard.vue`

**Interfaces:**
- `CustomerRiskLevel = { risk_level_code: CustomerRiskLevelCode; risk_level_name: string }`.
- `riskProductLimit(code)` and `riskTheme(code)` accept C codes only.

- [ ] **Step 1: Write failing front-end utility tests**

```ts
expect(riskProductLimit('C4')).toBe('R4')
expect(riskLevelName('C4')).toBe('积极型')
expect(() => riskProductLimit('进取型' as never)).toThrow()
```

- [ ] **Step 2: Run RED**

Run: `npm --prefix frontend test -- --run src/utils/risk-level.test.ts`

Expected: FAIL because the utility does not exist.

- [ ] **Step 3: Implement code-only display helpers and replace local maps**

Delete `ProfileView.vue`'s C-code/Chinese compatibility maps. It renders `profile.risk_level_name`, and invokes the new helpers only with `profile.risk_level_code`.

- [ ] **Step 4: Run GREEN**

Run: `npm --prefix frontend test -- --run src/utils/risk-level.test.ts`

Expected: PASS.

### Task 7: Rebuild seed data and implement protected historical reset

**Files:**
- Modify: `scripts/seed_demo_data.py`
- Create: `scripts/rebuild_risk_profile_data.py`
- Create: `tests/test_rebuild_risk_profile_data.py`
- Modify: `tests/test_demo_seed.py`

**Interfaces:**
- Seed customers contain `risk_level_code` only; name is derived by mapping.
- `python scripts/rebuild_risk_profile_data.py` is read-only preflight.
- `python scripts/rebuild_risk_profile_data.py --apply --confirm-reset-risk-profile-data` is the only destructive invocation.

- [ ] **Step 1: Write failing snapshot and validation tests**

```python
def test_rebuild_converts_legacy_name_to_standard_pair():
    record = rebuild_record({"risk_level": "进取型", "risk_score": 70})
    assert record["risk_level_code"] == "C4"
    assert record["risk_level_name"] == "积极型"

def test_rebuild_rejects_unknown_value_before_reset():
    with pytest.raises(RebuildValidationError):
        build_rebuild_snapshot([{"risk_level": "未知型"}])
```

- [ ] **Step 2: Run RED**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_rebuild_risk_profile_data.py -q`

Expected: FAIL because the rebuild module does not exist.

- [ ] **Step 3: Implement preflight, snapshot and targeted reset**

Validate all historical values before executing `DELETE FROM fin_risk_assessment` and `DELETE FROM fin_customer_profile`; use one transaction; reinsert matching latest assessment/profile rows for every captured customer; derive four dimension values whose sum equals canonical score; verify the four postconditions from the design document before commit.

- [ ] **Step 4: Update deterministic demo data**

The demo script must insert matching C code/name profile rows and one assessment code per customer; its four dimensions must add to each risk score and fall inside the code’s score band.

- [ ] **Step 5: Run GREEN**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_rebuild_risk_profile_data.py tests/test_demo_seed.py -q`

Expected: PASS.

### Task 8: Execute migration and protected data rebuild

**Files:**
- Execute: `migrations/20260727_risk_level_consistency.sql`
- Execute: `scripts/rebuild_risk_profile_data.py`

- [ ] **Step 1: Run migration contract and full preflight**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_risk_level_migration_contract.py tests/test_rebuild_risk_profile_data.py -q`

Run: `./.venv/Scripts/python.exe scripts/rebuild_risk_profile_data.py`

Expected: PASS and a report with zero unnormalizable records; no database changes.

- [ ] **Step 2: Apply schema migration**

Run the migration through the configured MySQL client after checking the exact target schema is `education_pro` and the two target tables are `fin_customer_profile` and `fin_risk_assessment`.

- [ ] **Step 3: Run the explicit protected rebuild**

Run: `./.venv/Scripts/python.exe scripts/rebuild_risk_profile_data.py --apply --confirm-reset-risk-profile-data`

Expected: only the two declared tables are cleared and rebuilt; the final report has zero code/name, cross-table, score-band and dimension-sum violations.

- [ ] **Step 4: Query the database independently**

Run a read-only join between current profile rows and each customer’s latest assessment. Expected: zero mismatched codes, zero invalid name values, and zero profile rows whose four dimension sum differs from `risk_score`.

### Task 9: Full verification and documentation

**Files:**
- Modify: `docs/superpowers/specs/2026-07-27-risk-level-consistency-design.md` only if verification reveals an approved design clarification.

- [ ] **Step 1: Run backend suite**

Run: `./.venv/Scripts/python.exe -m pytest -q`

Expected: PASS.

- [ ] **Step 2: Run front-end suite and build**

Run: `npm --prefix frontend test -- --run`

Run: `npm --prefix frontend run build`

Expected: PASS.

- [ ] **Step 3: Check for prohibited customer-risk output and direct writes**

Run: `rg -n "risk_level\s*=|\.risk_level" app frontend/src scripts | rg "FinCustomerProfile|profile\.risk_level|risk_level_name.*C[1-5]"`

Expected: no customer-profile legacy write path; only assessment C-code field and product R-level field remain.

- [ ] **Step 4: Commit each independently reviewable unit**

Use focused commits for mapping/migration, write-boundary/API, front end, and rebuild/verification. Do not stage `.env` or `.idea/edu_pro.iml`.
