"""
知识图谱管理与可视化接口
负责人: LHG
"""

from fastapi import APIRouter, Depends, HTTPException
from app.tool.neo4j_client import Neo4jClient
from app.tool import graph_query_tool
from app.security.authorization import require_roles

router = APIRouter(dependencies=[Depends(require_roles("理财顾问", "管理员"))])
neo4j = Neo4jClient()


@router.get("/stats")
async def graph_stats():
    """图谱统计：节点数量、关系数量"""
    stats = await neo4j.get_stats()
    return {"code": 200, "message": "成功", "data": stats}


@router.get("/visualization/{customer_id}")
async def graph_visualization(customer_id: int):
    """
    获取客户关联图谱的可视化数据（节点 + 边 JSON）
    用于前端渲染 D3/ECharts 图谱
    """
    nodes = []
    edges = []
    node_ids = set()

    # 1. 获取客户节点
    customer_data = await neo4j.run_single(
        "MATCH (c:Customer {id: $cid}) RETURN c.name AS name, c.customer_level AS level",
        {"cid": customer_id},
    )
    if not customer_data:
        raise HTTPException(status_code=404, detail="客户不存在")

    nodes.append({
        "id": f"c_{customer_id}",
        "label": customer_data["name"],
        "type": "customer",
        "level": customer_data.get("level"),
    })
    node_ids.add(f"c_{customer_id}")

    # 2. 获取持仓产品
    products = await neo4j.run_query(
        """
        MATCH (c:Customer {id: $cid})-[h:INVESTS_IN]->(p:Product)
        RETURN p.id AS pid, p.name AS name, p.type AS type,
               p.risk_level AS risk_level, h.current_value AS value
        """,
        {"cid": customer_id},
    )
    for p in products:
        pid = f"p_{p['pid']}"
        if pid not in node_ids:
            nodes.append({
                "id": pid,
                "label": p["name"],
                "type": "product",
                "product_type": p.get("type"),
                "risk_level": p.get("risk_level"),
            })
            node_ids.add(pid)
        edges.append({
            "source": f"c_{customer_id}",
            "target": pid,
            "type": "INVESTS_IN",
            "value": float(p["value"]) if p.get("value") else 0,
        })

    # 3. 获取行业分布及产品归属关系
    product_industry = await neo4j.run_query(
        """
        MATCH (c:Customer {id: $cid})-[h:INVESTS_IN]->(p:Product)-[:BELONGS_TO]->(i:Industry)
        WITH c, i, COUNT(p) AS product_count, SUM(h.current_value) AS industry_value
        WITH c, SUM(industry_value) AS total_value,
             COLLECT({iid: i.industry_id, name: i.name, count: product_count, value: industry_value}) AS industries
        UNWIND industries AS ind
        RETURN ind.iid AS iid, ind.name AS industry_name,
               ind.count AS product_count, ind.value AS industry_value,
               ROUND(ind.value / total_value * 100, 2) AS percentage
        """,
        {"cid": customer_id},
    )
    # 构建产品→行业边（仅实际存在的归属关系）
    seen_edges = set()
    industry_nodes = {}
    for row in product_industry:
        iid = f"i_{row['iid']}"
        industry_nodes[iid] = {
            "id": iid,
            "label": row["industry_name"],
            "type": "industry",
            "product_count": row["product_count"],
            "industry_value": float(row["industry_value"]) if row.get("industry_value") else 0,
            "percentage": float(row["percentage"]) if row.get("percentage") else 0,
        }
    # 添加行业节点（去重）
    for iid, node in industry_nodes.items():
        if iid not in node_ids:
            nodes.append(node)
            node_ids.add(iid)

    # 查询产品→行业归属关系（用于边）
    product_to_industry = await neo4j.run_query(
        """
        MATCH (c:Customer {id: $cid})-[:INVESTS_IN]->(p:Product)-[:BELONGS_TO]->(i:Industry)
        RETURN p.id AS pid, i.industry_id AS iid
        """,
        {"cid": customer_id},
    )
    for row in product_to_industry:
        iid = f"i_{row['iid']}"
        edge_key = (f"p_{row['pid']}", iid)
        if edge_key not in seen_edges:
            edges.append({
                "source": f"p_{row['pid']}",
                "target": iid,
                "type": "BELONGS_TO",
            })
            seen_edges.add(edge_key)

    # 4. 获取客户风险等级节点
    risk_data = await neo4j.run_single(
        "MATCH (c:Customer {id: $cid})-[:HAS_RISK_LEVEL]->(crl:CustomerRiskLevel) "
        "RETURN crl.level_code AS level, crl.description AS desc",
        {"cid": customer_id},
    )
    if risk_data:
        rid = f"cr_{risk_data['level']}"
        if rid not in node_ids:
            nodes.append({
                "id": rid,
                "label": risk_data["desc"],
                "type": "customer_risk_level",
            })
            node_ids.add(rid)
        edges.append({
            "source": f"c_{customer_id}",
            "target": rid,
            "type": "HAS_RISK_LEVEL",
        })

    return {
        "code": 200,
        "message": "成功",
        "data": {"nodes": nodes, "edges": edges},
    }


