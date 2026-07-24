"""
Neo4j 图谱增量同步服务

当 MySQL 数据发生变更（申购/赎回/转账/风评更新等）时，
自动将变更同步到 Neo4j 图谱，无需重新全量导入。

同步粒度：单条记录级别（只同步变化的数据）
同步方式：事件驱动（Redis Pub/Sub 触发）+ 降级补偿（定时全量校验）

负责人: LHG
"""

import json
import logging
from typing import Optional

logger = logging.getLogger("service.graph_sync")

# 同步操作映射
SYNC_ACTIONS = {
    "purchase_product": "_sync_new_transaction",
    "redeem_product": "_sync_new_transaction",
    "transfer_funds": "_sync_new_transaction",
    "redo_assessment": "_sync_customer_risk_level",
    "update_contact": "_sync_customer_profile",
}


async def sync_to_neo4j(action: str, arguments: dict, result: dict) -> None:
    """
    根据操作类型同步到 Neo4j

    Args:
        action: 操作名称（如 purchase_product）
        arguments: 操作参数
        result: 操作结果
    """
    handler_name = SYNC_ACTIONS.get(action)
    if not handler_name:
        logger.debug(f"操作 {action} 无需图谱同步")
        return

    handler = globals().get(handler_name)
    if not handler:
        logger.warning(f"同步处理器 {handler_name} 未找到")
        return

    try:
        await handler(action, arguments, result)
        logger.info(f"图谱增量同步成功: {action}")
    except Exception as e:
        logger.warning(f"图谱增量同步失败: {action} | {e}")


async def _get_neo4j_session():
    """获取 Neo4j session"""
    from app.config.database import get_neo4j_driver
    from app.config.settings import get_settings
    settings = get_settings()
    driver = get_neo4j_driver()
    return driver.session(database=settings.neo4j.database)


async def _sync_new_transaction(action: str, arguments: dict, result: dict) -> None:
    """
    同步新交易到 Neo4j
    触发条件：申购/赎回/转账成功后
    同步内容：Transaction 节点 + MADE/ON_PRODUCT 关系
    """
    customer_id = arguments.get("customer_id") or result.get("data", {}).get("customer_id")
    product_id = arguments.get("product_id") or result.get("data", {}).get("product_id")
    transaction_no = result.get("data", {}).get("transaction_no", "")

    if not all([customer_id, transaction_no]):
        logger.warning(f"交易同步缺少必要参数: customer_id={customer_id}, tx_no={transaction_no}")
        return

    # 从 MySQL 读取完整交易数据
    from sqlalchemy import text
    from app.config.database import async_session_factory

    tx_data = None
    async with async_session_factory() as session:
        tx_result = await session.execute(
            text("SELECT transaction_no, customer_id, product_id, transaction_type, "
                 "amount, shares, nav, fee, status, operator_id, create_time "
                 "FROM fin_transaction WHERE transaction_no = :tx_no"),
            {"tx_no": transaction_no},
        )
        row = tx_result.first()
        if row:
            tx_data = {
                "tx_no": row[0],
                "cid": row[1],
                "pid": row[2],
                "tx_type": row[3] or "",
                "amount": float(row[4]) if row[4] else 0,
                "shares": float(row[5]) if row[5] else 0,
                "nav": float(row[6]) if row[6] else 0,
                "fee": float(row[7]) if row[7] else 0,
                "status": row[8] or "",
                "operator_id": row[9],
                "create_time": str(row[10]) if row[10] else "",
            }

    if not tx_data:
        logger.warning(f"未找到交易记录: {transaction_no}")
        return

    # 写入 Neo4j
    async with await _get_neo4j_session() as neo4j_session:
        # 1. 创建 Transaction 节点
        await neo4j_session.run(
            """
            MERGE (t:Transaction {transaction_no: $tx_no})
            SET t.type = $tx_type, t.amount = $amount,
                t.shares = $shares, t.nav = $nav, t.fee = $fee,
                t.status = $status, t.operator_id = $operator_id,
                t.timestamp = $create_time
            """,
            **tx_data,
        )

        # 2. 创建 MADE 关系（Customer → Transaction）
        await neo4j_session.run(
            """
            MATCH (c:Customer {id: $cid}), (t:Transaction {transaction_no: $tx_no})
            MERGE (c)-[:MADE]->(t)
            """,
            cid=tx_data["cid"], tx_no=tx_data["tx_no"],
        )

        # 3. 创建 ON_PRODUCT 关系（Transaction → Product）
        if tx_data.get("pid"):
            await neo4j_session.run(
                """
                MATCH (t:Transaction {transaction_no: $tx_no}), (p:Product {id: $pid})
                MERGE (t)-[:ON_PRODUCT]->(p)
                """,
                tx_no=tx_data["tx_no"], pid=tx_data["pid"],
            )

        # 4. 如果有经办人，创建 HANDLED_BY 关系
        if tx_data.get("operator_id"):
            await neo4j_session.run(
                """
                MATCH (t:Transaction {transaction_no: $tx_no}), (e:Employee {employee_id: $emp_id})
                MERGE (t)-[:HANDLED_BY]->(e)
                """,
                tx_no=tx_data["tx_no"], emp_id=tx_data["operator_id"],
            )

    logger.info(
        f"交易同步完成: tx_no={tx_data['tx_no']}, type={tx_data['tx_type']}, "
        f"amount={tx_data['amount']}"
    )


