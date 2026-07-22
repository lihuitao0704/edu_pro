# 用户画像投顾 Agent 建设方案 V3.0（终版）

> **项目**：智能财富管家系统  
> **模块**：用户画像 + 投顾助手 Agent  
> **负责人**：[待填写]  
> **版本**：V3.0  
> **日期**：2024-07-22  
> **状态**：待审核  

---

## 目录

1. [项目定位与核心理念](#一项目定位与核心理念)
2. [业务闭环](#二业务闭环)
3. [系统总体架构](#三系统总体架构)
4. [Agent 架构设计](#四agent-架构设计)
5. [用户画像体系](#五用户画像体系)
6. [风险画像规则引擎](#六风险画像规则引擎)
7. [硬性熔断规则](#七硬性熔断规则)
8. [知识图谱设计](#八知识图谱设计)
9. [Memory 三层记忆架构](#九memory-三层记忆架构)
10. [GraphRAG 增强检索](#十graphrag-增强检索)
11. [推荐引擎](#十一推荐引擎)
12. [数据库设计](#十二数据库设计)
13. [Redis 缓存设计](#十三redis-缓存设计)
14. [API 接口设计](#十四api-接口设计)
15. [可解释性设计](#十五可解释性设计)
16. [代码结构与技术选型](#十六代码结构与技术选型)
17. [实施计划](#十七实施计划)
18. [技术风险与应对](#十八技术风险与应对)
19. [验收标准](#十九验收标准)
20. [交付物清单](#二十交付物清单)

---

## 一、项目定位与核心理念

### 1.1 项目定位

本方案建设基于《投资者风险画像研判规则》（JR-RULE-2024-001）的**智能用户画像与投顾 Agent**，面向理财顾问，提供从客户理解到产品推荐的完整智能辅助。

### 1.2 核心理念

```
AI 大模型   →  负责理解客户、生成解释
规则引擎   →  负责风险决策、合规保证
知识图谱   →  负责关系推理、穿透分析
```

**核心原则**：规则保证合规，AI 提升效率，知识图谱增强推理。

### 1.3 解决的核心问题

| 痛点 | 现状 | 本方案预期 |
|------|------|-----------|
| 客户信息分散 | 开户、交易、风评数据孤岛 | 统一画像视图，四维度聚合展示 |
| 风险判断效率低 | 理财顾问凭经验手动研判 | 规则引擎自动计算，秒级输出 C1-C5 |
| 推荐标准不一致 | 不同顾问推荐结果差异大 | 规则化评分排序，推荐结果可复现 |
| 过程不可解释 | 判断靠经验，无法追溯 | 全链路记录：数据→规则→分数→等级→推荐 |

---

## 二、业务闭环

```
客户数据采集 → 用户画像生成 → 风险研判 → 适当性匹配 → 智能推荐 → 动态校准
      ↑                                                                    │
      └──────────────────── 反馈修正 ──────────────────────────────────────┘
```

整个闭环覆盖投资者从**开户 → 风评 → 产品购买 → 持有 → 赎回**的全生命周期。画像不是一次性快照，而是随客户行为变化持续校准的**动态画像**。

---

## 三、系统总体架构

```
                        理财顾问（Streamlit 前端）
                               │
                    用户画像投顾 Agent
                               │
            ┌──────────────────┼──────────────────┐
            │                  │                  │
      画像 Agent          推荐 Agent         解释 Agent
      (画像研判)        (产品匹配)          (理由生成)
            │                  │                  │
            └──────────────────┼──────────────────┘
                               │
                        风险规则引擎
                    (四维度打分 + 熔断检查)
                               │
            ┌──────────────────┼──────────────────┐
            │                  │                  │
         MySQL              Redis             Neo4j
       业务数据/日志      缓存/会话          知识图谱
```

**三层 Agent 子模块**：

| 子 Agent | 职责 | 依赖工具 |
|----------|------|---------|
| **画像 Agent** | 信息抽取、标签生成、画像研判、风险解释 | Profile Tool、规则引擎 |
| **推荐 Agent** | 产品筛选、适当性校验、排序打分、资产配置 | Recommendation Tool、GraphRAG |
| **解释 Agent** | 推荐理由生成、画像摘要、风险等级解读 | LLM + 上下文注入 |

---

## 四、Agent 架构设计

### 4.1 统一执行骨架

```
用户提问（自然语言）
       │
       ▼
   Intent Recognition    ← 意图识别（画像查询 / 产品推荐 / 持仓分析 / 配置建议）
       │
       ▼
      Planner            ← 制定执行计划，编排 Tool 调用顺序
       │
       ▼
   ┌─────────────────────────────────────────┐
   │           Tool Calling 层               │
   │                                         │
   │  Profile Tool    —— 读取客户画像        │
   │  Graph Tool      —— Neo4j 图谱查询      │
   │  Holding Tool    —— 持仓分析            │
   │  Recommend Tool  —— 产品推荐打分        │
   │  Allocation Tool —— 资产配置建议        │
   └─────────────────────────────────────────┘
       │
       ▼
      Memory           ← 短期（会话上下文）/ 中期（画像缓存）/ 长期（图谱+向量）
       │
       ▼
    GraphRAG           ← 图谱增强检索（向量相似度 + 图谱关系融合排序）
       │
       ▼
  Recommendation       ← 候选产品 → 风险过滤 → 适当性过滤 → 偏好过滤 → 排序 → TopN
       │
       ▼
    LLM Response       ← 生成最终回答（推荐理由 + 风险解释 + 配置建议）
```

### 4.2 Tool Calling 设计

| Tool 名称 | 功能 | 输入 | 输出 |
|-----------|------|------|------|
| **Profile Tool** | 读取客户画像 | customer_id | 四维度画像 + C1-C5等级 |
| **Graph Tool** | Neo4j 图谱查询 | Cypher 语句 / 实体 | 图谱节点 & 关系路径 |
| **Holding Tool** | 持仓穿透分析 | customer_id | 当前持仓 + 行业分布 + 集中度 |
| **Recommendation Tool** | 产品推荐打分 | customer_id + 候选产品池 | TopN 产品 + 评分明细 |
| **Allocation Tool** | 资产配置建议 | customer_id + risk_level | 配置比例方案 |

---

## 五、用户画像体系

### 5.1 画像四维度总览

| 维度 | 权重 | 子指标 | 数据来源 |
|------|------|--------|----------|
| **基础属性画像** | 25% | 年龄、学历、职业、家庭年收入、可投资资产 | 开户信息 / KYC |
| **投资经验画像** | 25% | 投资年限、持有产品复杂度、交易频率、历史收益 | 交易流水 / 持仓 |
| **风险偏好画像** | 30% | 风评得分、情绪化交易倾向、亏损承受能力 | 风评问卷 / 行为分析 |
| **行为风险画像** | 20% | 频繁赎回、大额集中交易、异常时段操作等 8 种异常 | 实时交易流水 |

### 5.2 画像输出示例

```json
{
  "customer_id": 1001,
  "risk_level": "C2",
  "risk_score": 38,
  "tags": ["稳健型", "中等资产", "固收偏好", "2年投资经验"],
  "dimensions": {
    "basic": { "score": 17.5, "subs": { "age": 10, "education": 8, "occupation": 7, "income": 5, "assets": 5 } },
    "experience": { "score": 16.25, "subs": { "years": 6, "complexity": 5, "frequency": 7, "returns": 8 } },
    "risk_pref": { "score": 15.0, "subs": { "assessment": 15, "emotional_deduction": -3, "loss_tolerance": 3 } },
    "behavior": { "score": 15, "subs": { "abnormal_count": 2, "risk_level": "中" } }
  },
  "total_score": 63.75,
  "confidence_score": 0.85,
  "suitable_products": ["R1", "R2", "R3"]
}
```

### 5.3 画像更新机制

| 触发类型 | 触发条件 | 更新范围 |
|----------|---------|---------|
| 定期触发 | 风评到期前 30 天 | 全部四个维度 |
| 事件触发 | 大额资金变动（>50 万） | 基础属性维度 |
| 行为触发 | 交易模式显著变化 | 投资经验 + 行为异常维度 |
| 市场触发 | 指数波动 >20% | 风险偏好维度 |
| 人工触发 | 客户主动申请 | 全部重新评估 |

### 5.4 画像标签体系

| 标签属性 | 说明 |
|----------|------|
| 标签名 | 如 "风险偏好" |
| 标签值 | 如 "稳健型" |
| 来源 | 风评问卷 / AI 对话提取 / 用户自述 / 默认值 |
| 置信度 | 0.00 - 1.00 |
| 创建时间 | 标签首次生成时间 |
| 更新时间 | 最近一次更新 |
| 有效期限 | 标签有效期 |

**置信度来源初始值**：
- 风评问卷 → 0.9
- AI 对话提取 → 0.6
- 用户自述 → 0.4
- 系统默认 → 0.2

**冲突处理策略**：新标签 vs 旧标签，来源置信度高的覆盖低的，相同来源按时间新覆盖旧，保留冲突记录入审计日志。

---

## 六、风险画像规则引擎

### 6.1 四维度详细评分规则

#### 维度一：基础属性特征（满分 25 分）

**计算公式**：`(年龄分 + 学历分 + 职业分 + 收入分 + 资产分) ÷ 5 ÷ 10 × 25`

| 指标 | 评分表 |
|------|--------|
| **年龄** | 18-25→8, 26-35→10, 36-45→9, 46-55→7, 56-65→5, >65→3 |
| **学历** | 高中及以下→4, 大专→6, 本科→8, 硕士及以上→10 |
| **职业** | 公务员→10, 国企→9, 专技人员→8, 中小企业→6, 自由职业→5, 无业→2, 退休→4 |
| **年收入** | <10万→3, 10-30万→5, 30-50万→7, 50-100万→8, 100-300万→9, >300万→10 |
| **可投资资产** | <5万→2, 5-20万→4, 20-50万→6, 50-100万→7, 100-500万→8, 500-1000万→9, >1000万→10 |

#### 维度二：投资经验特征（满分 25 分）

**计算公式**：`(投资年限分 + 产品复杂度分 + 交易频率分 + 历史收益分) ÷ 4 ÷ 10 × 25`

| 指标 | 评分表 |
|------|--------|
| **投资年限** | 无经验→2, <1年→4, 1-3年→6, 3-5年→8, 5-10年→9, >10年→10 |
| **产品复杂度** | 仅存款→2, 货币基金→4, 纯债基金→5, 混合/指数基金→7, 股票基金→8, 期货/期权→10 |
| **交易频率** | 极低频(<10次/年)→5, 低频(月1-3次)→7, 中频(月4-10次)→8, 高频(周3次+)→6（扣分项） |
| **历史收益** | 无记录→3, <-15%→3, -15%~-5%→4, -5%~5%→6, 5%~15%→8, >15%→9 |

#### 维度三：风险偏好特征（满分 30 分，下限 0 分）

**计算公式**：`风评映射分 + 情绪化交易扣分 + 亏损承受调整`

**风评得分映射**：
| 风评等级 | 映射分 |
|----------|--------|
| C1 保守型 | 5 |
| C2 稳健型 | 10 |
| C3 平衡型 | 15 |
| C4 进取型 | 20 |
| C5 激进型 | 25 |

**情绪化交易扣分**（4 种行为）：
| 行为 | 识别方法 | 扣分 |
|------|---------|------|
| 追涨杀跌 | 净值新高 3 日内买入 / 新低 3 日内卖出 | -3 |
| 恐慌赎回 | 大跌日（>5%）赎回超持仓 50% | -5 |
| FOMO 加仓 | 连续 3 日上涨后大额加仓超月均 3 倍 | -2 |
| 频繁改策略 | 90 天内调整组合 >3 次 | -3 |

**亏损承受能力调整**：
| 可承受亏损 | 调整 |
|-----------|------|
| 不能承受 | -5 |
| 5%以内 | -2 |
| 10%-20% | 0（基准） |
| 20%-40% | +3 |
| 40%以上 | +5 |

#### 维度四：行为异常特征（满分 20 分）

**8 种异常行为检测**：
| 异常行为 | 识别规则 | 风险等级 |
|----------|---------|---------|
| 频繁赎回 | 30 天内 ≥5 次 | 中 |
| 大额集中交易 | 单日 > 账户总资产 50% | 中 |
| 非正常时段交易 | 凌晨 0-6 点频繁操作 | 低 |
| 突然大额入金 | 单笔 > 历史平均 5 倍 | 中 |
| 分散转出 | 单日出金 ≥5 个不同账户 | 高 |
| 产品风险越级 | 要求购买超等级 2 级以上 | 高 |
| 信息频繁变更 | 30 天内 ≥3 次 | 中 |
| 代理操作 | 非本人设备/IP 频繁操作 | 高 |

**计分规则**：
| 异常情况 | 得分 |
|----------|------|
| 无异常 | 20 |
| 1-2 项低风险 | 15 |
| 1-2 项中风险 | 10 |
| ≥3 项中风险 | 5 |
| 任何高风险 | 0 |

### 6.2 综合评分与等级映射

```
综合得分 = 维度一×25% + 维度二×25% + 维度三×30% + 维度四×20%（满分 100）
```

| 得分区间 | 等级 | 类型 | 可购产品等级 |
|----------|------|------|-------------|
| 0-25 | C1 | 保守型 | R1-R2 |
| 26-40 | C2 | 稳健型 | R1-R3 |
| 41-60 | C3 | 平衡型 | R1-R4（R4 需风险揭示书） |
| 61-80 | C4 | 进取型 | R1-R5（R5 需风险揭示书） |
| 81-100 | C5 | 激进型 | R1-R5 |

### 6.3 执行流程

```
输入客户ID
     │
     ▼
Step 1: 数据采集 ─── MySQL/Redis 加载客户全量数据
     │
     ▼
Step 2: 硬性熔断检查 ─── 逐条匹配 FM-01 ~ FM-05
     │   触发熔断 → 返回限制结果，终止后续流程
     ▼
Step 3: 四维度打分 ─── 维度一 + 维度二 + 维度三 + 维度四
     │
     ▼
Step 4: 综合评分 ─── 加权求和 → 映射 C1-C5
     │
     ▼
Step 5: 特殊场景处理 ─── 信息不完整 / 自评冲突 / 特殊人群
     │
     ▼
Step 6: 结果输出 ─── 更新画像表 + Redis缓存 + 记录评分明细 + 返回研判报告
```

### 6.4 特殊场景处理

| 场景 | 处理规则 |
|------|---------|
| **信息不完整** | 收入缺失→按当地最低工资 + 下调一档；投资经验缺失→默认 3 分；>3 项缺失→暂停新开户 |
| **自评 vs AI 冲突** | 差 1 档→取 AI + 可申请复核；差 2 档→取 AI + 需面签；差 3 档+→取 AI + 合规调查 |
| **多账户合并** | 取更保守评级；家庭成员共享异常标记但独立评级 |
| **在校学生** | 收入按 0，仅允许 R1-R2 |
| **失信被执行人** | 限制大额申购，加强资金核实 |
| **市场极端波动** | 指数单日跌 >7%，赎回需二次确认，暂停新开户 72 小时 |

---

## 七、硬性熔断规则

以下规则为强制执行硬性门槛，触发后不受综合评分影响：

| 规则编号 | 条件 | 处理 |
|----------|------|------|
| **FM-01 年龄** | <18 岁 | 禁止开户 |
| | 18-22 岁 | R4+ 需监护人知情同意书 |
| | >70 岁 | R3+ 需网点面签确认 |
| | >80 岁 | 仅 R1-R2，R3 需特殊审批 |
| **FM-02 收入资产** | 无收入 + 资产 <1 万 | 仅 R1-R2 |
| | 无收入 + 资产 1-5 万 | R1-R3，R3 ≤ 总资产 30% |
| **FM-03 风评时效** | >12 个月未更新 | 冻结购买权限，仅允许赎回 |
| | >6 个月未更新 | 推送提醒，暂不限制 |
| **FM-04 身份异常** | 身份证过期 >90 天 | 冻结全部交易权限 |
| | 联网核查不通过 | 暂停非柜面交易 |
| | 涉及制裁名单 | 立即冻结 + 上报合规 |
| **FM-05 交易熔断** | 单日亏损 >10% | 推送风险提示，建议暂停 |
| | 连续 3 日大额赎回 >40% | 触发人工回访 |
| | 账户疑似盗用 | 立即冻结 + 通知客户 |

---

## 八、知识图谱设计

### 8.1 Neo4j 图谱模型

**节点**：

| 节点类型 | 属性 | 说明 |
|----------|------|------|
| Customer | customer_id, name, risk_level | 客户节点 |
| Product | product_code, type, risk_level, expected_return | 产品节点 |
| RiskLevel | level（C1-C5/R1-R5） | 风险等级节点 |
| Industry | name | 行业节点 |
| FundManager | name, experience | 基金经理节点 |
| Asset | type, amount | 资产节点 |

**关系**：

| 关系 | 方向 | 说明 |
|------|------|------|
| HAS_RISK_LEVEL | Customer → RiskLevel | 客户风险等级 |
| INVESTS_IN | Customer → Product | 持仓/购买关系 |
| HAS_PRODUCT | RiskLevel → Product | 风险等级适配 |
| BELONGS_TO | Product → Industry | 产品所属行业 |
| MANAGED_BY | Product → FundManager | 基金经理管理 |
| SUITABLE_FOR | Product → RiskLevel | 适当性匹配 |

### 8.2 图谱查询 Tool

| Tool | Cypher 模式 | 用途 |
|------|------------|------|
| get_customer_products | `MATCH (c:Customer)-[:INVESTS_IN]->(p:Product) WHERE c.id=$id RETURN p` | 客户持仓 |
| get_product_industry | `MATCH (p:Product)-[:BELONGS_TO]->(i:Industry) WHERE p.code=$code RETURN i` | 产品行业 |
| get_suitable_products | `MATCH (r:RiskLevel {level:$level})-[:HAS_PRODUCT]->(p:Product) RETURN p` | 适当性匹配 |
| get_industry_distribution | `MATCH (c:Customer)-[:INVESTS_IN]->(p)-[:BELONGS_TO]->(i) WHERE c.id=$id RETURN i.name, count(p)` | 行业集中度 |
| get_common_holdings | `MATCH (c1:Customer)-[:INVESTS_IN]->(p)<-[:INVESTS_IN]-(c2:Customer) WHERE c1.id=$id1 AND c2.id=$id2 RETURN p` | 共同持仓 |

---

## 九、Memory 三层记忆架构

### 9.1 短期记忆（Redis）

| 配置项 | 值 |
|--------|-----|
| 存储内容 | 当前会话消息列表 |
| Key 格式 | `session:{session_id}:messages` |
| 数据类型 | Redis List |
| TTL | 30 分钟（每次对话续期），最长 24h |
| Token 上限 | 4096 token，超出截断旧消息 |
| 归档 | 会话结束后写入 `conversation_archive` 表 |

### 9.2 中期记忆（Redis 缓存 + MySQL 回源）

| 配置项 | 值 |
|--------|-----|
| 存储内容 | 客户画像、工单状态 |
| 画像缓存 Key | `profile:{customer_id}` |
| 访问策略 | Cache-Aside（先查 Redis → 未命中查 MySQL → 回填 Redis） |
| TTL | 7 天 |

**缓存失效触发**：风评更新、持仓变化、大额交易发生 → 立即清除对应 `profile:{customer_id}` 缓存。

### 9.3 长期记忆（MySQL + Neo4j + Milvus）

| 存储 | 内容 |
|------|------|
| MySQL | 交易历史、评分记录、画像变更日志 |
| Neo4j | 客户-产品-行业关系图谱 |
| Milvus | 知识库向量（FAQ、产品说明、政策法规） |

---

## 十、GraphRAG 增强检索

### 10.1 执行流程

```
用户提问（自然语言）
     │
     ▼
实体识别（LLM NER / 正则匹配：产品名、风险等级、行业、客户名）
     │
     ├──────────────────────────────┐
     ▼                              ▼
向量检索（Milvus TopK）      图谱检索（Neo4j 多跳查询）
     │                              │
     ▼                              ▼
文档片段 + Score_A            关联实体 + 关系路径
     │                              │
     └──────────┬───────────────────┘
                ▼
         融合排序（去重 + 综合分）
         Score = α × Score_A + β × Score_B
         （α=0.6 向量权重，β=0.4 图谱权重，可配置）
                │
                ▼
        注入 LLM 上下文 → 增强生成
```

### 10.2 支持查询类型

| 类型 | 示例 | 图谱能力 |
|------|------|---------|
| 风险关系 | "这个产品适合什么风险等级的客户？" | 产品 → 风险等级关系 |
| 产品关系 | "和 XX 产品类似的其他产品有哪些？" | 产品 → 同行业 / 同风险 |
| 行业关系 | "我的持仓集中在哪些行业？" | 客户 → 产品 → 行业多跳 |
| 持仓关系 | "哪些客户持有了 XX 产品？" | 产品 → 客户反向查询 |

---

## 十一、推荐引擎

### 11.1 推荐流程

```
候选产品池（全部在售产品）
     │
     ▼
风险过滤 ─── 产品风险等级 ≤ 客户可购上限
     │
     ▼
适当性过滤 ─── 符合客户 C1-C5 适应性矩阵
     │
     ▼
偏好过滤 ─── 匹配客户产品偏好标签
     │
     ▼
持仓互补 ─── 图谱分析避免行业过度集中
     │
     ▼
综合排序 ─── 多因子加权打分
     │
     ▼
TopN 输出 ─── 默认 Top 3，含推荐理由
```

### 11.2 排序评分公式

```
Score = 40% × 风险匹配度   （风险等级越低→越匹配保守型客户）
      + 25% × 偏好匹配度   （产品类型 ∈ 客户偏好的类型）
      + 20% × 持仓互补度   （产品行业 ∉ 客户已有重仓行业）
      + 15% × 收益期限度   （收益率/期限与客户目标的契合度）
```

### 11.3 资产配置建议

| 客户类型 | 货币类 | 债券类 | 混合类 | 股票类 | 现金 |
|----------|--------|--------|--------|--------|------|
| C1 保守型 | 40% | 40% | — | — | 20% |
| C2 稳健型 | 20% | 50% | 20% | — | 10% |
| C3 平衡型 | 10% | 35% | 30% | 20% | 5% |
| C4 进取型 | 5% | 20% | 30% | 40% | 5% |
| C5 激进型 | — | 10% | 25% | 55% | 10% |

### 11.4 关键原则

> LLM 仅负责生成推荐理由和自然语言解释，不直接决定推荐结果。推荐排序由规则引擎的评分公式计算，确保可控、可复现、可审计。

---

## 十二、数据库设计

### 12.1 核心表结构

#### customer_profile（客户画像主表）

| 字段 | 类型 | 说明 |
|------|------|------|
| customer_id | BIGINT | 客户 ID（关联 sys_user） |
| risk_level | VARCHAR(16) | 风险等级 C1-C5 |
| risk_score | INT | 综合评分 0-100 |
| confidence_score | DECIMAL(5,2) | 画像综合置信度 |
| basic_score | DECIMAL(5,2) | 维度一得分 |
| experience_score | DECIMAL(5,2) | 维度二得分 |
| risk_pref_score | DECIMAL(5,2) | 维度三得分 |
| behavior_score | DECIMAL(5,2) | 维度四得分 |
| profile_json | JSON | 完整画像 JSON |
| updated_at | DATETIME | 更新时间 |

#### customer_tag（画像标签表）

| 字段 | 类型 | 说明 |
|------|------|------|
| tag_id | BIGINT | 主键 |
| customer_id | BIGINT | 客户 ID |
| tag_name | VARCHAR(64) | 标签名（如 risk_preference） |
| tag_value | VARCHAR(128) | 标签值（如稳健型） |
| source | VARCHAR(32) | 来源：questionnaire/ai_extract/self_report/default |
| confidence | DECIMAL(5,2) | 标签置信度 |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |
| valid_until | DATE | 有效期 |

#### risk_score_record（评分过程记录表）

| 字段 | 类型 | 说明 |
|------|------|------|
| record_id | BIGINT | 主键 |
| customer_id | BIGINT | 客户 ID |
| rating_date | DATETIME | 评分日期 |
| basic_score | DECIMAL(5,2) | 基础属性评分 |
| experience_score | DECIMAL(5,2) | 投资经验评分 |
| risk_pref_score | DECIMAL(5,2) | 风险偏好评分 |
| behavior_score | DECIMAL(5,2) | 行为异常评分 |
| total_score | DECIMAL(5,2) | 综合评分 |
| risk_level | VARCHAR(16) | 评定等级 |
| detail_json | JSON | 各子项评分明细 |
| circuit_breakers | JSON | 触发的熔断规则 |
| trigger_type | VARCHAR(32) | 触发方式 |

#### risk_rule（规则配置表）

| 字段 | 类型 | 说明 |
|------|------|------|
| rule_id | VARCHAR(16) | 规则编号（如 FM-01） |
| rule_name | VARCHAR(128) | 规则名称 |
| rule_type | VARCHAR(32) | 类型：scoring / circuit_breaker |
| dimension | VARCHAR(32) | 所属维度 |
| config_json | JSON | 规则配置（分值表、阈值等） |
| weight | DECIMAL(5,2) | 权重 |
| is_active | TINYINT | 是否启用 |
| version | VARCHAR(16) | 版本号 |

#### product_recommendation（推荐结果表）

| 字段 | 类型 | 说明 |
|------|------|------|
| recommend_id | BIGINT | 主键 |
| customer_id | BIGINT | 客户 ID |
| session_id | VARCHAR(64) | 会话 ID |
| product_code | VARCHAR(32) | 推荐产品代码 |
| match_score | DECIMAL(5,2) | 匹配评分 |
| score_detail | JSON | 评分明细 |
| reasoning | TEXT | 推荐理由 |
| created_at | DATETIME | 推荐时间 |

---

## 十三、Redis 缓存设计

| Key 模式 | 内容 | TTL | 说明 |
|----------|------|-----|------|
| `profile:{customer_id}` | 客户画像 JSON | 7 天 | Cache-Aside，更新即失效 |
| `session:{session_id}:messages` | 会话消息列表 | 30 min + 每次续期 | 短期记忆 |
| `risk:rule:version` | 当前规则版本号 | 永久 | 规则热加载版本标识 |

---

## 十四、API 接口设计

### 14.1 接口总览

| 接口 | 方法 | 说明 | 阶段 |
|------|------|------|------|
| `/api/profile/{customer_id}` | GET | 查询客户画像（Cache-Aside） | Phase 2 |
| `/api/profile/{customer_id}` | PUT | 增量更新画像标签 | Phase 2 |
| `/api/profile/{customer_id}/assess` | POST | 执行画像研判打分 | Phase 2 |
| `/api/risk/questionnaire` | GET | 获取风评问卷（16 题） | Phase 2 |
| `/api/risk/assessment` | POST | 提交风评答卷 | Phase 2 |
| `/api/risk/suitability-check` | POST | 适当性匹配校验 | Phase 2 |
| `/api/chat/advisor` | POST | 投顾对话（推荐/配置/持仓分析） | Phase 3 |
| `/api/recommend` | POST | 产品推荐（纯 API） | Phase 3 |
| `/api/allocation` | POST | 资产配置建议 | Phase 3 |

### 14.2 核心接口详情

#### POST `/api/profile/{customer_id}/assess`

**请求**：`{ "customer_id": 1001, "trigger_type": "manual" }`

**响应**：
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "customer_id": 1001,
    "risk_level": "C2",
    "risk_score": 38,
    "total_score": 63.75,
    "dimensions": {
      "basic":     { "score": 17.5, "detail": { "age": 10, "education": 8, "occupation": 7, "income": 5, "assets": 5 } },
      "experience": { "score": 16.25, "detail": { "years": 6, "complexity": 5, "frequency": 7, "returns": 8 } },
      "risk_pref":  { "score": 15.0, "detail": { "assessment": 15, "emotional_deduction": -3, "loss_tolerance": 3 } },
      "behavior":   { "score": 15, "detail": { "abnormal_count": 2, "risk_level": "中" } }
    },
    "confidence_score": 0.85,
    "circuit_breakers": [],
    "warnings": ["风评将于30天后过期"],
    "recommended_products": ["R1", "R2", "R3"]
  },
  "trace_id": "uuid-xxx"
}
```

#### POST `/api/chat/advisor`

**请求**：`{ "session_id": "sess-xxx", "message": "给客户张三推荐3款稳健型产品", "user_id": 2001, "customer_id": 1001 }`

**响应**：
```json
{
  "code": 200,
  "data": {
    "reply": "根据客户张三的C2稳健型风险画像，为您推荐以下3款产品...",
    "recommendations": [
      { "product_code": "F000012", "product_name": "XX稳健增利债券A", "risk_level": "R2",
        "expected_return": 4.5, "match_score": 0.92, "reason": "低波动纯债基金，与客户稳健型偏好高度匹配" }
    ],
    "customer_profile": { "risk_level": "C2", "risk_score": 38 },
    "reasoning": "基于客户2年投资经验、中等资产规模及固收偏好，优先推荐R2级低波动纯债产品",
    "session_id": "sess-xxx"
  },
  "trace_id": "uuid-xxx"
}
```

---

## 十五、可解释性设计

### 15.1 全链路记录

系统对每一次研判和推荐记录完整决策链：

```
输入数据 → 使用规则 → 评分过程 → 风险等级 → 推荐依据
```

### 15.2 研判可解释性示例

```
客户：张三（ID: 1001）

【风险等级】C3 平衡型（综合评分：58 分）

评分明细：
  基础属性：18 分（年龄 35→10, 本科→8, 国企→9, 收入 30 万→7, 资产 60 万→7 → 均值 8.2 ÷10 ×25 = 20.5 → 修正 18）
  投资经验：20 分（投资 5 年→9, 混合基金→7, 低频→7, 年化 8%→8 → 均值 7.75 ÷10 ×25 = 19.4 → 修正 20）
  风险偏好：15 分（C3 映射→15, 无情绪化→0, 承受 15%→0）
  行为异常：20 分（无异常行为）

可购产品等级：R1-R4（R4 需风险揭示书）

推荐依据：基于客户平衡型风险偏好、5 年投资经验及国企稳定收入，优先推荐 R2-R3 级别混合类产品，
          同时考虑持仓分散化，避免与已有债基持仓过度重叠。
```

### 15.3 记录存储

每一条研判记录写入 `risk_score_record` 表，每次推荐写入 `product_recommendation` 表，确保**任何结论都可逆向追溯到原始数据和规则**。

---

## 十六、代码结构与技术选型

### 16.1 技术选型

| 组件 | 选型 | 用途 |
|------|------|------|
| Web 框架 | FastAPI | API 接口 |
| ORM | SQLAlchemy | MySQL 数据操作 |
| 缓存 | Redis | 画像缓存、会话存储、事件总线 |
| LLM | OpenAI API | 意图识别、标签提取、推荐理由生成 |
| 向量数据库 | Milvus | RAG 知识库检索 |
| 图数据库 | Neo4j | 知识图谱存储与查询 |
| AI 框架 | LangChain | Agent 编排、Tool 管理 |
| 前端 | Streamlit | 投顾演示界面 |

### 16.2 代码目录结构

```
app/
├── api/
│   ├── profile.py              # 画像 CRUD + 研判接口
│   ├── risk.py                 # 风评问卷 + 适当性匹配
│   └── advisor.py              # 投顾对话接口（Phase 3）
│
├── agent/                      # Agent 编排层
│   ├── base_agent.py           # Agent 基类（统一执行骨架）
│   ├── profile_agent.py        # 画像 Agent（信息抽取+标签生成+研判）
│   ├── recommendation_agent.py # 推荐 Agent（产品筛选+排序）
│   └── explanation_agent.py    # 解释 Agent（理由生成+风险解读）
│
├── service/
│   ├── profile_service.py      # 画像业务编排
│   ├── advisor_service.py      # 投顾推荐 Pipeline
│   └── risk_service.py         # 风评业务逻辑
│
├── engine/                     # 规则引擎层
│   ├── dimension_calculator.py # 四维度计算器
│   │   ├── BasicDimension      # 维度一
│   │   ├── ExperienceDimension # 维度二
│   │   ├── RiskPrefDimension   # 维度三
│   │   └── BehaviorDimension   # 维度四
│   ├── circuit_breaker.py      # 5 条熔断规则
│   ├── special_case.py         # 特殊场景处理
│   ├── confidence.py           # 置信度计算
│   └── score_mapper.py         # 分数→等级映射
│
├── tool/                       # Tool 层（Agent 可调用）
│   ├── profile_tool.py         # 画像查询 Tool
│   ├── graph_tool.py           # 图谱查询 Tool
│   ├── holding_tool.py         # 持仓分析 Tool
│   ├── recommendation_tool.py  # 推荐打分 Tool
│   └── allocation_tool.py      # 资产配置 Tool
│
├── graph/                      # 图谱层
│   ├── neo4j_client.py         # Neo4j 连接
│   ├── cypher_templates.py     # Cypher 查询模板
│   └── graphrag_pipeline.py    # GraphRAG 融合检索
│
├── memory/                     # 记忆层
│   ├── session_memory.py       # 短期记忆（Redis）
│   ├── profile_cache.py        # 中期记忆（Cache-Aside）
│   └── long_term.py            # 长期记忆管理
│
├── model/
│   ├── schemas.py              # Pydantic 模型
│   └── entities.py             # SQLAlchemy ORM
│
├── config/
│   ├── settings.py             # 环境配置
│   ├── rules_config.py         # 研判规则配置
│   └── database.py             # 数据库连接
│
└── utils/
    ├── response.py             # 统一响应格式
    ├── exceptions.py           # 自定义异常
    └── logger.py               # 日志模块
```

---

## 十七、实施计划

### 17.1 整体阶段规划

| 阶段 | 内容 | 周期 | 交付物 |
|------|------|------|--------|
| **第一阶段** | 画像基础能力建设 | 第 1-2 周 | 画像 CRUD + 四维度引擎 + Redis 缓存 |
| **第二阶段** | 风险规则引擎建设 | 第 2 周 | 5 条熔断 + 特殊场景处理 + 置信度 |
| **第三阶段** | AI 画像 Agent 建设 | 第 2-3 周 | 画像 Agent + 风评模块 + LLM 标签提取 |
| **第四阶段** | 投顾 Agent 建设 | 第 3 周 | 推荐引擎 + GraphRAG + 资产配置 |

### 17.2 详细任务计划

#### 第一阶段：画像基础能力建设（第 1 周）

| 天数 | 任务 |
|------|------|
| Day 1 | 搭建模块骨架，创建目录结构、ORM 模型（customer_profile / customer_tag）、MySQL 建表 |
| Day 2 | 实现维度一（基础属性）和维度二（投资经验）计算器，编写单元测试 |
| Day 3 | 实现维度三（风险偏好）和维度四（行为异常）计算器，编写单元测试 |
| Day 4 | 实现画像 CRUD 接口（GET / PUT）+ Redis Cache-Aside 缓存 |
| Day 5 | 实现完整研判接口 `POST /api/profile/{id}/assess`，联调 5 位测试客户 |

#### 第二阶段：风险规则引擎建设（第 2 周前半）

| 天数 | 任务 |
|------|------|
| Day 6 | 实现 5 条硬性熔断规则（FM-01 ~ FM-05）+ 特殊场景处理器 |
| Day 7 | 实现风评模块：问卷接口 + 答题评分 + 适当性匹配 + 置信度计算器 |
| Day 8 | 集成联调：研判引擎 × 熔断 × 特殊场景全流程测试 |

#### 第三阶段：AI 画像 Agent 建设（第 2 周后半）

| 天数 | 任务 |
|------|------|
| Day 9 | 实现画像 Agent（Profile Tool + LLM 标签提取 + 画像总结生成） |
| Day 10 | 实现 LLM 信息抽取 Prompt 调优（对话→结构化标签），标签冲突处理 |

#### 第四阶段：投顾 Agent 建设（第 3 周）

| 天数 | 任务 |
|------|------|
| Day 11 | 实现推荐引擎（候选→过滤→排序→TopN）+ Neo4j 图谱 Schema 搭建 |
| Day 12 | 实现 GraphRAG Pipeline（向量 + 图谱融合检索） |
| Day 13 | 实现投顾对话接口 `/api/chat/advisor` + 资产配置 Tool |
| Day 14 | 端到端全链路测试 + 文档完善 + 演示准备 |

### 17.3 双人协作分工

| 成员 A（图谱 +Agent 编排） | 成员 B（画像 + 规则引擎） |
|---------------------------|--------------------------|
| Neo4j Schema 搭建 | 客户画像四维度引擎 |
| GraphRAG Pipeline | 硬性熔断规则引擎 |
| Cypher 查询 Tool 封装 | 特殊场景处理器 |
| Agent 统一执行骨架 | Redis 缓存 + 置信度 |
| 推荐引擎 | 风评模块（问卷+适当性） |
| 投顾对话接口 | FastAPI 接口层 |

---

## 十八、技术风险与应对

| 风险 | 影响 | 概率 | 应对措施 |
|------|------|------|---------|
| 画像缓存不一致（Redis vs MySQL） | 推荐基于过期画像 | 低 | Cache-Aside + 关键事件触发缓存立即失效 |
| 图谱数据质量不足 | 推荐效果下降 | 中 | 图谱查询降级：超时或数据缺失时退回纯 RAG 推荐 |
| 研判规则变更频繁 | 规则引擎需频繁调整 | 中 | 规则配置化（risk_rule 表 + JSON 配置），支持热更新 |
| LLM 标签提取不准确 | 画像标签质量差 | 中 | 低置信度标签不入核心画像，多源交叉验证 |
| 推荐排序不符合合规要求 | 法律风险 | 低 | 规则引擎评分排序，LLM 仅负责解释，不参与排序决策 |
| Neo4j 多跳查询耗时 | 投顾推荐超时 | 低 | 3 秒超时降级，跳过图谱增强，仅用 RAG 结果 |

---

## 十九、验收标准

### Phase 2 验收（画像 + 规则引擎）

- [ ] 画像研判引擎正确输出 C1-C5 等级（5 位测试客户，结果与手工计算一致）
- [ ] 四维度每项子评分可独立验证追溯
- [ ] 5 条熔断规则全部生效（测试年龄边界、风评过期、身份异常等）
- [ ] 画像标签携带置信度，冲突按来源优先级正确处理
- [ ] 风评问卷 16 题可正常作答并正确计算等级
- [ ] 适当性匹配生效（C1 客户无法购买 R3+ 产品）
- [ ] Cache-Aside 缓存正常（命中 Redis → 回源 MySQL → 回填）
- [ ] 信息不完整场景给出保守处理

### Phase 3 验收（投顾 Agent）

- [ ] 投顾推荐产品严格符合客户风险等级
- [ ] 推荐理由引用客户画像信息
- [ ] GraphRAG 可完成至少 3 种多跳查询（持仓穿透、行业分析、产品关联）
- [ ] 推荐结果通过适当性过滤
- [ ] Redis 缓存命中/回源正常
- [ ] 5 个 Tool Calling 均可正常调用
- [ ] 画像→研判→推荐全链路端到端通过（至少 5 个场景）
- [ ] LLM 不直接决定推荐结果，推荐排序由规则引擎计算

---

## 二十、交付物清单

| 序号 | 交付物 | 说明 |
|------|--------|------|
| 1 | `app/api/profile.py` / `risk.py` / `advisor.py` | API 接口层 |
| 2 | `app/agent/profile_agent.py` / `recommendation_agent.py` / `explanation_agent.py` | Agent 编排层 |
| 3 | `app/engine/dimension_calculator.py` | 四维度打分计算器 |
| 4 | `app/engine/circuit_breaker.py` | 5 条熔断规则引擎 |
| 5 | `app/engine/special_case.py` | 特殊场景处理器 |
| 6 | `app/engine/confidence.py` | 置信度计算器 |
| 7 | `app/tool/` 下 5 个 Tool | Agent 可调用工具 |
| 8 | `app/graph/graphrag_pipeline.py` | GraphRAG 融合检索 |
| 9 | `app/memory/` 三层记忆 | 短期 / 中期 / 长期记忆 |
| 10 | `app/model/schemas.py` / `entities.py` | 数据模型 |
| 11 | 单元测试 | 四维度计算器、熔断规则、5 位测试客户全流程 |
| 12 | API 接口文档 | Swagger 自动生成 + 补充说明 |
| 13 | Neo4j Cypher 导入脚本 | 图谱初始化与数据同步 |

---

> **编制人**：[待填写]  
> **审核人**：[待填写]  
> **批准人**：[待填写]  
> **日期**：2024 年 07 月 22 日
