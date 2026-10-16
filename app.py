"""
نظام تحليل سجلات الحضور والانصراف - النسخة الشبكية (Flask)
الجمعية الثقافية العربية - مدرسة الرائد العربي

هذه هي الحزمة "الأساسية" الأولى من التحويل التدريجي من النسخة المكتبية
(Tkinter) إلى واجهة ويب: لوحة تحكم، رفع بيانات وتحليل، تقارير مع فلترة،
إدخال يدوي، أوقات الأقسام، وإعدادات عامة - بنفس لغة التصميم البصري
المعتمدة (Sidebar + Topbar + بطاقات إحصاء + جداول + نوافذ منبثقة + Toast).
"""
import hashlib
import os
import io
import csv
import json
import re
import uuid
import sqlite3
import tempfile
from functools import wraps
from datetime import datetime, timedelta

from flask import (Flask, render_template, request, jsonify, session,
                    redirect, url_for, send_file, Response)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
import pandas as pd

import db
from attendance_engine import analyze, parse_time_str
from pdf_export import build_report_pdf
import overtime_engine
import email_sender
from app_helpers import STATUS_FILTERS
import zk_devices
import mdb_import
import sqlite_import
import face_copy
import cloud_import
import sync_engine
import onedrive_backup
import gdrive_backup

import mimetypes  # noqa: E402
mimetypes.add_type('application/vnd.android.package-archive', '.apk')
mimetypes.add_type('application/manifest+json', '.webmanifest')

app = Flask(__name__)


def _secret_key():
    """مفتاح الجلسات: من .env، وإلا يُولَّد مرة واحدة ويُحفظ بجانب قاعدة البيانات (لا مفتاح افتراضي معروف)"""
    key = os.environ.get('ATTENDANCE_SECRET_KEY') or os.environ.get('SECRET_KEY')
    if key:
        return key
    path = os.path.join(os.path.dirname(os.path.abspath(db.DB_PATH)), '.secret_key')
    try:
        with open(path, encoding='utf-8') as fh:
            key = fh.read().strip()
    except OSError:
        key = ''
    if not key:
        import secrets as _s
        key = _s.token_urlsafe(48)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(key)
    return key


app.secret_key = _secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=(os.environ.get('BASE_URL', '').startswith('https://')),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=int(os.environ.get('SESSION_HOURS', '12') or 12)),
)

# أسرار لا تُرسل للمتصفح أبداً — تظهر كنجوم، وإرسال النجوم كما هي يعني «بدون تغيير»
SECRET_SETTINGS = ('smtp_sender_password', 'graph_client_secret', 'sync_api_key')
SECRET_MASK = '••••••••'


def mask_secrets(d):
    return {k: (SECRET_MASK if k in SECRET_SETTINGS and v else v) for k, v in d.items()}

# تطبيق الموظفين على الهاتف (تسجيل الحركات + Geofence + ربط الهاتف) — انظر mobile.py
from mobile import bp as _mobile_bp  # noqa: E402
app.register_blueprint(_mobile_bp)
import adms as _adms  # noqa: E402 — استقبال البصمات من الأجهزة عبر الإنترنت (ADMS / Cloud Server)
app.register_blueprint(_adms.bp)
import admin_notes as _admin_notes  # noqa: E402 — إشعارات أندرويد لتطبيق الإدارة
app.register_blueprint(_admin_notes.bp)
import shares as _shares  # noqa: E402 — مشاركة الموقع من تطبيق الموظف
app.register_blueprint(_shares.bp)
try:
    _c = db.get_db()
    _adms.init_tables(_c)
    _admin_notes.init_tables(_c)
    _shares.init_tables(_c)
    _c.commit()
    _c.close()
except Exception:
    pass

# حماية مصدر الصفحات (تشفير + منع الزر الأيمن والاختصارات) — انظر utils/page_shield.py
from utils.page_shield import install as _shield  # noqa: E402
_shield(app)

# ===== شعار المؤسسة - يُحفَظ كملف واحد تحت static/uploads/ (اسم ثابت
# "org_logo.<امتداد>")، والامتداد الفعلي يُحفَظ بإعداد org_logo_filename
# حتى تُعرف صيغته عند العرض/التضمين بالتقارير والبريد =====
LOGO_UPLOAD_DIR = os.path.join(app.static_folder, 'uploads')
os.makedirs(LOGO_UPLOAD_DIR, exist_ok=True)
_ALLOWED_LOGO_EXT = {'png', 'jpg', 'jpeg', 'jfif', 'gif', 'webp', 'bmp'}
_MAX_LOGO_BYTES = 15 * 1024 * 1024  # يُقبل حتى 15MB ثم يُصغَّر تلقائياً إلى 1024px


def get_logo_path(settings=None):
    """يُعيد المسار المطلق لملف الشعار الحالي لو محفوظاً وموجوداً فعلياً
    على القرص، وإلا None - تستخدمه كل نقاط تضمين الشعار (PDF/بريد)."""
    settings = settings or db.get_all_settings()
    filename = settings.get('org_logo_filename')
    if not filename:
        return None
    path = os.path.join(LOGO_UPLOAD_DIR, filename)
    return path if os.path.isfile(path) else None


# ============================================================
# ===== سجل التدقيق =====
# ============================================================
from utils.i18n import tr as _tr, ui_lang as _ui_lang, translate_json as _translate_json  # noqa: E402


def _audit_now():
    """وقت محلي (المنطقة الزمنية ATT_TZ) بدل UTC الافتراضي في SQLite"""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(os.environ.get('ATT_TZ', 'Asia/Amman'))).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def log_audit(conn, action_type, target_type, employee_name=None, date_affected=None,
              old_value=None, new_value=None, reason=None):
    """يسجّل عملية حساسة بسجل التدقيق. لا يرمي استثناء عند الفشل حتى لا
    يعطّل العملية الأساسية - التدقيق إضافي وليس شرطاً لنجاح الطلب."""
    try:
        conn.execute(
            "INSERT INTO audit_log (username, action_type, target_type, employee_name, "
            "date_affected, old_value, new_value, reason, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (session.get('username', ''), action_type, target_type, employee_name,
             date_affected, old_value, new_value, reason, _audit_now())
        )
    except Exception:
        pass

RT_LABELS = {
    'all': 'الكامل', 'late': 'المتأخرون', 'absent': 'الغائبون',
    'ontime': 'في الوقت', 'shift': 'المناوبون', 'sat_present': 'حاضرو السبت',
    'holiday': 'عطلة أسبوعية',
}


# ============================================================
# ===== المصادقة والصلاحيات =====
# ============================================================
# ===== نظام صلاحيات مطابق للنسخة المكتبية (home.py) بالضبط: 3 أدوار
# (admin/dept_manager/viewer) + 4 صلاحيات دقيقة مستقلة عن الدور نفسه
# (can_manage_employees/can_manage_departments/can_push_devices/
# can_edit_org_settings)، بالإضافة لتقييد اختياري بالأقسام لكل مستخدم
# (user_departments - قائمة فاضية = بدون قيد). في home.py كل التبويبات
# ظاهرة لأي مستخدم مسجَّل دخول عدا "المستخدمون" (admin فقط)، والصلاحيات
# الأربع تُعطِّل/تُفعِّل أزراراً محدَّدة بس (موظفين/أجهزة/إعدادات المؤسسة) -
# نفس الفلسفة هنا، لكن التطبيق فعلي بالخادم (403) لأن هذا تطبيق ويب
# معرَّض على الشبكة، بعكس الأصل المكتبي المحلي الذي يكتفي بتعطيل الزر.
#
# ملاحظة اختيار أمان (بطلب المستخدم): بعض الإجراءات الحسّاسة كانت مفتوحة
# لأي مستخدم بلا أي قيد بالأصل المكتبي (تعديل الإعدادات العامة، إضافة/
# حذف/تعديل جهاز بصمة، سحب/مسح سجل جهاز، فتح باب) - هنا قُيِّدت بصلاحية
# can_edit_org_settings للإعدادات العامة، و can_push_devices لكل إجراءات
# الأجهزة، بدل تركها مفتوحة كالأصل، لأن هذه نسخة ويب وليست جهازاً مكتبياً
# محلياً موثوقاً به بالكامل. أما can_manage_departments فتبقى صلاحية
# محفوظة غير مفعَّلة فعلياً (تماماً كالأصل - كانت مخصَّصة لحذف قسم فارغ،
# وهي وظيفة غير موجودة بهذه النسخة أصلاً) =====
_PERMISSION_KEYS = ('can_manage_employees', 'can_manage_departments', 'can_push_devices', 'can_edit_org_settings')

# مسارات تتطلب صلاحية دقيقة معيّنة (غير admin) - الافتراضي لأي مسار آخر
# غير مذكور هنا هو: مفتوح لأي مستخدم مسجَّل دخول (نفس home.py بالضبط)
PERMISSION_REQUIRED_ENDPOINTS = {
    'api_employees': 'can_manage_employees',
    'api_employee_delete': 'can_manage_employees',
    'api_employees_import': 'can_manage_employees',

    'api_settings': 'can_edit_org_settings',
    'api_settings_logo': 'can_edit_org_settings',
    'api_shift_names': 'can_edit_org_settings',
    'api_dept_times': 'can_edit_org_settings',
    'api_dept_time_delete': 'can_edit_org_settings',

    'api_devices': 'can_push_devices',
    'api_device_edit': 'can_push_devices',
    'api_device_test': 'can_push_devices',
    'api_devices_pull': 'can_push_devices',
    'api_devices_push': 'can_push_devices',
    'api_device_unlock': 'can_push_devices',
    'api_device_clear_attendance': 'can_push_devices',
    'api_device_delete_users': 'can_push_devices',
    'api_devices_live_start': 'can_push_devices',
    'api_devices_live_stop': 'can_push_devices',
    'api_devices_copy_fingerprint': 'can_push_devices',
    'api_devices_copy_face': 'can_push_devices',
    'api_devices_import_mdb': 'can_push_devices',
    'api_devices_import_sqlite': 'can_push_devices',
    'api_sync_push': 'can_push_devices',

    # إعدادات البريد والجدولة والنسخ الاحتياطي ومسح السجلات — لمن يملك صلاحية إعدادات المؤسسة فقط
    'api_schedule': 'can_edit_org_settings',
    'api_schedule_test_email': 'can_edit_org_settings',
    'api_schedule_run_now': 'can_edit_org_settings',
    'api_backup_onedrive': 'can_edit_org_settings',
    'api_backup_onedrive_run': 'can_edit_org_settings',
    'api_backup_gdrive': 'can_edit_org_settings',
    'api_backup_gdrive_run': 'can_edit_org_settings',
    'api_punches_clear': 'can_edit_org_settings',

    # تطبيق الموظفين على الهاتف (mobile.py)
    'mobile.api_accounts': 'can_manage_employees',
    'mobile.api_leaves_decide': 'can_manage_employees',
    'mobile.api_leaves_delete': 'can_manage_employees',
    'mobile.api_presence_events_delete': 'can_manage_employees',
    'mobile.api_accounts_bulk': 'can_manage_employees',
    'mobile.api_employees_bulk_dept': 'can_manage_employees',
    'mobile.api_sites': 'can_edit_org_settings',
    'mobile.api_site_edit': 'can_edit_org_settings',
    'mobile.api_mobile_settings': 'can_edit_org_settings',
    'mobile.api_kiosks': 'can_edit_org_settings',
    'mobile.api_kiosks_bulk': 'can_edit_org_settings',
    'mobile.api_mobile_punches_delete': 'can_manage_employees',
}

# دور «اطّلاع فقط» (viewer): لا يعدّل شيئاً — مسموح له فقط بهذه الطلبات غير GET (حسابات وتقارير بلا حفظ)
VIEWER_ALLOWED_WRITES = {'api_overtime', 'api_overtime_export_csv', 'api_change_password', 'login', 'logout', 'api_my_favorites', 'admin_notes.api_notify_token'}

# مسارات admin فقط بغض النظر عن أي صلاحية دقيقة - إدارة المستخدمين حصراً
# (تبويب "المستخدمون" بالكامل مخفي عن غير admin بالواجهة أيضاً، مطابقةً
# للأصل المكتبي بالضبط)
ADMIN_ONLY_ENDPOINTS = {'api_users', 'api_user_edit', 'api_users_review', 'api_users_bulk', 'api_reset_requests', 'api_reset_request_action', 'api_maintenance_counts', 'api_maintenance_purge'}

# مسارات القراءة الخاضعة لتقييد "الأقسام المسموحة" - تُصفَّى بياناتها
# تلقائياً حسب user_departments لو المستخدم مقيَّد (راجع scoped_dept_filter)
DEPT_SCOPED_ENDPOINTS = {
    'api_meta', 'api_stats', 'api_reports', 'api_reports_export_csv', 'api_reports_export_pdf',
    'api_overtime', 'api_overtime_export_csv', 'api_compare', 'api_blueprint',
    'api_export_excel', 'api_export_send_email', 'api_employees',
}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            if request.path.startswith('/api/'):
                return jsonify({'ok': False, 'error': 'يرجى تسجيل الدخول أولاً'}), 401
            return redirect(url_for('login', next=request.path))
        return view(*args, **kwargs)
    return wrapped


def user_can(permission):
    """يطابق _user_can() بالنسخة المكتبية بالضبط: admin يقدر على كل شيء
    دائماً بغض النظر عن قيم الصلاحيات المخزَّنة له، وأي دور آخر يُفحَص
    حسب الصلاحية المحدَّدة الفعلية المخزَّنة بجلسته."""
    if session.get('role') == 'admin':
        return True
    return bool(session.get(permission))


def allowed_departments():
    """قائمة الأقسام المسموحة للمستخدم الحالي - فاضية تعني بدون أي قيد
    (يشوف كل الأقسام)، تماماً كنفس منطق النسخة المكتبية."""
    return session.get('allowed_depts') or []


def scoped_dept_filter(rows, dept_key='dept'):
    """يُطبَّق على أي قائمة قواميس فيها مفتاح قسم - يُصفّي حسب الأقسام
    المسموحة للمستخدم الحالي لو مقيَّداً، وإلا يُعيدها كما هي (بدون قيد)."""
    allowed = allowed_departments()
    if not allowed:
        return rows
    allowed_set = set(allowed)
    return [r for r in rows if (r.get(dept_key) or '') in allowed_set]


@app.before_request
def enforce_role_permissions():
    """يُطبَّق على كل الطلبات - يرفض فوراً (403 على مسارات API) أي طلب
    لمسار admin فقط من غير admin، أو لمسار يتطلب صلاحية دقيقة معيّنة
    والمستخدم الحالي لا يملكها. أي مسار آخر غير مذكور بالقائمتين مفتوح
    لأي مستخدم مسجَّل دخول - تماماً كسلوك النسخة المكتبية الأصلي."""
    endpoint = request.endpoint or ''
    # حماية من الطلبات المزوّرة من مواقع أخرى (CSRF): أي طلب تعديل يجب أن يأتي من نفس الموقع
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and endpoint != 'api_sync_receive':
        origin = request.headers.get('Origin') or request.headers.get('Referer') or ''
        if origin:
            from urllib.parse import urlparse
            if urlparse(origin).netloc.lower() != (request.host or '').lower():
                return jsonify({'ok': False, 'error': 'طلب مرفوض (مصدر غير موثوق)'}), 403
    if request.path in ('/me', '/kiosk') or request.path.startswith(('/me/', '/kiosk/')):
        return   # تطبيق الموظف على الهاتف — له جلسته وصلاحياته الخاصة (mobile.py)
    if not session.get('user_id'):
        return
    # الصلاحيات تُقرأ من قاعدة البيانات مع كل طلب: حذف مستخدم أو تغيير دوره يسري فوراً
    conn = db.get_db()
    try:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (session['user_id'],)).fetchone()
        depts = [r['dept'] for r in conn.execute(
            "SELECT dept FROM user_departments WHERE user_id = ?", (session['user_id'],)).fetchall()] if user else []
    finally:
        conn.close()
    if user is None:
        session.clear()
        if request.path.startswith('/api/'):
            return jsonify({'ok': False, 'error': 'يرجى تسجيل الدخول أولاً'}), 401
        return redirect(url_for('login'))
    session['role'] = user['role'] or 'viewer'
    for perm in _PERMISSION_KEYS:
        session[perm] = bool(user[perm])
    session['allowed_depts'] = depts
    if (session['role'] == 'viewer' and request.method not in ('GET', 'HEAD')
            and endpoint not in VIEWER_ALLOWED_WRITES):
        return jsonify({'ok': False, 'error': 'حسابك للاطّلاع فقط — لا يمكنه التعديل'}), 403
    if endpoint in ADMIN_ONLY_ENDPOINTS and session.get('role') != 'admin':
        return jsonify({'ok': False, 'error': 'هذا الإجراء مخصَّص لمدير النظام (admin) فقط'}), 403
    required_perm = PERMISSION_REQUIRED_ENDPOINTS.get(endpoint)
    # GET على مسارات القراءة (قائمة الأجهزة/الأقسام...) مسموح للجميع -
    # القيد على التعديل فقط (POST/PUT/DELETE)، تماماً كأزرار home.py
    # المعطَّلة بس (العرض نفسه ما كان مقيَّداً هناك)
    if required_perm and request.method != 'GET' and not user_can(required_perm):
        return jsonify({'ok': False, 'error': 'ليس لديك صلاحية لهذا الإجراء'}), 403




def L(v):
    """نص ثابت (عنوان عمود، حالة…) بلغة المستخدم في ملفات التصدير"""
    return _tr(v) if _ui_lang(request) == 'en' else v


def LL(values):
    return [L(v) if isinstance(v, str) else v for v in values]


@app.context_processor
def _inject_lang():
    lang = _ui_lang(request)
    try:
        st = db.get_all_settings()
    except Exception:
        st = {}
    org = (st.get('org_name_en') if lang == 'en' else '') or st.get('org_name') or ''
    logo, ver = _logo_file(st)
    return {'ui_lang': lang, 'ui_dir': 'ltr' if lang == 'en' else 'rtl', 'org_display': org,
            'logo_url': url_for('static', filename='uploads/' + logo, v=ver) if logo else '', 'icon_ver': ver}


def _logo_file(st=None):
    """(اسم ملف الشعار إن وُجد فعلاً، رقم إصدار لتجاوز ذاكرة المتصفح)"""
    st = st if st is not None else db.get_all_settings()
    name = st.get('org_logo_filename') or ''
    path = os.path.join(LOGO_UPLOAD_DIR, name) if name else ''
    if name and os.path.isfile(path):
        return name, int(os.path.getmtime(path))
    return '', 0




@app.url_defaults
def _static_version(endpoint, values):
    """رقم إصدار لكل ملف ثابت (?v=وقت التعديل) حتى لا يعرض المتصفح أو Cloudflare نسخة قديمة بعد التحديث"""
    if endpoint != 'static' or 'v' in values or not values.get('filename'):
        return
    fn = values['filename']
    try:
        path = os.path.join(app.static_folder, fn)
        values['v'] = int(os.path.getmtime(path))
    except OSError:
        pass


_ICON_SIZES = {16, 32, 180, 192, 512}