async def _sync_customer_risk_level(action: str, arguments: dict, result: dict) -> None:
    """
    同步客户风险等级变更
    触发条件：风评重新评估后
    同步内容：更新 Customer → CustomerRiskLevel 关系
    """
    customer_id = arguments.get("customer_id") or result.get("data", {}).get("customer_id")
    risk_level = result.get("data", {}).get("risk_level", "")

    if not customer_id:
        return

    # 转换风险等级为 C 编码
    if risk_level and risk_level.startswith("R"):
        risk_level = f"C{risk_level[1:]}"
    if not risk_level.startswith("C"):
        risk_level = f"C{risk_level}" if risk_level else "C3"

    async with await _get_neo4j_session() as neo4j_session:
        # 删除旧的风险等级关系，创建新的
        await neo4j_session.run(
            """
            MATCH (c:Customer {id: $cid})-[old:HAS_RISK_LEVEL]->(:CustomerRiskLevel)
            DELETE old
            """,
            cid=customer_id,
        )
        await neo4j_session.run(
            """
            MATCH (c:Customer {id: $cid}), (r:CustomerRiskLevel {level_code: $level})
            MERGE (c)-[:HAS_RISK_LEVEL]->(r)
            """,
            cid=customer_id, level=risk_level,
        )

    logger.info(f"客户风险等级同步: customer_id={customer_id}, level={risk_level}")


async def _sync_customer_profile(action: str, arguments: dict, result: dict) -> None:
    """
    同步客户画像属性变更
    触发条件：联系方式更新后
    同步内容：更新 Customer 节点属性
    """
    customer_id = arguments.get("customer_id")
    field = arguments.get("field", "")
    value = arguments.get("value", "")

    if not customer_id:
        return

    # 映射字段到 Neo4j 属性名
    field_map = {
        "phone": "phone",
        "email": "email",
        "occupation": "occupation",
        "education": "education",
    }
    neo4j_field = field_map.get(field)
    if not neo4j_field:
        return

    async with await _get_neo4j_session() as neo4j_session:
        await neo4j_session.run(
            f"MATCH (c:Customer {{id: $cid}}) SET c.{neo4j_field} = $value",
            cid=customer_id, value=value,
        )

    logger.info(f"客户属性同步: customer_id={customer_id}, {neo4j_field}={value}")


async def sync_holdings(customer_id: Optional[int] = None) -> None:
    """
    全量/单客户持仓同步（补偿用）
    当 INVESTS_IN 关系可能不一致时调用
    """
    from sqlalchemy import text
    from app.config.database import async_session_factory

    query = "SELECT customer_id, product_id, shares, cost_amount, current_value, profit_loss, profit_ratio FROM fin_holdings WHERE status = '持有中'"
    params = {}
    if customer_id:
        query += " AND customer_id = :cid"
        params["cid"] = customer_id

    async with async_session_factory() as session:
        result = await session.execute(text(query), params)
        holdings = result.fetchall()

    holdings_data = [
        {
            "cid": row[0], "pid": row[1],
            "shares": float(row[2] or 0), "cost": float(row[3] or 0),
            "value": float(row[4] or 0), "pl": float(row[5] or 0),
            "ratio": float(row[6] or 0),
        }
        for row in holdings
    ]

    if not holdings_data:
        return

    async with await _get_neo4j_session() as neo4j_session:
        await neo4j_session.run(
            """
            UNWIND $holdings AS h
            MATCH (c:Customer {id: h.cid}), (p:Product {id: h.pid})
            MERGE (c)-[inv:INVESTS_IN]->(p)
            SET inv.shares = h.shares, inv.cost_amount = h.cost,
                inv.current_value = h.value, inv.profit_loss = h.pl,
                inv.profit_ratio = h.ratio
            """,
            holdings=holdings_data,
        )

    logger.info(f"持仓同步完成: {len(holdings_data)} 条")


async def sync_customer_relations() -> None:
    """
    重新计算 Customer 间 RELATED_TO 关系（补偿用）
    基于共同持仓重新建立关联
    """
    async with await _get_neo4j_session() as neo4j_session:
        # 先删除旧的 RELATED_TO 关系
        await neo4j_session.run("MATCH ()-[r:RELATED_TO]->() DELETE r")
        # 重新创建
        await neo4j_session.run(
            """
            MATCH (c1:Customer)-[:INVESTS_IN]->(p:Product)<-[:INVESTS_IN]-(c2:Customer)
            WHERE c1.id < c2.id
            WITH c1, c2, COUNT(p) AS common_products, COLLECT(p.name) AS product_names
            WHERE common_products >= 1
            MERGE (c1)-[r:RELATED_TO]->(c2)
            SET r.relation_type = '共同持仓', r.strength = common_products,
                r.detected_at = datetime(), r.product_names = product_names
            """
        )
    logger.info("Customer 间关联关系重新计算完成")
