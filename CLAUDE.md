# CLAUDE.md — 知识图谱 + 业务操作Agent 开发指南

> 本文件为 Claude Code 在此目录下工作时提供上下文与开发约束。
> 我的职责：**Phase 4 — 知识图谱 + 业务操作Agent（NL2API）**
> 其他模块（智能客服/投顾Agent/风控/数据分析/GraphRAG）由同事负责。

---

## 数据库连接配置

所有敏感配置（密码、API Key等）统一放在 `.env` 文件，**不要提交到Git**。

我需要用到的中间件：

| 组件 | 需要的配置项 |
|------|-------------|
| MySQL | `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE` |
| Redis | `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_DB` |
| Neo4j | `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` |
| LLM | `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL_CHAT` |

`.env` 文件已配置完成。

---

## 项目背景

XX科技·智能财富管家系统，5个Agent协作的金融服务平台。
我负责两大块：
1. **Neo4j知识图谱构建** — 为其他Agent提供图谱查询能力
2. **业务操作Agent（NL2API）** — 自然语言执行申购/赎回/转账等操作

**整体技术栈**：Python 3.10+ / FastAPI / MySQL 8.0 / Redis 7.x / Neo4j 5.x / OpenAI API（Qwen/DeepSeek）
**认证**：Mock JWT（HS256，Payload: `user_id, username, user_type, employee_role/customer_level, exp`）

---

## 我的交付范围

### 一、Neo4j知识图谱构建

#### 图谱数据模型

**节点类型**：
| 节点 | 属性 | 数据来源 |
|------|------|---------|
| Customer | customer_id, name, risk_level | MySQL: sys_user + fin_customer_profile |
| Product | product_id, product_code, type, risk_level, expected_return | MySQL: fin_product |
| RiskLevel | level (R1-R5), description | 静态数据 |
| Industry | industry_id, name | Mock数据 |
| FundManager | manager_id, name | Mock数据 |
| Market | market_id, name | Mock数据 |

**关系类型**：
| 关系 | 说明 |
|------|------|
| `(:Customer)-[:HAS_RISK_LEVEL]->(:RiskLevel)` | 客户风险等级 |
| `(:Customer)-[:INVESTS_IN]->(:Product)` | 客户持仓 |
| `(:Product)-[:HAS_RISK_LEVEL]->(:RiskLevel)` | 产品风险等级 |
| `(:Product)-[:BELONGS_TO]->(:Industry)` | 产品所属行业 |
| `(:Product)-[:MANAGED_BY]->(:FundManager)` | 基金经理管理 |
| `(:Product)-[:SUITABLE_FOR]->(:RiskLevel)` | 适当性匹配 |

#### 数据导入

```python
# 从MySQL导入
# 1. 产品数据 → (:Product) 节点
# 2. 客户持仓 → (:Customer)-[:INVESTS_IN]->(:Product)
# 3. 风评数据 → (:Customer)-[:HAS_RISK_LEVEL]->(:RiskLevel)

# Mock数据
# 4. 行业/市场/基金经理 → (:Industry), (:Market), (:FundManager)
# 5. 产品→行业关联 → (:Product)-[:BELONGS_TO]->(:Industry)
```

#### 图谱管理接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/graph/stats` | 节点统计、关系统计 |
| GET | `/api/graph/visualization/{customer_id}` | 图谱可视化数据（节点+边JSON） |

#### 图谱Tool（Cypher封装）

| Tool名称 | 功能 | 入参 |
|----------|------|------|
| `get_customer_products` | 查询客户持仓产品 | customer_name |
| `get_product_industry` | 查询产品所属行业 | product_name |
| `get_suitable_products` | 适当性匹配产品查询 | risk_level |
| `get_industry_distribution` | 客户持仓行业分布 | customer_name |

---

### 二、业务操作Agent（NL2API）

#### 对话接口

