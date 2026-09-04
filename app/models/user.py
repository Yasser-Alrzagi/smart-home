"""
SQLAlchemy ORM Model: users
All 9 roles from specification. No additional roles allowed.
"""
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum as SAEnum, String
from sqlalchemy.orm import relationship

from app.models.base import Base, utcnow
from app.models.enums import UserRole


class User(Base):
    __tablename__ = "users"

    user_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(80), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(SAEnum(UserRole), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    # Relationships
    student = relationship("Student", back_populates="user", uselist=False, cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(user_id={self.user_id}, username={self.username}, role={self.role})>"
