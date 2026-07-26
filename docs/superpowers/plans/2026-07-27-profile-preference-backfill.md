# Customer Profile Preference Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill empty customer allocation and product-preference JSON with risk-aligned values linked to exact in-sale `fin_product` rows.

**Architecture:** A small pure module builds allocation templates and candidate products from profile and catalogue dictionaries. A CLI loads database data, updates only missing values in one transaction, then performs independent SQL validation.

**Tech Stack:** Python 3, PyMySQL, pytest, MySQL JSON, existing `app.config.risk_level_mapping`.

## Global Constraints

- Update only empty `fin_customer_profile.asset_allocation` and `fin_customer_profile.product_preference`.
- Never modify risk codes/names/scores, holdings, assessment rows, or populated preference data.
- Candidate `product_id` and `product_code` must identify the same in-sale row in `fin_product`.
- Product `R1`–`R5` must not exceed customer `C1`–`C5`; allocation keys sum to `1.00`.

---

### Task 1: Build test-first allocation and candidate-product functions

**Files:**

- Create: `app/service/profile_preference_backfill.py`
- Create: `tests/test_profile_preference_backfill.py`

**Interfaces:**

- Consumes: `normalize_risk_level(value)`.
- Produces: `build_asset_allocation(risk_code: str) -> dict[str, float]` and `build_product_preference(risk_code: str, products: list[dict], generated_at: str) -> dict`.

- [ ] **Step 1: Write a failing test**

```python
def test_builds_c3_allocation_and_references_real_allowed_products():
    from app.service.profile_preference_backfill import build_asset_allocation, build_product_preference
    products = [
        {"id": 11, "product_code": "P-R1", "product_name": "货币产品", "product_type": "货币", "risk_level": "R1", "status": "在售"},
        {"id": 12, "product_code": "P-R3", "product_name": "混合产品", "product_type": "混合", "risk_level": "R3", "status": "在售"},
        {"id": 13, "product_code": "P-R4", "product_name": "股票产品", "product_type": "股票", "risk_level": "R4", "status": "在售"},
    ]
    assert build_asset_allocation("C3") == {"cash": 0.15, "bond": 0.35, "hybrid": 0.30, "equity": 0.20}
    result = build_product_preference("C3", products, "2026-07-27T00:00:00Z")
    assert [item["product_id"] for item in result["candidate_products"]] == [11, 12]
    assert result["candidate_products"][0]["product_code"] == "P-R1"
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_profile_preference_backfill.py::test_builds_c3_allocation_and_references_real_allowed_products -v`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement the minimum code**

```python
_ALLOCATIONS = {
    "C1": {"cash": 0.30, "bond": 0.55, "hybrid": 0.15, "equity": 0.00},
    "C2": {"cash": 0.20, "bond": 0.45, "hybrid": 0.25, "equity": 0.10},
    "C3": {"cash": 0.15, "bond": 0.35, "hybrid": 0.30, "equity": 0.20},
    "C4": {"cash": 0.10, "bond": 0.20, "hybrid": 0.35, "equity": 0.35},
    "C5": {"cash": 0.05, "bond": 0.10, "hybrid": 0.25, "equity": 0.60},
}
```

Normalize the code, sort allowed in-sale products by `(risk_level, product_code)`, and copy exact `id`, code, name, type, risk fields into up to three candidates.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_profile_preference_backfill.py::test_builds_c3_allocation_and_references_real_allowed_products -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add app/service/profile_preference_backfill.py tests/test_profile_preference_backfill.py && git commit -m "feat: build profile preference data"`

### Task 2: Protect populated values and invalid catalogue data

**Files:**

- Modify: `app/service/profile_preference_backfill.py`
- Modify: `tests/test_profile_preference_backfill.py`

**Interfaces:**

- Consumes: Task 1 construction functions.
- Produces: `build_missing_profile_fields(profile: dict, products: list[dict], generated_at: str) -> dict[str, dict]`.

- [ ] **Step 1: Write a failing test**

```python
def test_only_builds_missing_fields_and_requires_an_allowed_in_sale_product():
    from app.service.profile_preference_backfill import build_missing_profile_fields
    profile = {"risk_level_code": "C1", "asset_allocation": {"cash": 1.0}}
    product = {"id": 1, "product_code": "P-1", "product_name": "货币", "product_type": "货币", "risk_level": "R1", "status": "在售"}
    result = build_missing_profile_fields(profile, [product], "2026-07-27T00:00:00Z")
    assert "asset_allocation" not in result
    assert result["product_preference"]["candidate_products"][0]["product_id"] == 1
    with pytest.raises(ValueError, match="没有可用在售产品"):
        build_missing_profile_fields({"risk_level_code": "C1"}, [], "2026-07-27T00:00:00Z")
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_profile_preference_backfill.py::test_only_builds_missing_fields_and_requires_an_allowed_in_sale_product -v`

Expected: FAIL because `build_missing_profile_fields` does not exist.

- [ ] **Step 3: Implement the minimum code**

```python
def is_empty_json(value: object) -> bool:
    return value is None or value == {} or value == ""

def build_missing_profile_fields(profile, products, generated_at):
    updates = {}
    if is_empty_json(profile.get("asset_allocation")):
        updates["asset_allocation"] = build_asset_allocation(profile["risk_level_code"])
    if is_empty_json(profile.get("product_preference")):
        updates["product_preference"] = build_product_preference(profile["risk_level_code"], products, generated_at)
    return updates
```

Raise `ValueError("没有可用在售产品")` if selection returns no candidates.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_profile_preference_backfill.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add app/service/profile_preference_backfill.py tests/test_profile_preference_backfill.py && git commit -m "test: enforce profile preference boundaries"`

### Task 3: Backfill transaction and validate live references

**Files:**

- Create: `scripts/backfill_profile_preferences.py`
- Modify: `tests/test_profile_preference_backfill.py`

**Interfaces:**

- Consumes: `build_missing_profile_fields` and `get_settings()`.
- Produces: `backfill(apply: bool) -> dict[str, int]`; writes require `--apply --confirm-backfill-profile-preferences`.

- [ ] **Step 1: Write a failing test**

```python
def test_backfill_dry_run_reports_candidates_without_writing():
    import scripts.backfill_profile_preferences as script
    assert script.backfill(apply=False)["updated_profiles"] == 0
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_profile_preference_backfill.py::test_backfill_dry_run_reports_candidates_without_writing -v`

Expected: FAIL because the script does not exist.

- [ ] **Step 3: Implement the minimum code**

Use one non-autocommit PyMySQL connection to load profiles and products. Build only missing JSON fields and, on dry run, roll back and report proposed counts. On `apply`, update only the specific empty column(s) with JSON-serialized values and commit. Then count and reject: empty fields, allocations not summing to one, candidate `(product_id, product_code)` pairs absent from `fin_product`, off-sale references, and product risks higher than profile risks.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_profile_preference_backfill.py -v`

Expected: PASS.

- [ ] **Step 5: Run dry-run and approved write**

Run: `python scripts/backfill_profile_preferences.py`

Expected: JSON preview; transaction rolled back.

Run: `python scripts/backfill_profile_preferences.py --apply --confirm-backfill-profile-preferences`

Expected: JSON with updated count and every validation count at zero.

- [ ] **Step 6: Commit**

Run: `git add scripts/backfill_profile_preferences.py tests/test_profile_preference_backfill.py && git commit -m "feat: backfill profile preferences"`
