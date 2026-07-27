# Defense Report Narrative Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the financial report set into a concise, first-person defense narrative with a single previous/next navigation sequence.

**Architecture:** Treat `00-index.html` as the non-linear landing page and eight report pages as a fixed linear sequence. Preserve each report's existing flow diagram and requirement mapping; add only role-specific conclusion, evidence, and boundary copy drawn from `答辩逐字稿-全角色.md`.

**Tech Stack:** Static HTML5, shared `reports.css`, Python `unittest`, Git.

## Global Constraints

- Use `00-index.html` and `07-记忆架构汇报.html` as the replacements for deleted `index.html` and `记忆架构.html`.
- In every report-page top navigation, render exactly two links: `上一页` and `下一页`.
- Use concise answerer voice and direct headings such as “核心结论”“亮点与边界”; never add the title “我会这样讲”.
- Retain requirement mapping, flow diagrams, code-aligned claims, and the existing specialist anchors checked by `tests/test_report_html.py`.
- Do not stage or modify unrelated user worktree files.

---

### Task 1: Encode the replacement filenames and linear navigation contract

**Files:**
- Modify: `tests/test_report_html.py`
- Modify: `00-index.html`
- Modify: `00-总体汇报.html`
- Modify: `01-投顾Agent汇报.html`
- Modify: `02-客服Agent汇报.html`
- Modify: `03-风控Agent汇报.html`
- Modify: `04-业务操作Agent汇报.html`
- Modify: `05-数据分析Agent汇报.html`
- Modify: `06-多Agent联动与架构汇报.html`
- Modify: `07-记忆架构汇报.html`

**Interfaces:**
- Consumes: the filename chain declared in `docs/superpowers/specs/2026-07-27-defense-report-narrative-design.md`.
- Produces: all live report navigation links resolve within the new nine-page report set.

- [ ] **Step 1: Write the failing test**

Add a navigation matrix and assert exact labels and targets:

```python
REPORT_CHAIN = [
    "00-index.html", "00-总体汇报.html", "01-投顾Agent汇报.html",
    "02-客服Agent汇报.html", "03-风控Agent汇报.html",
    "04-业务操作Agent汇报.html", "05-数据分析Agent汇报.html",
    "06-多Agent联动与架构汇报.html", "07-记忆架构汇报.html",
]

def test_report_navigation_is_a_single_previous_next_chain(self):
    for index, filename in enumerate(REPORT_CHAIN[1:], start=1):
        text = (ROOT / filename).read_text(encoding="utf-8")
        previous = REPORT_CHAIN[index - 1]
        following = REPORT_CHAIN[index + 1] if index < len(REPORT_CHAIN) - 1 else REPORT_CHAIN[0]
        self.assertIn(f'<a href="{previous}">上一页</a>', text)
        self.assertIn(f'<a href="{following}">下一页</a>', text)
```

Also update the report filename registry to reference `00-index.html` and `07-记忆架构汇报.html`, and assert that no report contains `href="index.html"` or `href="记忆架构.html"`.

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m unittest tests.test_report_html.ReportHtmlTest.test_report_navigation_is_a_single_previous_next_chain -v
```

Expected: failure because existing pages have directory, overall, or role-specific labels instead of the exact two-link contract.

- [ ] **Step 3: Implement the navigation matrix**

Replace each report page's existing `<nav class="nav">...</nav>` with the exact previous/next markup from this table:

| Page | Previous | Next |
| --- | --- | --- |
| `00-总体汇报.html` | `00-index.html` | `01-投顾Agent汇报.html` |
| `01-投顾Agent汇报.html` | `00-总体汇报.html` | `02-客服Agent汇报.html` |
| `02-客服Agent汇报.html` | `01-投顾Agent汇报.html` | `03-风控Agent汇报.html` |
| `03-风控Agent汇报.html` | `02-客服Agent汇报.html` | `04-业务操作Agent汇报.html` |
| `04-业务操作Agent汇报.html` | `03-风控Agent汇报.html` | `05-数据分析Agent汇报.html` |
| `05-数据分析Agent汇报.html` | `04-业务操作Agent汇报.html` | `06-多Agent联动与架构汇报.html` |
| `06-多Agent联动与架构汇报.html` | `05-数据分析Agent汇报.html` | `07-记忆架构汇报.html` |
| `07-记忆架构汇报.html` | `06-多Agent联动与架构汇报.html` | `00-index.html` |

Each replacement has exactly this shape:

```html
<nav class="nav">
  <a href="PREVIOUS_FILE">上一页</a>
  <a href="NEXT_FILE">下一页</a>
