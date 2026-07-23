"""
智能财富管家系统 · Streamlit 演示前端
AI Wealth Copilot for Private Banking
"""
import streamlit as st
import requests
import json
import time
import re
from datetime import datetime
from typing import Optional

# ==================== 配置 ====================
st.set_page_config(
    page_title="智能财富管家 · AI Copilot",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_BASE = "http://127.0.0.1:8001"
API_CHAT = f"{API_BASE}/api/chat"
API_AUTH = f"{API_BASE}/api/auth"

# ==================== Design Tokens (CSS 注入) ====================
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&family=Noto+Serif+SC:wght@600;700&display=swap');

:root {
    --ink: #0C1F1A;
    --ink-soft: #0E241D;
    --paper: #F7F6F2;
    --paper-card: #FFFFFF;
    --pine: #0E5F4C;
    --pine-hover: #0B4D3D;
    --gold: #C2A14D;
    --border: #E3E1DA;
    --border-strong: #C9C6BD;
    --text-primary: #1A1A1A;
    --text-secondary: #6B6B65;
    --text-tertiary: #9B9B93;
    --agent-customer: #3E7CB1;
    --agent-advisor: #0E5F4C;
    --agent-risk: #B4452F;
    --agent-analyst: #6B5CA5;
    --agent-operator: #B98A2F;
    --alert-low: #3B82C4;
    --alert-medium: #D9A400;
    --alert-high: #D4382C;
    --up: #D4382C;
    --down: #1D8A5F;
    --risk-R1: #4CAF7D;
    --risk-R2: #8BC34A;
    --risk-R3: #FFB74D;
    --risk-R4: #FF7043;
    --risk-R5: #C62828;
}

/* ============ 全局底色 ============ */
html, body, [class*="stApp"] {
    font-family: 'IBM Plex Sans', 'PingFang SC', 'Microsoft YaHei', system-ui !important;
    color: var(--text-primary) !important;
    background: var(--paper) !important;
}
[class*="stApp"] {
    background-image:
        linear-gradient(var(--paper) 100%),
        repeating-linear-gradient(0deg, transparent, transparent 23px, rgba(12,31,26,0.025) 23px, rgba(12,31,26,0.025) 24px),
        repeating-linear-gradient(90deg, transparent, transparent 23px, rgba(12,31,26,0.025) 23px, rgba(12,31,26,0.025) 24px);
    background-blend-mode: multiply;
}

/* ============ 侧栏（深松墨绿）============ */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, var(--ink) 0%, var(--ink-soft) 100%) !important;
    color: #E8E4D8 !important;
    border-right: 1px solid rgba(194,161,77,0.12);
}
section[data-testid="stSidebar"] * {
    color: #E8E4D8 !important;
    font-family: 'IBM Plex Sans', 'PingFang SC', sans-serif !important;
}
section[data-testid="stSidebar"] .stRadio label {
    background: transparent !important;
    border: 1px solid transparent !important;
    border-radius: 6px !important;
    padding: 8px 12px !important;
    margin: 2px 0 !important;
    transition: all 200ms cubic-bezier(0.22,1,0.36,1) !important;
}
section[data-testid="stSidebar"] .stRadio label:hover {
    background: rgba(255,255,255,0.04) !important;
    border-color: rgba(255,255,255,0.08) !important;
}
section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label:has(input:checked) {
    background: rgba(14,95,76,0.25) !important;
    border-left: 3px solid var(--pine) !important;
    border-color: var(--pine) !important;
}
section[data-testid="stSidebar"] hr {
    border-color: rgba(194,161,77,0.15) !important;
}

/* ============ 卡片 ============ */
[data-testid="stVerticalBlock"] > [data-testid="stVerticalBlockBorderWrapper"] {
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    box-shadow: 0 1px 2px rgba(12,31,26,0.04) !important;
    background: var(--paper-card) !important;
    transition: all 200ms cubic-bezier(0.22,1,0.36,1) !important;
}
[data-testid="stVerticalBlock"] > [data-testid="stVerticalBlockBorderWrapper"]:hover {
    box-shadow: 0 2px 6px rgba(12,31,26,0.08) !important;
    border-color: var(--border-strong) !important;
}

/* ============ 标题：衬线体 ============ */
h1, h2, h3 {
    font-family: 'Noto Serif SC', 'Source Han Serif SC', serif !important;
    font-weight: 600 !important;
    color: var(--text-primary) !important;
    letter-spacing: -0.01em !important;
}
h1 { font-size: 28px !important; }
h2 { font-size: 20px !important; }
h3 { font-size: 15px !important; font-weight: 600 !important; }

/* ============ 数字：等宽 + tabular-nums ============ */
.mono, .amount, code, pre {
    font-family: 'IBM Plex Mono', 'JetBrains Mono', monospace !important;
    font-variant-numeric: tabular-nums !important;
}

/* ============ 主按钮：松石绿 ============ */
.stButton > button[kind="primary"], .stButton > button {
    background: var(--pine) !important;
    color: #FFF !important;
    border: none !important;
    border-radius: 6px !important;
    font-family: 'IBM Plex Sans', sans-serif !important;
    font-weight: 500 !important;
    padding: 8px 18px !important;
    transition: all 150ms !important;
}
.stButton > button:hover {
    background: var(--pine-hover) !important;
    transform: translateY(-1px);
}

/* ============ 输入框 ============ */
.stTextInput input, .stTextArea textarea, .stSelectbox select {
    border: 1px solid var(--border-strong) !important;
    border-radius: 6px !important;
    background: var(--paper-card) !important;
    font-family: 'IBM Plex Sans', sans-serif !important;
}
.stTextInput input:focus, .stTextArea textarea:focus {
    border-color: var(--pine) !important;
    box-shadow: 0 0 0 3px rgba(14,95,76,0.1) !important;
}

/* ============ Tabs ============ */
.stTabs [data-baseweb="tab-list"] {
    gap: 0 !important;
    border-bottom: 1px solid var(--border) !important;
}
.stTabs [data-baseweb="tab"] {
    background: transparent !important;
    color: var(--text-secondary) !important;
    border: none !important;
    border-bottom: 2px solid transparent !important;
    padding: 10px 18px !important;
    font-weight: 500 !important;
}
.stTabs [aria-selected="true"] {
    color: var(--pine) !important;
    border-bottom-color: var(--pine) !important;
}

