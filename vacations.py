"""
الإجازات وأرصدتها (بدون أي احتساب مالي):
• أنواع إجازات تحدّدها الإدارة: الرصيد السنوي بالأيام (0 = بلا حد)، مدفوعة أم لا (معلومة فقط)، هل تحتاج موافقة،
  وهل يطلبها الموظف من التطبيق. رصيد خاص لموظف معيّن يتجاوز رصيد النوع.
• الأيام تُحسب أيام عمل فقط (بلا الجمعة، والسبت إن لم يكن له دوام، والعطل الرسمية).
• الموظف يطلب من تطبيق Check-in، والإدارة توافق/ترفض (أو تُدخل إجازة مباشرة). الإجازة المعتمدة تظهر في التقارير
  باسمها («إجازة: سنوية») بدل «غائب»، حتى لو لم تكن في ذلك اليوم أي بصمة.
• الخيار كله يُفعَّل أو يُعطَّل من الإعدادات (vacations_enabled)، وطلب الموظف بخيار مستقل (vacations_employee_request).
"""
from datetime import date as _date, datetime, timedelta

from flask import Blueprint, jsonify, request, session

import db
from mobile import (_me_json, admin_required, now_local, _employee_scope_ok, _audit_emp,
                    push_to_employee, schedule_analysis)

bp = Blueprint('vacations', __name__)
STATUS_LABEL = {'pending': 'بانتظار الموافقة', 'approved': 'معتمدة', 'rejected': 'مرفوضة', 'cancelled': 'ملغاة'}
MAX_SPAN_DAYS = 90


