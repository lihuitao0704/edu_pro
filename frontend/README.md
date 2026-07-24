# FINTELLIGENCE · 金融多 Agent 智能平台

基于 Vue 3、TypeScript、Vite 与 ECharts 的企业级金融 AI 前端。它提供面向客户的 AI 财富助手，以及面向理财顾问、风控人员和管理员的多 Agent 运营中心。

## 核心页面

- `/chat`：AI 财富助手。以金融建议卡、风险等级、置信度与推荐操作呈现回复，不暴露内部 Agent 编排。
- `/dashboard`：内部智能运营中心。包含五类 Agent 运行指标、完整请求 Trace、风险关注事项与 ECharts 经营看板。

## 工程结构

```text
src/
├── api/                 # HTTP 基础能力与 /api/chat 契约
├── components/          # ChatWindow、MessageCard、RecommendationCard 等业务组件
├── layouts/             # 平台壳与导航
├── mocks/               # Dashboard 与聊天降级演示数据
├── views/               # 页面级视图（ChatView、DashboardView）
├── router/              # 路由与角色权限
└── styles/              # Dark Finance 主题与响应式规则
```

## 本地运行

```bash
npm install
npm run dev
```

开发服务器默认运行于 `http://localhost:5173`，并将 `/api` 代理至 `http://127.0.0.1:8000`。

## API 对接

聊天服务使用统一入口。页面组件采用 `conversation_id`，API 适配层将其转换为现有后端的 `session_id` 并保留服务端返回的会话 ID：

```http
POST /api/chat
Content-Type: application/json

{
  "user_id": 1,
  "user_role": "客户",
  "session_id": "wealth-session-001",
  "message": "我有 50 万，如何稳健配置？"
}
```

响应通过现有标准 Envelope 解包，适配层将后端的 `reply`、`data.recommendations` 转换为页面使用的 `answer`、推荐卡片与操作建议：

```ts
{
  answer: string
  agent: string
  confidence: number
  suggestions: string[]
  metadata: {
    risk_level?: string
    recommendation?: {
      title: string
      risk_level: '低风险' | '稳健型' | '进取型'
      product: string
      allocation: string
      rationale: string
    }
  }
}
```

当 API 不可用时，生产环境展示错误状态，不会生成替代性的投资建议。仅在开发环境显式设置 `VITE_ENABLE_CHAT_MOCK=true` 时，聊天页才会展示带“演示数据”标记的 Mock 结果，便于界面走查。

## 验证

```bash
npm test
npm run build
```
