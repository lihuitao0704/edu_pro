# 风控Agent — 待修改清单（最终版）

> 队长修完后逐文件验证，2026-07-23

---

## 队长动了什么

队长提交 `f038df0` 改了30个文件，涉及风控Agent的只有 `risk_scheduler.py`（+5行写回逻辑），其余全是队友的基础设施文件。

风控Agent本身6个核心文件**全部原样未动**：

| 文件 | 当前问题 | 不改的后果 |
|------|------|------|
| `schemas.py` | TransactionEvent 缺少 `extra: allow` | 6条规则(R003/R006/R009/R016/R017/R019)通过API永远触发不了。Pydantic直接丢弃前端传来的 age/in_24h/avoid_pattern_count 等字段 |
| `risk_monitor_service.py` | grade()只看条数不看优先级、status中英文混存、pending没TTL | R011制裁国交易只给low(蓝)；前端按英文查pending查不到数据；Redis pending集合只增不删内存持续增长 |
| `risk_monitor_rules.py` | R008 非法时间戳 `else 0` 被当成午夜 | 格式错误的时间戳被误判为凌晨交易，产生假预警 |
| `risk.py` | 置信度来源写死 `ai_extract`(0.60) | 所有预警置信度比应有的低20%，看起来不如实际可信 |
| `demo_10_scenarios.py` | 第95行两个分支都打印通过 | 答辩演示脚本永远全绿，6/10场景实际失败也看不出来 |
| `risk_scheduler.py` | 传了 `age_days` 但 `calc_single()` 不收 | 每周日凌晨3点周期校准崩溃。时间衰减配置了但从未执行 |

---

## 待修改明细（10项）

| # | 问题 | 文件 | 改动量 | 不改的后果 |
|:--:|------|------|:--:|------|
| 1 | Schema吞字段 | `schemas.py` TransactionEvent | +1行 `model_config = {"extra": "allow"}` | 6条规则通过API永远不触发。答辩demo 8/10场景假通过 |
| 2 | demo断言自欺 | `demo_10_scenarios.py:95` | 改1行 | 演示脚本永远全绿，实际6/10失败，答辩演示成摆设 |
| 3 | R008时间戳误判 | `risk_monitor_rules.py` R008 | 改1行 `else 0` → `else 23` | 格式错误的时间戳被当成凌晨交易报警，正常交易可能误触发 |
| 4 | grade()不看优先级 | `risk_monitor_service.py` grade() | ~10行 | R011制裁国交易只给low(蓝)不升级red(红)。制裁相关预警不够紧急。合规风险 |
| 5 | status中英文混存 | `risk_monitor_service.py` save/handle | ~5行 | 前端 `?status=pending` 查不到任何东西。字段值不可靠 |
| 6 | resolve拼写错误 | MySQL | 1条SQL | 数据库有一条脏数据，查 status='resolved' 会漏掉 |
| 7 | pending永不过期 | `risk_monitor_service.py` sadd/srem | ~5行 | Redis pending集合只增不删。SCARD返回17但真实pending只有13。运行越久数据越假 |
| 8 | 置信度来源用错 | `risk.py:74` | 改1行 `ai_extract` → `behavior` | 所有预警从0.60起算而非0.80。警报看起来比实际更不可信 |
| 9 | 调度器参数不匹配 | `risk_scheduler.py` × `confidence.py` | 接口对齐 | 周日3点校准崩溃。时间衰减从未执行，半年前的预警和今天的置信度一样 |
| 10 | 置信度优先级硬编码 | `confidence.py`（队友） | 配置化 | 新增来源类型被静默忽略，影响重排准确度 |

---

## 建议修改顺序

1. **先修 #1** — 所有API测试都依赖Schema透传字段
2. **#2 #3 #8** — 各1行，独立无依赖
3. **#4 #5 #7** — 同一文件 `risk_monitor_service.py`，一起改
4. **#6** — 数据库清理
5. **#9 #10** — 需跟队友的 `confidence.py` 对齐接口

---

## 二、协作联调问题（4项，队友负责）

队长提交未涉及 `event_bus.py` 和 `operations/*.py`，融合链路P0-P3**全部未修**：

| # | 问题 | 文件 | 谁负责 | 不改的后果 |
|:--:|------|------|:--:|------|
| C1 | 核心链路断裂 | `event_bus.py` ACTION_EVENT_MAP | 队友 | operator执行交易后直接发event:risk_alert，跳过风控20条规则。风控Agent等于白写 |
| C2 | 频道语义混淆 | `event_bus.py` + `main.py` | 队友 | event:risk_alert被operator和风控同时发。投顾分不清是普通交易还是红色预警 |
| C3 | purchase/redeem/transfer绕过风控 | `operations/*.py` | 队友 | 交易写库后不调evaluate_all()，AML检查完全被绕过 |
| C4 | 订阅suspicious_intent缺失 | `main.py` + `event_bus.py` | 队友 | 客服识别到可疑意图也无法通知风控Agent |
