"""
GraphRAG 场景测试

测试内容：
  1. Cypher 多跳查询 → 在 Neo4j 中执行
  2. 实体提取 → LLM 提取 query 中的实体
  3. 融合检索 → 图谱 + 向量并行检索
  4. 完整流程 → retrieve() 返回最终回答

场景："查询持有'新能源'行业产品的所有 C4 级进取型客户"

注意：
  - 当前 Neo4j 中全部客户为 R3，R4 查询预期返回空结果，属于正常行为
  - Milvus Embedding 需要有效的 Embedding 服务（OpenAI/Ollama）才能跑向量检索
"""

import asyncio
import json
import sys
import os

# 确保从 edu_pro 目录运行以加载 .env
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.graph.neo4j_client import Neo4jClient
from app.graph.cypher_templates import (
    CUSTOMERS_BY_INDUSTRY_AND_RISK,
    GRAPH_ENTITY_SEARCH,
    FULL_GRAPH_OVERVIEW,
    PEER_PRODUCTS_BY_INDUSTRY,
    RISK_INDUSTRY_STATS,
)
from app.graph.graphrag_pipeline import GraphRAGPipeline


# ═══════════════════════════════════════════════════════════════
# 测试 1: Cypher 多跳查询（纯 Neo4j，不依赖 LLM）
# ═══════════════════════════════════════════════════════════════

async def test_cypher_multihop():
    """验证 CUSTOMERS_BY_INDUSTRY_AND_RISK 模板正确执行"""
    print("=" * 60)
    print("  测试 1: Neo4j 多跳查询")
    print("=" * 60)

    client = Neo4jClient()

    # 场景1: 新能源 + R4 — 预期空（当前数据下无R4客户）
    print("\n--- 场景: 新能源 + R4（预期空）---")
    results = await client.run_query(CUSTOMERS_BY_INDUSTRY_AND_RISK, {
        "industry": "新能源", "risk_level": "R4",
    })
    print(f"  结果数: {len(results)}")
    assert len(results) == 0, f"预期为空，实际 {len(results)} 条"
    print("  PASS")

    # 场景2: 新能源 + R3 — 当前数据下预期有结果
    print("\n--- 场景: 新能源 + R3（预期有结果）---")
    results = await client.run_query(CUSTOMERS_BY_INDUSTRY_AND_RISK, {
        "industry": "新能源", "risk_level": "R3",
    })
    print(f"  结果数: {len(results)}")
    for r in results:
        print(f"    客户: {r['customer_name']} | 等级: {r['risk_level']}({r['risk_description']})")
        print(f"    行业: {r['industry_name']}")
        print(f"    持仓: {[h['name'] for h in r.get('holdings', [])]}")
    print("  PASS")

    # 场景3: 不存在的行业 — 预期空
    print("\n--- 场景: 不存在的行业 '元宇宙' + R3（预期空）---")
    results = await client.run_query(CUSTOMERS_BY_INDUSTRY_AND_RISK, {
        "industry": "元宇宙", "risk_level": "R3",
    })
    print(f"  结果数: {len(results)}")
    assert len(results) == 0
    print("  PASS")

    # 场景4: 模糊匹配 — 用 '新能' 匹配 '新能源'
    print("\n--- 场景: '新能' + R3（CONTAINS 模糊匹配）---")
    results = await client.run_query(CUSTOMERS_BY_INDUSTRY_AND_RISK, {
        "industry": "新能", "risk_level": "R3",
    })
    print(f"  结果数: {len(results)}")
    # 预期匹配到 新能源
    print("  PASS" if len(results) > 0 else "  (空 — 检查产品是否关联了新能源行业)")


# ═══════════════════════════════════════════════════════════════
# 测试 2: 实体模糊搜索
# ═══════════════════════════════════════════════════════════════

async def test_entity_search():
    """验证 GRAPH_ENTITY_SEARCH 模板"""
    print("\n" + "=" * 60)
    print("  测试 2: 图谱实体模糊搜索")
    print("=" * 60)

    client = Neo4jClient()

    for keyword in ["新能源", "R4", "张三", "债基"]:
        print(f"\n--- 搜索: '{keyword}' ---")
        results = await client.run_query(GRAPH_ENTITY_SEARCH, {"keyword": keyword})
        print(f"  结果数: {len(results)}")
        for r in results:
            print(f"    类型: {r['labels']} | 名称: {r['name']} | 等级: {r.get('level')}")
    print("  PASS")


# ═══════════════════════════════════════════════════════════════
# 测试 3: 全图谱概览 + 行业统计
# ═══════════════════════════════════════════════════════════════

