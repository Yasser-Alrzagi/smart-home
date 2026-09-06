"""Test-only database guard, intentionally independent of app/settings imports."""
import re

from sqlalchemy.engine import make_url


class UnsafeTestDatabase(ValueError):
    pass


def validate_test_url(value: str) -> str:
    try:
        url = make_url(value)
        valid = (
            url.drivername in {"mysql+pymysql", "mariadb+pymysql"}
            and re.fullmatch(r"smart_home_test(?:_[a-z0-9]+)?", url.database or "")
            and url.host in {"localhost", "127.0.0.1", "::1", "mysql", "mariadb"}
        )
        # Also force parsing/validation of the port before any engine is built.
        _ = url.port
    except Exception:
        raise UnsafeTestDatabase("Invalid TEST_DATABASE_URL (value redacted).") from None
    if not valid:
        raise UnsafeTestDatabase(
            "Tests require a local/CI MySQL database named smart_home_test or "
            "smart_home_test_<suffix>; refusing the supplied URL (value redacted)."
        )
    return value
