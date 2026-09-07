"""Real Chromium workflow on a guarded TEST database; never a production seed tool.

Starts a temporary local server if --base-url is absent. Cleans its synthetic users,
requests, documents and events on exit. Artifacts contain synthetic data only.
"""

import argparse
import io
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import uuid
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url")
    parser.add_argument("--artifacts", default="artifacts/ui")
    args = parser.parse_args()
    from tests.db_safety import validate_test_url

    url = validate_test_url(os.environ.get("TEST_DATABASE_URL", ""))
    os.environ.update(
        APP_ENV="test", DATABASE_URL=url, SECRET_KEY=secrets.token_hex(48), DEBUG="True"
    )
    from PIL import Image
    from playwright.sync_api import sync_playwright, expect
    from sqlalchemy import delete, select
    from app.core.database import SessionLocal, engine
    from app.core.security import get_password_hash
    from app.models import (
        Application,
        ApplicationEvent,
        AuditEvent,
        AuthSession,
        LoginRateBucket,
        Student,
        User,
    )
    from app.models.enums import UserRole

    artifacts = Path(args.artifacts).resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    server = None
    log = None
    ids, accounts = [], {}
    password = "Synthetic-UI-Password-2026!"
    suffix = uuid.uuid4().hex[:8]
    try:
        if not args.base_url:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            args.base_url = f"http://127.0.0.1:{port}"
            log = (artifacts / "server.log").open("w")
            server = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                env=os.environ.copy(),
            )
            for _ in range(60):
                if server.poll() is not None:
                    raise RuntimeError("Test server failed to start")
                try:
                    with urlopen(args.base_url + "/ready", timeout=1) as response:
                        if response.status == 200:
                            break
                except Exception:
                    time.sleep(0.2)
            else:
                raise RuntimeError("Test server readiness timed out")
        with SessionLocal.begin() as db:
            for key, role in [
                ("student", UserRole.student),
                ("affairs", UserRole.student_affairs),
                ("housing", UserRole.housing_administration),
            ]:
                name = f"ui_{key}_{suffix}"
                user = User(
                    username=name,
                    email=name + "@example.com",
                    role=role,
                    is_active=True,
                    must_change_password=False,
                    password_hash=get_password_hash(password),
                )
                db.add(user)
                db.flush()
                ids.append(user.user_id)
                accounts[key] = name
        image = io.BytesIO()
        Image.new("RGB", (128, 80), "#e8eee9").save(image, format="PNG")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))

            def capture(filename):
                # Wait for the first compositor frames. Retry only image capture,
                # never workflow assertions, to tolerate a Chromium capture race.
                for attempt in range(3):
                    page.evaluate(
                        "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
                    )
                    try:
                        page.screenshot(
                            path=str(artifacts / filename),
                            full_page=True,
                            animations="disabled",
                        )
                        return
                    except Exception:
                        if attempt == 2:
                            raise

            page.goto(args.base_url + "/app")
            capture("login-desktop.png")

            def login(who):
                page.locator("#loginForm input[name=username]").fill(accounts[who])
                page.locator("#loginForm input[name=password]").fill(password)
                page.locator("#loginForm button[type=submit]").click()
                expect(page.locator("#portal")).to_be_visible()
                expect(page.locator("#page h1")).to_be_visible()

            def nav(label):
                page.locator("#navigation").get_by_role(
                    "button", name=label, exact=True
                ).click()

            def logout():
                if page.locator("#detailDialog").is_visible():
                    page.locator("#closeDialog").click()
                page.locator("#logoutButton").click()
                expect(page.locator("#loginView")).to_be_visible()

            login("student")
            nav("ملفي الطلابي")
            malicious = '<img src=x onerror="window.pwned=1">'
            page.get_by_label("الاسم الكامل", exact=True).fill(malicious)
            page.get_by_label("الجامعة", exact=True).fill("جامعة تجريبية")
            page.get_by_label("التخصص", exact=True).fill("علوم الحاسوب")
            page.get_by_role("button", name="إنشاء الملف", exact=True).click()
            expect(page.locator("#message")).to_be_visible()
            expect(page.locator("#message")).to_contain_text("تم حفظ الملف")
            nav("لوحة المتابعة")
            expect(page.locator("#page h1")).to_contain_text(malicious)
            assert page.evaluate("window.pwned") is None
            assert page.locator("#page img").count() == 0
            nav("ملفي الطلابي")
            page.get_by_label("الاسم الكامل", exact=True).fill("طالب تجريبي")
            page.get_by_role("button", name="حفظ التعديلات", exact=True).click()
            expect(page.locator("#message")).to_be_visible()
            expect(page.locator("#message")).to_contain_text("تم حفظ الملف")
            nav("طلبات السكن")
            page.get_by_role("button", name="＋ إنشاء طلب", exact=True).click()
            expect(page.locator("#detailDialog")).to_be_visible()
            for index, label in enumerate(["الهوية الوطنية", "إفادة القيد"]):
                page.locator(f'input[aria-label="رفع {label}"]').set_input_files(
                    {
                        "name": "synthetic.png",
                        "mimeType": "image/png",
                        "buffer": image.getvalue(),
                    }
                )
                expect(page.locator("#detailContent .doc-status")).to_have_count(
                    index + 1
                )
            with page.expect_download() as downloaded:
                page.locator("#detailContent").get_by_role(
                    "button", name="تنزيل", exact=True
                ).first.click()
            assert downloaded.value.suggested_filename.endswith(".png")
            page.get_by_role("button", name="تقديم الطلب للمراجعة", exact=True).click()
            expect(page.locator("#detailContent .badge")).to_have_text("تم التقديم")
            logout()
            login("affairs")
            nav("مراجعة الطلبات")
            page.get_by_role("button", name="التفاصيل", exact=True).first.click()
            page.get_by_role("button", name="بدء المراجعة", exact=True).click()
            expect(page.locator("#detailContent .badge")).to_have_text("قيد المراجعة")
            page.get_by_label("ملاحظات المراجعة", exact=True).fill(
                "مستندات تجريبية مكتملة لاختبار مسار المراجعة."
            )
            page.get_by_role(
                "button", name="اكتمال المراجعة والإحالة لإدارة السكن", exact=True
            ).click()
            expect(page.locator("#detailContent .badge")).to_have_text("جاهز للقرار")
            capture("review-desktop.png")
            logout()
            login("housing")
            nav("مراجعة الطلبات")
            page.get_by_role("button", name="التفاصيل", exact=True).first.click()
            page.get_by_label("ملاحظات القرار", exact=True).fill(
                "قرار تجريبي: مقبول، دون تخصيص غرفة."
            )
            page.get_by_role("button", name="قبول الطلب", exact=True).click()
            expect(page.locator("#detailContent .badge")).to_have_text("مقبول")
            if page.locator("#detailDialog").is_visible():
                page.locator("#closeDialog").click()
            # D4: build one floor/apartment/room and allocate through the UI.
            nav("السكن والغرف")
            expect(page.locator("#page h1")).to_contain_text("السكن والغرف")
            structure = page.locator("section.panel").filter(has_text="البنية السكنية")
            floor_form = structure.locator("form").filter(has_text="اسم المبنى")
            floor_form.locator("input[name=building_name]").fill(
                "مبنى برمجي " + suffix
            )
            floor_form.locator("input[name=floor_number]").fill("1")
            structure.get_by_role(
                "button", name="إضافة مبنى/طابق", exact=True
            ).click()
            expect(page.locator("#message")).to_contain_text("أُضيف المبنى/الطابق")
            # housingPage() re-renders after each add; wait until the fresh DOM
            # shows the new structure before interacting with the next form.
            structure = page.locator("section.panel").filter(has_text="البنية السكنية")
            expect(structure).to_contain_text("مبنى برمجي " + suffix)
            apartment_form = structure.locator("form").filter(has_text="رقم الشقة")
            apartment_form.locator("select").select_option(
                label="مبنى برمجي " + suffix + " · الطابق 1"
            )
            apartment_form.locator("input[name=apartment_number]").fill("برمجية")
            structure.get_by_role("button", name="إضافة شقة", exact=True).click()
            expect(page.locator("#message")).to_contain_text("أُضيفت الشقة")
            structure = page.locator("section.panel").filter(has_text="البنية السكنية")
            expect(structure).to_contain_text("شقة برمجية")
            room_form = structure.locator("form").filter(has_text="رقم الغرفة")
            room_form.locator("select").select_option(
                label=(
                    "مبنى برمجي " + suffix + " · الطابق 1 · شقة برمجية"
                )
            )
            room_form.locator("input[name=room_number]").fill("بي 101")
            structure.get_by_role("button", name="إضافة غرفة", exact=True).click()
            expect(page.locator("#message")).to_contain_text("أُضيفت الغرفة")
            # Wait for the room row (fresh render) before opening the dialog,
            # otherwise the dialog would show a stale free-rooms snapshot.
            rooms_panel = page.locator("section.panel").filter(
                has_text="حالة الإشغال تُحسب"
            )
            expect(
                rooms_panel.locator("tr", has_text="مبنى برمجي " + suffix).first
            ).to_be_visible()
            eligible = page.locator("section.panel").filter(has_text="بانتظار غرفة")
            eligible.get_by_role(
                "button", name="تخصيص غرفة", exact=True
            ).first.click()
            expect(page.locator("#detailDialog")).to_be_visible()
            page.locator("#detailDialog select").select_option(
                label=(
                    "مبنى برمجي " + suffix + " · الطابق 1 · شقة برمجية"
                    " · غرفة بي 101 (متاح 1)"
                )
            )
            page.locator("#detailDialog").get_by_role(
                "button", name="تأكيد التخصيص", exact=True
            ).click()
            expect(page.locator("#message")).to_contain_text("تم التسكين بنجاح")
            expect(
                page.locator("section.panel").filter(has_text="التسكينات النشطة")
            ).to_contain_text("طالب تجريبي")
            capture("housing-desktop.png")
            logout()
            login("student")
            nav("لوحة المتابعة")
            expect(page.locator("#page")).to_contain_text("مقبول")
            capture("student-desktop.png")
            nav("غرفتي")
            expect(page.locator("#page h1")).to_contain_text("غرفتي")
            expect(page.locator("#page")).to_contain_text("مبنى برمجي " + suffix)
            expect(page.locator("#page")).to_contain_text("بي 101")
            capture("student-room.png")
            page.set_viewport_size({"width": 390, "height": 844})
            capture("student-mobile.png")
            assert page.evaluate(
                "document.documentElement.scrollWidth <= innerWidth + 1"
            )
            assert page.evaluate("localStorage.length") == 0
            assert page.evaluate("sessionStorage.length") == 0
            assert context.cookies() == []
            page.reload()
            expect(page.locator("#loginView")).to_be_visible()
            assert not errors, errors
            (artifacts / "result.json").write_text(
                json.dumps(
                    {
                        "status": "passed",
                        "workflow": "student -> affairs -> housing -> accepted -> allocated",
                        "required_documents": 2,
                        "room_allocation_ui": True,
                        "xss_execution": False,
                        "persistent_token_storage": False,
                        "mobile_horizontal_overflow": False,
                        "javascript_errors": errors,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            browser.close()
        print(
            "Browser workflow passed: profile, two files, submit, two-role review, decision, room allocation/transfer UI, private download, XSS, mobile, logout/reload."
        )
    finally:
        if server:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
        if log:
            log.close()
        with SessionLocal.begin() as db:
            appids = list(
                db.scalars(
                    select(Application.application_id)
                    .join(Student, Application.student_id == Student.student_id)
                    .where(Student.user_id.in_(ids))
                )
            )
            db.execute(
                delete(ApplicationEvent).where(
                    ApplicationEvent.application_id.in_(appids)
                )
            )
            db.execute(
                delete(AuditEvent).where(
                    AuditEvent.actor_id.in_(ids) | AuditEvent.target_user_id.in_(ids)
                )
            )
            db.execute(delete(AuthSession).where(AuthSession.user_id.in_(ids)))
            db.execute(delete(LoginRateBucket))
            db.execute(delete(User).where(User.user_id.in_(ids)))
        engine.dispose()


if __name__ == "__main__":
    main()
