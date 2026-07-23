# 单端口部署与统一认证前端 Implementation Plan

> **For agentic workers:** Execute every task with RED → GREEN → REFACTOR and retain each successful test result.

**Goal:** 在 8000 单端口提供 FastAPI API 和生产 Vue 应用，提供统一登录、客户注册及基于服务端 JWT 角色的自动工作台跳转。

**Architecture:** FastAPI 托管 frontend/dist；生产浏览器使用相对 /api 请求。Vite 仅用于 5173 端口热更新，并代理 /api 到后端 8000。Pinia 保存会话，前端仅决定展示和导航，API 权限继续由后端 JWT 负责。

**Tech Stack:** Python 3, FastAPI, Uvicorn, unittest, Vue 3, TypeScript, Pinia, Vue Router, Vite, Vitest.

## Global Constraints

- main.py 直接运行时固定监听 8000，页面和 API 同端口。
- 客户自助注册只接收用户名、密码、真实姓名、可选手机号；服务端强制 CUSTOMER 和空 employee_role。
- 不增加员工自助注册、SSO、短信/邮件验证、找回密码或反向代理。
- 每一项生产行为都必须先有一个观察到失败的测试。

---

### Task 1: 固化单端口 SPA 托管行为

**Files:**
- Modify: tests/test_frontend_serving.py
- Modify: main.py
- Modify: frontend/vite.config.ts

**Interfaces:**
- GET /login、GET /register 和任意非 API history 路由返回 frontend/dist/index.html。
- GET /api/not-a-route 返回 JSON 404。
- 开发服务器仍为 5173，/api 代理至 http://127.0.0.1:8000。

- [ ] **Step 1: 写失败测试**

~~~python
from fastapi import HTTPException

def test_register_history_route_uses_vue_index(self):
    response = asyncio.run(main.frontend_fallback("register"))
    expected = os.path.join(main.frontend_dir, "index.html")
    self.assertEqual(os.path.normpath(expected), os.path.normpath(response.path))

def test_api_paths_are_not_served_by_spa_fallback(self):
    with self.assertRaises(HTTPException) as raised:
        asyncio.run(main.frontend_fallback("api/not-a-route"))
    self.assertEqual(404, raised.exception.status_code)
~~~

- [ ] **Step 2: 验证 RED**

Run: python -m unittest tests.test_frontend_serving -v

Expected: 新增断言先失败，失败原因是静态托管契约尚未完整实现。

- [ ] **Step 3: 写最小实现**

~~~python
@app.get("/{frontend_path:path}", include_in_schema=False)
async def frontend_fallback(frontend_path: str):
    if frontend_path == "api" or frontend_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found")
    requested_path = os.path.abspath(os.path.join(frontend_dir, frontend_path))
    frontend_root = os.path.abspath(frontend_dir)
    if (
        os.path.commonpath([frontend_root, requested_path]) == frontend_root
        and os.path.isfile(requested_path)
    ):
        return FileResponse(requested_path)
    return FileResponse(os.path.join(frontend_dir, "index.html"))
~~~

在 main.py 保留 uvicorn 的 port=8000。Vite 保持：

~~~ts
server: {
  port: 5173,
  proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } },
},
~~~

- [ ] **Step 4: 验证 GREEN**

Run: python -m unittest tests.test_frontend_serving -v

Expected: OK。

- [ ] **Step 5: 提交**

~~~powershell
git add main.py frontend/vite.config.ts tests/test_frontend_serving.py
git commit -m "test: define single-port frontend serving contract"
~~~

### Task 2: 完成客户注册安全边界和自动登录 Store

**Files:**
- Modify: tests/test_auth_and_rbac.py
- Modify: app/api/auth.py
- Modify: frontend/src/api/types.ts
- Modify: frontend/src/stores/auth.ts
- Create: frontend/src/stores/auth.test.ts
- Modify: frontend/src/api/http.ts
- Modify: frontend/src/api/http.test.ts

**Interfaces:**
- POST /api/auth/register 返回 user_id、username、role 等于 客户。
- auth.register(payload) 先调用注册接口，再使用提交的用户名和密码调用 auth.login。
- 401 必须清空 wealth-token 和 wealth-user，并继续抛出 ApiError。

- [ ] **Step 1: 写失败的后端注册测试**

~~~python
class RegisterEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_register_forces_customer_without_employee_role(self):
        from app.api.auth import RegisterRequest, register

        db = AsyncMock()
        db.execute.side_effect = [
            SimpleNamespace(first=lambda: None),
            SimpleNamespace(lastrowid=42),
        ]
        result = await register(
            RegisterRequest(
                username="new_customer",
                password="StrongPass@123",
                real_name="新客户",
                phone="13800138000",
            ),
            db,
        )

        _, params = db.execute.await_args_list[1].args
        self.assertEqual("new_customer", params["username"])
        self.assertNotIn("employee_role", params)
        self.assertEqual("客户", result["data"]["role"])
~~~

在文件 import 中加入 AsyncMock 和 SimpleNamespace。

