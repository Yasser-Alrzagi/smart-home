SMART STUDENT HOUSING MANAGEMENT SYSTEM
AI-Optimized Cleaning Task Scheduling (BFS + A*)
Artificial Intelligence Course Project — 2026/2027
====================================================

WHAT IS THIS
------------
A complete software system for managing a university student housing complex:
housing applications and decisions, room allocation, services (food, laundry,
activity, maintenance, cleaning), support/complaints, daily attendance and
unauthorized absence alerts, notifications, role-scoped dashboards, and an AI
module that schedules daily cleaning tasks for floor residents using two
search algorithms implemented from scratch: BFS and A*.

It exposes 12 REST API modules (auth, users, admissions, housing, facilities,
support, attendance, daily attendance, notifications, dashboards, cleaning,
reports) consumed by two platforms sharing one MySQL database:
  1) Web portal (Arabic RTL, browser)
  2) Desktop client (Tkinter, standard library only)

HOW TO RUN (Windows, from this folder)
--------------------------------------
1. Python 3.12 or 3.13 required.
2. Create the database (MySQL/MariaDB):
       CREATE DATABASE smart_students_home
         CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
3. Install dependencies:
       python -m venv .venv
       .venv\Scripts\activate.bat
       python -m pip install --require-hashes -r requirements.txt
4. Configure:
       copy .env.example .env
       (set a real SECRET_KEY and your DB credentials in .env)
5. Migrate and create the first administrator account (one-time):
       python -m alembic upgrade head
       python -m tools.bootstrap_admin --username admin --email you@example.com
6. Start the server:
       python main.py
   Open http://127.0.0.1:8000/app in the browser (web platform).
7. Desktop platform (second window):
       python desktop_client\main.py

NOTE: There is no public registration. The System Administrator creates all
accounts inside the portal (Accounts page) or the desktop client.

AI MODULE
---------
Cleaning (D9): POST /api/v1/cleaning/cycles/{id}/optimize with
{"algorithm": "bfs"} or {"algorithm": "astar"} → compare runs by nodes
expanded, runtime, max load and fairness.

TESTS
-----
524 tests pass (unit + integration) against a dedicated disposable database:
    pytest -q            (with TEST_DATABASE_URL set to a disposable schema)

REPORT AND DOCS
---------------
docs/course-ai.md           AI compliance matrix + report skeleton
docs/ai-course-proposal.md  Phase-One proposal (Week 7)
docs/cleaning-d9.md         Cleaning AI policy and design
docs/d9-results.md          BFS vs A* evaluation results
docs/course-advanced-programming.md  Advanced Programming compliance


----
GROUP NAMES (as required by the course submission)
1. ياسر عبدالسلام الرزاقي
2. شهاب الدين فهد رعدان
