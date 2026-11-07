"""المناوبات المسمّاة: مناوبات بأسماء وأوقات وأيام، تُسند إلى الموظفين لفترة (من تاريخ إلى تاريخ).

- الجدولان: shifts (الاسم، البداية، النهاية، الأيام، التفعيل) وemployee_shifts (الموظف بالاسم، المناوبة، من، إلى).
- الأولوية في الحساب (attendance_engine.analyze): إذن بوقت خاص ← **المناوبة المسمّاة** ← نظام المناوبتين
  القديم ← وقت السبت ← وقت القسم ← الوقت العام.
- «الأيام»: إن حُدّدت لا تُطبَّق المناوبة إلا فيها، ويصبح كل يوم منها يوم عمل للموظف حتى لو كان الجمعة
  أو السبت (مناوبة الحراسة مثلاً). وإن تُركت فارغة تُطبَّق في كل أيام العمل المعتادة.
- إسناد مناوبة جديدة لموظف يُغلق إسناده المفتوح السابق في اليوم الذي يسبق بدايتها؛ وعند تداخل فترتين
  يُعتمد الإسناد الأحدث بدايةً.
- الحذف المحمي: المناوبة المسندة لموظفين لا تُحذف، وتُعطَّل بدلاً من ذلك.
- بعد كل تغيير يُعاد بناء التقارير (run_full_analysis) لتظهر الأوقات الجديدة.
"""
import re
from datetime import date as _date, datetime, timedelta

from flask import Blueprint, jsonify, request, session

import db

bp = Blueprint('shifts', __name__)

# أيام الأسبوع بترقيم Python (الإثنين = 0) مرتبة من الأحد كما في التقويم المحلي
WEEKDAYS = [(6, 'الأحد'), (0, 'الإثنين'), (1, 'الثلاثاء'), (2, 'الأربعاء'), (3, 'الخميس'), (4, 'الجمعة'), (5, 'السبت')]
_TIME = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')
_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
FAR = '9999-12-31'


def init_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS shifts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        days TEXT NOT NULL DEFAULT '',
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS employee_shifts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        shift_id INTEGER NOT NULL,
        date_from TEXT NOT NULL,
        date_to TEXT,
        created_by TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_employee_shifts_name ON employee_shifts(name)")


# ---------------------------------------------------------------
#   القراءة للحساب
# ---------------------------------------------------------------
def _days(s):
    return frozenset(int(x) for x in (s or '').split(',') if x.strip().isdigit() and 0 <= int(x) <= 6)


def load(conn):
    """{اسم الموظف: [(من، إلى، البداية، النهاية، اسم المناوبة، الأيام)]} مرتبة من الأحدث بدايةً؛ المناوبات المفعّلة فقط"""
    out = {}
    for r in conn.execute("SELECT es.name, es.date_from, es.date_to, s.start_time, s.end_time, s.name AS label, s.days "
                          "FROM employee_shifts es JOIN shifts s ON s.id = es.shift_id WHERE s.active = 1 "
                          "ORDER BY es.date_from DESC, es.id DESC"):
        out.setdefault(r['name'], []).append(
            (r['date_from'], r['date_to'] or FAR, r['start_time'], r['end_time'], r['label'], _days(r['days'])))
    return out


def find(assign, name, date_str, weekday):
    """مناوبة الموظف في هذا اليوم أو None"""
    for d1, d2, start, end, label, days in (assign or {}).get(name, ()):
        if d1 <= date_str <= d2 and (not days or weekday in days):
            return start, end, label, bool(days)
    return None


# ---------------------------------------------------------------
#   الصلاحية والمساعدات
# ---------------------------------------------------------------
def _rebuild(conn):
    try:
        import app as app_module
        app_module.run_full_analysis(conn)
        conn.commit()
    except Exception:   # noqa: BLE001 — التقارير تُبنى لاحقاً من زر «تطبيق الإعدادات»
        pass


def _audit(conn, action, value, name=None):
    try:
        import app as app_module
        app_module.log_audit(conn, action, 'shift', employee_name=name, new_value=str(value)[:500])
    except Exception:   # noqa: BLE001
        pass


def _err(msg, code=400):
    return jsonify({'ok': False, 'error': msg}), code


def _guard():
    """التعديل لمن سجّل دخوله ويملك صلاحية إعدادات المؤسسة (وتُفحص أيضاً في app.enforce_role_permissions)"""
    if not session.get('user_id'):
        return _err('يرجى تسجيل الدخول أولاً', 401)
    if session.get('role') != 'admin' and not session.get('can_edit_org_settings'):
        return _err('ليس لديك صلاحية لهذا الإجراء', 403)
    return None


def _today():
    try:
        from mobile import now_local
        return now_local().strftime('%Y-%m-%d')
    except Exception:   # noqa: BLE001
        return _date.today().isoformat()


def _days_label(days):
    if not days:
        return 'أيام العمل المعتادة'
    return '، '.join(n for d, n in WEEKDAYS if d in days)


