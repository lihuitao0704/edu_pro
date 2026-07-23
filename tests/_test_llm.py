"""直接测试 LLM API 连通性"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
import os

api_key = os.getenv("OPENAI_API_KEY", "")
base_url = os.getenv("OPENAI_BASE_URL", "")
model = os.getenv("OPENAI_MODEL_CHAT", "")
print(f"API Key: {api_key[:10]}...{api_key[-4:]}")
print(f"Base URL: {base_url}")
print(f"Model: {model}")

from openai import OpenAI
client = OpenAI(api_key=api_key, base_url=base_url)

print("\n发送测试请求...")
t0 = time.time()
try:
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "你好，请回复'测试成功'四个字"}],
        max_tokens=50,
        timeout=30,
    )
    elapsed = time.time() - t0
    print(f"✅ LLM 响应成功 ({elapsed:.2f}s)")
    print(f"回复: {resp.choices[0].message.content}")
except Exception as e:
    elapsed = time.time() - t0
    print(f"❌ LLM 调用失败 ({elapsed:.2f}s): {type(e).__name__}: {e}")
