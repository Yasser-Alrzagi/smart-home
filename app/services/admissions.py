"""D3 policy: students own drafts, Student Affairs review, Housing decides.

User rows (actor + owner) lock in sorted order before student/application rows.
This also covers the FK locks taken by audit/history writes. Version checks
protect against stale browser forms and concurrent document replacement.
"""

import hashlib
import json

from sqlalchemy import func, select

from app.core.errors import AppError
from app.models import (
    Application,
    ApplicationDocument,
    ApplicationEvent,
    Student,
    User,
    utcnow,
)
from app.models.enums import (
    ApplicationStatus as S,
    DocumentType,
    REQUIRED_DOCUMENT_TYPES,
    UserRole as R,
)
from app.services.accounts import account_write
from app.services.audit import record_event
from app.services.sessions import lock_self, validate_locked_actor

REVIEW_ROLES = {R.student_affairs, R.housing_administration}
EDITABLE = {S.draft, S.pending_documents}


def ready(ctx):
    if ctx.user.must_change_password:
        raise AppError(403, "Password change required before this operation.")
    if ctx.user.role not in {R.student, *REVIEW_ROLES}:
        raise AppError(403, "Operation not permitted")


def student_only(ctx):
    ready(ctx)
    if ctx.user.role != R.student:
        raise AppError(403, "Student access required")


def profile_values(profile):
    return {key: getattr(profile, key) for key in ["full_name", "university", "major"]}


def get_profile(db, ctx):
    student_only(ctx)
    profile = db.scalar(select(Student).where(Student.user_id == ctx.user.user_id))
    if profile is None:
        raise AppError(404, "Create your student profile first.")
    return profile


@account_write
def create_profile(db, ctx, data):
    student_only(ctx)
    user = lock_self(db, ctx)
    student_only(ctx)
    if db.scalar(
        select(Student.student_id)
        .where(Student.user_id == user.user_id)
        .with_for_update()
    ):
        raise AppError(409, "Student profile already exists.")
    profile = Student(user_id=user.user_id, **data.model_dump())
    db.add(profile)
    db.flush()
    record_event(
        db,
        "student.profile_create",
        actor=user,
        target_id=user.user_id,
        details={"student_id": profile.student_id},
    )
    return profile


