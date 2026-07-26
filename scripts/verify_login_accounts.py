"""Read-only login smoke test for the current acceptance account matrix."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


ACCOUNTS = {
    "客户": "user_0001",
    "理财顾问": "emp_001",
    "风控专员": "emp_007",
    "客户经理": "emp_012",
    "管理员": "emp_017",
}


def verify_login(base_url: str, username: str, expected_role: str, password: str) -> tuple[bool, str]:
    payload = json.dumps({"username": username, "password": password}).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/auth/login",
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return False, f"请求失败: {exc}"

    user = ((body.get("data") or {}).get("user") or {})
    if body.get("code") != 200:
        return False, body.get("message") or "登录失败"
    if user.get("username") != username:
        return False, f"返回账号不一致: {user.get('username')}"
    if user.get("role") != expected_role:
        return False, f"返回角色不一致: {user.get('role')}"
    return True, f"user_id={user.get('user_id')}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8003")
    parser.add_argument("--password", default="Demo@123")
    args = parser.parse_args()

    failed = 0
    for expected_role, username in ACCOUNTS.items():
        ok, detail = verify_login(args.base_url, username, expected_role, args.password)
        print(f"[{'PASS' if ok else 'FAIL'}] {expected_role:<6} {username:<10} {detail}")
        failed += int(not ok)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
