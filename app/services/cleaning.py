"""D9 cleaning workflow: cycles → optimization (BFS/A*) → approval → execution.

Only the Cleaning Officer orchestrates a cycle. Each optimization run is
stored with its metrics (both algorithms can be compared); approving a run
materializes its schedule into ``cleaning_assignments`` inside the same
transaction, then the cycle can be activated (assigned students are
notified) and later completed. Students touch only their own assignments.
"""

import json
import uuid
from datetime import date, timedelta

from sqlalchemy import func, select

from app.core.errors import AppError
from app.models import (
    Apartment,
    CleaningAssignment,
    CleaningCycle,
    AIOptimizationRun,
    Floor,
    Room,
    RoomAssignment,
    Student,
    utcnow,
)
from app.models.enums import (
    AIAlgorithm,
    CleaningAssignmentStatus as CAS,
    CleaningCycleStatus as CCS,
    RoomAssignmentStatus,
    UserRole as R,
)
from app.services.accounts import account_write
from app.services.audit import record_event
from app.services.cleaning_ai import InfeasibleError, Task, solve_astar, solve_bfs
from app.services.notifications import notify_role, notify_user
from app.services.sessions import lock_self

MAX_TASKS = 1000


def _officer_ready(ctx):
    if ctx.user.role != R.cleaning_officer:
        raise AppError(403, "Cleaning Officer access required")


def _student_ready(ctx):
    if ctx.user.role != R.student:
        raise AppError(403, "Student access required")


def _floor_dict(floor):
    return dict(
        floor_id=floor.floor_id,
        building_name=floor.building_name,
        floor_number=floor.floor_number,
    )


def list_floors(db, ctx):
    _officer_ready(ctx)
    rows = db.scalars(
        select(Floor).order_by(Floor.building_name, Floor.floor_number)
    ).all()
    return [_floor_dict(f) for f in rows]


# ---------------------------------------------------------------- cycles
@account_write
def create_cycle(db, ctx, data):
    _officer_ready(ctx)
    actor = lock_self(db, ctx)
    _officer_ready(ctx)
    floor = db.get(Floor, data.floor_id)
    if floor is None:
        raise AppError(422, "Unknown floor")
    if data.end_date < data.start_date:
        raise AppError(422, "End date must not be before start date")
    cycle = CleaningCycle(
        cycle_id=str(uuid.uuid4()),
        floor_id=floor.floor_id,
        start_date=data.start_date,
        end_date=data.end_date,
        status=CCS.draft,
        created_by=actor.user_id,
    )
    db.add(cycle)
    db.flush()
    record_event(
        db, "cleaning.cycle.create", actor=actor,
        details={"cycle_id": cycle.cycle_id, "student_id": None, "date": data.start_date.isoformat()},
    )
    return _cycle_dict(db, cycle)


def list_cycles(db, ctx, offset=0, limit=20):
    _officer_ready(ctx)
    query = select(CleaningCycle)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(CleaningCycle.start_date.desc(), CleaningCycle.cycle_id)
        .offset(offset).limit(limit)
    ).all()
    return dict(items=[_cycle_dict(db, c) for c in rows], total=total, offset=offset, limit=limit)


def get_cycle(db, ctx, cycle_id):
    _officer_ready(ctx)
    cycle = db.get(CleaningCycle, cycle_id)
    if cycle is None:
        raise AppError(404, "Cycle not found")
    runs = db.scalars(
        select(AIOptimizationRun).where(
            AIOptimizationRun.cycle_id == cycle.cycle_id
        ).order_by(AIOptimizationRun.created_at)
    ).all()
    assignments = db.scalars(
        select(CleaningAssignment).where(
            CleaningAssignment.cycle_id == cycle.cycle_id
        ).order_by(CleaningAssignment.assignment_date, CleaningAssignment.task_description)
    ).all()
    return dict(
        **_cycle_dict(db, cycle),
        runs=[_run_dict(r, count_task(db, r)) for r in runs],
        assignments=[_assignment_dict(db, a) for a in assignments],
    )