`POST /api/chat/operator`
- 请求体：`{ session_id, message, user_id }`
- 响应体：`{ reply, action, params, status, session_id }`

#### 8种业务意图

| # | 意图 | 示例 | 可执行角色 |
|---|------|------|-----------|
| 1 | 产品申购 | "帮客户A申购10万元XX产品" | 理财顾问 |
| 2 | 产品赎回 | "赎回客户B持有的XX产品全部份额" | 理财顾问 |
| 3 | 转账 | "把客户A的50万转到客户B账户" | 理财顾问 |
| 4 | 风评重做 | "给客户A重新做风险评估" | 理财顾问 |
| 5 | 信息更新 | "把客户A的手机号改成138XXXXXXXX" | 客户经理 |
| 6 | 产品查询 | "查一下XX产品的最新净值" | 理财顾问/员工 |
| 7 | 可疑上报 | "上报客户A的可疑交易" | 风控专员 |
| 8 | 工单创建 | "为客户A创建一个投诉工单" | 客户经理 |

#### 处理流程

```
用户自然语言指令
  → 意图识别（LLM分类为8种之一）
  → 参数提取（Function Calling / Tool Use）
  → 权限校验（RBAC：角色 × 操作权限矩阵）
  → 二次确认（申购 > 1万元 或 转账 > 5万元）
  → 调用 FastAPI 业务接口执行
  → 返回操作结果
```

#### RBAC 权限矩阵

| 操作 | 理财顾问 | 客户经理 | 风控专员 | 管理员 |
|------|---------|---------|---------|--------|
| 产品申购 | ✅ | ❌ | ❌ | ✅ |
| 产品赎回 | ✅ | ❌ | ❌ | ✅ |
| 转账 | ✅ | ❌ | ❌ | ✅ |
| 风评重做 | ✅ | ❌ | ❌ | ✅ |
| 信息更新 | ❌ | ✅ | ❌ | ✅ |
| 产品查询 | ✅ | ❌ | ❌ | ✅ |
| 可疑上报 | ❌ | ❌ | ✅ | ✅ |
| 工单创建 | ❌ | ✅ | ❌ | ✅ |

---

## 我的代码位置

```
app/
├── api/
│   ├── chat.py                 # 统一对话入口，agent_type路由
│   ├── graph.py                # ★ 我的：图谱管理与可视化接口
│   └── operations/             # ★ 我的：8个业务操作API
│       ├── purchase.py
│       ├── redeem.py
│       ├── transfer.py
│       ├── contact.py
│       ├── assessment.py
│       ├── product_query.py
│       ├── suspicious_report.py
│       └── workorder.py
├── service/
│   └── operator_agent.py       # ★ 我的：业务操作Agent
├── tool/
│   ├── neo4j_tool.py           # ★ 我的：Neo4j查询封装
│   ├── graph_query_tool.py     # ★ 我的：图谱Tool（4个Cypher查询）
│   └── nl2api_tool.py          # ★ 我的：Function Calling工具
├── model/
├── config/
└── utils/
```

---

## 业务API端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/operation/purchase` | 基金申购 |
| POST | `/api/operation/redeem` | 基金赎回 |
| POST | `/api/operation/transfer` | 转账 |
| PUT | `/api/operation/contact` | 更新联系信息 |
| POST | `/api/profile/{customer_id}/assessment` | 风评重做 |
| GET | `/api/product/{id}` | 产品查询（净值） |
| POST | `/api/risk/monitor` | 可疑上报 |
| POST | `/api/workorder` | 工单创建 |

---

## Function Calling Tool定义（8个业务函数）

```python
tools = [
    {"type": "function", "function": {"name": "purchase_product", ...}},
    {"type": "function", "function": {"name": "redeem_product", ...}},
    {"type": "function", "function": {"name": "transfer_funds", ...}},
    {"type": "function", "function": {"name": "redo_assessment", ...}},
    {"type": "function", "function": {"name": "update_contact_info", ...}},
    {"type": "function", "function": {"name": "query_product_detail", ...}},
    {"type": "function", "function": {"name": "report_suspicious", ...}},
    {"type": "function", "function": {"name": "create_work_order", ...}}
]
```

