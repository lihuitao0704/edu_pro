# 多 Agent 算法决策章节 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a concise, compliant six-algorithm decision chapter to the Multi-Agent architecture defense page.

**Architecture:** Extend the existing offline report page with one heading, an explanatory requirement band, and six existing-style cards in a `grid three` section. A static report test verifies all six techniques and their model-governance boundaries.

**Tech Stack:** Static HTML5, existing `reports.css`, Python `unittest`.

## Global Constraints

- Modify only `06-多Agent联动与架构汇报.html` and `tests/test_report_html.py`.
- Keep all 14 existing business scenarios, report navigation, local asset references, and offline behavior unchanged.
- Present models as assistive signals: Bayesian preference updates, clustering, collaborative filtering, graphs, and anomaly scores must not directly alter C1-C5 ratings or bypass appropriate review.
- Apply LightGBM Rank only after product status, risk, appropriateness, and concentration filtering; historical performance does not promise future returns.

---

### Task 1: Define the algorithm-section contract

**Files:**

- Modify: `tests/test_report_html.py`
- Modify: `06-多Agent联动与架构汇报.html`

**Interfaces:**

- Consumes: UTF-8 page source through `Path.read_text(encoding="utf-8")`.
- Produces: `ReportHtmlTest.test_multi_agent_report_explains_algorithmic_decisions`.

- [ ] **Step 1: Write the failing test**

Add this method to `ReportHtmlTest`:

```python
def test_multi_agent_report_explains_algorithmic_decisions(self):
    html = (ROOT / "06-多Agent联动与架构汇报.html").read_text(encoding="utf-8")
    for anchor in (
        "算法驱动的智能决策", "贝叶斯更新", "高斯混合模型", "GMM",
        "UserCF", "协同过滤", "LightGBM Rank", "Learning-to-Rank",
        "知识图谱 Agent", "Isolation Forest", "异常概率 92%",
        "不自动修改正式 C1-C5 风险等级", "先进入合规候选池",
        "历史表现不构成未来收益承诺", "人工审核",
    ):
        self.assertIn(anchor, html)
    self.assertGreaterEqual(html.count('class="algorithm-card"'), 6)
```

- [ ] **Step 2: Verify the test fails**

Run:

```powershell
python -m unittest tests.test_report_html.ReportHtmlTest.test_multi_agent_report_explains_algorithmic_decisions -v
```

Expected: FAIL because the algorithm section is absent.

- [ ] **Step 3: Commit the red test**

```powershell
git add -- tests/test_report_html.py
git commit -m "test: define algorithm report contract"
```

### Task 2: Add the compliant six-card algorithm chapter

**Files:**

- Modify: `06-多Agent联动与架构汇报.html:105`

**Interfaces:**

- Consumes: the existing `grid three`, `card`, `requirement`, and `small` CSS classes plus the contract from Task 1.
- Produces: a `section.algorithm-card` collection placed directly before `<h2>从需求分阶段到金融级协同</h2>`.

- [ ] **Step 1: Insert the chapter shell after the scenario section**

Insert this immediately after the closing `</section>` that follows 场景 14:

```html
<h2>算法驱动的智能决策</h2>
<section class="requirement"><strong>模型治理原则：</strong>权限、产品状态、适当性、风险和集中度先形成合规候选池；算法只在授权数据范围内完成偏好更新、用户分层、候选扩展、排序、关系解释或异常预警，不替代人工审核和正式风险评级。</section>
<section class="grid three algorithm-grid">
  <!-- six cards below -->
</section>
```

- [ ] **Step 2: Add cards one to three**

Inside `algorithm-grid`, add exactly these three `algorithm-card` articles:

