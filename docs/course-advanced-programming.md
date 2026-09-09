# امتثال مشروع «سكن بازرعة» لمتطلبات البرمجة المتقدمة

حسب متطلبات المادة (A. Alwaleed Alduais — 2026) وملاحظات المدرس:
التركيز على **النقاط الإلزامية**، وكل جدول في قاعدة البيانات يُعد واجهة API.

## الإلزامي — كلها محققة ✅

| المتطلب الإلزامي | التنفيذ | الدليل |
|---|---|---|
| ‏4+ واجهات API بوحدات أعمال مختلفة | **11 وحدة** | `app/api/v1/`: auth، users، admissions، housing، facilities، support، attendance، daily_attendance، notifications، dashboards، cleaning، reports — +88 مساراً |
| منصتان تشتركان في قاعدة بيانات واحدة عبر REST | **Web + Desktop** | واجهة `app/web/` + عميل `desktop_client/` — كلاهما يستدعي `/api/v1/*` فقط |
| قاعدة بيانات (MySQL) | MySQL/MariaDB InnoDB + 28 جدولاً | `app/models/` + `alembic/` |
| JWT/OAuth2 | PyJWT HS256، انتهاء 30 دقيقة، `iss/aud`، جلسات محدودة | `app/services/auth.py`, `sessions.py` |
| أذونات | RBAC ثابت بالكود (بدون جداول أدوار) | `app/api/deps.py` — `RoleChecker` + فحص أدوار في كل خدمة |
| التحقق والتنظيف من الإدخال | Pydantic صارم (`extra="forbid"`, bounds, hidden input) | `app/schemas/`, `StrictInput` |
| الحماية من SQL Injection | SQLAlchemy ORM معامَل؛ لا SQL ممزوج | كل `app/repositories/` |
| الحماية من XSS | CSP صارمة + `no-store` + عدم إخراج HTML خام | `app/web/routes.py` |
| تخزين كلمة المرور بأمان | **Argon2id** | `app/core/security.py` |
| انتهاء الرمز | 30 دقيقة + تحديث إلزامي عند تبديل كلمة المرور | `access_token` + `auth_version` |
| HTTPS | يسري عبر Cloudflare Tunnel (شهادة مجانية) أو Nginx بعد النشر | دليل النشر: README → Deploy |
| JSON | كل الواجهات (افتراضي) | `application/json` |
| **XML** | عبر واجهة التقارير `format=xml` | `app/api/v1/reports.py` |
| اختبارات وحدة | ‏`tests/unit/` — منطق الأعمال | ‏`test_cleaning_ai`, `test_services_auth`, … |
| اختبارات تكامل | ‏`tests/integration/` — API + قاعدة حقيقية | ‏`test_http_foundation`, `test_identity_d2`, `test_reports_xml`, … |
| توثيق الكود (Docstrings) | كل الوحدات: docstrings + تعليقات | إجمالي السلسلة: ‏**524 نجح / 3 تخطي** |
| توثيق الـAPI | ‏Swagger/OpenAPI + `docs/` بالعربية | ‏`/docs` (مع DEBUG) + `docs/identity-d2.md` إلخ |
| SOLID | طبقات: API → Service → Repository → ORM | دليل README: المعمارية |
| ‏3+ أنماط تصميم | **Strategy** (BFS/A* للنظافة)، **Unit of Work** (`session_scope`)، **Dependency Injection**، **Repository**، **Singleton** (Settings)، **Observer** (أحداث الإشعارات) | `app/services/`, `app/repositories/` |

## اختياري — محقق (بونص) ✅

| المتطلب الاختياري | التنفيذ |
|---|---|
| AI | تنظيف AI: BFS + A* من تنفيذ الفريق، مقارنة وتقييم — `app/services/cleaning_ai.py` |
| UI/UX | بوابة عربية RTL بتصميم موحد، توثيق بالألوان، إشعارات فورية، ‏`assets` |
| ‏MVC/MVVM | مصمم طبقي (API/Service/Repository) — تأثير MVC |
| تقارير إضافية | ‏`/reports/*` بتصدير JSON أو XML |

## بيان عيوب مقصودة (تلبية لسؤال «لماذا لا يوجد CRUD كامل»)
- ‏`DELETE /users` غير موجود عمداً: إدارة الحساب بالإيقاف فقط (سياسة أمنية — لا حذف
  لسجلات أثرية).
- واجهات AI (تحسين مسارات النظافة) قراءة/تشغيل بدون `CREATE/UPDATE/DELETE` مفتوح:
  الحالة تنتقل عبر سلسلة حالة موثقة (Draft→Optimizing→Approved→Active→Completed).

## التسليم
- ‏`readme.txt` + ملف مضغوط يحتوي: الكود، `docs/` (هذا الملف + سياسات المراحل D1–D9)،
  لقطات الشاشة، ونتائج الاختبارات (`pytest`).
