"""D9 unit contracts: BFS and A* schedule search (pure, no DB)."""

import math
from datetime import date, timedelta

import pytest

from app.services.cleaning_ai import InfeasibleError, Task, solve_astar, solve_bfs


def make_tasks(rooms, days):
    base = date(2026, 9, 1)
    return [
        Task(base + timedelta(days=d), f"r{i}", f"room {i}")
        for d in range(days)
        for i in range(rooms)
    ]


def check_invariants(students, tasks, schedule):
    assert schedule.feasibility == 1.0
    assert len(schedule.student_of_task) == len(tasks)
    for task, sid in zip(tasks, schedule.student_of_task):
        assert sid in students
    per_day = {}
    for task, sid in zip(tasks, schedule.student_of_task):
        per_day.setdefault(task.day, []).append(sid)
    for day, sids in per_day.items():
        assert len(set(sids)) == len(sids), f"duplicate student on {day}"
    cap = min(math.ceil(len(tasks) / len(students)), len(per_day))
    assert max(schedule.loads.values()) <= cap
    assert sum(schedule.loads.values()) == len(tasks)


def test_bfs_is_deterministic_and_feasible():
    students = [f"s{i}" for i in range(4)]
    tasks = make_tasks(rooms=3, days=2)
    first = solve_bfs(students, tasks)
    second = solve_bfs(students, tasks)
    assert first.student_of_task == second.student_of_task
    check_invariants(students, tasks, first)


def test_astar_is_deterministic_feasible_and_no_worse_than_bfs():
    students = [f"s{i}" for i in range(4)]
    tasks = make_tasks(rooms=3, days=3)
    astar = solve_astar(students, tasks)
    bfs = solve_bfs(students, tasks)
    assert astar.student_of_task == solve_astar(students, tasks).student_of_task
    check_invariants(students, tasks, astar)
    assert astar.total_cost <= bfs.total_cost
    assert astar.fairness >= bfs.fairness - 1e-9


def test_astar_reaches_theoretical_optimum():
    """With 3 students / 6 tasks over 2 days the optimal max load is 2."""
    students = [f"s{i}" for i in range(3)]
    tasks = make_tasks(rooms=3, days=2)
    astar = solve_astar(students, tasks)
    assert astar.total_cost == 2
    assert max(astar.loads.values()) == 2


def test_unbalanced_instance_astar_balances():
    """5 tasks / 3 students over 2 days: optimum max load 2."""
    students = [f"s{i}" for i in range(3)]
    tasks = make_tasks(rooms=3, days=1) + [
        Task(date(2026, 9, 2), f"b{i}", f"room b{i}") for i in range(2)
    ]
    astar = solve_astar(students, tasks)
    bfs = solve_bfs(students, tasks)
    check_invariants(students, tasks, astar)
    assert astar.total_cost == 2
    assert astar.total_cost <= bfs.total_cost


def test_infeasible_day_is_rejected():
    students = [f"s{i}" for i in range(2)]
    tasks = make_tasks(rooms=5, days=1)
    with pytest.raises(InfeasibleError):
        solve_bfs(students, tasks)
    with pytest.raises(InfeasibleError):
        solve_astar(students, tasks)


def test_no_students_is_rejected():
    with pytest.raises(InfeasibleError):
        solve_bfs([], make_tasks(rooms=1, days=1))
    with pytest.raises(InfeasibleError):
        solve_astar([], make_tasks(rooms=1, days=1))


def test_larger_instance_stays_feasible():
    students = [f"s{i}" for i in range(6)]
    tasks = make_tasks(rooms=4, days=5)
    bfs = solve_bfs(students, tasks)
    astar = solve_astar(students, tasks)
    check_invariants(students, tasks, bfs)
    check_invariants(students, tasks, astar)
    assert astar.total_cost <= bfs.total_cost
