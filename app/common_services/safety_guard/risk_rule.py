from dataclasses import dataclass


@dataclass(frozen=True)
class SafetyRule:
    name: str
    action: str
    pattern: str


INPUT_RULES = (
    SafetyRule("password", "block", r"(?:密码|口令|验证码)\s*(?:是|为|:|：)?\s*\S+"),
)

OUTPUT_RULES = (
    # ── 承诺类 ──
    SafetyRule("guaranteed_return", "block", r"保证收益|稳赚不赔|保本保收益|无风险高收益"),
    SafetyRule("zero_risk", "block", r"零风险|无风险.*理财|绝对.*赚|一定.*涨|包赚|肯定.*能赚"),
    SafetyRule("promise_return", "block", r"承诺.*回报|稳赚|零损失|保本.*高收益|无风险.*收益"),
    # ── 夸大类 ──
    SafetyRule("exaggerate_product", "block", r"最佳.*产品|第一.*名|绝对.*安全|100%.*收益"),
    SafetyRule("exaggerate_safe", "block", r"稳如泰山|万无一失|只赚不赔"),
    # ── 诱导类 ──
    SafetyRule("insider_info", "block", r"内幕消息|代客操作|代客理财"),
    SafetyRule("urgency_tactic", "block", r"立即.*抢购|限时.*优惠|错过.*再等"),
    SafetyRule("internal_channel", "block", r"内部.*渠道|特殊.*名额"),
    # ── 违规类 ──
    SafetyRule("money_laundering", "block", r"(?<!反)洗钱|逃税|避税|套现"),
    SafetyRule("illegal_fund", "block", r"非法集资|庞氏骗局|传销"),
    # ── 金融合规类 ──
    SafetyRule("rigid_payment", "block", r"刚性兑付|兜底|暗箱操作"),
    SafetyRule("rat_trading", "block", r"老鼠仓|利益输送"),
)
