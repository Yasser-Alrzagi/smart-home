"""Desktop platform for the Smart Student Housing system (Tkinter).

The web portal and this desktop client are two independent front-ends that
share the SAME database; the only bridge between them is the REST API
(see api.py). The UI layer is intentionally thin: it renders data fetched
from the API and never touches the database directly.

Run from the project root:
    python desktop_client/main.py [--api http://127.0.0.1:8000]
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .api import ApiClient, ApiError

# ---------------------------------------------------------------- theme
BG = "#0e3b2e"        # deep green, matches the web portal palette
PANEL = "#14523f"
FG = "#ffffff"
ACCENT = "#2e8b68"
BUTTON = "#1f6f52"

FONT = ("Segoe UI", 11)
FONT_TITLE = ("Segoe UI", 18, "bold")
FONT_SMALL = ("Segoe UI", 9)

ROLE_LABELS = [
    ("Student", "طالب"),
    ("Housing Administration", "إدارة السكن"),
    ("Student Affairs", "شؤون الطلاب"),
    ("Maintenance Officer", "موظف الصيانة"),
    ("Activity Officer", "موظف النشاط"),
    ("Cleaning Officer", "موظف النظافة"),
    ("Food Officer", "موظف التغذية"),
    ("Sports Officer", "موظف الرياضة"),
    ("System Administrator", "مسؤول النظام"),
]

# Role gates mirror the web portal's fixed RBAC menu (same API, same authority).
ADMIN_ROLES = {"System Administrator"}
STAFF_ROLES = {"Student Affairs", "Housing Administration"}
APPLICATION_ROLES = {"Student", "Student Affairs", "Housing Administration"}


class DesktopApp:
    """Controller: owns the Tk root and swaps the visible view."""

    def __init__(self, api: ApiClient) -> None:
        self.api = api
        self.user: dict = {}
        self.root = tk.Tk()
        self.root.title("سكن بازرعة — العميل المكتبي")
        self.root.geometry("1020x660")
        self.root.configure(bg=BG)
        self._shell = tk.Frame(self.root, bg=BG)
        self._shell.pack(fill="both", expand=True)
        self.show_login()

    # ------------------------------------------------------------ routing
    def _clear(self) -> None:
        for child in self._shell.winfo_children():
            child.destroy()

    def show_login(self) -> None:
        self._clear()
        LoginView(self._shell, self)

    def show_change_password(self, forced: bool) -> None:
        self._clear()
        ChangePasswordView(self._shell, self, forced=forced)

    def show_main(self) -> None:
        self._clear()
        MainView(self._shell, self)

    def run(self) -> None:
        self.root.mainloop()


def _busy(root: tk.Misc):
    root.config(cursor="watch")
    root.update_idletasks()


def _idle(root: tk.Misc):
    root.config(cursor="")


class LoginView(tk.Frame):
    """Single responsibility: authenticate against the API."""

    def __init__(self, parent: tk.Frame, app: DesktopApp) -> None:
        super().__init__(parent, bg=BG)
        self.app = app
        self.pack(fill="both", expand=True)
        tk.Label(self, text="سكن بازرعة", bg=BG, fg=FG, font=FONT_TITLE).pack(pady=(60, 0))
        tk.Label(
            self, text="عميل سطح المكتب — تسجيل الدخول", bg=BG, fg="#9fd4bd", font=FONT
        ).pack(pady=(4, 30))

        form = tk.Frame(self, bg=BG)
        form.pack()
        tk.Label(form, text="اسم المستخدم", bg=BG, fg=FG, font=FONT).grid(
            row=0, column=0, sticky="e", padx=8, pady=6
        )
        self.username = ttk.Entry(form, width=32, font=FONT)
        self.username.grid(row=0, column=1, padx=8, pady=6)
        tk.Label(form, text="كلمة المرور", bg=BG, fg=FG, font=FONT).grid(
            row=1, column=0, sticky="e", padx=8, pady=6
        )
        self.password = ttk.Entry(form, width=32, font=FONT, show="•")
        self.password.grid(row=1, column=1, padx=8, pady=6)

        self.error = tk.Label(self, text="", bg=BG, fg="#ffb3a7", font=FONT_SMALL)
        self.error.pack(pady=(10, 0))

        ttk.Button(
            self, text="الدخول إلى النظام", command=self._submit, style="Accent.TButton"
        ).pack(pady=18)
        self.bind("<Return>", lambda _e: self._submit())
        self.password.focus_set()

    def _submit(self) -> None:
        username = self.username.get().strip()
        password = self.password.get()
        if not username or not password:
            self.error.config(text="أدخل اسم المستخدم وكلمة المرور")
            return
        _busy(self.app.root)
        try:
            self.app.api.login(username, password)
        except ApiError as exc:
            self.error.config(text=exc.detail or f"فشل الدخول (HTTP {exc.status})")
            self.password.delete(0, "end")
            return
        finally:
            _idle(self.app.root)
        try:
            self.app.user = self.app.api.me()
        except ApiError as exc:
            self.error.config(text=exc.detail or "فشل جلب البيانات")
            return
        if self.app.api.password_change_required:
            self.app.show_change_password(forced=True)
        else:
            self.app.show_main()


class ChangePasswordView(tk.Frame):
    """Forced password rotation; mirrors the portal's D2 policy flow."""

    def __init__(self, parent: tk.Frame, app: DesktopApp, forced: bool) -> None:
        super().__init__(parent, bg=BG)
        self.app = app
        self.forced = forced
        self.pack(fill="both", expand=True)

        tk.Label(
            self,
            text="تغيير كلمة المرور",
            bg=BG,
            fg=FG,
            font=FONT_TITLE,
        ).pack(pady=(70, 6))
        tk.Label(
            self,
            text="لأسباب أمنية يجب تغيير كلمة المرور قبل المتابعة"
            if forced
            else "حدّث كلمة المرور متى شئت",
            bg=BG,
            fg="#9fd4bd",
            font=FONT,
        ).pack(pady=(0, 24))

        form = tk.Frame(self, bg=BG)
        form.pack()
        fields = [("كلمة المرور الحالية", 0), ("الجديدة", 1), ("تأكيد الجديدة", 2)]
        self.entries: list[ttk.Entry] = []
        for label, row in fields:
            tk.Label(form, text=label, bg=BG, fg=FG, font=FONT).grid(
                row=row, column=0, sticky="e", padx=8, pady=6
            )
            entry = ttk.Entry(form, width=32, font=FONT, show="•")
            entry.grid(row=row, column=1, padx=8, pady=6)
            self.entries.append(entry)

        self.error = tk.Label(self, text="", bg=BG, fg="#ffb3a7", font=FONT_SMALL)
        self.error.pack(pady=(8, 0))
        ttk.Button(self, text="حفظ كلمة المرور", command=self._submit).pack(pady=14)
        if not forced:
            ttk.Button(self, text="رجوع", command=lambda: app.show_main()).pack()

    def _submit(self) -> None:
        current, new, confirm = (e.get() for e in self.entries)
        if not current or not new:
            self.error.config(text="أكمل جميع الحقول")
            return
        if new != confirm:
            self.error.config(text="الكلمتان الجديدتان غير متطابقتين")
            return
        _busy(self.app.root)
        try:
            self.app.api.change_password(current, new)
        except ApiError as exc:
            self.error.config(text=exc.detail or "فشل التغيير")
            return
        finally:
            _idle(self.app.root)
        messagebox.showinfo("تم", "تم تحديث كلمة المرور بنجاح")
        self.app.show_main()


