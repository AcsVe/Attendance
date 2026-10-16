"""
إشعارات أندرويد لتطبيق الإدارة (RAS Admin).

• عند فتح لوحة التحكم داخل تطبيق الإدارة، تطلب الصفحة «رمز إشعارات» لهذا المستخدم وتسلّمه للتطبيق.
• يسأل التطبيق الخادم في الخلفية (كل ربع ساعة تقريباً، حتى وهو مغلق) عن الجديد منذ آخر مرة:
  تنبيهات التواجد، طلبات الخروج المؤقت بانتظار الموافقة، طلبات نسيان كلمة المرور، وأجهزة بصمة جديدة.
• الطلب موقّع بمفتاح التطبيق، والرمز يُحفظ في الخادم مشفّراً (hash) ويُلغى بحذف المستخدم.
"""
import hashlib
import hmac
import json
import secrets
import time

from flask import Blueprint, jsonify, request, session

import db

bp = Blueprint('admin_notes', __name__)


def init_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS user_notify_tokens (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        last_pull_at TEXT,
        last_event_id INTEGER,
        last_leave_id INTEGER,
        last_reset_id INTEGER,
        last_adms_at TEXT
    )''')


def _h(t):
    return hashlib.sha256(('notify:' + t).encode()).hexdigest()


def _max(conn, sql):
    try:
        return conn.execute(sql).fetchone()[0] or 0
    except Exception:
        return 0


@bp.route('/api/my/notify-token', methods=['POST'])
def api_notify_token():
    """رمز إشعارات لهذا المستخدم على هذا الهاتف (يُطلب من صفحة لوحة التحكم داخل تطبيق الإدارة)"""
    if not session.get('user_id'):
        return jsonify({'ok': False, 'error': 'يرجى تسجيل الدخول أولاً'}), 401
    tok = secrets.token_hex(32)
    conn = db.get_db()
    try:
        # نبدأ من «الآن» حتى لا تصل دفعة إشعارات قديمة عند أول تشغيل
        conn.execute("INSERT INTO user_notify_tokens (token_hash, user_id, last_event_id, last_leave_id, last_reset_id, last_adms_at) "
                     "VALUES (?, ?, ?, ?, ?, datetime('now'))",
                     (_h(tok), session['user_id'], _max(conn, "SELECT MAX(id) FROM presence_events"),
                      _max(conn, "SELECT MAX(id) FROM leave_requests"), _max(conn, "SELECT MAX(id) FROM password_reset_requests")))
        conn.commit()
        return jsonify({'ok': True, 'token': tok})
    finally:
        conn.close()


def _signed():
    from mobile import APP_KEY
    raw = request.get_data() or b''
    ts = request.headers.get('X-App-Ts', '')
    good = hmac.new(APP_KEY.encode(), raw + b'|' + ts.encode(), hashlib.sha256).hexdigest()
    try:
        fresh = abs(time.time() * 1000 - float(ts)) < 600000
    except ValueError:
        fresh = False
    if not (fresh and hmac.compare_digest(good, request.headers.get('X-App-Sig', ''))):
        return None
    try:
        return json.loads(raw.decode('utf-8') or '{}')
    except ValueError:
        return None


_KIND = {'outside': 'خارج موقع العمل', 'no_location': 'خدمة الموقع متوقفة', 'no_signal': 'انقطع هاتفه',
         'missed_check': 'لم يردّ على فحص الحضور', 'failed_check': 'فشل فحص الحضور',
         'leave_overdue': 'تجاوز وقت العودة', 'leave_not_returned': 'لم يعد من الخروج'}


@bp.route('/api/admin/notes/pull', methods=['POST'])
def api_admin_notes_pull():
    d = _signed()
    if d is None:
        return jsonify({'ok': False, 'error': 'توقيع غير صحيح'}), 403
    tok = str(d.get('token') or '')
    conn = db.get_db()
    try:
        t = conn.execute("SELECT * FROM user_notify_tokens WHERE token_hash = ?", (_h(tok),)).fetchone() if len(tok) >= 32 else None
        user = conn.execute("SELECT * FROM users WHERE id = ?", (t['user_id'],)).fetchone() if t else None
        if not t or not user:
            return jsonify({'ok': False, 'stop': True}), 401
        is_admin = (user['role'] or '') == 'admin'
        can_emp = is_admin or bool(user['can_manage_employees'])
        notes = []
        ev_max = _max(conn, "SELECT MAX(id) FROM presence_events")
        lv_max = _max(conn, "SELECT MAX(id) FROM leave_requests")
        rr_max = _max(conn, "SELECT MAX(id) FROM password_reset_requests")
        if is_admin:
            rows = conn.execute("SELECT name, kind FROM presence_events WHERE id > ? AND id <= ? ORDER BY id",
                                (t['last_event_id'] or 0, ev_max)).fetchall()
            if rows:
                names = [f"{r['name']} ({_KIND.get(r['kind'], r['kind'])})" for r in rows[:4]]
                more = f" و{len(rows) - 4} غيرهم" if len(rows) > 4 else ''
                notes.append({'id': 900000 + ev_max % 100000, 'title': f'تنبيهات التواجد: {len(rows)}',
                              'body': '، '.join(names) + more})
            rr = conn.execute("SELECT COUNT(*) FROM password_reset_requests WHERE id > ? AND id <= ? AND status = 'pending'",
                              (t['last_reset_id'] or 0, rr_max)).fetchone()[0]
            if rr:
                notes.append({'id': 800000 + rr_max % 100000, 'title': 'طلبات نسيان كلمة المرور',
                              'body': f'{rr} طلب جديد بانتظار المعالجة'})
            ad = conn.execute("SELECT COUNT(*) FROM adms_devices WHERE approved = 0 AND created_at > ?",
                              (t['last_adms_at'] or '',)).fetchone()[0] if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'adms_devices'").fetchone() else 0
            if ad:
                notes.append({'id': 700001, 'title': 'جهاز بصمة جديد', 'body': f'{ad} جهاز يرسل عبر الإنترنت بانتظار الموافقة'})
        if can_emp:
            rows = conn.execute("SELECT name, from_time, to_time FROM leave_requests WHERE id > ? AND id <= ? AND status = 'pending' ORDER BY id",
                                (t['last_leave_id'] or 0, lv_max)).fetchall()
            if rows:
                names = [f"{r['name']} {r['from_time']}–{r['to_time']}" for r in rows[:4]]
                notes.append({'id': 600000 + lv_max % 100000, 'title': f'طلبات خروج مؤقت: {len(rows)}',
                              'body': '، '.join(names) + (f" و{len(rows) - 4} غيرها" if len(rows) > 4 else '')})
        conn.execute("UPDATE user_notify_tokens SET last_pull_at = datetime('now'), last_event_id = ?, last_leave_id = ?, "
                     "last_reset_id = ?, last_adms_at = datetime('now') WHERE token_hash = ?", (ev_max, lv_max, rr_max, t['token_hash']))
        conn.commit()
        return jsonify({'ok': True, 'notes': notes})
    finally:
        conn.close()
