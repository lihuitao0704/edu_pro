# 持仓收益与产品推荐动画流程图 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an offline, auto-playable answer-defense flow diagram for the journey from portfolio-return inquiry to compliant product recommendations and feedback closure.

**Architecture:** A standalone HTML document contains the layered SVG flow graph, mock result cards, the 18-step narration data, and a small vanilla-JavaScript player. A focused static unit test protects the display contract; no backend services or real trading data are changed.

**Tech Stack:** HTML5, CSS custom properties, inline SVG, vanilla JavaScript, Python `unittest`.

## Global Constraints

- Create `持仓收益与推荐-动画流程图.html` as a standalone UTF-8 document with no remote assets or libraries.
- Preserve `记忆架构-动画流程图.html`; this is a separate answer-defense presentation page.
- Model 18 sequential steps covering authentication, orchestration, factual return calculation, multi-agent enrichment, compliant recommendation, SSE response, Outbox eventing, and observability.
- Treat MySQL as the source of truth for holdings, transactions, and return calculation; Redis and Neo4j are projections only.
- Apply risk/appropriateness/product-status/concentration filtering before historical-performance ranking; never promise yield or alter formal C1-C5 ratings from model output or user feedback.
- Support `prefers-reduced-motion` by retaining manual navigation while preventing automatic playback.

---

### Task 1: Define the animation page contract

**Files:**

- Modify: `tests/test_report_html.py`
- Create: `持仓收益与推荐-动画流程图.html`

**Interfaces:**

- Consumes: UTF-8 HTML through `Path.read_text(encoding="utf-8")`.
- Produces: `ReportHtmlTest.test_portfolio_recommendation_animation_page_has_complete_flow`.

- [ ] **Step 1: Write the failing test**

Add this method before the module’s main block:

```python
def test_portfolio_recommendation_animation_page_has_complete_flow(self):
    page = ROOT / "持仓收益与推荐-动画流程图.html"
    self.assertTrue(page.is_file())
    html = page.read_text(encoding="utf-8")
    for anchor in (
        "持仓收益率", "高收益产品", "HoldingTool", "RecommendationTool",
        "ProfileAgent", "RiskMonitor", "OutputSafetyFilter", "SSE",
        "Outbox", "Redis Pub/Sub", "MySQL", "Redis", "Milvus", "MinIO", "Neo4j",
        "适当性", "历史业绩不代表未来", "不自动改变正式 C1-C5 风险等级",
        "播放", "暂停", "上一步", "下一步", "重播", "prefers-reduced-motion",
    ):
        self.assertIn(anchor, html)
    self.assertIn("const steps = [", html)
    self.assertIn("steps.length", html)
    self.assertIn("<svg", html)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m unittest tests.test_report_html.ReportHtmlTest.test_portfolio_recommendation_animation_page_has_complete_flow -v
```

Expected: FAIL because `持仓收益与推荐-动画流程图.html` has not been created.

- [ ] **Step 3: Commit the red test**

```powershell
git add -- tests/test_report_html.py
git commit -m "test: define portfolio animation contract"
```

### Task 2: Build the standalone visual flow and narration data

**Files:**

- Create: `持仓收益与推荐-动画流程图.html`

**Interfaces:**

- Consumes: Task 1’s static contract and `docs/superpowers/specs/2026-07-27-portfolio-recommendation-animation-design.md`.
- Produces: `const steps`, SVG groups/paths addressed by id, and the targets `stepTitle`, `stepDetail`, `stepInput`, `stepOutput`, `stepStore`, `stepBoundary`, `status`.

- [ ] **Step 1: Create the semantic shell and player controls**

