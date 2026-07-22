# 智能财富管家系统 — 项目架构文档

> 版本: V1.0 | 更新: 2026-07-22 | 框架: FastAPI + SQLAlchemy + LangChain

---

## 一、系统总览架构图

```mermaid
graph TB
    subgraph 前端
        UI["理财顾问<br/>Streamlit / API 调用方"]
    end

    subgraph 入口
        MAIN["main.py<br/>FastAPI 入口<br/>● /api/health<br/>● /api/engine/test"]
    end

    subgraph 路由层
        direction TB
        A1["profile.py<br/>画像 CRUD + 研判"]
        A2["risk.py<br/>风评问卷 + 适当性"]
        A3["advisor.py<br/>投顾对话"]
        A4["chat.py<br/>SSE 流式"]
        A5["admin.py<br/>管理后台"]
        A6["knowledge.py<br/>知识库管理"]
    end

    subgraph Agent层
        direction TB
        B1["base_agent.py<br/>统一执行骨架"]
        B2["profile_agent.py<br/>画像 Agent"]
        B3["recommendation_agent.py<br/>推荐 Agent"]
        B4["explanation_agent.py<br/>解释 Agent"]
    end

    subgraph 规则引擎
        direction TB
        C1["dimension_calculator.py<br/>四维度计算器"]
        C2["circuit_breaker.py<br/>5 条熔断规则"]
        C3["special_case.py<br/>特殊场景"]
        C4["confidence.py<br/>置信度"]
        C5["score_mapper.py<br/>等级映射"]
    end

    subgraph 业务服务层
        direction TB
        D1["profile_service.py"]
        D2["advisor_service.py"]
        D3["risk_service.py"]
        D4["agent_service.py"]
        D5["memory_service.py"]
        D6["rag_service.py"]
        D7["risk_monitor_service.py"]
    end

    subgraph Tool层
        direction TB
        E1["profile_tool"]
        E2["graph_tool"]
        E3["holding_tool"]
        E4["recommendation_tool"]
        E5["allocation_tool"]
        E6["milvus_tool"]
        E7["document_parser"]
        E8["embedding_tool"]
    end

    subgraph 数据基础架构
        direction LR
        F1[("MySQL<br/>业务数据<br/>14 张表")]
        F2[("Redis<br/>缓存/会话")]
        F3[("Neo4j<br/>知识图谱")]
        F4[("Milvus<br/>向量检索")]
        F5[("MinIO<br/>文档存储")]
    end

    UI --> MAIN
    MAIN --> 路由层
    路由层 --> Agent层
    路由层 --> 业务服务层
    Agent层 --> 业务服务层
    Agent层 --> Tool层
    业务服务层 --> Tool层
    业务服务层 --> 规则引擎
    Tool层 --> 规则引擎
    Tool层 --> 数据基础架构
    规则引擎 --> 数据基础架构
    业务服务层 --> 数据基础架构
```

---

## 二、分层架构详解

### 2.1 上层：请求入口 → Agent 编排 → 业务服务

