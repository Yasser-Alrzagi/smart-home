"""
SQLAlchemy ORM Model: applications + application_documents
Application must be fully submitted with docs before it moves to review.
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Integer,
    UniqueConstraint,
    text,
    event,
    Column,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.orm import deferred, relationship
from sqlalchemy.dialects.mysql import DATETIME, MEDIUMBLOB

from app.models.base import Base, utcnow
from app.models.enums import ApplicationStatus, DocumentType


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (CheckConstraint("version >= 1", name="ck_applications_version"),)

    application_id = Column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    student_id = Column(
        String(36),
        ForeignKey("students.student_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    application_date = Column(DateTime, default=utcnow, nullable=False)
    status = Column(
        SAEnum(ApplicationStatus), nullable=False, default=ApplicationStatus.draft
    )
    decision_date = Column(DateTime, nullable=True)
    decision_notes = Column(Text, nullable=True)
    reviewed_by = Column(
        String(36), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )

    version = Column(Integer, nullable=False, default=1, server_default=text("1"))
    submitted_at = Column(DateTime, nullable=True)
    review_completed_at = Column(DateTime, nullable=True)
    prechecked_by = Column(
        String(36), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )
    review_notes = Column(Text, nullable=True)
    requested_documents = Column(
        Text, nullable=False, default="[]", server_default=text("'[]'")
    )
    profile_snapshot = Column(Text, nullable=True)

    # Relationships
    student = relationship("Student", back_populates="applications")
    documents = relationship(
        "ApplicationDocument",
        back_populates="application",
        cascade="all, delete-orphan",
    )
    reviewer = relationship("User", foreign_keys=[reviewed_by])

    def __repr__(self):
        return (
            f"<Application(application_id={self.application_id}, status={self.status})>"
        )


class ApplicationDocument(Base):
    __tablename__ = "application_documents"
    __table_args__ = (
        UniqueConstraint(
            "application_id", "document_type", name="uq_application_document_type"
        ),
        CheckConstraint(
            "size_bytes IS NULL OR size_bytes > 0", name="ck_document_size"
        ),
    )

    document_id = Column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    application_id = Column(
        String(36),
        ForeignKey("applications.application_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_type = Column(SAEnum(DocumentType), nullable=False)
    file_path = Column(String(500), nullable=False)
    uploaded_at = Column(DateTime, default=utcnow, nullable=False)

    content = deferred(Column(MEDIUMBLOB, nullable=True))
    content_type = Column(String(100), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    sha256 = Column(String(64), nullable=True)

    # Relationships
    application = relationship("Application", back_populates="documents")

    def __repr__(self):
        return f"<ApplicationDocument(document_id={self.document_id}, document_type={self.document_type})>"


class ApplicationEvent(Base):
    """Business history, visible only to the owner and authorized reviewers."""

    __tablename__ = "application_events"
    event_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    application_id = Column(
        String(36),
        ForeignKey("applications.application_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    actor_id = Column(
        String(36), ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    actor_role = Column(String(60), nullable=False)
    action = Column(String(64), nullable=False)
    from_status = Column(String(40), nullable=True)
    to_status = Column(String(40), nullable=False)
    note = Column(Text, nullable=True)
    application_version = Column(Integer, nullable=False)
    created_at = Column(DATETIME(fsp=6), nullable=False, default=utcnow)


@event.listens_for(ApplicationEvent, "before_update")
@event.listens_for(ApplicationEvent, "before_delete")
def protect_application_history(mapper, connection, target):
    raise ValueError("Application history is append-only through the ORM.")
