"""
风控监测 — 20 条反洗钱规则定义
===============================
基于《反洗钱可疑交易识别规则.md》(JR-AML-RULE-2024-001 V2.1)
策略模式实现，每条规则独立封装。
"""

from abc import ABC, abstractmethod
from typing import Optional


class BaseAMLRule(ABC):
    """风控规则抽象基类"""

    rule_id: str = ""
    rule_name: str = ""
    rule_type: str = ""          # 实时/准实时/日批/周批
    risk_level: str = ""         # 低/中/中高/高
    weight: float = 0.5
    trigger_condition: str = ""

    @abstractmethod
    def evaluate(self, tx: dict) -> bool:
        """判断交易是否触发本规则"""
        ...


# ═══════════════════════════ 优先级 1（最高）═══════════════════════════

class HighRiskCountryRule(BaseAMLRule):
    """R011: 涉及高风险国家/地区的资金往来"""
    rule_id = "R011"
    rule_name = "高风险国家/地区交易"
    rule_type = "实时"
    risk_level = "高"
    weight = 1.0
    trigger_condition = "FATF黑灰名单国家 + 金额>=1万"

    HIGH_RISK = {"伊朗", "朝鲜", "叙利亚", "缅甸", "古巴", "委内瑞拉", "也门", "苏丹"}

    def evaluate(self, tx: dict) -> bool:
        country = tx.get("counterparty", {}).get("country", "")
        return country in self.HIGH_RISK and tx.get("amount", 0) >= 10000


class PEPRule(BaseAMLRule):
    """R013: PEP关联账户异常"""
    rule_id = "R013"
    rule_name = "政治公众人物关联"
    rule_type = "日批"
    risk_level = "高"
    weight = 1.0
    trigger_condition = "PEP + (>=20万 or 新增境外对手 or 模式变化>50%)"

    def evaluate(self, tx: dict) -> bool:
        if not tx.get("is_pep"):
            return False
        cp = tx.get("counterparty", {})
        amount = tx.get("amount", 0)
        is_new_foreign = cp.get("is_new", False) and cp.get("country", "CN") != "CN"
        return amount >= 200000 or is_new_foreign


class MultiAccountRule(BaseAMLRule):
    """R018: 多账户关联资金归集"""
    rule_id = "R018"
    rule_name = "多账户关联资金归集"
    rule_type = "周批"
    risk_level = "高"
    weight = 1.0
    trigger_condition = ">=3关联账户 + 7天归集>=30万"

    def evaluate(self, tx: dict) -> bool:
        return tx.get("linked_accounts", 0) >= 3 and tx.get("collection_amount", 0) >= 300000


class GamblingFraudRule(BaseAMLRule):
    """R019: 涉赌涉诈资金特征"""
    rule_id = "R019"
    rule_name = "涉赌涉诈资金流转"
    rule_type = "日批"
    risk_level = "高"
    weight = 1.0
    trigger_condition = "小额入金+大额整数出金+夜间(20-02)"

    def evaluate(self, tx: dict) -> bool:
        return tx.get("small_in_pattern", False) and tx.get("large_round_out", False) and tx.get("night_pattern", False)


# ═══════════════════════════ 优先级 2 ═══════════════════════════

class ScatterInRule(BaseAMLRule):
    """R004: 分散转入集中转出"""
    rule_id = "R004"
    rule_name = "分散转入集中转出"
    rule_type = "日批"
    risk_level = "高"
    weight = 1.0
    trigger_condition = "5天>=5来源 + >=80%转至同一对手 + >=20万"

    def evaluate(self, tx: dict) -> bool:
        return tx.get("incoming_sources", 0) >= 5 and tx.get("outgoing_concentration", 0) >= 0.8 and tx.get("amount", 0) >= 200000


class ScatterOutRule(BaseAMLRule):
    """R005: 集中转入分散转出"""
    rule_id = "R005"
    rule_name = "集中转入分散转出"
    rule_type = "日批"
    risk_level = "高"
    weight = 1.0
    trigger_condition = ">=1笔大额转入(>=10万) + 3日>=5个转出"

    def evaluate(self, tx: dict) -> bool:
        return tx.get("big_incoming_count", 0) >= 1 and tx.get("outgoing_targets", 0) >= 5