def _cycle_dict(db, cycle):
    assignments = db.scalar(
        select(func.count()).select_from(CleaningAssignment).where(
            CleaningAssignment.cycle_id == cycle.cycle_id
        )
    ) or 0
    floor = db.get(Floor, cycle.floor_id)
    return dict(
        cycle_id=cycle.cycle_id,
        building_name=floor.building_name if floor else "—",
        floor_number=floor.floor_number if floor else "—",
        start_date=cycle.start_date,
        end_date=cycle.end_date,
        status=cycle.status,
        assignments_count=assignments,
        created_at=cycle.created_at if hasattr(cycle, "created_at") else None,
    )


# ---------------------------------------------------------------- optimize
def _resident_students(db, cycle):
    """Students with an active assignment on the cycle's floor, by name."""
    rows = db.execute(
        select(Student)
        .join(RoomAssignment, RoomAssignment.student_id == Student.student_id)
        .join(Room, Room.room_id == RoomAssignment.room_id)
        .join(Apartment, Apartment.apartment_id == Room.apartment_id)
        .where(
            Apartment.floor_id == cycle.floor_id,
            RoomAssignment.status == RoomAssignmentStatus.active,
        )
        .order_by(Student.full_name, Student.student_id)
        .distinct()
    ).scalars().all()
    return rows


def _build_tasks(db, cycle):
    rooms = db.scalars(
        select(Room)
        .join(Apartment, Apartment.apartment_id == Room.apartment_id)
        .where(Apartment.floor_id == cycle.floor_id)
        .order_by(Room.room_number, Room.room_id)
    ).all()
    if not rooms:
        raise AppError(422, "No rooms on this floor")
    end = cycle.end_date or cycle.start_date
    tasks = []
    day = cycle.start_date
    while day <= end:
        for room in rooms:
            tasks.append(Task(day, room.room_id, f"تنظيف الغرفة {room.room_number}"))
        day += timedelta(days=1)
    if len(tasks) > MAX_TASKS:
        raise AppError(422, f"Too many tasks ({len(tasks)}); max {MAX_TASKS}")
    return tasks, rooms


@account_write
def optimize_cycle(db, ctx, cycle_id, algorithm):
    _officer_ready(ctx)
    actor = lock_self(db, ctx)
    _officer_ready(ctx)
    cycle = db.get(CleaningCycle, cycle_id)
    if cycle is None:
        raise AppError(404, "Cycle not found")
    if cycle.status == CCS.active or cycle.status == CCS.completed:
        raise AppError(409, "Cycle already activated or completed")
    students = _resident_students(db, cycle)
    tasks, rooms = _build_tasks(db, cycle)
    student_ids = [s.student_id for s in students]
    if not student_ids:
        raise AppError(422, "No resident students on this floor; the cycle cannot be scheduled")
    try:
        if algorithm == AIAlgorithm.astar:
            schedule = solve_astar(student_ids, tasks)
        else:
            schedule = solve_bfs(student_ids, tasks)
    except InfeasibleError as exc:
        raise AppError(422, str(exc)) from exc
    summary = {
        "tasks": [
            {
                "day": t.day.isoformat(),
                "room_id": t.key,
                "description": t.description,
                "student_id": schedule.student_of_task[i],
            }
            for i, t in enumerate(tasks)
        ],
        "loads": schedule.loads,
    }
    run = AIOptimizationRun(
        run_id=str(uuid.uuid4()),
        cycle_id=cycle.cycle_id,
        algorithm=algorithm,
        total_cost=schedule.total_cost,
        fairness_score=round(schedule.fairness, 4),
        feasibility_rate=round(schedule.feasibility, 4),
        nodes_expanded=schedule.nodes,
        execution_time=round(schedule.elapsed * 1000, 2),  # milliseconds
        result_summary=json.dumps(summary, ensure_ascii=True, sort_keys=True),
    )
    db.add(run)
    cycle.status = CCS.optimizing
    db.flush()
    record_event(
        db, "cleaning.optimize", actor=actor,
        details={
            "cycle_id": cycle.cycle_id,
            "run_id": run.run_id,
            "algorithm": algorithm.value,
            "task_count": len(tasks),
            "count": len(student_ids),
        },
    )
    return _run_dict(run, len(tasks))


