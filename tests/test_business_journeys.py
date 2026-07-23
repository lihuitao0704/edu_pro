"""Opt-in live journeys against a running FastAPI/MySQL/Redis environment.

Run with:
  RUN_LIVE_E2E=1 E2E_BASE_URL=http://127.0.0.1:8000 \
    python -m unittest tests.test_business_journeys -v
"""

import json
import os
import time
import unittest
import urllib.error
import urllib.request


LIVE = os.getenv("RUN_LIVE_E2E") == "1"
BASE_URL = os.getenv("E2E_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def api(path: str, *, token: str = "", method: str = "GET", body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def login(username: str) -> tuple[str, dict]:
    status, payload = api(
        "/api/auth/login",
        method="POST",
        body={"username": username, "password": "Demo@123"},
    )
    if status != 200 or payload["code"] != 200:
        raise AssertionError(payload)
    return payload["data"]["access_token"], payload["data"]["user"]


@unittest.skipUnless(LIVE, "set RUN_LIVE_E2E=1 to run live business journeys")
class LiveBusinessJourneys(unittest.TestCase):
    def test_retail_customer_profile_and_role_isolation(self):
        token, user = login("demo_customer_01")
        status, profile = api(
            f"/api/profile/{user['user_id']}",
            token=token,
        )
        self.assertEqual(200, status)
        self.assertEqual(user["user_id"], profile["data"]["customer_id"])

        forbidden_status, _ = api("/api/risk/alerts", token=token)
        self.assertEqual(403, forbidden_status)

        chat_status, _ = api(
            "/api/chat/customer",
            token=token,
            method="POST",
            body={
                "session_id": "scope-check",
                "message": "查询画像",
                "user_id": user["user_id"] + 1,
            },
        )
        advisor_status, _ = api(
            "/api/chat/advisor",
            token=token,
            method="POST",
            body={
                "session_id": "scope-check",
                "message": "生成建议",
                "user_id": user["user_id"],
                "customer_id": user["user_id"] + 1,
            },
        )
        self.assertEqual(403, chat_status)
        self.assertEqual(403, advisor_status)

    def test_advisor_customer_and_holding_flow(self):
        token, _ = login("demo_advisor")
        status, customers = api("/api/customers?page_size=5", token=token)
        self.assertEqual(200, status)
        self.assertTrue(customers["data"]["items"])

        customer_id = customers["data"]["items"][0]["customer_id"]
        holding_status, holdings = api(
            f"/api/customers/{customer_id}/holdings",
            token=token,
        )
        self.assertEqual(200, holding_status)
        self.assertIn("items", holdings["data"])

    def test_risk_alert_and_work_order_flow(self):
        token, _ = login("demo_risk")
        _, customer = login("demo_customer_01")
        transaction_id = f"E2E-RISK-{int(time.time() * 1000)}"
        monitor_status, monitor = api(
            "/api/risk/monitor",
            token=token,
            method="POST",
            body={
                "customer_id": customer["user_id"],
                "transaction_id": transaction_id,
                "amount": 500000,
                "transaction_type": "cash",
                "timestamp": "2026-07-23T22:30:00",
                "annual_income": 100000,
                "daily_amount": 500000,
                "weekly_count": 25,
                "weekly_total": 500000,
                "account_age_days": 10,
                "investor_account": str(customer["user_id"]),
                "counterparty": {"account": "THIRD-PARTY-E2E"},
            },
        )
        self.assertEqual(200, monitor_status)
        alert = monitor["data"]["alert"]
        self.assertIsNotNone(alert)
        self.assertIn(alert["alert_level"], {"medium", "high"})
        alert_id = str(alert["alert_id"])

        order_status, workorders = api(
            "/api/operation/workorders?page_size=100",
            token=token,
        )
        self.assertEqual(200, order_status)
        linked_order = None
        for order in workorders["data"]["items"]:
            content = order.get("biz_content") or {}
            if isinstance(content, str):
                content = json.loads(content)
            if str(content.get("alert_id")) == alert_id:
                linked_order = order
                break
        self.assertIsNotNone(linked_order)

        close_status, _ = api(
            f"/api/operation/workorder/{linked_order['id']}/handle",
            token=token,
            method="PUT",
            body={
                "status": "已完成",
                "handler_id": 999999,
                "handle_note": "E2E 核实完成",
            },
        )
        self.assertEqual(200, close_status)

        detail_status, detail = api(f"/api/risk/alert/{alert_id}", token=token)
        self.assertEqual(200, detail_status)
        self.assertEqual("resolved", detail["data"]["status"])

        from redis import Redis
        from app.config.settings import get_settings

        redis_settings = get_settings().redis
        redis_client = Redis(
            host=redis_settings.host,
            port=redis_settings.port,
            password=redis_settings.password or None,
            db=redis_settings.db,
            decode_responses=True,
        )
        self.assertFalse(redis_client.sismember("risk:alert:pending", alert_id))


if __name__ == "__main__":
    unittest.main()
