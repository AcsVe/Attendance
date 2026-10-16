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
                    sites_for, _work_end)

bp = Blueprint('shares', __name__)
LIVE_CHOICES = {15, 30, 60, 120, 240}


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


def _ts(now=None):
    return (now or now_local()).strftime('%Y-%m-%d %H:%M:%S')


def _num(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def active_share(conn, emp_id, now=None):
    """المشاركة المباشرة السارية لهذا الموظف (أو None)"""
    now_s = _ts(now)
    r = conn.execute("SELECT * FROM location_shares WHERE employee_id = ? AND kind = 'live' AND stopped_at IS NULL "
                     "AND ends_at > ? ORDER BY id DESC LIMIT 1", (emp_id, now_s)).fetchone()
    return dict(r) if r else None


def add_point(conn, share, lat, lng, acc, now=None):
    lat, lng, acc = _num(lat), _num(lng), _num(acc)
    if lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return False
    ts = _ts(now)
    last = conn.execute("SELECT ts FROM location_share_points WHERE share_id = ? ORDER BY ts DESC LIMIT 1", (share['id'],)).fetchone()
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
    return {'id': s['id'], 'ends_at': s['ends_at'], 'ends': s['ends_at'][11:16], 'started': s['started_at'][11:16],
            'remaining_ms': max(0, int((datetime.strptime(s['ends_at'], '%Y-%m-%d %H:%M:%S') - now_local()).total_seconds() * 1000))}


# ----------------------------- تطبيق الموظف -----------------------------
@bp.route('/me/api/share/once', methods=['POST'])
@_me_json
def me_share_once(conn, acc, emp, cfg):
    d = request.get_json(silent=True) or {}
    lat, lng = _num(d.get('lat')), _num(d.get('lng'))
    if lat is None or lng is None:
        return jsonify({'ok': False, 'error': 'لم يُحدَّد موقعك بعد — انتظر قليلاً ثم أعد المحاولة'}), 400
    now = _ts()
    cur = conn.execute("INSERT INTO location_shares (employee_id, name, dept, kind, note, started_at, ends_at, stopped_at, lat, lng, accuracy, updated_at, points) "
                       "VALUES (?, ?, ?, 'once', ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                       (emp['id'], emp['name'], emp['dept'] or '', (d.get('note') or '').strip()[:200], now, now, now, lat, lng, _num(d.get('accuracy')), now))
    conn.execute("INSERT INTO location_share_points (share_id, ts, lat, lng, accuracy) VALUES (?, ?, ?, ?, ?)",
                 (cur.lastrowid, now, lat, lng, _num(d.get('accuracy'))))
    conn.commit()
    return jsonify({'ok': True, 'message': 'أُرسل موقعك الحالي إلى الإدارة'})


@bp.route('/me/api/share/live/start', methods=['POST'])
@_me_json
def me_share_live_start(conn, acc, emp, cfg):
    d = request.get_json(silent=True) or {}
    now = now_local()
    mins = d.get('minutes')
    if mins == 'shift':
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
    cur = conn.execute("INSERT INTO location_shares (employee_id, name, dept, kind, note, started_at, ends_at) VALUES (?, ?, ?, 'live', ?, ?, ?)",
                       (emp['id'], emp['name'], emp['dept'] or '', (d.get('note') or '').strip()[:200], _ts(now), _ts(end)))
    share = dict(conn.execute("SELECT * FROM location_shares WHERE id = ?", (cur.lastrowid,)).fetchone())
    add_point(conn, share, d.get('lat'), d.get('lng'), d.get('accuracy'), now)
    conn.commit()
    return jsonify({'ok': True, 'share': share_info(conn, emp['id']), 'message': f'بدأت مشاركة موقعك المباشر حتى {end.strftime("%H:%M")}'})


@bp.route('/me/api/share/live/point', methods=['POST'])
@_me_json
def me_share_live_point(conn, acc, emp, cfg):
    d = request.get_json(silent=True) or {}
    s = active_share(conn, emp['id'])
    if not s:
        return jsonify({'ok': True, 'active': False})
    add_point(conn, s, d.get('lat'), d.get('lng'), d.get('accuracy'))
    conn.commit()
    return jsonify({'ok': True, 'active': True})


@bp.route('/me/api/share/live/stop', methods=['POST'])
@_me_json
def me_share_live_stop(conn, acc, emp, cfg):
    s = active_share(conn, emp['id'])
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
