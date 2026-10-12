"""
استيراد البصمات الخام من ملف قاعدة بيانات SQLite (تصدير بعض برامج/أنظمة
حضور تستخدم نفس مخطط جدول CHECKINOUT المعروف - USERID/CHECKTIME/CHECKTYPE -
لكن بصيغة SQLite بدل Access .mdb). بعكس استيراد att.mdb، هذا لا يحتاج أي
سائق أو مكتبة خارجية (sqlite3 مُضمَّنة ببايثون نفسه)، فيعمل على أي نظام
تشغيل بدون أي قيد (ويندوز/لينكس/أندرويد-Termux).

نفس منطق التجميع المستخدم بسحب الأجهزة/استيراد att.mdb بالضبط: أول/آخر
بصمة باليوم لكل (موظف، تاريخ).

بالإضافة: يقرأ أيضاً جدول USERINFO (+ DEPARTMENTS لو موجود بنفس الملف)
لإرجاع قائمة موظفين (device_uid/name/dept) جاهزة لإنشاء/تحديث الموظفين
تلقائياً وقت الاستيراد، بدل اشتراط إضافتهم يدوياً بتبويب الموظفين أولاً.
"""
import os
import sqlite3
from datetime import datetime, timedelta

import pandas as pd


def _table_exists(conn, name):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    return row is not None


def _table_columns(conn, name):
    """يُرجع dict {ASSM_UPPER: الاسم_الفعلي_بحساسية_الأحرف} - أسماء
    الأعمدة تختلف بحساسية الأحرف بين برامج تصدير مختلفة."""
    return {r[1].upper(): r[1] for r in conn.execute(f"PRAGMA table_info({name})").fetchall()}


def _get_department_map(conn):
    """يقرأ جدول DEPARTMENTS (لو موجود) ويُرجع dict {dept_id: dept_name} -
    أسماء الأعمدة الفعلية تختلف بين برامج التصدير، فنجرّب المرشَّحين
    الأكثر شيوعاً بدل افتراض اسم واحد ثابت."""
    if not _table_exists(conn, 'DEPARTMENTS'):
        return {}
    cols = _table_columns(conn, 'DEPARTMENTS')
    id_col = next((cols[c] for c in ('DEPTID', 'ID', 'DEPARTMENTID') if c in cols), None)
    name_col = next((cols[c] for c in ('DEPTNAME', 'NAME', 'DEPT_NAME') if c in cols), None)
    if not id_col or not name_col:
        return {}
    try:
        rows = conn.execute(f"SELECT {id_col}, {name_col} FROM DEPARTMENTS").fetchall()
    except sqlite3.OperationalError:
        return {}
    return {str(r[0]): (r[1] or '').strip() for r in rows if r[0] is not None}


def read_employees(conn):
    """يقرأ USERINFO (+ DEPARTMENTS) لإرجاع قائمة موظفين جاهزة
    [{'device_uid', 'name', 'dept'}, ...] مباشرة من ملف SQLite - قائمة
    فاضية لو الجدول غير موجود أو ناقص الأعمدة الأساسية (USERID/NAME)."""
    if not _table_exists(conn, 'USERINFO'):
        return []
    cols = _table_columns(conn, 'USERINFO')
    userid_col = cols.get('USERID')
    name_col = cols.get('NAME')
    if not userid_col or not name_col:
        return []
    dept_id_col = next((cols[c] for c in ('DEFAULTDEPTID', 'DEPTID', 'DEPARTMENTID') if c in cols), None)
    dept_map = _get_department_map(conn) if dept_id_col else {}

    select_cols = f"{userid_col}, {name_col}" + (f", {dept_id_col}" if dept_id_col else "")
    try:
        rows = conn.execute(f"SELECT {select_cols} FROM USERINFO").fetchall()
    except sqlite3.OperationalError:
        return []

    employees = []
    for row in rows:
        uid = str(row[0]).strip() if row[0] is not None else ''
        name = (row[1] or '').strip()
        if not uid or not name:
            continue
        dept = ''
        if dept_id_col and len(row) > 2 and row[2] is not None:
            dept = dept_map.get(str(row[2]), '')
        employees.append({'device_uid': uid, 'name': name, 'dept': dept})
    return employees