```mermaid
graph TB
    subgraph L0["L0 · 入口层"]
        MAIN["<b>main.py</b><br/>FastAPI 应用入口<br/>路由注册 · CORS · 生命周期"]
    end

    subgraph L1["L1 · 路由层 — app/api/ — 6 个模块"]
        direction LR
        API1["<b>profile.py</b><br/>画像 CRUD / 研判"]
        API2["<b>risk.py</b><br/>风评问卷 / 适当性"]
        API3["<b>advisor.py</b><br/>投顾对话 / 推荐 / 配置"]
        API4["<b>chat.py</b><br/>SSE 流式对话"]
        API5["<b>admin.py</b><br/>管理后台"]
        API6["<b>knowledge.py</b><br/>知识库管理"]
    end

    subgraph L2["L2 · Agent 编排层 — app/agent/ — 4 个模块"]
        direction LR
        AG1["<b>base_agent.py</b><br/>抽象基类<br/>统一执行骨架"]
        AG2["<b>profile_agent.py</b><br/>画像 Agent<br/>信息抽取+标签生成"]
        AG3["<b>recommendation_agent.py</b><br/>推荐 Agent<br/>产品匹配+排序"]
        AG4["<b>explanation_agent.py</b><br/>解释 Agent<br/>理由生成+风险解读"]
    end

    subgraph L3["L3 · 业务服务层 — app/service/ — 7 个模块"]
        direction LR
        SV1["<b>profile_service</b><br/>画像业务编排<br/>Cache-Aside"]
        SV2["<b>advisor_service</b><br/>推荐 Pipeline<br/>过滤→排序→TopN"]
        SV3["<b>risk_service</b><br/>风评问卷/答题<br/>适当性匹配"]
        SV4["<b>agent_service</b><br/>Agent 工厂<br/>模型路由"]
        SV5["<b>memory_service</b><br/>三层记忆<br/>统一入口"]
        SV6["<b>rag_service</b><br/>GraphRAG<br/>向量+图谱融合"]
        SV7["<b>risk_monitor_service</b><br/>异常检测<br/>预警记录"]
    end

    L0 --> L1
    L1 --> L2
    L1 --> L3
    L2 --> L3
```

### 2.2 下层：规则引擎 → Tool 工具 → 数据基础架构

```mermaid
graph TB
    subgraph L4["L4 · 规则引擎层 — app/engine/ — 5 个模块 | 纯逻辑 · 100% 可测试"]
        direction LR
        EG1["<b>dimension_calculator</b><br/>四维度计算器<br/>+ evaluate_customer()"]
        EG2["<b>circuit_breaker</b><br/>5 条熔断<br/>FM-01 ~ FM-05"]
        EG3["<b>special_case</b><br/>特殊场景<br/>信息缺失/冲突"]
        EG4["<b>confidence</b><br/>置信度计算<br/>来源优先级"]
        EG5["<b>score_mapper</b><br/>分数→C1-C5<br/>产品适当性矩阵"]
    end

    subgraph L5["L5 · Tool 工具层 — app/tool/ — 8 个模块 | Agent 可调用的原子能力"]
        direction LR
        TL1["<b>profile_tool</b><br/>画像查询"]
        TL2["<b>graph_tool</b><br/>图谱查询"]
        TL3["<b>holding_tool</b><br/>持仓分析"]
        TL4["<b>recommendation_tool</b><br/>推荐打分"]
        TL5["<b>allocation_tool</b><br/>资产配置"]
        TL6["<b>milvus_tool</b><br/>向量检索"]
        TL7["<b>document_parser</b><br/>文档解析"]
        TL8["<b>embedding_tool</b><br/>向量嵌入"]
    end

    subgraph L6["L6 · 数据基础架构 — 5 大数据源"]
        direction LR
        D1[("<b>MySQL</b><br/>业务数据<br/>14 张表")]
        D2[("<b>Redis</b><br/>缓存/会话<br/>TTL 管理")]
        D3[("<b>Neo4j</b><br/>知识图谱<br/>关系推理")]
        D4[("<b>Milvus</b><br/>向量检索<br/>语义相似")]
        D5[("<b>MinIO</b><br/>文档存储<br/>PDF/Word")]
    end

    L4 --> L5
    L5 --> L6
    L4 --> L6
```

### 2.3 跨层调用关系

```mermaid
flowchart LR
    subgraph 上层["请求处理流"]
        API["路由层<br/>app/api/"]
        AGENT["Agent 层<br/>app/agent/"]
        SVC["业务服务层<br/>app/service/"]
    end

    subgraph 下层["能力提供层"]
        ENGINE["规则引擎<br/>app/engine/"]
        TOOL["Tool 层<br/>app/tool/"]
        DATA["数据层<br/>MySQL/Redis/Neo4j/Milvus/MinIO"]
    end

    API -->|"意图路由"| AGENT
    API -->|"直接调用"| SVC
    AGENT -->|"编排调度"| SVC
    AGENT -->|"调用工具"| TOOL
    SVC -->|"调用规则"| ENGINE
    SVC -->|"调用工具"| TOOL
    TOOL -->|"计算依赖"| ENGINE
    SVC -->|"读写数据"| DATA
    TOOL -->|"读写数据"| DATA
    ENGINE -->|"读取配置"| DATA
```

