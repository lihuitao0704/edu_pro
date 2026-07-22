"""快速启动服务器并验证API"""
import sys
sys.path.insert(0, ".")
import asyncio
import httpx

async def test():
    # 验证 health 接口
    async with httpx.AsyncClient() as client:
        r = await client.get("http://127.0.0.1:8000/api/health")
        print(f"Health: {r.json()}")
        
        r2 = await client.get("http://127.0.0.1:8000/api/engine/test")
        data = r2.json()
        print(f"Engine: code={data['code']}, level={data['data']['risk_level']}, status={data['data']['status']}")

print("请先执行: uvicorn main:app --port 8000")
print("然后运行: python tests/start_server.py 测试API")
