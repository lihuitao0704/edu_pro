"""
数据脱敏工具
对敏感信息（身份证、手机号、姓名、银行卡）进行脱敏处理
用途：日志输出、SSE 流式推送、会话归档

负责人: LHG
"""

import re
from typing import Optional


def mask_id_card(s: Optional[str]) -> str:
    """
    身份证号脱敏: 保留前 3 位和后 4 位
    例: 110101199001011234 → 110***1234
    """
    if not s:
        return ""
    s = str(s)
    if len(s) < 7:
        return s
    return s[:3] + "***" + s[-4:]


def mask_phone(s: Optional[str]) -> str:
    """
    手机号脱敏: 保留前 3 位和后 4 位
    例: 13812345678 → 138****5678
    """
    if not s:
        return ""
    s = str(s)
    if len(s) < 7:
        return s
    return s[:3] + "****" + s[-4:]


def mask_name(s: Optional[str]) -> str:
    """
    姓名脱敏: 保留姓氏，其余用 * 代替
    例: 张三 → 张*，王小明 → 王**
    """
    if not s:
        return ""
    s = str(s).strip()
    if len(s) <= 1:
        return s
    return s[0] + "*" * (len(s) - 1)


def mask_bank_card(s: Optional[str]) -> str:
    """
    银行卡号脱敏: 仅保留后 4 位
    例: 6222021234567890 → **7890
    """
    if not s:
        return ""
    s = str(s).replace(" ", "")
    if len(s) < 4:
        return "**"
    return "**" + s[-4:]


def mask_text(text: str) -> str:
    """
    自动检测并脱敏文本中的多种 PII（混合文本场景）
    顺序：身份证 → 银行卡 → 手机号
    使用 lookbehind/lookahead 代替 word boundary，确保中文相邻数字也能匹配
    """
    if not text:
        return ""

    # 身份证号 (18 位)
    text = re.sub(
        r'(?<!\d)(\d{3})\d{11}(\d{4})(?!\d)',
        lambda m: m.group(1) + "***" + m.group(2),
        text,
    )
    # 银行卡号 (16-19 位连续数字)
    text = re.sub(
        r'(?<!\d)\d{12,15}(\d{4})(?!\d)',
        lambda m: "**" + m.group(1),
        text,
    )
    # 手机号 (11 位)
    text = re.sub(
        r'(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)',
        lambda m: m.group(1) + "****" + m.group(2),
        text,
    )
    return text