def read_employees_only(path):
    """يفتح ملف SQLite ويقرأ منه USERINFO/DEPARTMENTS فقط (بدون اشتراط
    وجود CHECKINOUT) - تستخدمها ميزة استيراد الموظفين عندما يتضح أن الملف
    المرفوع/المنزَّل هو فعلياً قاعدة بيانات جهاز بصمة (SQLite) بدل ملف
    Excel/CSV، فبدل رفض الاستيراد نستخرج الموظفين مباشرة من نفس الملف."""
    if not path or not os.path.exists(path):
        return {'ok': False, 'error': f'الملف غير موجود بالمسار المحدَّد: {path}'}
    try:
        conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    except Exception as e:
        return {'ok': False, 'error': f'تعذّر فتح ملف SQLite: {e}'}
    try:
        employees = read_employees(conn)
    finally:
        conn.close()
    if not employees:
        return {'ok': False, 'error': 'لم يتم العثور على جدول USERINFO (أو بياناته ناقصة) بهذا الملف SQLite - '
                                       'لا يمكن استخراج قائمة موظفين منه.'}
    return {'ok': True, 'employees': employees}


def read_source(path):
    """يفتح ملف SQLite ويقرأ منه كل ما يلزم بقراءة واحدة (يُغلَق الملف
    فوراً بعدها): قائمة الموظفين المحتمَلين (USERINFO/DEPARTMENTS) وسجلات
    CHECKINOUT الخام. يُرجع dict: {ok, employees, raw_rows, raw_count} أو
    {ok: False, error}."""
    if not path or not os.path.exists(path):
        return {'ok': False, 'error': f'الملف غير موجود بالمسار المحدَّد: {path}'}

    try:
        conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    except Exception as e:
        return {'ok': False, 'error': f'تعذّر فتح ملف SQLite: {e}'}

    try:
        if not _table_exists(conn, 'CHECKINOUT'):
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
            return {'ok': False, 'error': 'لم يتم العثور على جدول CHECKINOUT بهذا الملف - '
                                           f'الجداول الموجودة: {", ".join(tables) if tables else "لا يوجد"}'}

        employees = read_employees(conn)

        try:
            raw_rows = conn.execute("SELECT USERID, CHECKTIME, CHECKTYPE FROM CHECKINOUT").fetchall()
        except sqlite3.OperationalError as e:
            return {'ok': False, 'error': f'تعذّر قراءة جدول CHECKINOUT: {e}'}
    finally:
        conn.close()

    return {'ok': True, 'employees': employees, 'raw_rows': raw_rows, 'raw_count': len(raw_rows)}


