"""
مشاركة الموقع من تطبيق الموظف (بمبادرة الموظف فقط):
• «إرسال موقعي الحالي»: نقطة واحدة مع ملاحظة اختيارية.
• «مشاركة الموقع المباشر»: لمدة يختارها الموظف (أو حتى نهاية الدوام)، يتحدّث الموقع كل دقيقة تقريباً،
  ويستطيع الموظف إيقافه في أي لحظة، وينتهي تلقائياً عند انتهاء المدة.
تظهر للإدارة في صفحة «المواقع المشاركة» على الخريطة مع المسار، وتصل إشعاراً لتطبيق الإدارة.
"""
import json
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

import db
from mobile import (_me_json, admin_required, now_local, _employee_scope_ok, _audit, haversine_m,
                    sites_for, _work_end, check_integrity)

bp = Blueprint('shares', __name__)
LIVE_CHOICES = {15, 30, 60, 120, 240}
FOREVER = '9999-12-31 23:59:59'     # مشاركة بلا مدة (حتى الإيقاف)


def init_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS location_shares (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        name TEXT, dept TEXT,
        kind TEXT NOT NULL,              -- once / live
        note TEXT,
        started_at TEXT NOT NULL,
        ends_at TEXT,
        stopped_at TEXT,
        lat REAL, lng REAL, accuracy REAL,
        updated_at TEXT,
        points INTEGER NOT NULL DEFAULT 0
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS location_share_points (
        share_id INTEGER NOT NULL,
        ts TEXT NOT NULL,
        lat REAL NOT NULL, lng REAL NOT NULL, accuracy REAL
    )''')
    conn.execute("CREATE INDEX IF NOT EXISTS ix_share_points ON location_share_points(share_id, ts)")
    cols = {r['name'] for r in conn.execute("PRAGMA table_info(location_shares)")}
    for col in ('flags', 'source'):
        if col not in cols:
            conn.execute(f"ALTER TABLE location_shares ADD COLUMN {col} TEXT")


def _integrity(conn, emp, d, cfg):
    """نفس حماية تسجيل الدوام من الموقع الوهمي: يرجع (سبب الرفض، علامات الاشتباه، المصدر)"""
    lat, lng, acc = _num(d.get('lat')), _num(d.get('lng')), _num(d.get('accuracy'))
    reason, flags, source = check_integrity(conn, emp, 'share', d, lat, lng, acc, None, cfg)
    if not reason and source == 'app' and d.get('dev_opts'):
        flags.append('خيارات المطوّر مفعّلة على الهاتف')
    if not reason and d.get('mock'):      # المتصفح لا يكشفه عادةً، لكن إن وصل نرفضه
        reason = 'تم اكتشاف تطبيق موقع وهمي (Fake GPS) على هاتفك — أغلقه ثم أعد المحاولة'
    return reason, flags, source


def _flag(conn, share_id, text):
    r = conn.execute("SELECT flags FROM location_shares WHERE id = ?", (share_id,)).fetchone()
    old = [x for x in ((r['flags'] if r else '') or '').split('؛ ') if x]
    if text not in old:
        old.append(text)
    conn.execute("UPDATE location_shares SET flags = ? WHERE id = ?", ('؛ '.join(old)[:500], share_id))


def _ts(now=None):
    return (now or now_local()).strftime('%Y-%m-%d %H:%M:%S')


def _num(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def active_share(conn, emp_id, now=None):
    """المشاركة المباشرة السارية لهذا الموظف (أو None).
    الحساب المفعّل له «التتبع المستمر» من الإدارة (الأجهزة المتنقلة) تُنشأ له مشاركة بلا مدة تلقائياً."""
    now_s = _ts(now)
    r = conn.execute("SELECT * FROM location_shares WHERE employee_id = ? AND kind = 'live' AND stopped_at IS NULL "
                     "AND ends_at > ? ORDER BY id DESC LIMIT 1", (emp_id, now_s)).fetchone()
    if r:
        return dict(r)
    acc = conn.execute("SELECT always_track, active FROM employee_accounts WHERE employee_id = ?", (emp_id,)).fetchone()
    if acc and acc['always_track'] and acc['active']:
        emp = conn.execute("SELECT name, dept FROM employees WHERE id = ?", (emp_id,)).fetchone()
        if emp:
            cur = conn.execute("INSERT INTO location_shares (employee_id, name, dept, kind, note, started_at, ends_at, source) "
                               "VALUES (?, ?, ?, 'live', 'تتبع مستمر من الإدارة', ?, ?, 'admin')", (emp_id, emp['name'], emp['dept'] or '', now_s, FOREVER))
            conn.commit()
            return dict(conn.execute("SELECT * FROM location_shares WHERE id = ?", (cur.lastrowid,)).fetchone())
    return None


def add_point(conn, share, lat, lng, acc, now=None):
    lat, lng, acc = _num(lat), _num(lng), _num(acc)
    if lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return False
    ts = _ts(now)
    last = conn.execute("SELECT ts, lat, lng FROM location_share_points WHERE share_id = ? ORDER BY ts DESC LIMIT 1", (share['id'],)).fetchone()
    if last:
        secs = max((datetime.strptime(ts, '%Y-%m-%d %H:%M:%S') - datetime.strptime(last['ts'], '%Y-%m-%d %H:%M:%S')).total_seconds(), 1)
        km = haversine_m(lat, lng, last['lat'], last['lng']) / 1000
        if km > 1 and km / (secs / 3600) > 250:
            _flag(conn, share['id'], f'قفزة غير منطقية ({km:.0f} كم خلال ' + (f'{secs / 60:.0f} دقيقة)' if secs >= 60 else 'أقل من دقيقة)'))
    if last and (datetime.strptime(ts, '%Y-%m-%d %H:%M:%S') - datetime.strptime(last['ts'], '%Y-%m-%d %H:%M:%S')).total_seconds() < 20:
        conn.execute("UPDATE location_shares SET lat = ?, lng = ?, accuracy = ?, updated_at = ? WHERE id = ?", (lat, lng, acc, ts, share['id']))
        return True
    conn.execute("INSERT INTO location_share_points (share_id, ts, lat, lng, accuracy) VALUES (?, ?, ?, ?, ?)", (share['id'], ts, lat, lng, acc))
    conn.execute("UPDATE location_shares SET lat = ?, lng = ?, accuracy = ?, updated_at = ?, points = points + 1 WHERE id = ?",
                 (lat, lng, acc, ts, share['id']))
    return True


def share_info(conn, emp_id):
    s = active_share(conn, emp_id)
    if not s:
        return None
    unlimited = s['ends_at'] >= FOREVER[:4]
    return {'id': s['id'], 'ends_at': s['ends_at'], 'ends': '' if unlimited else s['ends_at'][11:16], 'started': s['started_at'][11:16],
            'unlimited': unlimited, 'forced': s.get('source') == 'admin',
            'remaining_ms': max(0, int((datetime.strptime(s['ends_at'], '%Y-%m-%d %H:%M:%S') - now_local()).total_seconds() * 1000))}


# ----------------------------- تطبيق الموظف -----------------------------
@bp.route('/me/api/share/once', methods=['POST'])
@_me_json
def me_share_once(conn, acc, emp, cfg):
    d = request.get_json(silent=True) or {}
    lat, lng = _num(d.get('lat')), _num(d.get('lng'))
    if lat is None or lng is None:
        return jsonify({'ok': False, 'error': 'لم يُحدَّد موقعك بعد — انتظر قليلاً ثم أعد المحاولة'}), 400
    reason, flags, source = _integrity(conn, emp, d, cfg)
    if reason:
        return jsonify({'ok': False, 'error': reason}), 403
    now = _ts()
    cur = conn.execute("INSERT INTO location_shares (employee_id, name, dept, kind, note, started_at, ends_at, stopped_at, lat, lng, accuracy, updated_at, points, flags, source) "
                       "VALUES (?, ?, ?, 'once', ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                       (emp['id'], emp['name'], emp['dept'] or '', (d.get('note') or '').strip()[:200], now, now, now, lat, lng, _num(d.get('accuracy')), now,
                        '؛ '.join(flags)[:500], source))
    conn.execute("INSERT INTO location_share_points (share_id, ts, lat, lng, accuracy) VALUES (?, ?, ?, ?, ?)",
                 (cur.lastrowid, now, lat, lng, _num(d.get('accuracy'))))
    conn.commit()
    return jsonify({'ok': True, 'message': 'أُرسل موقعك الحالي إلى الإدارة'})


@bp.route('/me/api/share/live/start', methods=['POST'])
@_me_json
def me_share_live_start(conn, acc, emp, cfg):
    d = request.get_json(silent=True) or {}
    now = now_local()
    if _num(d.get('lat')) is None:
        return jsonify({'ok': False, 'error': 'لم يُحدَّد موقعك بعد — انتظر قليلاً ثم أعد المحاولة'}), 400
    reason, flags, source = _integrity(conn, emp, d, cfg)
    if reason:
        return jsonify({'ok': False, 'error': reason}), 403
    mins = d.get('minutes')
    if mins == 'unlimited':
        end = None
    elif mins == 'shift':
        end = _work_end(conn, emp, cfg, now)
        if end <= now:
            return jsonify({'ok': False, 'error': 'انتهى الدوام — اختر مدة محددة'}), 400
    else:
        try:
            mins = int(mins)
        except (TypeError, ValueError):
            mins = 0
        if mins not in LIVE_CHOICES:
            return jsonify({'ok': False, 'error': 'مدة غير صالحة'}), 400
        end = now + timedelta(minutes=mins)
    old = active_share(conn, emp['id'], now)
    if old:
        conn.execute("UPDATE location_shares SET stopped_at = ? WHERE id = ?", (_ts(now), old['id']))
    cur = conn.execute("INSERT INTO location_shares (employee_id, name, dept, kind, note, started_at, ends_at, flags, source) VALUES (?, ?, ?, 'live', ?, ?, ?, ?, ?)",
                       (emp['id'], emp['name'], emp['dept'] or '', (d.get('note') or '').strip()[:200], _ts(now), _ts(end) if end else FOREVER, '؛ '.join(flags)[:500], source))
    share = dict(conn.execute("SELECT * FROM location_shares WHERE id = ?", (cur.lastrowid,)).fetchone())
    add_point(conn, share, d.get('lat'), d.get('lng'), d.get('accuracy'), now)
    conn.commit()
    return jsonify({'ok': True, 'share': share_info(conn, emp['id']), 'message': (f'بدأت مشاركة موقعك المباشر حتى {end.strftime("%H:%M")}' if end else 'بدأت مشاركة موقعك المباشر بلا مدة — حتى تضغط «إيقاف»')})


@bp.route('/me/api/share/live/point', methods=['POST'])
@_me_json
def me_share_live_point(conn, acc, emp, cfg):
    d = request.get_json(silent=True) or {}
    s = active_share(conn, emp['id'])
    if not s:
        return jsonify({'ok': True, 'active': False})
    if d.get('mock'):
        stop_for_mock(conn, s)
        conn.commit()
        return jsonify({'ok': False, 'active': False, 'error': 'أُوقفت المشاركة: تم اكتشاف تطبيق موقع وهمي'}), 403
    add_point(conn, s, d.get('lat'), d.get('lng'), d.get('accuracy'))
    conn.commit()
    return jsonify({'ok': True, 'active': True})


def stop_for_mock(conn, share):
    conn.execute("UPDATE location_shares SET stopped_at = ? WHERE id = ?", (_ts(), share['id']))
    _flag(conn, share['id'], 'موقع وهمي (Fake GPS) أثناء المشاركة — أُوقفت تلقائياً')


@bp.route('/me/api/share/live/stop', methods=['POST'])
@_me_json
def me_share_live_stop(conn, acc, emp, cfg):
    s = active_share(conn, emp['id'])
    if s and s.get('source') == 'admin':
        conn.commit()
        return jsonify({'ok': False, 'error': 'التتبع المستمر مفعّل من الإدارة لهذا الحساب — لا يمكن إيقافه من الهاتف'}), 403
    if s:
        conn.execute("UPDATE location_shares SET stopped_at = ? WHERE id = ?", (_ts(), s['id']))
        conn.commit()
    return jsonify({'ok': True, 'message': 'أُوقفت مشاركة الموقع'})


# ----------------------------- لوحة الإدارة -----------------------------
@bp.route('/api/shares')
@admin_required
def api_shares():
    days = max(1, min(int(request.args.get('days') or 7), 90))
    since = (now_local() - timedelta(days=days)).strftime('%Y-%m-%d 00:00:00')
    now_s = _ts()
    conn = db.get_db()
    try:
        rows = []
        for r in conn.execute("SELECT * FROM location_shares WHERE started_at >= ? ORDER BY started_at DESC LIMIT 1000", (since,)):
            x = dict(r)
            if not _employee_scope_ok(x['dept']):
                continue
            x['live_now'] = x['kind'] == 'live' and not x['stopped_at'] and (x['ends_at'] or '') > now_s
            emp = conn.execute("SELECT dept FROM employees WHERE id = ?", (x['employee_id'],)).fetchone()
            x['site_dist'] = None
            if x['lat'] is not None and emp is not None:
                ds = [(haversine_m(x['lat'], x['lng'], s['lat'], s['lng']) - s['radius_m'], s['name']) for s in sites_for(conn, emp['dept'])]
                if ds:
                    best = min(ds)
                    x['site_dist'], x['site_name'] = round(max(best[0], 0)), best[1]
            rows.append(x)
        return jsonify({'ok': True, 'rows': rows, 'live': sum(1 for x in rows if x['live_now'])})
    finally:
        conn.close()


@bp.route('/api/shares/<int:sid>/track')
@admin_required
def api_share_track(sid):
    conn = db.get_db()
    try:
        s = conn.execute("SELECT * FROM location_shares WHERE id = ?", (sid,)).fetchone()
        if not s or not _employee_scope_ok(s['dept']):
            return jsonify({'ok': False, 'error': 'غير موجود'}), 404
        pts = [[r['lat'], r['lng'], r['ts'][11:19], r['accuracy']] for r in
               conn.execute("SELECT * FROM location_share_points WHERE share_id = ? ORDER BY ts", (sid,))]
        return jsonify({'ok': True, 'share': dict(s), 'points': pts})
    finally:
        conn.close()


@bp.route('/api/shares/delete', methods=['POST'])
@admin_required
def api_shares_delete():
    ids = [int(i) for i in ((request.get_json(silent=True) or {}).get('ids') or []) if str(i).isdigit()]
    if not ids:
        return jsonify({'ok': False, 'error': 'لم يُحدَّد شيء'}), 400
    conn = db.get_db()
    try:
        q = ','.join('?' * len(ids))
        conn.execute(f"DELETE FROM location_share_points WHERE share_id IN ({q})", ids)
        conn.execute(f"DELETE FROM location_shares WHERE id IN ({q})", ids)
        _audit(conn, 'shares_delete', 'location_share', json.dumps(ids)[:300])
        conn.commit()
        return jsonify({'ok': True, 'deleted': len(ids)})
    finally:
        conn.close()


@bp.route('/api/shares/tracking', methods=['GET', 'POST'])
@admin_required
def api_shares_tracking():
    """التتبع المستمر بلا مدة (للأجهزة المتنقلة التي تُعامَل كموظف): عرض/تشغيل/إيقاف لموظف أو أكثر"""
    conn = db.get_db()
    try:
        if request.method == 'POST':
            d = request.get_json(silent=True) or {}
            ids = [int(i) for i in (d.get('ids') or []) if str(i).isdigit()]
            on = bool(d.get('on'))
            if not ids:
                return jsonify({'ok': False, 'error': 'لم يُحدَّد أحد'}), 400
            q = ','.join('?' * len(ids))
            n = conn.execute(f"UPDATE employee_accounts SET always_track = ? WHERE employee_id IN ({q})", [1 if on else 0] + ids).rowcount
            if not on:     # إيقاف المشاركة الجارية التي أنشأتها الإدارة
                conn.execute(f"UPDATE location_shares SET stopped_at = ? WHERE employee_id IN ({q}) AND source = 'admin' AND stopped_at IS NULL",
                             [_ts()] + ids)
            _audit(conn, 'tracking_on' if on else 'tracking_off', 'location_share', json.dumps(ids)[:300])
            conn.commit()
            return jsonify({'ok': True, 'updated': n})
        rows = [dict(r) for r in conn.execute(
            "SELECT e.id, e.name, e.dept, a.always_track, a.active AS acc_active, a.username FROM employees e "
            "JOIN employee_accounts a ON a.employee_id = e.id WHERE e.active = 1 ORDER BY a.always_track DESC, e.dept, e.name")]
        rows = [r for r in rows if _employee_scope_ok(r['dept'])]
        now_s = _ts()
        for r in rows:
            s = conn.execute("SELECT updated_at, lat FROM location_shares WHERE employee_id = ? AND kind = 'live' AND stopped_at IS NULL "
                             "AND ends_at > ? ORDER BY id DESC LIMIT 1", (r['id'], now_s)).fetchone()
            r['last_update'] = s['updated_at'] if s else None
        return jsonify({'ok': True, 'rows': rows})
    finally:
        conn.close()


@bp.route('/api/shares/stop', methods=['POST'])
@admin_required
def api_shares_stop():
    """إيقاف مشاركات مباشرة جارية (والتتبع المستمر لأصحابها إن كان مفعّلاً)"""
    ids = [int(i) for i in ((request.get_json(silent=True) or {}).get('ids') or []) if str(i).isdigit()]
    if not ids:
        return jsonify({'ok': False, 'error': 'لم يُحدَّد شيء'}), 400
    conn = db.get_db()
    try:
        q = ','.join('?' * len(ids))
        emps = [r['employee_id'] for r in conn.execute(f"SELECT employee_id FROM location_shares WHERE id IN ({q}) AND source = 'admin'", ids)]
        if emps:
            conn.execute(f"UPDATE employee_accounts SET always_track = 0 WHERE employee_id IN ({','.join('?' * len(emps))})", emps)
        n = conn.execute(f"UPDATE location_shares SET stopped_at = ? WHERE id IN ({q}) AND stopped_at IS NULL", [_ts()] + ids).rowcount
        _audit(conn, 'shares_stop', 'location_share', json.dumps(ids)[:300])
        conn.commit()
        return jsonify({'ok': True, 'stopped': n})
    finally:
        conn.close()
