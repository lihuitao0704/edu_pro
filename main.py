"""
智能财富管家系统 - 主入口
启动方式: python main.py  或  uvicorn main:app --reload
"""

import socket
import subprocess
from pathlib import Path

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

    # 启动图谱同步重试补偿
    try:
        from app.service.graph_sync_retry_service import start_graph_sync_retry_scheduler
        start_graph_sync_retry_scheduler()
        print("  Scheduler: Neo4j 图谱同步重试补偿已启动（每60秒）")
    except Exception as e:
        print(f"  Scheduler: 图谱同步重试启动失败 ({e})")

    # 启动事件总线：Outbox 可靠投递 + Redis 广播 + 多 Agent 独立消费者
    event_subscriber_task = None
    event_outbox_task = None
    try:
        import asyncio
        from app.service.event_bus import start_event_subscriber
        from app.service.agent_event_service import run_outbox_relay
        event_subscriber_task = asyncio.create_task(start_event_subscriber())
        event_outbox_task = asyncio.create_task(run_outbox_relay())
        print("  EventBus: Outbox→Redis 广播已启动（画像/投顾/客服/风控独立消费者）")
    except Exception as e:
        print(f"  EventBus: 启动失败 ({e})")

    print("  服务就绪，等待请求...\n")
    yield

    print("[关闭] 系统正在停止...")
    if event_subscriber_task:
        event_subscriber_task.cancel()
    if event_outbox_task:
        event_outbox_task.cancel()
    try:
        from app.service.risk_scheduler import stop_scheduler
        stop_scheduler()
    except Exception:
        pass
    try:
        from app.service.graph_sync_retry_service import stop_graph_sync_retry_scheduler
        stop_graph_sync_retry_scheduler()
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
from fastapi.responses import FileResponse, HTMLResponse
import os

project_dir = os.path.dirname(__file__)
PROJECT_ROOT = Path(project_dir).resolve()
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
    html_path = os.path.join(frontend_dir, "index.html")
    with open(html_path, encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(
        content,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"},
    )

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
    from app.api.advisor import router as advisor_router
    app.include_router(advisor_router, prefix="/api", tags=["投顾助手"])
except Exception as e:
    print(f"  [WARN] advisor route load failed: {e}")

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
    from app.api.feedback import router as feedback_router
    app.include_router(feedback_router, prefix="/api", tags=["对话反馈"])
    from app.api.analytics import router as analytics_router
    app.include_router(analytics_router, prefix="/api", tags=["对话分析"])
except Exception as e:
    print(f"  [WARN] 对话平台路由加载失败: {e}")

try:
    from app.api.admin import router as admin_router
    app.include_router(admin_router, prefix="/api/admin", tags=["管理"])
    print("  API: /api/admin (健康检查 / 可观测性 / 规则热加载) [OK]")
except Exception as e:
    print(f"  [WARN] 管理路由加载失败: {e}")

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

try:
    from app.api.nlp import router as nlp_router
    app.include_router(nlp_router, prefix="/api/nlp", tags=["NLP 智能解读"])
    print("  API: /api/nlp (NLP 产品智能解读) [OK]")
except Exception as e:
    print(f"  [WARN] NLP路由加载失败: {e}")

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


@app.get("/api/health/live")
async def health_live():
    """Process liveness only; no dependency calls."""
    return success(data={
        "status": "alive",
        "service": "wealth-manager",
        "version": "1.0.0",
    })


async def _readiness_payload() -> dict:
    from sqlalchemy import text
    from app.config.database import async_session_factory, get_redis
    from app.service.runtime_health_service import get_runtime_health

    checks: dict[str, dict] = {}
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["mysql"] = {"status": "ok"}
    except Exception as exc:
        checks["mysql"] = {"status": "unavailable", "error_type": type(exc).__name__}

    try:
        redis = await get_redis()
        await redis.ping()
        checks["redis"] = {"status": "ok"}
    except Exception as exc:
        checks["redis"] = {"status": "unavailable", "error_type": type(exc).__name__}

    checks.update(get_runtime_health())
    unavailable = [
        name
        for name, detail in checks.items()
        if detail.get("status") == "unavailable"
    ]
    return {
        "status": "ready" if not unavailable else "degraded",
        "service": "wealth-manager",
        "version": "1.0.0",
        "llm_model": settings.llm.openai_model_chat,
        "auth_mode": "mock" if settings.jwt.mock_mode else "jwt",
        "checks": checks,
        "unavailable": unavailable,
    }


@app.get("/api/health")
async def health_check():
    """Backward-compatible readiness response used by the frontend."""
    return success(data=await _readiness_payload())


@app.get("/api/health/ready")
async def health_ready():
    return success(data=await _readiness_payload())


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
        if requested_path.endswith(".html"):
            with open(requested_path, encoding="utf-8") as f:
                return HTMLResponse(
                    f.read(),
                    headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
                )
        return FileResponse(requested_path)
    with open(os.path.join(frontend_dir, "index.html"), encoding="utf-8") as f:
        return HTMLResponse(
            f.read(),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"},
        )


def is_port_available(port: int) -> bool:
    """Return whether the TCP port is available on the local host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


def _listener_pid(port: int) -> str | None:
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True, check=False
        )
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3] == "LISTENING":
                return parts[-1]
    except OSError:
        return None
    return None


def listener_command(port: int) -> str:
    pid = _listener_pid(port)
    if not pid:
        return ""
    result = subprocess.run(
        [
            "powershell", "-NoProfile", "-Command",
            f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def release_workspace_listener(port: int) -> bool:
    """End a stale listener only when it is this workspace's Python service."""
    pid = _listener_pid(port)
    command = listener_command(port)
    normalized = command.replace("/", "\\").lower()
    root = str(PROJECT_ROOT).replace("/", "\\").lower()
    if not pid or root not in normalized or not ("python" in normalized or "uvicorn" in normalized):
        return False
    subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, text=True, check=False)
    return is_port_available(port)


def resolve_server_port(preferred_port: int = 8000) -> int:
    for port in dict.fromkeys((preferred_port, 8001)):
        if is_port_available(port):
            return port
        release_workspace_listener(port)
        if is_port_available(port):
            return port
    raise RuntimeError("端口 8000 和 8001 均不可用，请释放端口后重试。")


def ensure_frontend_build(project_root: Path = PROJECT_ROOT) -> None:
    if (project_root / "frontend" / "dist" / "index.html").is_file():
        return
    subprocess.run(["pnpm", "--dir", "frontend", "build"], cwd=project_root, check=True)


if __name__ == "__main__":
    ensure_frontend_build()
    server_port = resolve_server_port()
    if server_port != 8000:
        print("[启动] 端口 8000 被非本项目进程占用，已安全切换到 8001。")
    # 设置环境变量允许热重载时的子进程正确处理
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=server_port,
        reload=True,
        log_level="info",
    )