# ═══════════════════════════ 优先级 3 ═══════════════════════════

class LargeTransactionRule(BaseAMLRule):
    """R001: 大额现金交易"""
    rule_id = "R001"
    rule_name = "大额现金交易"
    rule_type = "实时"
    risk_level = "中"
    weight = 0.8
    trigger_condition = "单日累计现金>=5万"

    def evaluate(self, tx: dict) -> bool:
        return tx.get("amount", 0) >= 50000 and tx.get("transaction_type") == "cash"


class QuickInOutRule(BaseAMLRule):
    """R003: 资金快进快出"""
    rule_id = "R003"
    rule_name = "资金快进快出"
    rule_type = "准实时"
    risk_level = "中高"
    weight = 0.9
    trigger_condition = "入账24h内>=90%转出 + >=5万"

    def evaluate(self, tx: dict) -> bool:
        return tx.get("in_24h", False) and tx.get("out_ratio", 0) >= 0.9 and tx.get("amount", 0) >= 50000


class ThirdPartyPayRule(BaseAMLRule):
    """R014: 第三方代付"""
    rule_id = "R014"
    rule_name = "非本人账户代付投资款"
    rule_type = "实时"
    risk_level = "中高"
    weight = 0.8
    trigger_condition = "申购账户!=投资账户 + >=5万"

    def evaluate(self, tx: dict) -> bool:
        return tx.get("counterparty", {}).get("account", "") != tx.get("investor_account", "") and tx.get("amount", 0) >= 50000


# ═══════════════════════════ 优先级 4 ═══════════════════════════

class FrequentSmallRule(BaseAMLRule):
    """R002: 频繁小额交易（蚂蚁搬家）"""
    rule_id = "R002"
    rule_name = "频繁小额交易"
    rule_type = "日批"
    risk_level = "中高"
    weight = 0.7
    trigger_condition = "7天>=20笔 + 累计>=10万"

    def evaluate(self, tx: dict) -> bool:
        return tx.get("weekly_count", 0) >= 20 and tx.get("weekly_total", 0) >= 100000


class AmountMismatchRule(BaseAMLRule):
    """R006: 交易金额与客户身份不符"""
    rule_id = "R006"
    rule_name = "金额与身份严重不符"
    rule_type = "日批"
    risk_level = "中高"
    weight = 0.8
    trigger_condition = "单日>=年收入×3 + >=10万"

    def evaluate(self, tx: dict) -> bool:
        income = tx.get("annual_income", 0)
        if income <= 0:
            return False
        return tx.get("daily_amount", 0) >= income * 3 and tx.get("daily_amount", 0) >= 100000


class IntegerAvoidRule(BaseAMLRule):
    """R009: 交易金额刻意规避报告标准"""
    rule_id = "R009"
    rule_name = "整数规避特征"
    rule_type = "日批"
    risk_level = "中高"
    weight = 0.9
    trigger_condition = "30天>=5笔 49,999/199,999等规避金额"

    def evaluate(self, tx: dict) -> bool:
        return tx.get("avoid_pattern_count", 0) >= 5


class RelatedTransRule(BaseAMLRule):
    """R010: 关联方异常资金往来"""
    rule_id = "R010"
    rule_name = "关联交易异常"
    rule_type = "日批"
    risk_level = "中高"
    weight = 0.7
    trigger_condition = "7天双向>=3次 + 净额<20%"

    def evaluate(self, tx: dict) -> bool:
        return tx.get("bidirectional_count", 0) >= 3 and tx.get("net_ratio", 0) < 0.2


class NewAccountRule(BaseAMLRule):
    """R017: 新开户短期内大额交易"""
    rule_id = "R017"
    rule_name = "新开户短期大额交易"
    rule_type = "准实时"
    risk_level = "中高"
    weight = 0.7
    trigger_condition = "开户30天 + (单笔>=20万 or 累计>=50万)"

    def evaluate(self, tx: dict) -> bool:
        if tx.get("account_age_days", 999) > 30:
            return False
        return tx.get("amount", 0) >= 200000 or tx.get("total_since_open", 0) >= 500000


