import unittest
from collections import Counter


class DemoSeedTests(unittest.TestCase):
    def test_customer_dataset_covers_roles_and_risk_segments(self):
        from scripts.seed_demo_data import build_customers

        customers = build_customers()
        segments = {customer["segment"] for customer in customers}
        levels = {customer["risk_level"] for customer in customers}

        self.assertGreaterEqual(len(customers), 20)
        self.assertTrue({"普通投资者", "稳健投资者", "激进投资者", "高净值客户"}.issubset(segments))
        self.assertTrue({"保守型", "稳健型", "平衡型", "进取型", "激进型"}.issubset(levels))

    def test_product_dataset_has_30_products_and_required_categories(self):
        from scripts.seed_demo_data import build_products

        products = build_products()
        categories = {product["product_type"] for product in products}
        levels = {product["risk_level"] for product in products}

        self.assertGreaterEqual(len(products), 30)
        self.assertTrue({"基金", "债券", "理财产品"}.issubset(categories))
        self.assertEqual({"R1", "R2", "R3", "R4", "R5"}, levels)
        self.assertTrue(all(product["industry"] for product in products))

    def test_transaction_dataset_contains_all_risk_scenarios(self):
        from scripts.seed_demo_data import build_transactions

        transactions = build_transactions()
        counts = Counter(item["scenario"] for item in transactions)

        for scenario in ("正常交易", "大额交易", "高频交易", "异常交易"):
            self.assertGreater(counts[scenario], 0)

    def test_each_demo_customer_has_holdings(self):
        from scripts.seed_demo_data import build_holdings

        holdings = build_holdings()
        customer_counts = Counter(item["customer_username"] for item in holdings)

        self.assertEqual(20, len(customer_counts))
        self.assertTrue(all(count >= 2 for count in customer_counts.values()))

    def test_five_login_roles_are_available(self):
        from scripts.seed_demo_data import build_test_accounts

        roles = {account["role"] for account in build_test_accounts()}
        self.assertEqual({"客户", "理财顾问", "客户经理", "风控专员", "管理员"}, roles)


if __name__ == "__main__":
    unittest.main()
