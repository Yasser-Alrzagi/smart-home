# Smart Student Housing — سكن بازرعة الطلابي

**All milestones are delivered: D1 foundation, D2 identity, D3 two-stage admissions, D4 room allocation and transfers, D5 services/support/attendance, D6 notifications, D7 daily attendance ledger, D8 role-scoped officer dashboards and D9 cleaning AI (BFS/A*) — in a fully Arabic browser portal.**

- 27 ORM tables: domain tables, identity/security, application history, and the housing structure.
- Identity, admission and **housing** HTTP APIs, health/readiness, and an Arabic browser portal at `/app` including a "غرفتي" student view and a full Housing Administration workspace.
- Student profile, required documents, Student Affairs review, Housing Administration decisions, **room allocation, transfers and ended-assignment history** are implemented. No public registration, attendance-records, officer dashboards, or BFS/A* implementation yet.
- Approved provisioning policy: **only the System Administrator creates accounts and assigns roles**. Other roles manage only their own account/session through self-service endpoints.

## D3: open the Arabic portal

After configuring `.env`, installing the updated runtime requirements and running
`alembic upgrade head`, start `python main.py` and visit **http://127.0.0.1:8000/app**.
The API welcome JSON at `/` remains available. No Node/npm build is needed for the UI.

Use the D2 bootstrap tool for a first administrator only. The administrator can create
Student, Student Affairs and Housing Administration accounts in the portal. Newly created
accounts must change their temporary password before performing normal work.

Approved policy: **Student Affairs reviews; Housing Administration decides**. Only National
ID and enrollment certificate are mandatory initially; university ID is optional. Staff may
request specific additional documents with a reason. Approval is not room allocation.

The new revision is `d3b7a21c8f04`, based on the published D2 main commit `249bc91`.
It preserves historical migrations, adds application history/versioning/snapshots and private
DB document content. New student profiles start as Applicant. D3 downgrade refuses D3 data;
never use downgrade as a production recovery shortcut.

Documents are stored as private DB blobs, not public file paths, and committed with their
metadata/history. Default max 5 MiB/file; PDF/JPEG/PNG only. Images are re-encoded; PDFs are
bounded and active/encrypted files rejected. This is not antivirus or authenticity checking.
DB/backup encryption and TLS remain deployment responsibilities. The legacy UPLOAD_DIR is
not used to expose these documents. See **[D3 policy and operations](docs/admissions-d3.md)**.

The UI keeps its token in page memory, never localStorage/sessionStorage/cookies. Reloading
requires login again. There are no seeded production/demo credentials in the archive.

## D4: room allocation and transfers

Housing Administration manages the structure (`floors` → `apartments` → `rooms`) and the assignment
lifecycle; students see their own room at `/app` under «غرفتي». Approval is never allocation and
allocation is never automatic.

| Rule | Behavior |
|---|---|
| Eligibility | Only students with an `Accepted` application; `Suspended`/`Terminated` are refused (409) |
| One active assignment | A second allocation for the same student is refused (409) |
| Capacity | Enforced under room row locks; over-capacity is refused (422); concurrent allocations to a full room cannot both succeed |
| Room status | Derived from occupancy (`available`/`partially_occupied`/`fully_occupied`); `maintenance`/`closed` are officer-declared and refuse new allocations |
| Transfer | Old assignment becomes `Transferred` with an end date; a new active assignment is created; source/target rooms are locked in sorted order |
| End | Assignment becomes `Ended`; the student returns to the eligible list; no deletion anywhere |
| History | First allocation moves `applicant` → `active` and records `student_status_history`; ending never silently changes the housing status |
| Audit | `housing.*` events with identifiers/numbers only (no names, no profile values) |

Endpoints (`/api/v1`): `GET/POST /housing/floors`, `GET/POST /housing/apartments`, `GET/POST /housing/rooms`,
`PATCH /housing/rooms/{id}`, `GET /housing/students/unassigned`, `GET/POST /housing/assignments`,
`POST /housing/assignments/{id}/transfer`, `POST /housing/assignments/{id}/end`, `GET /housing/me`.

