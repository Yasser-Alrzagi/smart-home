"""D3 real HTTP/DB contracts: two reviewers, ownership, files, concurrency."""

from concurrent.futures import ThreadPoolExecutor
import io
import uuid

from PIL import Image
from pypdf import PdfWriter
import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.models import Application, ApplicationDocument, ApplicationEvent, User
from app.models.enums import UserRole as R

pytestmark = pytest.mark.db
PASSWORD = "Admissions-Test-Password-2026!"


def png_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (32, 24), "#e0ede3").save(buffer, format="PNG")
    return buffer.getvalue()


def pdf_bytes(active=False, encrypted=False):
    w = PdfWriter()
    w.add_blank_page(width=100, height=100)
    if active:
        w.add_js('app.alert("not allowed")')
    if encrypted:
        w.encrypt("test-only")
    b = io.BytesIO()
    w.write(b)
    return b.getvalue()


@pytest.fixture
def actors(client):
    def create(role=R.student):
        name = "d3_" + uuid.uuid4().hex
        with SessionLocal.begin() as db:
            u = User(
                username=name,
                email=name + "@example.com",
                role=role,
                is_active=True,
                password_hash=get_password_hash(PASSWORD),
                must_change_password=False,
            )
            db.add(u)
            db.flush()
            uid = u.user_id
        login = client.post(
            "/api/v1/auth/login/access-token",
            data={"username": name, "password": PASSWORD},
        )
        assert login.status_code == 200
        return {
            "id": uid,
            "headers": {"Authorization": "Bearer " + login.json()["access_token"]},
        }

    return create


def new_draft(client, user):
    profile = client.post(
        "/api/v1/students/me",
        headers=user["headers"],
        json={
            "full_name": "طالب تجريبي",
            "university": "جامعة الاختبار",
            "major": "علوم الحاسوب",
        },
    )
    assert profile.status_code == 201, profile.text
    assert profile.json()["housing_status"] == "Applicant"
    result = client.post("/api/v1/applications", headers=user["headers"])
    assert result.status_code == 201, result.text
    return result.json()


def upload(
    client,
    user,
    app,
    kind="National ID",
    content=None,
    name="example.png",
    mime="image/png",
):
    return client.post(
        f"/api/v1/applications/{app['application_id']}/documents",
        headers=user["headers"],
        data={"document_type": kind, "expected_version": app["version"]},
        files={"file": (name, png_bytes() if content is None else content, mime)},
    )


