import uuid
from fastapi import Body, APIRouter, File, Form, Query, Response, UploadFile

from app.api.deps import Authenticated
from app.core.config import settings
from app.core.database import DatabaseSession
from app.models.enums import ApplicationStatus, DocumentType, REQUIRED_DOCUMENT_TYPES
from app.schemas.admissions import (
    EmptyApplicationInput,
    ApplicationPage,
    ApplicationResponse,
    ProfileCreate,
    ProfileResponse,
    ProfileUpdate,
    ReviewInput,
    VersionInput,
)
from app.services import admissions as service
from app.services.documents import validate_document
from app.services.rate_limit import consume, opaque_key

router = APIRouter(tags=["Student admissions"])


@router.get("/admissions/policy")
def policy(ctx: Authenticated):
    service.ready(ctx)
    return {
        "required_documents": [x.value for x in REQUIRED_DOCUMENT_TYPES],
        "document_types": [x.value for x in DocumentType],
        "max_document_bytes": settings.DOCUMENT_MAX_BYTES,
        "accepted_formats": ["PDF", "JPEG", "PNG"],
        "reviewer_role": "Student Affairs",
        "decision_role": "Housing Administration",
    }


@router.get("/students/me", response_model=ProfileResponse)
def my_profile(db: DatabaseSession, ctx: Authenticated):
    return service.get_profile(db, ctx)


@router.post("/students/me", response_model=ProfileResponse, status_code=201)
def create_profile(data: ProfileCreate, db: DatabaseSession, ctx: Authenticated):
    return service.create_profile(db, ctx, data)


@router.patch("/students/me", response_model=ProfileResponse)
def update_profile(data: ProfileUpdate, db: DatabaseSession, ctx: Authenticated):
    return service.update_profile(db, ctx, data)


@router.get("/applications", response_model=ApplicationPage)
def applications(
    db: DatabaseSession,
    ctx: Authenticated,
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(20, ge=1, le=50),
    status: ApplicationStatus | None = None,
):
    return service.list_applications(db, ctx, offset, limit, status)


@router.post("/applications", response_model=ApplicationResponse, status_code=201)
def create_application(
    db: DatabaseSession,
    ctx: Authenticated,
    data: EmptyApplicationInput = Body(default=EmptyApplicationInput()),
):
    return service.create_application(db, ctx)


@router.get("/applications/{application_id}", response_model=ApplicationResponse)
def application(application_id: uuid.UUID, db: DatabaseSession, ctx: Authenticated):
    return service.details(db, ctx, str(application_id))


@router.post(
    "/applications/{application_id}/submit", response_model=ApplicationResponse
)
def submit(
    application_id: uuid.UUID,
    data: VersionInput,
    db: DatabaseSession,
    ctx: Authenticated,
):
    return service.submit(db, ctx, str(application_id), data.expected_version)


@router.post(
    "/applications/{application_id}/review", response_model=ApplicationResponse
)
def review(
    application_id: uuid.UUID,
    data: ReviewInput,
    db: DatabaseSession,
    ctx: Authenticated,
):
    return service.review(db, ctx, str(application_id), data)


@router.post(
    "/applications/{application_id}/documents", response_model=ApplicationResponse
)
def upload_document(
    application_id: uuid.UUID,
    db: DatabaseSession,
    ctx: Authenticated,
    document_type: DocumentType = Form(),
    expected_version: int = Form(ge=1),
    file: UploadFile = File(),
):
    app_id = str(application_id)
    service.can_upload(db, ctx, app_id, expected_version)
    consume(opaque_key("document_upload", ctx.user.user_id), limit=12, seconds=60)
    payload = file.file.read(settings.DOCUMENT_MAX_BYTES + 1)
    data, mime, digest = validate_document(payload, file.filename, file.content_type)
    return service.save_document(
        db, ctx, app_id, expected_version, document_type, data, mime, digest
    )


@router.get("/applications/{application_id}/documents/{document_id}")
def download_document(
    application_id: uuid.UUID,
    document_id: uuid.UUID,
    db: DatabaseSession,
    ctx: Authenticated,
):
    data, mime, filename = service.download(
        db, ctx, str(application_id), str(document_id)
    )
    return Response(
        content=data,
        media_type=mime,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )


@router.delete(
    "/applications/{application_id}/documents/{document_id}",
    response_model=ApplicationResponse,
)
def remove_document(
    application_id: uuid.UUID,
    document_id: uuid.UUID,
    db: DatabaseSession,
    ctx: Authenticated,
    expected_version: int = Query(ge=1),
):
    return service.remove_document(
        db, ctx, str(application_id), str(document_id), expected_version
    )