---

## 三、数据流转核心链路

### 3.1 画像研判链路（最核心路径）

```mermaid
sequenceDiagram
    actor Client as 理财顾问
    participant API as profile.py
    participant SVC as ProfileService
    participant DB as MySQL
    participant CB as CircuitBreaker
    participant DC as DimensionCalculator
    participant SC as SpecialCaseHandler
    participant Cache as Redis

    Client->>API: POST /api/profile/{id}/assess
    API->>SVC: assess(customer_id)

    Note over SVC: ① 数据采集
    SVC->>DB: SELECT sys_user
    DB-->>SVC: 基础信息 (年龄/学历/职业...)
    SVC->>DB: SELECT fin_customer_profile
    DB-->>SVC: 已有画像
    SVC->>DB: SELECT fin_risk_assessment
    DB-->>SVC: 最近风评

    Note over SVC,CB: ② 熔断检查
    SVC->>CB: check_all(customer_data)
    CB-->>SVC: {passed, triggered_rules, warnings}

    Note over SVC,DC: ③ 四维度打分
    SVC->>DC: calc_all(customer_data)
    DC->>DC: BasicDimension.calc() → 维度一 (0-25)
    DC->>DC: ExperienceDimension.calc() → 维度二 (0-25)
    DC->>DC: RiskPrefDimension.calc() → 维度三 (0-30)
    DC->>DC: BehaviorDimension.calc() → 维度四 (0-20)
    DC-->>SVC: 四维度得分明细

    Note over SVC: ④ 综合评分 + 等级映射
    SVC->>SVC: total = Σ(维度得分) → C1-C5

    Note over SVC,SC: ⑤ 特殊场景处理
    SVC->>SC: handle(customer_data, ai_level)
    SC-->>SVC: 调整结果

    Note over SVC,DB: ⑥ 持久化
    SVC->>DB: UPDATE fin_customer_profile
    SVC->>DB: INSERT risk_score_record (评分记录)

    Note over SVC,Cache: ⑦ 失效缓存
    SVC->>Cache: DEL profile:{customer_id}

    SVC-->>API: 研判结果
    API-->>Client: {risk_level, risk_score, dimensions, warnings}
```

### 3.2 投顾对话链路

```mermaid
sequenceDiagram
    actor Client as 理财顾问
    participant API as advisor.py
    participant PA as ProfileAgent
    participant RA as RecommendationAgent
    participant EA as ExplanationAgent
    participant Tool as Tools
    participant LLM as LLM (DeepSeek)
    participant RAG as GraphRAG
    participant Data as 数据层

    Client->>API: POST /api/chat/advisor<br/>{message: "给张三推荐3款产品"}

    Note over API: 意图识别<br/>关键词: "推荐"

    API->>PA: execute(message, customer_id)
    PA->>Tool: ProfileTool.get_profile(id)
    Tool->>Data: Redis/MySQL 画像查询
    Data-->>Tool: 客户画像
    PA->>Tool: SessionMemory.get_messages()
    Tool->>Data: Redis 会话历史
    Data-->>Tool: 上下文
    PA->>LLM: 提示词 + 画像
    LLM-->>PA: 画像摘要

    API->>RA: execute(message, customer_id)

    rect rgb(240, 248, 255)
        Note over RA,Tool: 推荐 Pipeline
        RA->>Tool: GraphTool.query()
        Tool->>Data: Neo4j 持仓图谱
        Data-->>Tool: 行业分布

        RA->>Tool: RecommendationTool.score()
        Tool->>Tool: ① 风险过滤
        Tool->>Tool: ② 适当性过滤
        Tool->>Tool: ③ 偏好过滤
        Tool->>Tool: ④ 持仓互补检查
        Tool->>Tool: ⑤ Score = 0.4×风险 + 0.25×偏好<br/>   + 0.2×互补 + 0.15×收益
        Tool-->>RA: TopN 产品

        RA->>Tool: AllocationTool.allocate(risk_level)
        Tool-->>RA: C1-C5 配置模板
    end

    API->>EA: execute(推荐结果, 客户画像)

    rect rgb(255, 248, 240)
        Note over EA,RAG: GraphRAG 增强检索
        EA->>RAG: retrieve(query)
        RAG->>Data: Milvus TopK 检索 (权重 0.6)
        RAG->>Data: Neo4j 多跳查询 (权重 0.4)
        RAG->>RAG: 融合排序: α×Score_A + β×Score_B
        RAG-->>EA: 检索上下文
    end

    EA->>LLM: 上下文 + 推荐结果 + 画像
    LLM-->>EA: 推荐理由 + 风险解释

    API-->>Client: {reply, recommendations,<br/>customer_profile, reasoning}
```

