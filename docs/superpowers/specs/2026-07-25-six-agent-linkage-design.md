# 六 Agent 联动闭环设计

**日期：**2026-07-25  
**范围：** 智能客服、客户画像、投顾推荐、风控、数据分析、业务操作六类 Agent 的内部协作。  
**不在范围：** 知识库刷新、ExplanationAgent、审计日志自动合规、WebSocket/短信/邮件等外部通知通道。

## 1. 结论与目标

当前项目并非 15 条链路均未实现。在上述范围内，审查报告中的 12 条相关链路里，画像到投顾推荐基本可用；其余 11 条存在断链或只有局部实现。

本设计的目标是建立单一、可测试的领域事件契约，使每一条跨 Agent 联动都遵循：**业务事实产生 → 风控/画像研判 → 可追溯的策略状态 → 下游 Agent 消费**。

金融合规边界：交易、对话情绪、推荐拒绝和盈亏只能形成“行为信号”或“策略约束”；不得自动修改正式投资者风险等级。正式风险等级仅由已有的风险评估/画像研判流程变更。

## 2. 已确认的根因

1. `app/service/event_bus.py` 的 `publish_operation_event()` 发出的 payload 为 `arguments/result` 嵌套结构，但 `_handle_risk_alert()` 读取顶层 `customer_id/alert_level`。业务操作附加发布的 C1 事件无法可靠更新风险标记。
2. C1/C2/C4 和 `event:risk_alert` 同时发布；legacy 消费又执行三个处理器，造成重复消费与不清晰的所有权。
3. `TransactionFlowService` 已被申购、赎回、转账 API 调用，但在写入交易之后运行。它能生成事后预警，不能作为高风险操作的事前决策闸门。
4. 推荐反馈、分析洞察、客户情绪、风险评估到期、可疑上报没有标准事件和消费者。NL2SQL 的查询结果只返回页面。
5. 推荐记录没有状态/反馈字段；客户画像虽然有 `product_preference`、`calibration_json`，推荐服务不消费这些行为信号。

## 3. 目标架构

### 3.1 单一事件信封

所有六 Agent 之间的异步消息采用下列稳定结构；Redis channel 只负责传输，业务处理只由 `event_type` 决定。

```python
{
    "event_id": "uuid",
    "event_type": "risk_alert_created",
    "version": 1,
    "source_agent": "risk",
    "customer_id": 27,
    "correlation_id": "request-or-operation-id",
    "occurred_at": "2026-07-25T12:00:00+08:00",
    "payload": {"...": "event-specific immutable facts"},
}
```

事件处理器必须幂等：以 `event_id + consumer_name` 记录处理结果；同一事件重投不得重复修改画像、重复生成客服任务或重复创建预警。

### 3.2 事件及消费者

| 事件 | 生产者 | 消费者 | 有效结果 |
|---|---|---|---|
| `transaction_completed` | 业务操作 | 风控、客户画像 | 风控规则评估；画像重新研判/缓存失效 |
| `risk_alert_created` | 风控 | 客户画像、投顾、客服 | 风险标记、推荐约束、客服待触达任务 |
| `recommendation_feedback` | 投顾 | 客户画像、投顾 | 更新偏好信号，后续推荐排除已拒绝类别 |
| `analytics_insight` | 数据分析 | 客户画像、投顾、风控 | 只消费经白名单提取的盈亏/频率洞察 |
| `customer_sentiment` | 客服 | 客户画像 | 写入短期情绪标签和证据，不改变正式风险等级 |
| `risk_assessment_expiring` | 风控 | 客服、客户画像 | 生成客服待触达任务、清除相关画像缓存 |
| `suspicious_reported` | 业务操作 | 风控 | 复用风控研判与风险告警链路 |

## 4. 六 Agent 联动设计

### 4.1 业务操作 → 风控 → 画像 / 投顾 / 客服

申购、赎回、转账在执行前构造统一交易上下文，调用 `TransactionFlowService.assess_pre_execution()`。

- low：允许执行，成功后发 `transaction_completed`。
- medium：创建待复核风险记录，业务操作返回“待风控复核”，不写交易流水。
- high：拒绝执行，创建预警；客服仅获得待触达任务，不调用外部推送。