Create the document with no external scripts or stylesheets:

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>持仓收益与推荐｜金融智能助手动画流程图</title>
</head>
<body>
  <main class="page">
    <header class="hero"><p class="eyebrow">答辩演示 · 模拟数据</p><h1>持仓收益分析 → 合规产品推荐</h1></header>
    <section class="controls" aria-label="流程图播放器">
      <button id="prevStep">上一步</button><button id="playPause">播放</button>
      <button id="nextStep">下一步</button><button id="replay">重播</button>
      <label>播放速度 <select id="speed"><option value="800">快速</option><option value="1600" selected>标准</option><option value="2600">慢速</option></select></label>
      <p id="status" aria-live="polite"></p>
    </section>
    <section class="diagram-card"><svg viewBox="0 0 1640 1120" role="img" aria-label="持仓收益与产品推荐完整业务流程图">…</svg></section>
    <section class="step-panel"><p id="stepKicker"></p><h2 id="stepTitle"></h2><p id="stepDetail"></p><dl><div><dt>输入</dt><dd id="stepInput"></dd></div><div><dt>输出</dt><dd id="stepOutput"></dd></div><div><dt>数据来源</dt><dd id="stepStore"></dd></div><div><dt>合规边界</dt><dd id="stepBoundary"></dd></div></dl></section>
  </main>
</body>
</html>
```

- [ ] **Step 2: Add seven swimlanes, SVG nodes, connectors, and result cards**

Use these swimlane labels: `① 用户与权限边界`, `② 会话与意图编排`, `③ 持仓收益事实计算`, `④ Multi-Agent 数据/知识增强`, `⑤ 推荐与合规决策`, `⑥ 受控响应`, `⑦ 事件闭环与可观测性`.

Use `<g id="…" class="diagram-node">` nodes named `question`, `auth`, `inputSafety`, `orchestrator`, `memory`, `router`, `holding`, `returnCalc`, `profile`, `graph`, `nl2sql`, `rag`, `candidate`, `filter`, `advisor`, `risk`, `explanation`, `response`, `sse`, `outbox`, `eventBus`, `projection`, `trace`.

Every arriving path must be `<path id="eN" class="edge">`; use this node pattern:

```svg
<path id="e1" class="edge" d="M210 170H300" marker-end="url(#arrow)"/>
<g id="auth" class="diagram-node" transform="translate(300 124)">
  <rect class="node-card" width="170" height="96"/>
  <circle class="node-dot" cx="20" cy="20" r="7"/>
  <text class="node-title" x="34" y="26">认证与 RBAC</text>
  <text class="node-detail" x="16" y="54">actor / role / customer</text>
  <text class="node-detail" x="16" y="75">客户归属、会话范围</text>
</g>
```

Below the graph include labeled simulated-result cards with `data-result="returns"`, `data-result="recommendations"`, `data-result="disclosure"`. Show `+8.42%` 组合累计收益率, `-5.16%` 最大回撤, three product candidates, an appropriateness-filter note, and `历史业绩不代表未来`.

- [ ] **Step 3: Define all 18 steps and implement state changes**

Start the ordered data collection exactly as follows, then replace the comment with 16 complete objects:

```js
const steps = [
  {node:'question', edge:null, title:'用户提出复合投顾问题', input:'“我目前持仓收益率如何？给我推荐收益率高的产品。”', output:'建立带 customer_id 的受控请求', store:'认证主体与 session_id', boundary:'未完成身份、角色和客户归属校验，不读取任何持仓或产品数据。'},
  {node:'auth', edge:'e1', title:'认证、RBAC 与客户归属校验', input:'actor_id、role、customer_id、session_id', output:'授权范围与数据隔离上下文', store:'sys_user / 会话声明', boundary:'理财顾问只能访问获授权客户；跨客户访问直接拒绝。'},
  // inputSafety, memory/router, holding, returnCalc, profile, graph, nl2sql, rag,
  // candidate, filter, advisor, risk, explanation, response/sse, outbox, eventBus/projection/trace
];
```

Every object has `node`, `edge`, `title`, `input`, `output`, `store`, `boundary`. Step 12 states that risk/appropriateness/product-status/concentration filtering happens before historical-performance ranking. Step 15 includes `OutputSafetyFilter`, step 16 includes `SSE`, step 17 includes `Outbox`, and step 18 includes `Redis Pub/Sub`, projection refresh, and `TraceService`.

Use the following implementation, then wire it to buttons and node clicks:

```js
let step = 0;
let timer = null;
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const byId = id => document.getElementById(id);
const asArray = value => Array.isArray(value) ? value : [value];
const allNodes = [...document.querySelectorAll('.diagram-node')];
const allEdges = [...document.querySelectorAll('.edge')];

