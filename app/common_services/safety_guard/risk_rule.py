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
    SafetyRule("guaranteed_return", "block", r"保证收益|稳赚不赔|保本保收益|无风险高收益"),
)
