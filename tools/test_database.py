"""Migrate a guarded TEST database only. Never reads the application's .env."""
import argparse
import os
import secrets

from tests.db_safety import UnsafeTestDatabase, validate_test_url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        url = validate_test_url(os.environ.get("TEST_DATABASE_URL", ""))
    except UnsafeTestDatabase as exc:
        parser.error(str(exc))
    os.environ.update(APP_ENV="test", DATABASE_URL=url, SECRET_KEY=secrets.token_hex(48))
    # Deliberately import Alembic only AFTER validating and setting isolated config.
    from alembic import command
    from alembic.config import Config
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    command.upgrade(Config(str(root / "alembic.ini")), "head")
    print("Isolated test schema upgraded successfully (connection details redacted).")


if __name__ == "__main__":
    main()
