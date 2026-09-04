"""FastAPI application entry point — API layer wiring only."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.v1 import auth
from app.core.config import ensure_directories, settings
from app.core.database import engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_directories()
    yield


# Interactive API documentation is exposed only while DEBUG is enabled.
app = FastAPI(
    title=f"{settings.PROJECT_NAME} ({settings.PROJECT_NAME_AR})",
    version=settings.VERSION,
    description="REST API for Smart Student Housing Management System - سكن بازرعة الطلابي",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
    lifespan=lifespan,
)

# Credentialed requests are allowed only from the explicitly listed browser origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

app.mount(
    "/static",
    StaticFiles(directory=settings.static_path, check_dir=False),
    name="static",
)

# REST routers — API group 1: Authentication.
app.include_router(auth.router, prefix=settings.API_V1_STR)


@app.get("/health", tags=["System"])
def health_check():
    """System health check — verifies MySQL connectivity instead of assuming it."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database_connected = True
    except Exception:
        database_connected = False

    payload = {
        "status": "healthy" if database_connected else "degraded",
        "project": settings.PROJECT_NAME,
        "project_ar": settings.PROJECT_NAME_AR,
        "version": settings.VERSION,
        "database": "MySQL (Local XAMPP)",
        "database_connected": database_connected,
    }
    return JSONResponse(status_code=200 if database_connected else 503, content=payload)


@app.get("/", tags=["System"])
def root():
    """Root entry point."""
    return {
        "message": "Welcome to Smart Student Housing Management System - سكن بازرعة الطلابي",
        "docs_url": "/docs" if settings.DEBUG else None,
        "health_check": "/health",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
