"""临时脚本：检查 Milvus 和 Neo4j 数据状态"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config.settings import get_settings
s = get_settings()

# ── 1. Milvus 检查 ──
print("=" * 50)
print("Milvus 检查")
print("=" * 50)
try:
    from pymilvus import MilvusClient
    client = MilvusClient(uri=f"http://{s.milvus.host}:{s.milvus.port}", timeout=5)
    cols = client.list_collections()
    print(f"Collections: {cols}")
    for c in cols:
        try:
            stats = client.get_collection_stats(c)
            cnt = stats.get("row_count", "?")
            print(f"  {c}: {cnt} 条向量")
        except Exception as e:
            print(f"  {c}: 查询失败 {e}")
except Exception as e:
    print(f"Milvus 连接失败: {e}")

# ── 2. Neo4j 检查 ──
print("\n" + "=" * 50)
print("Neo4j 检查")
print("=" * 50)
try:
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(s.neo4j.uri, auth=(s.neo4j.user, s.neo4j.password))
    with driver.session() as sess:
        for label in ["Customer", "Product", "Industry", "FundManager", "RiskLevel", "Market"]:
            r = sess.run(f"MATCH (n:{label}) RETURN count(n) AS c")
            print(f"  {label}: {r.single()['c']} 个节点")
        for rel in ["INVESTS_IN", "BELONGS_TO", "HAS_RISK_LEVEL", "MANAGED_BY", "SUITABLE_FOR"]:
            r = sess.run(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS c")
            print(f"  [{rel}]: {r.single()['c']} 条关系")
    driver.close()
except Exception as e:
    print(f"Neo4j 连接失败: {e}")

# ── 3. Redis 检查 ──
print("\n" + "=" * 50)
print("Redis 检查")
print("=" * 50)
try:
    import redis
    r = redis.Redis(host=s.redis.host, port=s.redis.port, db=s.redis.db, decode_responses=True)
    print(f"  Ping: {r.ping()}")
    keys = r.keys("*")
    print(f"  现有 keys: {len(keys)} 个")
    for k in keys[:10]:
        print(f"    {k}")
except Exception as e:
    print(f"Redis 连接失败: {e}")