@app.route('/app-icon/<int:size>.png')
@app.route('/app-icon/<int:size>-<kind>.png')
def app_icon(size, kind='any'):
    """أيقونة التطبيق عند التثبيت (الكمبيوتر والهاتف): تُولَّد من شعار المؤسسة، وإلا الأيقونة الافتراضية"""
    if size not in _ICON_SIZES:
        size = 192
    maskable = kind == 'maskable'
    logo, ver = _logo_file()
    if not logo or logo.rsplit('.', 1)[-1].lower() == 'svg':
        name = {16: 'favicon-16.png', 32: 'favicon-32.png', 180: 'apple-touch-icon.png'}.get(size) or \
            (f'icon-{size}-maskable.png' if maskable else f'icon-{size}.png')
        return send_file(os.path.join(app.static_folder, 'icons', name), mimetype='image/png', max_age=3600)
    cache_dir = os.path.join(os.path.dirname(db.DB_PATH) or '.', 'icon-cache')
    os.makedirs(cache_dir, exist_ok=True)
    out = os.path.join(cache_dir, f'{size}-{kind}-{ver}.png')
    if not os.path.isfile(out):
        from PIL import Image
        src = Image.open(os.path.join(LOGO_UPLOAD_DIR, logo)).convert('RGBA')
        canvas = Image.new('RGBA', (size, size), (255, 255, 255, 255))
        # هامش أكبر للأيقونات «maskable» (أندرويد يقصّ الأطراف بشكل دائري)
        pad = int(size * (0.2 if maskable else 0.08)) if size >= 64 else 1
        box = size - 2 * pad
        src.thumbnail((box, box), Image.LANCZOS)
        canvas.alpha_composite(src, ((size - src.width) // 2, (size - src.height) // 2))
        canvas.convert('RGB').save(out, 'PNG', optimize=True)
        for old in os.listdir(cache_dir):          # نحذف أيقونات شعار قديم
            if not old.endswith(f'-{ver}.png'):
                try:
                    os.remove(os.path.join(cache_dir, old))
                except OSError:
                    pass
    return send_file(out, mimetype='image/png', max_age=3600)


@app.route('/manifest.json')
@app.route('/manifest-me.json')
def dynamic_manifest():
    """ملف التثبيت (PWA) بأيقونات مولَّدة من شعار المؤسسة واسمها"""
    me = request.path.endswith('-me.json')
    with open(os.path.join(app.static_folder, 'manifest-me.json' if me else 'manifest.json'), encoding='utf-8') as fh:
        m = json.load(fh)
    _logo, ver = _logo_file()
    m['icons'] = [{'src': f'/app-icon/{sz}{"-maskable" if purpose == "maskable" else ""}.png?v={ver}', 'sizes': f'{sz}x{sz}',
                   'type': 'image/png', 'purpose': purpose} for purpose in ('any', 'maskable') for sz in (192, 512)]
    resp = jsonify(m)
    resp.headers['Content-Type'] = 'application/manifest+json'
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


@app.after_request
def _translate_messages(resp):
    """رسائل الخادم (الأخطاء والتأكيدات) بالإنجليزية لمن اختارها"""
    if _ui_lang(request) == 'en' and resp.mimetype == 'application/json' and not resp.direct_passthrough:
        try:
            data = json.loads(resp.get_data(as_text=True))
            if isinstance(data, dict):
                resp.set_data(json.dumps(_translate_json(data), ensure_ascii=False))
        except (ValueError, TypeError):
            pass
    return resp


@app.after_request
def _no_cache_login(resp):
    """يمنع متصفحات الموبايل من تخزين صفحة تسجيل الدخول بذاكرة bfcache -
    بدونه، زر "رجوع" بالتلفون بعد الدخول للنظام قد يُرجع نسخة قديمة من
    شاشة الدخول مباشرة من ذاكرة المتصفح (بدون أي طلب فعلي للسيرفر)
    فتظهر وكأن المستخدم سُجِّل خروجه رغم أن جلسته ما زالت صالحة فعلياً."""
    if request.path in ('/login', '/'):
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        resp.headers['Pragma'] = 'no-cache'
    return resp


_LOGIN_FAILS = {}   # {ip|user: [أوقات المحاولات الخاطئة]}


def _login_blocked(key, limit=5, window=900):
    import time
    now = time.time()
    tries = [t for t in _LOGIN_FAILS.get(key, []) if now - t < window]
    _LOGIN_FAILS[key] = tries
    return len(tries) >= limit


def _login_failed(key):
    import time
    _LOGIN_FAILS.setdefault(key, []).append(time.time())


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        if session.get('user_id'):
            return redirect(url_for('dashboard'))
        return render_template('login.html', error=None, settings=db.get_all_settings())

    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    key = f"{request.remote_addr}|{username.lower()}"
    if _login_blocked(key):
        return render_template('login.html', error='محاولات كثيرة خاطئة — انتظر 15 دقيقة ثم حاول مجدداً',
                                settings=db.get_all_settings()), 429
    conn = db.get_db()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if user is None or not check_password_hash(user['password_hash'], password):
        _login_failed(key)
        session['username'] = ''
        log_audit(conn, 'login_failed', 'user', new_value=f"{username[:60]} — {(request.headers.get('CF-Connecting-IP') or request.remote_addr or '')[:45]}")
        conn.commit()
        conn.close()
        return render_template('login.html', error='اسم المستخدم أو كلمة المرور غير صحيحة',
                                settings=db.get_all_settings())
    _LOGIN_FAILS.pop(key, None)

    dept_rows = conn.execute("SELECT dept FROM user_departments WHERE user_id = ?", (user['id'],)).fetchall()
    ip = (request.headers.get('CF-Connecting-IP') or request.remote_addr or '')[:45]
    conn.execute("UPDATE users SET last_login_at = ?, last_login_ip = ? WHERE id = ?",
                 (datetime.now().strftime('%Y-%m-%d %H:%M'), ip, user['id']))
    session['username'] = user['username']
    log_audit(conn, 'login', 'user', new_value=f"{user['username']} — {ip}")
    conn.commit()
    conn.close()

    session.clear()
    session.permanent = True
    session['user_id'] = user['id']
    session['username'] = user['username']
    session['full_name'] = user['full_name'] or user['username']
    session['role'] = user['role'] or 'viewer'
    for perm in _PERMISSION_KEYS:
        session[perm] = bool(user[perm])
    session['allowed_depts'] = [r['dept'] for r in dept_rows]
    return redirect(url_for('dashboard'))


# ============================================================
# ===== نسيان كلمة المرور (مستخدمو النظام والموظفون) =====
# ============================================================
_FORGOT_HITS = {}


def forgot_blocked():
    import time as _t
    key = request.remote_addr or ''
    now = _t.time()
    hits = [t for t in _FORGOT_HITS.get(key, []) if now - t < 900]
    hits.append(now)
    _FORGOT_HITS[key] = hits
    return len(hits) > 6


def reset_token_create(conn, kind, subject_id, minutes=30):
    import secrets as _s
    from datetime import timedelta as _td
    token = _s.token_urlsafe(32)
    exp = (datetime.now() + _td(minutes=minutes)).strftime('%Y-%m-%d %H:%M:%S')
    conn.execute("INSERT INTO password_reset_tokens (kind, subject_id, token_hash, expires_at) VALUES (?, ?, ?, ?)",
                 (kind, subject_id, hashlib.sha256(token.encode()).hexdigest(), exp))
    return token


def reset_token_get(conn, kind, token):
    row = conn.execute("SELECT * FROM password_reset_tokens WHERE token_hash = ? AND kind = ?",
                       (hashlib.sha256((token or '').encode()).hexdigest(), kind)).fetchone()
    if not row or row['used_at'] or row['expires_at'] < datetime.now().strftime('%Y-%m-%d %H:%M:%S'):
        return None
    return row


def reset_mail(to_email, name, link):
    """يرسل رابط إعادة التعيين — يرجع True عند النجاح، False إن لم يُضبط البريد أو فشل الإرسال"""
    settings = db.get_all_settings()
    if not to_email or not (settings.get('smtp_sender_email') or settings.get('graph_sender_upn')):
        return False
    org = settings.get('org_name') or 'نظام الحضور والانصراف'
    try:
        email_sender.send_email_auto(
            settings, [to_email], f'{org} — إعادة تعيين كلمة المرور',
            f'مرحباً {name}،\n\nلإعادة تعيين كلمة المرور افتح الرابط التالي (صالح لمدة 30 دقيقة ولمرة واحدة):\n{link}\n\n'
            f'إن لم تطلب ذلك فتجاهل هذه الرسالة؛ كلمة مرورك الحالية لم تتغيّر.')
        return True
    except Exception:
        return False


def reset_request_add(conn, kind, subject_id, label):
    if conn.execute("SELECT 1 FROM password_reset_requests WHERE kind = ? AND subject_id = ? AND status = 'pending'",
                    (kind, subject_id)).fetchone():
        return
    conn.execute("INSERT INTO password_reset_requests (kind, subject_id, label, ip, created_at) VALUES (?, ?, ?, ?, ?)",
                 (kind, subject_id, label, (request.headers.get('CF-Connecting-IP') or request.remote_addr or '')[:45], _audit_now()))


@app.route('/forgot', methods=['GET', 'POST'])
def forgot_password():
    settings = db.get_all_settings()
    if request.method == 'GET':
        return render_template('forgot.html', settings=settings, done=False, error=None)
    if forgot_blocked():
        return render_template('forgot.html', settings=settings, done=False, error='طلبات كثيرة — حاول بعد 15 دقيقة'), 429
    q = (request.form.get('username') or '').strip()
    conn = db.get_db()
    try:
        user = conn.execute("SELECT * FROM users WHERE lower(username) = lower(?) OR (email != '' AND lower(email) = lower(?))", (q, q)).fetchone()
        if user:
            sent = False
            if user['email']:
                token = reset_token_create(conn, 'user', user['id'])
                conn.commit()
                sent = reset_mail(user['email'], user['full_name'] or user['username'], url_for('reset_password', token=token, _external=True))
            if not sent:
                reset_request_add(conn, 'user', user['id'], user['username'])
            session['username'] = ''
            log_audit(conn, 'password_forgot', 'user', new_value=f"{user['username']} — {'رابط بالبريد' if sent else 'طلب للإدارة'}")
            conn.commit()
    finally:
        conn.close()
    # الرد نفسه دائماً حتى لا يُعرف هل الحساب موجود
    return render_template('forgot.html', settings=settings, done=True, error=None)


@app.route('/reset/<token>', methods=['GET', 'POST'])
def reset_password(token):
    settings = db.get_all_settings()
    conn = db.get_db()
    try:
        row = reset_token_get(conn, 'user', token)
        if not row:
            return render_template('reset.html', settings=settings, error='الرابط غير صالح أو انتهت صلاحيته — اطلب رابطاً جديداً', ok=False, invalid=True)
        if request.method == 'GET':
            return render_template('reset.html', settings=settings, error=None, ok=False, invalid=False)
        pw, pw2 = request.form.get('password') or '', request.form.get('password2') or ''
        if len(pw) < 8 or pw != pw2:
            return render_template('reset.html', settings=settings, error='كلمة المرور 8 أحرف على الأقل، ويجب أن تتطابق الخانتان', ok=False, invalid=False)
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(pw), row['subject_id']))
        conn.execute("UPDATE password_reset_tokens SET used_at = ? WHERE id = ?", (_audit_now(), row['id']))
        conn.execute("UPDATE password_reset_requests SET status = 'done', handled_by = '(رابط البريد)', handled_at = ? "
                     "WHERE kind = 'user' AND subject_id = ? AND status = 'pending'", (_audit_now(), row['subject_id']))
        u = conn.execute("SELECT username FROM users WHERE id = ?", (row['subject_id'],)).fetchone()
        session['username'] = ''
        log_audit(conn, 'password_reset', 'user', new_value=(u['username'] if u else '') + ' — عبر رابط البريد')
        conn.commit()
        return render_template('reset.html', settings=settings, error=None, ok=True, invalid=False)
    finally:
        conn.close()


@app.route('/api/reset-requests')
@login_required
def api_reset_requests():
    conn = db.get_db()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM password_reset_requests WHERE status = 'pending' ORDER BY id DESC").fetchall()]
        for r in rows:
            if r['kind'] == 'emp':
                e = conn.execute("SELECT e.name, e.dept FROM employees e WHERE e.id = ?", (r['subject_id'],)).fetchone()
                r['name'], r['dept'] = (e['name'], e['dept']) if e else (r['label'], '')
            else:
                u = conn.execute("SELECT username, full_name FROM users WHERE id = ?", (r['subject_id'],)).fetchone()
                r['name'], r['dept'] = ((u['full_name'] or u['username']), 'مستخدم النظام') if u else (r['label'], '')
        return jsonify({'ok': True, 'rows': rows})
    finally:
        conn.close()


@app.route('/api/reset-requests/<int:req_id>', methods=['POST'])
@login_required
def api_reset_request_action(req_id):
    import secrets as _s
    action = (request.get_json(silent=True) or {}).get('action')
    conn = db.get_db()
    try:
        r = conn.execute("SELECT * FROM password_reset_requests WHERE id = ? AND status = 'pending'", (req_id,)).fetchone()
        if not r:
            return jsonify({'ok': False, 'error': 'الطلب غير موجود أو عولج مسبقاً'}), 404
        cred = None
        if action == 'reset':
            if r['kind'] == 'emp':
                pw = ''.join(_s.choice('23456789') for _ in range(4)) + ''.join(_s.choice('abcdefghjkmnpqrstuvwxyz') for _ in range(4))
                acc = conn.execute("SELECT a.id, a.username, e.name, e.dept FROM employee_accounts a JOIN employees e ON e.id = a.employee_id "
                                   "WHERE a.employee_id = ?", (r['subject_id'],)).fetchone()
                if not acc:
                    return jsonify({'ok': False, 'error': 'لا يوجد حساب تطبيق لهذا الموظف'}), 404
                conn.execute("UPDATE employee_accounts SET password_hash = ? WHERE id = ?", (generate_password_hash(pw), acc['id']))
                cred = {'name': acc['name'], 'dept': acc['dept'] or '', 'username': acc['username'], 'password': pw}
            else:
                pw = _s.token_urlsafe(9)
                u = conn.execute("SELECT username, full_name FROM users WHERE id = ?", (r['subject_id'],)).fetchone()
                if not u:
                    return jsonify({'ok': False, 'error': 'المستخدم غير موجود'}), 404
                conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(pw), r['subject_id']))
                cred = {'name': u['full_name'] or u['username'], 'dept': 'مستخدم النظام', 'username': u['username'], 'password': pw}
            status = 'done'
        elif action == 'dismiss':
            status = 'dismissed'
        else:
            return jsonify({'ok': False, 'error': 'إجراء غير معروف'}), 400
        conn.execute("UPDATE password_reset_requests SET status = ?, handled_by = ?, handled_at = ? WHERE id = ?",
                     (status, session.get('username', ''), _audit_now(), req_id))
        log_audit(conn, 'password_reset' if cred else 'password_request_dismiss', 'user' if r['kind'] == 'user' else 'employee_accounts',
                  employee_name=cred['name'] if cred and r['kind'] == 'emp' else None, new_value=r['label'])
        conn.commit()
        return jsonify({'ok': True, 'credentials': [cred] if cred else []})
    finally:
        conn.close()


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
def index():
    return redirect(url_for('dashboard') if session.get('user_id') else url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    settings = db.get_all_settings()
    perms = {k: user_can(k) for k in _PERMISSION_KEYS}
    conn = db.get_db()
    row = conn.execute("SELECT fav_tabs FROM users WHERE id = ?", (session.get('user_id'),)).fetchone()
    conn.close()
    fav = (row['fav_tabs'] if row and row['fav_tabs'] is not None else None)
    return render_template('dashboard.html', settings=settings, full_name=session.get('full_name', ''),
                            role=session.get('role', 'viewer'), perms=perms, fav_tabs=fav)


_FAV_DEFAULT = ['dashboard', 'mobile-moves', 'reports', 'employees']


@app.route('/api/my/favorites', methods=['GET', 'POST'])
@login_required
def api_my_favorites():
    """أزرار المفضلة في الشريط السفلي — لكل مستخدم، وتتبعه على كل أجهزته"""
    conn = db.get_db()
    try:
        if request.method == 'POST':
            tabs = (request.get_json(force=True) or {}).get('tabs') or []
            tabs = [t for t in tabs if isinstance(t, str) and re.fullmatch(r'[a-z0-9-]{1,40}', t)]
            tabs = list(dict.fromkeys(tabs))[:5]
            conn.execute("UPDATE users SET fav_tabs = ? WHERE id = ?", (json.dumps(tabs), session.get('user_id')))
            conn.commit()
            return jsonify({'ok': True, 'tabs': tabs})
        row = conn.execute("SELECT fav_tabs FROM users WHERE id = ?", (session.get('user_id'),)).fetchone()
        try:
            tabs = json.loads(row['fav_tabs']) if row and row['fav_tabs'] else _FAV_DEFAULT
        except ValueError:
            tabs = _FAV_DEFAULT
        return jsonify({'ok': True, 'tabs': tabs})
    finally:
        conn.close()


# ============================================================
# ===== لوحة التحكم: الإحصاءات =====
# ============================================================
def _apply_common_filters(rows, args):
    dept = args.get('dept', '').strip()
    employee = args.get('employee', '').strip()
    # ===== employees: قائمة أكثر من موظف مفصولة بفاصلة (بديل employee
    # المفرد) - تدعم اختيار عدة أشخاص معاً بتحليل/تصفية التقرير (مثلاً
    # شخصين أو أكثر من نفس القسم) بدل الاقتصار على موظف واحد أو الكل =====
    employees_multi = [e.strip() for e in args.get('employees', '').split(',') if e.strip()]
    date_from = args.get('date_from', '').strip()
    date_to = args.get('date_to', '').strip()
    rt = args.get('report_type', 'all').strip()
    q = args.get('q', '').strip().lower()

    # ===== قيد الأقسام المسموحة يُطبَّق دائماً أولاً وبغض النظر عن فلتر
    # القسم المختار بالواجهة (حتى "الكل") - تماماً كتعليق النسخة المكتبية:
    # "هذا يطبَّق دايماً بغض النظر عن اختيار الكل بالفلتر" =====
    rows = scoped_dept_filter(rows)

    out = []
    for r in rows:
        if dept and dept != 'الكل' and (r['dept'] or '') != dept:
            continue
        if employee and employee != 'الكل' and r['name'] != employee:
            continue
        if employees_multi and r['name'] not in employees_multi:
            continue
        if date_from and r['date'] < date_from:
            continue
        if date_to and r['date'] > date_to:
            continue
        if q and q not in (r['name'] or '').lower() and q not in (r['dept'] or '').lower():
            continue
        if rt == 'late' and r['status'] not in ('متأخر', 'تأخير بسيط'):
            continue
        elif rt == 'absent' and r['status'] != 'غائب':
            continue
        elif rt == 'ontime' and r['status'] != 'في الوقت':
            continue
        elif rt == 'holiday' and r['status'] != 'عطلة أسبوعية':
            continue
        elif rt == 'sat_present' and not (r['weekday'] == 5 and r['status'] not in ('غائب', 'عطلة أسبوعية', 'عطلة رسمية', 'استثناء')):
            continue
        out.append(r)
    return out


@app.route('/api/stats')
@login_required
def api_stats():
    conn = db.get_db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM report_cache").fetchall()]
    conn.close()
    filtered = _apply_common_filters(rows, request.args)

    total = len(filtered)
    ontime = sum(1 for r in filtered if r['status'] == 'في الوقت')
    late = sum(1 for r in filtered if r['status'] in ('متأخر', 'تأخير بسيط'))
    absent = sum(1 for r in filtered if r['status'] == 'غائب')
    holiday = sum(1 for r in filtered if r['status'] == 'عطلة أسبوعية')
    sat_present = sum(1 for r in filtered if r['weekday'] == 5 and r['status'] not in ('غائب', 'عطلة أسبوعية', 'عطلة رسمية', 'استثناء'))
    hours = [r['working_hours'] for r in filtered if r['working_hours']]
    avg_hours = round(sum(hours) / len(hours), 1) if hours else 0
    lates = [r['late_minutes'] for r in filtered if r['late_minutes']]
    avg_late = round(sum(lates) / len(lates), 1) if lates else 0

    return jsonify({
        'ok': True,
        'total': total, 'ontime': ontime, 'late': late, 'absent': absent,
        'holiday': holiday, 'sat_present': sat_present,
        'avg_hours': avg_hours, 'avg_late': avg_late,
    })


@app.route('/api/reports')
@login_required
def api_reports():
    conn = db.get_db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM report_cache ORDER BY date DESC, time_in ASC").fetchall()]
    conn.close()
    filtered = _apply_common_filters(rows, request.args)

    sort_col = request.args.get('sort', '')
    sort_dir = request.args.get('dir', 'asc')
    if sort_col and filtered and sort_col in filtered[0]:
        filtered.sort(key=lambda r: (r[sort_col] is None, r[sort_col]), reverse=(sort_dir == 'desc'))

    page = int(request.args.get('page', 1) or 1)
    page_size = int(request.args.get('page_size', 50) or 50)
    total = len(filtered)
    start = (page - 1) * page_size
    page_rows = filtered[start:start + page_size]

    return jsonify({'ok': True, 'rows': page_rows, 'total': total, 'page': page, 'page_size': page_size})


@app.route('/api/reports/export.csv')
@login_required
def api_reports_export_csv():
    conn = db.get_db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM report_cache ORDER BY date DESC, time_in ASC").fetchall()]
    conn.close()
    filtered = _apply_common_filters(rows, request.args)

    buf = io.StringIO()
    buf.write('﻿')  # BOM حتى يفتح إكسل الملف بترميز عربي صحيح
    writer = csv.writer(buf)
    writer.writerow(LL(['الاسم', 'القسم', 'التاريخ', 'وقت الحضور', 'وقت الانصراف', 'الحالة', 'دقائق التأخير', 'ساعات العمل', 'المناوبة']))
    for r in filtered:
        writer.writerow([r['name'], r['dept'] or '', r['date'], r['time_in'] or '', r['time_out'] or '',
                          L(r['status'] or ''), r['late_minutes'], r['working_hours'], r['shift'] or ''])
    mem = io.BytesIO(buf.getvalue().encode('utf-8'))
    return send_file(mem, mimetype='text/csv', as_attachment=True,
                      download_name=f"attendance_report_{datetime.now().strftime('%Y%m%d_%H%M')}.csv")


@app.route('/api/overtime', methods=['POST'])
@login_required
def api_overtime():
    """
    يحسب العمل الإضافي من بيانات report_cache المخزّنة (نفس نتائج آخر
    تحليل) - بدون الحاجة لإعادة تحليل البصمات. يقارن وقت الانصراف
    الفعلي بوقت الانصراف المقرر لكل موظف (وقت القسم/المناوبة أو ساعات
    مخصّصة)، ويطبّق فترة سماح اختيارية قبل احتساب أي دقيقة كعمل إضافي.
    """
    data = request.get_json(force=True) or {}
    names = [n.strip() for n in (data.get('names') or []) if n.strip()]
    date_from = (data.get('date_from') or '').strip()
    date_to = (data.get('date_to') or '').strip()
    try:
        grace_minutes = int(data.get('grace_minutes') or 0)
    except (TypeError, ValueError):
        grace_minutes = 0
    use_custom_hours = bool(data.get('use_custom_hours'))
    custom_end = (data.get('custom_end') or '').strip() or None

    if not names:
        return jsonify({'ok': False, 'error': 'اختر موظفاً واحداً على الأقل'}), 400
    if use_custom_hours and not custom_end:
        return jsonify({'ok': False, 'error': 'حدّد وقت الانصراف المخصّص للحساب'}), 400

    conn = db.get_db()
    placeholders = ','.join('?' * len(names))
    q = f"SELECT name, dept, date, time_out FROM report_cache WHERE name IN ({placeholders})"
    params = list(names)
    if date_from:
        q += " AND date >= ?"
        params.append(date_from)
    if date_to:
        q += " AND date <= ?"
        params.append(date_to)
    rows = scoped_dept_filter([dict(r) for r in conn.execute(q, params).fetchall()])

    settings = db.get_all_settings()
    dept_rows = conn.execute("SELECT dept, attendance_time, departure_time FROM dept_attendance_settings").fetchall()
    dept_times = {r['dept']: (
        parse_time_str(r['attendance_time']) if r['attendance_time'] else None,
        parse_time_str(r['departure_time']) if r['departure_time'] else None
    ) for r in dept_rows}
    shift1_names = json.loads(db.get_setting('shift1_names_json', '[]'))
    shift2_names = json.loads(db.get_setting('shift2_names_json', '[]'))
    conn.close()

    records = overtime_engine.calculate(rows, settings, dept_times, shift1_names, shift2_names,
                                         grace_minutes, use_custom_hours, custom_end)
    records.sort(key=lambda r: (r['date'], -r['ot_minutes']))

    total_minutes = sum(r['ot_minutes'] for r in records)
    summary = {
        'instances': len(records),
        'total_minutes': total_minutes,
        'total_duration': overtime_engine.format_duration(total_minutes),
        'top_employee': None,
        'top_employee_duration': None,
    }
    if records:
        by_emp = {}
        for r in records:
            by_emp[r['name']] = by_emp.get(r['name'], 0) + r['ot_minutes']
        top_name = max(by_emp, key=by_emp.get)
        summary['top_employee'] = top_name
        summary['top_employee_duration'] = overtime_engine.format_duration(by_emp[top_name])

    for r in records:
        r['ot_duration'] = overtime_engine.format_duration(r['ot_minutes'])

    return jsonify({'ok': True, 'rows': records, 'summary': summary})


@app.route('/api/overtime/export.csv', methods=['POST'])
@login_required
def api_overtime_export_csv():
    data = request.get_json(force=True) or {}
    names = [n.strip() for n in (data.get('names') or []) if n.strip()]
    date_from = (data.get('date_from') or '').strip()
    date_to = (data.get('date_to') or '').strip()
    try:
        grace_minutes = int(data.get('grace_minutes') or 0)
    except (TypeError, ValueError):
        grace_minutes = 0
    use_custom_hours = bool(data.get('use_custom_hours'))
    custom_end = (data.get('custom_end') or '').strip() or None

    conn = db.get_db()
    if names:
        placeholders = ','.join('?' * len(names))
        q = f"SELECT name, dept, date, time_out FROM report_cache WHERE name IN ({placeholders})"
        params = list(names)
    else:
        q = "SELECT name, dept, date, time_out FROM report_cache WHERE 1=1"
        params = []
    if date_from:
        q += " AND date >= ?"
        params.append(date_from)
    if date_to:
        q += " AND date <= ?"
        params.append(date_to)
    rows = scoped_dept_filter([dict(r) for r in conn.execute(q, params).fetchall()])

    settings = db.get_all_settings()
    dept_rows = conn.execute("SELECT dept, attendance_time, departure_time FROM dept_attendance_settings").fetchall()
    dept_times = {r['dept']: (
        parse_time_str(r['attendance_time']) if r['attendance_time'] else None,
        parse_time_str(r['departure_time']) if r['departure_time'] else None
    ) for r in dept_rows}
    shift1_names = json.loads(db.get_setting('shift1_names_json', '[]'))
    shift2_names = json.loads(db.get_setting('shift2_names_json', '[]'))
    conn.close()

    records = overtime_engine.calculate(rows, settings, dept_times, shift1_names, shift2_names,
                                         grace_minutes, use_custom_hours, custom_end)
    records.sort(key=lambda r: (r['date'], r['name']))

    buf = io.StringIO()
    buf.write('﻿')
    writer = csv.writer(buf)
    writer.writerow(LL(['الاسم', 'القسم', 'التاريخ', 'وقت الانصراف الفعلي', 'وقت الانصراف المقرر', 'دقائق العمل الإضافي', 'مدة العمل الإضافي', 'عطلة أسبوعية']))
    for r in records:
        writer.writerow([r['name'], r['dept'], r['date'], r['time_out'], r['scheduled_end'],
                          r['ot_minutes'], overtime_engine.format_duration(r['ot_minutes']),
                          'نعم' if r['is_weekend'] else ''])
    mem = io.BytesIO(buf.getvalue().encode('utf-8'))
    return send_file(mem, mimetype='text/csv', as_attachment=True,
                      download_name=f"overtime_report_{datetime.now().strftime('%Y%m%d_%H%M')}.csv")


# ============================================================
# ===== الجدولة التلقائية (سحب + تحليل + إرسال بريد) =====
# ============================================================
_SCHEDULE_KEYS = [
    'email_method',
    'smtp_host', 'smtp_port', 'smtp_sender_email', 'smtp_sender_password', 'smtp_recipients',
    'smtp_provider', 'smtp_security', 'smtp_username', 'smtp_sender_name',
    'graph_tenant_id', 'graph_client_id', 'graph_client_secret', 'graph_sender_upn',
    'schedule_enabled', 'schedule_time', 'schedule_days_json', 'schedule_status_filter', 'schedule_pull_before',
]

_ONEDRIVE_BACKUP_KEYS = ['onedrive_backup_upn', 'onedrive_backup_folder']
_GDRIVE_BACKUP_KEYS = ['gdrive_service_account_json_path', 'gdrive_backup_folder_id']


@app.route('/api/schedule', methods=['GET', 'POST'])
@login_required
def api_schedule():
    if request.method == 'POST':
        data = request.get_json(force=True) or {}
        if 'schedule_days' in data:
            data['schedule_days_json'] = json.dumps(data.get('schedule_days') or [])
        for key in _SCHEDULE_KEYS:
            if key in data:
                value = data[key]
                if key in SECRET_SETTINGS and value == SECRET_MASK:
                    continue   # لم يُغيَّر
                if key in ('schedule_enabled', 'schedule_pull_before'):
                    value = '1' if value else '0'
                db.set_setting(key, str(value if value is not None else ''))
        return jsonify({'ok': True})

    settings = db.get_all_settings()
    result = mask_secrets({k: settings.get(k, '') for k in _SCHEDULE_KEYS})
    result['schedule_days'] = json.loads(result.get('schedule_days_json') or '[]')
    result['schedule_last_run_at'] = settings.get('schedule_last_run_at', '')
    result['schedule_last_run_status'] = settings.get('schedule_last_run_status', '')
    result['schedule_last_run_message'] = settings.get('schedule_last_run_message', '')
    result['status_filters'] = STATUS_FILTERS
    return jsonify({'ok': True, 'settings': result})


@app.route('/api/schedule/test-email', methods=['POST'])
@login_required
def api_schedule_test_email():
    settings = db.get_all_settings()
    recipients = [r.strip() for r in (settings.get('smtp_recipients') or '').replace(';', ',').split(',') if r.strip()]
    if not recipients:
        return jsonify({'ok': False, 'error': 'أدخل مستلماً واحداً على الأقل بإعدادات البريد أولاً'}), 400
    org = settings.get('org_name')
    method_label = 'Microsoft Graph API' if settings.get('email_method') == 'graph' else 'SMTP'
    try:
        email_sender.send_email_auto(
            settings, recipients,
            f"{org} - رسالة اختبار الجدولة التلقائية",
            f"هذه رسالة اختبار من نظام {org} للتأكد من صحة إعدادات البريد ({method_label}).\n\n"
            f"This is a test message from the {org} system to verify the email settings ({method_label}).",
        )
    except Exception as e:
        return jsonify({'ok': False, 'error': f'فشل الإرسال عبر {method_label}: {e}'}), 400
    return jsonify({'ok': True, 'message': f"تم إرسال رسالة اختبار بنجاح عبر {method_label} إلى: {', '.join(recipients)}"})


@app.route('/api/backup/onedrive', methods=['GET', 'POST'])
@login_required
def api_backup_onedrive():
    """يحفظ إعدادات النسخ الاحتياطي على OneDrive (GET/POST) بدون Client
    Secret (يُعاد نفس Tenant/Client/Secret المستخدَم أصلاً بإعدادات
    البريد عبر Graph - راجع onedrive_backup.py)."""
    if request.method == 'POST':
        data = request.get_json(force=True) or {}
        for key in _ONEDRIVE_BACKUP_KEYS:
            if key in data:
                db.set_setting(key, str(data[key] or ''))
        return jsonify({'ok': True})

    settings = db.get_all_settings()
    result = {k: settings.get(k, '') for k in _ONEDRIVE_BACKUP_KEYS}
    result['onedrive_last_backup_at'] = settings.get('onedrive_last_backup_at', '')
    result['onedrive_last_backup_status'] = settings.get('onedrive_last_backup_status', '')
    return jsonify({'ok': True, 'settings': result})


@app.route('/api/backup/onedrive/run', methods=['POST'])
@login_required
def api_backup_onedrive_run():
    settings = db.get_all_settings()
    upn = settings.get('onedrive_backup_upn') or ''
    folder = settings.get('onedrive_backup_folder') or 'AttendanceBackups'
    if not upn:
        return jsonify({'ok': False, 'error': 'يرجى تعبئة بريد صاحب OneDrive المستهدَف وحفظه أولاً'}), 400

    backup_name = f"attendance_web_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    result = onedrive_backup.upload_file(
        settings.get('graph_tenant_id'), settings.get('graph_client_id'), settings.get('graph_client_secret'),
        upn, folder, db.DB_PATH, remote_filename=backup_name,
    )
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    if result.get('ok'):
        db.set_setting('onedrive_last_backup_at', now_str)
        db.set_setting('onedrive_last_backup_status', 'نجح')
        conn = db.get_db()
        log_audit(conn, 'backup', 'onedrive', new_value=f"نسخة احتياطية بنجاح ({backup_name}) لمجلد {folder}")
        conn.commit()
        conn.close()
        return jsonify({'ok': True, 'webUrl': result.get('webUrl', ''), 'filename': backup_name})

    db.set_setting('onedrive_last_backup_at', now_str)
    db.set_setting('onedrive_last_backup_status', f"فشل: {result.get('error', '')}")
    return jsonify(result), 400


