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
