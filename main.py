"""
智能财富管家系统 - 主入口
启动方式: python main.py  或  uvicorn main:app --reload
"""

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.config.settings import get_settings
from app.utils.logger import setup_logger
from app.utils.response import success

setup_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    settings.jwt.ensure_runtime_safe()
    print(f"[启动] 智能财富管家系统 V1.0.0")
    print(f"  LLM: {settings.llm.openai_model_chat}")

    # 数据库连接（开发阶段允许失败，不影响核心服务启动）
    try:
        from app.config.database import init_db, get_redis
        await init_db()
        print(f"  MySQL: {settings.mysql.host}:{settings.mysql.port}/{settings.mysql.database} [OK]")
    except Exception as e:
        print(f"  MySQL: 连接失败 ({e})，画像接口将不可用")

    try:
        await get_redis()
        print(f"  Redis: {settings.redis.host}:{settings.redis.port} [OK]")
    except Exception:
        print(f"  Redis: 未连接，缓存功能暂不可用")

    # Embedding / RAG 依赖检测（Ollama）
    try:
        from app.tool.embedding_tool import get_embedding_tool
        _emb = get_embedding_tool()
        _vec = await _emb.encode("连通性检测")
        print(f"  Embedding: {settings.llm.ollama_embed_url} [OK, dim={len(_vec)}]")
    except Exception as e:
        print(f"  Embedding: 连接失败 ({settings.llm.ollama_embed_url}) —— 智能客服/RAG 检索将返回 500，请检查 Ollama 是否运行: {str(e)[:80]}")

    # 启动风控周期校准
    try:
        from app.service.risk_scheduler import start_scheduler
        start_scheduler()
        print("  Scheduler: 风控周期校准已启动（每周日03:00）")
    except Exception as e:
        print(f"  Scheduler: 启动失败 ({e})")

    # 启动事件总线订阅消费者（多 Agent 协作闭环）
    # 统一订阅者：同时处理 risk_alert → risk_flag(MySQL+Redis) + cache clear + profile_update + work_order_change
    event_subscriber_task = None
    try:
        import asyncio
        from app.service.event_bus import start_event_subscriber
        event_subscriber_task = asyncio.create_task(start_event_subscriber())
        print("  EventBus: 事件订阅消费者已启动（risk_alert→risk_flag + profile_update + work_order_change）")
    except Exception as e:
        print(f"  EventBus: 启动失败 ({e})")

    print("  服务就绪，等待请求...\n")
    yield

    print("[关闭] 系统正在停止...")
    if event_subscriber_task:
        event_subscriber_task.cancel()
    try:
        from app.service.risk_scheduler import stop_scheduler
        stop_scheduler()
    except Exception:
        pass
    try:
        from app.config.database import close_redis, close_neo4j, close_milvus
        await close_redis()
        await close_neo4j()
        close_milvus()
    except Exception:
        pass
    print("[关闭] 系统已停止")