@app.route('/api/backup/gdrive', methods=['GET', 'POST'])
@login_required
def api_backup_gdrive():
    """يحفظ إعدادات النسخ الاحتياطي على Google Drive (بديل OneDrive) -
    مسار ملف JSON على جهاز الخادم (لا يُرفَع عبر المتصفح إطلاقاً، تماماً
    كفكرة local_path المستخدَمة بميزات الاستيراد الأخرى) بدل نسخ محتواه."""
    if request.method == 'POST':
        data = request.get_json(force=True) or {}
        for key in _GDRIVE_BACKUP_KEYS:
            if key in data:
                db.set_setting(key, str(data[key] or ''))
        return jsonify({'ok': True})

    settings = db.get_all_settings()
    result = {k: settings.get(k, '') for k in _GDRIVE_BACKUP_KEYS}
    result['gdrive_last_backup_at'] = settings.get('gdrive_last_backup_at', '')
    result['gdrive_last_backup_status'] = settings.get('gdrive_last_backup_status', '')
    return jsonify({'ok': True, 'settings': result})


@app.route('/api/backup/gdrive/run', methods=['POST'])
@login_required
def api_backup_gdrive_run():
    settings = db.get_all_settings()
    json_path = settings.get('gdrive_service_account_json_path') or ''
    folder_id = settings.get('gdrive_backup_folder_id') or ''
    if not json_path or not folder_id:
        return jsonify({'ok': False, 'error': 'يرجى تعبئة مسار ملف JSON ومعرّف المجلد (Folder ID) وحفظهما أولاً'}), 400

    backup_name = f"attendance_web_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    result = gdrive_backup.upload_file(json_path, folder_id, db.DB_PATH, remote_filename=backup_name)
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    if result.get('ok'):
        db.set_setting('gdrive_last_backup_at', now_str)
        db.set_setting('gdrive_last_backup_status', 'نجح')
        conn = db.get_db()
        log_audit(conn, 'backup', 'gdrive', new_value=f"نسخة احتياطية بنجاح ({backup_name})")
        conn.commit()
        conn.close()
        return jsonify({'ok': True, 'webViewLink': result.get('webViewLink', ''), 'filename': backup_name})

    db.set_setting('gdrive_last_backup_at', now_str)
    db.set_setting('gdrive_last_backup_status', f"فشل: {result.get('error', '')}")
    return jsonify(result), 400


@app.route('/api/schedule/run-now', methods=['POST'])
@login_required
def api_schedule_run_now():
    import scheduler
    result = scheduler.run_scheduled_report(manual_trigger=True)
    status = 200 if result.get('ok') else 400
    return jsonify({'ok': result.get('ok'), 'message': result.get('message')}), status


_IMPORT_AUDIT_TARGETS = ('device_sqlite', 'device_mdb', 'device', 'employees_from_sqlite', 'employees')
_IMPORT_ACTION_LABELS = {
    ('pull', 'device'): 'سحب مباشر من الأجهزة (عبر الشبكة)',
    ('import', 'device_sqlite'): 'استيراد من ملف SQLite',
    ('import', 'device_mdb'): 'استيراد من ملف att.mdb',
    ('import', 'employees_from_sqlite'): 'استيراد موظفين من ملف SQLite',
    ('import', 'employees'): 'استيراد قائمة موظفين',
}


@app.route('/api/last-import-notice')
@login_required
def api_last_import_notice():
    """يُرجع تفاصيل آخر عملية سحب/استيراد بصمات أو موظفين مسجَّلة بسجل
    التدقيق - تُعرَض كإشعار عند فتح التطبيق (راجع showLastImportNotice
    بـapp.js) لتفادي تكرار نفس عملية الاستيراد/السحب دون داعٍ، خصوصاً
    لملفات SQLite ضخمة (غيغابايتات) يأخذ تحميلها من رابط سحابي دقائق
    طويلة كما لاحظ المستخدم فعلياً."""
    conn = db.get_db()
    placeholders = ','.join('?' * len(_IMPORT_AUDIT_TARGETS))
    row = conn.execute(
        f"SELECT * FROM audit_log WHERE target_type IN ({placeholders}) "
        "ORDER BY timestamp DESC, id DESC LIMIT 1", _IMPORT_AUDIT_TARGETS
    ).fetchone()
    conn.close()
    if not row:
        return jsonify({'ok': True, 'has_notice': False})
    row = dict(row)
    label = _IMPORT_ACTION_LABELS.get((row['action_type'], row['target_type']), row['target_type'])
    return jsonify({
        'ok': True, 'has_notice': True,
        'timestamp': row.get('timestamp', ''),
        'label': label,
        'username': row.get('username', ''),
        'detail': row.get('new_value', '') or '',
    })


@app.route('/api/meta')
@login_required
def api_meta():
    conn = db.get_db()
    depts = [r['dept'] for r in conn.execute(
        "SELECT DISTINCT dept FROM employees WHERE dept IS NOT NULL AND dept != '' ORDER BY dept").fetchall()]
    employees = [dict(r) for r in conn.execute(
        "SELECT name, dept FROM employees WHERE active = 1 ORDER BY name").fetchall()]
    conn.close()
    # ===== قيد الأقسام المسموحة (لو مقيَّداً) - نفس _refresh_dept_filter_options
    # بالنسخة المكتبية: قوائم الفلترة نفسها لا تعرض أقساماً/موظفين خارج
    # نطاق المستخدم أصلاً =====
    allowed = allowed_departments()
    if allowed:
        allowed_set = set(allowed)
        depts = [d for d in depts if d in allowed_set]
        employees = [e for e in employees if (e.get('dept') or '') in allowed_set]
    # ===== employees_full (بالاسم + القسم معاً) بالإضافة لـemployees (أسماء
    # فقط - للتوافق مع الاستخدامات القديمة) - تحتاجه الواجهة لتصفية قائمة
    # "الموظفون" تلقائياً حسب القسم المختار بدل عرض كل موظفي القاعدة دائماً
    # بغض النظر عن القسم المحدَّد (كانت هذه المشكلة بالضبط) =====
    # ===== قوائم أسباب سبق إدخالها فعلياً (تأخير/غياب) - تُستخدم بصندوق
    # "تسجيل حدث" السريع (يُفتَح بالضغط على كلمة متأخر/غائب بجدول التقارير)
    # لعرضها كخيارات جاهزة بدل إجبار المستخدم على كتابة نفس السبب المتكرر
    # يدوياً كل مرة (مثلاً "إجازة مرضية بموافقة الإدارة") =====
    conn2 = db.get_db()
    late_labels = [r[0] for r in conn2.execute(
        "SELECT DISTINCT label FROM late_permissions WHERE label IS NOT NULL AND TRIM(label) != '' "
        "ORDER BY label").fetchall()]
    absence_reason_options = [r[0] for r in conn2.execute(
        "SELECT DISTINCT reason FROM absence_reasons WHERE reason IS NOT NULL AND TRIM(reason) != '' "
        "ORDER BY reason").fetchall()]
    conn2.close()
    return jsonify({'ok': True, 'departments': depts, 'employees': [e['name'] for e in employees],
                    'employees_full': employees, 'late_labels': late_labels,
                    'absence_reason_options': absence_reason_options})


_AR_WEEKDAYS = ['الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد']
_EXCLUDED_STATUSES = ('عطلة أسبوعية', 'عطلة رسمية', 'استثناء')


@app.route('/api/compare')
@login_required
def api_compare():
    """
    مقارنات إحصائية على بيانات report_cache (بعد آخر تحليل)، مجمَّعة
    حسب معيار مختار: القسم/الموظف/اليوم (بالأسبوع)/الأسبوع/الشهر - نفس
    معايير المقارنة بالنسخة المكتبية (home.py -> _generate_comparison)،
    مبسَّطة إلى مؤشرين موحَّدين يصلحان لكل معيار: متوسط دقائق التأخير
    (لمن تأخر فعلياً)، ونسبة الالتزام بالوقت (بدون احتساب أيام العطل/
    الاستثناء بالمقام).
    """
    criterion = request.args.get('criterion', 'dept')
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    conn = db.get_db()
    q = "SELECT * FROM report_cache WHERE 1=1"
    params = []
    if date_from:
        q += " AND date >= ?"
        params.append(date_from)
    if date_to:
        q += " AND date <= ?"
        params.append(date_to)
    rows = scoped_dept_filter([dict(r) for r in conn.execute(q, params).fetchall()])
    conn.close()

    if not rows:
        return jsonify({'ok': True, 'labels': [], 'avg_late': [], 'ontime_pct': [], 'counts': []})

    def group_key(r):
        if criterion == 'dept':
            return r.get('dept') or 'غير محدد'
        if criterion == 'employee':
            return r['name']
        if criterion == 'day':
            wd = r.get('weekday')
            return _AR_WEEKDAYS[wd] if wd is not None and 0 <= wd <= 6 else 'غير معروف'
        if criterion == 'week':
            try:
                d = datetime.strptime(r['date'], '%Y-%m-%d').date()
                y, w, _ = d.isocalendar()
                return f"{y}-W{w:02d}"
            except ValueError:
                return 'غير معروف'
        if criterion == 'month':
            return (r.get('date') or '')[:7]
        return 'الكل'

    groups = {}
    for r in rows:
        groups.setdefault(group_key(r), []).append(r)

    stats = []
    for label, grp in groups.items():
        late_rows = [r for r in grp if (r.get('late_minutes') or 0) > 0]
        avg_late = round(sum(r['late_minutes'] for r in late_rows) / len(late_rows), 1) if late_rows else 0
        non_excluded = [r for r in grp if r.get('status') not in _EXCLUDED_STATUSES]
        ontime = sum(1 for r in non_excluded if r.get('status') == 'في الوقت')
        ontime_pct = round(ontime / len(non_excluded) * 100, 1) if non_excluded else 0
        stats.append({'label': label, 'avg_late': avg_late, 'ontime_pct': ontime_pct, 'count': len(grp)})

    if criterion in ('dept', 'employee'):
        stats.sort(key=lambda s: s['avg_late'], reverse=True)
        stats = stats[:15]
    elif criterion == 'day':
        order = {d: i for i, d in enumerate(_AR_WEEKDAYS)}
        stats.sort(key=lambda s: order.get(s['label'], 99))
    else:  # week / month - ترتيب زمني تصاعدي
        stats.sort(key=lambda s: s['label'])

    return jsonify({
        'ok': True,
        'labels': [s['label'] for s in stats],
        'avg_late': [s['avg_late'] for s in stats],
        'ontime_pct': [s['ontime_pct'] for s in stats],
        'counts': [s['count'] for s in stats],
    })


@app.route('/api/blueprint')
@login_required
def api_blueprint():
    """
    لوحة "Blueprint" - نظرة شاملة بصفحة واحدة (مؤشرات + توزيع الحالات +
    اتجاه الحضور اليومي + اتجاه التأخير اليومي + أكثر الأقسام/الموظفين
    تأخيراً)، على نفس بيانات report_cache، بفلترة تاريخ اختيارية - نسخة
    ويب من تبويب Blueprint بالنسخة المكتبية (home.py).
    """
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    conn = db.get_db()
    q = "SELECT * FROM report_cache WHERE 1=1"
    params = []
    if date_from:
        q += " AND date >= ?"
        params.append(date_from)
    if date_to:
        q += " AND date <= ?"
        params.append(date_to)
    q += " ORDER BY date"
    rows = scoped_dept_filter([dict(r) for r in conn.execute(q, params).fetchall()])
    conn.close()

    if not rows:
        return jsonify({'ok': True, 'empty': True})

    total = len(rows)
    ontime = sum(1 for r in rows if r['status'] == 'في الوقت')
    late = sum(1 for r in rows if r['status'] in ('متأخر', 'تأخير بسيط'))
    hours = [r['working_hours'] for r in rows if r['working_hours']]
    avg_hours = round(sum(hours) / len(hours), 1) if hours else 0
    lates = [r['late_minutes'] for r in rows if r['late_minutes']]
    avg_late = round(sum(lates) / len(lates), 1) if lates else 0
    kpis = {
        'total': total,
        'ontime_pct': round(ontime / total * 100, 1) if total else 0,
        'late_pct': round(late / total * 100, 1) if total else 0,
        'avg_hours': avg_hours,
        'avg_late': avg_late,
    }

    status_counts = {}
    for r in rows:
        status_counts[r['status']] = status_counts.get(r['status'], 0) + 1

    non_holiday = [r for r in rows if r['status'] not in _EXCLUDED_STATUSES]
    daily_present = {}
    for r in non_holiday:
        daily_present[r['date']] = daily_present.get(r['date'], 0) + 1
    daily_present_sorted = sorted(daily_present.items())

    daily_late = {}
    daily_late_count = {}
    for r in rows:
        if (r.get('late_minutes') or 0) > 0:
            daily_late[r['date']] = daily_late.get(r['date'], 0) + r['late_minutes']
            daily_late_count[r['date']] = daily_late_count.get(r['date'], 0) + 1
    daily_late_avg_sorted = sorted(
        (d, round(daily_late[d] / daily_late_count[d], 1)) for d in daily_late
    )

    dept_late = {}
    dept_late_count = {}
    for r in rows:
        if (r.get('late_minutes') or 0) > 0:
            dept = r.get('dept') or 'غير محدد'
            dept_late[dept] = dept_late.get(dept, 0) + r['late_minutes']
            dept_late_count[dept] = dept_late_count.get(dept, 0) + 1
    top_depts = sorted(
        ({'label': d, 'value': round(dept_late[d] / dept_late_count[d], 1)} for d in dept_late),
        key=lambda x: x['value'], reverse=True
    )[:10]

    emp_late_sum = {}
    for r in rows:
        emp_late_sum[r['name']] = emp_late_sum.get(r['name'], 0) + (r.get('late_minutes') or 0)
    top_employees = sorted(
        ({'label': n, 'value': v} for n, v in emp_late_sum.items() if v > 0),
        key=lambda x: x['value'], reverse=True
    )[:10]

    return jsonify({
        'ok': True,
        'empty': False,
        'kpis': kpis,
        'status_counts': status_counts,
        'daily_present': {'labels': [d for d, _ in daily_present_sorted], 'values': [v for _, v in daily_present_sorted]},
        'daily_late': {'labels': [d for d, _ in daily_late_avg_sorted], 'values': [v for _, v in daily_late_avg_sorted]},
        'top_depts': top_depts,
        'top_employees': top_employees,
    })


# ============================================================
# ===== الموظفون =====
# ============================================================
@app.route('/api/employees', methods=['GET', 'POST'])
@login_required
def api_employees():
    conn = db.get_db()
    if request.method == 'POST':
        data = request.get_json(force=True)
        name = (data.get('name') or '').strip()
        dept = (data.get('dept') or '').strip()
        device_uid = (data.get('device_uid') or '').strip() or None
        if not name:
            conn.close()
            return jsonify({'ok': False, 'error': 'الاسم إجباري'}), 400
        try:
            conn.execute("INSERT INTO employees (name, dept, device_uid) VALUES (?, ?, ?)", (name, dept, device_uid))
            conn.commit()
        except Exception:
            conn.execute("UPDATE employees SET dept = ?, device_uid = COALESCE(?, device_uid) WHERE name = ?",
                         (dept, device_uid, name))
            conn.commit()
        conn.close()
        return jsonify({'ok': True})

    rows = scoped_dept_filter([dict(r) for r in conn.execute("SELECT * FROM employees ORDER BY name").fetchall()])
    conn.close()
    return jsonify({'ok': True, 'rows': rows})


@app.route('/api/employees/<int:emp_id>', methods=['DELETE'])
@login_required
def api_employee_delete(emp_id):
    conn = db.get_db()
    emp = conn.execute("SELECT name FROM employees WHERE id = ?", (emp_id,)).fetchone()
    for t in ('employee_accounts', 'geofence_overrides', 'employee_notifications', 'webauthn_credentials'):
        conn.execute(f"DELETE FROM {t} WHERE employee_id = ?", (emp_id,))
    conn.execute("DELETE FROM employees WHERE id = ?", (emp_id,))
    if emp:
        log_audit(conn, 'employee_delete', 'employee', emp['name'], new_value='حذف الموظف وحساب التطبيق')
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


