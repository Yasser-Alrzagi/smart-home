"""Application configuration loaded from environment / .env file."""

import os
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

# Project root: <root>/app/core/config.py -> parents[2] == <root>
BASE_DIR: Path = Path(__file__).resolve().parents[2]

# Value shipped in .env.example; refused at runtime so a known key can never sign tokens.
_PLACEHOLDER_SECRETS = {
    "CHANGE_ME_GENERATE_WITH_python_-c_import_secrets_print_secrets.token_hex_48",
    "supersecret_jwt_key_for_smart_student_housing_system_change_in_production",
}


class Settings(BaseSettings):
    APP_ENV: Literal["development", "test", "production"] = "development"
    PROJECT_NAME: str = "Smart Student Housing Management System"
    PROJECT_NAME_AR: str = "سكن بازرعة الطلابي"
    VERSION: str = "1.0.0"
    DEBUG: bool = True
    API_V1_STR: str = "/api/v1"

    # Security — SECRET_KEY has no default on purpose: it must come from the environment.
    SECRET_KEY: str = Field(repr=False)
    ALGORITHM: Literal["HS256"] = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(30, ge=1, le=60)
    JWT_ISSUER: str = Field("smart-student-housing", min_length=1, max_length=128)
    JWT_AUDIENCE: str = Field("smart-student-housing-api", min_length=1, max_length=128)
    MAX_ACTIVE_SESSIONS: int = Field(5, ge=1, le=20)
    LOGIN_IP_LIMIT: int = Field(30, ge=1, le=1000)
    LOGIN_IP_WINDOW_SECONDS: int = Field(60, ge=1, le=3600)
    LOGIN_ACCOUNT_IP_LIMIT: int = Field(8, ge=1, le=100)
    LOGIN_ACCOUNT_WINDOW_SECONDS: int = Field(300, ge=1, le=3600)

    # Browser origins allowed to call the API (comma separated).
    BACKEND_CORS_ORIGINS: str = "http://127.0.0.1:8000,http://localhost:8000"

    # MySQL Database (XAMPP Local)
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = Field("", repr=False)
    DB_NAME: str = "smart_students_home"
    DATABASE_URL: Optional[str] = Field(None, repr=False)

    # Uploads
    UPLOAD_DIR: str = "uploads"

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="forbid",
        hide_input_in_errors=True,
    )

    @field_validator("SECRET_KEY")
    @classmethod
    def _validate_secret_key(cls, value: str) -> str:
        if value in _PLACEHOLDER_SECRETS:
            raise ValueError(
                "SECRET_KEY is still the placeholder value. Generate a real one with: "
                'python -c "import secrets; print(secrets.token_hex(48))"'
            )
        if len(value) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long.")
        return value

    @property
    def get_database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return URL.create(
            "mysql+pymysql",
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=self.DB_NAME,
            query={"charset": "utf8mb4"},
        ).render_as_string(hide_password=False)

    @field_validator("BACKEND_CORS_ORIGINS")
    @classmethod
    def _validate_cors(cls, value: str) -> str:
        origins = [item.strip() for item in value.split(",") if item.strip()]
        if not origins or any("*" in item for item in origins):
            raise ValueError(
                "CORS requires explicit, nonempty origins; wildcards are forbidden."
            )
        return value

    @property
    def cors_origins(self) -> List[str]:
        return [
            origin.strip()
            for origin in self.BACKEND_CORS_ORIGINS.split(",")
            if origin.strip()
        ]

    # Absolute paths — never depend on the process working directory.
    @property
    def upload_path(self) -> Path:
        path = Path(self.UPLOAD_DIR)
        return path if path.is_absolute() else BASE_DIR / path

    @property
    def static_path(self) -> Path:
        return BASE_DIR / "app" / "web" / "static"

    @property
    def templates_path(self) -> Path:
        return BASE_DIR / "app" / "web" / "templates"


# Tests must never read a developer/production .env, including unrelated secrets.
settings = Settings(
    _env_file=None if os.environ.get("APP_ENV") == "test" else BASE_DIR / ".env"
)


def ensure_directories() -> None:
    """Create the runtime directories. Called from the app lifespan, not at import time."""
    for path in (settings.upload_path, settings.static_path, settings.templates_path):
        path.mkdir(parents=True, exist_ok=True)
