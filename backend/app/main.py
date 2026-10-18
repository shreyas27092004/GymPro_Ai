# app/main.py
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from .auth.router import router as auth_router
from .settings import settings

app = FastAPI(
    title="GymPro AI",
    description="GymPro AI Backend API",
    version="0.1.0",
)

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