/* ============ Metrics ============ */
[data-testid="stMetricValue"] {
    font-family: 'IBM Plex Mono', monospace !important;
    font-variant-numeric: tabular-nums !important;
    font-weight: 500 !important;
    color: var(--text-primary) !important;
}
[data-testid="stMetricLabel"] {
    font-family: 'IBM Plex Sans', sans-serif !important;
    color: var(--text-secondary) !important;
}

/* ============ Chips ============ */
.chip {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 4px;
    font-size: 11.5px;
    font-weight: 500;
    margin: 2px 3px 2px 0;
    font-family: 'IBM Plex Sans', sans-serif;
}
.chip-intent { background: #E8F4EE; color: var(--pine); }
.chip-risk-R1 { background: #E8F5E9; color: #2E7D32; }
.chip-risk-R2 { background: #F1F8E9; color: #558B2F; }
.chip-risk-R3 { background: #FFF3E0; color: #E65100; }
.chip-risk-R4 { background: #FBE9E7; color: #BF360C; }
.chip-risk-R5 { background: #FFEBEE; color: #B71C1C; }
.chip-alert-low { background: #E3F2FD; color: var(--alert-low); border-left: 2px solid var(--alert-low); }
.chip-alert-medium { background: #FFF8E1; color: #A67C00; border-left: 2px solid var(--alert-medium); }
.chip-alert-high {
    background: #FFEBEE; color: var(--alert-high);
    border-left: 2px solid var(--alert-high);
    animation: breathe 2.4s ease-in-out infinite;
}
@keyframes breathe {
    0%, 100% { box-shadow: 0 0 0 0 rgba(212,56,44,0); }
    50% { box-shadow: 0 0 8px 2px rgba(212,56,44,0.12); }
}

/* ============ 对话气泡 ============ */
.chat-user {
    background: #EAE7DE;
    padding: 12px 16px;
    border-radius: 8px;
    border-bottom-right-radius: 2px;
    margin: 8px 0 8px 20%;
    font-size: 13.5px;
    line-height: 1.65;
}
.chat-ai {
    background: var(--paper-card);
    border: 1px solid var(--border);
    padding: 14px 18px;
    border-radius: 8px;
    border-bottom-left-radius: 2px;
    margin: 8px 20% 8px 0;
    font-size: 13.5px;
    line-height: 1.7;
}
.chat-ai-meta {
    display: flex;
    gap: 12px;
    align-items: center;
    margin-top: 12px;
    padding-top: 10px;
    border-top: 1px dashed var(--border);
    font-size: 11.5px;
    color: var(--text-secondary);
}
.confidence-ring {
    width: 24px; height: 24px;
    border-radius: 50%;
    background: conic-gradient(var(--pine) calc(var(--pct) * 1%), #E3E1DA 0);
    display: inline-flex; align-items: center; justify-content: center;
    font-size: 10px; color: var(--pine); font-weight: 600;
}
.confidence-ring::after {
    content: ''; width: 16px; height: 16px; border-radius: 50%; background: white;
    position: absolute;
}

/* ============ 二次确认卡片 ============ */
.confirm-card {
    border: 1px solid var(--alert-medium);
    border-left: 3px solid var(--alert-medium);
    background: #FFFBF0;
    padding: 16px;
    border-radius: 8px;
    margin: 10px 0;
}
.confirm-card .amount {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 18px;
    font-weight: 600;
    color: var(--text-primary);
    font-variant-numeric: tabular-nums;
}

/* ============ 表格 ============ */
[data-testid="stDataFrame"] {
    border: 1px solid var(--border) !important;
    border-radius: 6px !important;
}
[data-testid="stDataFrame"] th {
    background: #FAF9F5 !important;
    font-weight: 600 !important;
    font-size: 12px !important;
}

/* ============ 品牌标识 ============ */
.brand-mark {
    font-family: 'Noto Serif SC', serif;
    font-weight: 700;
    font-size: 18px;
    color: var(--paper);
    letter-spacing: 0.04em;
    margin-bottom: 4px;
}
.brand-mark .gold {
    color: var(--gold);
    font-size: 14px;
    margin-left: 6px;
    font-weight: 600;
}
.brand-sub {
    font-size: 11px;
    color: rgba(232,228,216,0.5);
    letter-spacing: 0.08em;
    margin-bottom: 18px;
}

/* ============ Agent 头像光环 ============ */
.agent-avatar {
    width: 36px; height: 36px;
    border-radius: 8px;
    display: inline-flex; align-items: center; justify-content: center;
    font-size: 16px;
    margin-right: 10px;
    flex-shrink: 0;
    box-shadow: 0 0 0 2px var(--agent-color, var(--pine));
}

/* ============ 工具调用抽屉 ============ */
.tool-drawer {
    background: #FAF9F5;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 12px 14px;
    margin: 8px 0;
    font-size: 12.5px;
}
.tool-drawer .sql-block {
    background: #0C1F1A;
    color: #A8E6CF;
    padding: 10px 14px;
    border-radius: 6px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    overflow-x: auto;
    margin: 8px 0;
}
.tool-drawer .security-badge {
    display: inline-block;
    background: #E8F4EE;
    color: var(--pine);
    padding: 2px 8px;
    border-radius: 3px;
    font-size: 10px;
    font-weight: 600;
    margin-left: 6px;
}

/* ============ 来源 chip ============ */
.source-chip {
    display: inline-block;
    padding: 4px 10px;
    background: #F1F0EA;
    border-radius: 4px;
    font-size: 11px;
    color: var(--text-secondary);
    margin: 2px 4px 2px 0;
}
.source-chip .score {
    color: var(--pine);
    font-weight: 600;
    font-family: 'IBM Plex Mono', monospace;
    margin-left: 4px;
}

/* ============ 建议问题 ============ */
.suggestion-chip {
    display: inline-block;
    padding: 6px 12px;
    background: var(--paper-card);
    border: 1px solid var(--border);
    border-radius: 16px;
    font-size: 12px;
    color: var(--text-primary);
    margin: 3px 4px 3px 0;
    cursor: pointer;
    transition: all 150ms;
}
.suggestion-chip:hover {
    border-color: var(--pine);
    color: var(--pine);
    background: #F0F7F4;
}

/* ============ 状态栏 ============ */
.status-bar {
    position: fixed;
    bottom: 0; left: 0; right: 0;
    height: 24px;
    background: var(--ink);
    color: rgba(232,228,216,0.6);
    font-size: 10.5px;
    display: flex;
    align-items: center;
    padding: 0 16px;
    gap: 16px;
    z-index: 999;
    font-family: 'IBM Plex Mono', monospace;
}
.status-bar .dot {
    display: inline-block;
    width: 6px; height: 6px;
    border-radius: 50%;
    background: #4CAF7D;
    margin-right: 5px;
    animation: pulse 2s infinite;
}
@keyframes pulse {
    0%,100% { opacity: 1; } 50% { opacity: 0.4; }
}

/* ============ 减少动画（无障碍）============ */
@media (prefers-reduced-motion: reduce) {
    .chip-alert-high { animation: none !important; }
    * { transition: none !important; animation: none !important; }
}

/* ============ 隐藏 Streamlit 默认元素 ============ */
#MainMenu, footer, header { visibility: hidden; height: 0; }
.stDeployButton { display: none !important; }
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)

# ==================== Session State ====================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user" not in st.session_state:
    st.session_state.user = None
if "token" not in st.session_state:
    st.session_state.token = None
if "current_agent" not in st.session_state:
    st.session_state.current_agent = "customer"
if "messages" not in st.session_state:
    st.session_state.messages = {}  # per-agent message history
if "session_id" not in st.session_state:
    import random
    st.session_state.session_id = "web-" + ''.join(random.choices('abcdefghijklmnopqrstuvwxyz01234567', k=8))

# ==================== Agent 定义 ====================
AGENTS = {
    "customer": {
        "name": "智能客服",
        "icon": "🧑‍💼",
        "color": "#3E7CB1",
        "role": "零售 / 高净值客户",
        "desc": "RAG 问答 · 转人工兜底",
        "greeting": "您好，我是智能财富管家 AI 客服。请问有什么可以帮您？",
        "quick_commands": [
            "查询我的风险等级",
            "如何开通基金账户？",
            "转人工客服",
            "产品赎回流程",
        ],
    },
    "advisor": {
        "name": "投顾助手",
        "icon": "🎯",
        "color": "#0E5F4C",
        "role": "理财顾问",
        "desc": "客户画像 · 适当性 · GraphRAG",
        "greeting": "您好，我是您的 AI 投顾助手。可以帮您分析客户画像、推荐匹配产品、解读市场动态。",
        "quick_commands": [
            "分析客户张三的画像",
            "为 C3 客户推荐 R3 以内产品",
            "新能源行业近期走势",
            "查看客户持仓",
        ],
    },
    "risk": {
        "name": "风控监测",
        "icon": "🛡️",
        "color": "#B4452F",
        "role": "风控专员",
        "desc": "20 条反洗钱规则 · 三级预警",
        "greeting": "风控监测系统就绪。当前未处理预警 3 条，请指示。",
        "quick_commands": [
            "查看未处理预警",
            "分析客户 ID 1001 近期交易",
            "生成可疑交易报告",
            "本月预警统计",
        ],
    },
    "analyst": {
        "name": "数据分析",
        "icon": "📊",
        "color": "#6B5CA5",
        "role": "内部员工",
        "desc": "NL2SQL · 仅 SELECT · 自然语言解读",
        "greeting": "数据分析 Agent 就绪。请用自然语言描述您想查询的数据，我会生成 SQL 并解读结果。",
        "quick_commands": [
            "AUM 超过 100 万的客户有多少个",
            "本月各产品类型的申购总额",
            "风险等级为 C4 的客户持仓分布",
            "近 30 天预警数量趋势",
        ],
    },
    "operator": {
        "name": "业务操作",
        "icon": "⚡",
        "color": "#B98A2F",
        "role": "客户经理",
        "desc": "NL2API 8 种意图 · RBAC · 二次确认",
        "greeting": "业务操作 Agent 就绪。可执行：申购、赎回、转账、风评重做、信息更新、产品查询、可疑上报、工单创建。",
        "quick_commands": [
            "为客户张三申购 5 万元「稳健增长混合基金」",
            "查询在售 R3 产品列表",
            "为客户李四重做风评",
            "转账 6 万元给客户王五",
        ],
    },
}

# ==================== Mock 数据 ====================
MOCK_PRODUCTS = [
    {"code": "F000001", "name": "现金增利货币", "type": "货币", "risk": "R1", "return": 2.15, "min": 1, "status": "在售"},
    {"code": "F000002", "name": "短债安心 90 天", "type": "债券", "risk": "R1", "return": 3.25, "min": 1000, "status": "在售"},
    {"code": "F000003", "name": "稳健增长混合 A", "type": "混合", "risk": "R3", "return": 8.42, "min": 10000, "status": "在售"},
    {"code": "F000004", "name": "沪深 300 指数增强", "type": "股票", "risk": "R4", "return": 12.68, "min": 10000, "status": "在售"},
    {"code": "F000005", "name": "科技创新精选", "type": "股票", "risk": "R5", "return": -5.32, "min": 50000, "status": "在售"},
    {"code": "F000006", "name": "全球配置 QDII", "type": "混合", "risk": "R4", "return": 6.85, "min": 100000, "status": "暂停"},
]

MOCK_CUSTOMERS = {
    "A": {
        "id": 1001, "name": "明**", "level": "钻石", "risk": "C4", "risk_name": "进取型",
        "age": 42, "assets": 8_450_000, "income": "100 万以上",
        "dimensions": {"basic": 22.5, "experience": 20.0, "risk_pref": 24.0, "behavior": 16.5},
        "total_score": 83, "confidence": 0.92,
        "tags": [
            {"name": "高净值", "source": "AI 提取", "conf": 0.95},
            {"name": "稳健偏好", "source": "风评问卷", "conf": 0.88},
            {"name": "长期持有", "source": "行为分析", "conf": 0.82},
        ],
        "holdings": [
            {"product": "稳健增长混合 A", "shares": 150000, "nav": 1.2345, "value": 185175, "pnl": 3.24, "risk": "R3"},
            {"product": "沪深 300 指数增强", "shares": 80000, "nav": 2.0156, "value": 161248, "pnl": -1.85, "risk": "R4"},
        ],
    },
    "B": {
        "id": 1002, "name": "张*", "level": "普通", "risk": "C2", "risk_name": "稳健型",
        "age": 28, "assets": 85_000, "income": "10-30 万",
        "dimensions": {"basic": 15.0, "experience": 10.5, "risk_pref": 12.0, "behavior": 18.0},
        "total_score": 55.5, "confidence": 0.71,
        "tags": [
            {"name": "新客", "source": "AI 提取", "conf": 0.90},
            {"name": "低风险偏好", "source": "风评问卷", "conf": 0.85},
        ],
        "holdings": [
            {"product": "短债安心 90 天", "shares": 50000, "nav": 1.0032, "value": 50160, "pnl": 0.32, "risk": "R1"},
        ],
    },
}

MOCK_ALERTS = [
    {"id": "ALT-20260723-001", "level": "low", "customer": "张*", "rules": ["R001 大额交易"],
     "amount": 180_000, "time": "2026-07-23 10:15", "status": "待处理", "conf": 0.72},
    {"id": "ALT-20260723-002", "level": "medium", "customer": "李**",
     "rules": ["R001 大额交易", "R003 频繁交易"],
     "amount": 450_000, "time": "2026-07-23 11:42", "status": "待处理", "conf": 0.85},
    {"id": "ALT-20260723-003", "level": "high", "customer": "王**",
     "rules": ["R001 大额交易", "R003 频繁交易", "R007 分散转入集中转出", "历史预警"],
     "amount": 2_350_000, "time": "2026-07-23 14:08", "status": "待处理", "conf": 0.94},
]

# ==================== 工具函数 ====================

def fmt_amount(v, mask=False):
    """金额格式化（千分位 + 2 位小数）；mask=True 时脱敏"""
    if mask:
        s = f"{v:,.0f}"
        if len(s) > 4:
            return s[:-4] + "****"
        return "****"
    return f"{v:,.2f}"

def fmt_nav(v):
    """净值 4-6 位小数"""
    return f"{v:.6f}".rstrip('0').rstrip('.')

def fmt_pct(v):
    """收益率带 % 号，红涨绿跌"""
    color = "var(--up)" if v >= 0 else "var(--down)"
    arrow = "▲" if v >= 0 else "▼"
    return f'<span style="color:{color};font-family:IBM Plex Mono,monospace;font-variant-numeric:tabular-nums">{arrow} {abs(v):.2f}%</span>'

def mask_id(s):
    """身份证脱敏：110****1234"""
    if len(s) < 8: return s
    return s[:3] + "****" + s[-4:]

def mask_phone(s):
    """手机脱敏：138****5678"""
    if len(s) < 7: return s
    return s[:3] + "****" + s[-4:]

def mask_name(s):
    """姓名脱敏：张**"""
    if not s: return s
    return s[0] + "**" * max(1, len(s) - 1)

def mask_card(s):
    """银行卡脱敏：**6789"""
    if len(s) < 4: return s
    return "**" + s[-4:]

def risk_chip(level):
    """R1-R5 色阶 chip"""
    return f'<span class="chip chip-risk-{level}">{level}</span>'

def alert_chip(level):
    return f'<span class="chip chip-alert-{level}">{level.upper()}</span>'

# 适当性矩阵
SUITABILITY = {
    "C1": ["R1"],
    "C2": ["R1", "R2"],
    "C3": ["R1", "R2", "R3"],
    "C4": ["R1", "R2", "R3", "R4"],
    "C5": ["R1", "R2", "R3", "R4", "R5"],
}

def check_suitability(customer_level, product_risk):
    allowed = SUITABILITY.get(customer_level, [])
    return product_risk in allowed

# ==================== API 调用 ====================

def api_call(path, method="GET", body=None, need_auth=True):
    """统一 API 调用"""
    headers = {"Content-Type": "application/json"}
    if need_auth and st.session_state.token:
        headers["Authorization"] = f"Bearer {st.session_state.token}"
    url = f"{API_BASE}{path}"
    try:
        if method == "GET":
            r = requests.get(url, headers=headers, timeout=15)
        else:
            r = requests.post(url, headers=headers, json=body, timeout=30)
        return r.json()
    except requests.exceptions.ConnectionError:
        return {"code": 503, "message": "后端服务未启动（使用 Mock 模式）", "data": None, "trace_id": "offline"}
    except Exception as e:
        return {"code": 500, "message": str(e), "data": None, "trace_id": "err"}

def chat_with_agent(agent_type, message, user_role="理财顾问"):
    """调用对应 Agent 的对话接口"""
    paths = {
        "customer": "/api/chat/customer",
        "advisor": "/api/chat/advisor",
        "risk": "/api/chat/analyst",  # risk 暂用 analyst
        "analyst": "/api/chat/analyst",
        "operator": "/api/chat/operator",
    }
    path = paths.get(agent_type, "/api/chat/customer")
    body = {
        "message": message,
        "session_id": st.session_state.session_id,
    }
    if agent_type == "operator":
        body["user_id"] = st.session_state.user.get("user_id", 0) if st.session_state.user else 0
        body["user_role"] = user_role

    result = api_call(path, "POST", body)

    # 标准化响应
    if result.get("code") == 200 and result.get("data"):
        data = result["data"]
        return {
            "reply": data.get("reply", ""),
            "intent": data.get("intent", ""),
            "confidence": data.get("confidence", 0.5),
            "source_references": data.get("source_references", []),
            "tool_calls": data.get("tool_calls", []),
            "suggestions": data.get("suggestions", []),
            "trace_id": result.get("trace_id", ""),
        }
    # 后端未启动 → Mock 回复
    return mock_reply(agent_type, message)

def mock_reply(agent_type, message):
    """后端不可用时的 Mock 回复"""
    agent = AGENTS[agent_type]
    if agent_type == "analyst":
        return {
            "reply": f"已为您查询：「{message}」\n\n**结果**：AUM 超过 100 万的客户共有 **23** 位，其中 C4 进取型 12 位、C5 激进型 5 位。\n\n总资产合计 **¥4.28 亿**，近 30 天净流入 **¥2,150 万**。",
            "intent": "数据查询",
            "confidence": 0.88,
            "source_references": [],
            "tool_calls": [{
                "tool": "NL2SQL",
                "params": {"query": message},
                "sql": "SELECT risk_level, COUNT(*) as cnt, SUM(total_assets) as aum\nFROM fin_customer_profile\nWHERE total_assets > 1000000\nGROUP BY risk_level\nORDER BY aum DESC;",
                "result_rows": 5,
                "explanation": "查询 AUM 超 100 万的客户按风险等级分布",
            }],
            "suggestions": ["按行业细分这些客户的持仓", "近 90 天这些客户的净申购额"],
            "trace_id": "mock-" + str(int(time.time())),
        }
    if agent_type == "operator":
        return {
            "reply": f"已为您执行：「{message}」\n\n✅ 操作成功\n\n交易流水号：TXN20260723141256A3B2C1\n确认份额：8,098.52 份\n适用净值日期：2026-07-23",
            "intent": "产品申购",
            "confidence": 0.95,
            "source_references": [],
            "tool_calls": [{
                "tool": "NL2API",
                "params": {
                    "action": "purchase_product",
                    "customer_name": "张*",
                    "product_name": "稳健增长混合 A",
                    "amount": 10000,
                },
            }],
            "suggestions": ["查询该产品近 30 天走势", "查看客户持仓"],
            "trace_id": "mock-" + str(int(time.time())),
        }
    return {
        "reply": f"[{agent['name']}] 收到您的问题：「{message}」\n\n这是 Mock 回复。请启动后端服务（`python main.py`）以获得真实的 AI 响应。当前处于演示模式，展示交互与视觉规范。",
        "intent": "问题识别",
        "confidence": 0.5,
        "source_references": [{"title": "Mock 数据源", "score": 0.0, "type": "演示模式"}],
        "tool_calls": [],
        "suggestions": agent["quick_commands"][:3],
        "trace_id": "mock-" + str(int(time.time())),
    }

# ==================== 登录页 ====================

def render_login():
    """登录页：左品牌 / 右表单"""
    # 隐藏侧栏
    st.markdown("""
    <style>section[data-testid="stSidebar"]{display:none !important}</style>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 1.3, 1])
    with col2:
        st.markdown("")
        st.markdown("")
        st.markdown('<div class="brand-mark" style="font-size:32px;color:var(--ink)">智能财富管家<span class="gold">AI · Copilot</span></div>', unsafe_allow_html=True)
        st.markdown('<div style="color:var(--text-secondary);font-size:13px;margin-bottom:28px;letter-spacing:0.08em">PRIVATE BANKING · WEALTH MANAGEMENT PLATFORM</div>', unsafe_allow_html=True)

        with st.form("login_form"):
            username = st.text_input("用户名", value="", placeholder="请输入用户名")
            password = st.text_input("密码", type="password", value="", placeholder="请输入密码")

            # 测试账号快捷选择
            role_choice = st.selectbox(
                "测试账号快捷填充",
                options=["自定义", "理财顾问 (advisor)", "风控专员 (risk_officer)", "客户经理 (manager)", "零售客户 (retail)", "私行客户 (private)"],
                index=0,
            )
            st.markdown("")
            submitted = st.form_submit_button("登 录", use_container_width=True)

        if submitted:
            # 快捷填充
            role_map = {
                "理财顾问 (advisor)": ("advisor", "advisor123"),
                "风控专员 (risk_officer)": ("risk_officer", "risk1234"),
                "客户经理 (manager)": ("manager", "manager123"),
                "零售客户 (retail)": ("retail", "retail123"),
                "私行客户 (private)": ("private", "private123"),
            }
            if role_choice in role_map and not username:
                username, password = role_map[role_choice]
            if not username or not password:
                st.error("请输入用户名和密码")
                return
            # 调用登录 API
            result = api_call("/api/auth/login", "POST", {"username": username, "password": password}, need_auth=False)
            if result.get("code") == 200 and result.get("data", {}).get("access_token"):
                st.session_state.authenticated = True
                st.session_state.token = result["data"]["access_token"]
                st.session_state.user = result["data"].get("user", {"username": username, "role": "理财顾问"})
                st.success("登录成功")
                time.sleep(0.5)
                st.rerun()
            else:
                # 后端不可用 → Mock 登录
                st.session_state.authenticated = True
                st.session_state.token = "mock-token"
                st.session_state.user = {"username": username, "role": "理财顾问", "user_id": 1}
                st.info("后端未启动，使用 Mock 登录")
                time.sleep(0.5)
                st.rerun()

# ==================== Agent 工作台 ====================

def render_workspace():
    """P0 · Agent 工作台（灵魂页面）"""
    agent = AGENTS[st.session_state.current_agent]

    # 顶部栏
    top1, top2, top3 = st.columns([2, 3, 2])
    with top1:
        st.markdown(f"""
        <div style="display:flex;align-items:center;gap:10px">
            <div class="agent-avatar" style="--agent-color:{agent['color']};background:{agent['color']}15;color:{agent['color']}">{agent['icon']}</div>
            <div>
                <div style="font-family:'Noto Serif SC',serif;font-weight:700;font-size:17px">{agent['name']}</div>
                <div style="font-size:11px;color:var(--text-secondary);margin-top:1px">{agent['role']} · {agent['desc']}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    with top2:
        pass
    with top3:
        user = st.session_state.user or {}
        st.markdown(f"""
        <div style="text-align:right;font-size:12px;color:var(--text-secondary)">
            <span style="color:var(--gold);font-weight:600">●</span>
            {user.get('username', '')} · <span style="color:var(--pine);font-weight:500">{user.get('role', '')}</span>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # 主工作区：对话 + 上下文面板
    main_col, ctx_col = st.columns([2.2, 1], gap="large")

    with main_col:
        render_chat_area(agent)

    with ctx_col:
        render_context_panel(agent)

def render_chat_area(agent):
    """对话流 + 输入"""
    agent_key = st.session_state.current_agent
    if agent_key not in st.session_state.messages:
        st.session_state.messages[agent_key] = [
            {"role": "assistant", "content": agent["greeting"], "meta": {
                "intent": "问候", "confidence": 1.0,
                "source_references": [], "tool_calls": [], "suggestions": agent["quick_commands"]
            }}
        ]

    # 快捷指令
    st.markdown(f"""
    <div style="font-size:11.5px;color:var(--text-tertiary);margin-bottom:6px">快捷指令</div>
    """, unsafe_allow_html=True)
    qc_cols = st.columns(len(agent["quick_commands"]))
    for i, cmd in enumerate(agent["quick_commands"]):
        with qc_cols[i]:
            if st.button(cmd, key=f"qc_{agent_key}_{i}", use_container_width=True):
                handle_user_message(cmd, agent)
                st.rerun()

    st.markdown("")

    # 对话消息流
    chat_container = st.container(height=520, border=False)
    with chat_container:
        for msg in st.session_state.messages[agent_key]:
            if msg["role"] == "user":
                st.markdown(f'<div class="chat-user">{msg["content"]}</div>', unsafe_allow_html=True)
            else:
                render_ai_message(msg)

    # 输入区
    st.markdown("")
    user_input = st.chat_input(f"向{agent['name']}提问...", key=f"input_{agent_key}")
    if user_input:
        handle_user_message(user_input, agent)
        st.rerun()

def handle_user_message(message, agent):
    """处理用户消息：添加到历史 + 调用 Agent"""
    agent_key = st.session_state.current_agent
    if agent_key not in st.session_state.messages:
        st.session_state.messages[agent_key] = []

    st.session_state.messages[agent_key].append({"role": "user", "content": message})

    # 调用 Agent
    with st.spinner(f"{agent['name']}思考中..."):
        reply = chat_with_agent(agent_key, message, user_role=(st.session_state.user or {}).get("role", "理财顾问"))

    st.session_state.messages[agent_key].append({
        "role": "assistant",
        "content": reply["reply"],
        "meta": {
            "intent": reply.get("intent", ""),
            "confidence": reply.get("confidence", 0.5),
            "source_references": reply.get("source_references", []),
            "tool_calls": reply.get("tool_calls", []),
            "suggestions": reply.get("suggestions", []),
        },
        "trace_id": reply.get("trace_id", ""),
    })

def render_ai_message(msg):
    """渲染 AI 消息 + 四件套"""
    meta = msg.get("meta", {})
    intent = meta.get("intent", "")
    confidence = meta.get("confidence", 0.5)
    sources = meta.get("source_references", [])
    tools = meta.get("tool_calls", [])
    suggestions = meta.get("suggestions", [])

    # 主回复
    st.markdown(f'<div class="chat-ai">{msg["content"]}</div>', unsafe_allow_html=True)

    # 四件套元信息
    meta_html = '<div class="chat-ai-meta">'

    # 1. 意图 chip + 置信度圆环
    if intent:
        meta_html += f'<span class="chip chip-intent">{intent}</span>'
    if confidence:
        pct = int(confidence * 100)
        meta_html += f'''
        <div style="position:relative;display:inline-flex;align-items:center;justify-content:center">
            <div class="confidence-ring" style="--pct:{pct}"></div>
            <span style="position:absolute;font-size:9px;font-weight:600;color:var(--pine)">{pct}</span>
        </div>
        '''

    # trace_id
    trace_id = msg.get("trace_id", "")
    if trace_id:
        meta_html += f'<span style="margin-left:auto;font-family:IBM Plex Mono,monospace;font-size:10px;color:var(--text-tertiary)" title="{trace_id}">trace: {trace_id[:12]}...</span>'

    meta_html += '</div>'
    st.markdown(meta_html, unsafe_allow_html=True)

    # 2. 引用来源（折叠）
    if sources:
        with st.expander(f"📚 引用来源（{len(sources)} 条）", expanded=False):
            for src in sources:
                score = src.get("score", 0)
                score_color = "var(--pine)" if score >= 0.7 else "var(--alert-medium)" if score >= 0.5 else "var(--text-tertiary)"
                st.markdown(f"""
                <div class="source-chip">
                    {src.get('title', '')} · <em>{src.get('type', '')}</em>
                    <span class="score" style="color:{score_color}">{score:.2f}</span>
                </div>
                """, unsafe_allow_html=True)

    # 3. 工具调用抽屉
    if tools:
        with st.expander(f"🧠 思考过程（{len(tools)} 个工具）", expanded=False):
            for tc in tools:
                tool_name = tc.get("tool", "")
                if tool_name == "NL2SQL":
                    st.markdown(f"""
                    <div class="tool-drawer">
                        <div style="font-weight:600;margin-bottom:6px">📊 NL2SQL<span class="security-badge">仅 SELECT · 已校验</span></div>
                        <div class="sql-block">{tc.get('sql', '').replace('<', '&lt;').replace('>', '&gt;')}</div>
                        <div style="font-size:12px;color:var(--text-secondary);margin-top:8px">
                            返回 <strong>{tc.get('result_rows', 0)}</strong> 行 · {tc.get('explanation', '')}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                elif tool_name == "NL2API":
                    params = tc.get("params", {})
                    st.markdown(f"""
                    <div class="tool-drawer">
                        <div style="font-weight:600;margin-bottom:6px">⚡ NL2API · {params.get('action', '')}</div>
                        <div class="sql-block">{json.dumps(params, ensure_ascii=False, indent=2)}</div>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.json(tc)

    # 4. 建议问题
    if suggestions:
        sug_html = '<div style="margin-top:10px">'
        for s in suggestions:
            sug_html += f'<span class="suggestion-chip">{s}</span>'
        sug_html += '</div>'
        st.markdown(sug_html, unsafe_allow_html=True)

def render_context_panel(agent):
    """右侧上下文面板：根据 Agent 场景切换"""
    agent_key = st.session_state.current_agent

    st.markdown(f"""
    <div style="font-family:'Noto Serif SC',serif;font-weight:600;font-size:15px;margin-bottom:14px;color:var(--text-primary)">
        上下文
    </div>
    """, unsafe_allow_html=True)

    if agent_key == "advisor":
        render_customer_profile_panel()
    elif agent_key == "risk":
        render_risk_panel()
    elif agent_key == "analyst":
        render_analyst_panel()
    elif agent_key == "operator":
        render_operator_panel()
    else:
        render_customer_panel()

def render_customer_profile_panel():
    """advisor 上下文：客户画像"""
    cust = MOCK_CUSTOMERS["A"]
    st.markdown(f"""
    <div style="background:var(--paper-card);border:1px solid var(--border);border-radius:8px;padding:14px;margin-bottom:12px">
        <div style="font-weight:600;font-size:13px">{cust['name']} <span style="color:var(--gold);font-size:11px;font-weight:600">● {cust['level']}</span></div>
        <div style="font-size:11px;color:var(--text-secondary);margin-top:3px">ID: {cust['id']} · {cust['age']}岁 · {cust['income']}</div>
        <div style="margin-top:10px;display:flex;gap:8px;align-items:baseline">
            <span style="font-family:'IBM Plex Mono';font-size:18px;font-weight:600;font-variant-numeric:tabular-nums">¥{fmt_amount(cust['assets'])}</span>
            <span style="font-size:11px;color:var(--text-tertiary)">总资产</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 风险仪表 + 四维度
    total = cust['total_score']
    level = cust['risk']
    st.markdown(f"""
    <div style="background:var(--paper-card);border:1px solid var(--border);border-radius:8px;padding:14px;margin-bottom:12px">
        <div style="font-weight:600;font-size:13px;margin-bottom:8px">风险画像</div>
        <div style="display:flex;align-items:center;gap:14px">
            <div style="font-family:'IBM Plex Mono';font-size:24px;font-weight:700;color:var(--pine)">{total}</div>
            <div>
                {risk_chip(level.replace('C', 'R'))}
                <span style="font-size:12px;color:var(--text-secondary);margin-left:4px">{cust['risk_name']}</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 四维度
    dims = cust['dimensions']
    st.markdown("**四维度得分**")
    dim_data = {
        "基础属性 (25)": dims['basic'],
        "投资经验 (25)": dims['experience'],
        "风险偏好 (30)": dims['risk_pref'],
        "行为异常 (20)": dims['behavior'],
    }
    for name, score in dim_data.items():
        max_score = float(name.split('(')[1].split(')')[0])
        pct = score / max_score
        st.markdown(f"""
        <div style="margin-bottom:8px">
            <div style="display:flex;justify-content:space-between;font-size:11.5px;margin-bottom:3px">
                <span>{name}</span>
                <span style="font-family:IBM Plex Mono;font-weight:500">{score:.1f}</span>
            </div>
            <div style="background:#E3E1DA;height:4px;border-radius:2px;overflow:hidden">
                <div style="background:var(--pine);height:100%;width:{pct*100:.0f}%;border-radius:2px;transition:width 600ms cubic-bezier(0.22,1,0.36,1)"></div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # 标签
    st.markdown("**画像标签**")
    for tag in cust['tags']:
        st.markdown(f"""
        <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px dashed var(--border);font-size:12px">
            <span><strong>{tag['name']}</strong> <span style="color:var(--text-tertiary);font-size:10.5px">· {tag['source']}</span></span>
            <span style="font-family:IBM Plex Mono;color:var(--pine);font-weight:500">{tag['conf']:.2f}</span>
        </div>
        """, unsafe_allow_html=True)

    # 持仓
    st.markdown("**持仓明细**")
    for h in cust['holdings']:
        st.markdown(f"""
        <div style="background:var(--paper-card);border:1px solid var(--border);border-radius:6px;padding:10px;margin:6px 0;font-size:12px">
            <div style="display:flex;justify-content:space-between;align-items:center">
                <strong>{h['product']}</strong>
                {risk_chip(h['risk'])}
            </div>
            <div style="display:flex;justify-content:space-between;margin-top:6px;font-family:IBM Plex Mono;font-variant-numeric:tabular-nums">
                <span>份额 <strong>{h['shares']:,.2f}</strong></span>
                <span>市值 <strong>¥{h['value']:,.2f}</strong></span>
                <span>{fmt_pct(h['pnl'])}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

def render_risk_panel():
    """risk 上下文：预警列表"""
    st.markdown("**未处理预警**")
    counts = {"low": 0, "medium": 0, "high": 0}
    for a in MOCK_ALERTS:
        counts[a['level']] += 1

    st.markdown(f"""
    <div style="display:flex;gap:8px;margin-bottom:12px">
        <div style="flex:1;background:#E3F2FD;border-left:3px solid var(--alert-low);padding:8px 12px;border-radius:6px">
            <div style="font-size:10px;color:var(--alert-low)">低</div>
            <div style="font-family:IBM Plex Mono;font-size:18px;font-weight:600;color:var(--alert-low)">{counts['low']}</div>
        </div>
        <div style="flex:1;background:#FFF8E1;border-left:3px solid var(--alert-medium);padding:8px 12px;border-radius:6px">
            <div style="font-size:10px;color:#A67C00">中</div>
            <div style="font-family:IBM Plex Mono;font-size:18px;font-weight:600;color:#A67C00">{counts['medium']}</div>
        </div>
        <div style="flex:1;background:#FFEBEE;border-left:3px solid var(--alert-high);padding:8px 12px;border-radius:6px">
            <div style="font-size:10px;color:var(--alert-high)">高</div>
            <div style="font-family:IBM Plex Mono;font-size:18px;font-weight:600;color:var(--alert-high)">{counts['high']}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    for a in MOCK_ALERTS:
        st.markdown(f"""
        <div style="border:1px solid var(--border);border-left:3px solid var(--alert-{a['level']});border-radius:6px;padding:10px;margin-bottom:8px;font-size:12px" class="{'chip-alert-high' if a['level']=='high' else ''}">
            <div style="display:flex;justify-content:space-between;align-items:center">
                <strong>{a['customer']}</strong>
                {alert_chip(a['level'])}
            </div>
            <div style="font-size:10.5px;color:var(--text-tertiary);margin-top:3px">{a['time']} · ¥{fmt_amount(a['amount'])}</div>
            <div style="margin-top:6px">
                {''.join(f'<span class="chip" style="background:#F1F0EA;font-size:10px;padding:2px 6px;margin:1px">{r}</span>' for r in a['rules'])}
            </div>
            <div style="margin-top:6px;display:flex;justify-content:space-between;align-items:center">
                <span style="font-size:10.5px;color:var(--text-tertiary)">置信度</span>
                <span style="font-family:IBM Plex Mono;color:var(--pine);font-weight:600">{a['conf']:.2f}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

def render_analyst_panel():
    """analyst 上下文：最近查询"""
    st.markdown("**最近查询**")
    st.markdown("""
    <div style="border:1px solid var(--border);border-radius:6px;padding:10px;margin-bottom:8px;font-size:12px">
        <div style="font-weight:500">AUM 超 100 万客户数</div>
        <div style="color:var(--text-tertiary);font-size:10.5px;margin-top:2px">2 分钟前 · 23 行</div>
    </div>
    <div style="border:1px solid var(--border);border-radius:6px;padding:10px;margin-bottom:8px;font-size:12px">
        <div style="font-weight:500">本月各产品类型申购额</div>
        <div style="color:var(--text-tertiary);font-size:10.5px;margin-top:2px">15 分钟前 · 6 行</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("**安全说明**")
    st.markdown("""
    <div style="background:#F0F7F4;border:1px solid #C8E6C9;border-radius:6px;padding:10px;font-size:11.5px;color:var(--pine)">
        ✅ 仅允许 SELECT 语句<br>
        ✅ 敏感列已过滤（password/api_key）<br>
        ✅ 单次最多返回 100 行
    </div>
    """, unsafe_allow_html=True)

def render_operator_panel():
    """operator 上下文：操作历史 + 确认阈值"""
    st.markdown("**确认阈值**")
    st.markdown("""
    <div style="background:var(--paper-card);border:1px solid var(--border);border-radius:6px;padding:12px;font-size:12px">
        <div style="margin-bottom:8px"><span class="chip" style="background:#FFF3E0;color:#B98A2F">申购</span> &gt; <strong style="font-family:IBM Plex Mono">¥10,000</strong> 需二次确认</div>
        <div style="margin-bottom:8px"><span class="chip" style="background:#FFF3E0;color:#B98A2F">转账</span> &gt; <strong style="font-family:IBM Plex Mono">¥50,000</strong> 需二次确认</div>
        <div><span class="chip" style="background:#FFF3E0;color:#B98A2F">赎回</span> &gt; <strong style="font-family:IBM Plex Mono">¥10,000</strong> 需二次确认</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("**适当性矩阵**")
    for level, allowed in SUITABILITY.items():
        chips = " ".join(f'<span class="chip chip-risk-{r}">{r}</span>' for r in allowed)
        st.markdown(f"""
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;font-size:12px">
            <span style="width:32px;font-weight:600">{level}</span>
            <span>→</span>
            <span>{chips}</span>
        </div>
        """, unsafe_allow_html=True)

def render_customer_panel():
    """customer 上下文：快捷功能"""
    st.markdown("**常用功能**")
    st.markdown("""
    <div style="border:1px solid var(--border);border-radius:6px;padding:10px;margin-bottom:8px;font-size:12px;cursor:pointer">
        📋 风险评估重做
    </div>
    <div style="border:1px solid var(--border);border-radius:6px;padding:10px;margin-bottom:8px;font-size:12px;cursor:pointer">
        💼 我的持仓查询
    </div>
    <div style="border:1px solid var(--border);border-radius:6px;padding:10px;margin-bottom:8px;font-size:12px;cursor:pointer">
        📞 转人工客服
    </div>
    """, unsafe_allow_html=True)

# ==================== 主流程 ====================

def main():
    # 未登录 → 登录页
    if not st.session_state.authenticated:
        render_login()
        return

    # 侧栏：Agent 切换
    with st.sidebar:
        st.markdown('<div class="brand-mark">智能财富管家<span class="gold">AI</span></div>', unsafe_allow_html=True)
        st.markdown('<div class="brand-sub">PRIVATE BANKING COPILOT</div>', unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("##### Agent 工作台")
        agent_options = list(AGENTS.keys())
        current_idx = agent_options.index(st.session_state.current_agent)
        selected = st.radio(
            "选择 Agent",
            options=agent_options,
            format_func=lambda k: f"{AGENTS[k]['icon']}  {AGENTS[k]['name']}",
            index=current_idx,
            label_visibility="collapsed",
        )
        if selected != st.session_state.current_agent:
            st.session_state.current_agent = selected
            st.rerun()

        st.markdown("---")
        st.markdown("##### 功能")
        if st.button("📈 风控中心"):
            pass  # TODO: navigate
        if st.button("👤 客户画像"):
            pass
        if st.button("📋 工单看板"):
            pass

        st.markdown("---")
        # 用户信息
        user = st.session_state.user or {}
        st.markdown(f"""
        <div style="font-size:11.5px;color:rgba(232,228,216,0.6);padding:8px 0">
            <div style="margin-bottom:4px">● {user.get('username', '')} · {user.get('role', '')}</div>
            <div style="font-family:IBM Plex Mono;font-size:10px;opacity:0.5">trace: {st.session_state.session_id}</div>
        </div>
        """, unsafe_allow_html=True)

        if st.button("退出登录", key="logout"):
            for k in ["authenticated", "user", "token"]:
                st.session_state.pop(k, None)
            st.rerun()

    # 主工作区
    render_workspace()

    # 状态栏
    st.markdown("""
    <div class="status-bar">
        <span><span class="dot"></span>ONLINE</span>
        <span>mock_mode: true</span>
        <span>agent: """ + st.session_state.current_agent + """</span>
        <span style="margin-left:auto">智能财富管家 V1.0.0</span>
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