@account_write
def update_profile(db, ctx, data):
    student_only(ctx)
    user = lock_self(db, ctx)
    student_only(ctx)
    profile = db.scalar(
        select(Student)
        .where(Student.user_id == user.user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if profile is None:
        raise AppError(404, "Student profile not found")
    if profile.profile_version != data.expected_version:
        raise AppError(409, "Profile changed; refresh before saving.")
    applications = list(
        db.scalars(
            select(Application)
            .where(
                Application.student_id == profile.student_id,
                Application.status != S.rejected,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    if any(a.status not in EDITABLE for a in applications):
        raise AppError(
            409, "Profile is locked while an application is being reviewed or accepted."
        )
    for key, value in data.model_dump(exclude={"expected_version"}).items():
        setattr(profile, key, value)
    profile.profile_version += 1
    for application in applications:
        application.version += 1
        history(
            db,
            application,
            user,
            "profile.updated",
            application.status,
            "تم تحديث بيانات الملف؛ تُراجع عند إعادة التقديم.",
        )
    db.flush()
    record_event(
        db,
        "student.profile_update",
        actor=user,
        target_id=user.user_id,
        details={"student_id": profile.student_id},
    )
    return profile


def history(db, application, actor, action, previous, note=None):
    db.add(
        ApplicationEvent(
            application_id=application.application_id,
            actor_id=actor.user_id,
            actor_role=actor.role.value,
            action=action,
            from_status=previous.value if previous else None,
            to_status=application.status.value,
            note=note or None,
            application_version=application.version,
        )
    )
    db.flush()


def summary(application, profile):
    snapshot = (
        json.loads(application.profile_snapshot)
        if application.profile_snapshot
        else profile_values(profile)
    )
    return dict(
        application_id=application.application_id,
        student_id=application.student_id,
        student_name=snapshot["full_name"],
        university=snapshot["university"],
        status=application.status,
        version=application.version,
        application_date=application.application_date,
        submitted_at=application.submitted_at,
    )


def _find(db, ctx, application_id):
    ready(ctx)
    pair = db.execute(
        select(Application, Student)
        .join(Student, Application.student_id == Student.student_id)
        .where(Application.application_id == application_id)
    ).first()
    if pair is None or (
        ctx.user.role == R.student and pair.Student.user_id != ctx.user.user_id
    ):
        raise AppError(404, "Application not found")
    if ctx.user.role in REVIEW_ROLES and pair.Application.status == S.draft:
        raise AppError(404, "Application not found")
    return pair.Application, pair.Student


def _locked(db, ctx, application_id, version=None):
    application, profile = _find(db, ctx, application_id)
    rows = {
        u.user_id: u
        for u in db.scalars(
            select(User)
            .where(User.user_id.in_({ctx.user.user_id, profile.user_id}))
            .order_by(User.user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    }
    actor = rows.get(ctx.user.user_id)
    validate_locked_actor(db, ctx, actor)
    ready(ctx)
    owner = rows.get(profile.user_id)
    if owner is None or not owner.is_active or owner.role != R.student:
        raise AppError(409, "The student account is not eligible for this operation.")
    profile = db.scalar(
        select(Student)
        .where(Student.student_id == profile.student_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    application = db.scalar(
        select(Application)
        .where(Application.application_id == application_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if ctx.user.role == R.student and profile.user_id != actor.user_id:
        raise AppError(404, "Application not found")
    if ctx.user.role in REVIEW_ROLES and application.status == S.draft:
        raise AppError(404, "Application not found")
    if version is not None and version != application.version:
        raise AppError(409, "Application changed; refresh before retrying.")
    return application, profile, actor


def doc_available(doc):
    return bool(
        doc.file_path == "db:" + doc.document_id
        and doc.content_type in {"application/pdf", "image/jpeg", "image/png"}
        and doc.size_bytes
        and doc.sha256
    )


def details(db, ctx, application_id):
    application, profile = _find(db, ctx, application_id)
    docs = list(
        db.scalars(
            select(ApplicationDocument)
            .where(ApplicationDocument.application_id == application_id)
            .order_by(ApplicationDocument.uploaded_at, ApplicationDocument.document_id)
        )
    )
    events = list(
        db.scalars(
            select(ApplicationEvent)
            .where(ApplicationEvent.application_id == application_id)
            .order_by(ApplicationEvent.created_at, ApplicationEvent.event_id)
        )
    )
    return {
        **summary(application, profile),
        "profile_snapshot": json.loads(application.profile_snapshot)
        if application.profile_snapshot
        else None,
        "review_notes": application.review_notes,
        "requested_documents": json.loads(application.requested_documents),
        "decision_notes": application.decision_notes,
        "decision_date": application.decision_date,
        "review_completed_at": application.review_completed_at,
        "documents": [
            dict(
                document_id=d.document_id,
                document_type=d.document_type,
                content_type=d.content_type,
                size_bytes=d.size_bytes,
                uploaded_at=d.uploaded_at,
                available=doc_available(d),
            )
            for d in docs
        ],
        "history": events,
    }


def list_applications(db, ctx, offset, limit, status=None):
    ready(ctx)
    query = select(Application, Student).join(
        Student, Application.student_id == Student.student_id
    )
    if ctx.user.role == R.student:
        query = query.where(Student.user_id == ctx.user.user_id)
    else:
        query = query.where(Application.status != S.draft)
    if status is not None:
        query = query.where(Application.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(
        query.order_by(Application.application_date.desc(), Application.application_id)
        .offset(offset)
        .limit(limit)
    ).all()
    return dict(
        items=[summary(a, p) for a, p in rows], total=total, offset=offset, limit=limit
    )


@account_write
def create_application(db, ctx):
    student_only(ctx)
    user = lock_self(db, ctx)
    student_only(ctx)
    profile = db.scalar(
        select(Student).where(Student.user_id == user.user_id).with_for_update()
    )
    if profile is None:
        raise AppError(409, "Create your student profile first.")
    if db.scalar(
        select(Application.application_id)
        .where(
            Application.student_id == profile.student_id,
            Application.status != S.rejected,
        )
        .with_for_update()
    ):
        raise AppError(409, "An open or accepted application already exists.")
    application = Application(student_id=profile.student_id)
    db.add(application)
    db.flush()
    history(db, application, user, "application.created", None)
    record_event(
        db,
        "application.create",
        actor=user,
        target_id=user.user_id,
        details={"application_id": application.application_id},
    )
    return details(db, ctx, application.application_id)


def _complete(db, application):
    required = set(REQUIRED_DOCUMENT_TYPES) | {
        DocumentType(x) for x in json.loads(application.requested_documents)
    }
    docs = list(
        db.scalars(
            select(ApplicationDocument).where(
                ApplicationDocument.application_id == application.application_id,
                ApplicationDocument.content.is_not(None),
            )
        )
    )
    present = {d.document_type for d in docs if doc_available(d)}
    if required - present:
        raise AppError(
            422,
            "Required documents are missing or unavailable: "
            + ", ".join(sorted(t.value for t in required - present)),
        )


@account_write
def submit(db, ctx, application_id, version):
    student_only(ctx)
    application, profile, actor = _locked(db, ctx, application_id, version)
    if application.status not in EDITABLE:
        raise AppError(
            409, "This application cannot be submitted in its current state."
        )
    _complete(db, application)
    previous = application.status
    application.status = S.submitted
    application.version += 1
    application.submitted_at = utcnow()
    application.review_completed_at = None
    application.prechecked_by = None
    application.profile_snapshot = json.dumps(
        profile_values(profile), ensure_ascii=False
    )
    history(db, application, actor, "application.submitted", previous)
    record_event(
        db,
        "application.submit",
        actor=actor,
        target_id=profile.user_id,
        details={"application_id": application_id, "version": application.version},
    )
    return details(db, ctx, application_id)


@account_write
def review(db, ctx, application_id, data):
    ready(ctx)
    if ctx.user.role not in REVIEW_ROLES:
        raise AppError(403, "Reviewer access required")
    application, profile, actor = _locked(
        db, ctx, application_id, data.expected_version
    )
    previous = application.status
    action, note = data.action, data.note.strip()
    if action in {"start", "request_documents", "complete"}:
        if actor.role != R.student_affairs:
            raise AppError(403, "Student Affairs review required")
        allowed = {S.submitted} if action == "start" else {S.submitted, S.under_review}
        if previous not in allowed:
            raise AppError(409, "Invalid review transition")
        if action == "start":
            application.status = S.under_review
        elif action == "request_documents":
            if len(note) < 3 or not data.document_types:
                raise AppError(422, "Specify the requested documents and a clear note.")
            application.status = S.pending_documents
            application.requested_documents = json.dumps(
                sorted({x.value for x in data.document_types})
            )
            application.review_notes = note
            application.review_completed_at = None
            application.prechecked_by = None
        else:
            if previous != S.under_review:
                raise AppError(409, "Start the review before completing it.")
            _complete(db, application)
            if not application.profile_snapshot or not application.submitted_at:
                raise AppError(409, "A complete submitted profile is required.")
            application.status = S.ready_for_decision
            application.prechecked_by = actor.user_id
            application.review_completed_at = utcnow()
            application.review_notes = note or None
    else:
        if actor.role != R.housing_administration:
            raise AppError(403, "Housing Administration decision required")
        if (
            previous != S.ready_for_decision
            or not application.prechecked_by
            or not application.review_completed_at
        ):
            raise AppError(409, "Student Affairs must complete the review first.")
        if action in {"reject", "return_to_review"} and len(note) < 3:
            raise AppError(422, "A clear reason is required.")
        if action == "return_to_review":
            application.status = S.under_review
            application.prechecked_by = None
            application.review_completed_at = None
            application.review_notes = note
        else:
            _complete(db, application)
            application.status = S.accepted if action == "accept" else S.rejected
            application.reviewed_by = actor.user_id
            application.decision_date = utcnow()
            application.decision_notes = note or None
    application.version += 1
    history(db, application, actor, "review." + action, previous, note)
    record_event(
        db,
        "application.review",
        actor=actor,
        target_id=profile.user_id,
        details={
            "application_id": application_id,
            "from_status": previous.value,
            "to_status": application.status.value,
            "version": application.version,
        },
    )
    return details(db, ctx, application_id)


def can_upload(db, ctx, application_id, version):
    student_only(ctx)
    application, _ = _find(db, ctx, application_id)
    if application.status not in EDITABLE or application.version != version:
        raise AppError(409, "Documents are locked or the application changed.")


@account_write
def save_document(db, ctx, application_id, version, doc_type, payload, mime, digest):
    student_only(ctx)
    application, profile, actor = _locked(db, ctx, application_id, version)
    if application.status not in EDITABLE:
        raise AppError(409, "Documents are locked in this state.")
    doc = db.scalar(
        select(ApplicationDocument)
        .where(
            ApplicationDocument.application_id == application_id,
            ApplicationDocument.document_type == doc_type,
        )
        .with_for_update()
    )
    if doc is None:
        doc = ApplicationDocument(
            application_id=application_id, document_type=doc_type, file_path="pending"
        )
        db.add(doc)
        db.flush()
    doc.file_path = "db:" + doc.document_id
    doc.content, doc.content_type, doc.size_bytes, doc.sha256 = (
        payload,
        mime,
        len(payload),
        digest,
    )
    doc.uploaded_at = utcnow()
    application.version += 1
    history(
        db, application, actor, "document.uploaded", application.status, doc_type.value
    )
    record_event(
        db,
        "document.upload",
        actor=actor,
        target_id=profile.user_id,
        details={
            "application_id": application_id,
            "document_id": doc.document_id,
            "document_type": doc_type.value,
        },
    )
    return details(db, ctx, application_id)


@account_write
def remove_document(db, ctx, application_id, document_id, version):
    student_only(ctx)
    application, profile, actor = _locked(db, ctx, application_id, version)
    if application.status not in EDITABLE:
        raise AppError(409, "Documents are locked in this state.")
    doc = db.scalar(
        select(ApplicationDocument)
        .where(
            ApplicationDocument.application_id == application_id,
            ApplicationDocument.document_id == document_id,
        )
        .with_for_update()
    )
    if doc is None:
        raise AppError(404, "Document not found")
    doc_type = doc.document_type
    db.delete(doc)
    application.version += 1
    history(
        db, application, actor, "document.removed", application.status, doc_type.value
    )
    record_event(
        db,
        "document.remove",
        actor=actor,
        target_id=profile.user_id,
        details={"application_id": application_id, "document_id": document_id},
    )
    return details(db, ctx, application_id)


@account_write
def download(db, ctx, application_id, document_id):
    application, profile, actor = _locked(db, ctx, application_id)
    doc = db.scalar(
        select(ApplicationDocument).where(
            ApplicationDocument.application_id == application_id,
            ApplicationDocument.document_id == document_id,
        )
    )
    if doc is None:
        raise AppError(404, "Document not found")
    if not doc_available(doc):
        raise AppError(
            409, "Legacy or unavailable document; a validated re-upload is required."
        )
    payload = doc.content
    if (
        not payload
        or len(payload) != doc.size_bytes
        or hashlib.sha256(payload).hexdigest() != doc.sha256
    ):
        raise AppError(409, "Document integrity check failed.")
    record_event(
        db,
        "document.download",
        actor=actor,
        target_id=profile.user_id,
        details={"application_id": application_id, "document_id": document_id},
    )
    extension = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg"}[
        doc.content_type
    ]
    return payload, doc.content_type, doc.document_type.name + "." + extension
