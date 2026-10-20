"""
طلبات تصحيح الحضور/الانصراف من تطبيق الموظف:
• الموظف الذي نسي تسجيل الانصراف (أو الحضور) يرسل طلباً بالوقت الصحيح والسبب من تبويب «الشهر».
• يقترح التطبيق الأيام الناقصة تلقائياً («بدون سجل انصراف» / «بدون سجل دخول» في آخر 14 يوماً).
• توافق الإدارة أو ترفض من «الإدخال اليدوي» (أو بإشعار تطبيق الإدارة)؛ الموافقة تُنشئ/تحدّث إدخالاً يدوياً
  لذلك اليوم، وتُسجَّل في سجل التدقيق، ويصل الموظف إشعار بالقرار، ويُعاد التحليل.
"""
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request, session

import db
from mobile import (_me_json, admin_required, now_local, _employee_scope_ok, _audit_emp,
                    push_to_employee, schedule_analysis)

bp = Blueprint('corrections', __name__)
KIND_LABEL = {'in': 'حضور', 'out': 'انصراف', 'both': 'حضور وانصراف'}
STATUS_LABEL = {'pending': 'بانتظار الموافقة', 'approved': 'تمت الموافقة', 'rejected': 'مرفوض', 'cancelled': 'ألغاه الموظف'}
MAX_DAYS_BACK = 30