- [ ] **Step 2: 验证后端 RED**

Run: python -m unittest tests.test_auth_and_rbac.RegisterEndpointTests -v

Expected: FAIL，直到 SQL 和返回对象达到客户身份约定。

- [ ] **Step 3: 写最小服务端实现**

~~~python
result = await db.execute(
    text(
        "INSERT INTO sys_user "
        "(username, password_hash, user_type, employee_role, customer_level, "
        "real_name, phone, status, create_time, update_time) "
        "VALUES (:username, :password_hash, 'CUSTOMER', NULL, '普通', "
        ":real_name, :phone, '正常', NOW(), NOW())"
    ),
    {
        "username": body.username,
        "password_hash": hash_password(body.password),
        "real_name": body.real_name,
        "phone": body.phone,
    },
)
return success(
    data={"user_id": int(result.lastrowid), "username": body.username, "role": "客户"},
    message="注册成功",
)
~~~

不要向 RegisterRequest 增加任何 role、employee_role 或 user_type 字段。

- [ ] **Step 4: 写失败的前端 Store 测试**

~~~ts
it('registers a customer and then logs in with submitted credentials', async () => {
  vi.mocked(post)
    .mockResolvedValueOnce({ user_id: 7, username: 'new_customer', role: '客户' })
    .mockResolvedValueOnce({
      access_token: 'jwt',
      user: { user_id: 7, username: 'new_customer', role: '客户' },
    })
  const auth = useAuthStore(createPinia())

  await auth.register({
    username: 'new_customer',
    password: 'StrongPass@123',
    real_name: '新客户',
    phone: '13800138000',
  })

  expect(post).toHaveBeenNthCalledWith(1, '/auth/register', expect.objectContaining({ username: 'new_customer' }))
  expect(post).toHaveBeenNthCalledWith(2, '/auth/login', { username: 'new_customer', password: 'StrongPass@123' })
  expect(auth.user?.role).toBe('客户')
})
~~~

- [ ] **Step 5: 验证前端 RED**

Run: npm test -- --run frontend/src/stores/auth.test.ts

Expected: FAIL，提示 register 方法缺失。

- [ ] **Step 6: 写最小类型与 Store 实现**

~~~ts
export interface RegisterPayload {
  username: string
  password: string
  real_name: string
  phone?: string
}
~~~

~~~ts
async function register(payload: RegisterPayload) {
  await post('/auth/register', payload)
  await login(payload.username, payload.password)
}
~~~

将 register 暴露在 useAuthStore 的返回值中。在 apiRequest 收到 401 时只执行：

~~~ts
localStorage.removeItem('wealth-token')
localStorage.removeItem('wealth-user')
~~~

- [ ] **Step 7: 验证 GREEN**

Run: python -m unittest tests.test_auth_and_rbac -v

Expected: OK.

Run: npm test -- --run frontend/src/stores/auth.test.ts frontend/src/api/http.test.ts

Expected: PASS，自动登录与 401 清理均通过。

- [ ] **Step 8: 提交**

~~~powershell
git add app/api/auth.py tests/test_auth_and_rbac.py frontend/src/api/types.ts frontend/src/api/http.ts frontend/src/api/http.test.ts frontend/src/stores/auth.ts frontend/src/stores/auth.test.ts
git commit -m "feat: add customer registration auth flow"
~~~

### Task 3: 建立统一登录和注册视图并按角色跳转

**Files:**
- Create: frontend/src/views/RegisterView.vue
- Modify: frontend/src/views/LoginView.vue
- Modify: frontend/src/router/index.ts
- Create: frontend/src/router/index.test.ts
- Modify: frontend/src/styles/index.css
- Modify: frontend/src/navigation.test.ts

**Interfaces:**
- public 路由为 /login 和 /register。
- 已登录用户打开认证页时跳到 homeForRole(role)。
- 未登录用户打开工作台时跳到 /login；无权限角色跳回自己的默认工作台。
- 注册成功的客户进入 /chat。

- [ ] **Step 1: 写失败的 Router 测试**

~~~ts
it('redirects an authenticated risk specialist from login to risk', async () => {
  localStorage.setItem('wealth-token', 'jwt')
  localStorage.setItem('wealth-user', JSON.stringify({ user_id: 3, username: 'risk', role: '风控专员' }))
  const router = createAppRouter(createMemoryHistory())

  await router.push('/login')
  await router.isReady()

  expect(router.currentRoute.value.fullPath).toBe('/risk')
})

it('redirects an unauthenticated advisor visitor to login', async () => {
  const router = createAppRouter(createMemoryHistory())

  await router.push('/advisor')
  await router.isReady()

  expect(router.currentRoute.value.fullPath).toBe('/login')
})
~~~

- [ ] **Step 2: 验证 Router RED**

Run: npm test -- --run frontend/src/router/index.test.ts

Expected: FAIL，直到 Router 工厂和认证页重定向实现。

- [ ] **Step 3: 写可测试 Router 工厂**

