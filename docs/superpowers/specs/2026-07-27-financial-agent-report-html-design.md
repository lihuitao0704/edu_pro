# 金融多 Agent 项目汇报 HTML 设计

**日期：** 2026-07-27  
**目标：** 基于当前仓库的真实实现，生成一组可离线打开、兼顾业务汇报与技术评审的简约 HTML 汇报页面。

## 1. 交付范围

在项目根目录创建一个报告入口页和七份独立专题页，共八个 HTML 文件：

| 文件 | 汇报主题 | 核心内容 |
|---|---|---|
| `index.html` | 报告导航 | 项目定位、报告目录、使用说明和专题跳转 |
| `00-总体汇报.html` | 项目总体 | 平台价值、技术栈、分层架构、六类 Agent、项目总结 |
| `01-投顾Agent汇报.html` | 投顾 Agent | 客户画像、推荐/配置、适当性约束、GraphRAG、流式交互与亮点 |
| `02-客服Agent汇报.html` | 客服 Agent | 知识问答、会话上下文、情绪信号、风险提醒协同 |
| `03-风控Agent汇报.html` | 风控 Agent | 事前交易闸门、四维画像/熔断、预警、工单与动态约束 |
| `04-业务操作Agent汇报.html` | 业务操作 Agent | NL2API、申购/赎回/转账/工单、权限、确认和合规校验 |
| `05-数据分析Agent汇报.html` | 数据分析 Agent | NL2SQL、只读 SQL 防护、结果解释、分析洞察与事件消费 |
| `06-多Agent联动与架构汇报.html` | 联动与全景架构 | Router、ChatOrchestrator、统一事件、Outbox、Redis、幂等消费、全平台架构和关键闭环 |

“项目架构详解”不再单列，完整架构内容放入第八份“多 Agent 联动与架构汇报”。

## 2. 内容依据与真实性边界

内容必须以仓库当前代码、架构文档和演示指南为依据，重点引用下列实现：

- FastAPI 入口和统一对话接口：`main.py`、`app/api/unified_chat.py`。
- 六类意图路由和横切编排：`app/agent/router_agent.py`、`app/common_services/orchestration/chat_orchestrator.py`。
- 投顾、客服和业务操作能力：`app/agent/advisor_agent.py`、`app/agent/customer_agent.py`、`app/agent/operator_agent.py`。
- 风控、画像与交易流程：`app/service/risk_monitor_service.py`、`app/service/risk_service.py`、`app/service/transaction_flow_service.py`、`app/engine/`。
- 数据分析与事件联动：`app/service/nl2sql_service.py`、`app/service/event_bus.py`、`app/service/agent_event_service.py`。
- 数据/知识基础设施：MySQL、Redis、Neo4j、Milvus、MinIO；依赖定义于 `requirements.txt`。
- 前端技术栈：Vue 3、TypeScript、Vite、Pinia、Element Plus、ECharts；定义于 `frontend/package.json`。

页面需以“当前实现”为口径。六 Agent 联动涉及的目标事件模型，应标注为“已实现的事件闭环/设计约束”时才可陈述；不得把未接入的 Kafka、外部通知、自动修改正式风险等级或未验证图谱推荐效果表述为现有能力。

## 3. 信息架构

每份专题页采用统一叙事顺序，便于答辩者讲解：

1. 标题、汇报定位和一句结论；
2. 业务问题与该 Agent 的职责边界；
3. 核心能力与典型用户流程；
4. 技术架构、关键服务/工具/数据依赖；
5. 设计原因、风控或工程亮点；
6. 与其他 Agent 的输入输出；
7. 可验证点、总结和返回目录。

总体页强调全局价值与技术全景；各 Agent 页强调职责边界和实现细节；联动页同时承载全平台分层架构图、统一消息模型和交易风控闭环、投顾反馈闭环、分析洞察闭环。

## 4. 视觉与交互规范

- 风格：简约、专业、适合投屏；白色背景、深蓝灰文字，以蓝绿作为单一强调色。
- 排版：宽度受控的内容容器，首屏结论卡，后续按节分区；桌面端双列卡片，小屏单列堆叠。
- 图形：用内联 SVG、HTML/CSS 节点和连线绘制架构图、流程图和数据流，不依赖 CDN、外部字体、图表库或构建步骤。
- 导航：每页包含页内锚点导航、上一篇/下一篇和入口页链接；入口页含全部报告卡片。
- 可访问性：语义化标题层级、可读色彩对比、清晰键盘焦点、图形配备文字说明；尊重 `prefers-reduced-motion`。
- 真实性标识：关键流程可用“当前实现”“策略约束”“演进方向”标签区分，避免误解。

## 5. 验收标准

1. 八个文件可由本地浏览器直接打开，且页面间导航可用。
2. 每份专题页能独立完成 5 至 10 分钟讲解，并同时给出业务价值和技术依据。
3. 技术栈、Agent 功能、核心路径和事件模型均与当前代码一致。
4. 架构图和联动图在无网络、无构建环境下显示正常。
5. 在 1280px 桌面和 390px 移动视口下无横向溢出，文字和对比度可读。
6. 通过静态检查验证文件存在、内部链接目标存在，浏览器预览无控制台错误。

## 6. 不在范围

- 不修改业务代码、接口、数据库或现有前端应用。
- 不加入在线部署、外部图库或第三方统计服务。
- 不把汇报页作为生产业务前端或替代项目现有 Vue 应用。