class OffshoreRule(BaseAMLRule):
    """R020: 离岸公司交易"""
    rule_id = "R020"
    rule_name = "与离岸金融中心异常交易"
    rule_type = "日批"
    risk_level = "中高"
    weight = 0.7
    trigger_condition = "对手方=BVI/开曼等 + >=10万 + 非专业机构"

    OFFSHORE = {"BVI", "英属维尔京", "开曼", "百慕大", "巴拿马", "塞舌尔", "萨摩亚", "毛里求斯"}

    def evaluate(self, tx: dict) -> bool:
        region = tx.get("counterparty", {}).get("register_region", "")
        return region in self.OFFSHORE and tx.get("amount", 0) >= 100000 and not tx.get("is_professional_investor", False)


# ═══════════════════════════ 优先级 5（最低）═══════════════════════════

class FrequentOpenCloseRule(BaseAMLRule):
    """R007: 频繁开销户"""
    rule_id = "R007"
    rule_name = "频繁开销户"
    rule_type = "周批"
    risk_level = "中"
    weight = 0.5
    trigger_condition = "30天开户>=3次 or 销户>=2次"

    def evaluate(self, tx: dict) -> bool:
        return tx.get("open_count_30d", 0) >= 3 or tx.get("close_count_30d", 0) >= 2


class AbnormalTimeRule(BaseAMLRule):
    """R008: 非正常时段大额交易"""
    rule_id = "R008"
    rule_name = "非正常时段大额交易"
    rule_type = "准实时"
    risk_level = "低"
    weight = 0.4
    trigger_condition = "凌晨0-6点 + >=10万 + 90天无类似"

    def evaluate(self, tx: dict) -> bool:
        ts = tx.get("timestamp", "")
        try:
            hour = int(ts[11:13]) if len(ts) >= 13 else 0
        except (ValueError, IndexError):
            return False
        return 0 <= hour < 6 and tx.get("amount", 0) >= 100000 and not tx.get("has_night_history_90d", False)


class FrequentTradeRule(BaseAMLRule):
    """R012: 频繁申购赎回"""
    rule_id = "R012"
    rule_name = "频繁申购赎回"
    rule_type = "日批"
    risk_level = "中"
    weight = 0.6
    trigger_condition = "30天申>=3 + 赎>=3 + 持有<7天"

    def evaluate(self, tx: dict) -> bool:
        return tx.get("buy_count_30d", 0) >= 3 and tx.get("sell_count_30d", 0) >= 3 and tx.get("hold_days", 999) < 7


class IdentityChangeRule(BaseAMLRule):
    """R015: 身份信息变更后大额交易"""
    rule_id = "R015"
    rule_name = "身份变更后大额交易"
    rule_type = "准实时"
    risk_level = "中"
    weight = 0.6
    trigger_condition = "变更手机/地址72h内 + >=10万"

    def evaluate(self, tx: dict) -> bool:
        return tx.get("info_changed_72h", False) and tx.get("amount", 0) >= 100000


class ElderlyRule(BaseAMLRule):
    """R016: 老年客户异常大额资金转出"""
    rule_id = "R016"
    rule_name = "老年客户异常大额转出"
    rule_type = "实时"
    risk_level = "中高"
    weight = 0.8
    trigger_condition = ">=65岁 + >=10万 + >过去12月月均×3"

    def evaluate(self, tx: dict) -> bool:
        if tx.get("age", 0) < 65:
            return False
        avg = tx.get("monthly_avg_12m", 0)
        return tx.get("amount", 0) >= 100000 and (avg <= 0 or tx.get("amount", 0) > avg * 3)


# ═══════════════════════════ 规则注册表 ═══════════════════════════

ALL_AML_RULES: list[BaseAMLRule] = [
    HighRiskCountryRule(), PEPRule(), MultiAccountRule(), GamblingFraudRule(),  # P1
    ScatterInRule(), ScatterOutRule(),                                           # P2
    LargeTransactionRule(), QuickInOutRule(), ThirdPartyPayRule(),              # P3
    FrequentSmallRule(), AmountMismatchRule(), IntegerAvoidRule(),               # P4
    RelatedTransRule(), NewAccountRule(), OffshoreRule(),
    FrequentOpenCloseRule(), AbnormalTimeRule(), FrequentTradeRule(),            # P5
    IdentityChangeRule(), ElderlyRule(),
]