---

## 四、数据库架构

### 4.1 存储矩阵

```mermaid
graph TB
    subgraph MySQL["MySQL (education_pro) — 14 张业务表"]
        direction TB
        subgraph 核心业务域
            direction LR
            T1["sys_user<br/>统一用户"]
            T2["fin_customer_profile<br/>客户画像主表"]
            T3["customer_tag<br/>画像标签"]
        end

        subgraph 风控域
            direction LR
            T4["fin_risk_assessment<br/>风评问卷记录"]
            T5["risk_score_record<br/>评分过程记录"]
            T6["risk_rule<br/>规则配置"]
            T7["fin_risk_alert<br/>风控预警"]
        end

        subgraph 产品域
            direction LR
            T8["fin_product<br/>金融产品"]
            T9["fin_holdings<br/>持仓"]
            T10["fin_transaction<br/>交易流水"]
            T11["product_recommendation<br/>推荐结果"]
        end

        subgraph 通用域
            direction LR
            T12["biz_work_order<br/>业务工单"]
            T13["conversation_archive<br/>会话归档"]
            T14["fin_knowledge_meta<br/>知识元数据"]
        end

        T1 -->|1:1| T2
        T2 -->|1:N| T3
        T2 -->|1:N| T4
        T2 -->|1:N| T5
        T2 -->|1:N| T9
        T2 -->|1:N| T10
        T2 -->|1:N| T11
        T2 -->|1:N| T7
        T9 -->|N:1| T8
        T10 -->|N:1| T8
    end

    subgraph Redis["Redis — 缓存 + 会话"]
        direction LR
        R1["session:{id}:messages<br/>会话消息 List<br/>TTL: 30min"]
        R2["profile:{id}<br/>画像 JSON 缓存<br/>TTL: 7d"]
        R3["risk:rule:version<br/>规则版本号"]
    end

    subgraph Neo4j["Neo4j — 知识图谱"]
        direction TB
        N1["(Customer)"] -->|"INVESTS_IN"| N2["(Product)"]
        N2 -->|"BELONGS_TO"| N3["(Industry)"]
        N4["(RiskLevel)"] -->|"HAS_PRODUCT"| N2
        N1 -->|"HAS_RISK_LEVEL"| N4
        N2 -->|"MANAGED_BY"| N5["(FundManager)"]
    end

    subgraph Milvus["Milvus — 向量检索"]
        direction LR
        M1["faq_knowledge<br/>FAQ 向量 (1536d)"]
        M2["product_knowledge<br/>产品说明向量"]
        M3["policy_knowledge<br/>政策法规向量"]
    end

    subgraph MinIO["MinIO — 文档存储"]
        O1["knowledge-docs/<br/>PDF / Word / Markdown"]
    end

    MySQL -.- 业务数据
    Redis -.- 缓存加速
    Neo4j -.- 关系推理
    Milvus -.- 语义检索
    MinIO -.- 原始文件
```

