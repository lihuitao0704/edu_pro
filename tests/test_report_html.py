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


if __name__ == "__main__":
    unittest.main()
