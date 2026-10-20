"""
شاشات العرض (للمشاهدة فقط — شاشة تلفاز في الإدارة، أو رابط لمدير):
• «لوحة الحضور»: حضور اليوم لحظياً — الحاضرون، المتأخرون، من لم يحضر، الإجازات — مع تفصيل الأقسام (أقسام محددة أو الكل).
• «الرصد المباشر»: خريطة لموظفين/أجهزة محددين فقط يُختارون عند الإنشاء — موقعهم المباشر ومسارهم.
تُنشأ من لوحة التحكم برابط سري (/display/<رمز>) لا يحتاج تسجيل دخول ولا يسمح بأي تعديل، ويمكن إيقافه
أو تغيير رمزه (فيتوقف الرابط القديم فوراً) أو حذفه. البيانات المعروضة محصورة فيما حُدّد للشاشة فقط.
"""
import json
import secrets
from datetime import datetime

from flask import Blueprint, jsonify, render_template, request, session, abort

import db
from mobile import now_local, site_rows

bp = Blueprint('displays', __name__)
KINDS = {'attendance': 'لوحة الحضور', 'tracking': 'الرصد المباشر'}
LATE = ('متأخر', 'تأخير بسيط')


def init_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS displays (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        kind TEXT NOT NULL,                 -- attendance / tracking
        token TEXT NOT NULL UNIQUE,
        config TEXT NOT NULL DEFAULT '{}',
        active INTEGER NOT NULL DEFAULT 1,
        created_by TEXT, created_at TEXT DEFAULT (datetime('now')),
        last_view_at TEXT, last_view_ip TEXT
    )''')


def _cfg(r):
    try:
        return json.loads(r['config'] or '{}')
    except ValueError:
        return {}


def _admin_only():
    if not session.get('user_id'):
        return jsonify({'ok': False, 'error': 'يرجى تسجيل الدخول أولاً'}), 401
    if session.get('role') != 'admin':
        return jsonify({'ok': False, 'error': 'إدارة شاشات العرض لمدير النظام فقط'}), 403
    return None


def _audit(conn, action, value):
    try:
        conn.execute("INSERT INTO audit_log (username, action_type, target_type, new_value, timestamp) VALUES (?, ?, ?, ?, ?)",
                     (session.get('username', ''), action, 'display', value, now_local().strftime('%Y-%m-%d %H:%M:%S')))
    except Exception:   # noqa: BLE001
        pass


# ----------------------------- إدارة الشاشات -----------------------------
@bp.route('/api/displays', methods=['GET', 'POST'])
def api_displays():
    err = _admin_only()
    if err:
        return err
    conn = db.get_db()
    try:
        if request.method == 'POST':
            d = request.get_json(silent=True) or {}
            kind = d.get('kind') if d.get('kind') in KINDS else None
            name = (d.get('name') or '').strip()[:80]
            if not kind or not name:
                return jsonify({'ok': False, 'error': 'اكتب اسماً للشاشة واختر نوعها'}), 400
            try:
                refresh = max(1, min(300, int(d.get('refresh') or (30 if kind == 'attendance' else 5))))
            except (TypeError, ValueError):
                refresh = 30 if kind == 'attendance' else 5
            cfg = {'refresh': refresh}
            if kind == 'attendance':
                cfg['depts'] = [str(x)[:80] for x in (d.get('depts') or []) if str(x).strip()][:100]
                cfg['show_names'] = bool(d.get('show_names', True))
            else:
                ids = [int(i) for i in (d.get('employees') or []) if str(i).isdigit()][:100]
                if not ids:
                    return jsonify({'ok': False, 'error': 'اختر موظفاً أو جهازاً واحداً على الأقل للرصد'}), 400
                cfg['employees'] = ids
                cfg['trail'] = bool(d.get('trail', True))
            if d.get('id'):
                conn.execute("UPDATE displays SET name = ?, kind = ?, config = ? WHERE id = ?",
                             (name, kind, json.dumps(cfg, ensure_ascii=False), d['id']))
                _audit(conn, 'display_edit', f'{name} ({KINDS[kind]})')
            else:
                conn.execute("INSERT INTO displays (name, kind, token, config, created_by) VALUES (?, ?, ?, ?, ?)",
                             (name, kind, secrets.token_urlsafe(24), json.dumps(cfg, ensure_ascii=False), session.get('username', '')))
                _audit(conn, 'display_add', f'{name} ({KINDS[kind]})')
            conn.commit()
            return jsonify({'ok': True})
        names = {r['id']: r['name'] for r in conn.execute("SELECT id, name FROM employees")}
        rows = []
        for r in conn.execute("SELECT * FROM displays ORDER BY id DESC"):
            x = dict(r)
            x['config'] = _cfg(r)
            x['kind_label'] = KINDS.get(r['kind'], r['kind'])
            x['employee_names'] = [names.get(i, '؟') for i in x['config'].get('employees', [])]
            x['url'] = request.host_url.rstrip('/') + '/display/' + r['token']
            rows.append(x)
        trackable = [dict(r) for r in conn.execute(
            "SELECT e.id, e.name, e.dept, a.always_track FROM employees e JOIN employee_accounts a ON a.employee_id = e.id "
            "WHERE e.active = 1 AND a.active = 1 ORDER BY a.always_track DESC, e.dept, e.name")]
        depts = sorted({r['dept'] for r in conn.execute("SELECT DISTINCT dept FROM employees WHERE active = 1") if r['dept']})
        return jsonify({'ok': True, 'rows': rows, 'trackable': trackable, 'depts': depts})
    finally:
        conn.close()


@bp.route('/api/displays/<int:did>/<action>', methods=['POST'])
def api_display_action(did, action):
    err = _admin_only()
    if err:
        return err
    conn = db.get_db()
    try:
        r = conn.execute("SELECT * FROM displays WHERE id = ?", (did,)).fetchone()
        if not r:
            return jsonify({'ok': False, 'error': 'غير موجودة'}), 404
        if action in ('enable', 'disable'):
            conn.execute("UPDATE displays SET active = ? WHERE id = ?", (1 if action == 'enable' else 0, did))
        elif action == 'regen':     # رمز جديد: الرابط القديم يتوقف فوراً
            conn.execute("UPDATE displays SET token = ? WHERE id = ?", (secrets.token_urlsafe(24), did))
        elif action == 'delete':
            conn.execute("DELETE FROM displays WHERE id = ?", (did,))
        else:
            return jsonify({'ok': False, 'error': 'إجراء غير معروف'}), 400
        _audit(conn, f'display_{action}', r['name'])
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


# ----------------------------- الشاشة نفسها (بلا تسجيل دخول) -----------------------------
def _display(conn, token):
    if not token or len(token) < 20:
        return None
    r = conn.execute("SELECT * FROM displays WHERE token = ?", (token,)).fetchone()
    return r if r and r['active'] else None


@bp.route('/display/<token>')
def display_page(token):
    conn = db.get_db()
    try:
        r = _display(conn, token)
        cfg = db.get_all_settings()
        if not r:
            return render_template('display.html', off=True, settings=cfg, d=None, conf={}), 404
        return render_template('display.html', off=False, settings=cfg, d=dict(r), conf=_cfg(r),
                               kind_label=KINDS.get(r['kind'], ''))
    finally:
        conn.close()


@bp.route('/display/<token>/data')
def display_data(token):
    conn = db.get_db()
    try:
        r = _display(conn, token)
        if not r:
            return jsonify({'ok': False, 'off': True}), 404
        now = now_local()
        ip = (request.headers.get('CF-Connecting-IP') or request.remote_addr or '')[:60]
        conn.execute("UPDATE displays SET last_view_at = ?, last_view_ip = ? WHERE id = ?", (now.strftime('%Y-%m-%d %H:%M:%S'), ip, r['id']))
        conn.commit()
        conf = _cfg(r)
        base = {'ok': True, 'kind': r['kind'], 'name': r['name'], 'now': now.strftime('%Y-%m-%d %H:%M:%S'), 'refresh': conf.get('refresh', 30)}
        if r['kind'] == 'attendance':
            base.update(_attendance(conn, conf, now))
        else:
            base.update(_tracking(conn, conf, now))
        resp = jsonify(base)
        resp.headers['Cache-Control'] = 'no-store'
        return resp
    finally:
        conn.close()


def _attendance(conn, conf, now):
    cfg = db.get_all_settings()
    today = now.strftime('%Y-%m-%d')
    depts_sel = set(conf.get('depts') or [])
    excluded = {d.strip() for d in (cfg.get('excluded_depts') or '').split(',') if d.strip()}
    open_depts = {x['dept'] for x in conn.execute("SELECT dept FROM dept_attendance_settings WHERE open_hours = 1")}
    import vacations
    vac = {n: t for (n, d), t in vacations.approved_days(conn).items() if d == today}
    exc = {x['name'] for x in conn.execute("SELECT name FROM date_exceptions WHERE date = ?", (today,))}
    emps = [dict(x) for x in conn.execute("SELECT name, dept FROM employees WHERE active = 1 ORDER BY dept, name")
            if (not depts_sel or (x['dept'] or '') in depts_sel) and (x['dept'] or '') not in excluded]
    rc = {x['name']: dict(x) for x in conn.execute("SELECT * FROM report_cache WHERE date = ?", (today,))}
    first_in = {}
    for x in conn.execute("SELECT name, MIN(time_in) AS t FROM punches WHERE date = ? AND COALESCE(time_in, '') != '' GROUP BY name", (today,)):
        first_in[x['name']] = x['t']
    for x in conn.execute("SELECT name, MIN(time) AS t FROM mobile_punches WHERE date = ? AND status = 'accepted' AND kind = 'in' GROUP BY name", (today,)):
        first_in[x['name']] = min(first_in.get(x['name']) or x['t'], x['t'])
    wd = now.weekday()
    work_day = wd != 4 and not (wd == 5 and cfg.get('sat_time_enabled') != '1') and \
        not conn.execute("SELECT 1 FROM official_holidays WHERE date = ?", (today,)).fetchone()
    present, late, absent, leave, open_staff = [], [], [], [], []
    by_dept = {}
    for e in emps:
        n, dept = e['name'], e['dept'] or '—'
        b = by_dept.setdefault(dept, {'dept': dept, 'expected': 0, 'present': 0, 'late': 0, 'absent': 0, 'leave': 0})
        t_in = (rc.get(n) or {}).get('time_in') or (first_in.get(n) or '')[:5]
        if n in vac or n in exc:
            leave.append({'name': n, 'dept': dept, 'why': vac.get(n) and f'إجازة {vac[n]}' or 'استثناء'})
            b['leave'] += 1
            continue
        if (e['dept'] or '') in open_depts and not t_in:
            open_staff.append(n)
            continue
        b['expected'] += 1
        if t_in:
            st = (rc.get(n) or {}).get('status')
            item = {'name': n, 'dept': dept, 'time': t_in[:5], 'late': int((rc.get(n) or {}).get('late_minutes') or 0)}
            present.append(item)
            b['present'] += 1
            if st in LATE:
                late.append(item)
                b['late'] += 1
        else:
            absent.append({'name': n, 'dept': dept})
            b['absent'] += 1
    expected = len(present) + len(absent)
    show = conf.get('show_names', True)
    return {'work_day': work_day, 'date': today,
            'counts': {'expected': expected, 'present': len(present), 'late': len(late), 'absent': len(absent), 'leave': len(leave),
                       'rate': round(100 * len(present) / expected) if expected else 0},
            'depts': sorted(by_dept.values(), key=lambda x: x['dept']),
            'present': sorted(present, key=lambda x: x['time'])[-40:][::-1] if show else [],
            'late': sorted(late, key=lambda x: -x['late']) if show else [],
            'absent': absent if show else [], 'leave': leave if show else [], 'show_names': show}


def _tracking(conn, conf, now):
    ids = conf.get('employees') or []
    if not ids:
        return {'rows': [], 'sites': []}
    now_s = now.strftime('%Y-%m-%d %H:%M:%S')
    today = now_s[:10]
    q = ','.join('?' * len(ids))
    emps = {x['id']: dict(x) for x in conn.execute(f"SELECT id, name, dept FROM employees WHERE id IN ({q})", ids)}
    rows = []
    for eid in ids:
        e = emps.get(eid)
        if not e:
            continue
        s = conn.execute("SELECT * FROM location_shares WHERE employee_id = ? AND lat IS NOT NULL ORDER BY "
                         "(kind = 'live' AND stopped_at IS NULL AND ends_at > ?) DESC, COALESCE(updated_at, started_at) DESC LIMIT 1",
                         (eid, now_s)).fetchone()
        last = conn.execute("SELECT kind, time FROM mobile_punches WHERE employee_id = ? AND date = ? AND status = 'accepted' "
                            "ORDER BY time DESC, id DESC LIMIT 1", (eid, today)).fetchone()
        row = {'id': eid, 'name': e['name'], 'dept': e['dept'] or '', 'live': False, 'lat': None, 'lng': None,
               'state': {'in': 'في الدوام', 'out': 'انصرف', 'leave_out': 'خروج مؤقت', 'leave_back': 'في الدوام'}.get(last['kind'], '') if last else 'لم يسجّل',
               'state_time': last['time'][:5] if last else ''}
        if s:
            live = s['kind'] == 'live' and not s['stopped_at'] and (s['ends_at'] or '') > now_s
            try:
                age = max(0, int((now - datetime.strptime((s['updated_at'] or s['started_at'])[:19], '%Y-%m-%d %H:%M:%S')).total_seconds()))
            except ValueError:
                age = None
            row.update({'live': live, 'lat': s['lat'], 'lng': s['lng'], 'accuracy': s['accuracy'], 'age_s': age,
                        'updated_at': (s['updated_at'] or '')[:19]})
            if conf.get('trail', True) and live:
                row['tail'] = [[p['lat'], p['lng']] for p in conn.execute(
                    "SELECT lat, lng FROM (SELECT lat, lng, ts FROM location_share_points WHERE share_id = ? AND ts >= ? "
                    "ORDER BY ts DESC LIMIT 120) ORDER BY ts", (s['id'], today + ' 00:00:00'))]
        rows.append(row)
    sites = [{'name': x['name'], 'lat': x['lat'], 'lng': x['lng'], 'radius': x['radius_m']} for x in site_rows(conn, True)]
    return {'rows': rows, 'sites': sites}