class MainView(tk.Frame):
    """Shell with header, navigation and tabbed content."""

    TABS = [
        ("overview", "نظرة عامة"),
        ("users", "الحسابات"),
        ("applications", "طلبات السكن"),
        ("notifications", "الإشعارات"),
        ("password", "كلمة المرور"),
    ]

    def __init__(self, parent: tk.Frame, app: DesktopApp) -> None:
        super().__init__(parent, bg=BG)
        self.app = app
        self.pack(fill="both", expand=True)

        header = tk.Frame(self, bg=PANEL)
        header.pack(fill="x")
        user = app.user or {}
        tk.Label(
            header,
            text=f"{user.get('full_name') or user.get('username', '')}  —  {user.get('role', '')}",
            bg=PANEL,
            fg=FG,
            font=FONT,
        ).pack(side="left", padx=14, pady=10)
        ttk.Button(header, text="تسجيل الخروج", command=self._logout).pack(
            side="right", padx=14, pady=8
        )

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)
        self.views: dict[str, tk.Frame] = {}
        role = str(user.get("role", ""))
        for key, label in self.TABS:
            if key == "users" and role not in ADMIN_ROLES:
                continue  # account management: System Administrator only
            if key == "applications" and role not in APPLICATION_ROLES:
                continue  # application queue: student/affairs/housing only
            frame = tk.Frame(self.notebook, bg="#f4f7f5")
            self.notebook.add(frame, text=label)
            self.views[key] = frame

        # Replace the placeholder frame with the live tab so the deferred
        # refresh targets the tab instance (which owns the api client).
        self.views["overview"] = OverviewTab(self.views["overview"], app)
        if "users" in self.views:
            UsersTab(self.views["users"], app)
        if "applications" in self.views:
            ApplicationsTab(self.views["applications"], app)
        NotificationsTab(self.views["notifications"], app)
        PasswordTab(self.views["password"], app)
        self.views["overview"].after(120, self.views["overview"].refresh)

    def _logout(self) -> None:
        self.app.api.logout()
        self.app.user = {}
        self.app.show_login()


