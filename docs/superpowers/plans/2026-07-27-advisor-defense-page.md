# Advisor Agent Defense Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `01-投顾Agent汇报.html` into a complete, code-aligned finance-advisor defense page with a full process architecture diagram.

**Architecture:** Keep the existing offline report shell, navigation, and CSS. Reorganize the body around one end-to-end AdvisorAgent flow, then distinguish requirement baseline capabilities from implemented engineering enhancements and state the financial business boundary explicitly.

**Tech Stack:** Static HTML5, existing `reports.css`, Python `unittest`.

## Global Constraints

- Modify only `01-投顾Agent汇报.html` and `tests/test_report_html.py` for the feature implementation.
- Preserve the global previous/next navigation contract and existing profile-expiry safeguards.
- Use code-aligned terms: `AdvisorAgent`, `smart_recommend`, seven tools, `Outbox`, `Redis Pub/Sub`, `Memory Manager`.
- Use no external assets or remote URLs; use the existing `.flow-diagram`, `.flow`, `.node`, and `.grid` classes.
- State that AdvisorAgent produces recommendations; it does not execute trades or change formal C1-C5 ratings.

---

### Task 1: Add an advisor-page coverage test

**Files:**
- Modify: `tests/test_report_html.py`
- Modify: `01-投顾Agent汇报.html`

**Interfaces:**
- Consumes: static HTML loaded through `Path.read_text(encoding="utf-8")`.
- Produces: an automated contract for the end-to-end advisor defense narrative.

- [ ] **Step 1: Write the failing test**

Add this method to `ReportHtmlTest`:

```python
def test_advisor_page_covers_full_flow_and_engineering_enhancements(self):
    html = (ROOT / "01-投顾Agent汇报.html").read_text(encoding="utf-8")
    for anchor in (
        "完整投顾流程架构",
        "七工具",
        "客户身份校验",
        "风险画像与动态约束",
        "产品推荐与资产配置",
        "业务操作 Agent",
        "Outbox",
        "Redis Pub/Sub",
        "需求文档中的基础能力",
        "当前工程增强",
        "预算分配",
        "SSE 工具进度",
        "不直接执行交易",
        "不修改正式风险评级",
    ):
        self.assertIn(anchor, html)
    self.assertGreaterEqual(html.count('class="flow-diagram"'), 3)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m unittest tests.test_report_html.ReportHtmlTest.test_advisor_page_covers_full_flow_and_engineering_enhancements -v
```

Expected: FAIL because the existing page does not name every process stage and requirement-versus-enhancement comparison item.

- [ ] **Step 3: Add the complete flow architecture and comparison sections**

Insert after the hero a `flow-diagram` whose ordered nodes are:

```html
<div class="node"><strong>理财顾问 / 客户</strong><span>推荐、比较、配置需求</span></div>
<div class="node"><strong>Router Agent</strong><span>识别投顾意图、校验角色</span></div>
<div class="node"><strong>客户身份校验</strong><span>customer_id、状态、会话归属</span></div>
<div class="node"><strong>风险画像与动态约束</strong><span>风评、持仓、预警、适当性</span></div>
<div class="node"><strong>AdvisorAgent 七工具</strong><span>LLM 选择并编排工具</span></div>
<div class="node"><strong>产品推荐与资产配置</strong><span>匹配度、比例、预算分配</span></div>
<div class="node"><strong>业务操作 Agent</strong><span>确认后进入受控交易链路</span></div>
<div class="node"><strong>Outbox / Redis Pub/Sub</strong><span>推荐、成交与偏好事件联动</span></div>
<div class="node"><strong>Memory Manager</strong><span>会话、画像、事实、图谱回写</span></div>
```

Add a seven-tool table/card section; then add a two-column “需求文档中的基础能力 / 当前工程增强” comparison. Include the exact labels `预算分配` and `SSE 工具进度`. End with a boundary card containing the exact wording `不直接执行交易` and `不修改正式风险评级`.

- [ ] **Step 4: Run the test to verify it passes**

Run:

```powershell
python -m unittest tests.test_report_html.ReportHtmlTest.test_advisor_page_covers_full_flow_and_engineering_enhancements -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add -- tests/test_report_html.py 01-投顾Agent汇报.html
git commit -m "docs: expand advisor defense report"
```

### Task 2: Run the complete offline report regression suite

**Files:**
- Modify if a regression is found: `01-投顾Agent汇报.html` or `tests/test_report_html.py`.

**Interfaces:**
- Consumes: all existing static report assertions.
- Produces: a complete report set that preserves navigation, requirement mapping, and specialist coverage.

- [ ] **Step 1: Run complete tests and whitespace validation**

Run:

```powershell
python -m unittest tests.test_report_html -v
git diff --check
```

Expected: all tests PASS and no whitespace errors.

- [ ] **Step 2: Commit any regression correction**

If a regression correction was necessary, run:

```powershell
git add -- tests/test_report_html.py 01-投顾Agent汇报.html
git commit -m "test: verify advisor defense report"
```

## Self-Review

- Spec coverage: Task 1 covers full flow, seven tools, safety/identity, recommendation-to-execution handoff, event-memory loop, and implementation enhancements. Task 2 covers the global report regression suite.
- Placeholder scan: no undefined content or future implementation items remain.
- Consistency: all test anchors match the exact page labels and all flow nodes use code-aligned service boundaries.
