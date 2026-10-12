"""
تطبيق الموظفين على الهاتف — تسجيل الحضور والانصراف والخروج المؤقت من أي مكان ضمن مواقع العمل المعتمدة.

• كل موظف له اسم مستخدم وكلمة مرور (منفصلة عن حسابات الإدارة) — صفحة الدخول /me/login
• ربط الحساب بهاتف واحد: أول دخول يربط الهاتف، ولا يمكن الدخول أو التسجيل من هاتف آخر حتى تفكّ الإدارة الربط
• Geofence: مواقع عمل (مركز + نصف قطر) لكل الأقسام أو لأقسام محددة — يرفض الخادم أي حركة من خارجها
  (أو بدقة موقع ضعيفة)، وتُسجَّل المحاولة المرفوضة مع السبب للمتابعة
• الحضور/الانصراف تدخل جدول البصمات نفسه (مع بصمات الأجهزة: أبكر حضور وآخر انصراف في اليوم) فتظهر في كل
  التقارير والتحليل؛ والخروج المؤقت يُحسب إذناً للمغادرة ويُخصم من ساعات العمل (قابل للإيقاف من الإعدادات)
• للإدارة: حسابات الموظفين (إنشاء جماعي)، مواقع العمل على الخريطة، سجل الحركات المباشر، والتصدير
"""
import csv
import hashlib
import io
import json
import math
import os
import secrets
import threading
import time
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import db

bp = Blueprint('mobile', __name__)

KINDS = {'in': 'حضور', 'out': 'انصراف', 'leave_out': 'خروج مؤقت', 'leave_back': 'عودة من الخروج'}
NEXT = {   # الحركة المسموحة حسب آخر حركة اليوم
    None: ['in'],
    'in': ['out', 'leave_out'],
    'leave_out': ['leave_back', 'out'],
    'leave_back': ['out', 'leave_out'],
    'out': ['in'],
}
LEAVE_REASON = 'خروج مؤقت عبر تطبيق الهاتف'


# =====================================================
#   أدوات
# =====================================================
def now_local():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(os.environ.get('ATT_TZ', 'Asia/Amman'))).replace(tzinfo=None)
    except Exception:
        return datetime.now()