def submit_ready(client, user, app):
    for kind in ["National ID", "Enrollment Certificate"]:
        response = upload(client, user, app, kind)
        assert response.status_code == 200, response.text
        app = response.json()
    response = client.post(
        f"/api/v1/applications/{app['application_id']}/submit",
        headers=user["headers"],
        json={"expected_version": app["version"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def review(client, actor, app, action, note="", docs=None):
    return client.post(
        f"/api/v1/applications/{app['application_id']}/review",
        headers=actor["headers"],
        json={
            "expected_version": app["version"],
            "action": action,
            "note": note,
            "document_types": docs or [],
        },
    )


def test_full_two_stage_admission_without_university_card(client, actors):
    owner, sa, ha = (
        actors(),
        actors(R.student_affairs),
        actors(R.housing_administration),
    )
    app = new_draft(client, owner)
    policy = client.get("/api/v1/admissions/policy", headers=owner["headers"]).json()
    assert set(policy["required_documents"]) == {
        "National ID",
        "Enrollment Certificate",
    }
    app = submit_ready(client, owner, app)
    assert review(client, ha, app, "accept").status_code == 409
    app = review(client, sa, app, "start").json()
    assert review(client, sa, app, "accept").status_code == 403
    app = review(client, sa, app, "complete", "تم التحقق من المستندات").json()
    assert app["status"] == "Ready for Decision"
    assert (
        review(
            client, sa, app, "request_documents", "إعادة", ["University ID"]
        ).status_code
        == 409
    )
    result = review(client, ha, app, "accept", "مقبول بعد اكتمال المراجعة")
    assert result.status_code == 200, result.text
    app = result.json()
    assert app["status"] == "Accepted"
    assert app["profile_snapshot"]["full_name"] == "طالب تجريبي"
    assert {x["actor_role"] for x in app["history"]} >= {
        "Student",
        "Student Affairs",
        "Housing Administration",
    }
    assert upload(client, owner, app).status_code == 409
    assert (
        client.post("/api/v1/applications", headers=owner["headers"]).status_code == 409
    )
    assert review(client, ha, app, "reject", "تغيير لاحق").status_code == 409
    profile = client.get("/api/v1/students/me", headers=owner["headers"]).json()
    assert profile["housing_status"] == "Applicant"  # no claim of room allocation
    assert (
        client.patch(
            "/api/v1/students/me",
            headers=owner["headers"],
            json={
                "expected_version": profile["profile_version"],
                "full_name": "اسم معدل",
                "university": "جامعة معدلة",
                "major": "تخصص معدل",
            },
        ).status_code
        == 409
    )


def test_requested_optional_document_becomes_required_and_snapshot_refreshes(
    client, actors
):
    owner, sa = actors(), actors(R.student_affairs)
    app = submit_ready(client, owner, new_draft(client, owner))
    app = review(
        client, sa, app, "request_documents", "يرجى إرفاق البطاقة", ["University ID"]
    ).json()
    assert app["status"] == "Pending Documents"
    assert (
        client.post(
            f"/api/v1/applications/{app['application_id']}/submit",
            headers=owner["headers"],
            json={"expected_version": app["version"]},
        ).status_code
        == 422
    )
    app = upload(client, owner, app, "University ID").json()
    profile = client.get("/api/v1/students/me", headers=owner["headers"]).json()
    update = client.patch(
        "/api/v1/students/me",
        headers=owner["headers"],
        json={
            "expected_version": profile["profile_version"],
            "full_name": "الاسم المصحح",
            "university": "جامعة الاختبار",
            "major": "علوم الحاسوب",
        },
    )
    assert update.status_code == 200
    # Profile update invalidates the stale application version too.
    assert (
        client.post(
            f"/api/v1/applications/{app['application_id']}/submit",
            headers=owner["headers"],
            json={"expected_version": app["version"]},
        ).status_code
        == 409
    )
    app = client.get(
        f"/api/v1/applications/{app['application_id']}", headers=owner["headers"]
    ).json()
    app = client.post(
        f"/api/v1/applications/{app['application_id']}/submit",
        headers=owner["headers"],
        json={"expected_version": app["version"]},
    ).json()
    assert (
        app["status"] == "Submitted"
        and app["profile_snapshot"]["full_name"] == "الاسم المصحح"
    )
    assert app["review_completed_at"] is None


def test_housing_can_return_review_and_rejection_allows_new_request(client, actors):
    owner, sa, ha = (
        actors(),
        actors(R.student_affairs),
        actors(R.housing_administration),
    )
    app = submit_ready(client, owner, new_draft(client, owner))
    app = review(client, sa, app, "start").json()
    app = review(client, sa, app, "complete").json()
    assert review(client, ha, app, "reject", "").status_code == 422
    app = review(client, ha, app, "return_to_review", "يرجى إعادة التحقق").json()
    assert app["status"] == "Under Review" and app["review_completed_at"] is None
    assert review(client, ha, app, "accept").status_code == 409
    app = review(client, sa, app, "complete").json()
    app = review(client, ha, app, "reject", "تعذر قبول الطلب").json()
    assert app["status"] == "Rejected"
    assert (
        client.post("/api/v1/applications", headers=owner["headers"]).status_code == 201
    )


@pytest.mark.parametrize("role", list(R))
def test_role_and_owner_visibility(role, client, actors):
    owner = actors()
    outsider = actors(role)
    app = new_draft(client, owner)
    doc_result = upload(client, owner, app)
    assert doc_result.status_code == 200
    app = doc_result.json()
    doc = app["documents"][0]
    root = f"/api/v1/applications/{app['application_id']}"
    expected = (
        404 if role in {R.student, R.student_affairs, R.housing_administration} else 403
    )
    assert client.get(root, headers=outsider["headers"]).status_code == expected
    assert (
        client.get(
            root + "/documents/" + doc["document_id"], headers=outsider["headers"]
        ).status_code
        == expected
    )
    assert client.get(root + "/documents/" + doc["document_id"]).status_code == 401
    app = submit_ready(client, owner, app)
    expected = (
        200
        if role in {R.student_affairs, R.housing_administration}
        else (404 if role == R.student else 403)
    )
    assert client.get(root, headers=outsider["headers"]).status_code == expected
    assert (
        client.get(
            root + "/documents/" + doc["document_id"], headers=outsider["headers"]
        ).status_code
        == expected
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"housing_status": "Active"},
        {"academic_status": "Completed"},
        {"user_id": "another-user"},
        {"profile_version": 7},
    ],
)
def test_profile_rejects_privileged_fields(extra, client, actors):
    user = actors()
    response = client.post(
        "/api/v1/students/me",
        headers=user["headers"],
        json={
            "full_name": "اسم الطالب",
            "university": "الجامعة",
            "major": "التخصص",
            **extra,
        },
    )
    assert response.status_code == 422


def test_profile_is_versioned_and_only_one_open_application(client, actors):
    owner = actors()
    app = new_draft(client, owner)
    assert (
        client.post(
            "/api/v1/students/me",
            headers=owner["headers"],
            json={"full_name": "اسم آخر", "university": "الجامعة", "major": "التخصص"},
        ).status_code
        == 409
    )
    assert (
        client.post("/api/v1/applications", headers=owner["headers"]).status_code == 409
    )
    assert (
        client.patch(
            "/api/v1/students/me",
            headers=owner["headers"],
            json={
                "expected_version": 999,
                "full_name": "اسم آخر",
                "university": "الجامعة",
                "major": "التخصص",
            },
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/applications/{app['application_id']}/submit",
            headers=owner["headers"],
            json={"expected_version": app["version"]},
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "name,mime,content",
    [
        ("evil.html", "text/html", b"<script>alert(1)</script>"),
        ("fake.pdf", "application/pdf", b"%PDF-fake %%EOF"),
        ("fake.png", "image/png", b"not an image"),
        ("test.zip", "application/zip", b"PK123"),
        ("wrong.jpg", "image/jpeg", png_bytes()),
        ("empty.png", "image/png", b""),
    ],
)
def test_invalid_files_rejected_without_rows(name, mime, content, client, actors):
    owner = actors()
    app = new_draft(client, owner)
    response = upload(client, owner, app, content=content, name=name, mime=mime)
    assert response.status_code in {413, 415}
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(ApplicationDocument)
                .where(ApplicationDocument.application_id == app["application_id"])
            )
            == 0
        )
        assert db.get(Application, app["application_id"]).version == app["version"]