_IMPORT_NAME_KEYS = ('name', 'اسم', 'الموظف')
_IMPORT_DEPT_KEYS = ('dept', 'department', 'قسم', 'إدارة')
# ===== "code"/"id"/"number"/"badge" أُضيفت بعد ملاحظة ملف حقيقي بعمود
# "Employee_Code" (رقم البصمة فعلياً) - كلمة "employee" وحدها بـ
# _IMPORT_NAME_KEYS كانت تلتقطه خطأً كعمود اسم (لاحتوائه على "employee")
# قبل ما يوصل الدور لعمود "Employee_Name" الحقيقي، فحُذفت من هناك، وأُضيف
# هنا كل ما يدل فعلياً على رقم/كود تعريف الموظف بجهاز البصمة =====
_IMPORT_AC_NO_KEYS = ('ac_no', 'ac-no', 'ac no', 'رقم الموظف', 'employee number', 'employee id',
                      'employee_id', 'employee code', 'employee_code', 'badge', 'card no', 'card_no',
                      'رقم البصمة', 'كود الموظف')


def _detect_import_columns(columns):
    """نفس منطق اكتشاف الأعمدة بـ home.py (_import_employees_from_file):
    نبحث بأسماء الأعمدة عن كلمات مفتاحية عربية/إنجليزية بدل الاعتماد على
    ترتيب أو تسمية ثابتة، حتى يعمل الاستيراد مع ملفات مصدَّرة من برامج
    مختلفة (حضور، جهاز بصمة، ملف يدوي...) بدون تعديل يدوي بأسماء الأعمدة.

    نكتشف عمود رقم البصمة (ac_no) أولاً، ثم عمود الاسم من الأعمدة
    المتبقية فقط (غير المُستخدَمة لرقم البصمة) - يمنع تضارب كلمات مفتاحية
    متشابهة (مثل "Employee_Code" مقابل "Employee_Name") من التقاط نفس
    العمود الخطأ لأول حقل يُفحص بترتيب الملف."""
    dept_col = ac_no_col = None
    for col in columns:
        col_lower = str(col).strip().lower()
        if col_lower.startswith('unnamed'):
            continue
        if dept_col is None and any(k in col_lower for k in _IMPORT_DEPT_KEYS):
            dept_col = col
        if ac_no_col is None and any(k in col_lower for k in _IMPORT_AC_NO_KEYS):
            ac_no_col = col

    name_col = None
    for col in columns:
        if col == ac_no_col or col == dept_col:
            continue
        col_lower = str(col).strip().lower()
        if col_lower.startswith('unnamed'):
            continue
        if any(k in col_lower for k in _IMPORT_NAME_KEYS):
            name_col = col
            break
    return name_col, dept_col, ac_no_col


@app.route('/api/employees/import', methods=['POST'])
@login_required
def api_employees_import():
    """استيراد موظفين من ملف Excel (.xlsx/.xls) أو CSV/TXT - مطابق لمنطق
    home.py (_import_employees_from_file): اكتشاف تلقائي لأعمدة الاسم/
    القسم/رقم البصمة (AC-No) بالاسم، واشتراط وجود عمود AC-No (بدونه
    سجلات الحضور المسحوبة من الجهاز ما تنطبق صح على الموظف). التكرار
    (نفس رقم AC-No أو نفس الاسم) يُحدَّث أو يُتجاهل حسب اختيار المستخدم
    بالنموذج (update_existing)، بدل تجاهله دائماً كما كانت النسخة السابقة."""
    src = _resolve_import_file()
    if not src.get('ok'):
        return jsonify(src), 400
    tmp_path = src['path']
    update_existing = request.form.get('update_existing') == '1'

    # ===== لو الملف/الرابط المُدخَل ببطاقة "استيراد الموظفين" هو فعلياً
    # قاعدة بيانات SQLite (تصدير جهاز بصمة - نفس الملف المستخدَم ببطاقة
    # "استيراد من جهاز البصمة") - نستخرج الموظفين من USERINFO مباشرة بدل
    # رفض الاستيراد، حتى يعمل استيراد الموظفين بنفس الرابط/الملف بغض النظر
    # عن أي بطاقة استُخدمت فعلياً، بدل اشتراط استخدام البطاقة "الصحيحة" =====
    try:
        with open(tmp_path, 'rb') as fh:
            is_sqlite = fh.read(len(_SQLITE_MAGIC)) == _SQLITE_MAGIC
    except OSError:
        is_sqlite = False
    if is_sqlite:
        try:
            sqlite_result = sqlite_import.read_employees_only(tmp_path)
        finally:
            if src.get('is_temp', True):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        if not sqlite_result.get('ok'):
            return jsonify(sqlite_result), 400
        conn = db.get_db()
        added, updated = _upsert_employees_from_source(conn, sqlite_result['employees'], update_existing)
        log_audit(conn, 'import', 'employees_from_sqlite',
                  new_value=f"{added} موظف جديد، {updated} تحديث - من ملف SQLite (بطاقة استيراد الموظفين)")
        conn.commit()
        conn.close()
        return jsonify({'ok': True, 'added': added, 'updated': updated, 'skipped': 0, 'missing_ac_no': 0})

    try:
        df, bad_lines = _read_table_file(tmp_path, tmp_path)
    except Exception as e:
        return jsonify({'ok': False, 'error': _friendly_read_error(e)}), 400
    finally:
        if src.get('is_temp', True):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    columns = list(map(str, df.columns))
    # ===== تعيين يدوي صريح (من خطوة تأكيد الأعمدة بالواجهة) له الأولوية
    # دائماً على الاكتشاف التلقائي بالاسم - يغطي أي تسمية أعمدة غير متوقَّعة
    # ما يلتقطها _detect_import_columns بدل رفض الملف نهائياً =====
    manual_mapping = request.form.get('mapping_confirmed') == '1'
    if manual_mapping:
        name_col = request.form.get('name_col') or None
        dept_col = request.form.get('dept_col') or None
        ac_no_col = request.form.get('ac_no_col') or None
        if not name_col:
            return jsonify({'ok': False, 'error': 'يرجى اختيار عمود الاسم'}), 400
        if not ac_no_col:
            return jsonify({'ok': False, 'error': 'يرجى اختيار عمود رقم البصمة (AC-No) - إجباري حتى تنطبق '
                                                    'سجلات الحضور المسحوبة من الجهاز على الموظف'}), 400
        if name_col not in df.columns or ac_no_col not in df.columns or (dept_col and dept_col not in df.columns):
            return jsonify({'ok': False, 'error': 'عمود محدَّد بخطوة التعيين غير موجود فعلياً بالملف'}), 400
    else:
        name_col, dept_col, ac_no_col = _detect_import_columns(df.columns)
        if not name_col or not ac_no_col:
            # ===== ما قدرنا نكتشف عمود الاسم و/أو رقم البصمة تلقائياً
            # بالاسم - بدل رفض الاستيراد نهائياً، نرجّع أسماء الأعمدة
            # الفعلية بالملف حتى يختارها المستخدم يدوياً (تماماً كخطوة
            # تعيين الأعمدة برفع بيانات البصمات) =====
            return jsonify({'ok': True, 'needs_mapping': True, 'columns': columns,
                             'detected': {'name_col': name_col, 'dept_col': dept_col, 'ac_no_col': ac_no_col}})

    conn = db.get_db()
    added = updated = skipped = missing_ac_no = 0
    for _, row in df.iterrows():
        name = str(row[name_col]).strip()
        if not name or name.lower() in ('nan', 'none', ''):
            continue
        dept = str(row[dept_col]).strip() if dept_col and pd.notna(row[dept_col]) else ''
        if dept.lower() in ('nan', 'none'):
            dept = ''
        ac_no = None
        if pd.notna(row[ac_no_col]):
            try:
                ac_no = str(int(float(row[ac_no_col])))
            except (ValueError, TypeError):
                ac_no = None
        if ac_no is None:
            # ===== نتجاهل الصف بدل إدخاله بدون رقم بصمة، حتى لا يتولّد
            # موظف ما ينطبق عليه أي سجل حضور من الجهاز أبداً =====
            missing_ac_no += 1
            continue

        existing = conn.execute(
            "SELECT id FROM employees WHERE device_uid = ? OR name = ?", (ac_no, name)
        ).fetchone()
        if existing:
            if update_existing:
                conn.execute("UPDATE employees SET dept = ?, device_uid = ? WHERE id = ?",
                             (dept, ac_no, existing['id']))
                updated += 1
            else:
                skipped += 1
            continue
        try:
            conn.execute("INSERT INTO employees (name, dept, device_uid) VALUES (?, ?, ?)", (name, dept, ac_no))
            added += 1
        except sqlite3.IntegrityError:
            # نفس الاسم موجود مسبقاً برقم بصمة مختلف - يُعامَل كتكرار بالاسم
            if update_existing:
                conn.execute("UPDATE employees SET dept = ?, device_uid = ? WHERE name = ?", (dept, ac_no, name))
                updated += 1
            else:
                skipped += 1
    conn.commit()
    conn.close()
    result = {'ok': True, 'added': added, 'updated': updated, 'skipped': skipped,
              'missing_ac_no': missing_ac_no}
    if bad_lines:
        result['warning'] = (f'تم تجاهل {len(bad_lines)} سطر غير صالح بالملف (عدد أعمدة غير متطابق) - '
                              'يُستحسن مراجعة الملف الأصلي والتأكد أن كل هذه الأسطر ليست بيانات '
                              'موظفين مطلوبة فعلياً.')
    return jsonify(result)


def _upsert_employees_from_source(conn, employees, update_existing):
    """يُنشئ/يحدّث موظفين من قائمة {device_uid, name, dept} (مثل الموظفين
    المستخرَجين من USERINFO/DEPARTMENTS بملف SQLite) - نفس منطق مطابقة
    استيراد Excel/CSV بالضبط (device_uid أو الاسم)، فرقه الوحيد أنه ياخذ
    القائمة جاهزة بدل قراءتها من DataFrame. يُرجع (added, updated)."""
    added = updated = 0
    for emp in employees:
        name = (emp.get('name') or '').strip()
        device_uid = (emp.get('device_uid') or '').strip()
        dept = (emp.get('dept') or '').strip()
        if not name or not device_uid:
            continue
        existing = conn.execute(
            "SELECT id, dept, device_uid FROM employees WHERE device_uid = ? OR name = ?", (device_uid, name)
        ).fetchone()
        if existing:
            if update_existing and (existing['dept'] != dept or existing['device_uid'] != device_uid):
                conn.execute("UPDATE employees SET dept = ?, device_uid = ? WHERE id = ?",
                             (dept, device_uid, existing['id']))
                updated += 1
            continue
        try:
            conn.execute("INSERT INTO employees (name, dept, device_uid) VALUES (?, ?, ?)", (name, dept, device_uid))
            added += 1
        except sqlite3.IntegrityError:
            # نفس الاسم موجود مسبقاً برقم بصمة مختلف - يُعامَل كتكرار بالاسم
            if update_existing:
                conn.execute("UPDATE employees SET dept = ?, device_uid = ? WHERE name = ?",
                             (dept, device_uid, name))
                updated += 1
    return added, updated


def _resolve_import_file(forced_ext=None):
    """يدعم ثلاثة مصادر لملف الاستيراد: ملف مرفوع مباشرة (حقل file)، رابط
    سحابي (حقل cloud_url: Google Drive/OneDrive/Dropbox أو أي رابط تنزيل
    مباشر آخر) - يُنزَّل الملف من الرابط لمسار مؤقت، أو مسار محلي على نفس
    جهاز الخادم (حقل local_path) - مفيد جداً لملفات ضخمة (مثل SQLite
    بحجم غيغابايت) عندما يعمل النظام مباشرة على نفس جهاز المستخدم
    (Termux/ويندوز): رفع الملف عبر المتصفح بهذه الحالة عملية زائدة تماماً
    (نسخ الملف نفسه مرتين على نفس الجهاز عبر شبكة محلية بطيئة أو متصفح
    قد يقطع الاتصال بملف ضخم) بينما الخادم يقدر يقرأه من القرص مباشرة.

    forced_ext: امتداد يُفرَض على المسار المؤقت بغض النظر عن اسم الملف
    الأصلي (تستخدمه ميزات att.mdb/SQLite اللي تعتمد على الامتداد لا
    المحتوى) - لو None نحاول اكتشاف الامتداد من اسم الملف نفسه (تستخدمه
    ميزات Excel/CSV لتحديد محرك القراءة المناسب).

    يُرجع dict: {ok, path, filename, is_temp} - is_temp=True فقط للملف
    المرفوع/المنزَّل من رابط (يُحذف بعد الاستخدام)، أما مسار محلي فهو ملف
    المستخدم الحقيقي على القرص ولا يُحذف أبداً - أو {ok: False, error}
    لو لا يوجد أي مصدر، أو فشل تنزيل الرابط، أو المسار المحلي غير موجود."""
    f = request.files.get('file')
    if f:
        filename = f.filename or ''
        ext = forced_ext if forced_ext is not None else (os.path.splitext(filename)[1] or '')
        tmp_path = os.path.join(tempfile.gettempdir(), f'upload_{uuid.uuid4().hex}{ext}')
        f.save(tmp_path)
        return {'ok': True, 'path': tmp_path, 'filename': filename, 'is_temp': True}

    cloud_url = (request.form.get('cloud_url') or '').strip()
    if cloud_url:
        dl = cloud_import.download_from_url(cloud_url)
        if not dl.get('ok'):
            return dl
        filename = dl.get('filename') or ''
        ext = forced_ext if forced_ext is not None else (os.path.splitext(filename)[1] or '')
        if ext:
            new_path = dl['path'] + ext
            try:
                os.rename(dl['path'], new_path)
                dl['path'] = new_path
            except OSError:
                pass
        return {'ok': True, 'path': dl['path'], 'filename': filename, 'is_temp': True}

    local_path = (request.form.get('local_path') or '').strip().strip('"')
    if local_path:
        if not os.path.isfile(local_path):
            return {'ok': False, 'error': f'الملف غير موجود بهذا المسار على جهاز الخادم: {local_path} - '
                                           'تأكد أن المسار صحيح وأن النظام (وليس المتصفح) يقدر يوصله فعلياً '
                                           '(نفس الجهاز أو تخزين متصل به).'}
        filename = os.path.basename(local_path)
        # ملفات قواعد البيانات (مثل att.mdb لبرنامج ZKTime) تُقرأ من نسخة مؤقتة لا من الأصل،
        # حتى لا يتعارض النظام مع البرنامج إن كان مفتوحاً، ولا يُترك أي قفل أو أثر على الملف الأصلي
        if os.path.splitext(local_path)[1].lower() in ('.mdb', '.accdb', '.db', '.sqlite', '.sqlite3'):
            import shutil
            tmp_path = os.path.join(tempfile.gettempdir(), f'copy_{uuid.uuid4().hex}{os.path.splitext(local_path)[1]}')
            try:
                shutil.copy2(local_path, tmp_path)
            except OSError as e:
                return {'ok': False, 'error': f'تعذّر نسخ الملف للقراءة: {e}'}
            return {'ok': True, 'path': tmp_path, 'filename': filename, 'is_temp': True}
        return {'ok': True, 'path': local_path, 'filename': filename, 'is_temp': False}

    return {'ok': False, 'error': 'يرجى اختيار ملف أو إدخال رابط الملف (Google Drive / OneDrive / '
                                   'Dropbox / أو أي رابط تنزيل مباشر)'}


def _friendly_read_error(e):
    """يحوّل خطأ قراءة الملف الخام (رسائل pandas الإنجليزية التقنية) إلى
    رسالة عربية مفهومة توضّح السبب الأرجح والحل المقترح - بدل عرض رسالة
    مثل "Error tokenizing data. C error: Expected 2 fields in line 35,
    saw 3" كما هي للمستخدم النهائي."""
    if isinstance(e, _BinaryFileDetected):
        return str(e)
    if isinstance(e, pd.errors.ParserError):
        return ('تعذّر قراءة الملف: عدد الأعمدة غير متطابق ببعض الأسطر - غالباً لأن الملف يستخدم فاصلاً غير '
                'الفاصلة العادية (,) مثل الفاصلة المنقوطة (;)، أو لأن أحد الحقول يحتوي فاصلة ضمن نصه بدون '
                'أن يكون النص محاطاً بعلامتي اقتباس ("..."). جرّب فتح الملف بـExcel وحفظه من جديد بصيغة '
                'CSV UTF-8، أو تأكد من صحة تنسيق الملف.')
    return f'تعذّر قراءة الملف: {e}'


def _read_csv_with_encoding(path, encoding):
    """يقرأ CSV بترميز محدَّد، ويُرجع (DataFrame, أرقام الأسطر المتجاهَلة) -
    يجرّب الفاصلة (,) أولاً، وإن فشل بخطأ "عدد أعمدة غير متطابق" (Error
    tokenizing data) يُعيد المحاولة بكشف الفاصل تلقائياً (csv.Sniffer عبر
    sep=None) بدل افتراض الفاصلة دائماً، لأن بعض ملفات Excel المصدَّرة
    بإعدادات عربية/أوروبية تستخدم الفاصلة المنقوطة (;) كفاصل. ولو ما زال
    الخطأ قائماً حتى بعد كشف الفاصل (سطر تالف فعلياً بالملف - حقل ناقص/
    زائد حقيقي، وليس مجرد فاصل خاطئ) نتجاهل ذلك السطر تحديداً بدل رفض
    الملف كاملاً، ونُرجع رقمه ليظهر للمستخدم بعد نجاح الاستيراد."""
    try:
        return pd.read_csv(path, encoding=encoding), []
    except pd.errors.ParserError:
        pass
    try:
        return pd.read_csv(path, encoding=encoding, sep=None, engine='python'), []
    except pd.errors.ParserError:
        pass
    skipped = []

    def _on_bad_line(bad_line):
        skipped.append(bad_line)
        return None  # يعني: تجاهل هذا السطر ومتابعة الباقي

    df = pd.read_csv(path, encoding=encoding, sep=None, engine='python',
                      on_bad_lines=_on_bad_line)
    return df, skipped


def _read_csv_auto_encoding(path):
    """يقرأ ملف CSV/TXT بأي ترميز - ملفات مصدَّرة من Excel على ويندوز عربي
    غالباً بترميز Windows-1256 (وليس UTF-8)، وأحياناً UTF-16 (لو حُفظت
    كـ"Unicode Text") أو UTF-8 بـBOM - فيفشل pandas.read_csv الافتراضي
    (UTF-8 صارم) برسالة "invalid continuation byte" رغم أن الملف سليم
    تماماً بترميزه الأصلي. نجرّب عدة ترميزات شائعة بالترتيب، ونستعين
    بمكتبة charset-normalizer لتخمين الترميز الفعلي لو كلها فشلت. بكل
    ترميز نجرّب أيضاً كشف الفاصل تلقائياً (انظر _read_csv_with_encoding)
    لأن مشكلة الفاصل قد تظهر مع أي ترميز."""
    encodings = ['utf-8-sig', 'utf-16', 'windows-1256', 'cp720', 'windows-1252']
    last_error = None
    for enc in encodings:
        try:
            return _read_csv_with_encoding(path, enc)
        except (UnicodeDecodeError, UnicodeError) as e:
            last_error = e
            continue
        except pd.errors.ParserError:
            # ===== الترميز نفسه صحيح (نجح فك التشفير) لكن الفاصل ما زال
            # غير متطابق حتى بعد الكشف التلقائي - نتوقف هنا بدل تجربة
            # ترميزات أخرى (لن تحل مشكلة الفاصل) ونرجّع الخطأ كما هو =====
            raise
    try:
        import charset_normalizer
        with open(path, 'rb') as fh:
            raw = fh.read()
        detected = charset_normalizer.from_bytes(raw).best()
        if detected and detected.encoding:
            return _read_csv_with_encoding(path, detected.encoding)
    except pd.errors.ParserError:
        raise
    except Exception:
        pass
    raise last_error or UnicodeDecodeError('utf-8', b'', 0, 1, 'تعذّر تحديد ترميز الملف')


_SQLITE_MAGIC = b'SQLite format 3\x00'


class _BinaryFileDetected(Exception):
    """يُرفَع لو الملف المطلوب قراءته كـCSV/TXT هو فعلياً ملف ثنائي (قاعدة
    بيانات SQLite، أو أي ملف آخر). ترميز Windows-1256 يقبل أي بايت بدون أي
    خطأ (بعكس UTF-8 الصارم)، فكان ملف SQLite ثنائي (مثل تصدير جهاز بصمة
    بامتداد .sqlite بُدّل اسمه أو استُخدم رابطه بالخطأ ببطاقة استيراد
    الموظفين) يُقرأ بصمت فيُنتِج أعمدة برموز غير مفهومة (مثل "ping%o") بدل
    رسالة خطأ واضحة."""
    pass


def _check_not_binary(path):
    try:
        with open(path, 'rb') as fh:
            sample = fh.read(8192)
    except OSError:
        return
    if not sample:
        return
    if sample.startswith(_SQLITE_MAGIC):
        raise _BinaryFileDetected(
            'هذا الملف هو قاعدة بيانات SQLite (تصدير من جهاز البصمة)، وليس ملف Excel/CSV لقائمة الموظفين. '
            'استخدم بطاقة "استيراد من جهاز البصمة (SQLite)" بدل بطاقة استيراد الموظفين - هي تستخرج الموظفين '
            'وسجلات الحضور من نفس الملف تلقائياً.')
    # نسبة البايتات غير القابلة للطباعة (نص حقيقي بأي ترميز - عربي أو غيره -
    # نادراً ما يتجاوز 1-2% حتى مع BOM/أسطر عربية) - تجاوز 30% يعني الملف
    # ثنائي وليس نصاً أصلاً، بصرف النظر عن الترميز
    text_bytes = bytes(range(0x20, 0x7f)) + b'\n\r\t\x0b\x0c'
    nontext = sum(1 for b in sample if b not in text_bytes and b < 0x80)
    if nontext / len(sample) > 0.3:
        raise _BinaryFileDetected(
            'هذا الملف ليس نصياً (CSV/TXT) بل يبدو ملفاً ثنائياً (مثل قاعدة بيانات أو ملف تالف أو نوع غير '
            'متوقَّع). تأكد من نوع الملف الصحيح، أو صدّره من جديد بصيغة CSV.')


def _read_table_file(f, filename):
    """يقرأ ملف مرفوع (Excel أو CSV) إلى (DataFrame, أرقام الأسطر
    المتجاهَلة) - قائمة فاضية دائماً لملفات Excel. نحدّد محرك القراءة
    صراحةً حسب امتداد الملف (xlrd لـ.xls، openpyxl لـ.xlsx) بدل الاعتماد
    على اكتشاف pandas التلقائي لصيغة الملف من محتواه، لأنه أحياناً يفشل
    (ValueError: Excel file format cannot be determined) مع ملفات .xls
    قديمة مصدَّرة من بعض برامج الحضور/الأجهزة رغم أن xlrd نفسه يقدر يقرأها
    بلا مشاكل لو استُدعي مباشرة. أما CSV/TXT فيُقرأ بمحاولة عدة ترميزات
    (انظر _read_csv_auto_encoding) بدل افتراض UTF-8 دائماً."""
    name_lower = (filename or '').lower()
    if name_lower.endswith('.xls'):
        return pd.read_excel(f, engine='xlrd'), []
    if name_lower.endswith('.xlsx'):
        return pd.read_excel(f, engine='openpyxl'), []
    _check_not_binary(f)
    return _read_csv_auto_encoding(f)


