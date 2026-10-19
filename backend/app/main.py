# app/main.py
import time
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from .auth.admin_router import admin_router
from .trainer_router import trainer_router
from .auth.router import router as auth_router
from .entitlements.router import router as entitlements_router
from .executor import executor_router
from .orchestrator.router import router as orchestrator_router
from .payments import router as payments_router
from .observability import (
    setup_logging,
    trace_span,
    get_current_trace_id,
    record_request,
    metrics,
)
from .settings import settings

app = FastAPI(
    title="GymPro AI",
    description="GymPro AI Backend API",
    version="0.1.0",
)


# Startup verification and observability setup
@app.on_event("startup")
async def startup_check():
    setup_logging()
    if settings.env == "production" and settings.payments_mode == "mock":
        raise RuntimeError("PAYMENTS_MODE=mock is not allowed when ENV=production")
    if settings.env == "production" and settings.llm_provider == "fake":
        raise RuntimeError("LLM_PROVIDER=fake is not allowed when ENV=production")


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.perf_counter()
        method = request.method
        path = request.url.path

        with trace_span(f"HTTP {method} {path}", attributes={"http.method": method, "http.target": path}):
            trace_id = get_current_trace_id()
            try:
                response = await call_next(request)
            except Exception as e:
                duration = time.perf_counter() - start_time
                record_request(method, path, 500, duration)
                raise e

            duration = time.perf_counter() - start_time
            record_request(method, path, response.status_code, duration)
            if trace_id:
                response.headers["X-Trace-Id"] = trace_id
            return response


app.add_middleware(ObservabilityMiddleware)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount authentication routers under /api/auth, /auth, /api, and /
app.include_router(auth_router, prefix="/api/auth")
app.include_router(auth_router, prefix="/auth")
app.include_router(auth_router, prefix="/api")

# Mount admin routers under /api/admin and /admin
app.include_router(admin_router, prefix="/api/admin")
app.include_router(admin_router, prefix="/admin")

# Mount trainer routers under /api/trainer and /trainer
app.include_router(trainer_router, prefix="/api/trainer")
app.include_router(trainer_router, prefix="/trainer")

# Mount entitlements & member profile router under /api
app.include_router(entitlements_router, prefix="/api")

# Mount deterministic executor router under /api
app.include_router(executor_router, prefix="/api")

# Mount payments router under /api
app.include_router(payments_router, prefix="/api")

# Mount agent chat orchestrator router under /api
app.include_router(orchestrator_router, prefix="/api")


@app.get("/health", status_code=status.HTTP_200_OK, tags=["System"])
async def health():
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/ready", status_code=status.HTTP_200_OK, tags=["System"])
async def ready():
    """Readiness probe checking subsystem status."""
    readiness = {
        "status": "ready",
        "environment": settings.env,
        "database": "configured",
        "rabbitmq": "configured",
        "llm_provider": settings.llm_provider,
    }
    return readiness


@app.get("/metrics", status_code=status.HTTP_200_OK, tags=["System"])
async def get_metrics():
    """Exposes Prometheus format metrics."""
    return Response(content=metrics.to_prometheus_format(), media_type="text/plain; version=0.0.4")


@app.get("/metrics/json", status_code=status.HTTP_200_OK, tags=["System"])
async def get_metrics_json():
    """Exposes JSON aggregated metrics."""
    return metrics.get_summary()