~~~ts
export function createAppRouter(history = createWebHistory()) {
  const router = createRouter({
    history,
    routes: [
      { path: '/login', component: () => import('../views/LoginView.vue'), meta: { public: true } },
      { path: '/register', component: () => import('../views/RegisterView.vue'), meta: { public: true } },
      // 保留现有 AppLayout 和全部受保护子路由
    ],
  })

  router.beforeEach((to) => {
    const token = localStorage.getItem('wealth-token')
    const savedUser = localStorage.getItem('wealth-user')
    const role = savedUser ? JSON.parse(savedUser).role || '' : ''
    if (to.meta.public) return token && savedUser ? homeForRole(role) : true
    if (!token || !savedUser) return '/login'
    return navigationForRole(role).some((item) => item.path === to.path) ? true : homeForRole(role)
  })
  return router
}
~~~

默认导出 createAppRouter()，保留现有路由列表。

- [ ] **Step 4: 写注册视图最小提交逻辑**

~~~ts
const form = reactive({ username: '', realName: '', phone: '', password: '', confirmPassword: '' })

async function submit() {
  if (form.password !== form.confirmPassword) {
    error.value = '两次输入的密码不一致'
    return
  }
  loading.value = true
  error.value = ''
  try {
    await auth.register({
      username: form.username,
      password: form.password,
      real_name: form.realName,
      phone: form.phone || undefined,
    })
    await router.push(homeForRole(auth.user?.role || '客户'))
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '注册失败，请稍后重试'
  } finally {
    loading.value = false
  }
}
~~~

模板必须为真实姓名、用户名、手机号、密码、确认密码配置关联 label、autocomplete、必填校验、ErrorAlert、提交中禁用和回到登录的链接。LoginView 使用相同组件类和注册链接。

- [ ] **Step 5: 写统一响应式样式**

~~~css
.auth-page { min-height: 100vh; display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(360px, .9fr); }
.auth-panel { display: grid; place-items: center; padding: 48px; background: var(--paper); }
.auth-form { width: min(430px, 100%); display: grid; gap: 16px; }
.auth-switch { margin: 0; color: var(--muted); text-align: center; font-size: 13px; }
.auth-switch a { color: var(--teal); font-weight: 700; }
@media (max-width: 760px) {
  .auth-page { grid-template-columns: 1fr; }
  .auth-panel { padding: 32px 20px; }
}
~~~

将现有 login 类迁移或复用为 auth 类，避免双套不一致的认证视觉体系。

- [ ] **Step 6: 验证 GREEN 和生产构建**

Run: npm test -- --run frontend/src/router/index.test.ts frontend/src/navigation.test.ts frontend/src/stores/auth.test.ts

Expected: PASS.

Run: npm run build

Expected: vue-tsc --noEmit 和 vite build 以 0 退出，创建 frontend/dist/index.html。

- [ ] **Step 7: 提交**

~~~powershell
git add frontend/src/views/LoginView.vue frontend/src/views/RegisterView.vue frontend/src/router/index.ts frontend/src/router/index.test.ts frontend/src/styles/index.css frontend/src/navigation.test.ts
git commit -m "feat: add unified login and registration experience"
~~~

### Task 4: 交付启动说明和最终验证

**Files:**
- Create: docs/DEPLOYMENT.md
- Modify: tests/test_frontend_serving.py

**Interfaces:**
- 文档给出构建一次后运行 python main.py 的生产启动流程。
- 文档给出 Vite 5173 开发流程及其到 8000 的 API 代理边界。

- [ ] **Step 1: 写构建入口断言**

~~~python
def test_production_entry_uses_built_vue_index(self):
    index_path = os.path.join(main.frontend_dir, 'index.html')
    self.assertTrue(index_path.endswith(os.path.join('frontend', 'dist', 'index.html')))
    self.assertTrue(os.path.isfile(index_path), 'Run npm run build before python main.py')
~~~

- [ ] **Step 2: 写部署内容**

~~~markdown
# 单端口启动

~~~powershell
cd frontend
npm ci
npm run build
cd ..
python main.py
~~~

打开 http://127.0.0.1:8000。页面和 API 均由同一进程、同一端口提供。

## 前端开发

~~~powershell
cd frontend
npm run dev
~~~

5173 只提供热更新；所有 /api 请求被转发到 8000。
~~~

- [ ] **Step 3: 执行最终验证**

Run: npm run build

Expected: frontend/dist/index.html 存在。

Run: python -m unittest tests.test_frontend_serving tests.test_auth_and_rbac -v

Expected: OK.

Run: npm test -- --run

Expected: 所有 Vitest 套件 PASS。

Run: python main.py

Expected: 访问 /login、/register、/chat 返回 Vue 页面；/api/not-a-route 返回 JSON 404。

- [ ] **Step 4: 提交**

~~~powershell
git add docs/DEPLOYMENT.md tests/test_frontend_serving.py
git diff --check
git status --short
git commit -m "docs: document single-port application startup"
~~~

不要提交 frontend/dist，除非仓库已有追踪构建产物的策略。