def _payload(conn):
    today = _today()
    counts = {r['shift_id']: r['n'] for r in conn.execute(
        "SELECT shift_id, COUNT(DISTINCT name) AS n FROM employee_shifts WHERE date_from <= ? AND COALESCE(date_to, ?) >= ? "
        "GROUP BY shift_id", (today, FAR, today))}
    used = {r['shift_id'] for r in conn.execute("SELECT DISTINCT shift_id FROM employee_shifts")}
    shifts = [{'id': r['id'], 'name': r['name'], 'start': r['start_time'], 'end': r['end_time'],
               'days': sorted(_days(r['days'])), 'days_label': _days_label(_days(r['days'])),
               'overnight': r['end_time'] <= r['start_time'], 'active': bool(r['active']),
               'current': counts.get(r['id'], 0), 'used': r['id'] in used}
              for r in conn.execute("SELECT * FROM shifts ORDER BY active DESC, start_time, name")]
    depts = {r['name']: r['dept'] or '' for r in conn.execute("SELECT name, dept FROM employees")}
    assignments = []
    for r in conn.execute("SELECT es.*, s.name AS shift_name, s.start_time, s.end_time, s.active AS shift_active "
                          "FROM employee_shifts es JOIN shifts s ON s.id = es.shift_id ORDER BY es.date_from DESC, es.name"):
        to = r['date_to'] or ''
        status = 'ended' if to and to < today else ('upcoming' if r['date_from'] > today else 'current')
        assignments.append({'id': r['id'], 'name': r['name'], 'dept': depts.get(r['name'], ''), 'shift_id': r['shift_id'],
                            'shift': r['shift_name'], 'time': f"{r['start_time']}–{r['end_time']}",
                            'date_from': r['date_from'], 'date_to': to, 'status': status,
                            'status_label': {'current': 'سارية', 'upcoming': 'قادمة', 'ended': 'منتهية'}[status],
                            'shift_active': bool(r['shift_active']), 'created_by': r['created_by'] or ''})
    emps = [{'name': r['name'], 'dept': r['dept'] or ''}
            for r in conn.execute("SELECT name, dept FROM employees WHERE active = 1 ORDER BY dept, name")]
    return {'ok': True, 'shifts': shifts, 'assignments': assignments, 'employees': emps, 'today': today,
            'weekdays': [{'d': d, 'name': n} for d, n in WEEKDAYS]}


# ---------------------------------------------------------------
#   الواجهة البرمجية
# ---------------------------------------------------------------
@bp.route('/api/shifts')
def api_shifts():
    if not session.get('user_id'):
        return _err('يرجى تسجيل الدخول أولاً', 401)
    conn = db.get_db()
    try:
        return jsonify(_payload(conn))
    finally:
        conn.close()


@bp.route('/api/shifts', methods=['POST'])
def api_shift_save():
    """إضافة مناوبة أو تعديلها"""
    denied = _guard()
    if denied:
        return denied
    d = request.get_json(force=True) or {}
    name = (d.get('name') or '').strip()[:80]
    start, end = (d.get('start') or '').strip(), (d.get('end') or '').strip()
    if not name:
        return _err('اكتب اسم المناوبة.')
    if not (_TIME.match(start) and _TIME.match(end)):
        return _err('حدّد وقتَي بداية المناوبة ونهايتها.')
    if start == end:
        return _err('وقت النهاية يجب أن يختلف عن وقت البداية.')
    days = ','.join(str(x) for x in sorted({int(x) for x in d.get('days') or [] if str(x).isdigit() and 0 <= int(x) <= 6}))
    sid = d.get('id')
    conn = db.get_db()
    try:
        clash = conn.execute("SELECT id FROM shifts WHERE name = ? AND id != ?", (name, sid or 0)).fetchone()
        if clash:
            return _err('توجد مناوبة بهذا الاسم.')
        if sid:
            if not conn.execute("SELECT 1 FROM shifts WHERE id = ?", (sid,)).fetchone():
                return _err('المناوبة غير موجودة.', 404)
            conn.execute("UPDATE shifts SET name = ?, start_time = ?, end_time = ?, days = ?, active = ? WHERE id = ?",
                         (name, start, end, days, 1 if d.get('active', True) else 0, sid))
            _audit(conn, 'shift_edit', f'{name} {start}–{end}')
        else:
            conn.execute("INSERT INTO shifts (name, start_time, end_time, days, active) VALUES (?, ?, ?, ?, 1)",
                         (name, start, end, days))
            _audit(conn, 'shift_add', f'{name} {start}–{end}')
        conn.commit()
        if sid:
            _rebuild(conn)
        return jsonify(_payload(conn))
    finally:
        conn.close()