@pytest.mark.parametrize("active,encrypted", [(True, False), (False, True)])
def test_active_or_encrypted_pdf_rejected(active, encrypted, client, actors):
    owner = actors()
    app = new_draft(client, owner)
    assert (
        upload(
            client,
            owner,
            app,
            content=pdf_bytes(active, encrypted),
            name="file.pdf",
            mime="application/pdf",
        ).status_code
        == 415
    )


def test_valid_pdf_private_download_and_blob_not_in_json(client, actors):
    owner = actors()
    app = new_draft(client, owner)
    data = pdf_bytes()
    response = upload(
        client,
        owner,
        app,
        content=data,
        name="../../private-name.pdf",
        mime="application/pdf",
    )
    assert response.status_code == 200, response.text
    app = response.json()
    doc = app["documents"][0]
    assert not {"file_path", "content", "sha256"} & set(doc)
    download = client.get(
        f"/api/v1/applications/{app['application_id']}/documents/{doc['document_id']}",
        headers=owner["headers"],
    )
    assert download.status_code == 200 and download.content == data
    assert (
        download.headers["content-disposition"]
        == 'attachment; filename="national_id.pdf"'
    )
    assert (
        download.headers["cache-control"] == "no-store"
        and download.headers["x-content-type-options"] == "nosniff"
    )
    assert client.get("/uploads/" + doc["document_id"]).status_code == 404
    with SessionLocal.begin() as db:
        db.get(ApplicationDocument, doc["document_id"]).content = b"corrupted"
    assert (
        client.get(
            f"/api/v1/applications/{app['application_id']}/documents/{doc['document_id']}",
            headers=owner["headers"],
        ).status_code
        == 409
    )