---

## 我需要用到的数据库表

| 表名 | 用途 |
|------|------|
| `sys_user` | 用户角色（RBAC）、客户ID查询 |
| `fin_customer_profile` | 客户风险等级（适当性校验） |
| `fin_product` | 产品代码、净值、风险等级、起投金额 |
| `fin_transaction` | 写入交易流水 |
| `fin_holdings` | 查持仓份额、更新持仓 |
| `fin_risk_assessment` | 写入风评记录 |
| `biz_work_order` | 写入工单 |

---

## 验收标准

**知识图谱**：
- [ ] Neo4j图谱成功导入（节点数 > 100，关系数 > 200）
- [ ] 图谱多跳查询正常（≥3个场景：持仓穿透、行业分析、产品关联）

**业务操作Agent**：
- [ ] NL2API正确识别8种业务意图（准确率 > 80%，10+测试用例）
- [ ] 参数提取正确率 > 90%
- [ ] 高风险操作触发二次确认（申购>1万、转账>5万）
- [ ] 无权限操作被正确拒绝

---

## 当前开发状态

**今天日期**：2026-07-22

| 模块 | 状态 | 进度 |
|------|------|------|
| Neo4j图谱导入 | 🔴 未开始 | 0% |
| 图谱查询Tool | 🔴 未开始 | 0% |
| 图谱管理接口 | 🔴 未开始 | 0% |
| NL2API意图识别 | 🔴 未开始 | 0% |
| 8个业务操作API | 🔴 未开始 | 0% |
| RBAC权限校验 | 🔴 未开始 | 0% |
| 二次确认逻辑 | 🔴 未开始 | 0% |

---

## 时间规划

| 日期 | 任务 | 状态 |
|------|------|------|
| 7.22-7.23 | **DEMO**：Neo4j导入 + 基础图谱查询 + NL2API 1-2个意图跑通 | ⏳ 进行中 |
| 7.24 | 完善：全部8个意图 + RBAC + 二次确认 | 待开始 |
| 7.25 | 联调多Agent协调，做PPT | 待开始 |

---

## 开发优先级

### P0（DEMO必须，7.22-7.23）
1. **Neo4j数据导入** — 先导入产品、客户、风评数据
2. **基础图谱查询** — `get_customer_products`, `get_suitable_products`
3. **NL2API最小闭环** — 产品申购 + 产品查询，跑通意图识别→参数提取→执行

### P1（完善，7.24）
4. 其余6个业务意图
5. RBAC权限校验
6. 二次确认逻辑

### P2（联调，7.25）
7. 事件广播（Redis Pub/Sub）
8. 与客服/投顾Agent联调

---

## 编码规范

- Python 3.10+，PEP 8，函数签名**必须有类型注解**
- 核心逻辑**必须有中文注释**
- Commit格式：`feat:` / `fix:` / `docs:` / `refactor:` / `test:`
- 分支：`feature/knowledge-graph` 或 `feature/operator-agent`

---

## 开发注意事项

### Neo4j连接
```python
# 使用 neo4j 官方驱动
from neo4j import GraphDatabase

driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD"))
)
```

### LLM调用模板
```python
# 使用 OpenAI API 格式（兼容 Qwen/DeepSeek）
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
)

response = client.chat.completions.create(
    model=os.getenv("OPENAI_MODEL_CHAT", "gpt-4"),
    messages=[...],
    tools=[...],  # Function Calling
    tool_choice="auto"
)
```

### 错误处理
- 数据库操作必须有 `try-except`，返回统一格式
- LLM调用失败时返回友好的降级回复
- 所有异常都要记录日志（脱敏后）

## 数据脱敏规则

