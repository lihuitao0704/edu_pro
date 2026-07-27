# 金融多 Agent 汇报 HTML 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 创建八个可离线打开的简约 HTML 汇报页，以流程图优先的方式说明金融多 Agent 平台的业务价值、技术实现与协作闭环。

**Architecture:** 在项目根目录创建入口页和七份专题页；页面使用 HTML5、CSS3 与内联 SVG/HTML 流程图，不依赖 CDN 或构建步骤。用 Python 标准库 `unittest` 静态检查文件集、流程图、导航和离线依赖。

**Tech Stack:** HTML5、CSS3、内联 SVG、原生 JavaScript、Python `unittest`。

## Global Constraints

- 使用 UTF-8，不改动现有业务代码、数据库、Vue 应用或接口。
- 事实依据限定于项目当前源代码、`ARCHITECTURE.md`、`docs/DEMO.md`、`requirements.txt` 与 `frontend/package.json`。
- 每个专题页至少含一张 `class="flow-diagram"` 主流程图；总体页与联动页以流程图为主要讲解骨架。
- 不使用 CDN、外部字体、外部图片、在线图表库或网络脚本。
- 显式区分“当前实现”“策略约束”“演进方向”；不得把未实现能力描述为当前能力。

---

### Task 1: 建立失败的静态报告合同测试

**Files:**
- Create: `tests/test_report_html.py`

**Interfaces:**
- Consumes: 根目录八个汇报 HTML 文件。
- Produces: `python -m unittest tests.test_report_html -v`。

- [ ] **Step 1: 写入最小测试**

测试以 `Path(__file__).resolve().parents[1]` 为项目根目录，逐一检查下列文件存在：`index.html`、`00-总体汇报.html`、`01-投顾Agent汇报.html`、`02-客服Agent汇报.html`、`03-风控Agent汇报.html`、`04-业务操作Agent汇报.html`、`05-数据分析Agent汇报.html`、`06-多Agent联动与架构汇报.html`。每个文件读取 UTF-8 文本，并断言包含 `<meta charset="UTF-8">`、`index.html`、`class="flow-diagram"`，且不包含 `http://` 或 `https://`。

- [ ] **Step 2: 验证 RED**

Run: `python -m unittest tests.test_report_html -v`
Expected: FAIL；错误明确说明至少一个报告文件尚不存在。

- [ ] **Step 3: 在完成页面后验证 GREEN**

Run: `python -m unittest tests.test_report_html -v`
Expected: PASS；八个文件全部满足离线页面合同。

### Task 2: 实现入口页和总体汇报页

**Files:**
- Create: `index.html`
- Create: `00-总体汇报.html`

**Interfaces:**
- Consumes: 项目技术栈、分层架构和六类 Agent 事实。
- Produces: 入口目录和从用户请求到数据/知识底座的全景流程讲解。

- [ ] **Step 1: 创建入口页**

实现八张相对链接卡片：总体、投顾、客服、风控、业务操作、数据分析、联动与架构；另含总览流程图“客户/员工 → 统一入口 → 六类 Agent → 数据与知识底座”。

- [ ] **Step 2: 创建总体页**

按“结论、业务价值、技术栈、全局流程图、六类 Agent 职责、总结”组织。流程图必须展示 Vue 3 → FastAPI → Router/ChatOrchestrator → Agent → 服务/工具/规则 → MySQL/Redis/Neo4j/Milvus/MinIO。技术栈卡片列出 Python/FastAPI/SQLAlchemy/LangChain 和 Vue 3/TypeScript/Vite/Pinia/Element Plus/ECharts。

- [ ] **Step 3: 共享视觉规则**

每页内联相同 CSS token：`--ink`、`--brand`、`--paper`、`--line`；内容宽度最大 1180px，720px 以下单列；实现 `:focus-visible` 与 `prefers-reduced-motion`。

### Task 3: 实现五份业务 Agent 专题页

**Files:**
- Create: `01-投顾Agent汇报.html`
- Create: `02-客服Agent汇报.html`
- Create: `03-风控Agent汇报.html`
- Create: `04-业务操作Agent汇报.html`
- Create: `05-数据分析Agent汇报.html`