D4 adds **no migration**: the housing tables already exist since D1, and `SCHEMA_HEAD` stays at
`d3b7a21c8f04`. Full Arabic policy and limitations: **[docs/housing-d4.md](docs/housing-d4.md)**.

## D5: services, support and attendance

Officers own their services and periods; students register while a period is open; complaints,
maintenance requests, permission requests, emergency reports and the documented absence log are
all handled through the Arabic portal at `/app`.

| Area | Behavior |
|---|---|
| Service ownership | Each service type belongs to fixed officer roles (`activity_officer` → Activity/Internet, `food_officer` → Food, `sports_officer` → Sports), enforced on every operation; duplicate type+name is refused (409) |
| Period lifecycle | `Upcoming` → `Open` → `Closed` → `Completed`; open/closed is the only reversible step |
| Registration | Only while `Open`, once per period (unique), and only while seats remain; the duplicate check runs before the capacity check (409 vs 422); students cancel their own registration; officers never delete |
| Concurrency | Named MySQL lock + `FOR UPDATE` row lock on the period: a two-thread race yields exactly `[201, 422]`, never over-capacity; the named lock is released inside the owning transaction (a stray release after rollback used to strand it on the pooled connection) |
| Complaints | Housing Administration lifecycle `Open` → `Under Review` → `Resolved` → `Closed`; resolution text is mandatory to resolve/close; no deletion |
| Maintenance | `Pending` → `Assigned` → `In Progress` → `Resolved` → `Closed`; a room may only be attached when it is the student's currently active assignment |
| Permissions | Student Affairs approves/rejects (`Pending` → `Approved`/`Rejected`, student cancel before decision); approval creates a `permission` absence with the same dates |
| Emergency reports | `Reported` → `Under Review` → `Verified` → `Closed`; an `emergency` absence is created only when the exit is verified (rule 9.2 — a report is not an absence until verified) |
| Absence log | Built only from permissions and verified emergencies, never written directly by students |
| Audit | `registration.*`, complaint/maintenance/permission/emergency events recorded in the same transaction as the change |

Endpoints (`/api/v1`): `GET/POST /services`, `PATCH /services/{id}`, `GET/POST /service-periods`,
`POST /service-periods/{id}/status`, `GET /service-periods/{id}/registrations`,
`POST /service-registrations`, `GET /service-registrations/me`,
`POST /service-registrations/{id}/cancel`, `GET/POST /complaints`, `GET /complaints/my`,
`POST /complaints/{id}/action`, `GET/POST /maintenance`, `GET /maintenance/my`,
`POST /maintenance/{id}/action`, `GET/POST /permissions`, `GET /permissions/my`,
`POST /permissions/{id}/decision`, `POST /permissions/{id}/cancel`, `POST /emergency`,
`GET /emergency/my`, `POST /emergency/{id}/action`, `GET /absences`, `GET /absences/my`.

D5 adds **no migration** either: the service, complaint, maintenance, permission, emergency and
absence tables already exist since D1, and `SCHEMA_HEAD` stays at `d3b7a21c8f04`.
Full Arabic policy and tested delivery: **[docs/services-d5.md](docs/services-d5.md)**,
**[docs/d5-results.md](docs/d5-results.md)** and **[docs/notifications-d6.md](docs/notifications-d6.md)**.

## D7: daily attendance ledger and unauthorized absences

Housing Administration records an attendance row per student per day (`Present` / `Late` /
`Absent` / `Excused`) in one bulk call; marking a day `Absent` without an approved permission or a
verified emergency exit covering that date creates a persistent `Unauthorized` absence
(`source = attendance:<record_id>`, once per record). Correcting a day later never deletes the
documented absence. Students read only their own ledger.