# ============================================================
# ===== رفع البيانات وتحليلها =====
# ============================================================
@app.route('/api/upload', methods=['POST'])
@login_required
def api_upload():
    src = _resolve_import_file()
    if not src.get('ok'):
        return jsonify(src), 400
    tmp_path = src['path']

    name_col = request.form.get('name_col', '').strip()
    date_col = request.form.get('date_col', '').strip()
    time_in_col = request.form.get('time_in_col', '').strip()
    time_out_col = request.form.get('time_out_col', '').strip()
    dept_col = request.form.get('dept_col', '').strip()

    try:
        raw_df, bad_lines = _read_table_file(tmp_path, tmp_path)
    except Exception as e:
        return jsonify({'ok': False, 'error': _friendly_read_error(e)}), 400
    finally:
        if src.get('is_temp', True):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    # ===== لو المستخدم ما حدد الأعمدة بعد، نرجّع أسماء الأعمدة الفعلية
    # بالملف حتى تُعرض بقوائم الاختيار بالواجهة (خطوة تعيين الأعمدة) =====
    if not (name_col and date_col and time_in_col and time_out_col):
        return jsonify({'ok': True, 'needs_mapping': True, 'columns': list(map(str, raw_df.columns))})

    missing = [c for c in [name_col, date_col, time_in_col, time_out_col] if c not in raw_df.columns]
    if missing:
        return jsonify({'ok': False, 'error': f'أعمدة غير موجودة بالملف: {", ".join(missing)}'}), 400

    df = pd.DataFrame()
    df['name'] = raw_df[name_col].astype(str).str.strip()
    df['date'] = pd.to_datetime(raw_df[date_col], errors='coerce').dt.strftime('%Y-%m-%d')
    df['time_in'] = raw_df[time_in_col].astype(str)
    df['time_out'] = raw_df[time_out_col].astype(str)
    df['dept'] = raw_df[dept_col].astype(str).str.strip() if (dept_col and dept_col in raw_df.columns) else ''
    df = df.dropna(subset=['date'])
    df = df[df['name'].str.strip() != '']

    batch_id = str(uuid.uuid4())
    conn = db.get_db()
    conn.executemany(
        "INSERT INTO punches (name, date, dept, time_in, time_out, batch_id) VALUES (?, ?, ?, ?, ?, ?)",
        [(r.name, r.date, r.dept, r.time_in, r.time_out, batch_id) for r in df.itertuples()]
    )
    # ===== نُنشئ/نحدّث سجل الموظف تلقائياً لو غير موجود، حتى تظهر قوائم
    # الأقسام/الموظفين بالفلاتر فور أول رفع بيانات =====
    for _, row in df.drop_duplicates('name').iterrows():
        try:
            conn.execute("INSERT INTO employees (name, dept) VALUES (?, ?)", (row['name'], row['dept']))
        except Exception:
            if row['dept']:
                conn.execute("UPDATE employees SET dept = ? WHERE name = ? AND (dept IS NULL OR dept = '')",
                             (row['dept'], row['name']))
    conn.commit()
    conn.close()

    result = {'ok': True, 'imported': len(df)}
    if bad_lines:
        result['warning'] = (f'تم تجاهل {len(bad_lines)} سطر غير صالح بالملف (عدد أعمدة غير متطابق) - '
                              'يُستحسن مراجعة الملف الأصلي والتأكد أن كل هذه الأسطر ليست بيانات '
                              'مطلوبة فعلياً.')
    return jsonify(result)


def run_full_analysis(conn):
    """
    ينفّذ نفس منطق /api/analyze على اتصال قاعدة بيانات مفتوح مُمرَّر من
    المستدعي (بدون فتح/إغلاق أو إرجاع JSON) - مستخرَجة بشكل مشترك حتى
    تُستخدم أيضاً من مهمة الجدولة التلقائية (scheduler.py) دون تكرار
    الكود أو الحاجة لطلب HTTP داخلي. تُرجع عدد الصفوف الناتجة.
    """
    punches_rows = conn.execute(
        "SELECT p.name, p.date, p.dept, p.time_in, p.time_out FROM punches p "
        "LEFT JOIN employees e ON e.name = p.name "
        "WHERE NOT (COALESCE(e.attendance_mode, 'both') IN ('device', 'qr', 'device_qr') AND COALESCE(p.batch_id, '') = 'mobile') "
        "AND NOT (COALESCE(e.attendance_mode, 'both') IN ('device', 'mobile') AND COALESCE(p.batch_id, '') = 'kiosk') "
        "AND NOT (COALESCE(e.attendance_mode, 'both') IN ('mobile', 'qr', 'mobile_qr') AND COALESCE(p.batch_id, '') NOT IN ('mobile', 'kiosk'))").fetchall()
    # كل مصدر يُحتسب فقط إن كانت طريقة توثيق الموظف تشمله (انظر MODE_SOURCES في mobile.py)
    punches_df = pd.DataFrame([dict(r) for r in punches_rows])

    settings = db.get_all_settings()

    dept_rows = conn.execute("SELECT dept, attendance_time, departure_time FROM dept_attendance_settings").fetchall()
    dept_times = {r['dept']: (
        parse_time_str(r['attendance_time']) if r['attendance_time'] else None,
        parse_time_str(r['departure_time']) if r['departure_time'] else None
    ) for r in dept_rows}

    manual_rows = conn.execute("SELECT name, date, time_in, time_out FROM manual_time_entries").fetchall()
    manual_entries = {(r['name'], r['date']): (r['time_in'], r['time_out']) for r in manual_rows}

    exc_rows = conn.execute("SELECT name, date FROM date_exceptions").fetchall()
    date_exceptions = {(r['name'], r['date']) for r in exc_rows}

    hol_rows = conn.execute("SELECT date FROM official_holidays").fetchall()
    official_holidays = {r['date'] for r in hol_rows}

    shift1_names = json.loads(db.get_setting('shift1_names_json', '[]'))
    shift2_names = json.loads(db.get_setting('shift2_names_json', '[]'))

    late_perm_rows = conn.execute(
        "SELECT name, date, minutes, custom_attendance_time, custom_departure_time FROM late_permissions").fetchall()
    late_permissions = {(r['name'], r['date']): dict(r) for r in late_perm_rows}

    dep_perm_rows = conn.execute(
        "SELECT name, date, departure_time, return_time FROM departure_permissions").fetchall()
    departure_permissions = {(r['name'], r['date']): dict(r) for r in dep_perm_rows}

    forced_rows = conn.execute("SELECT name, date FROM forced_absences").fetchall()
    forced_set = {(r['name'], r['date']) for r in forced_rows}

    cache_cols = ['name', 'dept', 'date', 'weekday', 'time_in', 'time_out', 'status', 'late_minutes', 'working_hours', 'shift']
    if punches_df.empty:
        result = pd.DataFrame(columns=cache_cols)
    else:
        result = analyze(punches_df, settings, dept_times, manual_entries, date_exceptions,
                          official_holidays, shift1_names, shift2_names,
                          late_permissions, departure_permissions)

    # ===== تطبيق "الغياب الإجباري" - يُجبر أي (موظف، تاريخ) مسجَّل بجدول
    # forced_absences يُحسب "غائب" فعلياً، بما في ذلك تحويل "عطلة أسبوعية"
    # (لمناوب كان مفروض يحضر) إلى "غائب" حقيقي - إلا لو كان اليوم استثناءً
    # شخصياً أو عطلة رسمية (هذان يبقيان أعلى أولوية دائماً). يشمل أيضاً
    # تركيب صف جديد بالكامل لو الموظف بلا أي بصمة إطلاقاً لهذا التاريخ
    # (بعكس النسخة المكتبية التي تتطلب صفاً موجوداً مسبقاً فقط) =====
    extra_rows = []
    if forced_set:
        result_keys = set(zip(result['name'], result['date'])) if not result.empty else set()
        if not result.empty:
            mask = result.apply(
                lambda r: (r['name'], r['date']) in forced_set and r['status'] not in ('استثناء', 'عطلة رسمية'),
                axis=1
            )
            if mask.any():
                result.loc[mask, 'time_in'] = ''
                result.loc[mask, 'time_out'] = ''
                result.loc[mask, 'status'] = 'غائب'
                result.loc[mask, 'late_minutes'] = 0
                result.loc[mask, 'working_hours'] = 0.0

        emp_dept = {r['name']: r['dept'] for r in conn.execute("SELECT name, dept FROM employees").fetchall()}
        for (name, date_str) in forced_set:
            if (name, date_str) in result_keys:
                continue
            if (name, date_str) in date_exceptions or date_str in official_holidays:
                continue
            try:
                weekday = datetime.strptime(date_str, '%Y-%m-%d').weekday()
            except ValueError:
                continue
            extra_rows.append({
                'name': name, 'dept': emp_dept.get(name, ''), 'date': date_str, 'weekday': weekday,
                'time_in': '', 'time_out': '', 'status': 'غائب', 'late_minutes': 0, 'working_hours': 0.0, 'shift': '',
            })

    rows_to_insert = [
        (r.name, r.dept, r.date, int(r.weekday) if pd.notna(r.weekday) else None, r.time_in, r.time_out,
         r.status, int(r.late_minutes), float(r.working_hours), r.shift) for r in result.itertuples()
    ] + [
        (r['name'], r['dept'], r['date'], r['weekday'], r['time_in'], r['time_out'],
         r['status'], r['late_minutes'], r['working_hours'], r['shift']) for r in extra_rows
    ]

    conn.execute("DELETE FROM report_cache")
    conn.executemany(
        "INSERT INTO report_cache (name, dept, date, weekday, time_in, time_out, status, late_minutes, working_hours, shift) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows_to_insert
    )
    conn.commit()
    return len(rows_to_insert)


@app.route('/api/analyze', methods=['POST'])
@login_required
def api_analyze():
    conn = db.get_db()
    has_punches = conn.execute("SELECT 1 FROM punches LIMIT 1").fetchone() is not None
    has_forced = conn.execute("SELECT 1 FROM forced_absences LIMIT 1").fetchone() is not None
    if not has_punches and not has_forced:
        conn.execute("DELETE FROM report_cache")
        conn.commit()
        conn.close()
        return jsonify({'ok': True, 'rows': 0, 'message': 'لا توجد بيانات مرفوعة للتحليل بعد'})
    rows = run_full_analysis(conn)
    conn.close()
    return jsonify({'ok': True, 'rows': rows})


@app.route('/api/punches/clear', methods=['POST'])
@login_required
def api_punches_clear():
    conn = db.get_db()
    conn.execute("DELETE FROM punches")
    conn.execute("DELETE FROM report_cache")
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


# ============================================================
# ===== الإدخال اليدوي =====
# ============================================================
@app.route('/api/manual-entries', methods=['GET', 'POST'])
@login_required
def api_manual_entries():
    conn = db.get_db()
    if request.method == 'POST':
        data = request.get_json(force=True)
        name = (data.get('name') or '').strip()
        date = (data.get('date') or '').strip()
        time_in = (data.get('time_in') or '').strip() or None
        time_out = (data.get('time_out') or '').strip() or None
        reason = (data.get('reason') or '').strip()
        if not (name and date and reason):
            conn.close()
            return jsonify({'ok': False, 'error': 'الاسم والتاريخ والسبب حقول إجبارية'}), 400
        if not (time_in or time_out):
            conn.close()
            return jsonify({'ok': False, 'error': 'يرجى تعبئة وقت الحضور أو الانصراف على الأقل'}), 400
        existing = conn.execute(
            "SELECT time_in, time_out FROM manual_time_entries WHERE name = ? AND date = ?",
            (name, date)
        ).fetchone()
        conn.execute(
            "INSERT INTO manual_time_entries (name, date, time_in, time_out, reason, entered_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(name, date) DO UPDATE SET "
            "time_in = COALESCE(excluded.time_in, manual_time_entries.time_in), "
            "time_out = COALESCE(excluded.time_out, manual_time_entries.time_out), "
            "reason = excluded.reason, entered_at = excluded.entered_at",
            (name, date, time_in, time_out, reason, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        log_audit(conn, 'update' if existing else 'create', 'manual_entry', name, date,
                   old_value=(f"{existing['time_in']}/{existing['time_out']}" if existing else None),
                   new_value=f"{time_in}/{time_out}", reason=reason)
        conn.commit()
        conn.close()
        return jsonify({'ok': True})

    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM manual_time_entries ORDER BY date DESC, name").fetchall()]
    conn.close()
    return jsonify({'ok': True, 'rows': rows})


@app.route('/api/manual-entries/<int:entry_id>', methods=['DELETE'])
@login_required
def api_manual_entry_delete(entry_id):
    conn = db.get_db()
    row = conn.execute("SELECT * FROM manual_time_entries WHERE id = ?", (entry_id,)).fetchone()
    conn.execute("DELETE FROM manual_time_entries WHERE id = ?", (entry_id,))
    if row:
        log_audit(conn, 'delete', 'manual_entry', row['name'], row['date'],
                   old_value=f"{row['time_in']}/{row['time_out']}", reason=row['reason'])
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


# ============================================================
# ===== أوقات الأقسام =====
# ============================================================
@app.route('/api/dept-times', methods=['GET', 'POST'])
@login_required
def api_dept_times():
    conn = db.get_db()
    if request.method == 'POST':
        data = request.get_json(force=True)
        dept = (data.get('dept') or '').strip()
        att = (data.get('attendance_time') or '').strip() or None
        dep = (data.get('departure_time') or '').strip() or None
        if not dept:
            conn.close()
            return jsonify({'ok': False, 'error': 'اسم القسم إجباري'}), 400
        conn.execute(
            "INSERT INTO dept_attendance_settings (dept, attendance_time, departure_time) VALUES (?, ?, ?) "
            "ON CONFLICT(dept) DO UPDATE SET attendance_time = excluded.attendance_time, departure_time = excluded.departure_time",
            (dept, att, dep)
        )
        conn.commit()
        conn.close()
        return jsonify({'ok': True})

    rows = [dict(r) for r in conn.execute("SELECT * FROM dept_attendance_settings ORDER BY dept").fetchall()]
    conn.close()
    return jsonify({'ok': True, 'rows': rows})


@app.route('/api/dept-times/<path:dept>', methods=['DELETE'])
@login_required
def api_dept_time_delete(dept):
    conn = db.get_db()
    conn.execute("DELETE FROM dept_attendance_settings WHERE dept = ?", (dept,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


# ============================================================
# ===== الإعدادات العامة =====
# ============================================================
@app.route('/api/settings', methods=['GET', 'POST'])
@login_required
def api_settings():
    if request.method == 'POST':
        data = request.get_json(force=True)
        allowed_keys = {
            'org_name', 'org_name_en', 'attendance_time', 'departure_time', 'late_threshold',
            'shift_enabled', 'shift1_start', 'shift1_end', 'shift2_start', 'shift2_end',
            'sat_time_enabled', 'sat_attendance_time', 'sat_departure_time', 'excluded_depts',
            'sync_central_url', 'sync_api_key',
        }
        old = db.get_all_settings()
        changed = []
        for k, v in data.items():
            if k in allowed_keys and not (k in SECRET_SETTINGS and v == SECRET_MASK):
                if str(old.get(k, '')) != str(v):
                    changed.append(k if k in SECRET_SETTINGS else f"{k}: {old.get(k, '')} → {v}")
                db.set_setting(k, str(v))
        if changed:
            c = db.get_db()
            log_audit(c, 'update', 'settings', new_value=' | '.join(changed)[:1000])
            c.commit()
            c.close()
        return jsonify({'ok': True})
    return jsonify({'ok': True, 'settings': mask_secrets(db.get_all_settings())})


@app.route('/api/settings/logo', methods=['POST', 'DELETE'])
@login_required
def api_settings_logo():
    """
    شعار المؤسسة: يُحفَظ كملف واحد فقط تحت static/uploads/org_logo.<ext>
    (يُستبدَل بالكامل عند رفع شعار جديد - أي امتداد قديم يُحذَف أولاً حتى
    لا يتراكم أكثر من ملف). يُستخدم لاحقاً بالشريط الجانبي، صفحة الدخول،
    ترويسة تقارير PDF، ورأس رسائل البريد.
    """
    settings = db.get_all_settings()
    old_filename = settings.get('org_logo_filename')

    if request.method == 'DELETE':
        if old_filename:
            old_path = os.path.join(LOGO_UPLOAD_DIR, old_filename)
            if os.path.isfile(old_path):
                os.remove(old_path)
        db.set_setting('org_logo_filename', '')
        return jsonify({'ok': True})

    file = request.files.get('logo')
    if not file or not file.filename:
        return jsonify({'ok': False, 'error': 'لم يُرفَع أي ملف'}), 400
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in _ALLOWED_LOGO_EXT:
        return jsonify({'ok': False, 'error': f'صيغة غير مدعومة - المسموح: {", ".join(sorted(_ALLOWED_LOGO_EXT))}'}), 400

    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > _MAX_LOGO_BYTES:
        return jsonify({'ok': False, 'error': 'حجم الملف كبير جداً (الحد الأقصى 15 ميجابايت)'}), 400

    # التحقق من أن الملف صورة فعلاً، وتصغيره وحفظه بصيغة PNG موحّدة
    # (يحل مشكلة الصور الكبيرة وصيغ الهاتف، ويحافظ على الشفافية)
    try:
        from PIL import Image, ImageOps
        img = Image.open(file.stream)
        img = ImageOps.exif_transpose(img)
        img = img.convert('RGBA')
        img.thumbnail((1024, 1024))
    except Exception:
        return jsonify({'ok': False, 'error': 'تعذّرت قراءة الصورة — استخدم ملف PNG أو JPG سليماً'}), 400

    # نحذف أي ملف شعار قديم (بأي امتداد) قبل حفظ الجديد
    if old_filename:
        old_path = os.path.join(LOGO_UPLOAD_DIR, old_filename)
        if os.path.isfile(old_path):
            os.remove(old_path)

    new_filename = 'org_logo.png'
    img.save(os.path.join(LOGO_UPLOAD_DIR, new_filename), 'PNG', optimize=True)
    db.set_setting('org_logo_filename', new_filename)
    logo, ver = _logo_file()
    return jsonify({'ok': True, 'logo_url': url_for('static', filename='uploads/' + logo, v=ver)})


# ============================================================
# ===== المزامنة مع قاعدة بيانات مركزية سحابية =====
# ============================================================
@app.route('/api/sync/push', methods=['POST'])
@login_required
def api_sync_push():
    """جانب الفرع (النسخة المحلية): يرفع كل التعديلات المحلية غير
    المرفوعة بعد (موظفون/بصمات) للقاعدة الرئيسية المضبوطة بالإعدادات
    (sync_central_url/sync_api_key)، وعند النجاح يعلّمها "تم رفعها" محلياً
    حتى لا تتكرر بالمرة القادمة."""
    settings = db.get_all_settings()
    conn = db.get_db()
    payload = sync_engine.get_unsynced_payload(conn)

    if not payload['employees'] and not payload['punches']:
        conn.close()
        return jsonify({'ok': True, 'nothing_to_sync': True})

    result = sync_engine.push_to_central(settings.get('sync_central_url'), settings.get('sync_api_key'), {
        'employees': [{k: v for k, v in e.items() if k != 'id'} for e in payload['employees']],
        'punches': [{k: v for k, v in p.items() if k != 'id'} for p in payload['punches']],
    })

    if not result.get('ok'):
        db.set_setting('sync_last_push_status', f"فشل: {result.get('error', '')}")
        conn.close()
        return jsonify(result), 400

    employee_ids = [e['id'] for e in payload['employees']]
    punch_ids = [p['id'] for p in payload['punches']]
    sync_engine.mark_synced(conn, employee_ids, punch_ids)
    log_audit(conn, 'sync', 'push',
              new_value=f"{len(employee_ids)} موظف، {len(punch_ids)} بصمة للقاعدة الرئيسية")
    conn.commit()
    conn.close()

    db.set_setting('sync_last_push_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    db.set_setting('sync_last_push_status', 'نجح')

    return jsonify({'ok': True, 'pushed_employees': len(employee_ids), 'pushed_punches': len(punch_ids),
                     'central_result': result})


@app.route('/api/sync/receive', methods=['POST'])
def api_sync_receive():
    """جانب القاعدة الرئيسية: يستقبل تعديلات من فرع محلي (عبر
    /api/sync/push هناك). ليست بحاجة تسجيل دخول (اتصال بين خادمين لا
    متصفح) - المصادقة عبر مفتاح ثابت برأس X-Sync-Key يجب أن يطابق
    sync_api_key المضبوط بإعدادات هذه النسخة بالضبط."""
    expected_key = (db.get_setting('sync_api_key') or '').strip()
    if not expected_key:
        return jsonify({'ok': False, 'error': 'هذه النسخة غير مُعدَّة لاستقبال مزامنة (لا يوجد مفتاح مزامنة '
                                                'بإعداداتها)'}), 401
    provided_key = (request.headers.get('X-Sync-Key') or '').strip()
    import hmac
    if not hmac.compare_digest(provided_key.encode(), expected_key.encode()):
        return jsonify({'ok': False, 'error': 'مفتاح المزامنة غير صحيح'}), 401

    payload = request.get_json(force=True, silent=True) or {}
    conn = db.get_db()
    result = sync_engine.receive_sync(conn, payload, run_full_analysis)
    log_audit(conn, 'sync', 'receive',
              new_value=f"{result.get('employees_added', 0)} موظف جديد، {result.get('employees_updated', 0)} "
                        f"تحديث، {result.get('punches_imported', 0)} بصمة - من فرع محلي")
    conn.commit()
    conn.close()
    return jsonify(result)


@app.route('/api/shift-names', methods=['GET', 'POST'])
@login_required
def api_shift_names():
    if request.method == 'POST':
        data = request.get_json(force=True)
        db.set_setting('shift1_names_json', json.dumps(data.get('shift1', []), ensure_ascii=False))
        db.set_setting('shift2_names_json', json.dumps(data.get('shift2', []), ensure_ascii=False))
        return jsonify({'ok': True})
    return jsonify({
        'ok': True,
        'shift1': json.loads(db.get_setting('shift1_names_json', '[]')),
        'shift2': json.loads(db.get_setting('shift2_names_json', '[]')),
    })


# ============================================================
# ===== استثناءات التواريخ/الموظفين =====
# ============================================================
@app.route('/api/date-exceptions', methods=['GET', 'POST'])
@login_required
def api_date_exceptions():
    conn = db.get_db()
    if request.method == 'POST':
        data = request.get_json(force=True)
        name = (data.get('name') or '').strip()
        date = (data.get('date') or '').strip()
        reason = (data.get('reason') or '').strip()
        if not (name and date):
            conn.close()
            return jsonify({'ok': False, 'error': 'الاسم والتاريخ حقلان إجباريان'}), 400
        conn.execute(
            "INSERT INTO date_exceptions (name, date, reason) VALUES (?, ?, ?) "
            "ON CONFLICT(name, date) DO UPDATE SET reason = excluded.reason",
            (name, date, reason)
        )
        log_audit(conn, 'create', 'date_exception', name, date, new_value=reason, reason=reason)
        conn.commit()
        conn.close()
        return jsonify({'ok': True})

    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM date_exceptions ORDER BY date DESC, name").fetchall()]
    conn.close()
    return jsonify({'ok': True, 'rows': rows})


@app.route('/api/date-exceptions/<int:exc_id>', methods=['DELETE'])
@login_required
def api_date_exception_delete(exc_id):
    conn = db.get_db()
    row = conn.execute("SELECT * FROM date_exceptions WHERE id = ?", (exc_id,)).fetchone()
    conn.execute("DELETE FROM date_exceptions WHERE id = ?", (exc_id,))
    if row:
        log_audit(conn, 'delete', 'date_exception', row['name'], row['date'], old_value=row['reason'])
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


def _date_range_list(date_from, date_to):
    """قائمة كل التواريخ (YYYY-MM-DD) بين تاريخين شاملين للطرفين، بلا
    استثناء أيام معيّنة (نفس سلوك "الإجازة الجماعية" بالنسخة المكتبية -
    تُطبَّق على كل يوم بالفترة بغض النظر عن كونه عطلة أسبوعية أم لا)."""
    d1 = datetime.strptime(date_from, '%Y-%m-%d').date()
    d2 = datetime.strptime(date_to, '%Y-%m-%d').date()
    if d2 < d1:
        d1, d2 = d2, d1
    days = (d2 - d1).days
    return [(d1 + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(days + 1)]


@app.route('/api/date-exceptions/bulk', methods=['POST'])
@login_required
def api_date_exceptions_bulk():
    """
    إجازة جماعية: يُطبِّق نفس استثناء التاريخ (بنفس السبب) على عدة
    موظفين معاً وعلى كل يوم ضمن فترة تاريخ محدَّدة دفعة واحدة - بدل
    تكرار /api/date-exceptions يدوياً لكل (موظف × يوم) على حدة. مطابق
    لميزة "إجازة جماعية" بالنسخة المكتبية (home.py).
    """
    data = request.get_json(force=True) or {}
    names = [n.strip() for n in (data.get('names') or []) if n.strip()]
    date_from = (data.get('date_from') or '').strip()
    date_to = (data.get('date_to') or '').strip()
    reason = (data.get('reason') or '').strip()
    if not names:
        return jsonify({'ok': False, 'error': 'اختر موظفاً واحداً على الأقل'}), 400
    if not (date_from and date_to):
        return jsonify({'ok': False, 'error': 'حدّد بداية ونهاية الفترة'}), 400
    try:
        dates = _date_range_list(date_from, date_to)
    except ValueError:
        return jsonify({'ok': False, 'error': 'صيغة تاريخ غير صحيحة'}), 400
    if len(dates) > 366:
        return jsonify({'ok': False, 'error': 'الفترة طويلة جداً (الحد الأقصى سنة واحدة)'}), 400

    conn = db.get_db()
    count = 0
    for name in names:
        for d in dates:
            conn.execute(
                "INSERT INTO date_exceptions (name, date, reason) VALUES (?, ?, ?) "
                "ON CONFLICT(name, date) DO UPDATE SET reason = excluded.reason",
                (name, d, reason)
            )
            count += 1
    log_audit(conn, 'create', 'date_exception_bulk',
              new_value=f"{len(names)} موظف × {len(dates)} يوم = {count} استثناء", reason=reason)
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'count': count})


@app.route('/api/date-exceptions/bulk-cancel', methods=['POST'])
@login_required
def api_date_exceptions_bulk_cancel():
    """يلغي (يحذف) استثناءات التاريخ لنفس الموظفين ونفس الفترة - العكس
    المباشر لـ /api/date-exceptions/bulk، بغض النظر عن السبب المسجَّل."""
    data = request.get_json(force=True) or {}
    names = [n.strip() for n in (data.get('names') or []) if n.strip()]
    date_from = (data.get('date_from') or '').strip()
    date_to = (data.get('date_to') or '').strip()
    if not names or not (date_from and date_to):
        return jsonify({'ok': False, 'error': 'اختر الموظفين وحدّد الفترة أولاً'}), 400
    try:
        dates = _date_range_list(date_from, date_to)
    except ValueError:
        return jsonify({'ok': False, 'error': 'صيغة تاريخ غير صحيحة'}), 400

    conn = db.get_db()
    placeholders_n = ','.join('?' * len(names))
    placeholders_d = ','.join('?' * len(dates))
    cur = conn.execute(
        f"DELETE FROM date_exceptions WHERE name IN ({placeholders_n}) AND date IN ({placeholders_d})",
        names + dates
    )
    deleted = cur.rowcount
    log_audit(conn, 'delete', 'date_exception_bulk',
              new_value=f"{len(names)} موظف × {len(dates)} يوم - حُذف {deleted} استثناء")
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'deleted': deleted})


# ============================================================
# ===== أسباب الغياب (لحالة "غائب" المحسوبة فعلياً بعد التحليل) =====
# ============================================================
@app.route('/api/absence-reasons', methods=['GET'])
@login_required
def api_absence_reasons():
    """
    يُرجع كل صفوف report_cache بحالة "غائب" (مع فلترة اختيارية بقسم/
    موظف/فترة تاريخ)، مربوطة بسبب الغياب المسجَّل لها لو موجود -
    مصدر تبويب "تصفح الغيابات وتحديد سبب كل يوم".
    """
    conn = db.get_db()
    q = "SELECT name, dept, date FROM report_cache WHERE status = 'غائب'"
    params = []
    dept = request.args.get('dept', '').strip()
    employee = request.args.get('employee', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    if dept and dept != 'الكل':
        q += " AND dept = ?"
        params.append(dept)
    if employee and employee != 'الكل':
        q += " AND name = ?"
        params.append(employee)
    if date_from:
        q += " AND date >= ?"
        params.append(date_from)
    if date_to:
        q += " AND date <= ?"
        params.append(date_to)
    q += " ORDER BY date DESC, name"
    absences = [dict(r) for r in conn.execute(q, params).fetchall()]

    reason_rows = conn.execute("SELECT name, date, reason FROM absence_reasons").fetchall()
    reason_map = {(r['name'], r['date']): r['reason'] for r in reason_rows}
    conn.close()

    for a in absences:
        a['reason'] = reason_map.get((a['name'], a['date']), '')
    return jsonify({'ok': True, 'rows': absences})


@app.route('/api/absence-reasons', methods=['POST'])
@login_required
def api_absence_reason_save():
    data = request.get_json(force=True) or {}
    name = (data.get('name') or '').strip()
    date = (data.get('date') or '').strip()
    reason = (data.get('reason') or '').strip()
    if not (name and date and reason):
        return jsonify({'ok': False, 'error': 'الاسم والتاريخ والسبب كلها حقول إجبارية'}), 400
    conn = db.get_db()
    conn.execute(
        "INSERT INTO absence_reasons (name, date, reason) VALUES (?, ?, ?) "
        "ON CONFLICT(name, date) DO UPDATE SET reason = excluded.reason",
        (name, date, reason)
    )
    log_audit(conn, 'create', 'absence_reason', name, date, new_value=reason)
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/absence-reasons/delete', methods=['POST'])
@login_required
def api_absence_reason_delete():
    data = request.get_json(force=True) or {}
    name = (data.get('name') or '').strip()
    date = (data.get('date') or '').strip()
    if not (name and date):
        return jsonify({'ok': False, 'error': 'الاسم والتاريخ إجباريان'}), 400
    conn = db.get_db()
    row = conn.execute("SELECT reason FROM absence_reasons WHERE name = ? AND date = ?", (name, date)).fetchone()
    conn.execute("DELETE FROM absence_reasons WHERE name = ? AND date = ?", (name, date))
    if row:
        log_audit(conn, 'delete', 'absence_reason', name, date, old_value=row['reason'])
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


# ============================================================
# ===== الغياب الإجباري =====
# ============================================================
@app.route('/api/forced-absences', methods=['GET'])
@login_required
def api_forced_absences():
    conn = db.get_db()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM forced_absences ORDER BY date DESC, name").fetchall()]
    conn.close()
    return jsonify({'ok': True, 'rows': rows})


@app.route('/api/forced-absences/<int:fa_id>', methods=['DELETE'])
@login_required
def api_forced_absence_delete(fa_id):
    conn = db.get_db()
    row = conn.execute("SELECT * FROM forced_absences WHERE id = ?", (fa_id,)).fetchone()
    conn.execute("DELETE FROM forced_absences WHERE id = ?", (fa_id,))
    if row:
        log_audit(conn, 'delete', 'forced_absence', row['name'], row['date'], old_value=row['reason'])
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/forced-absences/bulk', methods=['POST'])
@login_required
def api_forced_absences_bulk():
    """
    يُسجّل غياباً إجبارياً لعدة موظفين معاً وعلى كل يوم ضمن فترة تاريخ
    محدَّدة دفعة واحدة - مطابق لميزة "الغياب الإجباري" بالنسخة المكتبية،
    مع تحسين: يُنشئ سجلاً حتى لو الموظف بلا أي بصمة إطلاقاً لهذا التاريخ
    (راجع run_full_analysis بأعلى الملف).
    """
    data = request.get_json(force=True) or {}
    names = [n.strip() for n in (data.get('names') or []) if n.strip()]
    date_from = (data.get('date_from') or '').strip()
    date_to = (data.get('date_to') or '').strip()
    reason = (data.get('reason') or '').strip()
    if not names:
        return jsonify({'ok': False, 'error': 'اختر موظفاً واحداً على الأقل'}), 400
    if not (date_from and date_to):
        return jsonify({'ok': False, 'error': 'حدّد بداية ونهاية الفترة'}), 400
    try:
        dates = _date_range_list(date_from, date_to)
    except ValueError:
        return jsonify({'ok': False, 'error': 'صيغة تاريخ غير صحيحة'}), 400
    if len(dates) > 366:
        return jsonify({'ok': False, 'error': 'الفترة طويلة جداً (الحد الأقصى سنة واحدة)'}), 400

    conn = db.get_db()
    count = 0
    for name in names:
        for d in dates:
            conn.execute(
                "INSERT INTO forced_absences (name, date, reason) VALUES (?, ?, ?) "
                "ON CONFLICT(name, date) DO UPDATE SET reason = excluded.reason",
                (name, d, reason)
            )
            count += 1
    log_audit(conn, 'create', 'forced_absence_bulk',
              new_value=f"{len(names)} موظف × {len(dates)} يوم = {count} تسجيل غياب إجباري", reason=reason)
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'count': count})


@app.route('/api/forced-absences/bulk-cancel', methods=['POST'])
@login_required
def api_forced_absences_bulk_cancel():
    data = request.get_json(force=True) or {}
    names = [n.strip() for n in (data.get('names') or []) if n.strip()]
    date_from = (data.get('date_from') or '').strip()
    date_to = (data.get('date_to') or '').strip()
    if not names or not (date_from and date_to):
        return jsonify({'ok': False, 'error': 'اختر الموظفين وحدّد الفترة أولاً'}), 400
    try:
        dates = _date_range_list(date_from, date_to)
    except ValueError:
        return jsonify({'ok': False, 'error': 'صيغة تاريخ غير صحيحة'}), 400

    conn = db.get_db()
    placeholders_n = ','.join('?' * len(names))
    placeholders_d = ','.join('?' * len(dates))
    cur = conn.execute(
        f"DELETE FROM forced_absences WHERE name IN ({placeholders_n}) AND date IN ({placeholders_d})",
        names + dates
    )
    deleted = cur.rowcount
    log_audit(conn, 'delete', 'forced_absence_bulk',
              new_value=f"{len(names)} موظف × {len(dates)} يوم - حُذف {deleted} تسجيل")
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'deleted': deleted})


