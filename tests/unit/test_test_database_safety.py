import os
import subprocess
import sys

import pytest

from app.core.config import BASE_DIR, Settings
from tests.db_safety import UnsafeTestDatabase, validate_test_url


@pytest.mark.parametrize("value", [
    "mysql+pymysql://u:DO_NOT_LEAK@localhost/smart_students_home",
    "mysql+pymysql://u:DO_NOT_LEAK@production.example.com/smart_home_test",
    "sqlite:///production.db", "bad://[", "",
    "mysql+pymysql://u:DO_NOT_LEAK@localhost/smart_home_test_extra_bad",
])
def test_unsafe_test_urls_are_rejected_without_secret_echo(value):
    with pytest.raises(UnsafeTestDatabase) as error:
        validate_test_url(value)
    assert "DO_NOT_LEAK" not in str(error.value)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "mysql", "mariadb"])
def test_local_ci_test_names_are_allowed(host):
    url = f"mysql+pymysql://u:p@{host}/smart_home_test_ci"
    assert validate_test_url(url) == url


def test_pytest_refuses_unsafe_database_before_collection():
    env = os.environ.copy()
    env["TEST_DATABASE_URL"] = "mysql+pymysql://u:DO_NOT_LEAK@localhost/production"
    proc = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"],
                          cwd=BASE_DIR, env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode != 0
    assert "refusing" in (proc.stdout + proc.stderr).lower()
    assert "DO_NOT_LEAK" not in proc.stdout + proc.stderr


def test_test_environment_does_not_read_dotenv(tmp_path):
    # A copy of the real module points BASE_DIR at a disposable synthetic project.
    # With dotenv loading accidentally restored, UNKNOWN_KEY makes startup fail.
    copied = tmp_path / "app" / "core" / "config.py"
    copied.parent.mkdir(parents=True)
    copied.write_text((BASE_DIR / "app/core/config.py").read_text())
    (tmp_path / ".env").write_text('SECRET_KEY="SHOULD_NOT_BE_USED"\nUNKNOWN_KEY=bad\n')
    env = os.environ.copy()
    env.update(APP_ENV="test", SECRET_KEY="x" * 48)
    code = "import runpy; c=runpy.run_path(" + repr(str(copied)) + "); assert c['settings'].SECRET_KEY == 'x'*48"
    proc = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0


@pytest.mark.parametrize("origins", ["*", "http://localhost:8000,*", " , "])
def test_cors_misconfiguration_fails_fast(origins):
    with pytest.raises(ValueError):
        Settings(_env_file=None, SECRET_KEY="x" * 48, BACKEND_CORS_ORIGINS=origins)