### 4.2 核心表 ER 关系

```mermaid
erDiagram
    sys_user ||--|| fin_customer_profile : "1:1 画像"
    fin_customer_profile ||--o{ customer_tag : "1:N 标签"
    fin_customer_profile ||--o{ risk_score_record : "1:N 评分"
    fin_customer_profile ||--o{ fin_risk_assessment : "1:N 风评"
    fin_customer_profile ||--o{ product_recommendation : "1:N 推荐"
    fin_customer_profile ||--o{ fin_holdings : "1:N 持仓"
    fin_customer_profile ||--o{ fin_transaction : "1:N 交易"
    fin_customer_profile ||--o{ fin_risk_alert : "1:N 预警"
    fin_holdings }o--|| fin_product : "N:1 产品"
    fin_transaction }o--|| fin_product : "N:1 产品"

    sys_user {
        bigint id PK
        varchar username UK
        varchar user_type "CUSTOMER/EMPLOYEE"
        varchar employee_role "理财顾问/风控专员"
        varchar customer_level "普通/金卡/白金"
        varchar real_name
        varchar phone
        varchar id_card
        int age
        varchar education
        varchar occupation
    }

    fin_customer_profile {
        bigint id PK
        bigint customer_id UK "→ sys_user.id"
        varchar risk_level "C1-C5"
        int risk_score "0-100"
        decimal confidence_score "0.00-1.00"
        decimal basic_score "维度一"
        decimal experience_score "维度二"
        decimal risk_pref_score "维度三"
        decimal behavior_score "维度四"
        json profile_json "完整画像"
    }

    customer_tag {
        bigint id PK
        bigint customer_id FK
        varchar tag_name "risk_preference"
        varchar tag_value "稳健型"
        varchar source "questionnaire/ai_extract/self_report"
        decimal confidence "0.00-1.00"
        date valid_until
    }

    risk_score_record {
        bigint id PK
        bigint customer_id FK
        datetime rating_date
        decimal basic_score
        decimal experience_score
        decimal risk_pref_score
        decimal behavior_score
        decimal total_score
        varchar risk_level "C1-C5"
        json detail_json "子项明细"
        json circuit_breakers "触发熔断"
        varchar trigger_type "manual/auto/event"
    }
```

---

## 五、Memory 三层记忆架构

```mermaid
graph TB
    subgraph 短期记忆["短期记忆 — Redis"]
        direction TB
        S1["Key: session:{session_id}:messages"]
        S2["类型: Redis List"]
        S3["TTL: 30 min + 每次续期<br/>最长 24h"]
        S4["Token 上限: 4096<br/>超出截断旧消息"]
        S5["用途: 当前对话上下文"]
        S1 --> S2 --> S3 --> S4 --> S5
    end

    subgraph 中期记忆["中期记忆 — Redis Cache-Aside"]
        direction TB
        M1["Key: profile:{customer_id}"]
        M2["类型: JSON 缓存"]
        M3["TTL: 7 天"]
        M4["读取策略:<br/>① 查 Redis → 命中返回<br/>② 未命中 → 查 MySQL<br/>③ 回填 Redis"]
        M5["失效触发:<br/>● 风评更新<br/>● 持仓变化<br/>● 大额交易"]
        M6["用途: 画像快速读取"]
        M1 --> M2 --> M3 --> M4 --> M5 --> M6
    end

    subgraph 长期记忆["长期记忆 — MySQL + Neo4j + Milvus"]
        direction LR
        L1["MySQL<br/>─────<br/>交易历史<br/>评分记录<br/>画像变更日志<br/>会话归档"]
        L2["Neo4j<br/>─────<br/>客户↔产品↔行业<br/>知识图谱<br/>关系推理"]
        L3["Milvus<br/>─────<br/>FAQ 向量<br/>产品说明向量<br/>政策法规向量"]
        L4["用途: 历史追溯<br/>关系推理<br/>语义检索"]
        L1 --- L2 --- L3 --- L4
    end

    短期记忆 -->|"会话结束归档"| 中期记忆
    中期记忆 -->|"漂移检测触发"| 长期记忆
    长期记忆 -->|"GraphRAG 回填"| 短期记忆
```