```html
<article class="card algorithm-card"><h3>① 贝叶斯更新｜动态用户画像</h3><p><b>机制：</b>以“稳健 60%、积极 40%”为先验；连续、有效的权益类交易形成证据后，动态更新为“稳健 40%、积极 60%”。</p><p><b>作用：</b>输出偏好概率与置信度，调整沟通策略和候选权重。</p><p class="small"><b>边界：</b>动态偏好信号不自动修改正式 C1-C5 风险等级。</p></article>
<article class="card algorithm-card"><h3>② GMM｜无监督用户分层</h3><p><b>机制：</b>高斯混合模型（GMM）综合资产规模、风险承受力、交易频率、期限和偏好，形成稳健型、高净值进取型、投资新手等客群。</p><p><b>作用：</b>用于分层服务、产品匹配和合规运营触达。</p><p class="small"><b>边界：</b>聚类标签不替代风险测评或产品适当性结论。</p></article>
<article class="card algorithm-card"><h3>③ UserCF｜协同过滤候选召回</h3><p><b>机制：</b>在风险边界和行为相近的用户群中，发现“喜欢 A 产品的用户也认可 B 产品”的关联。</p><p><b>作用：</b>把 B 作为候选参考，扩展可解释的产品召回池。</p><p class="small"><b>边界：</b>协同过滤候选仍须经过产品状态、风险等级、适当性和集中度筛选。</p></article>
```

- [ ] **Step 3: Add cards four to six**

Continue the same section with these three articles:

```html
<article class="card algorithm-card"><h3>④ LightGBM Rank｜Learning-to-Rank 排序</h3><p><b>机制：</b>以风险匹配、期限、流动性、偏好、组合互补性和历史表现为特征，用 LightGBM Rank 计算匹配度并排序。</p><p><b>作用：</b>在合规候选池内选择最适合的 Top N 产品。</p><p class="small"><b>边界：</b>先进入合规候选池，再排序；历史表现不构成未来收益承诺。</p></article>
<article class="card algorithm-card"><h3>⑤ 知识图谱 Agent｜图算法关系发现</h3><p><b>机制：</b>基于客户—基金—行业—主题关系与图算法发现偏好；例如偏好新能源基金时，扩展检索新能源产业链候选产品。</p><p><b>作用：</b>提供关联路径和推荐理由，使候选扩展可解释。</p><p class="small"><b>边界：</b>图谱用于关系解释和候选扩展，不作为交易结算或正式评级依据。</p></article>
<article class="card algorithm-card"><h3>⑥ Isolation Forest｜异常交易检测</h3><p><b>机制：</b>学习客户常态金额、频次、产品类型和时点；平时买基金却单日买入 500 万股票时，可识别异常概率 92%。</p><p><b>作用：</b>触发人工审核、资金保护或风险提示。</p><p class="small"><b>边界：</b>异常分数是预警信号，不自动拒绝交易或改变正式风险等级。</p></article>
```

- [ ] **Step 4: Run the focused test**

```powershell
python -m unittest tests.test_report_html.ReportHtmlTest.test_multi_agent_report_explains_algorithmic_decisions -v
```

Expected: PASS.

- [ ] **Step 5: Commit the report**

```powershell
git add -- 06-多Agent联动与架构汇报.html
git commit -m "docs: add multi-agent algorithm section"
```

### Task 3: Run regression checks

**Files:**

- Modify only if verification identifies a defect: `06-多Agent联动与架构汇报.html` or `tests/test_report_html.py`.

**Interfaces:**

- Consumes: complete report suite.
- Produces: a regression-free offline report collection.

- [ ] **Step 1: Validate all report pages**

```powershell
python -m unittest tests.test_report_html -v
git diff --check
```

Expected: all tests PASS and no whitespace errors.

- [ ] **Step 2: Commit a correction if one was required**

```powershell
git add -- tests/test_report_html.py 06-多Agent联动与架构汇报.html
git commit -m "test: verify multi-agent algorithm section"
```

## Self-Review

- Spec coverage: Task 2 implements all six approved techniques, their roles, examples, and guardrails in one answer-defense chapter.
- Placeholder scan: every card, test anchor, insertion point, command, and commit target is explicit.
- Consistency: the test anchors exactly match the six-card copy and the page retains the existing `grid three` component pattern.