已执行的成功交易仍发 `transaction_completed`，供风控进行后验监控、画像重算和图谱同步。风险事件由 `RiskMonitorService` 统一发出 `risk_alert_created`；投顾不再自己订阅 Redis 修改风险标记。

### 4.2 投顾推荐 → 拒绝反馈 → 客户画像 → 下一次推荐

`ProductRecommendation` 增加 `status`（`pending/accepted/rejected/ignored`）、`feedback_reason`、`feedback_at`。投顾端提交拒绝反馈时，只能修改当前客户的推荐记录，并发出 `recommendation_feedback`。

画像消费者维护 `product_preference.feedback_signals`：产品类型、风险等级、行业、拒绝次数、最近拒绝时间。达到阈值时写入 `avoid_product_types`，并清除画像缓存。投顾服务读取该结构，从候选池中排除已拒绝类型；不降低客户正式风险等级。

### 4.3 数据分析 → 画像 / 投顾 / 风控

数据分析 Agent 在查询完成后调用 `InsightExtractor`，仅允许产生以下洞察：

- `pnl_drawdown`：客户持仓平均收益率或累计亏损达到配置阈值；
- `trading_frequency`：七日交易次数和金额达到配置阈值。

无法确认客户、时间窗口、数值或证据来源的 NL2SQL 结果绝不发布事件。投顾将 `pnl_drawdown` 作为推荐风险偏好惩罚；风控将 `trading_frequency` 转为一次可解释的规则评估；画像记录洞察快照并重新研判。均不得直接改正式风险等级。

### 4.4 客服情绪 → 客户画像

客服 Agent 在回复前调用本地关键词/模式分类器，输出 `neutral/negative/high_distress` 和命中证据。仅 `negative/high_distress` 产生 `customer_sentiment`；画像保存带 TTL 的情绪信号，供投顾生成更审慎的文案和产品波动提示。该功能不调用外部通知，不用未验证的 LLM 输出直接写核心画像字段。

### 4.5 风险评估到期 / 可疑上报 → 客服与风控

风险调度器创建到期提醒时同时发 `risk_assessment_expiring`。客服消费者写入客户待触达任务，客户下次进入客服会话时优先呈现；画像缓存失效。

可疑上报 API 在同一业务事务提交后发 `suspicious_reported`。风控消费者调用统一告警创建路径，产出 `risk_alert_created`，继而使画像、投顾、客服得到一致状态。

## 5. 数据与兼容性

新增迁移必须可重复执行：

- `product_recommendation` 的反馈字段与索引；
- `agent_event_outbox`：事务内持久化事件，后台投递 Redis；
- `agent_event_consumption`：消费者幂等记录；
- `fin_customer_profile` 不新增正式风险等级字段，只在现有 JSON 字段存放 `feedback_signals`、`analytics_signals`、`sentiment_signals`。

不再发布 C1/C2/C4 的多频道消息。保留 `event:risk_alert` 作为一版兼容读通道，但只映射为统一 `risk_alert_created`，并在迁移完成后移除旧订阅逻辑。

## 6. 质量与验收

每条联动都以测试先行，至少覆盖：

1. 事件信封字段完整、同一事件重复投递只消费一次；
2. high 风险转账在写流水前被阻止；
3. 交易产生中高风险预警后，画像风险标记、投顾约束、客服待触达任务一致；
4. 三次同类拒绝反馈会排除相应产品类型，正式风险等级不变；
5. 合格的 P&L / 高频洞察分别影响投顾/风控；非结构化分析结果不产生事件；
6. 负面情绪和风评到期只写行为信号/客服任务；
7. 可疑上报进入同一风险告警闭环；
8. 原有画像推荐、风控规则、业务操作单元测试保持通过。

## 7. 不做的内容

- 不增加 Kafka、外部消息队列、短信、邮件或 WebSocket；
- 不改知识库、ExplanationAgent、图谱算法或审计自动扫描；
- 不因盈亏、拒绝、情绪或频率自动改变客户的正式风险等级；
- 不重构六 Agent 以外的业务模块。