def _run_dict(run, task_count):
    return dict(
        run_id=run.run_id,
        cycle_id=run.cycle_id,
        algorithm=run.algorithm,
        total_cost=run.total_cost,
        fairness_score=run.fairness_score,
        feasibility_rate=run.feasibility_rate,
        nodes_expanded=run.nodes_expanded,
        execution_time=run.execution_time,
        task_count=task_count,
        created_at=run.created_at,
    )


def count_task(db, run):
    if not run.result_summary:
        return 0
    try:
        return len(json.loads(run.result_summary).get("tasks", []))
    except (ValueError, TypeError):
        return 0


# ---------------------------------------------------------------- approval
@account_write
def approve_cycle(db, ctx, cycle_id, run_id):
    _officer_ready(ctx)
    actor = lock_self(db, ctx)
    _officer_ready(ctx)
    cycle = db.get(CleaningCycle, cycle_id)
    if cycle is None:
        raise AppError(404, "Cycle not found")
    if cycle.status not in (CCS.draft, CCS.optimizing):
        raise AppError(409, "Only a draft or optimizing cycle can be approved")
    run = db.scalar(
        select(AIOptimizationRun).where(
            AIOptimizationRun.run_id == run_id,
            AIOptimizationRun.cycle_id == cycle.cycle_id,
        )
    )
    if run is None:
        raise AppError(404, "Run not found for this cycle")
    try:
        summary = json.loads(run.result_summary or "{}")
    except ValueError as exc:
        raise AppError(422, "Run summary is unreadable") from exc
    # Replace any previous materialization (re-approval).
    for old in db.scalars(
        select(CleaningAssignment).where(CleaningAssignment.cycle_id == cycle.cycle_id)
    ).all():
        db.delete(old)
    db.flush()
    for entry in summary.get("tasks", []):
        db.add(CleaningAssignment(
            assignment_id=str(uuid.uuid4()),
            cycle_id=cycle.cycle_id,
            student_id=entry["student_id"],
            task_description=entry.get("description", "مهمة نظافة"),
            assignment_date=date.fromisoformat(entry["day"]),
            status=CAS.pending,
        ))
    run.approved_by = actor.user_id
    cycle.status = CCS.approved
    db.flush()
    record_event(
        db, "cleaning.approve", actor=actor,
        details={"cycle_id": cycle.cycle_id, "run_id": run.run_id,
                 "algorithm": run.algorithm.value, "student_id": None,
                 "count": len(summary.get("tasks", []))},
    )
    return _cycle_dict(db, cycle)


@account_write
def activate_cycle(db, ctx, cycle_id):
    _officer_ready(ctx)
    actor = lock_self(db, ctx)
    _officer_ready(ctx)
    cycle = db.get(CleaningCycle, cycle_id)
    if cycle is None:
        raise AppError(404, "Cycle not found")
    if cycle.status != CCS.approved:
        raise AppError(409, "Only an approved cycle can be activated")
    cycle.status = CCS.active
    # Notify every assigned student in the same transaction.
    students = {}
    for assignment in db.scalars(
        select(CleaningAssignment).where(CleaningAssignment.cycle_id == cycle.cycle_id)
    ).all():
        student = db.get(Student, assignment.student_id)
        if student and student.user_id not in students:
            students[student.user_id] = (student, assignment)
    for user_id, (student, assignment) in students.items():
        notify_user(
            db,
            user_id=user_id,
            title="مهمة نظافة جديدة",
            message=f"أُسندت إليك مهمة: {assignment.task_description} في {assignment.assignment_date}.",
        )
    db.flush()
    record_event(
        db, "cleaning.activate", actor=actor,
        details={"cycle_id": cycle.cycle_id, "count": len(students)},
    )
    return _cycle_dict(db, cycle)