---

## 六、规则引擎架构

```mermaid
flowchart TD
    INPUT["evaluate_customer(customer_data)"]
    INPUT --> SPLIT{并行执行}

    SPLIT --> DC["DimensionCalculator<br/>四维度计算器"]
    SPLIT --> CB["CircuitBreaker<br/>5 条熔断规则"]
    SPLIT --> SM["ScoreMapper<br/>等级映射"]

    DC --> D1["BasicDimension<br/>维度一 满分25<br/>公式: Σ(5项)÷5÷10×25<br/>年龄/学历/职业/收入/资产"]
    DC --> D2["ExperienceDimension<br/>维度二 满分25<br/>公式: Σ(4项)÷4÷10×25<br/>年限/复杂度/频率/收益"]
    DC --> D3["RiskPrefDimension<br/>维度三 满分30 [0,30]<br/>公式: 风评+情绪化+亏损承受<br/>● C1→5 C2→10 C3→15<br/>● 追涨杀跌-3 恐慌赎回-5"]
    DC --> D4["BehaviorDimension<br/>维度四 满分20<br/>8种异常行为计分<br/>无异常20 任何高风险0"]

    CB --> F1["FM-01 年龄限制<br/><18禁止 >70面签 >80仅R1"]
    CB --> F2["FM-02 收入资产<br/>无收入+资产<1万→仅R1-R2"]
    CB --> F3["FM-03 风评时效<br/>>12月冻结 >6月提醒"]
    CB --> F4["FM-04 身份异常<br/>过期>90天冻结 制裁名单冻结"]
    CB --> F5["FM-05 交易熔断<br/>日亏>10% 连续大额赎回"]

    SM --> S1["综合得分 = Σ(四维度得分)<br/>满分 100"]
    S1 --> S2["等级映射<br/>0-25→C1 26-40→C2<br/>41-60→C3 61-80→C4<br/>81-100→C5"]
    S2 --> S3["产品矩阵<br/>C1→R1-R2 C2→R1-R3<br/>C3→R1-R4 C4→R1-R5<br/>C5→R1-R5"]

    D1 & D2 & D3 & D4 --> MERGE
    F1 & F2 & F3 & F4 & F5 --> MERGE
    S1 & S2 & S3 --> MERGE

    MERGE["汇总结果"]
    MERGE --> SC["SpecialCaseHandler<br/>● 信息不完整→保守下调<br/>● 自评vsAI冲突→人工复核<br/>● 特殊人群→额外限制"]
    SC --> OUTPUT["最终研判结果<br/>{passed, total_score, risk_level,<br/>dimensions, circuit_breakers,<br/>warnings, suitable_products}"]
```

---

## 七、知识库数据流

