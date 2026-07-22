# NL2SQL 数据分析模块 — 需求与设计文档

> 版本：v1.0  
> 日期：2026-07-22  
> 模块路径：`edu_pro/app/`

---

## 一、模块概述

### 1.1 背景

理财顾问在日常工作中需要频繁查询业务数据（客户画像、持仓、交易流水、产品信息等），传统方式依赖开发人员编写 SQL 或通过固定报表查看，响应慢、灵活度低。

NL2SQL（Natural Language to SQL）模块将自然语言自动转化为 SQL 语句，使业务人员可以直接用中文提问，系统自动生成 SQL、执行查询、并对结果进行自然语言解读。

### 1.2 核心能力

- **自然语言 → SQL**：用户输入中文问题，LLM 根据表结构生成 SELECT 语句
- **动态 Schema 匹配**：根据问题关键词自动筛选相关表，减少 Prompt Token 消耗
- **安全校验**：多层正则校验，禁止 DROP/DELETE/UPDATE 等危险操作
- **结果解读**：查询结果回传 LLM，生成简洁的自然语言总结
- **Mock 模式**：无 API Key 时自动降级为模拟模式，不阻塞开发调试

### 1.3 技术栈

| 组件 | 选型 |
|---|---|
| LLM 调用 | OpenAI 1.x SDK（兼容 DeepSeek / Qwen / GPT） |
| 数据库查询 | SQLAlchemy 2.x 同步引擎 + PyMySQL |
| Schema 来源 | MySQL `INFORMATION_SCHEMA.COLUMNS` |
| API 框架 | FastAPI |
| 数据校验 | Pydantic v2 |

---

## 二、模块架构

### 2.1 文件清单

```
app/
├── tool/
│   └── llm_client.py          # LLM 客户端（OpenAI 封装）
├── service/
│   └── nl2sql_service.py      # NL2SQL 核心服务
├── api/
│   └── chat.py                 # API 路由（数据分析部分）
├── model/
│   └── schemas.py              # 请求/响应模型
└── config/
    └── database.py             # 同步 SessionLocal（待恢复）
```

### 2.2 调用链路

```
用户自然语言
    │
    ▼
POST /chat/analyst  ──►  chat_analyst()        [app/api/chat.py]
    │                         │
    ▼                         ▼
QueryRequest ──────────►  NL2SQLService          [app/service/nl2sql_service.py]
                              │
                    ┌─────────┼─────────┐
                    ▼         ▼         ▼
              generate_sql  validate  execute
                    │                   │
                    ▼                   ▼
              LLMClient           SessionLocal
            [app/tool/llm_client.py]   [app/config/database.py]
                    │
                    ▼
            OpenAI API (gpt-3.5-turbo)
```

### 2.3 数据流

```
query (str)
  → _get_dynamic_schema()    → 相关表 DDL
  → _get_few_shot_examples() → Few-shot 示例
  → LLMClient.generate_sql() → SQL (str)
  → validate_sql()           → (bool, msg)
  → execute_sql()            → {columns, rows, row_count}
  → LLMClient.explain_result() → 自然语言解读 (str)
  → QueryResponse
```

---

## 三、详细设计

### 3.1 数据模型（`app/model/schemas.py`）

#### QueryRequest — 查询请求

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| session_id | str | 是 | 会话 ID，关联上下文 |
| message | str | 是 | 用户自然语言查询 |
| user_id | int | 是 | 操作用户 ID |

#### QueryResponse — 查询响应

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| reply | str | 是 | 自然语言解读 |
| sql | Optional[str] | 否 | 生成的 SQL 语句 |
| query_result | Optional[List[Dict]] | 否 | 查询结果列表 |
| session_id | str | 是 | 会话 ID |
| error | Optional[str] | 否 | 错误信息 |

### 3.2 LLM 客户端（`app/tool/llm_client.py`）

#### 类：LLMClient

**初始化逻辑：**
- 从环境变量 `OPENAI_API_KEY` 读取密钥
- 有密钥 → `mock_mode = False`，创建 `OpenAI` 客户端实例
- 无密钥 → `mock_mode = True`，打印警告，所有方法返回模拟值

**方法列表：**

| 方法 | 签名 | 功能 |
|---|---|---|
| `chat` | `(prompt, system_prompt?, max_retries=3) → str` | 调用 Chat Completions API，指数退避重试（1s/2s/4s） |
| `generate_sql` | `(user_query, schema_text) → str` | 用 Few-shot Prompt 模板生成 SQL，自动清理 Markdown 标记 |
| `explain_result` | `(query, result) → str` | 对查询结果做自然语言解读 |

**Prompt 模板（generate_sql）：**

```
你是一个SQL专家。根据以下表结构，将自然语言转为SQL语句。

【表结构】
{schema_text}

【规则】
1. 只允许SELECT查询
2. 字段名用反引号包裹
3. 字符串用单引号

【示例】
用户问：查询所有在售产品
SQL：SELECT * FROM `fin_product` WHERE `status` = '在售'
...

用户问：{user_query}
SQL：
```

**Mock 模式行为：**

| 方法 | Mock 返回值 |
|---|---|
| `chat` | `"[模拟回复] 已收到您的请求，当前为模拟模式。"` |
| `generate_sql` | `"SELECT * FROM \`fin_product\` WHERE \`status\` = '在售'"` |
| `explain_result` | `"【模拟解读】查询完成，共返回 N 条记录。"` |