| Area | Behavior |
|---|---|
| Recording | One row per student per date (unique `student_id + record_date`); re-recording same day updates, it never duplicates |
| Unauthorized absence | Created automatically on `Absent` when no coverage: approved permission containing the date, or a same-day verified emergency report; deduplicated per attendance record (`absence_id` returned in the bulk response) |
| Coverage check | `permission_requests` approved + date in range, or `emergency_reports` verified on the same day — evaluated on the student's current records only |
| Ownership | Housing Administration writes and lists days; students get `my-ledger` only; any other role → 403; no update/delete endpoints at all |
| Audit | `attendance.record` with identifiers/date/status only, same transaction |
| Migration | `d7a1b2c3d4e5` adds `attendance_records`; `SCHEMA_HEAD` moved to `d7a1b2c3d4e5`; contract tests (tables, unique constraint, cascade/SET NULL, Alembic chain, `docs/database.md`) updated to 28 tables |

Endpoints (`/api/v1`): `POST /attendance/daily`, `GET /attendance/daily?record_date=`,
`GET /attendance/my-ledger`, `GET /attendance/students?q=`.
Full Arabic policy and tested delivery: **[docs/attendance-daily-d7.md](docs/attendance-daily-d7.md)**
and **[docs/d7-results.md](docs/d7-results.md)**.

## D8: officer dashboards

One read-only summary per role at `GET /dashboards/me`: overall numbers, items needing
attention, the latest items that role owns, and quick portal actions. No writes, no audit,
no schema change; the same fixed role→permission matrix decides what each role sees.

| Role | Sees |
|---|---|
| Student Affairs | applications under review, pending permission requests, pending emergency reports |
| Housing Administration | rooms, occupied, awaiting assignment, open complaints, today's absent (D7), ready-for-decision queue |
| Maintenance Officer | pending/assigned/in-progress/open maintenance requests |
| Activity/Food/Sports Officers | owned services, open/upcoming periods, total registrations |
| Cleaning Officer | cleaning cycles by status and pending assignments |
| System Administrator | accounts, active accounts, must-change-password, active sessions |

Endpoints: `GET /api/v1/dashboards/me`.
Full Arabic policy and tested delivery: **[docs/dashboards-d8.md](docs/dashboards-d8.md)**
and **[docs/d8-results.md](docs/d8-results.md)**.

## D9: cleaning AI (BFS/A*)

Cleaning Officer creates a cycle per floor and date range; every room of the floor per day is one
task shared among the resident students under two constraints (one task per student per day, a
fairness cap). Both algorithms run and are stored with metrics (cost, fairness, feasibility,
expanded nodes, milliseconds) so the officer compares and approves one; approval materializes the
assignments in the same transaction, activation notifies every assigned student (D6), and students
run their own tasks (start/complete, audited) while the officer may skip.

| Algorithm | Behavior |
|---|---|
| BFS | One layer per day; the least-loaded students take the day's tasks. Deterministic, cheap, balanced — not proven optimal |
| A* | Optimal search over day-level choices minimizing (max load, sum of squared loads) with an admissible heuristic; never worse than BFS; capped at 200k states |

Cycle lifecycle: `Draft` → `Optimizing` → `Approved` → `Active` → `Completed`; infeasible instances
(a day with more tasks than residents, or no residents) are refused with 422 and a clear reason.
Endpoints (`/api/v1`): `GET /cleaning/floors`, `GET/POST /cleaning/cycles`,
`GET /cleaning/cycles/{id}`, `POST /cleaning/cycles/{id}/optimize|approve|activate|complete`,
`GET /cleaning/my`, `POST /cleaning/my/{id}`, `POST /cleaning/assignments/{id}/skip`.
Full Arabic policy and tested delivery: **[docs/cleaning-d9.md](docs/cleaning-d9.md)**
and **[docs/d9-results.md](docs/d9-results.md)**.

## Stack and layout

Python 3.12/3.13 · FastAPI · SQLAlchemy 2 · Alembic · MySQL/MariaDB InnoDB · Argon2id · PyJWT/HS256.

```text
API -> policy/services -> repositories/ORM -> MySQL/MariaDB
```

Use `DatabaseSession` for HTTP dependencies and `session_scope()` for jobs/CLI. The D1
unit of work commits before a successful response is sent, and rolls back the complete
operation on failure. Repositories do not commit partial operations. Do not reuse the
request session in background tasks or streaming responses.

