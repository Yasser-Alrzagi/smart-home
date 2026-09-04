"""
SQLAlchemy ORM Model: applications + application_documents
Application must be fully submitted with docs before it moves to review.
"""
import uuid

from sqlalchemy import Column, DateTime, Enum as SAEnum, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from app.models.base import Base, utcnow
from app.models.enums import ApplicationStatus, DocumentType


class Application(Base):
    __tablename__ = "applications"

    application_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = Column(String(36), ForeignKey("students.student_id", ondelete="CASCADE"), nullable=False, index=True)
    application_date = Column(DateTime, default=utcnow, nullable=False)
    status = Column(SAEnum(ApplicationStatus), nullable=False, default=ApplicationStatus.draft)
    decision_date = Column(DateTime, nullable=True)
    decision_notes = Column(Text, nullable=True)
    reviewed_by = Column(String(36), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)

    # Relationships
    student = relationship("Student", back_populates="applications")
    documents = relationship("ApplicationDocument", back_populates="application", cascade="all, delete-orphan")
    reviewer = relationship("User", foreign_keys=[reviewed_by])

    def __repr__(self):
        return f"<Application(application_id={self.application_id}, status={self.status})>"


class ApplicationDocument(Base):
    __tablename__ = "application_documents"

    document_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    application_id = Column(String(36), ForeignKey("applications.application_id", ondelete="CASCADE"), nullable=False, index=True)
    document_type = Column(SAEnum(DocumentType), nullable=False)
    file_path = Column(String(500), nullable=False)
    uploaded_at = Column(DateTime, default=utcnow, nullable=False)

    # Relationships
    application = relationship("Application", back_populates="documents")

    def __repr__(self):
        return f"<ApplicationDocument(document_id={self.document_id}, document_type={self.document_type})>"
