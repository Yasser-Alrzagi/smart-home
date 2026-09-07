"""D9 cleaning optimization: BFS and A* schedule search.

Pure functions over a tiny problem model — no DB, no ORM — so the algorithms
are unit-testable in isolation.

Problem
-------
A cleaning cycle covers one floor for a date range. Every day, each room of
the floor is one cleaning task. Tasks are assigned to the resident students
of that floor. Constraints for both algorithms:
  * at most one task per student per day
  * at most ``cap`` tasks per student over the whole cycle, where
    ``cap = min(ceil(T / M), number of days)``

Algorithms
----------
* BFS — breadth-first layer expansion: one layer per day; within a layer the
  least-loaded students take that day's tasks. Deterministic and cheap; the
  result is balanced but not proven optimal.
* A*  — optimal search minimizing ``(max load, sum of squared loads)``
  lexicographically. The heuristic is a lower bound on both components
  (ceil of remaining tasks per student for the max term and a convexity bound
  for the squared term), so the first completed state popped is optimal.

Both return the same ``Schedule`` shape so the portal can compare runs.
"""

import heapq
import math
import time
from collections import defaultdict
from itertools import combinations


class Task:
    __slots__ = ("day", "key", "description")

    def __init__(self, day, key, description):
        self.day = day
        self.key = key
        self.description = description


class Schedule:
    __slots__ = ("student_of_task", "loads", "nodes", "elapsed", "total_cost",
                 "fairness", "feasibility")

    def __init__(self, student_of_task, loads, nodes, elapsed, total_cost,
                 fairness, feasibility):
        self.student_of_task = student_of_task  # list[sid] aligned with tasks
        self.loads = loads                      # dict sid -> assigned count
        self.nodes = nodes
        self.elapsed = elapsed
        self.total_cost = total_cost            # max load
        self.fairness = fairness                # 1 - (max-min)/max(T, 1)
        self.feasibility = feasibility          # 0.0 / 1.0

    def to_dict(self):
        return {
            "student_of_task": self.student_of_task,
            "loads": self.loads,
            "nodes_expanded": self.nodes,
            "execution_time": self.elapsed,
            "total_cost": self.total_cost,
            "fairness": self.fairness,
            "feasibility": self.feasibility,
        }


class InfeasibleError(ValueError):
    """The instance violates a hard constraint (e.g. a day has more tasks
    than resident students)."""


def _feasibility_check(counts, students):
    m = len(students)
    if m == 0:
        raise InfeasibleError("no students available for the cycle")
    for day, r in counts.items():
        if r > m:
            raise InfeasibleError(f"day {day} has {r} tasks but only {m} students")


def _metrics(student_of_task, students, task_count):
    loads = {sid: 0 for sid in students}
    for sid in student_of_task:
        loads[sid] += 1
    maximum = max(loads.values()) if students else 0
    minimum = min(loads.values()) if students else 0
    fairness = 1.0 if task_count == 0 else 1.0 - (maximum - minimum) / task_count
    return loads, maximum, fairness


def _group_by_day(tasks):
    groups = defaultdict(list)
    for index, task in enumerate(tasks):
        groups[task.day].append(index)
    return groups


# ------------------------------------------------------------------ BFS
def solve_bfs(students, tasks):
    """Breadth-first layered assignment: one layer per day."""
    started = time.perf_counter()
    by_day = _group_by_day(tasks)
    _feasibility_check({day: len(idx) for day, idx in by_day.items()}, students)
    m = len(students)
    cap = min(math.ceil(len(tasks) / m), len(by_day))
    student_of_task = [None] * len(tasks)
    frontier = [(0, index, sid) for index, sid in enumerate(students)]
    heapq.heapify(frontier)
    for day in sorted(by_day):
        indexes = sorted(by_day[day])
        # One layer: the day's tasks go to the least-loaded students.
        chosen = [heapq.heappop(frontier) for _ in indexes]
        for (load, order, sid), index in zip(chosen, indexes):
            if load >= cap:  # cannot happen with the cap invariant
                raise InfeasibleError("BFS cap violated")
            student_of_task[index] = sid
        for load, order, sid in chosen:
            heapq.heappush(frontier, (load + 1, order, sid))
    if any(sid is None for sid in student_of_task):
        raise InfeasibleError("BFS left a task unassigned")
    loads, maximum, fairness = _metrics(student_of_task, students, len(tasks))
    return Schedule(
        student_of_task=student_of_task,
        loads=loads,
        nodes=len(tasks),
        elapsed=time.perf_counter() - started,
        total_cost=maximum,
        fairness=fairness,
        feasibility=1.0,
    )


