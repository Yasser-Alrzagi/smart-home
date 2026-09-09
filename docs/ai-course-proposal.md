# AI Course Project Proposal — Phase One (Week 7)

**Project title:** AI-Optimized Cleaning Task Scheduling for a University Student Housing System

**Course:** Artificial Intelligence — College of Computer & Information Technology, 2026/2027

---

## 1. Project description

Student housing floors need daily cleaning: every day, each room of a floor is
one cleaning task, and tasks must be distributed among the resident students.
Doing this by hand produces unfair or infeasible schedules (a student gets too
many rooms, or no feasible assignment exists on a given day).

We build an **AI scheduler** that, given a floor, its rooms and its residents,
generates the cleaning schedule for a whole cycle (one floor × a date range)
under two hard constraints: **at most one task per student per day**, and **at
most `cap = min(⌈T/M⌉, days)` tasks per student over the whole cycle** (T =
tasks, M = students). The system is part of the "Smart Student Housing"
platform: cleaning officers approve, activate and complete cycles, and every
student sees his/her tasks, all through a bilingual Arabic web portal and a
desktop client.

## 2. Selected AI algorithms

Both algorithms are **implemented by us** (no external AI services, no ready-made
models); they are the core of the solution, not a supporting feature:

| Algorithm | How it works | Why |
|---|---|---|
| **BFS** | Breadth-first layer expansion: one layer per day; within a day, the least-loaded students receive that day's tasks. Deterministic and fast. | Baseline; proves feasibility and gives a balanced schedule; cheap for large floors. |
| **A\*** | Optimal search on the load vector, minimizing **lexicographically (max load, sum of squared loads)**. Priority queue keyed by `f = g + h`; `h` is an admissible lower bound (remaining tasks per student + a convexity bound on the squared term), so the first goal popped is optimal. | Guarantees the fairest schedule and lets us measure the exact quality gain over BFS. |

Both return the same schedule shape, so the portal can run and **compare** them
on identical inputs.

## 3. Dataset and preprocessing

No external dataset is needed — this is a **search** problem over the system's
own data: floors, rooms and resident students stored in MySQL. Preprocessing:
extract a floor's rooms and active residents for the cycle → build the day→tasks
grouping → feasibility check (a cycle with more tasks on a day than residents is
rejected up front). A small benchmark set of floor sizes (e.g., 1–20 students,
1–40 rooms, 1–7 days) is generated to evaluate both algorithms.

## 4. Evaluation

For every instance we measure and compare BFS vs A*:

- `nodes` — search effort (BFS: number of tasks; A*: states expanded),
- `elapsed` — runtime,
- `total_cost` — the maximum load (fairness of the busiest student),
- `fairness` — `1 − (max − min) / tasks`, a 0–1 balance score.

These metrics are appropriate because the objective is load balancing, not
classification accuracy: they show both the **cost of optimality** (A* expands
more states) and its **benefit** (lower max load / better balance).

## 5. GUI type

Web application (Arabic RTL portal, FastAPI + browser) **and** a desktop client
(Tkinter) — both call the same REST API (`/api/v1/cleaning/*`), visualize the
schedule and let the officer run/compare BFS and A*.

## 6. Technologies

Python 3.13 · FastAPI · SQLAlchemy 2 · MySQL/MariaDB · Tkinter · PyJWT (JWT) ·
pytest (unit + integration; **524 tests passing**).

## 7. References

1. Russell, S. & Norvig, P. — *Artificial Intelligence: A Modern Approach*, 4th
   ed., ch. 3 (uninformed & informed search).
2. Project internal documentation: `docs/cleaning-d9.md`, `docs/d9-results.md`,
   `app/services/cleaning_ai.py`.

## 8. Team members

| Name | ID | Role / contribution |
|---|---|---|
| (name) | (id) | (e.g., algorithms A*, evaluation, UI) |
| (name) | (id) | (…) |
| (name) | (id) | (…) |

*Individual work is preferred; group size ≤ 3. All code is explained and
defended during the final demonstration.*

## 9. Brief implementation plan

1. Data model: floors, rooms, cleaning cycles, tasks (done — MySQL schema).
2. Core: `solve_bfs` + `solve_astar` in one pure module (done).
3. REST: `/cleaning/cycles`, `/optimize`, `/approve`, `/activate`, `/complete`
   (done), plus `/reports/*` export (JSON/XML).
4. UI: web portal (done) + desktop client (done).
5. Evaluation: benchmark runner + comparison tables (partial; final tables in
   the Week 11 report).
6. Final: documentation, screenshots, live demo.
