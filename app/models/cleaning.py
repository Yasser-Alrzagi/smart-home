"""
SQLAlchemy ORM Models: cleaning_cycles + cleaning_assignments + ai_optimization_runs
BFS and A* results are both stored before approval. Only Cleaning Officer approves.
"""
import uuid

from sqlalchemy import Column, Date, DateTime, Enum as SAEnum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.models.base import Base, utcnow
from app.models.enums import AIAlgorithm, CleaningAssignmentStatus, CleaningCycleStatus


class CleaningCycle(Base):
    __tablename__ = "cleaning_cycles"

    cycle_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    floor_id = Column(String(36), ForeignKey("floors.floor_id", ondelete="RESTRICT"), nullable=False, index=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    status = Column(SAEnum(CleaningCycleStatus), nullable=False, default=CleaningCycleStatus.draft)
    created_by = Column(String(36), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)

    # Relationships
    floor = relationship("Floor", back_populates="cleaning_cycles")
    assignments = relationship("CleaningAssignment", back_populates="cycle", cascade="all, delete-orphan")
    ai_runs = relationship("AIOptimizationRun", back_populates="cycle", cascade="all, delete-orphan")
    creator = relationship("User", foreign_keys=[created_by])

    def __repr__(self):
        return f"<CleaningCycle(cycle_id={self.cycle_id}, floor_id={self.floor_id}, status={self.status})>"


class CleaningAssignment(Base):
    __tablename__ = "cleaning_assignments"

    assignment_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    cycle_id = Column(String(36), ForeignKey("cleaning_cycles.cycle_id", ondelete="CASCADE"), nullable=False, index=True)
    student_id = Column(String(36), ForeignKey("students.student_id", ondelete="CASCADE"), nullable=False, index=True)
    task_description = Column(String(500), nullable=False)
    assignment_date = Column(Date, nullable=False)
    status = Column(SAEnum(CleaningAssignmentStatus), nullable=False, default=CleaningAssignmentStatus.pending)
    completed_date = Column(DateTime, nullable=True)

    # Relationships
    cycle = relationship("CleaningCycle", back_populates="assignments")
    student = relationship("Student", back_populates="cleaning_assignments")

    def __repr__(self):
        return f"<CleaningAssignment(assignment_id={self.assignment_id}, student_id={self.student_id}, status={self.status})>"


class AIOptimizationRun(Base):
    __tablename__ = "ai_optimization_runs"

    run_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    cycle_id = Column(String(36), ForeignKey("cleaning_cycles.cycle_id", ondelete="CASCADE"), nullable=False, index=True)
    algorithm = Column(SAEnum(AIAlgorithm), nullable=False)
    total_cost = Column(Float, nullable=True)          # Search Cost
    fairness_score = Column(Float, nullable=True)      # Fairness Score (0.0 to 1.0)
    feasibility_rate = Column(Float, nullable=True)    # Feasibility Rate (0.0 to 1.0)
    nodes_expanded = Column(Integer, nullable=True)    # Number of nodes/states explored
    execution_time = Column(Float, nullable=True)      # In seconds
    result_summary = Column(Text, nullable=True)       # JSON string of the proposed schedule
    approved_by = Column(String(36), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    # Relationships
    cycle = relationship("CleaningCycle", back_populates="ai_runs")
    approver = relationship("User", foreign_keys=[approved_by])

    def __repr__(self):
        return f"<AIOptimizationRun(run_id={self.run_id}, algorithm={self.algorithm}, cycle_id={self.cycle_id})>"
