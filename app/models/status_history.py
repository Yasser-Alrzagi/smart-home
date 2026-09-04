"""
SQLAlchemy ORM Model: student_status_history
Tracks all transitions of AcademicStatus and HousingStatus independently.
Full audit trail is preserved — no deletions.
"""
import uuid

from sqlalchemy import Column, DateTime, Enum as SAEnum, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from app.models.base import Base, utcnow
from app.models.enums import StatusType


class StudentStatusHistory(Base):
    __tablename__ = "student_status_history"

    history_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = Column(String(36), ForeignKey("students.student_id", ondelete="CASCADE"), nullable=False, index=True)
    status_type = Column(SAEnum(StatusType), nullable=False)
    old_status = Column(String(50), nullable=True)  # Allows NULL for initial status entry
    new_status = Column(String(50), nullable=False)
    start_date = Column(DateTime, default=utcnow, nullable=False)
    end_date = Column(DateTime, nullable=True)
    changed_by = Column(String(36), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    notes = Column(Text, nullable=True)

    # Relationships
    student = relationship("Student", back_populates="status_history")
    changed_by_user = relationship("User", foreign_keys=[changed_by])

    def __repr__(self):
        return f"<StudentStatusHistory(student_id={self.student_id}, type={self.status_type}, {self.old_status}->{self.new_status})>"
