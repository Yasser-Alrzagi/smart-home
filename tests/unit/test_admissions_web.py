from app.core.config import BASE_DIR
from app.core.errors import AppError
from app.services import documents
import pytest


def test_portal_serves_local_assets_without_storage_tokens(client):
    response = client.get("/app")
    assert response.status_code == 200
    assert 'lang="ar" dir="rtl"' in response.text
    assert "no-store" in response.headers["cache-control"]
    assert client.get("/static/portal.js").status_code == 200
    assert client.get("/static/portal.css").status_code == 200
    script = (BASE_DIR / "app/web/static/portal.js").read_text(encoding='utf-8')
    assert "localStorage" not in script and "sessionStorage" not in script
    assert ".innerHTML" not in script
    assert "http://" not in script and "https://" not in script


def test_document_parser_does_not_inherit_credentials(monkeypatch):
    from types import SimpleNamespace

    seen = {}

    def run(*args, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(returncode=0, stdout=b"validated bytes")

    monkeypatch.setattr(documents.subprocess, "run", run)
    documents.validate_document(b"input", "test.pdf", "application/pdf")
    assert "SECRET_KEY" not in seen["env"] and "DATABASE_URL" not in seen["env"]
    assert seen["timeout"] == 7


def test_parser_timeout_is_safe(monkeypatch):
    import subprocess

    def fail(*a, **kw):
        raise subprocess.TimeoutExpired("worker", 7)

    monkeypatch.setattr(documents.subprocess, "run", fail)
    with pytest.raises(AppError) as error:
        documents.validate_document(b"bytes", "file.pdf", "application/pdf")
    assert error.value.status_code == 415