app = FastAPI(
    title="智能财富管家系统",
    description="AI Agent 驱动的财富管理平台 — 客户画像 + 投顾助手",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — 从配置读取允许的域名（生产环境请在 .env 中设置 CORS_ORIGINS 白名单）
_cors_origins = settings.security.cors_origins_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# JWT 认证中间件
# AUTH_MOCK_MODE=true 时跳过认证（开发阶段兼容）；生产环境设为 false
from app.middleware.auth import JWTAuthMiddleware
app.add_middleware(JWTAuthMiddleware)

# 全局异常处理中间件
from app.middleware.exception_handler import register_exception_handlers
register_exception_handlers(app)

# ---- 静态文件（测试前端） ----
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

project_dir = os.path.dirname(__file__)
vue_dist_dir = os.path.join(project_dir, "frontend", "dist")
frontend_dir = vue_dist_dir

frontend_assets_dir = os.path.join(frontend_dir, "assets")
if os.path.isdir(frontend_assets_dir):
    app.mount(
        "/assets",
        StaticFiles(directory=frontend_assets_dir),
        name="frontend-assets",
    )

@app.get("/")
async def index():
    return FileResponse(os.path.join(frontend_dir, "index.html"))

# ---- 注册路由 ----
# 认证路由（公开，无需 Token）
try:
    from app.api.auth import router as auth_router
    app.include_router(auth_router, prefix="/api/auth", tags=["认证"])
except Exception as e:
    print(f"  [WARN] 认证路由加载失败: {e}")

try:
    from app.api.profile import router as profile_router
    app.include_router(profile_router, prefix="/api/profile", tags=["客户画像"])
except Exception as e:
    print(f"  [WARN] 画像路由加载失败: {e}")

try:
    from app.api.risk import router as risk_router
    app.include_router(risk_router, prefix="/api/risk", tags=["风险评估"])
except Exception as e:
    print(f"  [WARN] 风评路由加载失败: {e}")

# 统一对话入口（Router Agent → 6意图分类 → Agent分发）
# 替代原来的 /api/chat/customer, /api/chat/advisor, /api/chat/operator, /api/chat/analyst
try:
    from app.api.unified_chat import router as unified_chat_router
    app.include_router(unified_chat_router, prefix="/api", tags=["统一对话入口"])
    print("  API: /api/chat (Router Agent 统一入口) [OK]")
except Exception as e:
    print(f"  [WARN] 统一入口路由加载失败: {e}")

try:
    from app.api.knowledge import router as knowledge_router
    app.include_router(knowledge_router, prefix="/api/knowledge", tags=["知识库管理"])
except Exception as e:
    print(f"  [WARN] 知识库路由加载失败: {e}")

try:
    from app.api.graph import router as graph_router
    app.include_router(graph_router, prefix="/api/graph", tags=["知识图谱"])
except Exception as e:
    print(f"  [WARN] 图谱路由加载失败: {e}")

try:
    from app.api.customers import router as customers_router
    app.include_router(customers_router, prefix="/api/customers", tags=["客户工作台"])
except Exception as e:
    print(f"  [WARN] 客户工作台路由加载失败: {e}")

try:
    from app.api.operations.purchase import router as purchase_router
    app.include_router(purchase_router, prefix="/api/operation", tags=["业务操作"])
except Exception as e:
    print(f"  [WARN] 申购路由加载失败: {e}")

try:
    from app.api.operations.product_query import router as pq_router
    app.include_router(pq_router, prefix="/api/operation", tags=["业务操作"])
except Exception as e:
    print(f"  [WARN] 产品查询路由加载失败: {e}")

for _name, _prefix in [
    ("redeem", "/redeem"),
    ("transfer", "/transfer"),
    ("assessment", "/assessment"),
    ("contact", "/contact"),
    ("suspicious_report", "/suspicious"),
    ("workorder", "/workorder"),
]:
    try:
        mod = __import__(f"app.api.operations.{_name}", fromlist=["router"])
        app.include_router(mod.router, prefix="/api/operation", tags=["业务操作"])
    except Exception as e:
        print(f"  [WARN] {_name}路由加载失败: {e}")


@app.get("/api/health")
async def health_check():
    return success(data={
        "service": "wealth-manager",
        "version": "1.0.0",
        "llm_model": settings.llm.openai_model_chat,
        "auth_mode": "mock" if settings.jwt.mock_mode else "jwt",
    })


# ---- 引擎测试（纯逻辑，无需数据库） ----
@app.get("/api/engine/test")
async def engine_test():
    """测试画像研判引擎（纯逻辑，无需数据库）"""
    from app.engine.dimension_calculator import DimensionCalculator
    from app.engine.circuit_breaker import CircuitBreaker
    from app.engine.confidence import ConfidenceCalculator
    from app.engine.score_mapper import calc_total_score, map_score_to_risk_level

    calc = DimensionCalculator()
    customer = {
        "age": 35, "education": "本科", "occupation": "大型国企/上市公司正式员工",
        "annual_income_range": "30-50万", "asset_range": "50-100万",
        "total_assets": 600000, "has_income": True,
        "investment_years": "5-10年", "max_product_type": "混合基金/指数基金(R3)",
        "trade_frequency": "低频", "historical_return": "5%~15%",
        "risk_assessment_level": "C3", "loss_tolerance": "10%-20%",
        "abnormal_behaviors": [],
    }

    scores = calc.calc_all(customer)
    total = calc_total_score({k: v["score"] for k, v in scores.items()})
    level, name = map_score_to_risk_level(total)

    # 熔断测试
    breaker = CircuitBreaker()
    cb_result = breaker.check_all({"age": 35})

    # 置信度测试
    conf = ConfidenceCalculator()
    confidence = conf.calc_single("questionnaire")

    return success(data={
        "customer_profile": {
            "dimensions": {k: {"score": v["score"]} for k, v in scores.items()},
            "total_score": total,
            "risk_level": level,
            "risk_name": name,
        },
        "circuit_breaker": {
            "passed": cb_result.passed,
            "warnings": cb_result.warnings,
        },
        "confidence": confidence,
        "status": "ALL_OK",
    })


# ---- 主入口 ----
@app.get("/{frontend_path:path}", include_in_schema=False)
async def frontend_fallback(frontend_path: str):
    """Serve Vue history routes while preserving JSON 404 responses for APIs."""
    if frontend_path == "api" or frontend_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found")

    requested_path = os.path.abspath(os.path.join(frontend_dir, frontend_path))
    frontend_root = os.path.abspath(frontend_dir)
    if (
        os.path.commonpath([frontend_root, requested_path]) == frontend_root
        and os.path.isfile(requested_path)
    ):
        return FileResponse(requested_path)
    return FileResponse(os.path.join(frontend_dir, "index.html"))


def _kill_port(port: int) -> None:
    """Kill any process occupying the target port before starting."""
    import subprocess, platform

    try:
        if platform.system() == "Windows":
            # Find PID by port
            result = subprocess.run(
                ["cmd", "/c", f'netstat -ano | findstr :{port} | findstr LISTENING'],
                capture_output=True, text=True, shell=True,
            )
            for line in result.stdout.strip().split("\n"):
                parts = line.strip().split()
                if len(parts) >= 5:
                    pid = parts[-1]
                    subprocess.run(["taskkill", "/F", "/PID", pid],
                                   capture_output=True, shell=True)
                    print(f"  [端口释放] PID {pid} (端口 {port}) 已终止")
        else:
            # Linux/macOS
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"], capture_output=True, text=True
            )
            for pid in result.stdout.strip().split("\n"):
                if pid:
                    subprocess.run(["kill", "-9", pid], capture_output=True)
                    print(f"  [端口释放] PID {pid} (端口 {port}) 已终止")
    except Exception as e:
        print(f"  [端口释放] 检查失败（可能无旧进程）: {e}")


if __name__ == "__main__":
    import os as _os
    _kill_port(8000)
    # 设置环境变量允许热重载时的子进程正确处理
    _os.environ.setdefault("SERVER_PORT", "8000")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
