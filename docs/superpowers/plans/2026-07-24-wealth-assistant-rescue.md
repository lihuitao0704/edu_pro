# 财富助手与画像同步修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让财富助手安全排版、按认证用户恢复会话，并在风评后立即使用最新画像与持仓上下文。

**Architecture:** 保持 `/api/chat` 为唯一入口；在同一模块增加受 JWT 保护的历史读取。前端以认证用户 ID 作为会话键，后端只以 JWT 身份保存/读取消息并只为客户角色补全投顾客户上下文。

**Tech Stack:** FastAPI、SQLAlchemy async、MySQL、Redis、Vue 3、Pinia、TypeScript、Vitest、unittest。

## Global Constraints

- 会话历史按认证用户 ID 隔离；不得信任客户端传入的用户 ID。
- MySQL 画像为权威数据；风评提交后必须清除 Redis 画像缓存。
- 助手 Markdown 必须先转义 HTML；用户消息始终纯文本。
- 客户身份可使用 JWT 用户 ID 作为投顾客户上下文；员工身份不得回退到自身 ID。

---

## File Structure

- `app/api/unified_chat.py`: 历史读取接口。
- `app/agent/router_agent.py`: 客户身份上下文回退。
- `app/service/memory_service.py`: 一轮消息的可靠归档。
- `app/service/risk_service.py`: 风评结果同步画像快照。
- `frontend/src/api/chat.ts` 与 `stores/conversation.ts`: 恢复服务端会话。
- `frontend/src/utils/markdown.ts`: 受限 Markdown 渲染。
- `frontend/src/utils/profile-events.ts`: 跨页画像更新通知。
- `frontend/src/components`、`views`、`styles/index.css`: 展示和固定布局。

### Task 1: 后端会话历史和可信客户上下文

**Files:**
- Modify: `app/api/unified_chat.py:20-104`
- Modify: `app/agent/router_agent.py:68-154`
- Modify: `app/agent/customer_agent.py:230-251`
- Modify: `app/service/memory_service.py:49-140`
- Create: `tests/test_chat_memory_contract.py`

**Interfaces:**
- Produces: `GET /api/chat/history -> {session_id: str, messages: list[dict]}`
- Produces: `RouterAgent.route(..., user_role)` only uses `user_id` for `customer_id` when role is `客户`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_history_returns_only_authenticated_users_latest_session(self):
    result = await get_chat_history(db=db, user={"user_id": 2, "role": "客户"})
    self.assertEqual("s-2", result["data"]["session_id"])
    self.assertEqual("上一个问题", result["data"]["messages"][0]["content"])

async def test_customer_context_falls_back_to_jwt_identity(self):
    router = RouterAgent(AsyncMock())
    router.intent_service.classify_router = AsyncMock(return_value=("investment_recommendation", .9, {}))
    router._dispatch_advisor = AsyncMock(return_value={"reply": "ok", "data": {}})
    await router.route("评估我的持仓", user_id=7, user_role="客户")
    self.assertEqual(7, router._dispatch_advisor.await_args.args[3])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\\.venv\\Scripts\\python.exe -m unittest tests.test_chat_memory_contract -v`

Expected: FAIL because `get_chat_history` does not exist and the advisor receives `None`.

- [ ] **Step 3: Write minimal implementation**

```python
@router.get("/chat/history", response_model=dict)
async def get_chat_history(db=Depends(get_db), user=Depends(require_roles("客户", "理财顾问", "客户经理", "风控专员", "管理员"))):
    records = (await db.execute(select(ConversationArchive).where(
        ConversationArchive.user_id == authenticated_actor_id(user)
    ).order_by(ConversationArchive.create_time.desc()).limit(50))).scalars().all()
    session_id = records[0].session_id if records else ""
    messages = [r for r in reversed(records) if r.session_id == session_id]
    return success(data={"session_id": session_id, "messages": [
        {"role": r.role, "content": r.content, "created_at": r.create_time.isoformat()} for r in messages
    ]})

if agent_name == "advisor" and not customer_id and user_role == "客户":
    customer_id = user_id