def test_legacy_path_never_reads_server_files(client, actors):
    owner = actors()
    app = new_draft(client, owner)
    with SessionLocal.begin() as db:
        doc = ApplicationDocument(
            application_id=app["application_id"],
            document_type="national_id",
            file_path="/etc/passwd",
        )
        db.add(doc)
        db.flush()
        uid = doc.document_id
    response = client.get(
        f"/api/v1/applications/{app['application_id']}/documents/{uid}",
        headers=owner["headers"],
    )
    assert response.status_code == 409
    assert b"root:" not in response.content


def test_stale_document_writes_and_delete_are_safe(client, actors):
    owner = actors()
    app = new_draft(client, owner)
    first = upload(client, owner, app).json()
    assert upload(client, owner, app, "Enrollment Certificate").status_code == 409
    doc = first["documents"][0]
    path = (
        f"/api/v1/applications/{app['application_id']}/documents/{doc['document_id']}"
    )
    assert (
        client.delete(
            path + "?expected_version=" + str(app["version"]), headers=owner["headers"]
        ).status_code
        == 409
    )
    response = client.delete(
        path + "?expected_version=" + str(first["version"]), headers=owner["headers"]
    )
    assert response.status_code == 200 and response.json()["documents"] == []


def test_parallel_review_has_one_winner(client, actors):
    from app.services.admissions import review as service_review
    from app.services.sessions import resolve_context
    from app.schemas.admissions import ReviewInput
    from app.core.errors import AppError

    owner, sa = actors(), actors(R.student_affairs)
    app = submit_ready(client, owner, new_draft(client, owner))

    def attempt(_):
        try:
            with SessionLocal.begin() as db:
                ctx = resolve_context(db, sa["headers"]["Authorization"].split()[1])
                service_review(
                    db,
                    ctx,
                    app["application_id"],
                    ReviewInput(action="start", expected_version=app["version"]),
                )
            return 200
        except AppError as e:
            return e.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [1, 2]))
    assert results.count(200) == 1 and results.count(409) == 1
    with SessionLocal() as db:
        assert db.get(Application, app["application_id"]).version == app["version"] + 1


def test_audit_failure_rolls_back_document(client, actors, monkeypatch):
    from app.services import admissions
    from fastapi.testclient import TestClient
    from main import app as api_app

    owner = actors()
    application = new_draft(client, owner)

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(admissions, "record_event", fail)
    with TestClient(api_app, raise_server_exceptions=False) as c:
        assert upload(c, owner, application).status_code == 500
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(ApplicationDocument)
                .where(
                    ApplicationDocument.application_id == application["application_id"]
                )
            )
            == 0
        )
        assert (
            db.get(Application, application["application_id"]).version
            == application["version"]
        )


def test_request_size_bound_including_chunked(client, actors, monkeypatch):
    owner = actors()
    app = new_draft(client, owner)
    monkeypatch.setattr(settings, "DOCUMENT_MAX_BYTES", 1024)
    assert upload(client, owner, app, content=b"x" * 2000).status_code == 413
    response = client.post(
        "/api/v1/students/me",
        headers={**owner["headers"], "Content-Type": "application/json"},
        content=iter([b"x" * 40000, b"y" * 40000]),
    )
    assert response.status_code == 413, response.text


