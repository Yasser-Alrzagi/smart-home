"""
SQLAlchemy ORM Models: complaints + maintenance_requests
Both use independent status tracking and handler assignment.
"""
import uuid

from sqlalchemy import Column, DateTime, Enum as SAEnum, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from app.models.base import Base, utcnow
from app.models.enums import ComplaintStatus, MaintenanceStatus


class Complaint(Base):
    __tablename__ = "complaints"

    complaint_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = Column(String(36), ForeignKey("students.student_id", ondelete="CASCADE"), nullable=False, index=True)
    category = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(SAEnum(ComplaintStatus), nullable=False, default=ComplaintStatus.open)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    handled_by = Column(String(36), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    resolution = Column(Text, nullable=True)

    # Relationships
    student = relationship("Student", back_populates="complaints")
    handler = relationship("User", foreign_keys=[handled_by])

    def __repr__(self):
        return f"<Complaint(complaint_id={self.complaint_id}, status={self.status})>"


class MaintenanceRequest(Base):
    __tablename__ = "maintenance_requests"

    request_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = Column(String(36), ForeignKey("students.student_id", ondelete="CASCADE"), nullable=False, index=True)
    room_id = Column(String(36), ForeignKey("rooms.room_id", ondelete="SET NULL"), nullable=True, index=True)
    problem_type = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(SAEnum(MaintenanceStatus), nullable=False, default=MaintenanceStatus.pending)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    handled_by = Column(String(36), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    resolution = Column(Text, nullable=True)

    # Relationships
    student = relationship("Student", back_populates="maintenance_requests")
    room = relationship("Room", back_populates="maintenance_requests")
    handler = relationship("User", foreign_keys=[handled_by])

    def __repr__(self):
        return f"<MaintenanceRequest(request_id={self.request_id}, status={self.status})>"