class OverviewTab(tk.Frame):
    """Role-scoped dashboard summary fetched from /dashboards/me."""

    def __init__(self, parent: tk.Frame, app: DesktopApp) -> None:
        super().__init__(parent, bg="#f4f7f5")
        self.app = app
        self.pack(fill="both", expand=True)
        bar = tk.Frame(self, bg="#f4f7f5")
        bar.pack(fill="x", padx=10, pady=8)
        ttk.Button(bar, text="تحديث", command=self.refresh).pack(side="right")
        self.tree = ttk.Treeview(self, columns=("label", "value"), show="headings", height=14)
        self.tree.heading("label", text="المؤشر")
        self.tree.heading("value", text="القيمة")
        self.tree.column("label", width=520, anchor="e")
        self.tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def refresh(self) -> None:
        try:
            data = self.app.api.dashboard()
        except ApiError as exc:
            messagebox.showerror("خطأ", exc.detail)
            return
        self.tree.delete(*self.tree.get_children())
        for item in data.get("stats", []):
            label = str(item.get("label", item.get("key", "")))
            self.tree.insert("", "end", values=(label, str(item.get("value", ""))))
        for item in data.get("attention", []):
            label = str(item.get("label", item.get("key", "")))
            self.tree.insert("", "end", values=(label + " ⚠", str(item.get("value", ""))))


class UsersTab(tk.Frame):
    """Administrator account management (no public registration by policy)."""

    def __init__(self, parent: tk.Frame, app: DesktopApp) -> None:
        super().__init__(parent, bg="#f4f7f5")
        self.app = app
        self.pack(fill="both", expand=True)
        bar = tk.Frame(self, bg="#f4f7f5")
        bar.pack(fill="x", padx=10, pady=8)
        ttk.Button(bar, text="إضافة حساب", command=self._add).pack(side="right", padx=4)
        ttk.Button(bar, text="تحديث", command=self.refresh).pack(side="right")
        self.tree = ttk.Treeview(
            self, columns=("username", "email", "role", "active"), show="headings", height=16
        )
        for col, label, width in (
            ("username", "اسم المستخدم", 220),
            ("email", "البريد", 280),
            ("role", "الدور", 200),
            ("active", "نشط", 80),
        ):
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.refresh()

    def refresh(self) -> None:
        try:
            page = self.app.api.list_users()
        except ApiError as exc:
            messagebox.showerror("خطأ", exc.detail)
            return
        self.tree.delete(*self.tree.get_children())
        for user in page.get("items", []):
            self.tree.insert(
                "",
                "end",
                values=(
                    user.get("username", ""),
                    user.get("email", ""),
                    user.get("role", ""),
                    "✓" if user.get("is_active") else "—",
                ),
            )

    def _add(self) -> None:
        AddUserDialog(self.app, on_done=self.refresh)


class AddUserDialog(tk.Toplevel):
    """Modal create-account form (POST /users)."""

    def __init__(self, app: DesktopApp, on_done) -> None:
        super().__init__(app.root)
        self.app = app
        self.on_done = on_done
        self.title("إضافة حساب جديد")
        self.configure(bg="#f4f7f5")
        self.resizable(False, False)
        self.transient(app.root)
        self.grab_set()

        fields = [
            ("اسم المستخدم", 0, "entry"),
            ("البريد الإلكتروني", 1, "entry"),
            ("كلمة المرور الأولية", 2, "password"),
            ("الدور", 3, "role"),
        ]
        self.entries: dict[str, ttk.Entry | ttk.Combobox] = {}
        for row, (label, grid_row, kind) in enumerate(fields):
            tk.Label(self, text=label, bg="#f4f7f5", font=FONT).grid(
                row=grid_row, column=0, sticky="e", padx=12, pady=6
            )
            if kind == "role":
                box = ttk.Combobox(
                    self, state="readonly", width=30,
                    values=[label_ar for _, label_ar in ROLE_LABELS],
                )
                box.set(ROLE_LABELS[0][1])
            elif kind == "password":
                box = ttk.Entry(self, width=32, show="•")
            else:
                box = ttk.Entry(self, width=32)
            box.grid(row=grid_row, column=1, padx=12, pady=6)
            self.entries[label] = box

        self.error = tk.Label(self, text="", bg="#f4f7f5", fg="#c0392b", font=FONT_SMALL)
        self.error.grid(row=4, column=0, columnspan=2)
        ttk.Button(self, text="إنشاء الحساب", command=self._submit).grid(
            row=5, column=0, columnspan=2, pady=12
        )

    def _submit(self) -> None:
        username = self.entries["اسم المستخدم"].get().strip()
        email = self.entries["البريد الإلكتروني"].get().strip()
        password = self.entries["كلمة المرور الأولية"].get()
        role_ar = self.entries["الدور"].get()
        role = next((en for en, ar in ROLE_LABELS if ar == role_ar), "")
        if not username or not email or not password or not role:
            self.error.config(text="أكمل جميع الحقول")
            return
        try:
            self.app.api.create_user(username, email, role, password)
        except ApiError as exc:
            self.error.config(text=exc.detail or "فشل الإنشاء")
            return
        messagebox.showinfo("تم", f"أُنشئ الحساب {username} بنجاح")
        self.on_done()
        self.destroy()