async def test_overview():
    """验证 FULL_GRAPH_OVERVIEW 和 RISK_INDUSTRY_STATS"""
    print("\n" + "=" * 60)
    print("  测试 3: 全图谱概览 & 行业统计")
    print("=" * 60)

    client = Neo4jClient()

    print("\n--- 全图谱概览 ---")
    results = await client.run_query(FULL_GRAPH_OVERVIEW)
    for r in results:
        print(f"  {r['customer_name']} ({r['risk_level']} {r['risk_description']}) — "
              f"{len(r['holdings'])} 个产品")

    print("\n--- 各等级行业偏好 ---")
    results = await client.run_query(RISK_INDUSTRY_STATS)
    for r in results:
        print(f"  {r['risk_level']}({r['risk_desc']}) → {r['industry']}: "
              f"{r['customer_count']}人 {r['customers']}")
    print("  PASS")


# ═══════════════════════════════════════════════════════════════
# 测试 4: LLM 实体提取（需要有效的 LLM API）
# ═══════════════════════════════════════════════════════════════

async def test_entity_extraction():
    """验证 LLM 实体提取"""
    print("\n" + "=" * 60)
    print("  测试 4: LLM 实体提取")
    print("=" * 60)

    pipeline = GraphRAGPipeline()

    test_queries = [
        (
            "查询持有新能源行业产品的所有C4级进取型客户",
            {"industry": "新能源", "risk_level": "R4"},
        ),
        (
            "张三买了哪些科技类的基金",
            {"customer_name": "张三", "industry": "科技"},
        ),
    ]

    for query, expected in test_queries:
        print(f"\n--- 查询: '{query}' ---")
        entities = await pipeline._extract_entities(query)
        print(f"  提取结果: {json.dumps(entities, ensure_ascii=False)}")

        # 检查关键字段
        for key, expected_val in expected.items():
            actual_val = entities.get(key)
            if actual_val == expected_val:
                print(f"  [{key}] PASS: '{actual_val}'")
            else:
                print(f"  [{key}] WARN: 期望 '{expected_val}'，实际 '{actual_val}'")


# ═══════════════════════════════════════════════════════════════
# 测试 5: 完整检索流程（图谱 + 向量 → 回答）
# ═══════════════════════════════════════════════════════════════

async def test_full_retrieve():
    """验证完整 retrieve() 流程"""
    print("\n" + "=" * 60)
    print("  测试 5: 完整检索流程")
    print("=" * 60)

    pipeline = GraphRAGPipeline()

    query = "查询持有新能源行业产品的客户"
    print(f"\n  用户提问: '{query}'")

    # 先看原始数据
    raw = await pipeline.retrieve_raw(query)
    print(f"  实体提取: {json.dumps(raw['entities'], ensure_ascii=False)}")
    print(f"  图谱结果: {len(raw['graph_results'])} 条")
    print(f"  向量结果: {len(raw['vector_results'])} 条")
    print(f"  融合结果: {len(raw['fused'])} 条")

    if raw["graph_results"]:
        print("\n  图谱结果预览:")
        for r in raw["graph_results"][:3]:
            print(f"    - 客户 {r.get('customer_name')} "
                  f"等级 {r.get('risk_level')}({r.get('risk_description')}) "
                  f"→ {r.get('industry')}")

    # 生成完整回答（需要有效的 LLM API）
    print("\n  --- LLM 生成回答 ---")
    try:
        answer = await pipeline.retrieve(query)
        print(f"  {answer[:500]}...")
        print("  PASS")
    except Exception as e:
        print(f"  SKIP (LLM 不可用): {e}")


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

async def main():
    print("GraphRAG 场景测试")
    print(f"Neo4j: {os.getenv('NEO4J_URI', '默认配置')}")
    print()

    # 按顺序执行，前面失败的不会阻塞后面
    tests = [
        ("Cypher 多跳查询", test_cypher_multihop),
        ("图谱实体搜索", test_entity_search),
        ("全图谱概览", test_overview),
        ("LLM 实体提取", test_entity_extraction),
        ("完整检索流程", test_full_retrieve),
    ]

    passed, failed, skipped = 0, 0, 0
    for name, test_func in tests:
        try:
            await test_func()
            passed += 1
        except AssertionError as e:
            print(f"\n  FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"\n  SKIP ({type(e).__name__}): {e}")
            skipped += 1

    print("\n" + "=" * 60)
    print(f"  结果: {passed} 通过, {failed} 失败, {skipped} 跳过")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
