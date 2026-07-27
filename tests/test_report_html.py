from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPORTS = {
    "index.html": "金融多 Agent 智能财富管理平台",
    "00-总体汇报.html": "总体汇报",
    "01-投顾Agent汇报.html": "投顾 Agent",
    "02-客服Agent汇报.html": "客服 Agent",
    "03-风控Agent汇报.html": "风控 Agent",
    "04-业务操作Agent汇报.html": "业务操作 Agent",
    "05-数据分析Agent汇报.html": "数据分析 Agent",
    "06-多Agent联动与架构汇报.html": "多 Agent 联动",
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
                if filename != "index.html":
                    self.assertIn("index.html", html)
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
        self.assertGreaterEqual(text.count('class="flow-diagram"'), 17)
        self.assertIn("Event Bus", text)
        self.assertIn("Memory Manager", text)

    def test_reports_include_team_and_requirement_driven_value(self):
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("offer收割机", index)
        for member in ("李惠涛", "林罗英", "刘嘉威", "李嘉兵", "李华桂", "谢伟杰"):
            self.assertIn(member, index)
        self.assertIn("项目背景", index)
        self.assertIn("项目目标", index)
        for filename in REPORTS:
            if filename != "index.html":
                self.assertIn("需求映射", (ROOT / filename).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
