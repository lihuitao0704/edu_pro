"""
智能财富管家系统 - 主入口
启动方式: python main.py  或  uvicorn main:app --reload
"""

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config.settings import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
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

    print("  服务就绪，等待请求...\n")
    yield

    print("[关闭] 系统正在停止...")
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

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- 注册路由 ----
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

try:
    from app.api.advisor import router as advisor_router
    app.include_router(advisor_router, prefix="/api/chat", tags=["投顾对话"])
except Exception as e:
    print(f"  [WARN] 投顾路由加载失败: {e}")

try:
    from app.api.chat import router as customer_chat_router
    app.include_router(customer_chat_router, prefix="/api/chat", tags=["智能客服"])
except Exception as e:
    print(f"  [WARN] 智能客服路由加载失败: {e}")

try:
    from app.api.knowledge import router as knowledge_router
    app.include_router(knowledge_router, prefix="/api/knowledge", tags=["知识库管理"])
except Exception as e:
    print(f"  [WARN] 知识库路由加载失败: {e}")


@app.get("/api/health")
async def health_check():
    return {
        "code": 200,
        "message": "ok",
        "data": {
            "service": "wealth-manager",
            "version": "1.0.0",
            "llm_model": settings.llm.openai_model_chat,
            "auth_mode": "mock" if settings.jwt.mock_mode else "jwt",
        },
    }


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

    return {
        "code": 200,
        "message": "引擎测试完成",
        "data": {
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
        },
    }


# ---- 主入口 ----
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
