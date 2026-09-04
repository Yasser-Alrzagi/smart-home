"""PHASE 1 verification: application boots, configuration is sane, MySQL is reachable."""
from pathlib import Path

from sqlalchemy import text

from app.core.config import BASE_DIR, settings
from app.core.database import engine
from app.core.security import (
    create_access_token,
    decode_access_token,
    get_password_hash,
    verify_password,
)


def test_health_check_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["project_ar"] == "سكن بازرعة الطلابي"
    assert data["database"] == "MySQL (Local XAMPP)"
    assert data["database_connected"] is True


def test_root_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "سكن بازرعة الطلابي" in response.json()["message"]


def test_password_hashing():
    plain = "Secr3tPassword!"
    hashed = get_password_hash(plain)
    assert hashed != plain
    assert verify_password(plain, hashed) is True
    assert verify_password("WrongPassword", hashed) is False


def test_jwt_token_flow():
    token = create_access_token(subject="user_123", role="Student")
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "user_123"
    assert payload["role"] == "Student"


def test_invalid_jwt_is_rejected():
    assert decode_access_token("not.a.valid.token") is None


def test_database_connection():
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1


def test_secret_key_is_not_the_placeholder():
    example = (BASE_DIR / ".env.example").read_text(encoding="utf-8")
    assert 'SECRET_KEY="CHANGE_ME' in example
    assert "CHANGE_ME" not in settings.SECRET_KEY
    assert len(settings.SECRET_KEY) >= 32


def test_cors_is_not_a_wildcard():
    assert "*" not in settings.cors_origins
    assert settings.cors_origins


def test_runtime_paths_are_absolute(client):
    for path in (settings.upload_path, settings.static_path, settings.templates_path):
        assert isinstance(path, Path)
        assert path.is_absolute()
        assert path.exists(), f"{path} should be created by the application lifespan"