def test_history_cannot_be_mutated_through_orm(client, actors):
    owner = actors()
    app = new_draft(client, owner)
    with SessionLocal() as db:
        event = db.scalar(
            select(ApplicationEvent).where(
                ApplicationEvent.application_id == app["application_id"]
            )
        )
        event.note = "tamper"
        with pytest.raises(ValueError, match="append-only"):
            db.flush()
        db.rollback()


def test_create_body_rejects_target_student_id(client, actors):
    owner = actors()
    client.post(
        "/api/v1/students/me",
        headers=owner["headers"],
        json={
            "full_name": "طالب اختباري",
            "university": "جامعة اختبار",
            "major": "تخصص اختباري",
        },
    )
    response = client.post(
        "/api/v1/applications",
        headers=owner["headers"],
        json={"student_id": str(uuid.uuid4())},
    )
    assert response.status_code == 422


def test_concurrent_draft_creation_has_one_winner(client, actors):
    from app.services.admissions import create_application
    from app.services.sessions import resolve_context
    from app.core.errors import AppError

    owner = actors()
    client.post(
        "/api/v1/students/me",
        headers=owner["headers"],
        json={
            "full_name": "طالب اختباري",
            "university": "جامعة اختبار",
            "major": "تخصص اختباري",
        },
    )

    def create(_):
        try:
            with SessionLocal.begin() as db:
                ctx = resolve_context(db, owner["headers"]["Authorization"].split()[1])
                create_application(db, ctx)
            return 201
        except AppError as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, [1, 2]))
    assert sorted(results) == [201, 409]


def test_application_list_filters_and_cross_owner_write(client, actors):
    owner, other, staff, admin = (
        actors(),
        actors(),
        actors(R.student_affairs),
        actors(R.system_administrator),
    )
    a = new_draft(client, owner)
    new_draft(client, other)
    own = client.get("/api/v1/applications", headers=owner["headers"]).json()
    assert own["total"] == 1 and [x["application_id"] for x in own["items"]] == [
        a["application_id"]
    ]
    assert (
        client.get("/api/v1/applications", headers=staff["headers"]).json()["total"]
        == 0
    )
    assert (
        client.get("/api/v1/applications", headers=admin["headers"]).status_code == 403
    )
    assert upload(client, other, a).status_code == 404
    a = submit_ready(client, owner, a)
    visible = client.get("/api/v1/applications", headers=staff["headers"]).json()
    assert (
        visible["total"] == 1
        and visible["items"][0]["application_id"] == a["application_id"]
    )
    assert (
        client.get(
            "/api/v1/applications?status=Draft", headers=staff["headers"]
        ).json()["total"]
        == 0
    )
    assert (
        client.get(
            "/api/v1/applications?limit=51", headers=owner["headers"]
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/api/v1/applications?offset=-1", headers=owner["headers"]
        ).status_code
        == 422
    )


def test_image_metadata_is_removed(client, actors):
    from PIL.PngImagePlugin import PngInfo

    image = Image.new("RGB", (24, 24), "white")
    info = PngInfo()
    info.add_text("PrivateLocation", "DO_NOT_KEEP_METADATA")
    exif = Image.Exif()
    exif[270] = "DO_NOT_KEEP_EXIF"
    buf = io.BytesIO()
    image.save(buf, format="PNG", pnginfo=info, exif=exif)
    owner = actors()
    app = new_draft(client, owner)
    response = upload(client, owner, app, content=buf.getvalue())
    assert response.status_code == 200
    doc = response.json()["documents"][0]
    data = client.get(
        f"/api/v1/applications/{app['application_id']}/documents/{doc['document_id']}",
        headers=owner["headers"],
    ).content
    with Image.open(io.BytesIO(data)) as normalized:
        assert "PrivateLocation" not in normalized.info
        assert len(normalized.getexif()) == 0
    assert b"DO_NOT_KEEP" not in data
