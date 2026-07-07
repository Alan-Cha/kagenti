"""Mission Authority service - FastAPI application."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from mission_authority import __version__
from mission_authority.api.v1 import missions, token_exchange
from mission_authority.config import settings
from mission_authority.database import engine, Base
from mission_authority.services.token_service import get_jwks

import logging

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for startup/shutdown."""
    # Startup
    logger.info(f"Starting Mission Authority v{__version__}")
    logger.info(f"Log level: {settings.log_level}")
    logger.info(f"Database: {settings.database_url.split('@')[-1]}")  # Hide credentials

    # Create tables on startup. Tables are idempotent (create_all skips existing).
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    # Shutdown
    logger.info("Shutting down Mission Authority")
    await engine.dispose()


app = FastAPI(
    title="Mission Authority",
    description="Mission-based authorization for AI agents in Kagenti",
    version=__version__,
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(missions.router, prefix="/api/v1/missions", tags=["missions"])
app.include_router(token_exchange.router, prefix="/api/v1", tags=["token-exchange"])


# Health checks
@app.get("/health/live")
async def liveness():
    """Liveness probe for Kubernetes."""
    return {"status": "ok", "version": __version__}


@app.get("/health/ready")
async def readiness():
    """Readiness probe for Kubernetes."""
    from sqlalchemy import text
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ready", "database": "ok"}
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        return {"status": "not_ready", "error": str(e)}


@app.get("/.well-known/jwks.json", include_in_schema=False)
async def jwks():
    """Public key set for verifying Mission Authority-issued tokens (RS256)."""
    return get_jwks()


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "mission-authority",
        "version": __version__,
        "docs": "/docs",
        "health": "/health/live",
    }


# Prometheus metrics
Instrumentator().instrument(app).expose(app, endpoint="/metrics")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "mission_authority.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=settings.log_level.lower(),
    )
