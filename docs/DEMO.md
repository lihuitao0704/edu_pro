# 金融 Agent 项目演示与验收指南

## 1. 初始化与启动

演示账号统一密码：`Demo@123`。

| 角色 | 用户名 | 主要页面 |
| --- | --- | --- |
| 普通客户 | `demo_customer_01` | 智能对话、客户画像 |
| 理财顾问 | `demo_advisor` | 顾问工作台、智能投顾、数据分析 |
| 客户经理 | `demo_manager` | 客户工作台、业务操作 |
| 风控专员 | `demo_risk` | 风险预警、工单处理 |
| 管理员 | `demo_admin` | 全部管理功能、知识库 |

```powershell
# 首次部署先执行版本化数据库迁移（按实际连接参数替换）
Get-Content -Raw migrations\20260723_business_closure.sql |
  mysql -h <MYSQL_HOST> -u <MYSQL_USER> -p <MYSQL_DATABASE>

# 生成或幂等更新演示数据
.\.venv\Scripts\python.exe scripts\seed_demo_data.py --apply

# 安装依赖并生成 Vue 生产包
cd frontend
pnpm install
pnpm build
cd ..

# 建议以真实 JWT 模式启动
$env:AUTH_MOCK_MODE="false"
$env:JWT_SECRET_KEY="<至少48位的随机密钥>"
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

前端生产包已接入 FastAPI，访问 `http://127.0.0.1:8000/`。需要进行前端开发时：

```powershell
cd frontend
pnpm install
pnpm dev
```

演示数据包括 20 个分层客户、30 个金融产品、40 条客户持仓和 50 条交易；重复执行脚本不会重复插入同一批数据。

## 2. Demo 1：普通客户投资咨询

1. 使用 `demo_customer_01` 登录。
2. 打开“智能对话”，选择客服 Agent。
3. 输入：“我有50万，希望稳健投资。”
4. 验证 SSE 流式回复、Agent 标识和引用来源正常显示。
5. 打开“客户画像”，查看基础信息、风险等级、投资偏好、资产规模、画像标签和置信度。
6. 回到“智能对话”，切换投顾 Agent，要求生成稳健型配置方案。
7. 验证推荐产品风险等级与客户画像匹配，并展示风险提示。

验收标准：登录身份来自 JWT；画像、产品和推荐结果来自真实后端接口；聊天可流式输出；失败时有明确错误提示。

## 3. Demo 2：理财顾问服务客户

1. 使用 `demo_advisor` 登录。
2. 打开“理财顾问工作台”，按姓名或客户编号搜索客户。
3. 选择一个高净值客户，查看资产画像、标签和当前持仓。
4. 调用投顾 Agent 生成产品推荐和资产配置建议。
5. 打开“数据分析”，输入：“查询资产超过100万客户”。
6. 查看生成 SQL、查询表格和统计图表。

验收标准：客户列表、画像和持仓来自 MySQL；推荐调用真实 Advisor Agent；分析结果同时显示只读 SQL、数据表格和图表；非员工角色不能访问客户列表和 NL2SQL。

## 4. Demo 3：异常交易风控

1. 使用 `demo_manager` 登录，打开“业务操作”。
2. 输入大额申购或转账指令，确认 NL2API 参数提取和权限校验结果。
3. 执行业务 API 后，验证返回中包含 `risk_monitor` 检测结果。
4. 使用 `demo_risk` 登录，打开“风控管理”。
5. 查看新生成的风险预警，包括客户、金额、触发规则、风险等级和处理状态。
6. 查看关联工单，将预警处理为“已解决”或“误报”。
7. 刷新列表，验证预警与工单状态同步。

验收标准：交易提交、上下文补全、规则检测、预警持久化、工单创建和处理形成同一条数据链；客户或顾问账号访问风控列表时返回 403。

## 5. 自动化回归

```powershell
# 后端闭环回归
.\.venv\Scripts\python.exe -m unittest `
  tests.test_auth_and_rbac `
  tests.test_transaction_flow `
  tests.test_workspace_apis `
  tests.test_sse_transport `
  tests.test_demo_seed `
  tests.test_frontend_serving -v

# 前端回归
cd frontend
pnpm test
pnpm build
```

服务启动后可额外执行真实 MySQL/Redis/JWT 旅程：

```powershell
$env:RUN_LIVE_E2E="1"
$env:E2E_BASE_URL="http://127.0.0.1:8000"
.\.venv\Scripts\python.exe -m unittest tests.test_business_journeys -v
```