</nav>
```

Update footer links to the same `NEXT_FILE` for each report. Update `00-index.html` cards to point to `07-记忆架构汇报.html` and remove stale deleted-file links.

- [ ] **Step 4: Run the navigation test to verify it passes**

Run:

```powershell
python -m unittest tests.test_report_html.ReportHtmlTest.test_report_navigation_is_a_single_previous_next_chain -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add -- tests/test_report_html.py 00-index.html 00-总体汇报.html 01-投顾Agent汇报.html 02-客服Agent汇报.html 03-风控Agent汇报.html 04-业务操作Agent汇报.html 05-数据分析Agent汇报.html 06-多Agent联动与架构汇报.html 07-记忆架构汇报.html
git commit -m "docs: unify report navigation"
```

### Task 2: Add concise role-specific defense narratives

**Files:**
- Modify: `00-总体汇报.html`
- Modify: `01-投顾Agent汇报.html`
- Modify: `02-客服Agent汇报.html`
- Modify: `03-风控Agent汇报.html`
- Modify: `04-业务操作Agent汇报.html`
- Modify: `05-数据分析Agent汇报.html`
- Modify: `06-多Agent联动与架构汇报.html`
- Modify: `07-记忆架构汇报.html`
- Modify: `tests/test_report_html.py`

**Interfaces:**
- Consumes: `答辩逐字稿-全角色.md` role sections and existing page-specific implementation claims.
- Produces: one unique “核心结论” and one unique “亮点与边界” section per report.

- [ ] **Step 1: Write the failing test**

Add a test with unique role anchors and the forbidden generic heading:

```python
ROLE_NARRATIVE_ANCHORS = {
    "00-总体汇报.html": ("核心结论", "统一路由"),
    "01-投顾Agent汇报.html": ("策略找人", "smart_recommend"),
    "02-客服Agent汇报.html": ("有依据的回答", "转人工"),
    "03-风控Agent汇报.html": ("风险闭环", "正式风险评级"),
    "04-业务操作Agent汇报.html": ("受控业务动作", "P0-P5"),
    "05-数据分析Agent汇报.html": ("受控的自然语言分析", "洞察白名单"),
    "06-多Agent联动与架构汇报.html": ("可靠协作", "Outbox"),
    "07-记忆架构汇报.html": ("不混淆事实", "业务事实源"),
}

def test_reports_have_distinct_defense_narratives(self):
    for filename, anchors in ROLE_NARRATIVE_ANCHORS.items():
        text = (ROOT / filename).read_text(encoding="utf-8")
        for anchor in anchors:
            self.assertIn(anchor, text)
        self.assertNotIn("我会这样讲", text)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m unittest tests.test_report_html.ReportHtmlTest.test_reports_have_distinct_defense_narratives -v
```

Expected: failure for pages that do not yet contain their new unique narrative anchors.

- [ ] **Step 3: Implement the compact narrative sections**

For each report, insert a short first-person “核心结论” block after the hero and a short “亮点与边界” block before the footer. Use the following approved copy themes:

```html
<!-- 00-总体汇报.html -->
<section class="requirement"><strong>核心结论：</strong>我将系统设计为“统一路由、专业分工、事件联动、全程留痕”的金融服务链路；Multi-Agent 的价值不在数量，而在每项能力都可复用、可追溯、可约束。</section>

<!-- 01-投顾Agent汇报.html -->
<section class="requirement"><strong>核心结论：</strong>我希望把投顾从“人找策略”推进到“策略找人”。系统以客户画像、风险约束和产品匹配驱动推荐；当画像缺失或风评过期时，先提醒测评并降级到低风险产品，而不是假装了解客户。</section>

<!-- 02-客服Agent汇报.html -->
<section class="requirement"><strong>核心结论：</strong>我把客服定位为有依据的服务入口：先检索知识与召回上下文，再给出带风险提示的回答；知识不足时明确转人工，不让模型编造金融结论。</section>