## Second platform — desktop client (Tkinter)

The portal is platform one (Web); `desktop_client/` is platform two (Desktop).
Both talk to the same REST API and share the same database — see
[desktop_client/README.md](desktop_client/README.md). Runs with stdlib only:

```bat
python desktop_client\main.py --api http://127.0.0.1:8000
```

## Reports / export API (JSON + XML)

`/api/v1/reports/*` returns JSON (default) or XML with `?format=xml`:
`GET /reports/overview`, `GET /reports/users` (System Administrator),
`GET /reports/applications` (staff roles). Full matrix:
[docs/course-advanced-programming.md](docs/course-advanced-programming.md).

## Local setup

Create a fresh virtual environment. Runtime dependencies are exact pins with hashes:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements.txt
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_hex(48))"
```

Put the generated signing key in `.env`, and set your local database credentials.
On POSIX use `source .venv/bin/activate` and `cp .env.example .env`.

Explicitly create a database/user for your local application. Required defaults:

```sql
CREATE DATABASE smart_students_home
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

The server storage engine must default to InnoDB. The reference server is MariaDB
11.8.6 on Linux. Windows/XAMPP 10.4.21 has not been directly tested; the old documentation
referred to that environment, not the new reference environment.

```text
alembic upgrade head
python -m tools.bootstrap_admin --username YOUR_ADMIN --email you@example.com
python main.py
```

The bootstrap tool prompts for a password twice. It is one-time only, refuses to run
if a System Administrator already exists, and never prints a password/token. Choose
a real strong password; no default account is shipped. For explicit automation only,
`--password-stdin` accepts one line from stdin; never put a password in command-line arguments.

The development server listens on `http://127.0.0.1:8000` with reload. This is **not** a
production server configuration. Interactive docs exist only with `DEBUG=True`.

## Upgrading the D1 delivery

1. Back up any data you want to keep and review the incremental patch.
2. Reinstall dependencies from `requirements.txt` in a clean environment. PyJWT replaces
   python-jose; the old ecdsa/rsa/pyasn1 chain is no longer in the runtime lock.
3. Update `.env`: **change the old `ACCESS_TOKEN_EXPIRE_MINUTES=1440` to 30** (allowed 1–60).
   Review the new issuer/audience, session-cap, and login-limit settings in the example.
4. Run `alembic upgrade head` to revision `d2a5c19f0b72`.
5. Sign in again: D1 tokens are deliberately invalid under the D2 claim/session contract.

The new migration adds `users.auth_version`, `users.must_change_password`, `account_guard`,
`auth_sessions`, `audit_events`, and `login_rate_buckets`. Existing user records and password
hashes are preserved. Existing users are not forced to reset by the migration; new admin-
provisioned accounts and admin password resets require a password change.

The original migration was not rewritten. D2 downgrade removes new security tables and
therefore their session/audit data; **do not treat downgrade as a safe production recovery
strategy**. MySQL DDL is not protected by ordinary transaction rollback. Use backups and
review a recovery plan if an applied migration is interrupted.

## Account and session API

Paths below are under `/api/v1`. Send the token as `Authorization: Bearer <token>`.
Never put tokens in URLs. Login is form-encoded username/password, not a JSON body.

| Method | Path | Access / effect |
|---|---|---|
| POST | `/auth/login/access-token` | Login, with persistent attempt limits |
| GET | `/auth/users/me` | Own account |
| PATCH | `/auth/users/me` | Own username/email only; privileged fields rejected |
| POST | `/auth/change-password` | Current password + different new password; revokes all sessions |
| POST | `/auth/logout` | Revoke current session |
| POST | `/auth/logout-all` | Revoke all own sessions |
| GET | `/auth/sessions` | Active own sessions only |
| DELETE | `/auth/sessions/{session_id}` | Revoke an owned session, not delete its record |
| POST | `/users` | System Administrator creates an account; forced initial password change |
| GET | `/users` | Administrator list, bounded pagination |
| GET | `/users/{user_id}` | Administrator account read |
| PATCH | `/users/{user_id}` | Administrator username/email/role/is_active update |
| POST | `/users/{user_id}/reset-password` | Administrator resets another account; force change and revoke sessions |
| GET | `/audit-events` | System Administrator only |