# ============================================================
# ===== العطل الرسمية =====
# ============================================================
@app.route('/api/official-holidays', methods=['GET', 'POST'])
@login_required
def api_official_holidays():
    conn = db.get_db()
    if request.method == 'POST':
        data = request.get_json(force=True)
        date = (data.get('date') or '').strip()
        label = (data.get('label') or '').strip()
        if not date:
            conn.close()
            return jsonify({'ok': False, 'error': 'التاريخ إجباري'}), 400
        conn.execute(
            "INSERT INTO official_holidays (date, label) VALUES (?, ?) "
            "ON CONFLICT(date) DO UPDATE SET label = excluded.label",
            (date, label)
        )
        log_audit(conn, 'create', 'official_holiday', date_affected=date, new_value=label)
        conn.commit()
        conn.close()
        return jsonify({'ok': True})

    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM official_holidays ORDER BY date DESC").fetchall()]
    conn.close()
    return jsonify({'ok': True, 'rows': rows})


@app.route('/api/official-holidays/<path:date>', methods=['DELETE'])
@login_required
def api_official_holiday_delete(date):
    conn = db.get_db()
    row = conn.execute("SELECT * FROM official_holidays WHERE date = ?", (date,)).fetchone()
    conn.execute("DELETE FROM official_holidays WHERE date = ?", (date,))
    if row:
        log_audit(conn, 'delete', 'official_holiday', date_affected=date, old_value=row['label'])
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


# ============================================================
# ===== إذن التأخير =====
# ============================================================
@app.route('/api/late-permissions', methods=['GET', 'POST'])
@login_required
def api_late_permissions():
    conn = db.get_db()
    if request.method == 'POST':
        data = request.get_json(force=True)
        name = (data.get('name') or '').strip()
        date = (data.get('date') or '').strip()
        minutes = data.get('minutes')
        custom_att = (data.get('custom_attendance_time') or '').strip() or None
        custom_dep = (data.get('custom_departure_time') or '').strip() or None
        label = (data.get('label') or '').strip()
        if not (name and date):
            conn.close()
            return jsonify({'ok': False, 'error': 'الاسم والتاريخ حقلان إجباريان'}), 400
        if not (minutes or custom_att):
            conn.close()
            return jsonify({'ok': False, 'error': 'يرجى تحديد عدد الدقائق أو وقت حضور مخصّص'}), 400
        try:
            minutes = int(minutes) if minutes not in (None, '') else 0
        except (TypeError, ValueError):
            minutes = 0
        conn.execute(
            "INSERT INTO late_permissions (name, date, minutes, custom_attendance_time, custom_departure_time, label) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(name, date) DO UPDATE SET "
            "minutes = excluded.minutes, custom_attendance_time = excluded.custom_attendance_time, "
            "custom_departure_time = excluded.custom_departure_time, label = excluded.label",
            (name, date, minutes, custom_att, custom_dep, label)
        )
        log_audit(conn, 'create', 'late_permission', name, date,
                   new_value=f"minutes={minutes}, custom_att={custom_att}", reason=label)
        conn.commit()
        conn.close()
        return jsonify({'ok': True})

    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM late_permissions ORDER BY date DESC, name").fetchall()]
    conn.close()
    return jsonify({'ok': True, 'rows': rows})


@app.route('/api/late-permissions/<int:perm_id>', methods=['DELETE'])
@login_required
def api_late_permission_delete(perm_id):
    conn = db.get_db()
    row = conn.execute("SELECT * FROM late_permissions WHERE id = ?", (perm_id,)).fetchone()
    conn.execute("DELETE FROM late_permissions WHERE id = ?", (perm_id,))
    if row:
        log_audit(conn, 'delete', 'late_permission', row['name'], row['date'],
                   old_value=f"minutes={row['minutes']}, custom_att={row['custom_attendance_time']}")
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


# ============================================================
# ===== إذن المغادرة المؤقتة =====
# ============================================================
@app.route('/api/departure-permissions', methods=['GET', 'POST'])
@login_required
def api_departure_permissions():
    conn = db.get_db()
    if request.method == 'POST':
        data = request.get_json(force=True)
        name = (data.get('name') or '').strip()
        date = (data.get('date') or '').strip()
        departure_time = (data.get('departure_time') or '').strip()
        return_time = (data.get('return_time') or '').strip()
        reason = (data.get('reason') or '').strip()
        if not (name and date and departure_time and return_time):
            conn.close()
            return jsonify({'ok': False, 'error': 'الاسم والتاريخ ووقت المغادرة والعودة حقول إجبارية'}), 400
        try:
            parse_time_str(departure_time)
            parse_time_str(return_time)
        except ValueError:
            conn.close()
            return jsonify({'ok': False, 'error': 'صيغة الوقت غير صحيحة (HH:MM)'}), 400
        conn.execute(
            "INSERT INTO departure_permissions (name, date, departure_time, return_time, reason) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(name, date) DO UPDATE SET "
            "departure_time = excluded.departure_time, return_time = excluded.return_time, reason = excluded.reason",
            (name, date, departure_time, return_time, reason)
        )
        log_audit(conn, 'create', 'departure_permission', name, date,
                   new_value=f"{departure_time}-{return_time}", reason=reason)
        conn.commit()
        conn.close()
        return jsonify({'ok': True})

    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM departure_permissions ORDER BY date DESC, name").fetchall()]
    conn.close()
    return jsonify({'ok': True, 'rows': rows})


@app.route('/api/departure-permissions/<int:perm_id>', methods=['DELETE'])
@login_required
def api_departure_permission_delete(perm_id):
    conn = db.get_db()
    row = conn.execute("SELECT * FROM departure_permissions WHERE id = ?", (perm_id,)).fetchone()
    conn.execute("DELETE FROM departure_permissions WHERE id = ?", (perm_id,))
    if row:
        log_audit(conn, 'delete', 'departure_permission', row['name'], row['date'],
                   old_value=f"{row['departure_time']}-{row['return_time']}", reason=row['reason'])
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


# ============================================================
# ===== سجل التدقيق (قراءة فقط) =====
# ============================================================
# ============================================================
# ===== أدوات الصيانة: حذف السجلات (مرحلة التجارب) =====
# ============================================================
# كل مجموعة: (العنوان، [(الجدول، عمود التاريخ أو None، شرط إضافي)])
PURGE_GROUPS = {
    'device_punches': ('بصمات أجهزة البصمة والملفات المرفوعة', [('punches', 'date', "COALESCE(batch_id, '') != 'mobile'")]),
    'mobile_punches': ('حركات تطبيق الهاتف (المقبولة والمرفوضة)', [('mobile_punches', 'date', None), ('punches', 'date', "batch_id = 'mobile'")]),
    'manual': ('الإدخالات اليدوية', [('manual_time_entries', 'date', None)]),
    'permissions': ('أذونات التأخير والمغادرة', [('late_permissions', 'date', None), ('departure_permissions', 'date', None)]),
    'absences': ('أسباب الغياب والغياب المفروض', [('absence_reasons', 'date', None), ('forced_absences', 'date', None)]),
    'exceptions': ('استثناءات التواريخ', [('date_exceptions', 'date', None)]),
    'holidays': ('العطل الرسمية', [('official_holidays', 'date', None)]),
    'notifications': ('إشعارات الموظفين', [('employee_notifications', 'created_at', None)]),
    'overrides': ('استثناءات الموقع', [('geofence_overrides', 'starts_at', None)]),
    'audit': ('سجل التدقيق', [('audit_log', 'timestamp', None)]),
    'employees': ('الموظفون وحسابات التطبيق والبصمات الحيوية (كل شيء مرتبط بهم)', [
        ('webauthn_credentials', None, None), ('employee_notifications', None, None), ('geofence_overrides', None, None),
        ('employee_accounts', None, None), ('employees', None, None)]),
}


def _purge_where(date_col, cond, d_from, d_to):
    where, params = [], []
    if cond:
        where.append(cond)
    if date_col and d_from:
        where.append(f"{date_col} >= ?"); params.append(d_from)
    if date_col and d_to:
        where.append(f"substr({date_col}, 1, 10) <= ?"); params.append(d_to)
    return (' WHERE ' + ' AND '.join(where)) if where else '', params


def _purge_counts(conn, d_from, d_to):
    out = []
    for key, (label, parts) in PURGE_GROUPS.items():
        n = 0
        for table, col, cond in parts:
            if key == 'employees' and table != 'employees':
                continue
            w, p = _purge_where(col, cond, d_from, d_to)
            n += conn.execute(f"SELECT COUNT(*) FROM {table}{w}", p).fetchone()[0]
        out.append({'key': key, 'label': label, 'count': n, 'dated': key != 'employees'})
    return out


@app.route('/api/maintenance/counts')
@login_required
def api_maintenance_counts():
    conn = db.get_db()
    try:
        return jsonify({'ok': True, 'groups': _purge_counts(conn, request.args.get('from', '')[:10], request.args.get('to', '')[:10])})
    finally:
        conn.close()


@app.route('/api/maintenance/purge', methods=['POST'])
@login_required
def api_maintenance_purge():
    d = request.get_json(silent=True) or {}
    groups = [g for g in (d.get('groups') or []) if g in PURGE_GROUPS]
    if not groups:
        return jsonify({'ok': False, 'error': 'اختر نوعاً واحداً على الأقل'}), 400
    if (d.get('confirm') or '').strip() not in ('حذف', 'DELETE', 'delete', 'Delete'):
        return jsonify({'ok': False, 'error': 'اكتب كلمة «حذف» للتأكيد'}), 400
    d_from, d_to = (d.get('from') or '')[:10], (d.get('to') or '')[:10]
    # نسخة احتياطية تلقائية قبل الحذف (يمكن استرجاعها من مجلد البيانات)
    import sqlite3 as _sq
    bk_dir = os.path.join(os.path.dirname(db.DB_PATH), 'before-delete')
    os.makedirs(bk_dir, exist_ok=True)
    bk = os.path.join(bk_dir, f"before-delete-{_audit_now().replace(':', '').replace(' ', '_')}.db")
    src = db.get_db()
    dst = _sq.connect(bk)
    src.backup(dst)
    dst.close()
    src.close()
    for old in sorted(os.listdir(bk_dir))[:-10]:          # نحتفظ بآخر 10 نسخ فقط
        try:
            os.remove(os.path.join(bk_dir, old))
        except OSError:
            pass
    conn = db.get_db()
    try:
        done = []
        for key in groups:
            label, parts = PURGE_GROUPS[key]
            n = 0
            for table, col, cond in parts:
                w, p = _purge_where(col, cond, d_from, d_to)
                n += conn.execute(f"DELETE FROM {table}{w}", p).rowcount
            done.append(f"{label}: {n}")
        log_audit(conn, 'purge', 'maintenance', new_value=' | '.join(done)[:1000],
                  reason=f"الفترة: {d_from or 'البداية'} → {d_to or 'النهاية'}")
        conn.commit()
        try:
            run_full_analysis(conn)
        except Exception:
            conn.execute("DELETE FROM report_cache")   # لا توجد بيانات كافية للتحليل
        conn.commit()
        return jsonify({'ok': True, 'done': done, 'backup': os.path.basename(bk),
                        'groups': _purge_counts(conn, d_from, d_to)})
    finally:
        conn.close()