```

Add `MemoryService.archive_turn(session_id, user_id, agent_type, user_content, assistant_content)`, create both archive rows, commit, and await it in `CustomerServiceAgent.handle` before returning.

- [ ] **Step 4: Run tests to verify it passes**

Run: `.\\.venv\\Scripts\\python.exe -m unittest tests.test_chat_memory_contract tests.test_auth_and_rbac -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add app/api/unified_chat.py app/agent/router_agent.py app/agent/customer_agent.py app/service/memory_service.py tests/test_chat_memory_contract.py
git commit -m "fix: persist chat history by authenticated user"
```

### Task 2: 风评同步画像快照并修复画像响应契约

**Files:**
- Modify: `app/service/risk_service.py:69-158`
- Modify: `app/service/profile_service.py:990-1024`
- Modify: `tests/test_risk_assessment_consistency.py:7-34`
- Modify: `tests/test_workspace_apis.py:25-54`

**Interfaces:**
- Produces: `profile.profile_json["risk_level"] == AssessmentResult.risk_level`.
- Produces: 最小画像对象序列化时 `id is None`。

- [ ] **Step 1: Write the failing tests**

```python
result = await service.submit_assessment(7, answers)
self.assertEqual(result.risk_level, profile.profile_json["risk_level"])
self.assertEqual(result.total_score, profile.profile_json["risk_score"])

minimal = SimpleNamespace(customer_id=3, risk_level="C2", risk_score=42, confidence_score=None,
    total_assets=None, risk_flag="normal", profile_json=None, create_time=None, update_time=None,
    investment_experience=None, annual_income_range=None, asset_allocation=None,
    product_preference=None, basic_score=None, experience_score=None, risk_pref_score=None, behavior_score=None)