`/`, `/health`, `/ready` are public system operations. `/health` checks connectivity;
`/ready` checks the expected schema revision, singleton guard, and identity/admission tables/columns.
A ready identity backend is not a claim that housing workflows or deployment safety are complete.

No public registration and no account DELETE endpoint. The administrator cannot demote/
disable themselves. Administrative role/state changes are serialized and preserve an active
administrator. Concurrent conflicts can return 409; read current state before retrying.

Full Arabic policy and limitations: **[docs/identity-policy.md](docs/identity-policy.md)**.

## Security behavior and remaining operational work

- New/changed passwords: 12–256 UTF-8 characters, at most 1024 bytes; never trimmed or truncated.
- New hashes: Argon2id (64 MiB, 3 iterations, 4 lanes). Tune/measure production capacity.
- Legacy bcrypt: verify only up to 72 bytes, then rehash on successful active login. Longer
  legacy passwords need an authorized admin reset, not acceptance of their truncated prefix.
- Default access lifetime 30 minutes; max five active sessions. Required exp/iat/sub/jti/ver/
  type/iss/aud and an active matching DB session. No refresh tokens or anonymous recovery API.
- Password/role/activation changes revoke all sessions. Re-enabling does not restore old tokens.
- Default limits: 30 attempts/IP/60 seconds, 8 attempts/(account, IP)/300 seconds, including
  successful attempts. Persistent atomic DB counters survive failed request rollbacks.
- No global victim-account lock across other IPs. This reduces lockout abuse but is not complete
  protection against distributed guessing. Configure limits for shared NATs and add MFA as needed.
- Do not trust arbitrary forwarded headers; configure trusted proxy IPs in the ASGI server.
- Events exclude passwords/tokens/raw IPs/profile values. ORM event mutation/deletion is blocked;
  a privileged DBA/direct SQL is outside that protection. Retention duration is still to be approved.
- `python -m tools.prune_login_limits` is a dry-run; add `--apply` to remove expired counters only.
  Schedule it explicitly. There is no automatically running scheduler or automatic audit deletion.
- TLS/reverse proxy, backup/restore, MFA, breached-password policy, production hardening and formal
  security testing are not provided by this identity milestone.

## Configuration

Normal application settings read the project-root `.env`; unknown dotenv keys are rejected.
Missing/placeholder/short signing keys fail startup. Secret settings and password/token models
hide their secrets in repr, and API validation responses omit input values.

`DATABASE_URL`, if explicitly supplied, overrides all `DB_*` settings. It is commented out in
the example so editing DB_PASSWORD takes effect. DB_* uses SQLAlchemy URL escaping; a full
URL must already percent-encode credentials. Alembic handles the percent interpolation safely.
CORS requires explicit nonempty origins; wildcards are rejected. Development root/blank DB
examples are not production permissions. Use a least-privileged account in deployment.

## Tests — only dedicated disposable databases

```text
python -m pip install --require-hashes -r requirements-dev.txt
python -m pytest -q
```

Without TEST_DATABASE_URL, DB-independent tests run and DB tests are explicitly skipped.
The application `.env` is ignored and a test signing key is generated. The test URL guard
permits mysql+pymysql/mariadb+pymysql, database names `smart_home_test` or
`smart_home_test_<lowercase-alphanumeric-suffix>`, and hosts localhost/127.0.0.1/::1/mysql/mariadb.

To run all tests, explicitly create two **disposable** schemas with the required charset/
collation and a test-only user. On PowerShell:

```powershell
$env:TEST_DATABASE_URL="mysql+pymysql://TEST_USER:ENCODED_TEST_PASSWORD@127.0.0.1/smart_home_test?charset=utf8mb4"
$env:TEST_MIGRATION_DATABASE_URL="mysql+pymysql://TEST_USER:ENCODED_TEST_PASSWORD@127.0.0.1/smart_home_test_migration?charset=utf8mb4"
$env:RUN_MIGRATION_CYCLE="1"
python -m tools.test_database
python -m pytest -q --cov=app --cov=main --cov-branch
```