def init_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS correction_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        name TEXT NOT NULL, dept TEXT,
        date TEXT NOT NULL,
        kind TEXT NOT NULL,                 -- in / out / both
        time_in TEXT, time_out TEXT,
        reason TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        decided_by TEXT, decided_at TEXT, decision_note TEXT
    )''')
    conn.execute("CREATE INDEX IF NOT EXISTS ix_corr_status ON correction_requests(status, date)")


def _hm(v):
    v = (v or '').strip()[:5]
    try:
        datetime.strptime(v, '%H:%M')
        return v
    except ValueError:
        return None


def _row(r):
    x = dict(r)
    x['kind_label'] = KIND_LABEL.get(x['kind'], x['kind'])
    x['status_label'] = STATUS_LABEL.get(x['status'], x['status'])
    return x


def _notify(conn, emp_id, title, body):
    now = now_local().strftime('%Y-%m-%d %H:%M:%S')
    conn.execute("INSERT INTO employee_notifications (employee_id, title, body, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
                 (emp_id, title, body, session.get('username', '') or 'النظام', now))
    try:
        push_to_employee(conn, emp_id, title, body)
    except Exception:   # noqa: BLE001
        pass


# ----------------------------- تطبيق الموظف -----------------------------
@bp.route('/me/api/corrections')
@_me_json
def me_corrections(conn, acc, emp, cfg):
    today = now_local().date()
    since = (today - timedelta(days=14)).strftime('%Y-%m-%d')
    rows = [_row(r) for r in conn.execute(
        "SELECT * FROM correction_requests WHERE employee_id = ? ORDER BY id DESC LIMIT 30", (emp['id'],))]
    asked = {r['date'] for r in rows if r['status'] in ('pending', 'approved')}
    missing = []
    for r in conn.execute("SELECT date, time_in, time_out, status, out_flag FROM report_cache WHERE name = ? AND date >= ? "
                          "AND date < ? AND (COALESCE(out_flag, '') != '' OR status = 'بدون سجل دخول') ORDER BY date DESC",
                          (emp['name'], since, today.strftime('%Y-%m-%d'))):
        if r['date'] in asked:
            continue
        kind = 'in' if r['status'] == 'بدون سجل دخول' else 'out'
        missing.append({'date': r['date'], 'kind': kind, 'kind_label': KIND_LABEL[kind],
                        'time_in': r['time_in'] or '', 'auto': r['out_flag'] == 'auto'})
    return jsonify({'ok': True, 'rows': rows, 'missing': missing, 'max_days': MAX_DAYS_BACK})


@bp.route('/me/api/corrections', methods=['POST'])
@_me_json
def me_correction_request(conn, acc, emp, cfg):
    d = request.get_json(silent=True) or {}
    date = (d.get('date') or '').strip()[:10]
    kind = d.get('kind') if d.get('kind') in KIND_LABEL else None
    t_in, t_out = _hm(d.get('time_in')), _hm(d.get('time_out'))
    reason = (d.get('reason') or '').strip()[:300]
    try:
        day = datetime.strptime(date, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'ok': False, 'error': 'اختر التاريخ'}), 400
    today = now_local().date()
    if day > today or (today - day).days > MAX_DAYS_BACK:
        return jsonify({'ok': False, 'error': f'يمكن طلب التصحيح لآخر {MAX_DAYS_BACK} يوماً فقط'}), 400
    if not kind:
        return jsonify({'ok': False, 'error': 'اختر نوع التصحيح'}), 400
    if kind in ('in', 'both') and not t_in:
        return jsonify({'ok': False, 'error': 'اكتب وقت الحضور الصحيح'}), 400
    if kind in ('out', 'both') and not t_out:
        return jsonify({'ok': False, 'error': 'اكتب وقت الانصراف الصحيح'}), 400
    if kind == 'both' and t_out <= t_in:
        return jsonify({'ok': False, 'error': 'وقت الانصراف يجب أن يكون بعد الحضور'}), 400
    if day == today and max(t_in or '', t_out or '') > now_local().strftime('%H:%M'):
        return jsonify({'ok': False, 'error': 'لا يمكن طلب وقت لم يأتِ بعد'}), 400
    if len(reason) < 3:
        return jsonify({'ok': False, 'error': 'اكتب سبب التصحيح'}), 400
    if conn.execute("SELECT 1 FROM correction_requests WHERE employee_id = ? AND date = ? AND status = 'pending'",
                    (emp['id'], date)).fetchone():
        return jsonify({'ok': False, 'error': 'لديك طلب تصحيح لهذا اليوم بانتظار الموافقة'}), 400
    conn.execute("INSERT INTO correction_requests (employee_id, name, dept, date, kind, time_in, time_out, reason, created_at) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (emp['id'], emp['name'], emp['dept'] or '', date, kind,
                  t_in if kind != 'out' else None, t_out if kind != 'in' else None, reason,
                  now_local().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    return jsonify({'ok': True, 'message': 'أُرسل طلب التصحيح إلى الإدارة — يصلك إشعار بالقرار'})


@bp.route('/me/api/corrections/cancel', methods=['POST'])
@_me_json
def me_correction_cancel(conn, acc, emp, cfg):
    cid = (request.get_json(silent=True) or {}).get('id')
    n = conn.execute("UPDATE correction_requests SET status = 'cancelled' WHERE id = ? AND employee_id = ? AND status = 'pending'",
                     (cid, emp['id'])).rowcount
    conn.commit()
    return jsonify({'ok': bool(n), 'error': '' if n else 'لا يمكن إلغاء هذا الطلب'})


# ----------------------------- لوحة الإدارة -----------------------------
@bp.route('/api/corrections')
@admin_required
def api_corrections():
    status = request.args.get('status') or 'pending'
    conn = db.get_db()
    try:
        q, params = "SELECT * FROM correction_requests", []
        if status != 'all':
            q += " WHERE status = ?"
            params.append(status)
        q += " ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, date DESC, id DESC LIMIT 1000"
        rows = [_row(r) for r in conn.execute(q, params) if _employee_scope_ok(r['dept'])]
        # المسجّل حالياً لذلك اليوم (للمقارنة قبل الموافقة)
        for r in rows:
            c = conn.execute("SELECT time_in, time_out FROM report_cache WHERE name = ? AND date = ?", (r['name'], r['date'])).fetchone()
            r['current_in'], r['current_out'] = (c['time_in'] or '', c['time_out'] or '') if c else ('', '')
        pending = sum(1 for r in conn.execute("SELECT dept FROM correction_requests WHERE status = 'pending'") if _employee_scope_ok(r['dept']))
        return jsonify({'ok': True, 'rows': rows, 'pending': pending})
    finally:
        conn.close()


@bp.route('/api/corrections/decide', methods=['POST'])
@admin_required
def api_corrections_decide():
    if session.get('role') == 'viewer':
        return jsonify({'ok': False, 'error': 'صلاحيتك اطّلاع فقط'}), 403
    d = request.get_json(silent=True) or {}
    ids = [int(i) for i in (d.get('ids') or []) if str(i).isdigit()]
    action, note = d.get('action'), (d.get('note') or '').strip()[:300]
    if not ids or action not in ('approve', 'reject'):
        return jsonify({'ok': False, 'error': 'حدّد طلباً واحداً على الأقل'}), 400
    conn = db.get_db()
    try:
        now = now_local().strftime('%Y-%m-%d %H:%M:%S')
        n = 0
        for r in conn.execute(f"SELECT * FROM correction_requests WHERE id IN ({','.join('?' * len(ids))}) AND status = 'pending'", ids).fetchall():
            if not _employee_scope_ok(r['dept']):
                continue
            st = 'approved' if action == 'approve' else 'rejected'
            conn.execute("UPDATE correction_requests SET status = ?, decided_by = ?, decided_at = ?, decision_note = ? WHERE id = ?",
                         (st, session.get('username', ''), now, note, r['id']))
            what = f"{KIND_LABEL[r['kind']]} يوم {r['date']}: " + ' – '.join(x for x in (r['time_in'], r['time_out']) if x)
            if st == 'approved':
                # نفس «الإدخال اليدوي»: لا يمسح الوقت الآخر المسجّل لذلك اليوم
                conn.execute(
                    "INSERT INTO manual_time_entries (name, date, time_in, time_out, reason, entered_at) VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(name, date) DO UPDATE SET time_in = COALESCE(excluded.time_in, manual_time_entries.time_in), "
                    "time_out = COALESCE(excluded.time_out, manual_time_entries.time_out), reason = excluded.reason, "
                    "entered_at = excluded.entered_at",
                    (r['name'], r['date'], r['time_in'], r['time_out'], f"طلب تصحيح من الموظف: {r['reason']}"[:300], now))
            _audit_emp(conn, f'correction_{action}', 'manual_entry', r['name'], what + (f" — {note}" if note else ''))
            _notify(conn, r['employee_id'], 'تمت الموافقة على طلب التصحيح' if st == 'approved' else 'رُفض طلب التصحيح',
                    what + (f"\nملاحظة: {note}" if note else ''))
            n += 1
        conn.commit()
        if n and action == 'approve':
            schedule_analysis(1)
        return jsonify({'ok': True, 'count': n})
    finally:
        conn.close()