def haversine_m(lat1, lng1, lat2, lng2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _hash(token):
    return hashlib.sha256(('att-dev:' + (token or '')).encode()).hexdigest()


def _ip():
    return (request.headers.get('CF-Connecting-IP') or request.headers.get('X-Forwarded-For', '').split(',')[0]
            or request.remote_addr or '')[:45]


def _device_label():
    ua = request.headers.get('User-Agent', '')
    for key, label in (('iPhone', 'iPhone'), ('iPad', 'iPad'), ('Android', 'Android'), ('Windows', 'Windows'), ('Mac', 'Mac'), ('Linux', 'Linux')):
        if key in ua:
            model = ''
            if key == 'Android' and ';' in ua:
                try:
                    model = ua.split('Android')[1].split(';')[1].split(')')[0].split('Build')[0].strip()
                except IndexError:
                    model = ''
            return (label + (' — ' + model if model else ''))[:80]
    return ua[:80] or 'غير معروف'


def settings():
    return db.get_all_settings()


def _admin():
    """طلبات لوحة الإدارة — نفس صلاحيات app.py"""
    import app as app_module
    return app_module


def admin_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if not session.get('user_id'):
            return jsonify({'ok': False, 'error': 'يرجى تسجيل الدخول أولاً'}), 401
        return view(*a, **kw)
    return wrapped


def _employee_scope_ok(dept):
    allowed = session.get('allowed_depts') or []
    return not allowed or (dept or '') in allowed


# =====================================================
#   مواقع العمل
# =====================================================
def site_rows(conn, active_only=False):
    q = "SELECT * FROM work_sites" + (" WHERE active = 1" if active_only else "") + " ORDER BY name"
    out = []
    for r in conn.execute(q).fetchall():
        d = dict(r)
        try:
            d['depts'] = json.loads(d.get('depts_json') or '[]')
        except ValueError:
            d['depts'] = []
        out.append(d)
    return out


def sites_for(conn, dept):
    return [s for s in site_rows(conn, True) if not s['depts'] or (dept or '') in s['depts']]


def check_location(conn, emp, acc, lat, lng, accuracy, cfg):
    """يرجع (ok, reason, site, distance)"""
    if lat is None or lng is None:
        return False, 'لم يصل موقع الهاتف — فعّل خدمة الموقع (GPS) واسمح للمتصفح باستخدامه', None, None
    max_acc = float(cfg.get('mobile_max_accuracy') or 150)
    if accuracy is not None and accuracy > max_acc:
        return False, f'دقة الموقع ضعيفة ({int(accuracy)} م) — انتظر قليلاً في مكان مفتوح ثم أعد المحاولة', None, None
    sites = sites_for(conn, emp['dept'])
    best, best_d = None, None
    for s in sites:
        d = haversine_m(lat, lng, s['lat'], s['lng'])
        if best_d is None or d - s['radius_m'] < best_d - best['radius_m']:
            best, best_d = s, d
    if acc['anywhere'] or cfg.get('mobile_require_geofence', '1') != '1':
        return True, '', best, best_d
    if not sites:
        return False, 'لم تُحدَّد مواقع عمل لقسمك بعد — راجع الإدارة', None, None
    slack = min(accuracy or 0, 30)   # هامش صغير لخطأ GPS
    if best_d - slack <= best['radius_m']:
        return True, '', best, best_d
    return False, f'أنت خارج موقع العمل ({int(best_d)} م عن «{best["name"]}»، المسموح {best["radius_m"]} م)', best, best_d


# =====================================================
#   حالة اليوم ودمج الحركات في البصمات
# =====================================================
def today_moves(conn, emp_id, date_str):
    return [dict(r) for r in conn.execute(
        "SELECT kind, time, site_name FROM mobile_punches WHERE employee_id = ? AND date = ? AND status = 'accepted' "
        "ORDER BY time, id", (emp_id, date_str)).fetchall()]


def _merge_punch(conn, emp, date_str, time_str, kind):
    """الحضور/الانصراف في جدول البصمات (سجل واحد لليوم: أبكر حضور وآخر انصراف)"""
    row = conn.execute("SELECT id, time_in, time_out FROM punches WHERE name = ? AND date = ? ORDER BY id LIMIT 1",
                       (emp['name'], date_str)).fetchone()
    if row:
        tin, tout = row['time_in'] or '', row['time_out'] or ''
        if kind == 'in':
            tin = min(tin, time_str) if tin else time_str
            tout = tout or time_str
        else:
            tout = max(tout, time_str) if tout else time_str
            tin = tin or time_str
        conn.execute("UPDATE punches SET time_in = ?, time_out = ?, synced = 0 WHERE id = ?", (tin, tout, row['id']))
    else:
        conn.execute("INSERT INTO punches (name, date, dept, time_in, time_out, batch_id) VALUES (?, ?, ?, ?, ?, 'mobile')",
                     (emp['name'], date_str, emp['dept'] or '', time_str, time_str))


def _apply_leave(conn, emp, date_str):
    """مجموع الخروج المؤقت في اليوم ← إذن مغادرة واحد (يخصمه التحليل من ساعات العمل)"""
    moves = today_moves(conn, emp['id'], date_str)
    total, first_out, out_at = 0, None, None
    for m in moves:
        if m['kind'] == 'leave_out':
            out_at = m['time']
            first_out = first_out or m['time']
        elif m['kind'] == 'leave_back' and out_at:
            t1 = datetime.strptime(out_at[:5], '%H:%M')
            t2 = datetime.strptime(m['time'][:5], '%H:%M')
            total += max(0, int((t2 - t1).total_seconds() // 60))
            out_at = None
    if not first_out or total <= 0:
        return
    ret = (datetime.strptime(first_out[:5], '%H:%M') + timedelta(minutes=total)).strftime('%H:%M')
    ex = conn.execute("SELECT id, reason FROM departure_permissions WHERE name = ? AND date = ?", (emp['name'], date_str)).fetchone()
    if ex and (ex['reason'] or '') != LEAVE_REASON:
        return   # إذن أدخلته الإدارة يدوياً — لا نغيّره
    if ex:
        conn.execute("UPDATE departure_permissions SET departure_time = ?, return_time = ? WHERE id = ?", (first_out[:5], ret, ex['id']))
    else:
        conn.execute("INSERT INTO departure_permissions (name, date, departure_time, return_time, reason) VALUES (?, ?, ?, ?, ?)",
                     (emp['name'], date_str, first_out[:5], ret, LEAVE_REASON))


_analysis = {'pending': False, 'lock': threading.Lock()}


def schedule_analysis(delay=4):
    """إعادة التحليل في الخلفية (مرة واحدة لعدة حركات متقاربة) حتى يبقى زر التسجيل سريعاً"""
    with _analysis['lock']:
        if _analysis['pending']:
            return
        _analysis['pending'] = True

    def run():
        time.sleep(delay)
        with _analysis['lock']:
            _analysis['pending'] = False
        conn = db.get_db()
        try:
            _admin().run_full_analysis(conn)
            conn.commit()
        except Exception:
            import logging
            logging.getLogger('attendance').exception('mobile analysis failed')
        finally:
            conn.close()
    threading.Thread(target=run, daemon=True).start()


# =====================================================
#   تطبيق الموظف
# =====================================================
_FAILS = {}


def _blocked(key):
    now = time.time()
    tries = [t for t in _FAILS.get(key, []) if now - t < 900]
    _FAILS[key] = tries
    return len(tries) >= 5


def _account(conn):
    eid = session.get('emp_id')
    if not eid:
        return None, None
    acc = conn.execute("SELECT * FROM employee_accounts WHERE employee_id = ?", (eid,)).fetchone()
    emp = conn.execute("SELECT * FROM employees WHERE id = ?", (eid,)).fetchone()
    if not acc or not emp or not acc['active'] or not emp['active']:
        return None, None
    return acc, emp


def _device_ok(acc, token, cfg):
    if cfg.get('mobile_bind_device', '1') != '1':
        return True
    return bool(acc['device_hash']) and token and secrets.compare_digest(acc['device_hash'], _hash(token))


@bp.route('/me/login', methods=['GET', 'POST'])
def me_login():
    cfg = settings()
    if request.method == 'GET':
        return render_template('me_login.html', error=None, settings=cfg)
    username = (request.form.get('username') or '').strip().lower()
    password = request.form.get('password') or ''
    token = (request.form.get('device') or '').strip()
    key = f'{_ip()}|{username}'
    if _blocked(key):
        return render_template('me_login.html', error='محاولات كثيرة خاطئة — انتظر 15 دقيقة', settings=cfg), 429
    conn = db.get_db()
    try:
        acc = conn.execute("SELECT * FROM employee_accounts WHERE lower(username) = ?", (username,)).fetchone()
        emp = conn.execute("SELECT * FROM employees WHERE id = ?", (acc['employee_id'],)).fetchone() if acc else None
        if not acc or not check_password_hash(acc['password_hash'], password):
            _FAILS.setdefault(key, []).append(time.time())
            return render_template('me_login.html', error='اسم المستخدم أو كلمة المرور غير صحيحة', settings=cfg)
        if not acc['active'] or not emp or not emp['active']:
            return render_template('me_login.html', error='الحساب موقوف — راجع الإدارة', settings=cfg)
        if cfg.get('mobile_bind_device', '1') == '1':
            if len(token) < 32:
                return render_template('me_login.html', error='تعذّر التعرف على الهاتف — فعّل الجافاسكربت وأعد المحاولة', settings=cfg)
            if acc['device_hash'] and not secrets.compare_digest(acc['device_hash'], _hash(token)):
                return render_template('me_login.html', settings=cfg,
                                       error='هذا الحساب مرتبط بهاتف آخر. لا يمكن الدخول إلا من الهاتف المرتبط — اطلب من الإدارة فكّ الربط إن تغيّر هاتفك.')
            if not acc['device_hash']:
                conn.execute("UPDATE employee_accounts SET device_hash = ?, device_label = ?, bound_at = ? WHERE id = ?",
                             (_hash(token), _device_label(), now_local().strftime('%Y-%m-%d %H:%M'), acc['id']))
        conn.execute("UPDATE employee_accounts SET last_login_at = ? WHERE id = ?", (now_local().strftime('%Y-%m-%d %H:%M'), acc['id']))
        conn.commit()
    finally:
        conn.close()
    _FAILS.pop(key, None)
    for k in ('emp_id', 'emp_name'):
        session.pop(k, None)
    session.permanent = True
    session['emp_id'] = emp['id']
    session['emp_name'] = emp['name']
    return redirect(url_for('mobile.me_home'))


@bp.route('/me/logout')
def me_logout():
    session.pop('emp_id', None)
    session.pop('emp_name', None)
    return redirect(url_for('mobile.me_login'))


@bp.route('/me')
@bp.route('/me/')
def me_home():
    conn = db.get_db()
    try:
        acc, emp = _account(conn)
    finally:
        conn.close()
    if not acc:
        return redirect(url_for('mobile.me_login'))
    return render_template('me.html', emp=emp, settings=settings())


def _me_json(fn):
    @wraps(fn)
    def wrapped(*a, **kw):
        conn = db.get_db()
        try:
            acc, emp = _account(conn)
            if not acc:
                return jsonify({'ok': False, 'error': 'انتهت الجلسة — سجّل الدخول من جديد', 'login': True}), 401
            cfg = settings()
            token = request.headers.get('X-Device') or ''
            if not _device_ok(acc, token, cfg):
                return jsonify({'ok': False, 'error': 'هذا الحساب مرتبط بهاتف آخر — لا يمكن التسجيل من هذا الجهاز', 'login': True}), 403
            return fn(conn, acc, emp, cfg, *a, **kw)
        finally:
            conn.close()
    return wrapped


@bp.route('/me/api/status')
@_me_json
def me_status(conn, acc, emp, cfg):
    now = now_local()
    d = now.strftime('%Y-%m-%d')
    moves = today_moves(conn, emp['id'], d)
    last = moves[-1]['kind'] if moves else None
    sites = sites_for(conn, emp['dept'])
    month = now.strftime('%Y-%m')
    days = [dict(r) for r in conn.execute(
        "SELECT date, time_in, time_out, status, late_minutes, working_hours FROM report_cache "
        "WHERE name = ? AND date LIKE ? ORDER BY date DESC", (emp['name'], month + '%')).fetchall()]
    recent = [dict(r) for r in conn.execute(
        "SELECT date, time, kind, status, reason, site_name FROM mobile_punches WHERE employee_id = ? "
        "ORDER BY id DESC LIMIT 30", (emp['id'],)).fetchall()]
    for r in recent:
        r['kind_label'] = KINDS.get(r['kind'], r['kind'])
    return jsonify({
        'ok': True, 'now': now.strftime('%Y-%m-%d %H:%M:%S'), 'date': d,
        'name': emp['name'], 'dept': emp['dept'] or '',
        'enabled': cfg.get('mobile_enabled', '1') == '1',
        'moves': [{**m, 'label': KINDS[m['kind']]} for m in moves],
        'last': last, 'allowed': NEXT.get(last, ['in']),
        'anywhere': bool(acc['anywhere']) or cfg.get('mobile_require_geofence', '1') != '1',
        'max_accuracy': float(cfg.get('mobile_max_accuracy') or 150),
        'sites': [{'name': s['name'], 'lat': s['lat'], 'lng': s['lng'], 'radius': s['radius_m']} for s in sites],
        'month': days, 'recent': recent,
        'summary': {
            'days': sum(1 for x in days if x['time_in']),
            'late_days': sum(1 for x in days if (x['late_minutes'] or 0) > 0),
            'late_minutes': sum(int(x['late_minutes'] or 0) for x in days),
            'absent': sum(1 for x in days if x['status'] == 'غائب'),
            'hours': round(sum(float(x['working_hours'] or 0) for x in days), 1),
        },
    })


@bp.route('/me/api/punch', methods=['POST'])
@_me_json
def me_punch(conn, acc, emp, cfg):
    data = request.get_json(silent=True) or {}
    kind = data.get('kind')
    if kind not in KINDS:
        return jsonify({'ok': False, 'error': 'حركة غير معروفة'}), 400
    if cfg.get('mobile_enabled', '1') != '1':
        return jsonify({'ok': False, 'error': 'التسجيل من الهاتف متوقف حالياً من الإدارة'}), 403

    def num(k):
        try:
            v = float(data.get(k))
            return v if math.isfinite(v) else None
        except (TypeError, ValueError):
            return None
    lat, lng, accuracy = num('lat'), num('lng'), num('accuracy')
    if lat is not None and not (-90 <= lat <= 90 and -180 <= lng <= 180):
        lat = lng = None
    now = now_local()
    d, t = now.strftime('%Y-%m-%d'), now.strftime('%H:%M:%S')
    moves = today_moves(conn, emp['id'], d)
    last = moves[-1]['kind'] if moves else None
    recent = conn.execute("SELECT created_at FROM mobile_punches WHERE employee_id = ? AND status = 'accepted' "
                          "AND created_at >= datetime('now', '-30 seconds')", (emp['id'],)).fetchone()

    ok, reason, site, dist = check_location(conn, emp, acc, lat, lng, accuracy, cfg)
    if ok and kind not in NEXT.get(last, ['in']):
        ok, reason = False, f'لا يمكن تسجيل «{KINDS[kind]}» الآن — آخر حركة: {KINDS.get(last, "لا شيء")}'
    if ok and recent:
        ok, reason = False, 'سُجّلت حركة قبل لحظات — انتظر نصف دقيقة'
    conn.execute(
        "INSERT INTO mobile_punches (employee_id, name, dept, kind, date, time, lat, lng, accuracy, site_id, site_name, "
        "distance_m, status, reason, device_label, ip) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (emp['id'], emp['name'], emp['dept'] or '', kind, d, t, lat, lng, accuracy, site['id'] if site else None,
         site['name'] if site else None, round(dist, 1) if dist is not None else None,
         'accepted' if ok else 'rejected', reason or None, acc['device_label'] or _device_label(), _ip()))
    if ok:
        if kind in ('in', 'out'):
            _merge_punch(conn, emp, d, t, kind)
        if kind in ('leave_back', 'out') and cfg.get('mobile_leave_deduct', '1') == '1':
            conn.commit()
            _apply_leave(conn, emp, d)
    conn.commit()
    if not ok:
        return jsonify({'ok': False, 'error': reason, 'rejected': True}), 400
    if kind in ('in', 'out', 'leave_back'):
        schedule_analysis()
    return jsonify({'ok': True, 'message': f'تم تسجيل {KINDS[kind]} الساعة {t[:5]}' + (f' — {site["name"]}' if site else ''),
                    'time': t[:5]})


@bp.route('/me/api/password', methods=['POST'])
@_me_json
def me_password(conn, acc, emp, cfg):
    data = request.get_json(silent=True) or {}
    if not check_password_hash(acc['password_hash'], data.get('current') or ''):
        return jsonify({'ok': False, 'error': 'كلمة المرور الحالية غير صحيحة'}), 400
    new = data.get('new') or ''
    if len(new) < 6:
        return jsonify({'ok': False, 'error': 'كلمة المرور الجديدة 6 أحرف على الأقل'}), 400
    conn.execute("UPDATE employee_accounts SET password_hash = ? WHERE id = ?", (generate_password_hash(new), acc['id']))
    conn.commit()
    return jsonify({'ok': True})


# =====================================================
#   الإدارة: حسابات الموظفين
# =====================================================
def _gen_password():
    return ''.join(secrets.choice('23456789') for _ in range(4)) + ''.join(secrets.choice('abcdefghjkmnpqrstuvwxyz') for _ in range(4))


def _unique_username(conn, base):
    base = ''.join(ch for ch in (base or '').lower() if ch.isalnum() or ch in '._-')[:30] or 'emp'
    name, i = base, 1
    while conn.execute("SELECT 1 FROM employee_accounts WHERE lower(username) = ?", (name,)).fetchone():
        i += 1
        name = f'{base}{i}'
    return name


def _audit(conn, action, target, value=None):
    try:
        _admin().log_audit(conn, action, target, new_value=value)
    except Exception:
        pass


@bp.route('/api/mobile/accounts', methods=['GET', 'POST'])
@admin_required
def api_accounts():
    conn = db.get_db()
    try:
        if request.method == 'POST':
            data = request.get_json(silent=True) or {}
            emp = conn.execute("SELECT * FROM employees WHERE id = ?", (data.get('employee_id'),)).fetchone()
            if not emp:
                return jsonify({'ok': False, 'error': 'الموظف غير موجود'}), 404
            username = (data.get('username') or '').strip().lower()
            password = data.get('password') or ''
            acc = conn.execute("SELECT * FROM employee_accounts WHERE employee_id = ?", (emp['id'],)).fetchone()
            if username:
                clash = conn.execute("SELECT employee_id FROM employee_accounts WHERE lower(username) = ?", (username,)).fetchone()
                if clash and clash['employee_id'] != emp['id']:
                    return jsonify({'ok': False, 'error': 'اسم المستخدم مستخدم لموظف آخر'}), 400
            if password and len(password) < 6:
                return jsonify({'ok': False, 'error': 'كلمة المرور 6 أحرف على الأقل'}), 400
            if acc:
                if username:
                    conn.execute("UPDATE employee_accounts SET username = ? WHERE id = ?", (username, acc['id']))
                if password:
                    conn.execute("UPDATE employee_accounts SET password_hash = ? WHERE id = ?", (generate_password_hash(password), acc['id']))
                if 'anywhere' in data:
                    conn.execute("UPDATE employee_accounts SET anywhere = ? WHERE id = ?", (1 if data['anywhere'] else 0, acc['id']))
            else:
                if not username or not password:
                    return jsonify({'ok': False, 'error': 'اسم المستخدم وكلمة المرور مطلوبان'}), 400
                conn.execute("INSERT INTO employee_accounts (employee_id, username, password_hash, anywhere) VALUES (?, ?, ?, ?)",
                             (emp['id'], username, generate_password_hash(password), 1 if data.get('anywhere') else 0))
            _audit(conn, 'mobile_account', 'employee', emp['name'])
            conn.commit()
            return jsonify({'ok': True})

        today = now_local().strftime('%Y-%m-%d')
        rows = []
        q = """SELECT e.id, e.name, e.dept, e.device_uid, e.active, a.username, a.active AS acc_active, a.anywhere,
                      a.device_label, a.bound_at, a.last_login_at, a.id AS acc_id
               FROM employees e LEFT JOIN employee_accounts a ON a.employee_id = e.id ORDER BY e.dept, e.name"""
        last = {r['employee_id']: dict(r) for r in conn.execute(
            "SELECT employee_id, kind, time, date FROM mobile_punches WHERE id IN "
            "(SELECT MAX(id) FROM mobile_punches WHERE status = 'accepted' GROUP BY employee_id)").fetchall()}
        for r in conn.execute(q).fetchall():
            d = dict(r)
            if not _employee_scope_ok(d['dept']):
                continue
            lm = last.get(d['id'])
            d['last_move'] = (f"{KINDS.get(lm['kind'])} {lm['time'][:5]}" + ('' if lm['date'] == today else f" ({lm['date']})")) if lm else ''
            d['has_account'] = bool(d['acc_id'])
            rows.append(d)
        return jsonify({'ok': True, 'rows': rows})
    finally:
        conn.close()


@bp.route('/api/mobile/accounts/bulk', methods=['POST'])
@admin_required
def api_accounts_bulk():
    data = request.get_json(silent=True) or {}
    ids = [int(i) for i in (data.get('ids') or []) if str(i).isdigit()]
    action = data.get('action')
    if not ids:
        return jsonify({'ok': False, 'error': 'حدّد موظفاً واحداً على الأقل'}), 400
    conn = db.get_db()
    try:
        emps = [dict(r) for r in conn.execute(
            f"SELECT * FROM employees WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()]
        emps = [e for e in emps if _employee_scope_ok(e['dept'])]
        out, n = [], 0
        for e in emps:
            acc = conn.execute("SELECT * FROM employee_accounts WHERE employee_id = ?", (e['id'],)).fetchone()
            if action == 'create':
                if acc:
                    continue
                username = _unique_username(conn, e['device_uid'] and f"u{e['device_uid']}" or f"emp{e['id']}")
                pw = _gen_password()
                conn.execute("INSERT INTO employee_accounts (employee_id, username, password_hash) VALUES (?, ?, ?)",
                             (e['id'], username, generate_password_hash(pw)))
                out.append({'name': e['name'], 'dept': e['dept'] or '', 'username': username, 'password': pw})
            elif not acc:
                continue
            elif action == 'reset_password':
                pw = _gen_password()
                conn.execute("UPDATE employee_accounts SET password_hash = ? WHERE id = ?", (generate_password_hash(pw), acc['id']))
                out.append({'name': e['name'], 'dept': e['dept'] or '', 'username': acc['username'], 'password': pw})
            elif action == 'unbind':
                conn.execute("UPDATE employee_accounts SET device_hash = NULL, device_label = NULL, bound_at = NULL WHERE id = ?", (acc['id'],))
            elif action in ('enable', 'disable'):
                conn.execute("UPDATE employee_accounts SET active = ? WHERE id = ?", (1 if action == 'enable' else 0, acc['id']))
            elif action in ('anywhere_on', 'anywhere_off'):
                conn.execute("UPDATE employee_accounts SET anywhere = ? WHERE id = ?", (1 if action == 'anywhere_on' else 0, acc['id']))
            elif action == 'delete':
                conn.execute("DELETE FROM employee_accounts WHERE id = ?", (acc['id'],))
            else:
                return jsonify({'ok': False, 'error': 'إجراء غير معروف'}), 400
            n += 1
        _audit(conn, f'mobile_{action}', 'employee_accounts', f'{n} موظف')
        conn.commit()
        return jsonify({'ok': True, 'count': n, 'credentials': out})
    finally:
        conn.close()


@bp.route('/api/employees/bulk-dept', methods=['POST'])
@admin_required
def api_employees_bulk_dept():
    """توزيع الموظفين على الأقسام: نقل المحددين إلى قسم (ومع سجلاتهم السابقة إن طُلب)"""
    data = request.get_json(silent=True) or {}
    ids = [int(i) for i in (data.get('ids') or []) if str(i).isdigit()]
    dept = (data.get('dept') or '').strip()
    if not ids:
        return jsonify({'ok': False, 'error': 'حدّد موظفاً واحداً على الأقل'}), 400
    conn = db.get_db()
    try:
        names = [r['name'] for r in conn.execute(
            f"SELECT name FROM employees WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()]
        conn.execute(f"UPDATE employees SET dept = ?, synced = 0 WHERE id IN ({','.join('?' * len(ids))})", [dept] + ids)
        if data.get('history', True) and names:
            ph = ','.join('?' * len(names))
            conn.execute(f"UPDATE punches SET dept = ?, synced = 0 WHERE name IN ({ph})", [dept] + names)
            conn.execute(f"UPDATE mobile_punches SET dept = ? WHERE name IN ({ph})", [dept] + names)
        _audit(conn, 'bulk_dept', 'employees', f'{len(names)} ← {dept or "بدون قسم"}')
        conn.commit()
        if data.get('history', True):
            _admin().run_full_analysis(conn)
            conn.commit()
        return jsonify({'ok': True, 'count': len(names)})
    finally:
        conn.close()


# =====================================================
#   الإدارة: مواقع العمل
# =====================================================
def _site_payload(data):
    try:
        lat, lng = float(data.get('lat')), float(data.get('lng'))
        radius = int(float(data.get('radius_m') or 150))
    except (TypeError, ValueError):
        return None, 'أدخل خط العرض والطول ونصف القطر بأرقام صحيحة'
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None, 'إحداثيات غير صحيحة'
    if not 20 <= radius <= 20000:
        return None, 'نصف القطر بين 20 و 20000 متر'
    name = (data.get('name') or '').strip()
    if not name:
        return None, 'اسم الموقع مطلوب'
    depts = sorted({str(d).strip() for d in (data.get('depts') or []) if str(d).strip()})
    return {'name': name[:120], 'lat': lat, 'lng': lng, 'radius_m': radius, 'depts_json': json.dumps(depts, ensure_ascii=False),
            'active': 1 if data.get('active', True) else 0}, ''


@bp.route('/api/mobile/sites', methods=['GET', 'POST'])
@admin_required
def api_sites():
    conn = db.get_db()
    try:
        if request.method == 'POST':
            p, err = _site_payload(request.get_json(silent=True) or {})
            if err:
                return jsonify({'ok': False, 'error': err}), 400
            conn.execute("INSERT INTO work_sites (name, lat, lng, radius_m, depts_json, active) VALUES (?, ?, ?, ?, ?, ?)",
                         (p['name'], p['lat'], p['lng'], p['radius_m'], p['depts_json'], p['active']))
            _audit(conn, 'site_add', 'work_site', p['name'])
            conn.commit()
            return jsonify({'ok': True})
        depts = sorted({r['dept'] for r in conn.execute("SELECT DISTINCT dept FROM employees WHERE dept IS NOT NULL AND dept != ''")})
        counts = {}
        for r in conn.execute("SELECT site_id, COUNT(*) AS n FROM mobile_punches WHERE status = 'accepted' GROUP BY site_id"):
            counts[r['site_id']] = r['n']
        rows = site_rows(conn)
        for s in rows:
            s['moves'] = counts.get(s['id'], 0)
        return jsonify({'ok': True, 'rows': rows, 'depts': depts})
    finally:
        conn.close()


@bp.route('/api/mobile/sites/<int:site_id>', methods=['PUT', 'DELETE'])
@admin_required
def api_site_edit(site_id):
    conn = db.get_db()
    try:
        if request.method == 'DELETE':
            conn.execute("DELETE FROM work_sites WHERE id = ?", (site_id,))
            _audit(conn, 'site_delete', 'work_site', str(site_id))
        else:
            data = request.get_json(silent=True) or {}
            if set(data) == {'active'}:
                conn.execute("UPDATE work_sites SET active = ? WHERE id = ?", (1 if data['active'] else 0, site_id))
            else:
                p, err = _site_payload(data)
                if err:
                    return jsonify({'ok': False, 'error': err}), 400
                conn.execute("UPDATE work_sites SET name = ?, lat = ?, lng = ?, radius_m = ?, depts_json = ?, active = ? WHERE id = ?",
                             (p['name'], p['lat'], p['lng'], p['radius_m'], p['depts_json'], p['active'], site_id))
            _audit(conn, 'site_edit', 'work_site', str(site_id))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


@bp.route('/api/mobile/settings', methods=['GET', 'POST'])
@admin_required
def api_mobile_settings():
    keys = ('mobile_enabled', 'mobile_bind_device', 'mobile_max_accuracy', 'mobile_require_geofence', 'mobile_leave_deduct')
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        for k in keys:
            if k in data:
                v = data[k]
                if k == 'mobile_max_accuracy':
                    try:
                        v = str(max(10, min(1000, int(float(v)))))
                    except (TypeError, ValueError):
                        continue
                else:
                    v = '1' if v in (True, 1, '1', 'true', 'on') else '0'
                db.set_setting(k, v)
        return jsonify({'ok': True})
    cfg = settings()
    return jsonify({'ok': True, 'settings': {k: cfg.get(k) for k in keys}})


# =====================================================
#   الإدارة: سجل حركات الهاتف + المتابعة المباشرة + التصدير
# =====================================================
def _punch_query(args):
    today = now_local().strftime('%Y-%m-%d')
    d_from, d_to = args.get('from') or today, args.get('to') or args.get('from') or today
    where, params = ["date BETWEEN ? AND ?"], [d_from, d_to]
    for key, col in (('dept', 'dept'), ('name', 'name'), ('kind', 'kind'), ('status', 'status')):
        if args.get(key):
            where.append(f"{col} = ?")
            params.append(args[key])
    allowed = session.get('allowed_depts') or []
    if allowed:
        where.append(f"dept IN ({','.join('?' * len(allowed))})")
        params += allowed
    return ' AND '.join(where), params, d_from, d_to


@bp.route('/api/mobile/punches')
@admin_required
def api_punches():
    where, params, d_from, d_to = _punch_query(request.args)
    conn = db.get_db()
    try:
        rows = [dict(r) for r in conn.execute(
            f"SELECT * FROM mobile_punches WHERE {where} ORDER BY date DESC, time DESC, id DESC LIMIT 3000", params).fetchall()]
        # الأعداد (بدون فلتر النوع/الحالة حتى تبقى الأزرار صحيحة)
        base_args = {k: v for k, v in request.args.items() if k not in ('kind', 'status')}
        w2, p2, _, _ = _punch_query(base_args)
        counts = {'all': 0, 'rejected': 0, **{k: 0 for k in KINDS}}
        for r in conn.execute(f"SELECT kind, status, COUNT(*) AS n FROM mobile_punches WHERE {w2} GROUP BY kind, status", p2):
            counts['all'] += r['n']
            if r['status'] == 'rejected':
                counts['rejected'] += r['n']
            else:
                counts[r['kind']] = counts.get(r['kind'], 0) + r['n']
        for r in rows:
            r['kind_label'] = KINDS.get(r['kind'], r['kind'])
        names = sorted({r['name'] for r in conn.execute("SELECT DISTINCT name FROM mobile_punches")})
        return jsonify({'ok': True, 'rows': rows, 'counts': counts, 'from': d_from, 'to': d_to, 'names': names})
    finally:
        conn.close()


@bp.route('/api/mobile/live')
@admin_required
def api_live():
    """آخر حركة لكل موظف اليوم + من لم يسجّل بعد (للمتابعة من أي مكان)"""
    today = now_local().strftime('%Y-%m-%d')
    conn = db.get_db()
    try:
        last = {}
        for r in conn.execute("SELECT * FROM mobile_punches WHERE date = ? AND status = 'accepted' ORDER BY time, id", (today,)):
            last[r['employee_id']] = dict(r)
        emps = [dict(r) for r in conn.execute(
            "SELECT e.id, e.name, e.dept FROM employees e JOIN employee_accounts a ON a.employee_id = e.id "
            "WHERE e.active = 1 AND a.active = 1 ORDER BY e.dept, e.name").fetchall()]
        out, state = [], {'in': 0, 'out': 0, 'leave': 0, 'none': 0}
        for e in emps:
            if not _employee_scope_ok(e['dept']):
                continue
            m = last.get(e['id'])
            st = 'none' if not m else ('out' if m['kind'] == 'out' else 'leave' if m['kind'] == 'leave_out' else 'in')
            state[st] += 1
            out.append({**e, 'state': st, 'kind_label': KINDS.get(m['kind']) if m else '', 'time': m['time'][:5] if m else '',
                        'site': m['site_name'] if m else '', 'lat': m['lat'] if m else None, 'lng': m['lng'] if m else None})
        sites = site_rows(conn, True)
        return jsonify({'ok': True, 'date': today, 'rows': out, 'state': state, 'total': len(out),
                        'sites': [{'name': s['name'], 'lat': s['lat'], 'lng': s['lng'], 'radius': s['radius_m']} for s in sites]})
    finally:
        conn.close()


@bp.route('/api/mobile/punches/export')
@admin_required
def api_punches_export():
    where, params, d_from, d_to = _punch_query(request.args)
    conn = db.get_db()
    try:
        rows = conn.execute(f"SELECT * FROM mobile_punches WHERE {where} ORDER BY date, time, id", params).fetchall()
    finally:
        conn.close()
    header = ['التاريخ', 'الوقت', 'الموظف', 'القسم', 'الحركة', 'الحالة', 'السبب', 'الموقع', 'المسافة (م)', 'دقة GPS (م)',
              'خط العرض', 'خط الطول', 'الهاتف', 'IP']
    data = [[r['date'], r['time'], r['name'], r['dept'], KINDS.get(r['kind'], r['kind']),
             'مقبولة' if r['status'] == 'accepted' else 'مرفوضة', r['reason'] or '', r['site_name'] or '',
             r['distance_m'], r['accuracy'], r['lat'], r['lng'], r['device_label'] or '', r['ip'] or ''] for r in rows]
    fname = f'mobile-punches-{d_from}_{d_to}'
    if request.args.get('format') == 'xlsx':
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        wb = Workbook()
        ws = wb.active
        ws.title = 'حركات الهاتف'
        ws.sheet_view.rightToLeft = True
        ws.append(header)
        for c in ws[1]:
            c.font = Font(bold=True, color='FFFFFF')
            c.fill = PatternFill('solid', fgColor='1B6E8C')
        for row in data:
            ws.append(row)
        for i, w in enumerate((12, 10, 26, 18, 14, 10, 40, 20, 10, 10, 12, 12, 22, 16), 1):
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
        ws.freeze_panes = 'A2'
        ws.auto_filter.ref = ws.dimensions
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return send_file(buf, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                         as_attachment=True, download_name=fname + '.xlsx')
    s = io.StringIO()
    s.write('﻿')
    w = csv.writer(s)
    w.writerow(header)
    w.writerows(data)
    return send_file(io.BytesIO(s.getvalue().encode('utf-8')), mimetype='text/csv', as_attachment=True, download_name=fname + '.csv')