**Interfaces:**
- Consumes: `advisor_agent.py`、`customer_agent.py`、`risk_monitor_service.py`、`transaction_flow_service.py`、`operator_agent.py`、`nl2sql_service.py`。
- Produces: 五份各自可讲 5 至 10 分钟的 Agent 报告，页尾按报告顺序相互跳转。

- [ ] **Step 1: 投顾 Agent 页**

主流程图为“客户提问 → 画像/记忆召回 → 风险与适当性约束 → 产品筛选/排序与配置 → GraphRAG 解释 → SSE 流式答复”。说明 LangChain 工具调用、画像/持仓/推荐/配置工具、Redis、MySQL、Neo4j、Milvus；突出推荐不超出客户承受范围和风险事件可收紧推荐范围。

- [ ] **Step 2: 客服 Agent 页**

主流程图为“问题识别 → 会话上下文 → 知识/RAG 检索 → 风险上下文注入 → 答复与情绪信号”。说明情绪仅是短期行为信号，绝不直接改变 C1-C5 正式等级。

- [ ] **Step 3: 风控 Agent 页**

主流程图为“交易请求 → 事前评估 → 允许/复核/拦截 → 风险预警 → 工单 → 动态约束通知”。说明四维画像、熔断规则、`RiskMonitorService`、预警生命周期，并区分正式风险等级与动态风险标记。

- [ ] **Step 4: 业务操作 Agent 页**

主流程图为“自然语言指令 → 参数提取 → 身份/权限 → P0-P5 校验 → 二次确认 → 执行与审计 → 领域事件”。覆盖申购、赎回、转账、重新评估、信息更新、可疑上报、工单和查询。

- [ ] **Step 5: 数据分析 Agent 页**

主流程图为“自然语言问题 → Schema 选择/Few-shot → LLM 生成 SQL → SELECT 白名单校验 → 100 行受限执行 → 结果解释 → 合格洞察发布”。说明禁止写操作、表范围控制和“结构化且有证据”的洞察门槛。

### Task 4: 实现多 Agent 联动与全景架构页

**Files:**
- Create: `06-多Agent联动与架构汇报.html`
- Modify: `tests/test_report_html.py`

**Interfaces:**
- Consumes: Router、ChatOrchestrator、Outbox、Redis `event:agent_domain`、事件幂等消费和 MySQL 事实源。
- Produces: 一份终章报告，包含分层架构与三条跨 Agent 闭环。

- [ ] **Step 1: 绘制全景架构流程图**

从 Vue 前端到 FastAPI/API，再到 Router/ChatOrchestrator、六类 Agent、服务/工具/规则和五类数据基础设施；标注 HTTP/SSE、SQLAlchemy Async、Redis Pub/Sub、向量检索、图谱查询。

- [ ] **Step 2: 绘制风险交易闭环图**

业务操作 → 事前评估 → 风险预警 → Outbox → Redis 广播 → 画像/投顾/客服消费；说明 `event_id + consumer` 幂等与“不自动改变正式风险等级”的约束。

- [ ] **Step 3: 绘制推荐反馈和分析洞察闭环图**

推荐拒绝反馈 → 画像偏好信号 → 下一次候选池排除；NL2SQL 受控洞察 → 投顾/风控/画像消费。两图标明它们是策略信号而非正式调级。

- [ ] **Step 4: 扩展测试断言**

增加逐页关键词断言：投顾包含 `GraphRAG`；客服包含 `情绪`；风控包含 `事前`；业务操作包含 `二次确认`；数据分析包含 `SELECT`；联动包含 `Outbox`、`幂等`。

- [ ] **Step 5: 完整验证与提交**

Run: `python -m unittest tests.test_report_html -v`
Expected: PASS。
Run: `rg -n 'https?://' index.html 00-总体汇报.html 01-投顾Agent汇报.html 02-客服Agent汇报.html 03-风控Agent汇报.html 04-业务操作Agent汇报.html 05-数据分析Agent汇报.html 06-多Agent联动与架构汇报.html`
Expected: 无输出。
Open: 在浏览器以 1280px 和 390px 检查流程节点、页间导航与控制台错误。
Commit: `git add tests/test_report_html.py index.html 00-总体汇报.html 01-投顾Agent汇报.html 02-客服Agent汇报.html 03-风控Agent汇报.html 04-业务操作Agent汇报.html 05-数据分析Agent汇报.html 06-多Agent联动与架构汇报.html && git commit -m "feat: add financial agent report pages"`。