def init_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS vacation_types (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        quota_days REAL NOT NULL DEFAULT 0,        -- الرصيد السنوي (0 = بلا حد)
        paid INTEGER NOT NULL DEFAULT 1,           -- معلومة فقط (لا احتساب مالي)
        requires_approval INTEGER NOT NULL DEFAULT 1,
        employee_request INTEGER NOT NULL DEFAULT 1,
        active INTEGER NOT NULL DEFAULT 1,
        sort INTEGER NOT NULL DEFAULT 0
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS vacation_quota (
        employee_id INTEGER NOT NULL, type_id INTEGER NOT NULL, year INTEGER NOT NULL, days REAL NOT NULL,
        PRIMARY KEY (employee_id, type_id, year)
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS vacations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL, name TEXT NOT NULL, dept TEXT,
        type_id INTEGER NOT NULL, type_name TEXT,
        date_from TEXT NOT NULL, date_to TEXT NOT NULL, days REAL NOT NULL DEFAULT 0,
        reason TEXT, status TEXT NOT NULL DEFAULT 'pending', source TEXT NOT NULL DEFAULT 'employee',
        created_at TEXT NOT NULL, decided_by TEXT, decided_at TEXT, decision_note TEXT
    )''')
    conn.execute("CREATE INDEX IF NOT EXISTS ix_vac_emp ON vacations(employee_id, status, date_from)")
    if not conn.execute("SELECT 1 FROM vacation_types").fetchone():
        # أنواع مبدئية — الأرصدة قابلة للتعديل من صفحة «الإجازات» حسب سياستكم وقانون العمل
        for i, (n, q, paid) in enumerate((('سنوية', 14, 1), ('مرضية', 14, 1), ('بدون راتب', 0, 0))):
            conn.execute("INSERT INTO vacation_types (name, quota_days, paid, sort) VALUES (?, ?, ?, ?)", (n, q, paid, i))


def enabled(cfg=None):
    cfg = cfg or db.get_all_settings()
    return cfg.get('vacations_enabled', '1') == '1'


# ----------------------------- أدوات -----------------------------
def _d(s):
    return datetime.strptime(str(s)[:10], '%Y-%m-%d').date()


def work_days(conn, d1, d2, cfg=None):
    """أيام العمل بين تاريخين (شاملة): بلا الجمعة، والسبت إن لم يكن له دوام، والعطل الرسمية"""
    cfg = cfg or db.get_all_settings()
    sat_work = cfg.get('sat_time_enabled') == '1'
    hol = {r['date'] for r in conn.execute("SELECT date FROM official_holidays WHERE date >= ? AND date <= ?",
                                           (d1.isoformat(), d2.isoformat()))}
    out, d = [], d1
    while d <= d2:
        wd = d.weekday()
        if wd != 4 and not (wd == 5 and not sat_work) and d.isoformat() not in hol:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def approved_days(conn):
    """{(اسم الموظف، التاريخ): اسم نوع الإجازة} لكل أيام الإجازات المعتمدة — يستخدمها التحليل"""
    cfg = db.get_all_settings()
    if not enabled(cfg):
        return {}
    out = {}
    for v in conn.execute("SELECT name, type_name, date_from, date_to FROM vacations WHERE status = 'approved'"):
        try:
            for day in work_days(conn, _d(v['date_from']), _d(v['date_to']), cfg):
                out[(v['name'], day)] = v['type_name'] or 'إجازة'
        except ValueError:
            continue
    return out


def _quota(conn, emp_id, t, year):
    r = conn.execute("SELECT days FROM vacation_quota WHERE employee_id = ? AND type_id = ? AND year = ?",
                     (emp_id, t['id'], year)).fetchone()
    return float(r['days']) if r else float(t['quota_days'] or 0)


def _used(conn, emp_id, type_id, year, statuses=('approved',), exclude_id=None):
    """أيام مستخدمة من نوع في سنة (تُقسم الإجازة الممتدة بين سنتين على أيامها)"""
    cfg = db.get_all_settings()
    total = 0
    q = f"SELECT id, date_from, date_to FROM vacations WHERE employee_id = ? AND type_id = ? AND status IN ({','.join('?' * len(statuses))})"
    for v in conn.execute(q, [emp_id, type_id, *statuses]):
        if exclude_id and v['id'] == exclude_id:
            continue
        total += sum(1 for d in work_days(conn, _d(v['date_from']), _d(v['date_to']), cfg) if d[:4] == str(year))
    return total


def balances(conn, emp_id, year):
    out = []
    for t in conn.execute("SELECT * FROM vacation_types WHERE active = 1 ORDER BY sort, id"):
        quota = _quota(conn, emp_id, t, year)
        used = _used(conn, emp_id, t['id'], year)
        pending = _used(conn, emp_id, t['id'], year, ('pending',))
        out.append({'type_id': t['id'], 'name': t['name'], 'quota': quota, 'unlimited': quota <= 0, 'used': used,
                    'pending': pending, 'left': None if quota <= 0 else max(0, quota - used),
                    'employee_request': bool(t['employee_request']), 'paid': bool(t['paid'])})
    return out


def _row(r):
    x = dict(r)
    x['status_label'] = STATUS_LABEL.get(x['status'], x['status'])
    return x


def _validate(conn, emp, type_id, d_from, d_to, exclude_id=None):
    """يرجع (خطأ، النوع، الأيام)"""
    t = conn.execute("SELECT * FROM vacation_types WHERE id = ? AND active = 1", (type_id,)).fetchone()
    if not t:
        return 'اختر نوع الإجازة', None, None
    try:
        a, b = _d(d_from), _d(d_to)
    except ValueError:
        return 'اختر تاريخ البداية والنهاية', None, None
    if b < a:
        return 'تاريخ النهاية قبل البداية', None, None
    if (b - a).days > MAX_SPAN_DAYS:
        return f'أقصى مدة للطلب الواحد {MAX_SPAN_DAYS} يوماً', None, None
    days = work_days(conn, a, b)
    if not days:
        return 'الفترة المختارة لا تتضمن أيام عمل', None, None
    clash = conn.execute("SELECT id FROM vacations WHERE employee_id = ? AND status IN ('pending', 'approved') AND id != ? "
                         "AND date_from <= ? AND date_to >= ?", (emp['id'], exclude_id or 0, b.isoformat(), a.isoformat())).fetchone()
    if clash:
        return 'لديك إجازة أو طلب آخر يتداخل مع هذه الفترة', None, None
    for year in sorted({d[:4] for d in days}):
        quota = _quota(conn, emp['id'], t, int(year))
        if quota > 0:
            need = sum(1 for d in days if d[:4] == year)
            have = quota - _used(conn, emp['id'], t['id'], int(year), ('approved', 'pending'), exclude_id)
            if need > have:
                return f"الرصيد غير كافٍ: المتبقي من «{t['name']}» لسنة {year} هو {max(0, have):g} يوم والمطلوب {need}", None, None
    return None, t, len(days)


def _notify_emp(conn, emp_id, title, body):
    now = now_local().strftime('%Y-%m-%d %H:%M:%S')
    conn.execute("INSERT INTO employee_notifications (employee_id, title, body, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
                 (emp_id, title, body, session.get('username', '') or 'النظام', now))
    try:
        push_to_employee(conn, emp_id, title, body)
    except Exception:   # noqa: BLE001
        pass


# ----------------------------- تطبيق الموظف -----------------------------
@bp.route('/me/api/vacations')
@_me_json
def me_vacations(conn, acc, emp, cfg):
    if not enabled(cfg):
        return jsonify({'ok': True, 'enabled': False})
    year = now_local().year
    rows = [_row(r) for r in conn.execute("SELECT * FROM vacations WHERE employee_id = ? ORDER BY date_from DESC LIMIT 40", (emp['id'],))]
    return jsonify({'ok': True, 'enabled': True, 'can_request': cfg.get('vacations_employee_request', '1') == '1',
                    'year': year, 'balances': balances(conn, emp['id'], year), 'rows': rows})


@bp.route('/me/api/vacations', methods=['POST'])
@_me_json
def me_vacation_request(conn, acc, emp, cfg):
    if not enabled(cfg) or cfg.get('vacations_employee_request', '1') != '1':
        return jsonify({'ok': False, 'error': 'طلب الإجازة من التطبيق غير مفعّل — راجع الإدارة'}), 403
    d = request.get_json(silent=True) or {}
    t = conn.execute("SELECT * FROM vacation_types WHERE id = ?", (d.get('type_id'),)).fetchone()
    if t and not t['employee_request']:
        return jsonify({'ok': False, 'error': 'هذا النوع تُدخله الإدارة فقط'}), 400
    try:
        if _d(d.get('date_from')) < now_local().date() - timedelta(days=30):
            return jsonify({'ok': False, 'error': 'لا يمكن طلب إجازة لتاريخ مضى عليه أكثر من 30 يوماً'}), 400
    except ValueError:
        pass
    err, t, days = _validate(conn, emp, d.get('type_id'), d.get('date_from'), d.get('date_to'))
    if err:
        return jsonify({'ok': False, 'error': err}), 400
    reason = (d.get('reason') or '').strip()[:300]
    status = 'pending' if t['requires_approval'] else 'approved'
    now = now_local().strftime('%Y-%m-%d %H:%M:%S')
    conn.execute("INSERT INTO vacations (employee_id, name, dept, type_id, type_name, date_from, date_to, days, reason, status, source, created_at) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'employee', ?)",
                 (emp['id'], emp['name'], emp['dept'] or '', t['id'], t['name'], d['date_from'][:10], d['date_to'][:10], days,
                  reason, status, now))
    try:
        import admin_notes
        admin_notes.add_alert(conn, 'vacation_request', f"طلب إجازة {t['name']}: {emp['name']}",
                              f"{d['date_from'][:10]} — {d['date_to'][:10]} ({days} يوم)" + (f" — {reason}" if reason else ''),
                              '/dashboard#vacations', audience='staff')
    except Exception:   # noqa: BLE001
        pass
    conn.commit()
    if status == 'approved':
        schedule_analysis(1)
    return jsonify({'ok': True, 'message': f'أُرسل طلب الإجازة ({days} يوم عمل)' if status == 'pending' else f'سُجّلت الإجازة ({days} يوم عمل)'})


@bp.route('/me/api/vacations/cancel', methods=['POST'])
@_me_json
def me_vacation_cancel(conn, acc, emp, cfg):
    vid = (request.get_json(silent=True) or {}).get('id')
    n = conn.execute("UPDATE vacations SET status = 'cancelled' WHERE id = ? AND employee_id = ? AND status = 'pending'",
                     (vid, emp['id'])).rowcount
    conn.commit()
    return jsonify({'ok': bool(n), 'error': '' if n else 'يمكن إلغاء الطلبات التي بانتظار الموافقة فقط'})


# ----------------------------- لوحة الإدارة -----------------------------
def _can_edit():
    return session.get('role') != 'viewer'


@bp.route('/api/vacations')
@admin_required
def api_vacations():
    a = request.args
    conn = db.get_db()
    try:
        q, p = "SELECT * FROM vacations WHERE 1=1", []
        if a.get('from'):
            q += " AND date_to >= ?"; p.append(a['from'][:10])
        if a.get('to'):
            q += " AND date_from <= ?"; p.append(a['to'][:10])
        if a.get('status'):
            q += " AND status = ?"; p.append(a['status'])
        if a.get('type_id'):
            q += " AND type_id = ?"; p.append(a['type_id'])
        rows = [_row(r) for r in conn.execute(q + " ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, date_from DESC LIMIT 2000", p)
                if _employee_scope_ok(r['dept'])]
        pending = sum(1 for r in conn.execute("SELECT dept FROM vacations WHERE status = 'pending'") if _employee_scope_ok(r['dept']))
        types = [dict(r) for r in conn.execute("SELECT * FROM vacation_types ORDER BY sort, id")]
        return jsonify({'ok': True, 'rows': rows, 'pending': pending, 'types': types, 'enabled': enabled()})
    finally:
        conn.close()


@bp.route('/api/vacations', methods=['POST'])
@admin_required
def api_vacation_add():
    """إجازة تُدخلها الإدارة مباشرة (معتمدة)"""
    if not _can_edit():
        return jsonify({'ok': False, 'error': 'صلاحيتك اطّلاع فقط'}), 403
    d = request.get_json(silent=True) or {}
    conn = db.get_db()
    try:
        emp = conn.execute("SELECT * FROM employees WHERE name = ? AND active = 1", ((d.get('name') or '').strip(),)).fetchone()
        if not emp or not _employee_scope_ok(emp['dept']):
            return jsonify({'ok': False, 'error': 'اختر موظفاً من القائمة'}), 400
        err, t, days = _validate(conn, emp, d.get('type_id'), d.get('date_from'), d.get('date_to'))
        if err and not (d.get('force') and 'الرصيد' in err):
            return jsonify({'ok': False, 'error': err, 'can_force': 'الرصيد' in err}), 400
        if err:   # تجاوز الرصيد بموافقة صريحة من الإدارة
            t = conn.execute("SELECT * FROM vacation_types WHERE id = ?", (d.get('type_id'),)).fetchone()
            days = len(work_days(conn, _d(d['date_from']), _d(d['date_to'])))
        now = now_local().strftime('%Y-%m-%d %H:%M:%S')
        reason = (d.get('reason') or '').strip()[:300]
        conn.execute("INSERT INTO vacations (employee_id, name, dept, type_id, type_name, date_from, date_to, days, reason, status, source, "
                     "created_at, decided_by, decided_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'approved', 'admin', ?, ?, ?)",
                     (emp['id'], emp['name'], emp['dept'] or '', t['id'], t['name'], d['date_from'][:10], d['date_to'][:10], days,
                      reason, now, session.get('username', ''), now))
        _audit_emp(conn, 'vacation_add', 'vacations', emp['name'], f"{t['name']} {d['date_from'][:10]}—{d['date_to'][:10]} ({days})"
                   + (' — تجاوز الرصيد' if err else ''))
        _notify_emp(conn, emp['id'], f"سُجّلت لك إجازة {t['name']}", f"{d['date_from'][:10]} — {d['date_to'][:10]} ({days} يوم عمل)")
        conn.commit()
        schedule_analysis(1)
        return jsonify({'ok': True, 'days': days})
    finally:
        conn.close()


@bp.route('/api/vacations/decide', methods=['POST'])
@admin_required
def api_vacations_decide():
    if not _can_edit():
        return jsonify({'ok': False, 'error': 'صلاحيتك اطّلاع فقط'}), 403
    d = request.get_json(silent=True) or {}
    ids = [int(i) for i in (d.get('ids') or []) if str(i).isdigit()]
    action, note = d.get('action'), (d.get('note') or '').strip()[:300]
    if not ids or action not in ('approve', 'reject', 'cancel'):
        return jsonify({'ok': False, 'error': 'حدّد طلباً واحداً على الأقل'}), 400
    conn = db.get_db()
    try:
        now = now_local().strftime('%Y-%m-%d %H:%M:%S')
        n, errors = 0, []
        want = ('pending',) if action != 'cancel' else ('pending', 'approved')
        for r in conn.execute(f"SELECT * FROM vacations WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall():
            if r['status'] not in want or not _employee_scope_ok(r['dept']):
                continue
            if action == 'approve':
                emp = conn.execute("SELECT * FROM employees WHERE id = ?", (r['employee_id'],)).fetchone()
                err, _t, _days = _validate(conn, emp, r['type_id'], r['date_from'], r['date_to'], exclude_id=r['id'])
                if err and not d.get('force'):
                    errors.append(f"{r['name']}: {err}")
                    continue
            st = {'approve': 'approved', 'reject': 'rejected', 'cancel': 'cancelled'}[action]
            conn.execute("UPDATE vacations SET status = ?, decided_by = ?, decided_at = ?, decision_note = ? WHERE id = ?",
                         (st, session.get('username', ''), now, note, r['id']))
            what = f"{r['type_name']}: {r['date_from']} — {r['date_to']} ({r['days']:g} يوم)"
            _audit_emp(conn, f'vacation_{action}', 'vacations', r['name'], what + (f' — {note}' if note else ''))
            title = {'approved': 'تمت الموافقة على الإجازة', 'rejected': 'رُفض طلب الإجازة', 'cancelled': 'أُلغيت الإجازة'}[st]
            _notify_emp(conn, r['employee_id'], title, what + (f"\nملاحظة: {note}" if note else ''))
            n += 1
        conn.commit()
        if n and action in ('approve', 'cancel'):
            schedule_analysis(1)
        return jsonify({'ok': True, 'count': n, 'errors': errors})
    finally:
        conn.close()


@bp.route('/api/vacation-types', methods=['POST'])
@admin_required
def api_vacation_types():
    if session.get('role') != 'admin':
        return jsonify({'ok': False, 'error': 'تعديل أنواع الإجازات لمدير النظام فقط'}), 403
    d = request.get_json(silent=True) or {}
    name = (d.get('name') or '').strip()[:60]
    if not name:
        return jsonify({'ok': False, 'error': 'اكتب اسم النوع'}), 400
    try:
        quota = max(0.0, float(d.get('quota_days') or 0))
    except (TypeError, ValueError):
        quota = 0.0
    vals = (name, quota, 1 if d.get('paid') else 0, 1 if d.get('requires_approval', True) else 0,
            1 if d.get('employee_request', True) else 0, 1 if d.get('active', True) else 0)
    conn = db.get_db()
    try:
        if d.get('id'):
            conn.execute("UPDATE vacation_types SET name = ?, quota_days = ?, paid = ?, requires_approval = ?, employee_request = ?, active = ? "
                         "WHERE id = ?", vals + (d['id'],))
            conn.execute("UPDATE vacations SET type_name = ? WHERE type_id = ?", (name, d['id']))
        else:
            conn.execute("INSERT INTO vacation_types (name, quota_days, paid, requires_approval, employee_request, active, sort) "
                         "VALUES (?, ?, ?, ?, ?, ?, (SELECT COALESCE(MAX(sort), 0) + 1 FROM vacation_types))", vals)
        _audit_emp(conn, 'vacation_type_save', 'vacation_types', '', f"{name}: رصيد {quota:g}")
        conn.commit()
        if d.get('id'):
            schedule_analysis(1)
        return jsonify({'ok': True})
    except Exception as e:   # noqa: BLE001 — اسم مكرر
        return jsonify({'ok': False, 'error': 'يوجد نوع بنفس الاسم' if 'UNIQUE' in str(e) else str(e)}), 400
    finally:
        conn.close()


@bp.route('/api/vacations/balances')
@admin_required
def api_vacation_balances():
    try:
        year = int(request.args.get('year') or now_local().year)
    except ValueError:
        year = now_local().year
    conn = db.get_db()
    try:
        types = [dict(r) for r in conn.execute("SELECT * FROM vacation_types WHERE active = 1 ORDER BY sort, id")]
        rows = []
        for e in conn.execute("SELECT id, name, dept FROM employees WHERE active = 1 ORDER BY dept, name"):
            if not _employee_scope_ok(e['dept']):
                continue
            rows.append({'id': e['id'], 'name': e['name'], 'dept': e['dept'] or '', 'b': balances(conn, e['id'], year)})
        return jsonify({'ok': True, 'year': year, 'types': types, 'rows': rows})
    finally:
        conn.close()


@bp.route('/api/vacations/quota', methods=['POST'])
@admin_required
def api_vacation_quota():
    """رصيد خاص لموظف (نوع/سنة) — فارغ = يعود لرصيد النوع"""
    if session.get('role') != 'admin':
        return jsonify({'ok': False, 'error': 'تعديل الأرصدة لمدير النظام فقط'}), 403
    d = request.get_json(silent=True) or {}
    conn = db.get_db()
    try:
        emp = conn.execute("SELECT * FROM employees WHERE id = ?", (d.get('employee_id'),)).fetchone()
        if not emp:
            return jsonify({'ok': False, 'error': 'الموظف غير موجود'}), 400
        if d.get('days') in (None, ''):
            conn.execute("DELETE FROM vacation_quota WHERE employee_id = ? AND type_id = ? AND year = ?",
                         (emp['id'], d.get('type_id'), d.get('year')))
        else:
            conn.execute("INSERT INTO vacation_quota (employee_id, type_id, year, days) VALUES (?, ?, ?, ?) "
                         "ON CONFLICT(employee_id, type_id, year) DO UPDATE SET days = excluded.days",
                         (emp['id'], d.get('type_id'), d.get('year'), max(0.0, float(d['days']))))
        _audit_emp(conn, 'vacation_quota', 'vacation_quota', emp['name'], f"نوع {d.get('type_id')} سنة {d.get('year')}: {d.get('days')}")
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()