def aggregate_punches(raw_rows, uid_to_employee, date_from=None, date_to=None):
    """يجمّع سجلات CHECKINOUT الخام (من read_source) لكل (موظف، تاريخ) -
    أول/آخر بصمة باليوم، بعد فلترة الفترة الزمنية (لو محدَّدة) والمطابقة
    بموظفي النظام (uid_to_employee: device_uid -> name). يُرجع dict:
    {ok, rows, unmatched_uids, skipped_bad_time} أو {ok: False, error}.

    ===== محسَّنة للأداء: أجهزة البصمة تراكم غالباً مئات الآلاف/ملايين
    السجلات على مدى سنوات، وكان الإصدار السابق يمرّ عليها سجل-سجل
    بحلقة بايثون عادية، ويستدعي pd.to_datetime() لكل سجل على حدة (حمل
    استدعاء دالة ضخم يتكرر ملايين المرات) - وهذا يحصل حتى لو المستخدم
    حدَّد فترة زمنية ضيقة، لأن فلترة التاريخ كانت تتم بعد التفسير لكل
    سجل بدل قبله. الحل: نبني DataFrame واحد ونستخدم عمليات pandas
    المجمَّعة (vectorized) بدل الحلقة - فرق قد يصل لعشرات/مئات
    الأضعاف بالسرعة على ملفات كبيرة =====
    """
    uid_to_employee = uid_to_employee or {}

    parsed_from = parsed_to = None
    if date_from:
        try:
            parsed_from = datetime.strptime(date_from[:10], '%Y-%m-%d')
        except ValueError:
            return {'ok': False, 'error': f'صيغة تاريخ "من" غير صحيحة: {date_from}'}
    if date_to:
        try:
            parsed_to = datetime.strptime(date_to[:10], '%Y-%m-%d') + timedelta(days=1) - timedelta(seconds=1)
        except ValueError:
            return {'ok': False, 'error': f'صيغة تاريخ "إلى" غير صحيحة: {date_to}'}

    if not raw_rows:
        return {'ok': True, 'rows': [], 'unmatched_uids': [], 'skipped_bad_time': 0}

    df = pd.DataFrame(raw_rows, columns=['userid', 'checktime', 'checktype'])
    df['uid'] = df['userid'].astype(str).str.strip()

    # ===== نستبعد أرقام البصمة غير المطابَقة لأي موظف قبل أي تفسير
    # تاريخ - غالباً نسبة كبيرة من السجلات الخام (موظفين سابقين/محذوفين
    # بالجهاز) فلا داعي لإهدار وقت بتفسير وقتها إطلاقاً =====
    df['name'] = df['uid'].map(uid_to_employee)
    unmatched_mask = df['name'].isna()
    unmatched_uids = set(df.loc[unmatched_mask, 'uid'])
    df = df.loc[~unmatched_mask]

    if df.empty:
        return {'ok': True, 'rows': [], 'unmatched_uids': sorted(unmatched_uids), 'skipped_bad_time': 0}

    # ===== تفسير كل الأوقات دفعة واحدة (vectorized) بدل سجل-سجل =====
    df['checktime_parsed'] = pd.to_datetime(df['checktime'], errors='coerce')
    bad_mask = df['checktime_parsed'].isna()
    skipped_bad_time = int(bad_mask.sum())
    df = df.loc[~bad_mask]

    if parsed_from:
        df = df.loc[df['checktime_parsed'] >= parsed_from]
    if parsed_to:
        df = df.loc[df['checktime_parsed'] <= parsed_to]

    if df.empty:
        return {'ok': True, 'rows': [], 'unmatched_uids': sorted(unmatched_uids), 'skipped_bad_time': skipped_bad_time}

    df['date_str'] = df['checktime_parsed'].dt.strftime('%Y-%m-%d')

    rows = []
    for (uid, date_str), grp in df.groupby(['uid', 'date_str'], sort=False):
        stamps = grp['checktime_parsed'].sort_values()
        name = uid_to_employee[uid]
        time_in = stamps.iloc[0].strftime('%H:%M:%S')
        time_out = stamps.iloc[-1].strftime('%H:%M:%S') if len(stamps) > 1 else ''
        rows.append({'name': name, 'date': date_str, 'time_in': time_in, 'time_out': time_out})

    return {'ok': True, 'rows': rows, 'unmatched_uids': sorted(unmatched_uids), 'skipped_bad_time': skipped_bad_time}


def import_from_sqlite(path, date_from=None, date_to=None, uid_to_employee=None):
    """توافقية مع الاستدعاء القديم (بدون إنشاء موظفين تلقائياً) - يقرأ
    الملف ويجمّع البصمات بخطوة واحدة. يُرجع dict: {ok, rows, unmatched_uids,
    raw_count, skipped_bad_time, employees} أو {ok: False, error}."""
    source = read_source(path)
    if not source.get('ok'):
        return source
    result = aggregate_punches(source['raw_rows'], uid_to_employee, date_from, date_to)
    if not result.get('ok'):
        return result
    result['raw_count'] = source['raw_count']
    result['employees'] = source['employees']
    return result
