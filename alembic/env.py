from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool, text

from alembic import context

# Import application settings and all models so Alembic autogenerate can detect all tables
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.core.database import Base
import app.models  # noqa: F401 — registers all 26 models

config = context.config

# Set the database URL dynamically from app settings
config.set_main_option("sqlalchemy.url", settings.get_database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Point autogenerate at our single declarative Base
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no DB connection required)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connected to MySQL via XAMPP)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        if connection.dialect.name not in {"mysql", "mariadb"}:
            raise RuntimeError("Online migrations require MySQL/MariaDB.")
        defaults = connection.execute(text(
            "SELECT @@default_storage_engine, @@character_set_database, @@collation_database"
        )).one()
        if tuple(str(value).lower() for value in defaults) != ("innodb", "utf8mb4", "utf8mb4_unicode_ci"):
            raise RuntimeError("Migrations require InnoDB and database utf8mb4/utf8mb4_unicode_ci defaults.")
        # End the read-only preflight transaction before Alembic owns its transaction.
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
