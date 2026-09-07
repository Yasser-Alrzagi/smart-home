"""D9 cleaning AI contracts: cycles, runs, assignments."""

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import AIAlgorithm, CleaningAssignmentStatus, CleaningCycleStatus
from app.schemas.identity import StrictInput, UTCResponse


class CycleCreate(StrictInput):
    floor_id: str = Field(min_length=1, max_length=36)
    start_date: date
    end_date: date


class CycleResponse(UTCResponse):
    cycle_id: str
    building_name: str | None = None
    floor_number: str | None = None
    start_date: date
    end_date: date | None
    status: CleaningCycleStatus
    assignments_count: int = 0
    created_at: datetime | None = None


class CyclePage(BaseModel):
    items: list[CycleResponse]
    total: int
    offset: int
    limit: int


class OptimizeRequest(StrictInput):
    algorithm: AIAlgorithm


class RunResponse(UTCResponse):
    run_id: str
    cycle_id: str
    algorithm: AIAlgorithm
    total_cost: float | None
    fairness_score: float | None
    feasibility_rate: float | None
    nodes_expanded: int | None
    execution_time: float | None
    task_count: int = 0
    created_at: datetime | None = None


class ApproveRequest(StrictInput):
    run_id: str = Field(min_length=1, max_length=36)


class AssignmentResponse(UTCResponse):
    assignment_id: str
    cycle_id: str
    student_id: str
    student_name: str | None = None
    task_description: str
    assignment_date: date
    status: CleaningAssignmentStatus
    completed_date: datetime | None = None


class AssignmentPage(BaseModel):
    items: list[AssignmentResponse]
    total: int
    offset: int
    limit: int


class AssignmentAction(StrictInput):
    action: str = Field(pattern="^(start|complete)$")


class CycleDetailResponse(CycleResponse):
    runs: list[RunResponse]
    assignments: list[AssignmentResponse]