@router.post("/query")
async def graph_query(body: dict):
    """
    通用图谱查询接口（供其他 Agent 调用）
    body: {query_type, params}
    query_type: customer_products / suitable_products / product_industry / industry_distribution
                / product_centrality / customer_community / industry_concentration
                / tx_frequency_anomaly / shortest_path
    """
    query_type = body.get("query_type", "")
    params = body.get("params", {})

    if query_type == "customer_products":
        found, data = await graph_query_tool.get_customer_products(params.get("customer_name", ""))
        if not found:
            return {"code": 404, "message": data, "data": []}
        result = data
    elif query_type == "suitable_products":
        result = await graph_query_tool.get_suitable_products(params.get("risk_level", "R3"))
    elif query_type == "product_industry":
        result = await graph_query_tool.get_product_industry(params.get("product_name", ""))
    elif query_type == "industry_distribution":
        result = await graph_query_tool.get_industry_distribution(params.get("customer_name", ""))
    # ── 图算法查询 ──
    elif query_type == "product_centrality":
        result = await graph_query_tool.get_product_centrality(
            limit=params.get("limit", 20)
        )
    elif query_type == "customer_community":
        result = await graph_query_tool.get_customer_community(
            threshold=params.get("threshold", 0.3)
        )
    elif query_type == "shortest_path":
        result = await graph_query_tool.get_shortest_path(
            customer_1=params.get("customer_1", ""),
            customer_2=params.get("customer_2", ""),
        )
        if not result:
            return {"code": 404, "message": "未找到两个客户之间的关联路径", "data": None}
    elif query_type == "industry_concentration":
        result = await graph_query_tool.get_industry_concentration(
            limit=params.get("limit", 50)
        )
    elif query_type == "tx_frequency_anomaly":
        result = await graph_query_tool.get_tx_frequency_anomaly(
            days=params.get("days", 7),
            threshold=params.get("threshold", 5),
        )
    else:
        return {"code": 400, "message": f"不支持的查询类型: {query_type}"}

    return {"code": 200, "message": "成功", "data": result}


# ═══════════════════════════════════════════════════════════
# MySQL ↔ Neo4j 一致性对账
# ═══════════════════════════════════════════════════════════

@router.get("/reconciliation")
async def reconciliation_check():
    """
    MySQL ↔ Neo4j 一致性对账：
    - 检查 fin_graph_sync_retry 中的待处理/失败记录
    - 检查 Neo4j 同步状态概览
    """
    from app.config.database import async_session_factory
    from sqlalchemy import text

    async with async_session_factory() as db:
        # 同步失败统计
        pending = await db.execute(
            text("SELECT COUNT(*) FROM fin_graph_sync_retry WHERE status = 'pending'")
        )
        pending_count = pending.scalar() or 0

        manual = await db.execute(
            text("SELECT COUNT(*) FROM fin_graph_sync_retry WHERE status = 'manual_review'")
        )
        manual_count = manual.scalar() or 0

        # 最近失败明细 (top 10)
        recent = await db.execute(
            text("""
                SELECT id, sync_type, retry_count, error_message, status, created_at
                FROM fin_graph_sync_retry
                WHERE status IN ('pending', 'manual_review')
                ORDER BY created_at DESC LIMIT 10
            """)
        )
        recent_failures = [
            {
                "id": row.id,
                "sync_type": row.sync_type,
                "retry_count": row.retry_count,
                "error_message": (row.error_message or "")[:200],
                "status": row.status,
                "created_at": str(row.created_at) if row.created_at else None,
            }
            for row in recent.fetchall()
        ]

        # 按类型统计失败
        by_type = await db.execute(
            text("""
                SELECT sync_type, status, COUNT(*) as cnt
                FROM fin_graph_sync_retry
                WHERE status != 'success'
                GROUP BY sync_type, status
                ORDER BY sync_type, status
            """)
        )
        by_type_stats = [
            {"sync_type": row.sync_type, "status": row.status, "count": row.cnt}
            for row in by_type.fetchall()
        ]

    return {
        "code": 200,
        "message": "对账完成",
        "data": {
            "pending_retries": pending_count,
            "manual_review_needed": manual_count,
            "healthy": pending_count == 0 and manual_count == 0,
            "recent_failures": recent_failures,
            "by_type": by_type_stats,
        },
    }