On POSIX use `export NAME='value'`. Never use a real/student database even if it is named
like a test database. D2 test fixtures clear security events/sessions/rate counters and remove
new synthetic users; do not keep data worth preserving in those test schemas.

The migration cycle requires a distinct empty scratch schema (the known singleton seed is
allowed). It tests both an empty full cycle and preservation of a synthetic existing D1 account
through upgrade/downgrade. DDL is destructive and not covered by the transaction fixture.

The fixed initial schema is retained in `tests/fixtures/initial_schema.json`: new revisions
are compared as a whole against current models, without modifying historical schema to make
an initial-revision test pass. Live tests also verify FK rules, storage/collation and drift.

## Dependency locks and CI

`pyproject.toml` declares dependencies; `uv.lock` is the universal lock. Requirements files
are generated pins with hashes/platform markers. Do not edit them manually.

```text
python -m pip install uv==0.12.10
uv lock --check
ruff check .
```

To intentionally update, use `uv lock --upgrade`, regenerate exports below, and rerun tests:

```text
uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file requirements.txt
uv export --frozen --no-emit-project --format requirements-txt --output-file requirements-dev.txt
```

CI is configured in `.github/workflows/tests.yml` for Python 3.12/3.13 with disposable MariaDB
11.8.6, locked installs, Ruff, and real migration cycles. Local test results are not a claim of
an executed GitHub Actions run; no remote push has been performed by the assistant.

### Real browser regression

For the same explicitly configured disposable TEST_DATABASE_URL, after upgrading its schema:

```text
python -m playwright install chromium
python -m tools.ui_smoke
```

On Linux, browser OS dependencies may require `python -m playwright install --with-deps chromium`.
This test creates temporary synthetic users, runs a real three-role workflow with two documents,
checks download/XSS/mobile/session-storage behavior, and cleans its data. It starts and stops a
local test server itself. Screenshots go to ignored `artifacts/ui/` by default.

CI runs this browser test on Python 3.13 in addition to backend tests on both versions. Actions
are pinned to official Node 24 commits to replace the older Node 20 warning-generating actions.
The assistant has not run the new D3 workflow on GitHub or pushed this branch.

## Project documentation

- [D9 cleaning AI policy — Arabic](docs/cleaning-d9.md)
- [D8 dashboard policy — Arabic](docs/dashboards-d8.md)
- [D7 daily attendance policy — Arabic](docs/attendance-daily-d7.md)
- [D6 notification policy — Arabic](docs/notifications-d6.md)
- [D5 services/support/attendance policy — Arabic](docs/services-d5.md)
- [D9 tested delivery results — Arabic](docs/d9-results.md)
- [D8 tested delivery results — Arabic](docs/d8-results.md)
- [D7 tested delivery results — Arabic](docs/d7-results.md)
- [D5 tested delivery results — Arabic](docs/d5-results.md)
- [D4 housing policy — Arabic](docs/housing-d4.md)
- [D3 admission policy and UI — Arabic](docs/admissions-d3.md)
- [D3 tested delivery results — Arabic](docs/d3-results.md)

- [Database and migration design](docs/database.md)
- [D2 account/session policy — Arabic](docs/identity-policy.md)
- [D2 delivery notes — Arabic](docs/identity-d2.md)
- [Historical D1 delivery](docs/foundation-d1.md)

Historical generator text and `_offline_head.sql` are not active migrations. The old assembler
refuses to overwrite revisions; its source is archived as non-executable text under
`alembic/superseded/`. D4 (room allocation and transfers) and D5 (services, complaints,
maintenance, permissions/absences and emergency reports, with Arabic portal views) are delivered;
D6 (notifications mailbox with event-driven delivery), D7 (daily attendance ledger with
automatic unauthorized absences), D8 (role-scoped officer dashboards) and D9 (cleaning AI with
BFS/A* optimization) are delivered — the full remaining scope is closed.
