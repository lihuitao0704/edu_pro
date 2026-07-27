# 投顾 Agent 汇报内容覆盖 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the integrated advisor-report content with the richer temporary report content while preserving the integrated page’s report style and navigation.

**Architecture:** `01-投顾Agent汇报.html` remains the only served/integrated page and continues to load `reports.css`. Its body sections are rewritten as report-style cards, tables and flow diagrams using the approved content mapping; the temporary `01-投顾Agent汇报(2).html` is read-only source material.

**Tech Stack:** Static HTML5, existing `reports.css`, Python `unittest`.

## Global Constraints

- Modify only `01-投顾Agent汇报.html` and `tests/test_report_html.py`.
- Retain title, `reports.css`, previous/next links, demand mapping, no-external-resource behavior, and report-chain integration.
- Include the six approved content areas: pain points, dynamic profile/cache, seven tools, three engineering highlights, technology/compliance, and conclusion.
- State that formal C1-C5 changes require formal assessment and audit; behavioral signals may trigger review or conservative strategy only.
- Maintain recommendation-before-transaction separation, appropriateness filtering, risk warnings, and audit/confirmation boundaries.

---

### Task 1: Define the replacement-content contract

**Files:**

- Modify: `tests/test_report_html.py`
- Modify: `01-投顾Agent汇报.html`

**Interfaces:**

- Consumes: UTF-8 report HTML through `Path.read_text(encoding="utf-8")`.
- Produces: `ReportHtmlTest.test_advisor_report_covers_replacement_content_with_integrated_style`.

- [ ] **Step 1: Write the failing test**

Add this method to `ReportHtmlTest`:

```python
def test_advisor_report_covers_replacement_content_with_integrated_style(self):
    html = (ROOT / "01-投顾Agent汇报.html").read_text(encoding="utf-8")
    for anchor in (
        'href="00-总体汇报.html"', 'href="02-客服Agent汇报.html"',
        'href="reports.css"', "投顾 Agent 解决的核心痛点",
        "动态多表联查", "Cache-Aside", "七大核心工具",
        "Neo4j 同步失败", "默认 R1 推荐", "受控复核与保守策略",
        "LangChain", "从“经验推荐”到“证据推荐”",
        "不直接执行交易", "不修改正式风险评级", "需求映射",
    ):
        self.assertIn(anchor, html)
    for tool in (
        "smart_recommend", "profile_tool", "recommend_products", "asset_allocation",
        "analysis_holdings", "compare_customers", "graphrag_search",
    ):
        self.assertIn(tool, html)
    self.assertNotIn('href="01-投顾Agent汇报(2).html"', html)
```

- [ ] **Step 2: Verify failure**

```powershell
python -m unittest tests.test_report_html.ReportHtmlTest.test_advisor_report_covers_replacement_content_with_integrated_style -v
```

Expected: FAIL because the integrated report lacks required replacement-content anchors.

- [ ] **Step 3: Commit the red test**

```powershell
git add -- tests/test_report_html.py
git commit -m "test: define advisor report replacement contract"
```

### Task 2: Rewrite the integrated advisor report with the approved content

**Files:**

- Modify: `01-投顾Agent汇报.html`

**Interfaces:**

- Consumes: `01-投顾Agent汇报(2).html` as read-only source content and `reports.css` layout primitives.
- Produces: an integrated report whose navigation and report styling remain unchanged.

- [ ] **Step 1: Preserve the integration shell**

Keep these exact elements:

```html
<title>投顾 Agent｜项目汇报</title>
<link rel="stylesheet" href="reports.css">
<a href="00-总体汇报.html">上一页</a>
<a href="02-客服Agent汇报.html">下一页</a>
<footer class="footer"><span>当前实现 + 需求映射 / 投顾 Agent</span><a href="02-客服Agent汇报.html">客服 Agent →</a></footer>
```

- [ ] **Step 2: Add the core-value, pain-point and profile sections**

Replace the hero and first content sections with report-style HTML containing:

```html
<h1>从“人找策略”到“策略找人”</h1>
<section class="requirement"><strong>关键结论：</strong>LLM 编排七大工具；画像、风评、预警与适当性共同决定推荐范围，模型不直接给出交易结论。</section>
<h2>投顾 Agent 解决的核心痛点</h2>
<section class="grid two">…四张卡片：规模化效率、静态画像、风评脱节、数据缺少洞察…</section>
<h2>动态用户画像：多表事实 + Cache-Aside</h2>
<section class="grid two">…六表联查、实时统计、Redis TTL 7 天、更新后失效缓存…</section>
```

Use only existing `requirement`, `grid`, `card`, `tag` and `flow-diagram` classes.

- [ ] **Step 3: Add all seven tools and the three engineering highlights**

Add a `grid three` tool section with these exact tool headings: `smart_recommend`, `profile_tool`, `recommend_products`, `asset_allocation`, `analysis_holdings`, `compare_customers`, `graphrag_search`. Each card states its function and MySQL/Redis/Neo4j/Milvus source.

Add three flow-diagram cards with these headings and boundary text:

```html
<h3>Neo4j 同步失败：异步重试与可观测补偿</h3>
<p class="flow-note">MySQL 保留业务事实；Neo4j 是可重建投影，失败进入重试与人工介入队列。</p>
<h3>风评问卷弹窗与默认 R1 推荐</h3>
<p class="flow-note">风评缺失时提示问卷并采用 C1/R1 保守兜底；推荐不是交易执行。</p>
<h3>行为信号触发受控复核与保守策略</h3>
<p class="flow-note">行为偏差形成动态风险信号，触发正式复核或收紧候选池；不自动修改正式风险评级。</p>
```

- [ ] **Step 4: Add technical stack, compliance and conclusion**

Add a two-card technology/compliance section referencing LangChain, Profile/Holding/Recommendation/Allocation tools, Redis, MySQL, Neo4j and Milvus. Add conclusion cards containing the exact headings `从“经验推荐”到“证据推荐”`, `双重保护`, `数据一致性`, and `投顾不越权`.

The final boundary text must include:

```html
<p>AdvisorAgent <strong>不直接执行交易</strong>，也<strong>不修改正式风险评级</strong>；正式 C1-C5 变化只由正式风评与审计流程完成。</p>
```

Finish with the existing `需求映射` section.

- [ ] **Step 5: Run the focused contract test**

```powershell
python -m unittest tests.test_report_html.ReportHtmlTest.test_advisor_report_covers_replacement_content_with_integrated_style -v
```

Expected: PASS.

- [ ] **Step 6: Commit the report content**

```powershell
git add -- 01-投顾Agent汇报.html
git commit -m "docs: replace advisor report content"
```

### Task 3: Verify report-chain compatibility

**Files:**

- Modify only if verification exposes a defect: `01-投顾Agent汇报.html` or `tests/test_report_html.py`.

**Interfaces:**

- Consumes: report suite and target report page.
- Produces: regression-free integrated advisor report.

- [ ] **Step 1: Run full validation**

```powershell
python -m unittest tests.test_report_html -v
git diff --check
```

Expected: all tests PASS without whitespace errors.

- [ ] **Step 2: Commit any correction**

```powershell
git add -- tests/test_report_html.py 01-投顾Agent汇报.html
git commit -m "test: verify advisor report replacement"
```

## Self-Review

- Spec coverage: Task 2 includes every section from the temporary report and retains all integration and financial-governance constraints.
- Placeholder scan: exact files, test anchors, tools, headings, boundary wording and commands are specified.
- Consistency: the static test names and requires the same integrated page, navigation, tools and compliance language produced by Task 2.
