# Smart Student Housing Management System — سكن بازرعة الطلابي

Web-based student housing management system with an AI-assisted cleaning rotation
optimizer (BFS and A\*). Runs locally on XAMPP.

## Technology Stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI |
| Database | MySQL (XAMPP) |
| ORM | SQLAlchemy 2.0 |
| Migrations | Alembic |
| Auth | JWT (HS256) + bcrypt |
| Authorization | RBAC — 9 roles |
| API | REST, JSON, documented with Swagger / OpenAPI |
| Frontend | Web UI in the browser (Jinja2 templates + JavaScript calling the REST APIs) |
| AI | BFS and A\* search only |
| Architecture | Layered Architecture |

## Architecture

```
Web Browser UI            app/web/
        |  REST / JSON
FastAPI REST APIs         app/api/v1/            (7 API groups)
        |
Business Logic + Security app/services/, app/core/security.py
        |
Data Access Layer         app/repositories/ (Repository Pattern), app/models/
        |
MySQL via XAMPP
```

The Cleaning Rotation Optimizer (`app/ai/`) runs inside the same application layer
and uses the same MySQL database. BFS and A\* are selected through the Strategy
Pattern; results are advisory and require Cleaning Officer approval.

## Project Structure

```
main.py                 FastAPI entry point (/, /health)
alembic/                migration environment and versions
app/
  core/                 config, database engine/session, security (JWT + bcrypt)
  models/               16 SQLAlchemy models
  schemas/              Pydantic request/response schemas
  repositories/         data access (Repository Pattern)
  services/             business rules
  ai/                   cleaning rotation optimizer (BFS + A*)
  api/v1/               REST routers — 7 API groups
  web/                  Jinja2 templates and static assets
tests/                  unit/ integration/ scenario/ + conftest.py
uploads/                uploaded application documents
```

## Setup

Requires Python 3.12+ and a running XAMPP MySQL service.

```powershell
# 1. Virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Dependencies
pip install -r requirements.txt

# 3. Configuration
Copy-Item .env.example .env

# 4. Generate a real SECRET_KEY and put it in .env
#    The application refuses to start while SECRET_KEY is the placeholder value.
python -c "import secrets; print(secrets.token_hex(48))"

# 5. Create the database (once), in MySQL:
#    CREATE DATABASE smart_students_home CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

# 6. Apply migrations
alembic upgrade head

# 7. Run
python main.py
```

| URL | Description |
|---|---|
| `http://127.0.0.1:8000/` | Root |
| `http://127.0.0.1:8000/health` | Health check — returns 503 if MySQL is unreachable |
| `http://127.0.0.1:8000/docs` | Swagger UI (only while `DEBUG=True`) |
| `http://127.0.0.1:8000/redoc` | ReDoc (only while `DEBUG=True`) |

## Configuration

All settings come from `.env` (see `.env.example`). Unknown keys are rejected, so a
typo fails loudly instead of being ignored.

| Key | Notes |
|---|---|
| `SECRET_KEY` | **Required.** Minimum 32 characters, must not be the placeholder |
| `DEBUG` | Also gates `/docs`, `/redoc`, `/openapi.json` |
| `BACKEND_CORS_ORIGINS` | Comma-separated allowed browser origins. Never `*` |
| `DATABASE_URL` | Full SQLAlchemy URL; overrides the `DB_*` values |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT lifetime |
| `UPLOAD_DIR` | Resolved relative to the project root, not the working directory |

## Tests

```powershell
pytest -q
```

Tests run against the database configured in `.env`; no second database is created.
Database tests use the `db_session` fixture, which wraps each test in a transaction
that is rolled back on teardown.

## Documentation

| Document | Contents |
|---|---|
| [docs/database.md](docs/database.md) | Full schema for all 22 tables, enumerations, relationships, ERD, integrity policy |

## Roles

Student · Housing Administration · Student Affairs · Maintenance Officer ·
Activity Officer · Cleaning Officer · Food Officer · Sports Officer ·
System Administrator

## API Groups

1. Authentication
2. Student & Application
3. Housing
4. Services
5. Complaint & Maintenance
6. Cleaning AI
7. Reports

## Status

Built in 21 sequential phases. Current position: **PHASE 1 — Project Initialization
complete**; PHASE 4 (applying the Alembic migration) is next and pending approval.