### 3.3 NL2SQL 服务（`app/service/nl2sql_service.py`）

#### 类：NL2SQLService

**业务表范围（10 张）：**

| 表名 | 说明 |
|---|---|
| sys_user | 统一用户表 |
| fin_product | 金融产品表 |
| fin_customer_profile | 客户画像主表 |
| fin_transaction | 交易流水表 |
| fin_holdings | 持仓表 |
| fin_risk_assessment | 风险评估问卷记录 |
| fin_risk_alert | 风险预警表 |
| biz_work_order | 业务工单表 |
| conversation_archive | 对话归档表 |
| fin_knowledge_meta | 知识库元数据表 |

> ⚠️ `sys_table_dict` 是项目内部管理表（表结构说明），**不暴露**给 NL2SQL 查询。

#### 关键词 → 表映射

| 关键词 | 匹配表 |
|---|---|
| 用户 / 客户 / 员工 | sys_user |
| 产品 / 理财 | fin_product |
| 持仓 / 持有 / 份额 | fin_holdings |
| 交易 / 申购 / 赎回 / 流水 | fin_transaction |
| 画像 | fin_customer_profile |
| 风险 / 预警 / 风控 | fin_risk_alert |
| 工单 | biz_work_order |
| 知识 | fin_knowledge_meta |

无匹配关键词时，默认返回 `sys_user + fin_product + fin_holdings` 三张核心表。

#### 方法列表

| 方法 | 功能 |
|---|---|
| `_get_all_schemas()` | 从 INFORMATION_SCHEMA 读取所有表 DDL，缓存 |
| `_get_dynamic_schema(query)` | 关键词匹配 → 提取相关表 DDL |
| `_get_few_shot_examples()` | 返回 5 个固定 Few-shot 示例 |
| `generate_sql(query)` | 组装 Schema + 示例 → 调用 LLM 生成 SQL |
| `validate_sql(sql)` | 正则校验：只允许 SELECT，拦截危险关键词 |
| `execute_sql(sql)` | 同步执行 SQL，最多 100 行 |
| `query_and_explain(query)` | **主流程**：生成 → 校验 → 执行 → 解读 |
| `get_table_list()` | 返回 10 张业务表名 |

#### 安全校验（validate_sql）

- SQL 不能为空
- 必须以 `SELECT` 开头
- 禁用关键词（单词边界匹配）：`DROP` `DELETE` `UPDATE` `INSERT` `ALTER` `TRUNCATE` `CREATE` `EXEC` `EXECUTE`

#### Few-shot 示例（5 条）

1. "查询所有在售产品" → `SELECT * FROM fin_product WHERE status = '在售'`
2. "客户张三的持仓有哪些" → JOIN 查询
3. "统计各产品类型的平均收益率" → GROUP BY + AVG
4. "查询客户张三的画像" → 子查询
5. "AUM超过100万的客户有多少个" → COUNT + WHERE

#### query_and_explain 返回格式

```json
{
  "success": true,
  "sql": "SELECT ...",
  "query_result": [{"col": "val"}, ...],
  "explanation": "根据查询结果，目前...",
  "error": null
}
```

### 3.4 API 路由（`app/api/chat.py` — 数据分析部分）

| 方法 | 路由 | 说明 |
|---|---|---|
| POST | `/chat/analyst` | NL2SQL 对话：接收自然语言，返回 SQL + 结果 + 解读 |
| GET | `/chat/session/{session_id}/history` | 会话历史（预留接口） |

**POST /chat/analyst 流程：**

1. 接收 `QueryRequest`
2. 调用 `NL2SQLService.query_and_explain(message)`
3. 成功 → 返回 `success`，data 包含 reply/sql/query_result/session_id
4. 失败 → 返回 `error`（code=1003），data 包含 sql/session_id
5. 异常 → 返回 `error`（code=500）

### 3.5 数据库同步引擎（`app/config/database.py`）

> ⚠️ 该依赖需在 `database.py` 中补充（当前可能缺失）

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_sync_url = f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{db}?charset=utf8mb4"

sync_engine = create_engine(_sync_url, pool_size=10, pool_recycle=3600, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)
```

---

## 四、依赖清单

```
# requirements.txt 相关项
openai>=1.30.0          # LLM 调用（OpenAI 1.x SDK）
sqlalchemy>=2.0.30      # ORM + 同步引擎
pymysql>=1.1.0          # MySQL 驱动（同步）
pydantic>=2.7.0         # 数据校验
fastapi>=0.111.0        # Web 框架
```

---

## 五、安全设计

| 层级 | 措施 |
|---|---|
| SQL 校验 | 正则匹配禁止关键词，只允许 SELECT |
| 行数限制 | `execute_sql` 硬限制 100 行 |
| 表范围控制 | 10 张白名单表，`sys_table_dict` 不暴露 |
| 无 API Key 降级 | 自动进入 Mock 模式，不调用外部 API |
| Prompt 注入防护 | 规则中明确"只允许 SELECT"，Few-shot 均为 SELECT 示例 |

---

## 六、待完成项

- [ ] 恢复 `app/config/database.py` 中的同步 `SessionLocal`
- [ ] 实现会话历史持久化（`GET /chat/session/{session_id}/history`）
- [ ] 添加查询结果缓存（相同 SQL + 参数 → Redis 缓存）
- [ ] 支持多轮对话上下文（当前每次查询独立）
- [ ] 接入前端对话界面
- [ ] 单元测试覆盖（Mock 模式下的全流程测试）