# ------------------------------------------------------------------ A*
def solve_astar(students, tasks, node_cap=200000):
    """Optimal schedule under (max load, sum of squared loads)."""
    started = time.perf_counter()
    by_day = _group_by_day(tasks)
    counts = {day: len(indexes) for day, indexes in by_day.items()}
    _feasibility_check(counts, students)
    days = sorted(counts)
    m = len(students)
    total = len(tasks)
    cap = min(math.ceil(total / m), len(days))

    W = 10 ** 6  # dominates any reasonable squared-load sum

    def g_of(loads):
        return max(loads) * W + sum(x * x for x in loads)

    def h_of(loads, k):
        """Admissible lower bound on the g increase for the remaining days."""
        remaining = sum(counts[d] for d in days[k + 1:])
        if remaining <= 0:
            return 0
        max_gain = math.ceil(remaining / m)  # lower bound on max load gain
        sq_gain = remaining * remaining // m  # convexity bound on sumsq gain
        return max_gain * W + sq_gain

    start = tuple(0 for _ in students)
    # (f, g, -day_index, loads, path_combos)
    heap = [(h_of(start, -1), 0, 0, start, ())]
    best_g = {start: 0}
    nodes = 0
    goal_combos = None
    while heap:
        f, g, neg_k, loads, combos = heapq.heappop(heap)
        k = -neg_k
        if best_g.get(loads, 10 ** 18) < g:
            continue
        nodes += 1
        if nodes > node_cap:
            break
        if k == len(days):
            goal_combos = combos
            break
        r = counts[days[k]]
        for combo in combinations(range(m), r):
            if any(loads[j] + 1 > cap for j in combo):
                continue
            new_loads = list(loads)
            for j in combo:
                new_loads[j] += 1
            nlt = tuple(new_loads)
            g2 = g_of(nlt)
            if best_g.get(nlt, 10 ** 18) <= g2:
                continue
            best_g[nlt] = g2
            f2 = g2 + h_of(nlt, k)
            heapq.heappush(heap, (f2, g2, -(k + 1), nlt, combos + (combo,)))

    if goal_combos is None:
        raise RuntimeError("A* did not finish within the node budget")

    student_of_task = _materialize(students, tasks, days, counts, goal_combos)
    loads, maximum, fairness = _metrics(student_of_task, students, total)
    return Schedule(
        student_of_task=student_of_task,
        loads=loads,
        nodes=nodes,
        elapsed=time.perf_counter() - started,
        total_cost=maximum,
        fairness=fairness,
        feasibility=1.0,
    )


def _materialize(students, tasks, days, counts, combos):
    """Map the optimal per-day student sets to individual tasks.

    Deterministic: within a day, the student with the least load so far takes
    the earliest task (ties by student order).
    """
    student_of_task = [None] * len(tasks)
    by_day = _group_by_day(tasks)
    loads = {sid: 0 for sid in students}
    for day, combo in zip(days, combos):
        day_students = [students[j] for j in combo]
        indexes = sorted(by_day[day])
        # Order day's students by (current load, index) so the assignment is
        # stable and balanced within the day too.
        day_students.sort(key=lambda sid: (loads[sid], students.index(sid)))
        for sid, index in zip(day_students, indexes):
            student_of_task[index] = sid
            loads[sid] += 1
    if any(sid is None for sid in student_of_task):
        raise InfeasibleError("reconstruction left a task unassigned")
    return student_of_task
