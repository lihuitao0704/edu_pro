from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPORT_CHAIN = [
    "00-index.html",
    "00-总体汇报.html",
    "01-投顾Agent汇报.html",
    "02-客服Agent汇报.html",
    "03-风控Agent汇报.html",
    "04-业务操作Agent汇报.html",
    "05-数据分析Agent汇报.html",
    "06-多Agent联动与架构汇报.html",
    "07-记忆架构汇报.html",
]
REPORTS = {
    "00-index.html": "金融多 Agent 智能财富管理平台",
    "00-总体汇报.html": "总体汇报",
    "01-投顾Agent汇报.html": "投顾 Agent",
    "02-客服Agent汇报.html": "客服 Agent",
    "03-风控Agent汇报.html": "风控 Agent",
    "04-业务操作Agent汇报.html": "业务操作 Agent",
    "05-数据分析Agent汇报.html": "数据分析 Agent",
    "06-多Agent联动与架构汇报.html": "多 Agent 联动",
    "07-记忆架构汇报.html": "记忆架构",
}


class ReportHtmlTest(unittest.TestCase):
    def test_report_set_has_titles_navigation_and_flow_diagrams(self):
        for filename, expected_title in REPORTS.items():
            with self.subTest(filename=filename):
                page = ROOT / filename
                self.assertTrue(page.is_file(), f"missing report: {filename}")
                html = page.read_text(encoding="utf-8")
                self.assertIn('<meta charset="UTF-8">', html)
                self.assertIn(expected_title, html)
                self.assertIn('class="flow-diagram"', html)
                self.assertNotIn("https://", html)
                self.assertNotIn("http://", html)

    def test_each_specialist_page_has_its_real_process_anchor(self):
        anchors = {
            "01-投顾Agent汇报.html": "GraphRAG",
            "02-客服Agent汇报.html": "情绪",
            "03-风控Agent汇报.html": "事前",
            "04-业务操作Agent汇报.html": "二次确认",
            "05-数据分析Agent汇报.html": "SELECT",
            "06-多Agent联动与架构汇报.html": "Outbox",
        }
        for filename, anchor in anchors.items():
            with self.subTest(filename=filename):
                html = (ROOT / filename).read_text(encoding="utf-8")
                self.assertIn(anchor, html)

    def test_report_navigation_is_a_single_previous_next_chain(self):
        for index, filename in enumerate(REPORT_CHAIN[1:], start=1):
            with self.subTest(filename=filename):
                html = (ROOT / filename).read_text(encoding="utf-8")
                previous = REPORT_CHAIN[index - 1]
                following = REPORT_CHAIN[index + 1] if index < len(REPORT_CHAIN) - 1 else REPORT_CHAIN[0]
                self.assertIn(f'<a href="{previous}">上一页</a>', html)
                self.assertIn(f'<a href="{following}">下一页</a>', html)
                nav = html.split('<nav class="nav">', 1)[1].split('</nav>', 1)[0]
                self.assertEqual(nav.count('<a href='), 2)

    def test_report_pages_do_not_reference_replaced_filenames(self):
        for filename in REPORT_CHAIN:
            with self.subTest(filename=filename):
                html = (ROOT / filename).read_text(encoding="utf-8")
                self.assertNotIn('href="index.html"', html)
                self.assertNotIn('href="记忆架构.html"', html)

    def test_reports_have_distinct_defense_narratives(self):
        anchors = {
            "00-总体汇报.html": ("核心结论", "统一路由"),
            "01-投顾Agent汇报.html": ("策略找人", "smart_recommend"),
            "02-客服Agent汇报.html": ("有依据的回答", "转人工"),
            "03-风控Agent汇报.html": ("风险闭环", "正式风险评级"),
            "04-业务操作Agent汇报.html": ("受控业务动作", "P0-P5"),
            "05-数据分析Agent汇报.html": ("受控的自然语言分析", "洞察白名单"),
            "06-多Agent联动与架构汇报.html": ("可靠协作", "Outbox"),
            "07-记忆架构汇报.html": ("不混淆事实", "业务事实源"),
        }
        for filename, expected in anchors.items():
            with self.subTest(filename=filename):
                html = (ROOT / filename).read_text(encoding="utf-8")
                for anchor in expected:
                    self.assertIn(anchor, html)
                self.assertNotIn("我会这样讲", html)

    def test_advisor_report_explains_defense_value_and_profile_guardrail(self):
        text = (ROOT / "01-投顾Agent汇报.html").read_text(encoding="utf-8")
        for anchor in (
            "从“人找策略”到“策略找人”",
            "千人千面",
            "顶级投资经理",
            "画像缺失 / 风评过期",
            "风险测评提醒弹窗",
            "低风险产品",
        ):
            self.assertIn(anchor, text)

    def test_advisor_page_covers_full_flow_and_engineering_enhancements(self):
        html = (ROOT / "01-投顾Agent汇报.html").read_text(encoding="utf-8")
        for anchor in (
            "完整投顾流程架构",
            "七工具",
            "客户身份校验",
            "风险画像与动态约束",
            "产品推荐与资产配置",
            "业务操作 Agent",
            "Outbox",
            "Redis Pub/Sub",
            "需求文档中的基础能力",
            "当前工程增强",
            "预算分配",
            "SSE 工具进度",
            "不直接执行交易",
            "不修改正式风险评级",
        ):
            self.assertIn(anchor, html)
        self.assertGreaterEqual(html.count('class="flow-diagram"'), 3)

    def test_personal_defense_artifacts_cover_analytics_and_architecture(self):
        report = (ROOT / "05-数据分析Agent汇报.html").read_text(encoding="utf-8")
        for anchor in (
            "本人负责范围",
            "NL2SQL",
            "五道安全闸门",
            "BI 仪表盘",
            "6 个业务指标",
            "分析洞察白名单",
            "事务 Outbox",
            "Chat Orchestrator",
            "需求文档",
        ):
            self.assertIn(anchor, report)
        script = ROOT / "答辩稿.md"
        self.assertTrue(script.is_file())
        script_text = script.read_text(encoding="utf-8")
        self.assertIn("各位评委老师", script_text)
        self.assertIn("数据分析 Agent", script_text)
        self.assertIn("总体框架优化", script_text)
        self.assertFalse((ROOT / "数据分析.html").exists())

    def test_multi_agent_architecture_embeds_financial_process_design(self):
        text = (ROOT / "06-多Agent联动与架构汇报.html").read_text(encoding="utf-8")
        for number, title in enumerate((
            "用户发起交易", "大额转账风险审核", "风控发现风险，驱动投顾调整策略",
            "投顾推荐产品，风控审核", "投顾执行购买", "交易行为更新用户画像",
            "数据分析发现异常交易", "数据分析优化投资组合", "市场事件广播",
            "用户画像变化驱动投顾调整", "客服识别用户情绪", "合规销售审核",
            "账户安全保护", "客户投诉闭环",
        ), start=1):
            self.assertIn(f"场景{number}：{title}", text)
        self.assertGreaterEqual(text.count('flow-diagram'), 15)
        self.assertIn("Event Bus", text)
        self.assertIn("Memory Manager", text)
        self.assertNotIn("闭环一：", text)
        self.assertNotIn("闭环二：", text)
        self.assertIn('src="report-assets/financial-ai-architecture.png"', text)
        self.assertTrue((ROOT / "report-assets" / "financial-ai-architecture.png").is_file())

    def test_reports_include_team_and_requirement_driven_value(self):
        index = (ROOT / "00-index.html").read_text(encoding="utf-8")
        self.assertIn("offer收割机", index)
        for member in ("李惠涛", "林罗英", "刘嘉威", "李嘉兵", "李华桂", "谢伟杰"):
            self.assertIn(member, index)
        self.assertIn("项目背景", index)
        self.assertIn("项目目标", index)
        for filename in REPORTS:
            if filename != "00-index.html":
                self.assertIn("需求映射", (ROOT / filename).read_text(encoding="utf-8"))

    def test_memory_architecture_is_code_aligned_and_governed(self):
        text = (ROOT / "07-记忆架构汇报.html").read_text(encoding="utf-8")
        for anchor in (
            "chat:v2:{actor_id}:{session_id}:messages",
            "chat:v2:{actor_id}:{session_id}:context",
            "profile:{customer_id}",
            "MySQL 事务 Outbox + Redis Pub/Sub",
            "MinIO",
            "Milvus",
            "Neo4j",
            "Memory Manager",
            "不作为正式风险等级",
            "已实现",
            "建议补强",
            "Mermaid 风格路径图",
            "事件写入闭环",
        ):
            self.assertIn(anchor, text)
        self.assertGreaterEqual(text.count('class="memory-mermaid"'), 2)
        self.assertNotIn("严格结论", text)
        self.assertNotIn("当前实现为 <b>MySQL 事务 Outbox", text)
        self.assertNotIn("Redis Stream / Kafka", text)

    def test_memory_animation_page_has_two_routes_and_player_controls(self):
        page = ROOT / "记忆架构-动画流程图.html"
        self.assertTrue(page.is_file())
        html = page.read_text(encoding="utf-8")
        for anchor in (
            "读取路径", "写入路径", "播放", "暂停", "上一步", "下一步", "重播",
            "Redis", "MySQL", "Milvus", "MinIO", "Neo4j", "业务事实源",
            "Memory Manager", "Outbox", "Redis Pub/Sub", "prefers-reduced-motion",
            "不修改正式 C1-C5 风险评级",
        ):
            self.assertIn(anchor, html)
        self.assertIn("readSteps", html)
        self.assertIn("writeSteps", html)
        self.assertIn("<svg", html)

    def test_portfolio_recommendation_animation_page_has_complete_flow(self):
        page = ROOT / "持仓收益与产品推荐-动画流程图.html"
        self.assertTrue(page.is_file())
        html = page.read_text(encoding="utf-8")
        for anchor in (
            "持仓收益率", "高收益产品", "HoldingTool", "RecommendationTool",
            "ProfileAgent", "RiskMonitor", "OutputSafetyFilter", "SSE",
            "Outbox", "Redis Pub/Sub", "MySQL", "Redis", "Milvus", "MinIO", "Neo4j",
            "适当性", "历史业绩不代表未来", "不自动改变正式 C1-C5 风险等级",
            "播放", "暂停", "上一步", "下一步", "重播", "prefers-reduced-motion",
        ):
            self.assertIn(anchor, html)
        self.assertIn("const steps = [", html)
        self.assertIn("steps.length", html)
        self.assertIn("<svg", html)

    def test_portfolio_animation_connects_entry_parallel_fanout_and_closure(self):
        html = (ROOT / "持仓收益与产品推荐-动画流程图.html").read_text(encoding="utf-8")
        for anchor in (
            'id="e1" class="edge" d="M220 104V203H302"',
            'id="e2" class="edge" d="M472 203H565"',
            "并行读取 / 汇聚",
            'id="e9" class="edge parallel" d="M650 482V425H1075V449"',
            'id="e10" class="edge parallel" d="M650 482V405H1330V449"',
            'id="e22" class="edge feedback" d="M1415 944V1060H40V343H70"',
        ):
            self.assertIn(anchor, html)


if __name__ == "__main__":
    unittest.main()