function renderStep() {
  const item = steps[step];
  const completed = steps.slice(0, step).flatMap(item => asArray(item.node));
  const activeNodes = asArray(item.node);
  const completedEdges = steps.slice(0, step).map(item => item.edge).filter(Boolean);
  allNodes.forEach(element => {
    element.classList.toggle('is-done', completed.includes(element.id));
    element.classList.toggle('is-active', activeNodes.includes(element.id));
  });
  allEdges.forEach(element => {
    element.classList.toggle('is-done', completedEdges.includes(element.id));
    element.classList.toggle('is-active', item.edge === element.id);
  });
  byId('stepKicker').textContent = `全链路演示 · 第 ${step + 1} / ${steps.length} 步`;
  byId('stepTitle').textContent = item.title;
  byId('stepDetail').textContent = item.output;
  byId('stepInput').textContent = item.input;
  byId('stepOutput').textContent = item.output;
  byId('stepStore').textContent = item.store;
  byId('stepBoundary').textContent = item.boundary;
  byId('status').textContent = `当前讲解：第 ${step + 1} / ${steps.length} 步`;
  byId('prevStep').disabled = step === 0;
  byId('nextStep').disabled = step === steps.length - 1;
}
```

`play()` toggles an interval using `Number(byId('speed').value)`, stops at the final step, and reports manual-navigation mode without starting an interval when reduced motion is active. Manual navigation clears the timer. `replay` resets to step zero, renders, then starts unless reduced motion is active.

- [ ] **Step 4: Add visual, motion, and mobile-accessibility CSS**

Include these state semantics:

```css
.diagram-node.is-active .node-card { stroke: var(--brand); stroke-width: 3; filter: drop-shadow(0 7px 9px rgba(11,123,130,.18)); }
.diagram-node.is-done .node-card { fill: #eefafa; stroke: #78b6b2; }
.edge.is-active { stroke: var(--brand); stroke-width: 4; stroke-dasharray: 10 7; animation: dash .75s linear infinite; }
.edge.is-done { stroke: #73aaa9; stroke-width: 3; }
@media (prefers-reduced-motion: reduce) { .edge.is-active { animation: none; } *, *::before, *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; } }
```

Set the graph’s container to horizontal scrolling with an SVG minimum width of 1180px, preserve focus-visible outlines on controls, and label cards with text rather than color alone.

- [ ] **Step 5: Run the focused contract test**

```powershell
python -m unittest tests.test_report_html.ReportHtmlTest.test_portfolio_recommendation_animation_page_has_complete_flow -v
```

Expected: PASS.

- [ ] **Step 6: Commit the working page**

```powershell
git add -- 持仓收益与推荐-动画流程图.html
git commit -m "docs: add portfolio recommendation animation"
```

### Task 3: Validate the completed artifact

**Files:**

- Modify only if validation identifies a defect: `持仓收益与推荐-动画流程图.html` or `tests/test_report_html.py`.

**Interfaces:**

- Consumes: standalone page and the report test suite.
- Produces: a verified offline, presentation-ready page.

- [ ] **Step 1: Run static and regression validation**

```powershell
python -m unittest tests.test_report_html -v
git diff --check
```

Expected: all tests PASS and no whitespace errors.

- [ ] **Step 2: Open and inspect the local page**

```powershell
Start-Process "D:\edu_pro\持仓收益与推荐-动画流程图.html"
```

Verify first-step rendering, previous/next state, stop at step 18, replay, speed selection, node-click navigation, simulated-card transitions, and reduced-motion behavior.

- [ ] **Step 3: Commit any validation correction**

```powershell
git add -- tests/test_report_html.py 持仓收益与推荐-动画流程图.html
git commit -m "test: verify portfolio recommendation animation"
```

## Self-Review

- Spec coverage: Task 1 makes the artifact testable; Task 2 implements the seven lanes, 18 steps, factual return calculation, enrichment, filtering-before-ranking, response safety, SSE, Outbox, projections, and traceability; Task 3 verifies static and manual behavior.
- Placeholder scan: every file, control id, node id, test assertion, required sequence, and validation command is specified. The task explicitly requires replacement of the 16-object sample comment.
- Type consistency: all step records share `node`, `edge`, `title`, `input`, `output`, `store`, `boundary`; `renderStep()` consumes only these names.
