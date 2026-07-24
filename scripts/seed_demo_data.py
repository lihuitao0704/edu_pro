"""Deterministic financial demo dataset.

Run without arguments to print a summary. Use ``--apply`` to idempotently
upsert the records into the configured MySQL database.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.settings import get_settings
from app.security.passwords import hash_password


SEGMENTS = (
    ("普通投资者", "保守型", "C1"),
    ("稳健投资者", "稳健型", "C2"),
    ("普通投资者", "平衡型", "C3"),
    ("激进投资者", "进取型", "C4"),
    ("高净值客户", "激进型", "C5"),
)


def build_customers() -> list[dict]:
    occupations = ["教师", "工程师", "医生", "企业管理者", "创业者"]
    experiences = ["1年以下", "1-3年", "3-5年", "5-10年", "10年以上"]
    customers = []
    for index in range(1, 21):
        segment, risk_level, assessment_level = SEGMENTS[(index - 1) % len(SEGMENTS)]
        assets = 300_000 + index * 70_000
        if segment == "高净值客户":
            assets = 6_000_000 + index * 300_000
        customers.append(
            {
                "username": f"demo_customer_{index:02d}",
                "real_name": f"演示客户{index:02d}",
                "phone": f"1390000{index:04d}",
                "age": 24 + index * 2,
                "occupation": occupations[(index - 1) % len(occupations)],
                "annual_income_range": ["10-30万", "30-50万", "50-100万", "100-300万"][(index - 1) % 4],
                "total_assets": assets,
                "risk_level": risk_level,
                "assessment_level": assessment_level,
                "risk_score": 18 + ((index - 1) % 5) * 18,
                "investment_experience": experiences[(index - 1) % len(experiences)],
                "segment": segment,
                "holdings": [f"DEMO-P{((index - 1) % 30) + 1:03d}", f"DEMO-P{(index % 30) + 1:03d}"],
            }
        )
    return customers


def build_products() -> list[dict]:
    categories = ("基金", "债券", "理财产品")
    industries = ("现金管理", "政金债", "科技", "新能源", "医药", "消费")
    products = []
    for index in range(1, 31):
        category = categories[(index - 1) % len(categories)]
        risk = f"R{((index - 1) % 5) + 1}"
        products.append(
            {
                "product_code": f"DEMO-P{index:03d}",
                "product_name": f"演示{category}{index:02d}号",
                "product_type": category,
                "risk_level": risk,
                "expected_return": round(1.8 + index * 0.42, 2),
                "term_days": (30, 90, 180, 365, 730)[(index - 1) % 5],
                "industry": industries[(index - 1) % len(industries)],
                "min_amount": (100, 1000, 10_000)[(index - 1) % 3],
            }
        )
    return products


def build_transactions() -> list[dict]:
    rows = []
    for index in range(1, 21):
        rows.append(
            {
                "transaction_no": f"DEMO-NORMAL-{index:03d}",
                "customer_username": f"demo_customer_{((index - 1) % 20) + 1:02d}",
                "product_code": f"DEMO-P{((index - 1) % 30) + 1:03d}",
                "transaction_type": "purchase",
                "amount": 1_000 + index * 200,
                "scenario": "正常交易",
                "days_ago": 40 - index,
            }
        )
    rows.append(
        {
            "transaction_no": "DEMO-LARGE-001",
            "customer_username": "demo_customer_20",
            "product_code": "DEMO-P020",
            "transaction_type": "cash",
            "amount": 800_000,
            "scenario": "大额交易",
            "days_ago": 1,
        }
    )
    for index in range(1, 26):
        rows.append(
            {
                "transaction_no": f"DEMO-FREQ-{index:03d}",
                "customer_username": "demo_customer_14",
                "product_code": f"DEMO-P{((index - 1) % 5) + 1:03d}",
                "transaction_type": "purchase" if index % 2 else "redeem",
                "amount": 5_000,
                "scenario": "高频交易",
                "days_ago": index % 7,
            }
        )
    abnormal = (
        ("DEMO-ABNORMAL-001", "cash", 199_999),
        ("DEMO-ABNORMAL-002", "transfer_out", 300_000),
        ("DEMO-ABNORMAL-003", "redeem", 150_000),
        ("DEMO-ABNORMAL-004", "transfer_out", 499_999),
    )
    for index, (number, tx_type, amount) in enumerate(abnormal, start=1):
        rows.append(
            {
                "transaction_no": number,
                "customer_username": f"demo_customer_{15 + index:02d}",
                "product_code": f"DEMO-P{20 + index:03d}",
                "transaction_type": tx_type,
                "amount": amount,
                "scenario": "异常交易",
                "days_ago": 0,
            }
        )
    return rows


def build_holdings() -> list[dict]:
    holdings = []
    for customer in build_customers():
        for position, product_code in enumerate(customer["holdings"], start=1):
            amount = 20_000 + customer["risk_score"] * 500 + position * 5_000
            holdings.append(
                {
                    "customer_username": customer["username"],
                    "product_code": product_code,
                    "shares": float(amount),
                    "cost_amount": float(amount),
                    "current_value": round(amount * (1.01 + position * 0.015), 2),
                    "status": "持有中",
                }
            )
    return holdings


def build_test_accounts() -> list[dict]:
    return [
        {"username": "demo_customer_01", "real_name": "演示客户01", "role": "客户", "user_type": "CUSTOMER"},
        {"username": "demo_advisor", "real_name": "演示理财顾问", "role": "理财顾问", "user_type": "EMPLOYEE"},
        {"username": "demo_manager", "real_name": "演示客户经理", "role": "客户经理", "user_type": "EMPLOYEE"},
        {"username": "demo_risk", "real_name": "演示风控专员", "role": "风控专员", "user_type": "EMPLOYEE"},
        {"username": "demo_admin", "real_name": "演示管理员", "role": "管理员", "user_type": "EMPLOYEE"},
    ]


def apply_dataset() -> None:
    import pymysql

    settings = get_settings()
    connection = pymysql.connect(
        host=settings.mysql.host,
        port=settings.mysql.port,
        user=settings.mysql.user,
        password=settings.mysql.password,
        database=settings.mysql.database,
        charset="utf8mb4",
        autocommit=False,
    )
    password_hash = hash_password("Demo@123")
    try:
        with connection.cursor() as cursor:
            # ── 先插入20个演示客户（ID 1-20），确保"演示客户NN"的ID就是NN ──
            for customer in build_customers():
                cursor.execute(
                    """
                    INSERT INTO sys_user
                    (username,password_hash,user_type,employee_role,customer_level,
                     real_name,phone,age,occupation,status,balance,create_time,update_time)
                    VALUES (%s,%s,'CUSTOMER',NULL,%s,%s,%s,%s,%s,'正常',1000000,NOW(),NOW())
                    ON DUPLICATE KEY UPDATE real_name=VALUES(real_name), phone=VALUES(phone),
                      age=VALUES(age), occupation=VALUES(occupation), update_time=NOW()
                    """,
                    (
                        customer["username"],
                        password_hash,
                        "私行" if customer["segment"] == "高净值客户" else "普通",
                        customer["real_name"],
                        customer["phone"],
                        customer["age"],
                        customer["occupation"],
                    ),
                )
                cursor.execute("SELECT id FROM sys_user WHERE username=%s", (customer["username"],))
                customer_id = cursor.fetchone()[0]
                cursor.execute(
                    """
                    INSERT INTO fin_customer_profile
                    (customer_id,risk_level,risk_score,investment_experience,
                     annual_income_range,total_assets,confidence_score,risk_flag,
                     profile_json,create_time,update_time)
                    VALUES (%s,%s,%s,%s,%s,%s,0.85,'normal',%s,NOW(),NOW())
                    ON DUPLICATE KEY UPDATE risk_level=VALUES(risk_level),
                      risk_score=VALUES(risk_score), investment_experience=VALUES(investment_experience),
                      annual_income_range=VALUES(annual_income_range), total_assets=VALUES(total_assets),
                      confidence_score=0.85, profile_json=VALUES(profile_json), update_time=NOW()
                    """,
                    (
                        customer_id,
                        customer["risk_level"],
                        customer["risk_score"],
                        customer["investment_experience"],
                        customer["annual_income_range"],
                        customer["total_assets"],
                        json.dumps({"segment": customer["segment"]}, ensure_ascii=False),
                    ),
                )
                cursor.execute(
                    "DELETE FROM fin_risk_assessment WHERE customer_id=%s AND assessor_type='DEMO'",
                    (customer_id,),
                )
                cursor.execute(
                    """
                    INSERT INTO fin_risk_assessment
                    (customer_id,assessment_date,total_score,risk_level,answers,
                     assessor_type,valid_until,create_time)
                    VALUES (%s,CURDATE(),%s,%s,%s,'DEMO',DATE_ADD(CURDATE(),INTERVAL 1 YEAR),NOW())
                    """,
                    (
                        customer_id,
                        customer["risk_score"],
                        customer["assessment_level"],
                        json.dumps({"details": [{"q": 4, "a": "C"}]}, ensure_ascii=False),
                    ),
                )

            # ── 再插入角色账号（ID 21+），避免占用演示客户的ID空间 ──
            for account in build_test_accounts():
                # demo_customer_01 已在上面插入，跳过重复
                if account["username"] == "demo_customer_01":
                    continue
                cursor.execute(
                    """
                    INSERT INTO sys_user
                    (username,password_hash,user_type,employee_role,customer_level,
                     real_name,status,balance,create_time,update_time)
                    VALUES (%s,%s,%s,%s,%s,%s,'正常',1000000,NOW(),NOW())
                    ON DUPLICATE KEY UPDATE password_hash=VALUES(password_hash),
                      user_type=VALUES(user_type), employee_role=VALUES(employee_role),
                      real_name=VALUES(real_name), status='正常', update_time=NOW()
                    """,
                    (
                        account["username"],
                        password_hash,
                        account["user_type"],
                        None if account["role"] == "客户" else account["role"],
                        "普通" if account["role"] == "客户" else None,
                        account["real_name"],
                    ),
                )

            for product in build_products():
                cursor.execute(
                    """
                    INSERT INTO fin_product
                    (product_code,product_name,product_type,risk_level,expected_return,
                     min_amount,term_days,industry,status,create_time,update_time)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'在售',NOW(),NOW())
                    ON DUPLICATE KEY UPDATE product_name=VALUES(product_name),
                      product_type=VALUES(product_type),risk_level=VALUES(risk_level),
                      expected_return=VALUES(expected_return),min_amount=VALUES(min_amount),
                      term_days=VALUES(term_days),industry=VALUES(industry),status='在售',
                      update_time=NOW()
                    """,
                    (
                        product["product_code"],
                        product["product_name"],
                        product["product_type"],
                        product["risk_level"],
                        product["expected_return"],
                        product["min_amount"],
                        product["term_days"],
                        product["industry"],
                    ),
                )

            cursor.execute(
                """
                DELETE h FROM fin_holdings h
                JOIN sys_user u ON u.id = h.customer_id
                JOIN fin_product p ON p.id = h.product_id
                WHERE u.username LIKE 'demo_customer_%%'
                  AND p.product_code LIKE 'DEMO-P%%'
                """
            )
            for holding in build_holdings():
                cursor.execute(
                    "SELECT id FROM sys_user WHERE username=%s",
                    (holding["customer_username"],),
                )
                customer_id = cursor.fetchone()[0]
                cursor.execute(
                    "SELECT id FROM fin_product WHERE product_code=%s",
                    (holding["product_code"],),
                )
                product_id = cursor.fetchone()[0]
                cursor.execute(
                    """
                    INSERT INTO fin_holdings
                    (customer_id,product_id,shares,cost_amount,current_value,
                     profit_loss,profit_ratio,status,create_time,update_time)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())
                    """,
                    (
                        customer_id,
                        product_id,
                        holding["shares"],
                        holding["cost_amount"],
                        holding["current_value"],
                        holding["current_value"] - holding["cost_amount"],
                        holding["current_value"] / holding["cost_amount"] - 1,
                        holding["status"],
                    ),
                )

            for transaction in build_transactions():
                cursor.execute("SELECT id FROM sys_user WHERE username=%s", (transaction["customer_username"],))
                customer_id = cursor.fetchone()[0]
                cursor.execute("SELECT id FROM fin_product WHERE product_code=%s", (transaction["product_code"],))
                product_id = cursor.fetchone()[0]
                created = datetime.now() - timedelta(days=transaction["days_ago"])
                cursor.execute(
                    """
                    INSERT INTO fin_transaction
                    (transaction_no,customer_id,product_id,transaction_type,amount,
                     status,remark,create_time,update_time)
                    VALUES (%s,%s,%s,%s,%s,'已确认',%s,%s,%s)
                    ON DUPLICATE KEY UPDATE amount=VALUES(amount),
                      transaction_type=VALUES(transaction_type),remark=VALUES(remark),
                      create_time=VALUES(create_time),update_time=VALUES(update_time)
                    """,
                    (
                        transaction["transaction_no"],
                        customer_id,
                        product_id,
                        transaction["transaction_type"],
                        transaction["amount"],
                        transaction["scenario"],
                        created,
                        created,
                    ),
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        apply_dataset()
        print("演示数据已写入：20个客户、30个产品、50笔场景交易、5类角色账号")
    else:
        print(
            json.dumps(
                {
                    "customers": len(build_customers()),
                    "products": len(build_products()),
                    "holdings": len(build_holdings()),
                    "transactions": len(build_transactions()),
                    "accounts": len(build_test_accounts()),
                    "password": "Demo@123",
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