```mermaid
flowchart LR
    subgraph 知识源["data/knowledge/"]
        direction TB
        K1["公司信息/<br/>企业信息.md<br/>新人指南.md<br/>高频问答对.txt"]
        K2["公司业务/<br/>个人理财产品手册.md<br/>企业金融服务方案.md<br/>高净值客户服务规范.md"]
        K3["金融政策/<br/>适当性管理指南.md<br/>反洗钱合规手册.md<br/>理财产品销售办法.md"]
        K4["用户研判规则/<br/>投资者风险画像研判规则.md<br/>反洗钱可疑交易识别规则.md<br/>用户信息数据示例.md"]
    end

    subgraph 处理["处理管道"]
        direction TB
        P1["document_parser.py<br/>文档解析<br/>Markdown → 文本块"]
        P2["embedding_tool.py<br/>向量嵌入<br/>文本 → 1536d 向量"]
    end

    subgraph 存储["存储目标"]
        direction TB
        S1["Milvus<br/>faq_knowledge<br/>FAQ 语义检索"]
        S2["Milvus<br/>product_knowledge<br/>产品说明检索"]
        S3["Milvus<br/>policy_knowledge<br/>政策法规检索"]
        S4["app/config/<br/>rules_config.py<br/>规则配置（不入向量库）"]
    end

    subgraph 消费["消费场景"]
        direction TB
        C1["知识库管理 API<br/>GET /api/knowledge/*"]
        C2["投顾对话<br/>GraphRAG 检索增强"]
        C3["规则引擎<br/>evaluate_customer()"]
    end

    K1 --> P1
    K2 --> P1
    K3 --> P1
    K4 -->|"规则走引擎<br/>不入 Milvus"| S4

    P1 --> P2
    P2 --> S1
    P2 --> S2
    P2 --> S3

    S1 --> C1
    S1 --> C2
    S2 --> C1
    S2 --> C2
    S3 --> C1
    S3 --> C2
    S4 --> C3
```

---

## 八、部署拓扑

```mermaid
graph TB
    subgraph 应用层["应用层 — Python 进程"]
        APP["FastAPI App<br/>main.py :8000<br/>● /api/profile/*<br/>● /api/risk/*<br/>● /api/chat/*"]
    end

    subgraph 中间件["基础设施 — Docker / 物理机"]
        direction LR

        subgraph MySQL_CT["MySQL :3306"]
            M_DB["education_pro<br/>14 张业务表"]
        end

        subgraph Redis_CT["Redis :6379"]
            R_DB["db:0<br/>缓存 + 会话"]
        end

        subgraph Neo4j_CT["Neo4j :7687"]
            N_DB["neo4j<br/>知识图谱"]
        end

        subgraph Milvus_CT["Milvus :19530"]
            V_DB["3 个 Collection<br/>向量检索"]
        end

        subgraph MinIO_CT["MinIO :9000"]
            O_DB["knowledge-docs<br/>文档存储"]
        end

        subgraph LLM_CT["LLM API"]
            L_API["DeepSeek API<br/>deepseek-v4-pro<br/>+ 本地 LongCat 降级"]
        end
    end

    subgraph 前端层["前端"]
        FE["Streamlit 投顾界面"]
    end

    FE -->|HTTP/SSE| APP
    APP -->|SQLAlchemy Async| MySQL_CT
    APP -->|redis.asyncio| Redis_CT
    APP -->|neo4j.AsyncDriver| Neo4j_CT
    APP -->|pymilvus| Milvus_CT
    APP -->|minio-py| MinIO_CT
    APP -->|openai SDK| LLM_CT
```

---

## 九、快速导航

| 我想... | 去这里 |
|---------|--------|
| 启动项目 | `python main.py` |
| 测试规则引擎 | `python -m app.engine.dimension_calculator` |
| 测试熔断规则 | `python -m app.engine.circuit_breaker` |
| 查看 API 文档 | 启动后访问 `http://localhost:8000/docs` |
| 修改评分规则 | `app/config/rules_config.py` |
| 修改数据库表结构 | `app/model/entities.py` → 重启自动 DDL |
| 添加新的 API 接口 | `app/api/` 新建路由 → `main.py` 注册 |
| 添加新的 Agent | `app/agent/` 继承 `BaseAgent` |
| 添加新的 Tool | `app/tool/` 新建工具类 |
| 配置数据库连接 | `.env` (MYSQL_*/REDIS_*/NEO4J_*/MILVUS_*) |
| 添加知识文档 | 放入 `data/knowledge/` → 调用 `/api/knowledge/upload` |

---

> **技术栈速查**: FastAPI | SQLAlchemy Async | Redis | Neo4j | Milvus | MinIO | LangChain | DeepSeek V4 | Pydantic Settings
