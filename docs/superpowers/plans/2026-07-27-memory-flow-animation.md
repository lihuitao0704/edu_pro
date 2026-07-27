# Memory Flow Animation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create an offline, minimal animated flow-diagram page that presents the project’s memory read and event-write architecture step by step.

**Architecture:** A single HTML file holds the visual nodes, SVG connectors, route-step data, and a small controller. JavaScript updates the active/completed node state and the explanation panel; CSS uses transform/opacity and stroke-dashoffset only for meaningful flow movement.

**Tech Stack:** HTML5, CSS custom properties, inline SVG, vanilla JavaScript, Python `unittest`.

## Global Constraints

- Create `记忆架构-动画流程图.html` as a standalone offline document without remote assets or libraries.
- Implement both “读取路径” and “写入路径” as step data with previous/next/play/pause/replay controls.
- Include Redis, MySQL, Milvus, MinIO and Neo4j; state MySQL as the business fact source.
- Preserve reduced-motion usability with `prefers-reduced-motion` and manual controls.
- Never portray cache, retrieval, graph projection, or model output as able to alter formal C1-C5 ratings or bypass transaction confirmation.

---

### Task 1: Add a failing structural test for the animation page

**Files:**
- Modify: `tests/test_report_html.py`
- Create: `记忆架构-动画流程图.html`

**Interfaces:**
- Consumes: UTF-8 static HTML through `Path.read_text`.
- Produces: a checked contract for required paths, stores, controls, and accessibility hooks.

- [ ] **Step 1: Write the failing test**

Add this test method:

```python
def test_memory_animation_page_has_two_routes_and_player_controls(self):
    page = ROOT / "记忆架构-动画流程图.html"
    self.assertTrue(page.is_file())
    html = page.read_text(encoding="utf-8")
    for anchor in (
        "读取路径", "写入路径", "播放", "暂停", "上一步", "下一步", "重播",
        "Redis", "MySQL", "Milvus", "MinIO", "Neo4j", "业务事实源",
        "Memory Manager", "Outbox", "Redis Pub/Sub", "prefers-reduced-motion",
        "不修改正式 C1-C5 风险评级",
    ):
        self.assertIn(anchor, html)
    self.assertIn("readSteps", html)
    self.assertIn("writeSteps", html)
    self.assertIn("<svg", html)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m unittest tests.test_report_html.ReportHtmlTest.test_memory_animation_page_has_two_routes_and_player_controls -v
```

Expected: FAIL because the standalone animation page does not exist.

- [ ] **Step 3: Create the animation page**

Create `记忆架构-动画流程图.html` with these required components:

```html
<button data-route="read">读取路径</button>
<button data-route="write">写入路径</button>
<button id="prevStep">上一步</button>
<button id="playPause">播放</button>
<button id="nextStep">下一步</button>
<button id="replay">重播</button>
<svg aria-label="记忆架构数据流转图">...</svg>
<script>
const readSteps = [/* 请求、编排、Memory Manager、Redis、MySQL、Milvus/MinIO、Neo4j、响应 */];
const writeSteps = [/* 事实、Outbox、Relay、Pub/Sub、缓存/图谱/审计、下次读取 */];
</script>
```

Each step object supplies `node`, `edge`, `title`, `detail`, `store`, and `boundary`. On every state change, mark earlier nodes as `.done`, current node/edge as `.active`, update the current-step panel, and set `aria-live` status text. Use `setInterval` for autoplay, clear it on pause/route change, and honor reduced motion by disabling automatic playback.

- [ ] **Step 4: Run the test to verify it passes**

Run:

```powershell
python -m unittest tests.test_report_html.ReportHtmlTest.test_memory_animation_page_has_two_routes_and_player_controls -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add -- tests/test_report_html.py 记忆架构-动画流程图.html
git commit -m "docs: add animated memory flow diagram"
```

### Task 2: Verify the full report set

**Files:**
- Modify if verification uncovers an issue: `记忆架构-动画流程图.html` or `tests/test_report_html.py`.

**Interfaces:**
- Consumes: full static report suite and the new offline page.
- Produces: a clean, regression-free report collection.

- [ ] **Step 1: Run full tests and whitespace validation**

Run:

```powershell
python -m unittest tests.test_report_html -v
git diff --check
```

Expected: all tests PASS with no whitespace errors.

- [ ] **Step 2: Commit correction if required**

If a correction was needed, run:

```powershell
git add -- tests/test_report_html.py 记忆架构-动画流程图.html
git commit -m "test: verify animated memory flow"
```

## Self-Review

- Spec coverage: Task 1 covers the dual path, playback controls, five stores, source-of-truth boundary, SVG flow, and reduced-motion fallback; Task 2 covers regression verification.
- Placeholder scan: every node group, control, test anchor and command is defined.
- Consistency: the exact route names and JavaScript arrays match the static test contract.