@account_write
def complete_cycle(db, ctx, cycle_id):
    _officer_ready(ctx)
    actor = lock_self(db, ctx)
    _officer_ready(ctx)
    cycle = db.get(CleaningCycle, cycle_id)
    if cycle is None:
        raise AppError(404, "Cycle not found")
    if cycle.status != CCS.active:
        raise AppError(409, "Only an active cycle can be completed")
    cycle.status = CCS.completed
    db.flush()
    record_event(
        db, "cleaning.complete", actor=actor,
        details={"cycle_id": cycle.cycle_id},
    )
    return _cycle_dict(db, cycle)


# ---------------------------------------------------------------- assignments
def _assignment_dict(db, a):
    student = db.get(Student, a.student_id)
    return dict(
        assignment_id=a.assignment_id,
        cycle_id=a.cycle_id,
        student_id=a.student_id,
        student_name=student.full_name if student else "—",
        task_description=a.task_description,
        assignment_date=a.assignment_date,
        status=a.status,
        completed_date=a.completed_date,
    )


def my_assignments(db, ctx, offset=0, limit=50):
    _student_ready(ctx)
    student = db.scalar(select(Student).where(Student.user_id == ctx.user.user_id))
    if student is None:
        raise AppError(404, "Student profile not found")
    query = select(CleaningAssignment).where(CleaningAssignment.student_id == student.student_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(CleaningAssignment.assignment_date.desc(), CleaningAssignment.assignment_id)
        .offset(offset).limit(limit)
    ).all()
    return dict(items=[_assignment_dict(db, a) for a in rows], total=total, offset=offset, limit=limit)


@account_write
def student_update(db, ctx, assignment_id, action):
    _student_ready(ctx)
    actor = lock_self(db, ctx)
    _student_ready(ctx)
    student = db.scalar(select(Student).where(Student.user_id == ctx.user.user_id))
    if student is None:
        raise AppError(404, "Student profile not found")
    assignment = db.scalar(
        select(CleaningAssignment).where(
            CleaningAssignment.assignment_id == assignment_id,
            CleaningAssignment.student_id == student.student_id,
        )
    )
    if assignment is None:
        raise AppError(404, "Assignment not found")
    previous = assignment.status
    if action == "start":
        if previous != CAS.pending:
            raise AppError(409, "Only a pending task can be started")
        assignment.status = CAS.in_progress
    elif action == "complete":
        if previous != CAS.in_progress:
            raise AppError(409, "Only an in-progress task can be completed")
        assignment.status = CAS.completed
        assignment.completed_date = utcnow()
    else:
        raise AppError(422, "Unknown action")
    db.flush()
    record_event(
        db, "cleaning.assignment." + action, actor=actor,
        details={"assignment_id": assignment.assignment_id, "cycle_id": assignment.cycle_id,
                 "student_id": assignment.student_id, "from_status": previous.value,
                 "to_status": assignment.status.value, "date": assignment.assignment_date.isoformat()},
    )
    if action == "complete":
        notify_role(
            db, R.cleaning_officer,
            "أُنجزت مهمة نظافة",
            f"أنجز الطالب {student.full_name} مهمة: {assignment.task_description}.",
            exclude_user_id=actor.user_id,
        )
    return _assignment_dict(db, assignment)


@account_write
def skip_assignment(db, ctx, assignment_id):
    _officer_ready(ctx)
    actor = lock_self(db, ctx)
    _officer_ready(ctx)
    assignment = db.get(CleaningAssignment, assignment_id)
    if assignment is None:
        raise AppError(404, "Assignment not found")
    if assignment.status not in (CAS.pending, CAS.in_progress):
        raise AppError(409, "Only pending or in-progress tasks can be skipped")
    previous = assignment.status
    assignment.status = CAS.skipped
    db.flush()
    record_event(
        db, "cleaning.assignment.skip", actor=actor,
        details={"assignment_id": assignment.assignment_id, "cycle_id": assignment.cycle_id,
                 "student_id": assignment.student_id, "from_status": previous.value,
                 "to_status": assignment.status.value, "date": assignment.assignment_date.isoformat()},
    )
    return _assignment_dict(db, assignment)