<!-- 03-风控Agent汇报.html -->
<section class="requirement"><strong>核心结论：</strong>我把风控设计成风险闭环：识别、预警、处置、反馈和审计连续发生。动态信号可以约束推荐和触发核验，但不能跳过测评流程直接修改正式风险评级。</section>

<!-- 04-业务操作Agent汇报.html -->
<section class="requirement"><strong>核心结论：</strong>我将自然语言转成受控业务动作，而不是直接执行命令。每一次申购、赎回或转账都经过权限、参数、适当性、状态和二次确认等 P0-P5 校验。</section>

<!-- 05-数据分析Agent汇报.html -->
<section class="requirement"><strong>核心结论：</strong>我让员工能够自然语言看数据，同时把 SQL 执行权牢牢留在规则层。只有通过五道闸门且满足洞察白名单的结果，才能成为其他 Agent 的受控输入。</section>

<!-- 06-多Agent联动与架构汇报.html -->
<section class="requirement"><strong>核心结论：</strong>我用 Router 决定“谁处理”，用 Outbox 与事件总线决定“处理后谁必须联动”。这样专业能力可以独立演进，业务事实仍能可靠一致。</section>

<!-- 07-记忆架构汇报.html -->
<section class="requirement"><strong>核心结论：</strong>我让 Agent 记住客户，但不混淆事实、缓存和推断。MySQL 是业务事实源，Redis 提供时效，Milvus 和 Neo4j 只为检索、关系解释与辅助决策提供证据。</section>
```

Use an additional compact `grid two` section per page to state the role-specific highlight and boundary from the specification. Do not duplicate the navigation or repeat another report's primary mechanism.

- [ ] **Step 4: Run the narrative test to verify it passes**

Run:

```powershell
python -m unittest tests.test_report_html.ReportHtmlTest.test_reports_have_distinct_defense_narratives -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add -- tests/test_report_html.py 00-总体汇报.html 01-投顾Agent汇报.html 02-客服Agent汇报.html 03-风控Agent汇报.html 04-业务操作Agent汇报.html 05-数据分析Agent汇报.html 06-多Agent联动与架构汇报.html 07-记忆架构汇报.html
git commit -m "docs: add defense narratives to reports"
```

### Task 3: Verify the complete offline report set

**Files:**
- Modify: `tests/test_report_html.py`
- Modify if required by verification: any file listed in Tasks 1–2.

**Interfaces:**
- Consumes: static report files and all existing tests.
- Produces: a report set that can be opened locally without references to removed filenames.

- [ ] **Step 1: Write the failing test**

Add a local-link check covering all report pages:

```python
def test_report_pages_do_not_reference_replaced_filenames(self):
    for filename in REPORT_CHAIN:
        text = (ROOT / filename).read_text(encoding="utf-8")
        self.assertNotIn('href="index.html"', text)
        self.assertNotIn('href="记忆架构.html"', text)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m unittest tests.test_report_html.ReportHtmlTest.test_report_pages_do_not_reference_replaced_filenames -v
```

Expected: failure until all header/footer/card links use the replacement filenames.

- [ ] **Step 3: Correct remaining stale references**

Update any stale header, footer, directory-card, or test-registry references so all local links use `00-index.html` and `07-记忆架构汇报.html`. Do not alter external assets such as `reports.css` or `report-assets/financial-ai-architecture.png`.

- [ ] **Step 4: Run all report tests and whitespace validation**

Run:

```powershell
python -m unittest tests.test_report_html -v
git diff --check
```

Expected: all tests PASS and no whitespace errors.

- [ ] **Step 5: Commit**

```powershell
git add -- tests/test_report_html.py 00-index.html 00-总体汇报.html 01-投顾Agent汇报.html 02-客服Agent汇报.html 03-风控Agent汇报.html 04-业务操作Agent汇报.html 05-数据分析Agent汇报.html 06-多Agent联动与架构汇报.html 07-记忆架构汇报.html
git commit -m "test: verify defense report navigation"
```

## Self-Review

- Spec coverage: Task 1 implements the replacement filenames and exact navigation; Task 2 implements concise first-person page narratives without the prohibited title; Task 3 prevents stale filename regressions and runs all existing report checks.
- Placeholder scan: no TBD/TODO or undefined future work remains.
- Consistency: every navigation target uses the same `REPORT_CHAIN`; all new tests read the same UTF-8 HTML files.
