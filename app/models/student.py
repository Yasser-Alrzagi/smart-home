"""
SQLAlchemy ORM Model: students
Academic status and Housing status are independent per specification.
"""
import uuid

from sqlalchemy import Column, DateTime, Enum as SAEnum, ForeignKey, String
from sqlalchemy.orm import relationship

from app.models.base import Base, utcnow
from app.models.enums import AcademicStatus, HousingStatus


class Student(Base):
    __tablename__ = "students"

    student_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.user_id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    full_name = Column(String(200), nullable=False)
    university = Column(String(200), nullable=False)
    major = Column(String(200), nullable=False)
    academic_status = Column(SAEnum(AcademicStatus), nullable=False, default=AcademicStatus.continuing)
    housing_status = Column(SAEnum(HousingStatus), nullable=False, default=HousingStatus.active)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="student")
    applications = relationship("Application", back_populates="student", cascade="all, delete-orphan")
    status_history = relationship("StudentStatusHistory", back_populates="student", cascade="all, delete-orphan", order_by="StudentStatusHistory.start_date")
    room_assignments = relationship("RoomAssignment", back_populates="student", cascade="all, delete-orphan")
    complaints = relationship("Complaint", back_populates="student", cascade="all, delete-orphan")
    maintenance_requests = relationship("MaintenanceRequest", back_populates="student", cascade="all, delete-orphan")
    permission_requests = relationship("PermissionRequest", back_populates="student", cascade="all, delete-orphan")
    absences = relationship("StudentAbsence", back_populates="student", cascade="all, delete-orphan")
    emergency_reports = relationship("EmergencyReport", back_populates="student", cascade="all, delete-orphan")
    service_registrations = relationship("ServiceRegistration", back_populates="student", cascade="all, delete-orphan")
    disciplinary_cases = relationship("DisciplinaryCase", back_populates="student", cascade="all, delete-orphan")
    cleaning_assignments = relationship("CleaningAssignment", back_populates="student", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Student(student_id={self.student_id}, full_name={self.full_name}, housing_status={self.housing_status})>"