@app.route('/api/audit-log')
@login_required
def api_audit_log():
    """سجل التدقيق: فلترة بالفترة والنوع والعملية والبحث + ملخص بالأعداد + تصدير CSV.
    مستخدم بأقسام محددة يرى فقط ما يخص موظفي أقسامه (والعمليات العامة لا تظهر له)."""
    a = request.args
    where, params = [], []
    if a.get('from'):
        where.append("timestamp >= ?"); params.append(a['from'][:10])
    if a.get('to'):
        where.append("timestamp < date(?, '+1 day')"); params.append(a['to'][:10])
    base_where = list(where); base_params = list(params)
    tt = (a.get('target_type') or '').strip()
    if tt and tt != 'الكل':
        where.append("target_type = ?"); params.append(tt)
    at = (a.get('action_type') or '').strip()
    if at:
        where.append("action_type = ?"); params.append(at)
    q = (a.get('q') or '').strip()
    if q:
        where.append("(employee_name LIKE ? OR username LIKE ? OR reason LIKE ? OR new_value LIKE ? OR old_value LIKE ?)")
        params += [f'%{q}%'] * 5
    try:
        limit = max(50, min(int(a.get('limit') or 1000), 50000))
    except ValueError:
        limit = 1000
    conn = db.get_db()
    sql_w = (' WHERE ' + ' AND '.join(where)) if where else ''
    rows = [dict(r) for r in conn.execute(
        f"SELECT * FROM audit_log{sql_w} ORDER BY timestamp DESC, id DESC LIMIT ?", params + [limit]).fetchall()]
    total = conn.execute(f"SELECT COUNT(*) FROM audit_log{sql_w}", params).fetchone()[0]
    bw = (' WHERE ' + ' AND '.join(base_where)) if base_where else ''
    facets = {
        'target_type': [dict(r) for r in conn.execute(
            f"SELECT target_type AS k, COUNT(*) AS n FROM audit_log{bw} GROUP BY target_type ORDER BY n DESC", base_params)],
        'action_type': [dict(r) for r in conn.execute(
            f"SELECT action_type AS k, COUNT(*) AS n FROM audit_log{bw} GROUP BY action_type ORDER BY n DESC", base_params)],
    }
    conn.close()
    allowed = allowed_departments()
    if allowed:
        conn = db.get_db()
        names = {r['name'] for r in conn.execute(
            f"SELECT name FROM employees WHERE dept IN ({','.join('?' * len(allowed))})", list(allowed))}
        conn.close()
        rows = [r for r in rows if r['employee_name'] in names]
        total = len(rows)
    if a.get('format') == 'csv':
        import csv, io
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(LL(['الوقت', 'المستخدم', 'العملية', 'النوع', 'الموظف', 'التاريخ المتأثر', 'القيمة السابقة', 'القيمة الجديدة', 'السبب']))
        for r in rows:
            w.writerow([r['timestamp'], r['username'], r['action_type'], r['target_type'], r['employee_name'] or '',
                        r['date_affected'] or '', r['old_value'] or '', r['new_value'] or '', r['reason'] or ''])
        return Response('\ufeff' + buf.getvalue(), content_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition': 'attachment; filename=audit_log.csv'})
    return jsonify({'ok': True, 'rows': rows, 'total': total, 'shown': len(rows), 'facets': facets})


# ============================================================
# ===== تصدير PDF مطابق للتقارير الأصلية =====
# ============================================================
@app.route('/api/reports/export.pdf')
@login_required
def api_reports_export_pdf():
    conn = db.get_db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM report_cache ORDER BY date DESC, time_in ASC").fetchall()]
    settings = db.get_all_settings()
    dept_time_rows = {r['dept']: r for r in conn.execute(
        "SELECT dept, attendance_time, departure_time FROM dept_attendance_settings").fetchall()}
    conn.close()
    filtered = _apply_common_filters(rows, request.args)

    total = len(filtered)
    ontime = sum(1 for r in filtered if r['status'] == 'في الوقت')
    late = sum(1 for r in filtered if r['status'] in ('متأخر', 'تأخير بسيط'))
    absent = sum(1 for r in filtered if r['status'] == 'غائب')
    holiday = sum(1 for r in filtered if r['status'] == 'عطلة أسبوعية')
    hours = [r['working_hours'] for r in filtered if r['working_hours']]
    avg_hours = round(sum(hours) / len(hours), 1) if hours else 0
    lates = [r['late_minutes'] for r in filtered if r['late_minutes']]
    avg_late = round(sum(lates) / len(lates), 1) if lates else 0
    stats = {'total': total, 'ontime': ontime, 'late': late, 'absent': absent,
              'holiday': holiday, 'avg_hours': avg_hours, 'avg_late': avg_late}

    parts = []
    dept = request.args.get('dept', '').strip()
    employee = request.args.get('employee', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    rt = request.args.get('report_type', 'all').strip()
    if dept and dept != 'الكل':
        parts.append(f"القسم: {dept}")
    if employee and employee != 'الكل':
        parts.append(f"الموظف: {employee}")
    if date_from or date_to:
        parts.append(f"الفترة: {date_from or '...'} إلى {date_to or '...'}")
    if rt and rt != 'all':
        parts.append(f"نوع التقرير: {RT_LABELS.get(rt, rt)}")
    filters_desc = ' | '.join(parts) if parts else 'كل السجلات (بدون فلترة)'

    # ===== سطر يوضّح أي وقت حضور/انصراف طُبِّق فعلياً على هذا التقرير -
    # وقت القسم الخاص لو محدَّد قسم وله وقت مخصَّص، وإلا الوقت العام =====
    general_att = settings.get('attendance_time', '')
    general_dep = settings.get('departure_time', '')
    if dept and dept != 'الكل' and dept in dept_time_rows and \
            (dept_time_rows[dept]['attendance_time'] or dept_time_rows[dept]['departure_time']):
        d_att = dept_time_rows[dept]['attendance_time'] or general_att
        d_dep = dept_time_rows[dept]['departure_time'] or general_dep
        times_desc = f"وقت الحضور/الانصراف المعتمد لقسم «{dept}»: {d_att} - {d_dep} (وقت خاص بالقسم)"
    elif dept and dept != 'الكل':
        times_desc = f"وقت الحضور/الانصراف المعتمد: {general_att} - {general_dep} (الوقت العام - لا يوجد وقت خاص لقسم «{dept}»)"
    else:
        times_desc = f"وقت الحضور/الانصراف العام المعتمد: {general_att} - {general_dep}"
    if settings.get('sat_time_enabled') == '1' and settings.get('sat_attendance_time') and settings.get('sat_departure_time'):
        times_desc += f"  |  وقت السبت الخاص: {settings.get('sat_attendance_time')} - {settings.get('sat_departure_time')}"

    import pdf_export as _pdfx
    _pdfx.TRANSLATE.set(_tr if _ui_lang(request) == 'en' else None)
    pdf_bytes = build_report_pdf(filtered, settings.get('org_name'), filters_desc, stats,
                                   session.get('full_name') or session.get('username'), times_desc,
                                   get_logo_path(settings))
    mem = io.BytesIO(pdf_bytes)
    return send_file(mem, mimetype='application/pdf', as_attachment=True,
                      download_name=f"attendance_report_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf")


# ============================================================
# ===== تصدير مستقل (Excel متعدد الأوراق + إرسال فوري بالبريد) =====
# ============================================================
_EXCEL_SHEETS = [
    ('الكل', None),
    ('المتأخرون', ('متأخر', 'تأخير بسيط')),
    ('الغائبون', ('غائب',)),
    ('في الوقت', ('في الوقت',)),
    ('عطلة أسبوعية', ('عطلة أسبوعية',)),
]

_EXCEL_HEADERS = ['الاسم', 'القسم', 'التاريخ', 'وقت الحضور', 'وقت الانصراف', 'الحالة',
                  'دقائق التأخير', 'ساعات العمل', 'المناوبة']


def _excel_row(r):
    return [r['name'], r['dept'] or '', r['date'], r['time_in'] or '', r['time_out'] or '',
            L(r['status'] or ''), r['late_minutes'], r['working_hours'], r['shift'] or '']


@app.route('/api/export/excel')
@login_required
def api_export_excel():
    """
    تصدير Excel بعدة أوراق دفعة واحدة (الكل / المتأخرون / الغائبون / في
    الوقت / عطلة أسبوعية) بنفس فلاتر قسم/موظف/فترة/بحث المستخدَمة ببقية
    التصدير - ميزة غير متوفرة بتصدير CSV/PDF أحادي الورقة الحالي، لأن
    كل ورقة هناك تحتاج طلب/فلترة منفصلة.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill

    conn = db.get_db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM report_cache ORDER BY date DESC, time_in ASC").fetchall()]
    conn.close()
    base_filtered = _apply_common_filters(rows, request.args)

    wb = Workbook()
    wb.remove(wb.active)
    header_font = Font(bold=True, color='FFFFFF')
    header_fill = PatternFill('solid', fgColor='2A78D6')
    header_align = Alignment(horizontal='center')

    for sheet_name, statuses in _EXCEL_SHEETS:
        sheet_rows = base_filtered if statuses is None else [r for r in base_filtered if r['status'] in statuses]
        ws = wb.create_sheet(title=L(sheet_name)[:31])
        ws.sheet_view.rightToLeft = _ui_lang(request) != 'en'
        ws.append(LL(_EXCEL_HEADERS))
        for cell in ws[1]:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align
        for r in sheet_rows:
            ws.append(_excel_row(r))
        widths = [18, 16, 12, 12, 12, 14, 10, 10, 10]
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
        if not sheet_rows:
            ws.append([L('لا توجد سجلات مطابقة بهذه الفلترة')])

    mem = io.BytesIO()
    wb.save(mem)
    mem.seek(0)
    return send_file(mem, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                      as_attachment=True,
                      download_name=f"attendance_report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx")


@app.route('/api/export/send-email', methods=['POST'])
@login_required
def api_export_send_email():
    """
    إرسال التقرير الحالي (بفلاتره) فوراً بالبريد لمستلمي الجدولة
    التلقائية المحفوظين - مستقل تماماً عن توقيت/يوم الجدولة نفسها، لإرسال
    فوري عند الحاجة دون انتظار الموعد المجدوَل أو تعديل إعداداته.
    """
    data = request.get_json(force=True) or {}
    conn = db.get_db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM report_cache ORDER BY date DESC, time_in ASC").fetchall()]
    settings = db.get_all_settings()
    reason_rows = conn.execute("SELECT name, date, reason FROM absence_reasons").fetchall()
    conn.close()
    absence_reasons = {(r['name'], r['date']): r['reason'] for r in reason_rows}

    filter_args = {
        'dept': data.get('dept', ''), 'employee': data.get('employee', ''),
        'date_from': data.get('date_from', ''), 'date_to': data.get('date_to', ''),
        'q': data.get('q', ''), 'report_type': data.get('report_type', 'all'),
    }
    filtered = _apply_common_filters(rows, filter_args)
    if not filtered:
        return jsonify({'ok': False, 'error': 'لا توجد سجلات مطابقة لهذه الفلترة - لم يُرسَل شيء'}), 400

    recipients = [r.strip() for r in (settings.get('smtp_recipients') or '').replace(';', ',').split(',') if r.strip()]
    if not recipients:
        return jsonify({'ok': False, 'error': 'لا يوجد مستلمون محدَّدون بإعدادات البريد (تبويب الجدولة التلقائية)'}), 400

    status_label = RT_LABELS.get(filter_args['report_type'], 'الكل')
    total = len(filtered)
    ontime = sum(1 for r in filtered if r['status'] == 'في الوقت')
    late = sum(1 for r in filtered if r['status'] in ('متأخر', 'تأخير بسيط'))
    absent = sum(1 for r in filtered if r['status'] == 'غائب')
    holiday = sum(1 for r in filtered if r['status'] == 'عطلة أسبوعية')
    hours = [r['working_hours'] for r in filtered if r['working_hours']]
    avg_hours = round(sum(hours) / len(hours), 1) if hours else 0
    lates = [r['late_minutes'] for r in filtered if r['late_minutes']]
    avg_late = round(sum(lates) / len(lates), 1) if lates else 0
    stats = {'total': total, 'ontime': ontime, 'late': late, 'absent': absent,
              'holiday': holiday, 'avg_hours': avg_hours, 'avg_late': avg_late}

    org_name = settings.get('org_name')
    logo_path = get_logo_path(settings)
    pdf_bytes = build_report_pdf(filtered, org_name, f"إرسال فوري - {status_label}", stats,
                                   session.get('full_name') or session.get('username'), None, logo_path)
    plain_body, html_body = email_sender.build_bilingual_email_body(
        filtered, 'تقرير مُرسَل فوراً', 'a report sent on demand', org_name, absence_reasons, logo_path)
    subject = f"{org_name} - تقرير مُرسَل فوراً - {datetime.now().strftime('%Y-%m-%d')}"
    filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"

    try:
        email_sender.send_email_auto(settings, recipients, subject, plain_body, html_body, pdf_bytes, filename)
    except Exception as e:
        return jsonify({'ok': False, 'error': f'فشل إرسال البريد: {e}'}), 400

    return jsonify({'ok': True, 'message': f"تم الإرسال إلى: {', '.join(recipients)} ({total} سجل)"})


# ============================================================
# ===== إدارة الأجهزة (ZKTeco) =====
# ============================================================
def _uid_employee_map(conn):
    """{device_uid: employee_name} لكل الموظفين النشطين اللي عندهم رقم
    بصمة مسجَّل - نفس المفتاح المستخدم بكل عمليات المطابقة (سحب/دفع/نسخ)."""
    rows = conn.execute(
        "SELECT device_uid, name FROM employees WHERE active = 1 AND device_uid IS NOT NULL AND device_uid != ''"
    ).fetchall()
    return {str(r['device_uid']).strip(): r['name'] for r in rows}


@app.route('/api/devices', methods=['GET', 'POST'])
@login_required
def api_devices():
    conn = db.get_db()
    if request.method == 'POST':
        data = request.get_json(force=True)
        name = (data.get('name') or '').strip()
        ip = (data.get('ip') or '').strip()
        port = data.get('port') or 4370
        password = str(data.get('password') or '0').strip()
        location = (data.get('location') or '').strip()
        if not (name and ip):
            conn.close()
            return jsonify({'ok': False, 'error': 'اسم الجهاز وعنوان IP حقلان إجباريان'}), 400
        conn.execute(
            "INSERT INTO devices (name, ip, port, password, location) VALUES (?, ?, ?, ?, ?)",
            (name, ip, int(port), password, location)
        )
        log_audit(conn, 'create', 'device', new_value=f"{name} ({ip}:{port})")
        conn.commit()
        conn.close()
        return jsonify({'ok': True})

    rows = [dict(r) for r in conn.execute("SELECT * FROM devices ORDER BY name").fetchall()]
    conn.close()
    return jsonify({'ok': True, 'rows': rows})


@app.route('/api/devices/<int:dev_id>', methods=['PUT', 'DELETE'])
@login_required
def api_device_edit(dev_id):
    conn = db.get_db()
    if request.method == 'DELETE':
        row = conn.execute("SELECT * FROM devices WHERE id = ?", (dev_id,)).fetchone()
        conn.execute("DELETE FROM devices WHERE id = ?", (dev_id,))
        if row:
            log_audit(conn, 'delete', 'device', old_value=f"{row['name']} ({row['ip']}:{row['port']})")
        conn.commit()
        conn.close()
        return jsonify({'ok': True})

    data = request.get_json(force=True)
    conn.execute(
        "UPDATE devices SET name = ?, ip = ?, port = ?, password = ?, location = ?, active = ? WHERE id = ?",
        (data.get('name'), data.get('ip'), int(data.get('port') or 4370), str(data.get('password') or '0'),
         data.get('location') or '', 1 if data.get('active', True) else 0, dev_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


def _get_devices(conn, device_ids=None):
    if device_ids:
        placeholders = ','.join('?' * len(device_ids))
        return [dict(r) for r in conn.execute(
            f"SELECT * FROM devices WHERE id IN ({placeholders})", device_ids).fetchall()]
    return [dict(r) for r in conn.execute("SELECT * FROM devices WHERE active = 1").fetchall()]


@app.route('/api/devices/<int:dev_id>/test', methods=['POST'])
@login_required
def api_device_test(dev_id):
    conn = db.get_db()
    dev = conn.execute("SELECT * FROM devices WHERE id = ?", (dev_id,)).fetchone()
    conn.close()
    if not dev:
        return jsonify({'ok': False, 'error': 'الجهاز غير موجود'}), 404
    return jsonify(zk_devices.test_connection(dict(dev)))


def pull_from_devices(conn, device_ids=None, d_from=None, d_to=None):
    """
    يسحب البصمات من الأجهزة المحدَّدة (أو كل الأجهزة المفعَّلة لو
    device_ids فاضية) ويُدرجها بجدول punches - مُستخرَجة بشكل مشترك من
    /api/devices/pull حتى تُستخدم أيضاً من مهمة الجدولة التلقائية
    (scheduler.py) بخطوة "اسحب من الأجهزة قبل الإرسال" الاختيارية.
    لا تفتح/تُغلق اتصال قاعدة البيانات (تستخدم conn المُمرَّر) ولا تعمل
    commit إلا بعد إدراج البيانات.
    """
    devices = _get_devices(conn, device_ids)
    if not devices:
        return {'ok': False, 'error': 'لا يوجد جهاز محدَّد أو مفعَّل', 'imported': 0, 'per_device': [], 'unmatched_uids': []}
    uid_map = _uid_employee_map(conn)

    all_rows, per_device, all_unmatched = [], [], set()
    for dev in devices:
        result = zk_devices.pull_attendance(dev, d_from, d_to, uid_map)
        if result.get('ok'):
            all_rows.extend(result['rows'])
            all_unmatched.update(result.get('unmatched_uids') or [])
            per_device.append({'device': dev['name'], 'ok': True, 'count': len(result['rows'])})
        else:
            per_device.append({'device': dev['name'], 'ok': False, 'error': result.get('error')})

    if all_rows:
        batch_id = str(uuid.uuid4())
        emp_dept = {r['name']: r['dept'] for r in conn.execute("SELECT name, dept FROM employees").fetchall()}
        conn.executemany(
            "INSERT INTO punches (name, date, dept, time_in, time_out, batch_id) VALUES (?, ?, ?, ?, ?, ?)",
            [(r['name'], r['date'], emp_dept.get(r['name'], ''), r['time_in'], r['time_out'], batch_id) for r in all_rows]
        )
        log_audit(conn, 'pull', 'device',
                   new_value=f"{len(all_rows)} سجل من {len([d for d in per_device if d['ok']])} جهاز",
                   reason=f"غير مطابق: {len(all_unmatched)} رقم بصمة" if all_unmatched else None)
        conn.commit()

    return {'ok': True, 'imported': len(all_rows), 'per_device': per_device, 'unmatched_uids': sorted(all_unmatched)}


@app.route('/api/devices/pull', methods=['POST'])
@login_required
def api_devices_pull():
    data = request.get_json(force=True)
    device_ids = data.get('device_ids') or []
    date_from = data.get('date_from') or None
    date_to = data.get('date_to') or None
    d_from = datetime.strptime(date_from, '%Y-%m-%d').date() if date_from else None
    d_to = datetime.strptime(date_to, '%Y-%m-%d').date() if date_to else None

    conn = db.get_db()
    result = pull_from_devices(conn, device_ids, d_from, d_to)
    conn.close()
    if not result.get('ok'):
        return jsonify(result), 400
    return jsonify(result)


@app.route('/api/devices/push', methods=['POST'])
@login_required
def api_devices_push():
    data = request.get_json(force=True)
    device_ids = data.get('device_ids') or []
    conn = db.get_db()
    devices = _get_devices(conn, device_ids)
    employees = [dict(r) for r in conn.execute(
        "SELECT name, device_uid FROM employees WHERE active = 1 AND device_uid IS NOT NULL AND device_uid != ''"
    ).fetchall()]
    conn.close()
    if not devices:
        return jsonify({'ok': False, 'error': 'لا يوجد جهاز محدَّد أو مفعَّل'}), 400
    if not employees:
        return jsonify({'ok': False, 'error': 'لا يوجد موظفون لديهم رقم بصمة (device_uid) مسجَّل'}), 400

    per_device = []
    for dev in devices:
        result = zk_devices.push_employees(dev, employees)
        per_device.append({'device': dev['name'], **result})
    return jsonify({'ok': True, 'per_device': per_device})


@app.route('/api/devices/<int:dev_id>/unlock', methods=['POST'])
@login_required
def api_device_unlock(dev_id):
    data = request.get_json(force=True) or {}
    conn = db.get_db()
    dev = conn.execute("SELECT * FROM devices WHERE id = ?", (dev_id,)).fetchone()
    conn.close()
    if not dev:
        return jsonify({'ok': False, 'error': 'الجهاز غير موجود'}), 404
    return jsonify(zk_devices.unlock_door(dict(dev), data.get('seconds', 3)))


@app.route('/api/devices/<int:dev_id>/clear-attendance', methods=['POST'])
@login_required
def api_device_clear_attendance(dev_id):
    conn = db.get_db()
    dev = conn.execute("SELECT * FROM devices WHERE id = ?", (dev_id,)).fetchone()
    if not dev:
        conn.close()
        return jsonify({'ok': False, 'error': 'الجهاز غير موجود'}), 404
    result = zk_devices.clear_device_attendance(dict(dev))
    if result.get('ok'):
        log_audit(conn, 'delete', 'device_attendance', new_value=dev['name'])
        conn.commit()
    conn.close()
    return jsonify(result)


@app.route('/api/devices/<int:dev_id>/users', methods=['GET'])
@login_required
def api_device_query_users(dev_id):
    """استعلام مباشر من الجهاز نفسه عن المستخدمين المسجَّلين عليه فعلياً -
    قراءة فقط، مفتوحة لأي مستخدم مسجَّل دخول (نفس قاعدة أي GET بالنظام)."""
    conn = db.get_db()
    dev = conn.execute("SELECT * FROM devices WHERE id = ?", (dev_id,)).fetchone()
    conn.close()
    if not dev:
        return jsonify({'ok': False, 'error': 'الجهاز غير موجود'}), 404
    result = zk_devices.query_device_users(dict(dev))
    return jsonify(result)


@app.route('/api/devices/<int:dev_id>/delete-users', methods=['POST'])
@login_required
def api_device_delete_users(dev_id):
    data = request.get_json(force=True) or {}
    device_uids = data.get('device_uids') or None
    conn = db.get_db()
    dev = conn.execute("SELECT * FROM devices WHERE id = ?", (dev_id,)).fetchone()
    if not dev:
        conn.close()
        return jsonify({'ok': False, 'error': 'الجهاز غير موجود'}), 404
    result = zk_devices.delete_device_users(dict(dev), device_uids)
    if result.get('ok'):
        log_audit(conn, 'delete', 'device_users', new_value=f"{dev['name']}: {device_uids or 'الكل'}")
        conn.commit()
    conn.close()
    return jsonify(result)


@app.route('/api/devices/live/start', methods=['POST'])
@login_required
def api_devices_live_start():
    data = request.get_json(force=True) or {}
    device_ids = data.get('device_ids') or []
    conn = db.get_db()
    devices = _get_devices(conn, device_ids)
    uid_map = _uid_employee_map(conn)
    conn.close()
    if not devices:
        return jsonify({'ok': False, 'error': 'لا يوجد جهاز محدَّد أو مفعَّل'}), 400
    return jsonify(zk_devices.start_live_capture(devices, uid_map))


@app.route('/api/devices/live/stop', methods=['POST'])
@login_required
def api_devices_live_stop():
    return jsonify(zk_devices.stop_live_capture())


@app.route('/api/devices/live/events')
@login_required
def api_devices_live_events():
    since_id = int(request.args.get('since', 0) or 0)
    return jsonify(zk_devices.get_live_events(since_id))


@app.route('/api/devices/copy-fingerprint', methods=['POST'])
@login_required
def api_devices_copy_fingerprint():
    data = request.get_json(force=True)
    source_id = data.get('source_id')
    target_ids = data.get('target_ids') or []
    device_uids = data.get('device_uids') or None
    if not source_id or not target_ids:
        return jsonify({'ok': False, 'error': 'يرجى تحديد جهاز مصدر وجهاز هدف واحد على الأقل'}), 400
    conn = db.get_db()
    source = conn.execute("SELECT * FROM devices WHERE id = ?", (source_id,)).fetchone()
    targets = _get_devices(conn, target_ids)
    conn.close()
    if not source:
        return jsonify({'ok': False, 'error': 'الجهاز المصدر غير موجود'}), 404
    result = zk_devices.copy_fingerprint_templates(dict(source), targets, device_uids)
    return jsonify(result)


@app.route('/api/devices/copy-face', methods=['POST'])
@login_required
def api_devices_copy_face():
    data = request.get_json(force=True)
    source_id = data.get('source_id')
    target_ids = data.get('target_ids') or []
    device_uids = data.get('device_uids') or None
    manual_password = (data.get('manual_password') or '').strip()
    if not source_id or not target_ids:
        return jsonify({'ok': False, 'error': 'يرجى تحديد جهاز مصدر وجهاز هدف واحد على الأقل'}), 400

    conn = db.get_db()
    source = conn.execute("SELECT * FROM devices WHERE id = ?", (source_id,)).fetchone()
    targets = _get_devices(conn, target_ids)
    if device_uids:
        placeholders = ','.join('?' * len(device_uids))
        employees = [dict(r) for r in conn.execute(
            f"SELECT name, device_uid FROM employees WHERE device_uid IN ({placeholders})", device_uids).fetchall()]
    else:
        employees = [dict(r) for r in conn.execute(
            "SELECT name, device_uid FROM employees WHERE active = 1 AND device_uid IS NOT NULL AND device_uid != ''").fetchall()]
    conn.close()
    if not source:
        return jsonify({'ok': False, 'error': 'الجهاز المصدر غير موجود'}), 404
    if not employees:
        return jsonify({'ok': False, 'error': 'لا يوجد موظفون لديهم رقم بصمة صالح'}), 400

    result = face_copy.copy_face_templates(dict(source), targets, employees, manual_password)
    return jsonify(result)


def _is_sqlite_file(path):
    try:
        with open(path, 'rb') as fh:
            return fh.read(len(_SQLITE_MAGIC)) == _SQLITE_MAGIC
    except OSError:
        return False


def _do_sqlite_device_import(tmp_path, date_from, date_to, create_employees, update_existing_employees):
    """المنطق المشترَك لاستيراد بصمات + موظفين من ملف SQLite - يُستدعى من
    /api/devices/import-sqlite مباشرة، ومن /api/devices/import-mdb أيضاً
    لو اتضح أن الملف المُدخَل هناك (رغم التسمية) هو SQLite فعلياً وليس
    att.mdb. يُرجع dict جاهز للإرجاع كـJSON (يحوي 'ok' دائماً)."""
    employees_added = employees_updated = 0
    source = sqlite_import.read_source(tmp_path)
    if not source.get('ok'):
        return source
    conn = db.get_db()
    if create_employees and source.get('employees'):
        employees_added, employees_updated = _upsert_employees_from_source(
            conn, source['employees'], update_existing_employees)
        conn.commit()

    uid_map = _uid_employee_map(conn)
    result = sqlite_import.aggregate_punches(source['raw_rows'], uid_map, date_from, date_to)
    if result.get('ok'):
        result['raw_count'] = source['raw_count']
        if result['rows']:
            batch_id = str(uuid.uuid4())
            emp_dept = {r['name']: r['dept'] for r in conn.execute("SELECT name, dept FROM employees").fetchall()}
            conn.executemany(
                "INSERT INTO punches (name, date, dept, time_in, time_out, batch_id) VALUES (?, ?, ?, ?, ?, ?)",
                [(r['name'], r['date'], emp_dept.get(r['name'], ''), r['time_in'], r['time_out'], batch_id)
                 for r in result['rows']]
            )
        # ===== نسجّل بسجل التدقيق دائماً (حتى لو صفر سجل استورد فعلياً) -
        # خصوصاً حالة "كل شيء غير مطابَق" (رقم بصمة الملف ما يطابق أي موظف)
        # يلي المستخدم أكثر ما يحتاجها لاحقاً، وكانت سابقاً لا تُسجَّل إطلاقاً
        # لأن التسجيل كان مربوطاً بوجود صفوف مستورَدة فعلياً =====
        note = (f"{len(result['rows'])} سجل مستورَد من أصل {result['raw_count']} خام، "
                f"{employees_added} موظف جديد، {employees_updated} تحديث - من ملف SQLite")
        unmatched = result.get('unmatched_uids') or []
        if unmatched:
            note += f" - أرقام بصمة غير مطابقة لأي موظف ({len(unmatched)}): {', '.join(unmatched)}"
        if result.get('skipped_bad_time'):
            note += f" - {result['skipped_bad_time']} سجل تُجوهل لتعذّر تفسير وقت البصمة"
        log_audit(conn, 'import', 'device_sqlite', new_value=note)
        conn.commit()
    conn.close()
    result['employees_added'] = employees_added
    result['employees_updated'] = employees_updated
    return result


@app.route('/api/devices/import-mdb', methods=['POST'])
@login_required
def api_devices_import_mdb():
    src = _resolve_import_file(forced_ext='.mdb')
    if not src.get('ok'):
        return jsonify(src), 400
    tmp_path = src['path']
    date_from = request.form.get('date_from') or None
    date_to = request.form.get('date_to') or None

    try:
        # ===== الملف المُدخَل بهذه البطاقة أحياناً يكون فعلياً SQLite (وليس
        # att.mdb) - رابط/ملف واحد يُستخدم بالخطأ بالبطاقة "الغلط"، فبدل
        # فرض خطأ "يحتاج ويندوز + Access Database Engine" رغم أن الملف لا
        # يحتاج ذلك إطلاقاً، نكتشف نوعه الحقيقي بمحتواه (لا بامتداده
        # المفروض) ونستورده بالمسار الصحيح تلقائياً =====
        if _is_sqlite_file(tmp_path):
            result = _do_sqlite_device_import(tmp_path, date_from, date_to, create_employees=True,
                                               update_existing_employees=True)
            if not result.get('ok'):
                return jsonify(result), 400
            return jsonify({'ok': True, 'imported': len(result['rows']),
                             'unmatched_uids': result.get('unmatched_uids', []),
                             'raw_count': result.get('raw_count', 0),
                             'employees_added': result.get('employees_added', 0),
                             'employees_updated': result.get('employees_updated', 0),
                             'detected_as_sqlite': True})

        conn = db.get_db()
        uid_map = _uid_employee_map(conn)
        result = mdb_import.import_from_mdb(tmp_path, date_from, date_to, uid_map)
        if result.get('ok'):
            if result['rows']:
                batch_id = str(uuid.uuid4())
                emp_dept = {r['name']: r['dept'] for r in conn.execute("SELECT name, dept FROM employees").fetchall()}
                conn.executemany(
                    "INSERT INTO punches (name, date, dept, time_in, time_out, batch_id) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    [(r['name'], r['date'], emp_dept.get(r['name'], ''), r['time_in'], r['time_out'], batch_id)
                     for r in result['rows']]
                )
            note = f"{len(result['rows'])} سجل مستورَد من أصل {result.get('raw_count', 0)} خام - من ملف att.mdb"
            unmatched = result.get('unmatched_uids') or []
            if unmatched:
                note += f" - أرقام بصمة غير مطابقة لأي موظف ({len(unmatched)}): {', '.join(unmatched)}"
            log_audit(conn, 'import', 'device_mdb', new_value=note)
            conn.commit()
        conn.close()
    finally:
        if src.get('is_temp', True):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    if not result.get('ok'):
        return jsonify(result), 400
    return jsonify({'ok': True, 'imported': len(result['rows']), 'unmatched_uids': result.get('unmatched_uids', []),
                     'raw_count': result.get('raw_count', 0)})


@app.route('/api/devices/import-sqlite', methods=['POST'])
@login_required
def api_devices_import_sqlite():
    """استيراد بصمات خام من ملف قاعدة بيانات SQLite (نفس مخطط CHECKINOUT
    المستخدم بـatt.mdb لكن بصيغة SQLite) - يعمل على أي نظام تشغيل بدون أي
    سائق خارجي، بعكس استيراد att.mdb المقيَّد بويندوز.

    بالإضافة: لو الملف يحتوي USERINFO (+ DEPARTMENTS اختياري)، يُنشئ/يحدّث
    الموظفين تلقائياً منه قبل مطابقة البصمات - بدل اشتراط إضافتهم يدوياً
    بتبويب الموظفين أولاً (create_employees/update_existing_employees
    قابلان للتعطيل من الواجهة، ومفعَّلان افتراضياً)."""
    src = _resolve_import_file(forced_ext='.sqlite')
    if not src.get('ok'):
        return jsonify(src), 400
    tmp_path = src['path']
    date_from = request.form.get('date_from') or None
    date_to = request.form.get('date_to') or None
    create_employees = request.form.get('create_employees', '1') == '1'
    update_existing_employees = request.form.get('update_existing_employees', '1') == '1'

    try:
        result = _do_sqlite_device_import(tmp_path, date_from, date_to, create_employees, update_existing_employees)
    finally:
        if src.get('is_temp', True):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    if not result.get('ok'):
        return jsonify(result), 400
    return jsonify({'ok': True, 'imported': len(result['rows']), 'unmatched_uids': result.get('unmatched_uids', []),
                     'raw_count': result.get('raw_count', 0), 'skipped_bad_time': result.get('skipped_bad_time', 0),
                     'employees_added': result.get('employees_added', 0),
                     'employees_updated': result.get('employees_updated', 0)})


# ============================================================
# ===== المستخدمون =====
# ============================================================
_VALID_ROLES = ('admin', 'dept_manager', 'viewer')

# ===== قيم افتراضية للصلاحيات الأربع حسب الدور - نفس _apply_role_defaults
# بالنسخة المكتبية بالضبط: تُطبَّق فقط لو الطلب ما بعث قيماً صريحة لكل
# صلاحية (يعني تعبئة أولية)، وتبقى قابلة للتخصيص اليدوي بعدها =====
_ROLE_PERMISSION_DEFAULTS = {
    'admin': {'can_manage_employees': True, 'can_manage_departments': True,
              'can_push_devices': True, 'can_edit_org_settings': True},
    'dept_manager': {'can_manage_employees': True, 'can_manage_departments': False,
                      'can_push_devices': False, 'can_edit_org_settings': False},
    'viewer': {'can_manage_employees': False, 'can_manage_departments': False,
               'can_push_devices': False, 'can_edit_org_settings': False},
}


def _set_user_departments(conn, user_id, depts):
    conn.execute("DELETE FROM user_departments WHERE user_id = ?", (user_id,))
    depts = sorted({d.strip() for d in (depts or []) if d and d.strip()})
    for d in depts:
        conn.execute("INSERT OR IGNORE INTO user_departments (user_id, dept) VALUES (?, ?)", (user_id, d))
    return depts


@app.route('/api/users', methods=['GET', 'POST'])
@login_required
def api_users():
    conn = db.get_db()
    if request.method == 'POST':
        data = request.get_json(force=True)
        username = (data.get('username') or '').strip()
        password = data.get('password') or ''
        full_name = (data.get('full_name') or '').strip()
        email = (data.get('email') or '').strip()[:200]
        # ===== الدور: افتراضياً "viewer" (اطّلاع فقط) ما لم يُحدَّد غير
        # ذلك صراحةً - حتى لا يُنشأ مستخدم بصلاحية كاملة عن طريق الخطأ =====
        role = (data.get('role') or 'viewer').strip()
        if role not in _VALID_ROLES:
            role = 'viewer'
        defaults = _ROLE_PERMISSION_DEFAULTS[role]
        perms = {k: bool(data.get(k, defaults[k])) for k in _PERMISSION_KEYS}
        if not (username and password):
            conn.close()
            return jsonify({'ok': False, 'error': 'اسم المستخدم وكلمة المرور إجباريان'}), 400
        if len(password) < 8:
            conn.close()
            return jsonify({'ok': False, 'error': 'كلمة المرور 8 أحرف على الأقل'}), 400
        try:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, full_name, role, can_manage_employees, "
                "can_manage_departments, can_push_devices, can_edit_org_settings) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (username, generate_password_hash(password), full_name, role,
                 int(perms['can_manage_employees']), int(perms['can_manage_departments']),
                 int(perms['can_push_devices']), int(perms['can_edit_org_settings']))
            )
            _set_user_departments(conn, cur.lastrowid, data.get('allowed_departments'))
            if email:
                conn.execute("UPDATE users SET email = ? WHERE id = ?", (email, cur.lastrowid))
            log_audit(conn, 'create', 'user', new_value=f"{username} ({role})")
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return jsonify({'ok': False, 'error': 'اسم المستخدم موجود مسبقاً'}), 400
        conn.close()
        return jsonify({'ok': True})

    rows = [dict(r) for r in conn.execute(
        "SELECT id, username, full_name, email, role, can_manage_employees, can_manage_departments, "
        "can_push_devices, can_edit_org_settings, created_at FROM users ORDER BY id").fetchall()]
    for r in rows:
        dept_rows = conn.execute("SELECT dept FROM user_departments WHERE user_id = ?", (r['id'],)).fetchall()
        r['allowed_departments'] = [dr['dept'] for dr in dept_rows]
    conn.close()
    return jsonify({'ok': True, 'rows': rows})


@app.route('/api/users/<int:user_id>', methods=['PUT', 'DELETE'])
@login_required
def api_user_edit(user_id):
    if request.method == 'PUT':
        data = request.get_json(force=True) or {}
        if 'email' in data and 'role' not in data:          # تعديل البريد فقط
            conn = db.get_db()
            conn.execute("UPDATE users SET email = ? WHERE id = ?", ((data.get('email') or '').strip()[:200], user_id))
            conn.commit()
            conn.close()
            return jsonify({'ok': True})
        if 'new_password' in data:                           # كلمة مرور جديدة يحدّدها المدير
            pw = data.get('new_password') or ''
            if len(pw) < 8:
                return jsonify({'ok': False, 'error': 'كلمة المرور 8 أحرف على الأقل'}), 400
            conn = db.get_db()
            u = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(pw), user_id))
            log_audit(conn, 'password_reset', 'user', new_value=(u['username'] if u else str(user_id)) + ' — بواسطة المدير')
            conn.commit()
            conn.close()
            return jsonify({'ok': True})
        role = (data.get('role') or '').strip()
        if role not in _VALID_ROLES:
            return jsonify({'ok': False, 'error': 'دور غير صالح'}), 400
        if user_id == session.get('user_id') and role != 'admin':
            return jsonify({'ok': False, 'error': 'لا يمكن سحب صلاحية admin عن نفسك أثناء تسجيل دخولك'}), 400
        defaults = _ROLE_PERMISSION_DEFAULTS[role]
        perms = {k: bool(data.get(k, defaults[k])) for k in _PERMISSION_KEYS}
        conn = db.get_db()
        cur = conn.execute(
            "UPDATE users SET role = ?, can_manage_employees = ?, can_manage_departments = ?, "
            "can_push_devices = ?, can_edit_org_settings = ? WHERE id = ?",
            (role, int(perms['can_manage_employees']), int(perms['can_manage_departments']),
             int(perms['can_push_devices']), int(perms['can_edit_org_settings']), user_id)
        )
        if cur.rowcount == 0:
            conn.close()
            return jsonify({'ok': False, 'error': 'المستخدم غير موجود'}), 404
        if 'allowed_departments' in data:
            _set_user_departments(conn, user_id, data.get('allowed_departments'))
        target = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        log_audit(conn, 'update', 'user', new_value=f"{target['username'] if target else user_id} ← {role} "
                  + ' '.join(k for k, v in perms.items() if v))
        conn.commit()
        conn.close()
        if user_id == session.get('user_id'):
            session['role'] = role
            for k, v in perms.items():
                session[k] = v
        return jsonify({'ok': True})

    if user_id == session.get('user_id'):
        return jsonify({'ok': False, 'error': 'لا يمكن حذف المستخدم الحالي أثناء تسجيل دخوله'}), 400
    conn = db.get_db()
    target = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    if target:
        log_audit(conn, 'delete', 'user', old_value=target['username'])
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


PERM_LABELS = {
    'can_manage_employees': 'الموظفون وحسابات التطبيق',
    'can_manage_departments': 'الأقسام',
    'can_push_devices': 'أجهزة البصمة (سحب/رفع/باب)',
    'can_edit_org_settings': 'الإعدادات والبريد والجدولة ومواقع العمل',
}


@app.route('/api/users/review')
@login_required
def api_users_review():
    """مراجعة صلاحيات كل المستخدمين في جدول واحد + ما يعنيه كل دور"""
    conn = db.get_db()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, username, full_name, role, can_manage_employees, can_manage_departments, can_push_devices, "
            "can_edit_org_settings, created_at, last_login_at, last_login_ip FROM users ORDER BY role, username").fetchall()]
        for r in rows:
            r['allowed_departments'] = [x['dept'] for x in conn.execute(
                "SELECT dept FROM user_departments WHERE user_id = ?", (r['id'],)).fetchall()]
            eff = {k: (r['role'] == 'admin' or bool(r[k])) for k in _PERMISSION_KEYS}
            r['effective'] = eff
            r['read_only'] = r['role'] == 'viewer'
            r['is_me'] = r['id'] == session.get('user_id')
        return jsonify({'ok': True, 'rows': rows, 'perm_labels': PERM_LABELS})
    finally:
        conn.close()


@app.route('/api/users/bulk', methods=['POST'])
@login_required
def api_users_bulk():
    data = request.get_json(force=True) or {}
    ids = [int(i) for i in (data.get('ids') or []) if str(i).isdigit()]
    action, value = data.get('action'), data.get('value')
    me = session.get('user_id')
    if not ids:
        return jsonify({'ok': False, 'error': 'حدّد مستخدماً واحداً على الأقل'}), 400
    conn = db.get_db()
    n = 0
    try:
        for uid in ids:
            if action == 'role' and value in _VALID_ROLES:
                if uid == me and value != 'admin':
                    continue
                d = _ROLE_PERMISSION_DEFAULTS[value]
                conn.execute("UPDATE users SET role = ?, can_manage_employees = ?, can_manage_departments = ?, "
                             "can_push_devices = ?, can_edit_org_settings = ? WHERE id = ?",
                             (value, int(d['can_manage_employees']), int(d['can_manage_departments']),
                              int(d['can_push_devices']), int(d['can_edit_org_settings']), uid))
            elif action in ('grant', 'revoke') and value in _PERMISSION_KEYS:
                conn.execute(f"UPDATE users SET {value} = ? WHERE id = ?", (1 if action == 'grant' else 0, uid))
            elif action == 'depts':
                _set_user_departments(conn, uid, value or [])
            elif action == 'delete':
                if uid == me:
                    continue
                conn.execute("DELETE FROM users WHERE id = ?", (uid,))
            else:
                continue
            n += 1
        log_audit(conn, 'users_bulk', 'user', new_value=f'{action} {value or ""} ← {n} مستخدم')
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True, 'count': n})


@app.route('/sw.js')
def service_worker():
    """Service Worker على مستوى الموقع كله (يُثبَّت النظام كتطبيق على Windows/أندرويد)"""
    resp = send_file(os.path.join(app.static_folder, 'sw.js'), mimetype='application/javascript')
    resp.headers['Service-Worker-Allowed'] = '/'
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


@app.route('/app')
def app_download_page():
    """صفحة تنزيل التطبيقات (APK للموظف وللإدارة + تثبيت على Windows)"""
    apk_dir = os.path.join(app.static_folder, 'apk')
    files = {}
    for key, name in (('employee', 'attendance-employee.apk'), ('admin', 'attendance-admin.apk')):
        path = os.path.join(apk_dir, name)
        if os.path.isfile(path):
            files[key] = {'url': url_for('static', filename='apk/' + name),
                          'size': f"{os.path.getsize(path) / 1048576:.1f}",
                          'date': datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d')}
    version = ''
    try:
        with open(os.path.join(apk_dir, 'version.txt'), encoding='utf-8') as fh:
            version = fh.read().strip()
    except OSError:
        pass
    return render_template('app_download.html', files=files, version=version, settings=db.get_all_settings())


@app.route('/api/change-password', methods=['POST'])
@login_required
def api_change_password():
    data = request.get_json(force=True)
    current = data.get('current_password') or ''
    new = data.get('new_password') or ''
    conn = db.get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (session['user_id'],)).fetchone()
    if not user or not check_password_hash(user['password_hash'], current):
        conn.close()
        return jsonify({'ok': False, 'error': 'كلمة المرور الحالية غير صحيحة'}), 400
    if len(new) < 8:
        conn.close()
        return jsonify({'ok': False, 'error': 'كلمة المرور الجديدة قصيرة جداً (8 أحرف على الأقل)'}), 400
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(new), session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


if __name__ == '__main__':
    db.init_db()
    # ===== نبدأ المجدول الخلفي مرة واحدة فقط - مع Flask debug=True تُشغَّل
    # هذه العملية مرتين فعلياً (عملية أب + عملية reloader)، فنقتصر على
    # العملية التي تحمل WERKZEUG_RUN_MAIN فقط لتفادي تكرار الإرسال =====
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
        import scheduler
        scheduler.start_scheduler()
    # threaded=True: يمنع طلب طويل (رفع/استيراد ملف ضخم) من "تجميد" بقية
    # الطلبات (مثل فحوصات الحالة الدورية بالواجهة) لحين انتهائه
    # وضع التطوير (debug) فقط عند طلبه صراحة — لا يُشغَّل أبداً على الشبكة لأنه يسمح بتنفيذ أوامر من المتصفح
    _debug = os.environ.get('FLASK_DEBUG') == '1'
    app.run(host='127.0.0.1' if _debug else '0.0.0.0', port=int(os.environ.get('PORT') or 5000),
            debug=_debug, threaded=True)
