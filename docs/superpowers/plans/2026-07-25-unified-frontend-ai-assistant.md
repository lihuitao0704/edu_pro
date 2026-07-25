# 统一前端启动与 AI 财富助手实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `python main.py` 以 8000（不可用时 8001）启动可用的前后端，并修复推荐与 AI 财富助手主链路。

**Architecture:** FastAPI 托管 Vue 构建产物与 `/api`。推荐先取得结构化结果，再生成合规叙述；路由先做可解释规则判定，再使用 LLM 兜底。

**Tech Stack:** Python、FastAPI、SQLAlchemy async、Vue 3、TypeScript、Vite、Vitest、pytest。

## Global Constraints

- 仅终止确认属于 `D:\\edu_pro` 的 Python/Uvicorn 监听进程。
- 生产 API 使用相对 `/api`，不依赖 5173。
- 每项行为修改先写失败测试。
- 推荐文本必须包含“投资有风险，入市需谨慎”。

---

### Task 1: 安全单入口启动

**Files:** `main.py`, `frontend/vite.config.ts`, `tests/test_main_startup.py`

- [ ] 写失败测试：8000 不可绑定时选 8001；未知监听进程不被终止；缺少 `frontend/dist/index.html` 时执行 `pnpm --dir frontend build`。

```python
def test_resolve_server_port_falls_back_to_8001(monkeypatch):
    monkeypatch.setattr(main, "is_port_available", lambda port: port == 8001)
    assert main.resolve_server_port() == 8001
```

- [ ] 运行 `& .\.venv\Scripts\python.exe -m pytest tests/test_main_startup.py -q`，确认失败。
- [ ] 实现 `resolve_server_port()`、`release_workspace_listener()` 与 `ensure_frontend_build()`；监听命令行必须包含工作区绝对路径才允许结束，随后以解析到的端口调用 `uvicorn.run`。
- [ ] 重新运行该测试，确认通过。
- [ ] 提交：`git commit -m "feat: add safe single-port startup"`。

### Task 2: 结构化推荐与画像一致性

**Files:** `app/agent/advisor_agent.py`, `app/service/advisor_service.py`, `tests/test_advisor_recommendation_flow.py`

- [ ] 写失败测试：有效 C3 画像在配置查询失败时仍返回 `profile_status="available"`；画像读取在配置计算之前完成。

```python
async def test_existing_profile_is_not_reported_unavailable_when_allocation_fails():
    result = await agent._build_recommendation_result(27, 3)
    assert result["customer_profile"]["assessment"]["risk_level"] == "C3"
    assert result["profile_status"] == "available"
```

- [ ] 运行 `& .\.venv\Scripts\python.exe -m pytest tests/test_advisor_recommendation_flow.py -q`，确认失败。
- [ ] 从 `smart_recommend` 提取 `_build_recommendation_result(customer_id, top_n)`；先 `await profile_tool._arun`，再计算配置与推荐，禁止 `asyncio.gather` 共享同一 `AsyncSession`。
- [ ] 只在 `status="not_found"` 时回退 C1；真实异常标识 unavailable，不覆盖已成功读取的画像。
- [ ] 重新运行测试，确认通过并提交 `fix: keep advisor profile and recommendation in sync`。

### Task 3: LLM 叙述和合规兜底

**Files:** `app/service/advisor_narrative_service.py`, `app/agent/advisor_agent.py`, `app/api/advisor.py`, `tests/test_advisor_narrative_service.py`

- [ ] 写失败测试：LLM 成功结果与 LLM 异常的模板结果都包含风险提示；异常文本不出现在输出中。

```python
async def test_template_fallback_contains_disclaimer():
    output = await service.render(sample_result, "推荐产品")
    assert output["narrative_source"] == "template"
    assert "投资有风险，入市需谨慎" in output["narrative"]
```

- [ ] 运行 `& .\.venv\Scripts\python.exe -m pytest tests/test_advisor_narrative_service.py -q`，确认失败。
- [ ] 实现 `AdvisorNarrativeService.render(result, question)`；LLM 只接收结构化事实并设置短超时，失败时生成模板。`ensure_disclaimer()` 在两条路径追加固定提示。
- [ ] API 返回 `narrative`、`narrative_source` 与结构化结果；重新运行测试并提交 `feat: add compliant advisor narrative`。

### Task 4: 顾问工作台直连投顾接口

**Files:** `frontend/src/views/AdvisorWorkspaceView.vue`, `frontend/src/api/types.ts`, `frontend/src/views/AdvisorWorkspaceView.test.ts`

- [ ] 写失败组件测试：点击推荐按钮会 `post('/advisor', { customer_id: 27, ... })`，并展示 `narrative`。

```ts
expect(post).toHaveBeenCalledWith('/advisor', expect.objectContaining({ customer_id: 27 }))
expect(wrapper.text()).toContain('投资有风险，入市需谨慎')
```

- [ ] 运行 `pnpm --dir frontend vitest run src/views/AdvisorWorkspaceView.test.ts`，确认失败。
- [ ] 把 `runRecommend()` 从 `/chat` 改为 `/advisor`；直接映射 `customer_profile`、`recommendations`、`allocation`、`narrative`、`profile_status`。仅在 unavailable 时显示画像异常提示。
- [ ] 重新运行组件测试并提交 `fix: route advisor workspace to advisor API`。

### Task 5: AI 财富助手意图与交互

**Files:** `app/service/intent_service.py`, `app/agent/router_agent.py`, `frontend/src/components/ChatWindow.vue`, `frontend/src/stores/conversation.ts`, `tests/test_intent_service.py`, `frontend/src/components/ChatWindow.test.ts`

- [ ] 写失败测试：`推荐三款适合我的基金` 路由投顾；`帮我处理一下资金` 返回澄清而非执行操作；发送期间禁用发送按钮。

```python
async def test_ambiguous_money_request_needs_clarification():
    decision = await service.resolve("帮我处理一下资金", None)
    assert decision.needs_clarification is True
```

- [ ] 分别运行 pytest 和 Vitest，确认失败。
- [ ] 实现 `IntentDecision(intent, confidence, needs_clarification, clarification)`：关键词/上下文规则优先、现有 LLM 分类兜底、低置信度返回澄清。RouterAgent 不分发该类请求；ChatWindow 增加 loading、重复提交保护、重试和友好错误。
- [ ] 重新运行测试并提交 `feat: improve wealth assistant intent experience`。

### Task 6: 构建和页面 API 冒烟验证

**Files:** `frontend/src/views/AnalyticsView.vue`, `frontend/src/views/ProfileView.vue`, `tests/test_frontend_api_smoke.py`

- [ ] 写失败冒烟测试：`/api/health`、`/api/customers`、`/api/risk/alerts`、`/api/knowledge/documents` 不返回 5xx。
- [ ] 运行 `pnpm --dir frontend build`，确认 ECharts 类型与 nullable 画像错误；运行烟测确认当前失败点。
- [ ] 使用安装版本实际导出的 ECharts 类型，收窄 `profile.value` 的空值分支，并修复烟测发现的端点契约问题。
- [ ] 运行：

```powershell
pnpm --dir frontend build
pnpm --dir frontend test
& .\.venv\Scripts\python.exe -m pytest tests/test_main_startup.py tests/test_advisor_recommendation_flow.py tests/test_advisor_narrative_service.py tests/test_intent_service.py tests/test_frontend_api_smoke.py -q
```

- [ ] 最后执行 `& .\.venv\Scripts\python.exe main.py`，访问根页面和 `/api/health`，确认服务运行在 8000 或 8001；提交 `fix: verify frontend build and critical APIs`。
