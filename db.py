"""
طبقة قاعدة البيانات - SQLite واحدة تخدم كل تبويبات لوحة التحكم.
نفس فلسفة app_settings (key/value) الموجودة أصلاً بالنسخة المكتبية،
لتسهيل أي ترحيل بيانات لاحق بينهما.
"""
import sqlite3
import os
from werkzeug.security import generate_password_hash

# ===== مسار قاعدة البيانات قابل للتخصيص عبر متغير بيئة ATTENDANCE_DB_PATH -
# يسمح بوضع الملف بمجلد آخر (مثلاً مجلد مزامَن بخدمة سحابية على سطح
# المكتب/الموبايل، أو قرص تخزين دائم على منصة استضافة سحابية) بدل المسار
# الافتراضي بجانب الكود مباشرة، بدون أي تعديل بالكود نفسه =====
DB_PATH = os.environ.get('ATTENDANCE_DB_PATH') or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'attendance_web.db')


def get_db():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")   # طلبات متزامنة (خادم متعدد الخيوط) تنتظر بدل «database is locked»
    return conn


def init_db():
    conn = get_db()
    try:
        conn.execute("PRAGMA journal_mode = WAL")   # قراءة وكتابة متزامنة بأمان أكبر
    except sqlite3.DatabaseError:
        pass
    cur = conn.cursor()

    # ===== المستخدمون والصلاحيات - نفس نموذج النسخة المكتبية بالضبط: 3
    # أدوار (admin/dept_manager/viewer) + 4 صلاحيات دقيقة مستقلة عن الدور
    # (تُعبَّأ بقيم افتراضية حسب الدور المختار، لكن قابلة للتعديل يدوياً
    # لكل مستخدم على حدة) - راجع user_can()/user_allowed_departments()
    # بـ app.py للتفاصيل الكاملة =====
    cur.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        full_name TEXT,
        role TEXT NOT NULL DEFAULT 'viewer',
        can_manage_employees INTEGER NOT NULL DEFAULT 0,
        can_manage_departments INTEGER NOT NULL DEFAULT 0,
        can_push_devices INTEGER NOT NULL DEFAULT 0,
        can_edit_org_settings INTEGER NOT NULL DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    )''')

    # ===== الأقسام المسموحة لكل مستخدم - قائمة فاضية (بدون أي صف هنا)
    # تعني بدون قيد (يشوف كل الأقسام)، تماماً كنفس منطق النسخة المكتبية =====
    cur.execute('''CREATE TABLE IF NOT EXISTS user_departments (
        user_id INTEGER NOT NULL,
        dept TEXT NOT NULL,
        PRIMARY KEY (user_id, dept),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )''')

    # ===== ترحيل: قاعدة بيانات قديمة من قبل إضافة نظام الصلاحيات الدقيقة -
    # نضيف الأعمدة الناقصة بدل حذف/إعادة إنشاء الجدول حتى لا تُفقد حسابات
    # المستخدمين الموجودة =====
    existing_user_cols = {r['name'] for r in cur.execute("PRAGMA table_info(users)").fetchall()}
    _added_perm_cols = False
    for col in ('can_manage_employees', 'can_manage_departments', 'can_push_devices', 'can_edit_org_settings'):
        if col not in existing_user_cols:
            cur.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0")
            _added_perm_cols = True
    if _added_perm_cols:
        # ترقية من نسخة قديمة (قبل نظام الأدوار الثلاثة): المستخدمون الذين
        # كانوا role='admin' مسبقاً يحصلون على الصلاحيات الأربع كاملة، بدل
        # أن تظهر كلها معطَّلة بواجهة المستخدمين رغم أن admin يتجاوزها فعلياً
        cur.execute(
            "UPDATE users SET can_manage_employees = 1, can_manage_departments = 1, "
            "can_push_devices = 1, can_edit_org_settings = 1 WHERE role = 'admin'"
        )

    cur.execute('''CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        dept TEXT,
        device_uid TEXT,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now'))
    )''')

    # ===== سجلات البصمات الخام المرفوعة (من ملف CSV/Excel) - عمود واحد لكل
    # حقل أساسي (اسم/تاريخ/حضور/انصراف/قسم)، بغض النظر عن أسماء الأعمدة
    # الأصلية بالملف المرفوع (تُعيَّن أسماء الأعمدة وقت الرفع) =====
    cur.execute('''CREATE TABLE IF NOT EXISTS punches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        date TEXT NOT NULL,
        dept TEXT,
        time_in TEXT,
        time_out TEXT,
        batch_id TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )''')

    # ===== ترحيل: عمود "synced" لجدولَي employees/punches - يميّز صفوف
    # عُدِّلت/أُضيفت محلياً ولسا ما انرفعت للقاعدة الرئيسية عبر ميزة
    # "نشر ومزامنة" (sync_engine.py) - 0 يعني "بانتظار الرفع"، يُحوَّل 1
    # فور نجاح الرفع. غير مستخدم إطلاقاً على نسخة تعمل لوحدها (بدون رابط
    # قاعدة رئيسية مُعدّ بالإعدادات) =====
    for table in ('employees', 'punches'):
        cols = {r['name'] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()}
        if 'synced' not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN synced INTEGER NOT NULL DEFAULT 0")

    cur.execute('''CREATE TABLE IF NOT EXISTS dept_attendance_settings (
        dept TEXT PRIMARY KEY,
        attendance_time TEXT,
        departure_time TEXT
    )''')

    if 'open_hours' not in {r['name'] for r in cur.execute("PRAGMA table_info(dept_attendance_settings)").fetchall()}:
        cur.execute("ALTER TABLE dept_attendance_settings ADD COLUMN open_hours INTEGER NOT NULL DEFAULT 0")   # دوام مفتوح بلا أوقات
    cur.execute('''CREATE TABLE IF NOT EXISTS manual_time_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        date TEXT NOT NULL,
        time_in TEXT,
        time_out TEXT,
        reason TEXT NOT NULL,
        entered_at TEXT DEFAULT (datetime('now')),
        UNIQUE(name, date)
    )''')

    cur.execute('''CREATE TABLE IF NOT EXISTS date_exceptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        date TEXT NOT NULL,
        reason TEXT,
        UNIQUE(name, date)
    )''')

    cur.execute('''CREATE TABLE IF NOT EXISTS official_holidays (
        date TEXT PRIMARY KEY,
        label TEXT
    )''')

    # ===== إذن التأخير - إما بالدقائق (تُخصم من التأخير الخام) أو بوقت
    # حضور/انصراف مخصَّص (يُعاد حساب التأخير بالكامل بمقارنته بهذا الوقت
    # بدل الوقت الافتراضي) - نفس منطق النسخة المكتبية بالضبط =====
    cur.execute('''CREATE TABLE IF NOT EXISTS late_permissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        date TEXT NOT NULL,
        minutes INTEGER DEFAULT 0,
        custom_attendance_time TEXT,
        custom_departure_time TEXT,
        label TEXT,
        UNIQUE(name, date)
    )''')

    # ===== إذن مغادرة مؤقتة أثناء الدوام - تُخصم مدتها من ساعات العمل
    # المحسوبة فقط، بدون أي تأثير على التأخير أو تصنيف الحالة (الموظف
    # حاضر وبالوقت أصلاً) =====
    cur.execute('''CREATE TABLE IF NOT EXISTS departure_permissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        date TEXT NOT NULL,
        departure_time TEXT NOT NULL,
        return_time TEXT NOT NULL,
        reason TEXT,
        UNIQUE(name, date)
    )''')

    # ===== أجهزة البصمة (ZKTeco) - اسم/عنوان IP/بورت/كلمة سر الاتصال -
    # بديل شبكي عن قائمة الأجهزة الثابتة بالكود بالنسخة المكتبية، مع إمكانية
    # إضافة/حذف أي عدد من الأجهزة من الواجهة مباشرة =====
    cur.execute('''CREATE TABLE IF NOT EXISTS devices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        ip TEXT NOT NULL,
        port INTEGER NOT NULL DEFAULT 4370,
        password TEXT DEFAULT '0',
        location TEXT,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now'))
    )''')

    # ===== سجل التدقيق - يسجّل كل التعديلات الحساسة (إدخال يدوي، استثناء
    # تاريخ، عطلة رسمية، إذن تأخير/مغادرة) مع من قام بها ومتى والقيمة
    # القديمة والجديدة، لمرجعية دائمة =====
    cur.execute('''CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT DEFAULT (datetime('now')),
        username TEXT,
        action_type TEXT NOT NULL,
        target_type TEXT NOT NULL,
        employee_name TEXT,
        date_affected TEXT,
        old_value TEXT,
        new_value TEXT,
        reason TEXT
    )''')

    # ===== سبب الغياب - مرتبط بحالة "غائب" المحسوبة فعلياً بعد التحليل
    # (بعكس date_exceptions التي تُستثنى بالكامل من الحساب الطبيعي بحالة
    # "استثناء" منفصلة) - يُستخدم لعرض سبب الغياب (لو مسجَّل) بجانب اسم
    # الغائب بتقارير/رسائل البريد، تماماً كما بالنسخة المكتبية =====
    cur.execute('''CREATE TABLE IF NOT EXISTS absence_reasons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        date TEXT NOT NULL,
        reason TEXT NOT NULL,
        entered_at TEXT DEFAULT (datetime('now')),
        UNIQUE(name, date)
    )''')

    # ===== الغياب الإجباري - يُجبر (موظف، تاريخ) يُحسب "غائب" فعلياً حتى
    # لو كان يوم عطلة أسبوعية (لمناوب كان مفروض يحضر ذاك اليوم تحديداً)،
    # أو حتى لو ما عنده أي بصمة إطلاقاً - أعلى أولوية من العطلة الأسبوعية،
    # لكن أقل أولوية من استثناء شخصي أو عطلة رسمية (راجع run_full_analysis
    # بـ app.py للتفاصيل الكاملة) =====
    cur.execute('''CREATE TABLE IF NOT EXISTS forced_absences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        date TEXT NOT NULL,
        reason TEXT,
        entered_at TEXT DEFAULT (datetime('now')),
        UNIQUE(name, date)
    )''')

    cur.execute('''CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')

    # ===== نتيجة آخر تحليل - تُعاد كتابتها بالكامل كل مرة يُضغط فيها
    # "تحليل البيانات"، وتُستخدم كمصدر وحيد لتبويب التقارير ولوحة التحكم =====
    cur.execute('''CREATE TABLE IF NOT EXISTS report_cache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        dept TEXT,
        date TEXT NOT NULL,
        weekday INTEGER,
        time_in TEXT,
        time_out TEXT,
        status TEXT,
        late_minutes INTEGER DEFAULT 0,
        working_hours REAL DEFAULT 0,
        shift TEXT
    )''')

    # ===== ترحيل: قاعدة بيانات قديمة أُنشئت قبل إضافة عمود "shift" -
    # نضيفه هنا بدل حذف/إعادة إنشاء الجدول حتى لا تُفقد بيانات المستخدم =====
    existing_cols = {r['name'] for r in cur.execute("PRAGMA table_info(report_cache)").fetchall()}
    if 'shift' not in existing_cols:
        cur.execute("ALTER TABLE report_cache ADD COLUMN shift TEXT")
    if 'early_minutes' not in existing_cols:   # دقائق المغادرة المبكرة
        cur.execute("ALTER TABLE report_cache ADD COLUMN early_minutes INTEGER DEFAULT 0")
    if 'out_flag' not in existing_cols:        # '' / missing (بدون سجل انصراف) / auto (أُغلق تلقائياً)
        cur.execute("ALTER TABLE report_cache ADD COLUMN out_flag TEXT DEFAULT ''")
    if 'break_minutes' not in existing_cols:   # خروج مؤقت من البصمات الوسطى في جهاز البصمة (دقائق)
        cur.execute("ALTER TABLE report_cache ADD COLUMN break_minutes INTEGER DEFAULT 0")
    # كل بصمات أجهزة البصمة بأوقاتها (لا أول/آخر بصمة فقط) — لاحتساب الخروج والعودة من البصمات الوسطى
    cur.execute('''CREATE TABLE IF NOT EXISTS device_punch_times (
        name TEXT NOT NULL, date TEXT NOT NULL, time TEXT NOT NULL, source TEXT,
        PRIMARY KEY (name, date, time)
    )''')

    # ===== تطبيق الموظفين على الهاتف: حسابات دخول + ربط الهاتف + مواقع العمل (Geofence) + الحركات =====
    cur.execute('''CREATE TABLE IF NOT EXISTS employee_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER UNIQUE NOT NULL,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        anywhere INTEGER NOT NULL DEFAULT 0,
        device_hash TEXT,
        device_label TEXT,
        bound_at TEXT,
        last_login_at TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS work_sites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        lat REAL NOT NULL,
        lng REAL NOT NULL,
        radius_m INTEGER NOT NULL DEFAULT 150,
        depts_json TEXT NOT NULL DEFAULT '[]',
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS mobile_punches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER,
        name TEXT NOT NULL,
        dept TEXT,
        kind TEXT NOT NULL,
        date TEXT NOT NULL,
        time TEXT NOT NULL,
        lat REAL, lng REAL, accuracy REAL,
        site_id INTEGER, site_name TEXT, distance_m REAL,
        status TEXT NOT NULL DEFAULT 'accepted',
        reason TEXT,
        device_label TEXT,
        ip TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    cur.execute("CREATE INDEX IF NOT EXISTS ix_mobile_punches_date ON mobile_punches(date, employee_id)")
    # ترحيل: حماية من الموقع الوهمي — شبكة العمل لكل موقع + مصدر الحركة وعلامات الاشتباه
    site_cols = {r['name'] for r in cur.execute("PRAGMA table_info(work_sites)").fetchall()}
    if 'ips' not in site_cols:
        cur.execute("ALTER TABLE work_sites ADD COLUMN ips TEXT NOT NULL DEFAULT ''")
    if 'ip_required' not in site_cols:
        cur.execute("ALTER TABLE work_sites ADD COLUMN ip_required INTEGER NOT NULL DEFAULT 0")
    mp_cols = {r['name'] for r in cur.execute("PRAGMA table_info(mobile_punches)").fetchall()}
    for col, typ in (('flags', "TEXT"), ('source', "TEXT")):
        if col not in mp_cols:
            cur.execute(f"ALTER TABLE mobile_punches ADD COLUMN {col} {typ}")
    # ===== ملف الموظف: طريقة توثيق الدوام + استثناءات Geofence + إشعارات + البصمة الحيوية =====
    emp_cols = {r['name'] for r in cur.execute("PRAGMA table_info(employees)").fetchall()}
    if 'attendance_mode' not in emp_cols:   # device = جهاز البصمة فقط، mobile = الهاتف فقط، both = الاثنين
        cur.execute("ALTER TABLE employees ADD COLUMN attendance_mode TEXT NOT NULL DEFAULT 'both'")
    for col in ('phone', 'email', 'job_title', 'notes'):
        if col not in emp_cols:
            cur.execute(f"ALTER TABLE employees ADD COLUMN {col} TEXT")
    if 'presence_monitor' not in emp_cols:   # مراقبة الحضور أثناء الدوام لهذا الموظف (عند اختيار «موظفون محددون»)
        cur.execute("ALTER TABLE employees ADD COLUMN presence_monitor INTEGER NOT NULL DEFAULT 0")
    # ===== مراقبة الحضور أثناء الدوام: قراءات موقع دورية + تنبيهات + فحوص عشوائية =====
    cur.execute('''CREATE TABLE IF NOT EXISTS presence_pings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        ts TEXT NOT NULL,
        lat REAL, lng REAL, accuracy REAL,
        inside INTEGER,              -- 1 داخل النطاق، 0 خارجه، NULL بلا موقع
        distance_m REAL,
        status TEXT NOT NULL DEFAULT 'ok'   -- ok / location_off / mock / exempt
    )''')
    cur.execute("CREATE INDEX IF NOT EXISTS ix_presence_pings_emp ON presence_pings(employee_id, date, ts)")
    if 'source' not in {r['name'] for r in cur.execute("PRAGMA table_info(presence_pings)").fetchall()}:
        cur.execute("ALTER TABLE presence_pings ADD COLUMN source TEXT NOT NULL DEFAULT 'app'")   # app (خلفية أندرويد) / web (الصفحة مفتوحة)
    cur.execute('''CREATE TABLE IF NOT EXISTS presence_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        name TEXT, dept TEXT,
        date TEXT NOT NULL,
        kind TEXT NOT NULL,          -- outside / no_location / no_signal / missed_check / failed_check
        start_ts TEXT NOT NULL,
        end_ts TEXT,
        minutes INTEGER NOT NULL DEFAULT 0,
        details TEXT,
        open INTEGER NOT NULL DEFAULT 1
    )''')
    cur.execute("CREATE INDEX IF NOT EXISTS ix_presence_events_date ON presence_events(date)")
    # ===== الخروج المؤقت: طلبات (من–إلى) + موافقة اختيارية + متابعة العودة =====
    cur.execute('''CREATE TABLE IF NOT EXISTS leave_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        name TEXT, dept TEXT,
        date TEXT NOT NULL,
        from_time TEXT NOT NULL,          -- HH:MM
        to_time TEXT NOT NULL,            -- HH:MM (العودة المتوقعة)
        reason TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        -- pending / approved / rejected / cancelled / expired / active / overdue / returned / returned_late / not_returned
        out_time TEXT, back_time TEXT,
        requested_at TEXT, decided_by TEXT, decided_at TEXT, decision_note TEXT,
        source TEXT NOT NULL DEFAULT 'request'   -- request (بطلب) / direct (عند الضغط على «خروج مؤقت»)
    )''')
    cur.execute("CREATE INDEX IF NOT EXISTS ix_leave_requests_date ON leave_requests(date, status)")
    cur.execute('''CREATE TABLE IF NOT EXISTS push_subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        endpoint TEXT UNIQUE NOT NULL,
        p256dh TEXT NOT NULL,
        auth TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    if 'notified' not in {r['name'] for r in cur.execute("PRAGMA table_info(presence_checks)").fetchall()} and \
            cur.execute("SELECT name FROM sqlite_master WHERE name = 'presence_checks'").fetchone():
        cur.execute("ALTER TABLE presence_checks ADD COLUMN notified INTEGER NOT NULL DEFAULT 0")
    cur.execute('''CREATE TABLE IF NOT EXISTS presence_checks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        due_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',   -- pending / confirmed / missed / outside
        responded_at TEXT,
        lat REAL, lng REAL, distance_m REAL,
        notified INTEGER NOT NULL DEFAULT 0
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS geofence_overrides (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        starts_at TEXT NOT NULL,
        ends_at TEXT NOT NULL,
        no_location INTEGER NOT NULL DEFAULT 0,
        reason TEXT NOT NULL,
        created_by TEXT,
        revoked INTEGER NOT NULL DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS employee_notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        body TEXT,
        created_by TEXT,
        read_at TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
    )''')
    if 'device_shown_at' not in {r['name'] for r in cur.execute("PRAGMA table_info(employee_notifications)").fetchall()}:
        cur.execute("ALTER TABLE employee_notifications ADD COLUMN device_shown_at TEXT")   # عُرض كإشعار أندرويد
    cur.execute('''CREATE TABLE IF NOT EXISTS webauthn_credentials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        cred_id TEXT UNIQUE NOT NULL,
        public_key TEXT NOT NULL,
        alg INTEGER,
        sign_count INTEGER NOT NULL DEFAULT 0,
        label TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
    )''')
    user_cols = {r['name'] for r in cur.execute("PRAGMA table_info(users)").fetchall()}
    cur.execute('''CREATE TABLE IF NOT EXISTS user_login_devices (
        user_id INTEGER NOT NULL,
        device_hash TEXT NOT NULL,
        label TEXT,
        created_at TEXT,
        PRIMARY KEY (user_id, device_hash)
    )''')
    for col in ('last_login_at', 'last_login_ip', 'email', 'fav_tabs'):
        if col not in user_cols:
            cur.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT")
    # ===== أجهزة المداخل (QR): تابلت عند الباب يقرأ رمز الموظف المتغيّر =====
    acc_cols = {r['name'] for r in cur.execute("PRAGMA table_info(employee_accounts)").fetchall()}
    if 'always_track' not in acc_cols:   # تتبع مستمر بلا مدة (للأجهزة المتنقلة) — تفعّله الإدارة
        cur.execute("ALTER TABLE employee_accounts ADD COLUMN always_track INTEGER NOT NULL DEFAULT 0")
    if 'track_interval' not in acc_cols:   # فاصل إرسال التتبع المستمر بالثواني (5 / 10 / 15 / 30 / 60)
        cur.execute("ALTER TABLE employee_accounts ADD COLUMN track_interval INTEGER NOT NULL DEFAULT 60")
    if 'qr_secret' not in acc_cols:
        cur.execute("ALTER TABLE employee_accounts ADD COLUMN qr_secret TEXT")
    if 'bio_mode' not in acc_cols:   # بصمة الحضور لكل موظف: '' = حسب الإعداد العام، off / optional / required
        cur.execute("ALTER TABLE employee_accounts ADD COLUMN bio_mode TEXT NOT NULL DEFAULT ''")
    cur.execute('''CREATE TABLE IF NOT EXISTS qr_kiosks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        site_id INTEGER,
        token_hash TEXT,
        pair_code TEXT,
        pair_expires TEXT,
        active INTEGER NOT NULL DEFAULT 1,
        last_seen TEXT,
        last_ip TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS kiosk_scans_seen (
        uid TEXT PRIMARY KEY,
        kiosk_id INTEGER,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    # ===== نسيان كلمة المرور: روابط بريد لمرة واحدة + طلبات تصل للإدارة (لمن لا بريد له) =====
    cur.execute('''CREATE TABLE IF NOT EXISTS password_reset_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,                -- user (مستخدم النظام) أو emp (موظف)
        subject_id INTEGER NOT NULL,
        token_hash TEXT UNIQUE NOT NULL,
        expires_at TEXT NOT NULL,
        used_at TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS password_reset_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        subject_id INTEGER NOT NULL,
        label TEXT,
        ip TEXT,
        status TEXT NOT NULL DEFAULT 'pending',   -- pending / done / dismissed
        handled_by TEXT,
        handled_at TEXT,
        created_at TEXT
    )''')

    conn.commit()

    # ===== مستخدم افتراضي واحد عند أول تشغيل فقط - اسم المستخدم/كلمة
    # المرور يجب تغييرهما فوراً من تبويب "المستخدمون" بعد أول دخول =====
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        cur.execute(
            "INSERT INTO users (username, password_hash, full_name, role, can_manage_employees, "
            "can_manage_departments, can_push_devices, can_edit_org_settings) VALUES (?, ?, ?, ?, 1, 1, 1, 1)",
            ('admin', generate_password_hash(os.environ.get('ATTENDANCE_ADMIN_PASSWORD') or 'admin123'), 'مدير النظام', 'admin')
        )
        conn.commit()

    conn.close()


def get_setting(key, default=''):
    conn = get_db()
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row['value'] if row is not None else default


def set_setting(key, value):
    conn = get_db()
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value)
    )
    conn.commit()
    conn.close()


def get_all_settings():
    defaults = {
        'org_name': 'الجمعية الثقافية العربية - مدرسة الرائد العربي',
        'org_name_en': '',   # اسم المؤسسة في الواجهة الإنجليزية (اختياري)
        'org_logo_filename': '',
        'attendance_time': '09:00',
        'departure_time': '15:00',
        'late_threshold': '5',
        'shift_enabled': '0',
        'shift1_start': '08:30',
        'shift1_end': '15:00',
        'shift2_start': '15:00',
        'shift2_end': '21:00',
        'sat_time_enabled': '0',
        'sat_attendance_time': '09:00',
        'sat_departure_time': '13:00',
        'excluded_depts': '',

        # ===== إعدادات إرسال البريد - تُستخدم بالجدولة التلقائية والتصدير
        # الفوري وباختبار الإرسال اليدوي. email_method يحدد أياً من
        # الطريقتين فعّالة فعلياً (smtp أو graph)، وتبقى إعدادات الطريقة
        # الأخرى محفوظة بدون استخدام لو بدَّل المستخدم لاحقاً =====
        'email_method': 'smtp',
        'smtp_host': 'smtp.office365.com',
        'smtp_port': '587',
        'smtp_sender_email': '',
        'smtp_sender_password': '',
        'smtp_recipients': '',
        'smtp_provider': 'microsoft',     # google / microsoft / custom (قوالب جاهزة لإعدادات SMTP)
        'smtp_security': 'starttls',      # starttls (587) / ssl (465) / none
        'smtp_username': '',              # اسم الدخول إن اختلف عن بريد المرسل
        'smtp_sender_name': '',           # الاسم الظاهر للمستلم

        # ===== إرسال عبر Microsoft Graph API (Client Credentials) - بديل
        # حديث لـ SMTP AUTH التقليدي، خصوصاً بعد تعطيل مايكروسوفت له
        # بكثير من المستأجرين. يتطلب تسجيل تطبيق بـ Entra ID بصلاحية
        # Application من نوع Mail.Send مع موافقة المدير =====
        'graph_tenant_id': '',
        'graph_client_id': '',
        'graph_client_secret': '',
        'graph_sender_upn': '',

        # ===== نسخة احتياطية لملف قاعدة البيانات على OneDrive - تستخدم
        # نفس اعتماد Graph أعلاه (تحتاج صلاحية Application إضافية:
        # Files.ReadWrite.All) بدل رفعها على Google Drive (يحتاج حساب
        # Google غير متوفر لمستأجرات Microsoft 365 المؤسسية) =====
        'onedrive_backup_upn': '',
        'onedrive_backup_folder': 'AttendanceBackups',
        'onedrive_last_backup_at': '',
        'onedrive_last_backup_status': '',

        # ===== نسخة احتياطية على Google Drive (بديل عن OneDrive - يفيد
        # لو ما توفّرت صلاحية "Global Admin" على مستأجر Microsoft 365
        # اللازمة لمنح Admin Consent بطريقة Graph) - راجع gdrive_backup.py =====
        'gdrive_service_account_json_path': '',
        'gdrive_backup_folder_id': '',
        'gdrive_last_backup_at': '',
        'gdrive_last_backup_status': '',

        # ===== إعدادات الجدولة التلقائية (مهمة واحدة عامة - سحب اختياري
        # من الأجهزة + تحليل + إرسال بريد) =====
        'schedule_enabled': '0',
        'schedule_time': '07:00',
        'schedule_days_json': '[]',  # فاضية = كل يوم
        'schedule_status_filter': 'absent_or_late',
        'schedule_pull_before': '0',
        'schedule_last_run_at': '',
        'schedule_last_run_status': '',
        'schedule_last_run_message': '',
        'schedule_last_run_date': '',

        # ===== المزامنة مع قاعدة بيانات مركزية سحابية (اختياري بالكامل -
        # فاضية = هذه نسخة عادية مستقلة لا تُزامن مع أي مكان). لو عُبِّئت،
        # تظهر ميزة "نشر ومزامنة" لرفع التعديلات المحلية (موظفين/بصمات) إلى
        # نسخة أخرى من نفس النظام تعمل كـ"القاعدة الرئيسية" (راجع
        # sync_engine.py) - يجب أن يطابق sync_api_key نفس القيمة المضبوطة
        # بإعدادات النسخة المركزية تماماً =====
        # ===== تطبيق الموظفين على الهاتف (Geofence) =====
        'mobile_enabled': '1',            # تسجيل الحركات من الهاتف مفعّل
        'mobile_bind_device': '1',        # ربط حساب الموظف بهاتف واحد فقط
        'mobile_max_accuracy': '150',     # أقصى خطأ مقبول في دقة الموقع (متر)
        'mobile_require_geofence': '1',   # منع التسجيل خارج مواقع العمل
        'device_breaks': '1',             # البصمات الوسطى في جهاز البصمة = خروج ← عودة (يُخصم من ساعات العمل)
        'auto_checkout': '0',             # إغلاق الانصراف المنسي تلقائياً بوقت نهاية الدوام (يُعلَّم للمراجعة)
        'mobile_leave_deduct': '1',       # الخروج المؤقت يُخصم من ساعات العمل
        'mobile_require_app': '0',        # التسجيل من تطبيق الموظف (APK) فقط — لا من المتصفح
        'leave_max_minutes': '60',        # أقصى مدة للخروج المؤقت (0 = بلا حد)
        'leave_grace_min': '10',          # مهلة بعد وقت العودة قبل اعتباره متأخراً
        'leave_approval': '0',            # 1 = الخروج المؤقت يتطلب طلباً وموافقة مسبقة
        'leave_unreturned_early': '1',    # من لم يعد حتى نهاية الدوام يُحتسب خروجه مغادرة مبكرة
        'presence_enabled': '0',          # مراقبة الحضور أثناء الدوام (تشغيل/إيقاف عام)
        'presence_scope': 'selected',     # all = كل موظفي التطبيق، selected = المحددون فقط (أقسام و/أو موظفون)
        'presence_depts_json': '[]',      # الأقسام المشمولة بالمراقبة عند «المحددون»
        'presence_interval_min': '10',    # كل كم دقيقة يرسل تطبيق أندرويد الموقع
        'presence_grace_min': '20',       # مدة البقاء خارج النطاق قبل التنبيه
        'presence_checks_per_day': '0',   # فحوص حضور عشوائية يومياً (0 = بلا فحوص)
        'presence_check_window_min': '10',  # مهلة الرد على الفحص
        'mobile_biometric': 'off',        # بصمة الوجه/الإصبع قبل كل حركة: off / optional / required
        'mobile_suspicious': 'flag',      # الحركة المشبوهة (موقع ثابت/قفزة/شبكة أخرى): flag = تُقبل مع علامة، reject = تُرفض
        'sync_central_url': '',
        'sync_api_key': '',
        'sync_last_push_at': '',
        'sync_last_push_status': '',
    }
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
    conn.close()
    result = dict(defaults)
    for r in rows:
        if r['key'] in defaults:
            result[r['key']] = r['value']
    return result
