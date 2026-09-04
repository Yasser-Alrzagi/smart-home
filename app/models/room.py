"""
SQLAlchemy ORM Models: floors + apartments + rooms + room_assignments

floors -> apartments -> rooms is the structural chain that lets the cleaning optimizer
resolve the students living on a given floor. Capacity enforcement is done at the
business logic layer. Full assignment history is preserved.
"""
import uuid

from sqlalchemy import (
    Column,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.models.base import Base, utcnow
from app.models.enums import RoomAssignmentStatus, RoomStatus


class Floor(Base):
    __tablename__ = "floors"
    __table_args__ = (UniqueConstraint("building_name", "floor_number", name="uq_floors_building_number"),)

    floor_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    floor_number = Column(String(20), nullable=False)
    building_name = Column(String(100), nullable=False)

    # Relationships
    apartments = relationship("Apartment", back_populates="floor")
    cleaning_cycles = relationship("CleaningCycle", back_populates="floor")

    def __repr__(self):
        return f"<Floor(floor_id={self.floor_id}, building={self.building_name}, number={self.floor_number})>"


class Apartment(Base):
    __tablename__ = "apartments"
    __table_args__ = (UniqueConstraint("floor_id", "apartment_number", name="uq_apartments_floor_number"),)

    apartment_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    floor_id = Column(String(36), ForeignKey("floors.floor_id", ondelete="RESTRICT"), nullable=False, index=True)
    apartment_number = Column(String(20), nullable=False)

    # Relationships
    floor = relationship("Floor", back_populates="apartments")
    rooms = relationship("Room", back_populates="apartment")

    def __repr__(self):
        return f"<Apartment(apartment_id={self.apartment_id}, number={self.apartment_number})>"


class Room(Base):
    __tablename__ = "rooms"

    room_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    apartment_id = Column(
        String(36), ForeignKey("apartments.apartment_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    room_number = Column(String(20), nullable=False)
    capacity = Column(Integer, nullable=False, default=1)
    status = Column(SAEnum(RoomStatus), nullable=False, default=RoomStatus.available)

    # Relationships
    apartment = relationship("Apartment", back_populates="rooms")
    assignments = relationship("RoomAssignment", back_populates="room", cascade="all, delete-orphan")
    maintenance_requests = relationship("MaintenanceRequest", back_populates="room")

    def __repr__(self):
        return f"<Room(room_id={self.room_id}, room_number={self.room_number}, status={self.status})>"


class RoomAssignment(Base):
    __tablename__ = "room_assignments"

    assignment_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = Column(String(36), ForeignKey("students.student_id", ondelete="CASCADE"), nullable=False, index=True)
    room_id = Column(String(36), ForeignKey("rooms.room_id", ondelete="CASCADE"), nullable=False, index=True)
    assignment_date = Column(DateTime, default=utcnow, nullable=False)
    end_date = Column(DateTime, nullable=True)
    status = Column(SAEnum(RoomAssignmentStatus), nullable=False, default=RoomAssignmentStatus.active)
    assigned_by = Column(String(36), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)

    # Relationships
    student = relationship("Student", back_populates="room_assignments")
    room = relationship("Room", back_populates="assignments")
    assigner = relationship("User", foreign_keys=[assigned_by])

    def __repr__(self):
        return f"<RoomAssignment(assignment_id={self.assignment_id}, student_id={self.student_id}, room_id={self.room_id})>"
