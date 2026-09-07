"""
SQLAlchemy ORM Models: permission_requests + student_absences + emergency_reports
+ disciplinary_cases + notifications
"""
import uuid

from sqlalchemy import Boolean, Column, Date, DateTime, Enum as SAEnum, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from app.models.base import Base, utcnow
from app.models.enums import (
    AbsenceType,
    AttendanceStatus,
    DisciplinaryDecision,
    EmergencyReportStatus,
    NotificationStatus,
    PermissionStatus,
)


class PermissionRequest(Base):
    __tablename__ = "permission_requests"

    permission_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = Column(String(36), ForeignKey("students.student_id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(SAEnum(PermissionStatus), nullable=False, default=PermissionStatus.pending)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    reason = Column(Text, nullable=False)
    reviewed_by = Column(String(36), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)

    # Relationships
    student = relationship("Student", back_populates="permission_requests")
    reviewer = relationship("User", foreign_keys=[reviewed_by])

    def __repr__(self):
        return f"<PermissionRequest(permission_id={self.permission_id}, student_id={self.student_id}, status={self.status})>"


class StudentAbsence(Base):
    __tablename__ = "student_absences"

    absence_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = Column(String(36), ForeignKey("students.student_id", ondelete="CASCADE"), nullable=False, index=True)
    absence_type = Column(SAEnum(AbsenceType), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    source = Column(String(200), nullable=True)  # e.g., "Permission Request #XYZ" or "Emergency Report #XYZ"
    notes = Column(Text, nullable=True)

    # Relationships
    student = relationship("Student", back_populates="absences")
    emergency_reports = relationship("EmergencyReport", back_populates="absence")

    def __repr__(self):
        return f"<StudentAbsence(absence_id={self.absence_id}, type={self.absence_type})>"


class EmergencyReport(Base):
    """An emergency report exists independently of any absence.

    ``absence_id`` is populated only once the exit has been verified, which is what
    makes business rule 9.2 — not every emergency report implies an absence — auditable.
    """

    __tablename__ = "emergency_reports"

    report_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = Column(String(36), ForeignKey("students.student_id", ondelete="CASCADE"), nullable=False, index=True)
    reported_at = Column(DateTime, default=utcnow, nullable=False)
    description = Column(Text, nullable=False)
    status = Column(SAEnum(EmergencyReportStatus), nullable=False, default=EmergencyReportStatus.reported)
    exit_verified = Column(Boolean, nullable=False, default=False)
    absence_id = Column(
        String(36), ForeignKey("student_absences.absence_id", ondelete="SET NULL"), nullable=True, index=True
    )
    handled_by = Column(String(36), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)

    # Relationships
    student = relationship("Student", back_populates="emergency_reports")
    absence = relationship("StudentAbsence", back_populates="emergency_reports")
    handler = relationship("User", foreign_keys=[handled_by])

    def __repr__(self):
        return f"<EmergencyReport(report_id={self.report_id}, status={self.status}, exit_verified={self.exit_verified})>"



class DisciplinaryCase(Base):
    __tablename__ = "disciplinary_cases"

    case_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = Column(String(36), ForeignKey("students.student_id", ondelete="CASCADE"), nullable=False, index=True)
    incident_date = Column(Date, nullable=False)
    description = Column(Text, nullable=False)
    decision = Column(SAEnum(DisciplinaryDecision), nullable=False, default=DisciplinaryDecision.under_review)
    start_date = Column(Date, nullable=True)   # Suspension start date
    end_date = Column(Date, nullable=True)     # Suspension end date (mandatory for Temporary Suspension)
    decided_by = Column(String(36), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)

    # Relationships
    student = relationship("Student", back_populates="disciplinary_cases")
    decider = relationship("User", foreign_keys=[decided_by])

    def __repr__(self):
        return f"<DisciplinaryCase(case_id={self.case_id}, decision={self.decision})>"


class Notification(Base):
    __tablename__ = "notifications"

    notification_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(300), nullable=False)
    message = Column(Text, nullable=False)
    status = Column(SAEnum(NotificationStatus), nullable=False, default=NotificationStatus.unread)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    read_at = Column(DateTime, nullable=True)

    # Relationships
    user = relationship("User", back_populates="notifications")

    def __repr__(self):
        return f"<Notification(notification_id={self.notification_id}, user_id={self.user_id}, status={self.status})>"


class AttendanceRecord(Base):
    """Daily attendance ledger; one row per student per date.

    ``status`` is officer-declared. Marking a day ``absent`` without an
    approved permission or verified emergency for that date produces the
    matching ``Unauthorized`` StudentAbsence (source ``attendance:<id>``).
    """

    __tablename__ = "attendance_records"
    __table_args__ = (
        __import__("sqlalchemy").UniqueConstraint(
            "student_id", "record_date", name="uq_attendance_student_date"
        ),
    )

    record_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = Column(String(36), ForeignKey("students.student_id", ondelete="CASCADE"), nullable=False, index=True)
    record_date = Column(Date, nullable=False, index=True)
    status = Column(SAEnum(AttendanceStatus), nullable=False)
    notes = Column(Text, nullable=True)
    recorded_by = Column(String(36), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    source = Column(String(30), nullable=False, default="officer")  # officer | bulk
    created_at = Column(DateTime, default=utcnow, nullable=False)

    # Relationships
    student = relationship("Student", back_populates="attendance_records")
    recorder = relationship("User", foreign_keys=[recorded_by])