- 身份证：`110***1234` | 手机号：`138****5678` | 姓名：`张**` | 银行卡：`**6789`
- 脱敏位置：日志、SSE流式输出、对话归档

## Mock数据约束

- 收益率：货币1.5%-3%、债券3%-6%、混合5%-15%、股票-20%-30%
- 交易：15:00前按T日净值，之后T+1
- 单笔≤账户总资产120%，开户<首次交易，风评<购买

## 与同事的协作点

| 同事 | 协作内容 | 接口约定 |
|------|---------|---------|
| 客服Agent | 我的图谱查询可被客服调用 | `POST /api/graph/query` |
| 投顾Agent | 我提供 `get_suitable_products` 图谱查询 | Tool调用或REST |
| 风控Agent | 我执行操作后发 Redis Pub/Sub 事件 | `event:risk_alert` |
| 联调（Phase 5） | 注册到 `AGENT_REGISTRY["operator"]` | 待确认 |

## 事件广播（Redis Pub/Sub）

我的操作执行后广播：
- 申购/赎回/转账 → `event:risk_alert` → 风控Agent
- 信息更新 → `event:profile_update` → 投顾/客服
- 工单创建 → `event:work_order_change`

消息体：`{ event_type, source_agent: "operator", payload, timestamp, trace_id }`

```python
# 事件广播示例
import redis
import json

redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST"),
    port=int(os.getenv("REDIS_PORT")),
    password=os.getenv("REDIS_PASSWORD"),
    db=int(os.getenv("REDIS_DB", "0"))
)

def publish_event(event_type: str, payload: dict, trace_id: str):
    """发布事件到 Redis Pub/Sub"""
    message = {
        "event_type": event_type,
        "source_agent": "operator",
        "payload": payload,
        "timestamp": datetime.now().isoformat(),
        "trace_id": trace_id
    }
    redis_client.publish(event_type, json.dumps(message, ensure_ascii=False))
```

---

## 测试用例模板

### 图谱查询测试
```python
def test_get_customer_products():
    """测试查询客户持仓产品"""
    result = get_customer_products(customer_name="张三")
    assert len(result) > 0
    assert "product_name" in result[0]

def test_get_suitable_products():
    """测试适当性产品匹配"""
    result = get_suitable_products(risk_level="R3")
    assert all(p["risk_level"] in ["R1", "R2", "R3"] for p in result)
```

### NL2API 测试
```python
def test_purchase_intent():
    """测试申购意图识别"""
    response = operator_chat("帮客户张三申购10万元稳健增长混合A")
    assert response["action"] == "purchase"
    assert response["params"]["customer_name"] == "张三"
    assert response["params"]["amount"] == 100000
    assert response["params"]["product_name"] == "稳健增长混合A"

def test_permission_denied():
    """测试无权限操作被拒绝"""
    # 客户经理不能执行申购
    response = operator_chat("...", user_role="customer_manager")
    assert response["status"] == "error"
    assert "permission" in response["reply"].lower()

def test_double_confirm():
    """测试大额操作触发二次确认"""
    response = operator_chat("帮客户申购50万元XX产品")
    assert response["status"] == "confirm_required"
    assert "确认" in response["reply"]
```

---

## 快速开始命令

```bash
# 启动开发服务器
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 测试 Neo4j 连接
python -c "from app.config.db_config import check_neo4j_connection; check_neo4j_connection()"

# 测试 MySQL 连接
python -c "from app.config.db_config import check_mysql_connection; check_mysql_connection()"

# 测试 Redis 连接
python -c "from app.config.db_config import check_redis_connection; check_redis_connection()"
```

---

## 重要提醒

1. **不要提交 .env 文件** — 包含敏感密码
2. **不要提交 .idea/ 文件** — IDE 个人配置
3. **提交前运行** — `git status` 检查是否有敏感文件
4. **数据脱敏** — 日志中不要输出完整身份证号、银行卡号
5. **异常处理** — 所有数据库操作必须有 try-except