class ApplicationsTab(tk.Frame):
    """Housing application queue (staff view)."""

    def __init__(self, parent: tk.Frame, app: DesktopApp) -> None:
        super().__init__(parent, bg="#f4f7f5")
        self.app = app
        self.pack(fill="both", expand=True)
        bar = tk.Frame(self, bg="#f4f7f5")
        bar.pack(fill="x", padx=10, pady=8)
        ttk.Button(bar, text="تحديث", command=self.refresh).pack(side="right")
        self.tree = ttk.Treeview(
            self, columns=("applicant", "status", "created"), show="headings", height=16
        )
        for col, label, width in (
            ("applicant", "مقدم الطلب", 260),
            ("status", "الحالة", 260),
            ("created", "تاريخ التقديم", 200),
        ):
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.refresh()

    def refresh(self) -> None:
        try:
            page = self.app.api.applications()
        except ApiError as exc:
            messagebox.showerror("خطأ", exc.detail)
            return
        self.tree.delete(*self.tree.get_children())
        for item in page.get("items", []):
            self.tree.insert(
                "",
                "end",
                values=(
                    item.get("student_name", item.get("applicant_name", "")),
                    item.get("status", ""),
                    str(item.get("created_at", ""))[:16],
                ),
            )


class NotificationsTab(tk.Frame):
    """Personal notification mailbox."""

    def __init__(self, parent: tk.Frame, app: DesktopApp) -> None:
        super().__init__(parent, bg="#f4f7f5")
        self.app = app
        self.pack(fill="both", expand=True)
        bar = tk.Frame(self, bg="#f4f7f5")
        bar.pack(fill="x", padx=10, pady=8)
        self.count = tk.Label(bar, text="", bg="#f4f7f5", font=FONT)
        self.count.pack(side="left")
        ttk.Button(bar, text="تحديث", command=self.refresh).pack(side="right")
        self.tree = ttk.Treeview(
            self, columns=("title", "status", "date"), show="headings", height=16
        )
        for col, label, width in (
            ("title", "العنوان", 420),
            ("status", "الحالة", 160),
            ("date", "التاريخ", 200),
        ):
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.refresh()

    def refresh(self) -> None:
        try:
            page = self.app.api.notifications()
            unread = self.app.api.unread_count()
        except ApiError as exc:
            messagebox.showerror("خطأ", exc.detail)
            return
        self.count.config(text=f"غير مقروء: {unread}")
        self.tree.delete(*self.tree.get_children())
        for item in page.get("items", []):
            self.tree.insert(
                "",
                "end",
                values=(
                    item.get("title", ""),
                    item.get("status", ""),
                    str(item.get("created_at", ""))[:16],
                ),
            )


class PasswordTab(tk.Frame):
    """Self-service password change (not forced)."""

    def __init__(self, parent: tk.Frame, app: DesktopApp) -> None:
        super().__init__(parent, bg="#f4f7f5")
        self.app = app
        self.pack(fill="both", expand=True)
        form = tk.Frame(self, bg="#f4f7f5")
        form.pack(pady=30)
        self.entries: list[ttk.Entry] = []
        for row, label in enumerate(["كلمة المرور الحالية", "الجديدة", "تأكيد الجديدة"]):
            tk.Label(form, text=label, bg="#f4f7f5", font=FONT).grid(
                row=row, column=0, sticky="e", padx=8, pady=6
            )
            entry = ttk.Entry(form, width=30, show="•")
            entry.grid(row=row, column=1, padx=8, pady=6)
            self.entries.append(entry)
        self.error = tk.Label(form, text="", bg="#f4f7f5", fg="#c0392b", font=FONT_SMALL)
        self.error.grid(row=3, column=0, columnspan=2)
        ttk.Button(form, text="تحديث كلمة المرور", command=self._submit).grid(
            row=4, column=0, columnspan=2, pady=12
        )

    def _submit(self) -> None:
        current, new, confirm = (e.get() for e in self.entries)
        if new != confirm:
            self.error.config(text="الكلمتان الجديدتان غير متطابقتين")
            return
        try:
            self.app.api.change_password(current, new)
        except ApiError as exc:
            self.error.config(text=exc.detail or "فشل التغيير")
            return
        messagebox.showinfo("تم", "تم تحديث كلمة المرور")
        for entry in self.entries:
            entry.delete(0, "end")