@bp.route('/api/shifts/bulk', methods=['POST'])
def api_shifts_bulk():
    """تفعيل أو تعطيل أو حذف مناوبات محددة؛ المسندة لموظفين لا تُحذف بل تُعطَّل"""
    denied = _guard()
    if denied:
        return denied
    d = request.get_json(force=True) or {}
    action, ids = d.get('action'), [int(x) for x in d.get('ids') or [] if str(x).isdigit()]
    if action not in ('activate', 'deactivate', 'delete') or not ids:
        return _err('اختر الإجراء والمناوبات.')
    conn = db.get_db()
    try:
        ph = ','.join('?' * len(ids))
        warning = ''
        if action == 'delete':
            used = [r['shift_id'] for r in conn.execute(f"SELECT DISTINCT shift_id FROM employee_shifts WHERE shift_id IN ({ph})", ids)]
            free = [i for i in ids if i not in used]
            if free:
                conn.execute(f"DELETE FROM shifts WHERE id IN ({','.join('?' * len(free))})", free)
            if used:
                conn.execute(f"UPDATE shifts SET active = 0 WHERE id IN ({','.join('?' * len(used))})", used)
                warning = (f'حُذفت {len(free)}، وعُطّلت {len(used)} بدلاً من حذفها لأنها مسندة لموظفين '
                           '(احذف إسناداتها أولاً إن أردت حذفها نهائياً).')
            done = len(ids)
        else:
            conn.execute(f"UPDATE shifts SET active = ? WHERE id IN ({ph})", [1 if action == 'activate' else 0] + ids)
            done = len(ids)
        _audit(conn, f'shift_{action}', f'{done}')
        conn.commit()
        _rebuild(conn)
        out = _payload(conn)
        out.update(done=done, warning=warning)
        return jsonify(out)
    finally:
        conn.close()


@bp.route('/api/shifts/assign', methods=['POST'])
def api_shifts_assign():
    """إسناد مناوبة إلى موظف أو أكثر من تاريخ (إلى تاريخ اختياري)"""
    denied = _guard()
    if denied:
        return denied
    d = request.get_json(force=True) or {}
    names = [str(n).strip() for n in d.get('names') or [] if str(n).strip()]
    sid, d1, d2 = d.get('shift_id'), (d.get('date_from') or '').strip(), (d.get('date_to') or '').strip()
    if not names:
        return _err('اختر موظفاً واحداً على الأقل.')
    if not _DATE.match(d1):
        return _err('حدّد تاريخ بداية الإسناد.')
    if d2 and (not _DATE.match(d2) or d2 < d1):
        return _err('تاريخ النهاية يجب أن يكون بعد تاريخ البداية أو فارغاً (مستمرة).')
    conn = db.get_db()
    try:
        s = conn.execute("SELECT * FROM shifts WHERE id = ?", (sid,)).fetchone()
        if not s:
            return _err('اختر المناوبة.')
        if not s['active']:
            return _err('هذه المناوبة معطّلة؛ فعّلها أولاً.')
        known = {r['name'] for r in conn.execute("SELECT name FROM employees")}
        names = [n for n in dict.fromkeys(names) if n in known]
        if not names:
            return _err('الموظفون المحددون غير موجودين.')
        prev_day = (datetime.strptime(d1, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')
        user = session.get('username', '')
        for n in names:
            # الإسناد المفتوح السابق ينتهي في اليوم الذي يسبق الإسناد الجديد
            conn.execute("UPDATE employee_shifts SET date_to = ? WHERE name = ? AND date_to IS NULL AND date_from < ?",
                         (prev_day, n, d1))
            conn.execute("INSERT INTO employee_shifts (name, shift_id, date_from, date_to, created_by) VALUES (?, ?, ?, ?, ?)",
                         (n, s['id'], d1, d2 or None, user))
        _audit(conn, 'shift_assign', f"{s['name']}: {len(names)} — {d1}{(' → ' + d2) if d2 else ''}",
               names[0] if len(names) == 1 else None)
        conn.commit()
        _rebuild(conn)
        out = _payload(conn)
        out['done'] = len(names)
        return jsonify(out)
    finally:
        conn.close()


@bp.route('/api/shifts/assignments/bulk', methods=['POST'])
def api_assignments_bulk():
    """إنهاء إسنادات محددة اليوم أو حذفها"""
    denied = _guard()
    if denied:
        return denied
    d = request.get_json(force=True) or {}
    action, ids = d.get('action'), [int(x) for x in d.get('ids') or [] if str(x).isdigit()]
    if action not in ('end', 'delete') or not ids:
        return _err('اختر الإجراء والإسنادات.')
    conn = db.get_db()
    try:
        ph = ','.join('?' * len(ids))
        if action == 'end':
            today = _today()
            # الإسناد القادم الذي لم يبدأ بعد يُحذف؛ والساري ينتهي اليوم
            conn.execute(f"DELETE FROM employee_shifts WHERE id IN ({ph}) AND date_from > ?", ids + [today])
            conn.execute(f"UPDATE employee_shifts SET date_to = ? WHERE id IN ({ph}) AND (date_to IS NULL OR date_to > ?)",
                         [today] + ids + [today])
        else:
            conn.execute(f"DELETE FROM employee_shifts WHERE id IN ({ph})", ids)
        _audit(conn, f'shift_assign_{action}', f'{len(ids)}')
        conn.commit()
        _rebuild(conn)
        out = _payload(conn)
        out['done'] = len(ids)
        return jsonify(out)
    finally:
        conn.close()