self.assertIsNone(ProfileService(AsyncMock())._profile_to_dict(minimal)["id"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\\.venv\\Scripts\\python.exe -m unittest tests.test_risk_assessment_consistency tests.test_workspace_apis -v`

Expected: FAIL because `profile_json` is unchanged and `profile.id` is dereferenced.

- [ ] **Step 3: Write minimal implementation**

```python
snapshot = dict(profile.profile_json or {})
snapshot.update({"customer_id": customer_id, "risk_level": risk_level,
                 "risk_score": normalized, "updated_at": datetime.now().isoformat()})
profile.profile_json = snapshot

# ProfileService._profile_to_dict
"id": getattr(profile, "id", None),
```

Keep existing order: flush → tag upsert → score archive → flush → cache invalidate → commit; keep Neo4j sync after commit.

- [ ] **Step 4: Run test to verify it passes**

Run: `.\\.venv\\Scripts\\python.exe -m unittest tests.test_risk_assessment_consistency tests.test_profile_cache_contract tests.test_workspace_apis -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add app/service/risk_service.py app/service/profile_service.py tests/test_risk_assessment_consistency.py tests/test_workspace_apis.py
git commit -m "fix: synchronize assessment result into profile snapshot"
```

### Task 3: 恢复同一用户会话并渲染安全 Markdown

**Files:**
- Modify: `frontend/src/api/chat.ts`
- Modify: `frontend/src/stores/conversation.ts`
- Modify: `frontend/src/components/ChatWindow.vue`
- Modify: `frontend/src/components/MessageCard.vue`
- Create: `frontend/src/utils/markdown.ts`
- Create: `frontend/src/utils/markdown.test.ts`
- Modify: `frontend/src/stores/conversation.test.ts`

**Interfaces:**
- Produces: `getChatHistory(): Promise<{ sessionId: string; messages: ChatMessage[] }>`.
- Produces: `hydrateUserSession(userKey, history): void`.
- Produces: `renderAssistantMarkdown(content): string`.

- [ ] **Step 1: Write failing tests**

```ts
store.hydrateUserSession('7', { sessionId: 's-7', messages: [{ role: 'user', content: '上一个问题' }] })
expect(store.sessionFor('7').conversationId).toBe('s-7')
expect(renderAssistantMarkdown('## 建议\n- **分散**\n<script>x</script>'))
  .toContain('&lt;script&gt;x&lt;/script&gt;')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --dir frontend test -- --run src/stores/conversation.test.ts src/utils/markdown.test.ts`

Expected: FAIL because hydration and renderer do not exist.

- [ ] **Step 3: Write minimal implementation**

```ts
function hydrateUserSession(userKey: string, history: { sessionId: string; messages: ChatMessage[] }) {
  const session = sessionFor(userKey)
  if (!session.messages.length && history.messages.length) {
    session.conversationId = history.sessionId || session.conversationId
    session.messages = history.messages
  }
}
const escapeHtml = (text: string) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
```

Implement headings, paragraphs, contiguous ordered/unordered lists, bold, inline code, quote, separator, and empty lines over escaped text. In `ChatWindow`, call `getChatHistory` on mount and hydrate the computed user key. In `MessageCard`, use `v-html` only for the rendered assistant content.

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm --dir frontend test -- --run src/api/chat.test.ts src/stores/conversation.test.ts src/utils/markdown.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/api/chat.ts frontend/src/stores/conversation.ts frontend/src/components/ChatWindow.vue frontend/src/components/MessageCard.vue frontend/src/utils/markdown.ts frontend/src/utils/markdown.test.ts frontend/src/stores/conversation.test.ts
git commit -m "feat: restore user chat history and render replies"
```

### Task 4: 画像更新事件与固定聊天工作区

**Files:**
- Create: `frontend/src/utils/profile-events.ts`
- Create: `frontend/src/utils/profile-events.test.ts`
- Modify: `frontend/src/components/RiskAssessmentModal.vue`
- Modify: `frontend/src/views/ProfileView.vue`
- Modify: `frontend/src/views/AdvisorWorkspaceView.vue`
- Modify: `frontend/src/views/ChatView.vue`
- Modify: `frontend/src/views/OperationsView.vue`
- Modify: `frontend/src/styles/index.css:265-272`

**Interfaces:**
- Produces: `publishProfileUpdated(customerId): void`, `onProfileUpdated(listener): () => void`.
- Produces: fixed `.chat-window` with only `.chat-scroll-area` scrolling.

- [ ] **Step 1: Write the failing event test**

```ts
const listener = vi.fn()
const stop = onProfileUpdated(listener)
publishProfileUpdated(7)
stop()
publishProfileUpdated(8)
expect(listener).toHaveBeenCalledTimes(1)
expect(listener).toHaveBeenCalledWith(7)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --dir frontend test -- --run src/utils/profile-events.test.ts`

Expected: FAIL because the event module does not exist.

- [ ] **Step 3: Write minimal implementation**

```ts
const eventName = 'wealth:profile-updated'
export const publishProfileUpdated = (customerId: number) =>
  window.dispatchEvent(new CustomEvent<number>(eventName, { detail: customerId }))
export const onProfileUpdated = (listener: (customerId: number) => void) => {
  const handler = (event: Event) => listener((event as CustomEvent<number>).detail)
  window.addEventListener(eventName, handler)
  return () => window.removeEventListener(eventName, handler)
}
```

Publish after successful assessment. Refresh `ProfileView` and `AdvisorWorkspaceView` only if their displayed customer ID equals the event ID. Remove the repeated card title from `ChatWindow`; preserve the `ChatView` page title. Use the same `quick-prompts` markup for business-operation examples. Set `.chat-window` to viewport height with `overflow: hidden`; set `.chat-scroll-area { flex: 1; min-height: 0; max-height: none; overflow-y: auto }`.

- [ ] **Step 4: Run tests and build to verify it passes**

Run: `pnpm --dir frontend test -- --run src/utils/profile-events.test.ts && pnpm --dir frontend build`

Expected: PASS and a successful production bundle.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/utils/profile-events.ts frontend/src/utils/profile-events.test.ts frontend/src/components/RiskAssessmentModal.vue frontend/src/views/ProfileView.vue frontend/src/views/AdvisorWorkspaceView.vue frontend/src/views/ChatView.vue frontend/src/views/OperationsView.vue frontend/src/styles/index.css
git commit -m "fix: refresh profiles and constrain chat workspace"
```

### Task 5: 全量回归

**Files:**
- Modify: no production files expected
- Test: `tests/test_chat_memory_contract.py`, `tests/test_risk_assessment_consistency.py`, `tests/test_workspace_apis.py`, `frontend/src/**/*.test.ts`

**Interfaces:**
- Consumes: Tasks 1-4 contracts.
- Produces: verified implementation while preserving the user's pre-existing untracked reports.

- [ ] **Step 1: Run focused Python suite**

Run: `.\\.venv\\Scripts\\python.exe -m unittest tests.test_chat_memory_contract tests.test_risk_assessment_consistency tests.test_profile_cache_contract tests.test_profile_score_history tests.test_workspace_apis tests.test_auth_and_rbac -v`

Expected: all PASS.

- [ ] **Step 2: Run frontend suite**

Run: `pnpm --dir frontend test -- --run`

Expected: all Vitest tests PASS.

- [ ] **Step 3: Build frontend**

Run: `pnpm --dir frontend build`

Expected: `✓ built` with no TypeScript errors.

- [ ] **Step 4: Inspect final diff**

Run: `git diff --check; git status --short`

Expected: no whitespace error; pre-existing untracked report files remain untouched.

- [ ] **Step 5: Commit any verification-only updates**

```powershell
git add tests frontend/src
git commit -m "test: cover wealth assistant recovery flows"
```

