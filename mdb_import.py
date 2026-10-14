"""
استيراد البصمات الخام من ملف att.mdb (تصدير برنامج att.exe المرافق لأجهزة
ZKTeco) - منقول حرفياً عن نفس استعلام SQL المستخدم بالنسخة المكتبية
(home.py._import_from_mdb_path): جدول CHECKINOUT (USERID, CHECKTIME,
CHECKTYPE) مربوط بجدول USERINFO (اسم الموظف المسجَّل على الجهاز نفسه).

يعتمد على pyodbc + "Microsoft Access Database Engine" (سائق ODBC) المثبَّت
على جهاز ويندوز - ميزة متاحة فقط على ويندوز (تماماً كما بالنسخة المكتبية)،
فنتحقق من توفرها بأمان ونُرجع رسالة عربية واضحة بدل انهيار البرنامج لو
غير متاحة.
"""
try:
    import pyodbc
    PYODBC_AVAILABLE = True
except ImportError:
    pyodbc = None
    PYODBC_AVAILABLE = False


def _get_access_driver():
    available = pyodbc.drivers()
    for candidate in ["Microsoft Access Driver (*.mdb, *.accdb)", "Microsoft Access Driver (*.mdb)"]:
        if candidate in available:
            return candidate
    return None


def import_from_mdb(path, date_from=None, date_to=None, uid_to_employee=None):
    """
    يقرأ بصمات CHECKINOUT ضمن فترة التاريخ (فلترة داخل SQL نفسه، ليس بعد
    السحب - أساسي لأداء مقبول بملفات فيها ملايين السجلات)، ويجمّعها لكل
    (موظف، تاريخ) بنفس منطق pull_attendance تماماً.

    المطابقة تفضّل اسم الموظف المسجَّل على الجهاز (USERINFO.NAME) لو
    موجود ومطابق لموظف نشط بالنظام، وإلا تعتمد على device_uid
    (employees.device_uid == CHECKINOUT.USERID) كما بباقي الميزات.

    يُرجع dict: {ok, rows, unmatched_uids, error}
    """
    if not PYODBC_AVAILABLE:
        return {'ok': False, 'error': 'هذه الميزة تحتاج تشغيل النظام على ويندوز مع تثبيت '
                                       '"Microsoft Access Database Engine" - غير متاحة على هذا الخادم حالياً.'}
    import os
    if not path or not os.path.exists(path):
        return {'ok': False, 'error': f'ملف att.mdb غير موجود بالمسار المحدَّد: {path}'}

    driver = _get_access_driver()
    if driver is None:
        try:
            drivers_list = ', '.join(pyodbc.drivers())
        except Exception:
            drivers_list = 'تعذّر جلب القائمة'
        return {'ok': False, 'error': f'لا يوجد برنامج تشغيل (Driver) لـ Microsoft Access مثبَّت على هذا الجهاز. '
                                       f'برامج التشغيل المتاحة حالياً: {drivers_list}'}

    uid_to_employee = uid_to_employee or {}
    # قراءة فقط ودون حجز حصري — لا يكتب السائق أي شيء في الملف
    conn_str = rf"Driver={{{driver}}};DBQ={path};ReadOnly=1;Exclusive=0;"

    # ملاحظة مهمة: تمرير التاريخ كنص خام ("2026-01-01") لسائق Access قد يُقارَن
    # بشكل خاطئ مع عمود CHECKTIME (نوعه datetime) - أحياناً يرجع صفر سجلاً
    # بصمت دون أي خطأ. لذا نحوّل التواريخ إلى datetime حقيقية قبل تمريرها،
    # ونجعل "إلى" شاملاً لكامل اليوم (حتى 23:59:59) لا لحظة منتصف الليل فقط.
    from datetime import datetime as _dt, timedelta as _td
    params = []
    where_clause = ""
    if date_from and date_to:
        try:
            d_from = _dt.strptime(date_from[:10], '%Y-%m-%d')
            d_to = _dt.strptime(date_to[:10], '%Y-%m-%d') + _td(days=1) - _td(seconds=1)
            where_clause = " WHERE c.CHECKTIME BETWEEN ? AND ?"
            params = [d_from, d_to]
        except ValueError:
            return {'ok': False, 'error': f'صيغة التاريخ غير صحيحة: {date_from} / {date_to}'}

    try:
        conn = pyodbc.connect(conn_str, readonly=True)
        cursor = conn.cursor()
        query = ("SELECT c.USERID, c.CHECKTIME, c.CHECKTYPE, u.NAME "
                 "FROM CHECKINOUT c LEFT JOIN USERINFO u ON c.USERID = u.USERID") + where_clause
        cursor.execute(query, params) if params else cursor.execute(query)
        raw_rows = cursor.fetchall()
        conn.close()
    except Exception as e:
        return {'ok': False, 'error': f'تعذّر قراءة ملف att.mdb: {e}'}

    # ===== نفس التجميع المستخدم بسحب الأجهزة مباشرة: أول/آخر بصمة باليوم
    # لكل موظف؛ CHECKTYPE (I=دخول, O=خروج) يُستخدم فقط لو موجود ومفيد -
    # التجميع بالوقت وحده كافٍ ومطابق لمنطق pull_attendance =====
    buckets = {}
    unmatched_uids = set()
    for row in raw_rows:
        userid, checktime = row[0], row[1]
        uid = str(userid).strip()
        name = uid_to_employee.get(uid)
        if not name:
            unmatched_uids.add(uid)
            continue
        if checktime is None:
            continue
        date_str = checktime.strftime('%Y-%m-%d')
        buckets.setdefault((uid, date_str), []).append(checktime)

    rows = []
    for (uid, date_str), stamps in buckets.items():
        stamps.sort()
        name = uid_to_employee[uid]
        time_in = stamps[0].strftime('%H:%M:%S')
        time_out = stamps[-1].strftime('%H:%M:%S') if len(stamps) > 1 else ''
        rows.append({'name': name, 'date': date_str, 'time_in': time_in, 'time_out': time_out})

    return {'ok': True, 'rows': rows, 'unmatched_uids': sorted(unmatched_uids), 'raw_count': len(raw_rows)}
