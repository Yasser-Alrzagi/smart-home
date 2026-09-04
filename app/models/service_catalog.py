"""
SQLAlchemy ORM Models: services + service_periods + service_registrations

Backs the Services API (activities, food, sports, internet). A registration is unique
per (period, student), which is how business rule 9.2 — no duplicate registration for
the same service in the same period — is enforced at the database level.
"""
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.models.base import Base, utcnow
from app.models.enums import (
    ServicePeriodStatus,
    ServiceRegistrationStatus,
    ServiceType,
    UserRole,
)


class Service(Base):
    __tablename__ = "services"

    service_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    service_type = Column(SAEnum(ServiceType), nullable=False)
    name = Column(String(200), nullable=False)
    managed_by_role = Column(SAEnum(UserRole), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)

    # Relationships
    periods = relationship("ServicePeriod", back_populates="service", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Service(service_id={self.service_id}, type={self.service_type}, name={self.name})>"


class ServicePeriod(Base):
    __tablename__ = "service_periods"

    period_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    service_id = Column(String(36), ForeignKey("services.service_id", ondelete="CASCADE"), nullable=False, index=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    capacity = Column(Integer, nullable=True)  # NULL means unlimited
    status = Column(SAEnum(ServicePeriodStatus), nullable=False, default=ServicePeriodStatus.upcoming)

    # Relationships
    service = relationship("Service", back_populates="periods")
    registrations = relationship("ServiceRegistration", back_populates="period", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<ServicePeriod(period_id={self.period_id}, service_id={self.service_id}, status={self.status})>"


class ServiceRegistration(Base):
    __tablename__ = "service_registrations"
    __table_args__ = (
        UniqueConstraint("period_id", "student_id", name="uq_service_registrations_period_student"),
    )

    registration_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    period_id = Column(
        String(36), ForeignKey("service_periods.period_id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id = Column(String(36), ForeignKey("students.student_id", ondelete="CASCADE"), nullable=False, index=True)
    registered_at = Column(DateTime, default=utcnow, nullable=False)
    status = Column(
        SAEnum(ServiceRegistrationStatus), nullable=False, default=ServiceRegistrationStatus.registered
    )

    # Relationships
    period = relationship("ServicePeriod", back_populates="registrations")
    student = relationship("Student", back_populates="service_registrations")

    def __repr__(self):
        return f"<ServiceRegistration(registration_id={self.registration_id}, student_id={self.student_id})>"
