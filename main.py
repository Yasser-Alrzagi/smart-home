"""FastAPI application entry point — API layer wiring only."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.v1 import (
    auth,
    users,
    admissions,
    housing,
    facilities,
    support,
    attendance,
    notifications,
    daily_attendance,
    dashboards,
)
from app.web.routes import router as web_router
from app.core.body_limit import BodyLimitMiddleware
from app.core.errors import AppError
from app.core.schema_version import SCHEMA_HEAD
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


@app.exception_handler(AppError)
async def domain_error(_: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers
    )


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    # FastAPI's default error body may echo passwords or extra secret fields.
    errors = [
        {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


@app.exception_handler(SQLAlchemyError)
async def database_error(_: Request, exc: SQLAlchemyError):
    code = getattr(getattr(exc, "orig", None), "args", (None,))[0]
    if code in {1020, 1205, 1213}:
        return JSONResponse(
            status_code=409, content={"detail": "Concurrent update; retry the request."}
        )
    return JSONResponse(
        status_code=503, content={"detail": "Service temporarily unavailable."}
    )


@app.middleware("http")
async def private_api_responses(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(settings.API_V1_STR):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


# Identity + admissions + housing + D5 product APIs and the local-asset web portal.
app.add_middleware(BodyLimitMiddleware)
app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(users.router, prefix=settings.API_V1_STR)
app.include_router(admissions.router, prefix=settings.API_V1_STR)
app.include_router(housing.router, prefix=settings.API_V1_STR)
app.include_router(facilities.router, prefix=settings.API_V1_STR)
app.include_router(support.router, prefix=settings.API_V1_STR)
app.include_router(attendance.router, prefix=settings.API_V1_STR)
app.include_router(notifications.router, prefix=settings.API_V1_STR)
app.include_router(daily_attendance.router, prefix=settings.API_V1_STR)
app.include_router(dashboards.router, prefix=settings.API_V1_STR)
app.include_router(web_router)


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


@app.get("/ready", tags=["System"])
def readiness():
    try:
        with engine.connect() as connection:
            versions = (
                connection.execute(text("SELECT version_num FROM alembic_version"))
                .scalars()
                .all()
            )
            guard = connection.execute(
                text("SELECT guard_id FROM account_guard WHERE guard_id=1")
            ).scalar()
            connection.execute(
                text("SELECT auth_version,must_change_password FROM users LIMIT 1")
            )
            for table, column in [
                ("auth_sessions", "session_id"),
                ("audit_events", "event_id"),
                ("login_rate_buckets", "bucket_key"),
                ("applications", "version"),
                ("students", "profile_version"),
                ("application_documents", "content_type"),
                ("application_events", "event_id"),
                ("floors", "floor_id"),
                ("apartments", "apartment_id"),
                ("rooms", "room_id"),
                ("room_assignments", "assignment_id"),
                ("services", "service_id"),
                ("service_periods", "period_id"),
                ("service_registrations", "registration_id"),
                ("complaints", "complaint_id"),
                ("maintenance_requests", "request_id"),
                ("permission_requests", "permission_id"),
                ("emergency_reports", "report_id"),
                ("student_absences", "absence_id"),
            ]:
                connection.execute(text(f"SELECT {column} FROM {table} LIMIT 1"))
        ready = versions == [SCHEMA_HEAD] and guard == 1
    except SQLAlchemyError:
        ready = False
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready"},
    )


@app.get("/", tags=["System"])
def root():
    """Root entry point."""
    return {
        "message": "Welcome to Smart Student Housing Management System - سكن بازرعة الطلابي",
        "docs_url": "/docs" if settings.DEBUG else None,
        "health_check": "/health",
        "portal": "/app",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
