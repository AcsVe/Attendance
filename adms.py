"""
استقبال البصمات من أجهزة ZKTeco عبر الإنترنت (بروتوكول ADMS / «Cloud Server» / iclock).

الفكرة: بدل أن يتصل الخادم بالجهاز داخل شبكة المدرسة (يتعذّر إن كان الخادم على شبكة أخرى
أو على الهاتف الاحتياطي)، يُضبط الجهاز نفسه ليرسل كل بصمة إلى عنوان الموقع.

إعداد الجهاز: القائمة ← الاتصال ← Cloud Server Setting (أو ADMS):
    Server Address = 3.iajaward.org   Server Port = 80   (HTTPS إن كان الجهاز يدعمه: 443)

الأمان: أي جهاز جديد يظهر «بانتظار الموافقة» ولا تُقبل بياناته حتى يوافق عليه المدير
(الجهاز يحتفظ بالبصمات ويعيد إرسالها بعد الموافقة — لا يُفقد شيء).
"""
import threading
import time
from datetime import datetime

from flask import Blueprint, request, jsonify, Response, session

import db

bp = Blueprint('adms', __name__)
_ANALYZE_LOCK = threading.Lock()
_last_analyze = [0.0]


def init_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS adms_devices (
        sn TEXT PRIMARY KEY,
        name TEXT,
        approved INTEGER NOT NULL DEFAULT 0,
        last_seen TEXT,
        last_ip TEXT,
        att_stamp TEXT DEFAULT '0',
        punches INTEGER NOT NULL DEFAULT 0,
        model TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS adms_logs (
        sn TEXT NOT NULL,
        pin TEXT NOT NULL,
        ts TEXT NOT NULL,
        status TEXT,
        verify TEXT,
        matched TEXT,
        received_at TEXT DEFAULT (datetime('now')),
        UNIQUE (sn, pin, ts)
    )''')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_adms_logs_ts ON adms_logs (ts)")
    # البصمات السابقة الواصلة عبر الإنترنت → جدول أوقات البصمات (مرة واحدة؛ المكرر يُتجاهل)
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS device_punch_times (
            name TEXT NOT NULL, date TEXT NOT NULL, time TEXT NOT NULL, source TEXT,
            PRIMARY KEY (name, date, time))''')
        conn.execute("INSERT OR IGNORE INTO device_punch_times (name, date, time, source) "
                     "SELECT matched, substr(ts, 1, 10), substr(ts, 12, 8), 'adms' FROM adms_logs WHERE COALESCE(matched, '') != ''")
    except Exception:   # noqa: BLE001 — الجدول يُنشأ في db.init_db
        pass


def _text(body, status=200):
    return Response(body, status=status, mimetype='text/plain')


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _client_ip():
    return (request.headers.get('CF-Connecting-IP') or request.remote_addr or '')[:45]


def _touch(conn, sn):
    """يسجّل ظهور الجهاز (ويضيفه بانتظار الموافقة إن كان جديداً). يرجع صف الجهاز."""
    sn = (sn or '').strip()[:64]
    if not sn:
        return None
    row = conn.execute("SELECT * FROM adms_devices WHERE sn = ?", (sn,)).fetchone()
    if row is None:
        conn.execute("INSERT INTO adms_devices (sn, name, last_seen, last_ip) VALUES (?, ?, ?, ?)",
                     (sn, f'جهاز {sn[-6:]}', _now(), _client_ip()))
    else:
        conn.execute("UPDATE adms_devices SET last_seen = ?, last_ip = ? WHERE sn = ?", (_now(), _client_ip(), sn))
    conn.commit()
    return conn.execute("SELECT * FROM adms_devices WHERE sn = ?", (sn,)).fetchone()


# ---------------------------------------------------------------
#   نقاط الاتصال التي يستدعيها الجهاز (بلا تسجيل دخول — الحماية بالموافقة على الرقم التسلسلي)
# ---------------------------------------------------------------
@bp.route('/iclock/cdata', methods=['GET', 'POST'])
@bp.route('/iclock/cdata.aspx', methods=['GET', 'POST'])
def iclock_cdata():
    sn = request.args.get('SN', '')
    conn = db.get_db()
    try:
        dev = _touch(conn, sn)
        if dev is None:
            return _text('ERROR', 400)
        if request.method == 'GET':
            # مصافحة الجهاز: نرسل إعداداته (إرسال فوري لكل بصمة، ومن آخر نقطة استُلمت)
            stamp = dev['att_stamp'] if dev['approved'] else '0'
            body = (f"GET OPTION FROM: {dev['sn']}\nATTLOGStamp={stamp or 0}\nOPERLOGStamp=9999\nATTPHOTOStamp=9999\n"
                    "ErrorDelay=60\nDelay=10\nTransTimes=00:00;12:00\nTransInterval=1\n"
                    "TransFlag=TransData AttLog\nRealtime=1\nEncrypt=None\n")
            return _text(body)
        table = (request.args.get('table') or '').upper()
        raw = request.get_data(as_text=True) or ''
        if table != 'ATTLOG':
            return _text('OK')          # سجلات العمليات والصور: لا نحتاجها
        if not dev['approved']:
            return _text('ERROR: device not approved', 403)   # يحتفظ الجهاز بها ويعيد الإرسال لاحقاً
        n = _store_attlog(conn, dev, raw, request.args.get('Stamp'))
        return _text(f'OK: {n}')
    finally:
        conn.close()


@bp.route('/iclock/getrequest', methods=['GET'])
@bp.route('/iclock/getrequest.aspx', methods=['GET'])
def iclock_getrequest():
    conn = db.get_db()
    try:
        _touch(conn, request.args.get('SN', ''))
    finally:
        conn.close()
    return _text('OK')


@bp.route('/iclock/devicecmd', methods=['POST'])
@bp.route('/iclock/devicecmd.aspx', methods=['POST'])
def iclock_devicecmd():
    return _text('OK')


def _store_attlog(conn, dev, raw, stamp):
    """سطور ATTLOG: PIN \t YYYY-MM-DD HH:MM:SS \t Status \t Verify ..."""
    import app as app_module   # استيراد مؤجَّل لتفادي الحلقة
    uid_map = app_module._uid_employee_map(conn)
    by_day = {}
    count = 0
    for line in raw.splitlines():
        parts = line.strip().split('\t')
        if len(parts) < 2:
            continue
        pin, ts = parts[0].strip(), parts[1].strip()
        try:
            dt = datetime.strptime(ts[:19], '%Y-%m-%d %H:%M:%S')
        except ValueError:
            continue
        name = uid_map.get(pin)
        cur = conn.execute("INSERT OR IGNORE INTO adms_logs (sn, pin, ts, status, verify, matched) VALUES (?, ?, ?, ?, ?, ?)",
                           (dev['sn'], pin, dt.strftime('%Y-%m-%d %H:%M:%S'), parts[2] if len(parts) > 2 else '',
                            parts[3] if len(parts) > 3 else '', name or ''))
        count += 1
        if cur.rowcount and name:
            by_day.setdefault((name, dt.strftime('%Y-%m-%d')), []).append(dt.strftime('%H:%M:%S'))
            conn.execute("INSERT OR IGNORE INTO device_punch_times (name, date, time, source) VALUES (?, ?, ?, 'adms')",
                         (name, dt.strftime('%Y-%m-%d'), dt.strftime('%H:%M:%S')))
    depts = {r['name']: r['dept'] or '' for r in conn.execute("SELECT name, dept FROM employees")}
    for (name, d), times in by_day.items():
        lo, hi = min(times), max(times)
        ex = conn.execute("SELECT id, time_in, time_out FROM punches WHERE name = ? AND date = ? AND batch_id = 'adms'",
                          (name, d)).fetchone()
        if ex:
            t_in = min(ex['time_in'] or lo, lo)
            t_out = max(ex['time_out'] or ex['time_in'] or hi, hi)
            conn.execute("UPDATE punches SET time_in = ?, time_out = ? WHERE id = ?", (t_in, t_out if t_out != t_in else '', ex['id']))
        else:
            conn.execute("INSERT INTO punches (name, date, dept, time_in, time_out, batch_id) VALUES (?, ?, ?, ?, ?, 'adms')",
                         (name, d, depts.get(name, ''), lo, hi if hi != lo else ''))
    conn.execute("UPDATE adms_devices SET punches = punches + ?, att_stamp = COALESCE(?, att_stamp) WHERE sn = ?",
                 (count, stamp, dev['sn']))
    if by_day:
        conn.execute("INSERT INTO app_settings (key, value) VALUES ('adms_dirty', '1') "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value")
    conn.commit()
    if by_day:
        # التحليل في الخلفية: الجهاز يتلقى «OK» فوراً ولا ينتظر، حتى مع طابور موظفين
        threading.Thread(target=flush, kwargs={'throttle': 60}, daemon=True).start()
    return count


def flush(throttle=0):
    """تحليل البيانات بعد وصول بصمات جديدة (بحد أقصى مرة كل دقيقة؛ والمجدول يُكمل ما تبقّى)"""
    if db.get_setting('adms_dirty') != '1':
        return
    if throttle and time.time() - _last_analyze[0] < throttle:
        return
    if not _ANALYZE_LOCK.acquire(blocking=False):
        return
    try:
        _last_analyze[0] = time.time()
        db.set_setting('adms_dirty', '0')
        import app as app_module
        conn = db.get_db()
        try:
            app_module.run_full_analysis(conn)
            conn.commit()
        finally:
            conn.close()
    except Exception:
        db.set_setting('adms_dirty', '1')
    finally:
        _ANALYZE_LOCK.release()


# ---------------------------------------------------------------
#   إدارة الأجهزة المرسِلة (لوحة التحكم)
# ---------------------------------------------------------------
def _admin_ok():
    return bool(session.get('user_id')) and (session.get('role') == 'admin' or session.get('can_push_devices'))


@bp.route('/api/adms/devices', methods=['GET'])
def api_adms_devices():
    if not session.get('user_id'):
        return jsonify({'ok': False, 'error': 'يرجى تسجيل الدخول أولاً'}), 401
    conn = db.get_db()
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM adms_devices ORDER BY approved, last_seen DESC")]
        today = datetime.now().strftime('%Y-%m-%d')
        for r in rows:
            r['today'] = conn.execute("SELECT COUNT(*) FROM adms_logs WHERE sn = ? AND ts LIKE ?", (r['sn'], today + '%')).fetchone()[0]
            r['unmatched'] = conn.execute("SELECT COUNT(DISTINCT pin) FROM adms_logs WHERE sn = ? AND matched = ''", (r['sn'],)).fetchone()[0]
        host = request.host
        return jsonify({'ok': True, 'rows': rows, 'host': host})
    finally:
        conn.close()


@bp.route('/api/adms/devices/bulk', methods=['POST'])
def api_adms_bulk():
    if not _admin_ok():
        return jsonify({'ok': False, 'error': 'ليس لديك صلاحية لهذا الإجراء'}), 403
    d = request.get_json(silent=True) or {}
    sns = [str(s)[:64] for s in (d.get('sns') or []) if s]
    action = d.get('action')
    if not sns or action not in ('approve', 'block', 'delete', 'rename', 'resend'):
        return jsonify({'ok': False, 'error': 'طلب غير صالح'}), 400
    conn = db.get_db()
    try:
        for sn in sns:
            if action == 'approve':
                conn.execute("UPDATE adms_devices SET approved = 1 WHERE sn = ?", (sn,))
            elif action == 'block':
                conn.execute("UPDATE adms_devices SET approved = 0 WHERE sn = ?", (sn,))
            elif action == 'delete':
                conn.execute("DELETE FROM adms_devices WHERE sn = ?", (sn,))
            elif action == 'resend':      # يطلب من الجهاز إعادة إرسال كل سجلاته عند الاتصال القادم
                conn.execute("UPDATE adms_devices SET att_stamp = '0' WHERE sn = ?", (sn,))
            elif action == 'rename':
                name = (d.get('name') or '').strip()[:60]
                if name:
                    conn.execute("UPDATE adms_devices SET name = ? WHERE sn = ?", (name, sn))
        try:
            import app as app_module
            app_module.log_audit(conn, f'adms_{action}', 'device', new_value=', '.join(sns)[:500])
        except Exception:
            pass
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


# ===== تنبيه توقف جهاز البصمة عن الإرسال أثناء الدوام =====
def offline_check():
    """كل دقيقة من المجدول: جهاز معتمد لم يتصل منذ N دقيقة خلال الدوام ← تنبيه للإدارة، ثم تنبيه عند عودته.
    (أجهزة ADMS تتصل كل نصف دقيقة تقريباً حتى بلا بصمات، فانقطاعها يعني توقف الجهاز أو شبكته)"""
    if db.get_setting('device_offline_alert', '1') != '1':
        return
    try:
        limit = max(5, int(db.get_setting('device_offline_min', '30') or 30))
    except ValueError:
        limit = 30
    import admin_notes
    import mobile
    conn = db.get_db()
    try:
        cols = {r['name'] for r in conn.execute("PRAGMA table_info(adms_devices)")}
        if 'offline_alerted' not in cols:
            conn.execute("ALTER TABLE adms_devices ADD COLUMN offline_alerted INTEGER NOT NULL DEFAULT 0")
        if mobile.outage_hold(conn):
            conn.commit()
            return      # الخادم نفسه كان متوقفاً/بلا إنترنت: ليس عطلاً في الأجهزة
        now = datetime.now()
        cfg = db.get_all_settings()
        wd = now.weekday()
        work_day = wd != 4 and not (wd == 5 and cfg.get('sat_time_enabled') != '1') and \
            not conn.execute("SELECT 1 FROM official_holidays WHERE date = ?", (now.strftime('%Y-%m-%d'),)).fetchone()
        sat = wd == 5 and cfg.get('sat_time_enabled') == '1'
        start = (cfg.get('sat_attendance_time') if sat else '') or cfg.get('attendance_time') or '08:00'
        end = (cfg.get('sat_departure_time') if sat else '') or cfg.get('departure_time') or '15:00'
        in_hours = work_day and start <= now.strftime('%H:%M') <= end
        for d in conn.execute("SELECT * FROM adms_devices WHERE approved = 1").fetchall():
            try:
                gap = (now - datetime.strptime((d['last_seen'] or '')[:19], '%Y-%m-%d %H:%M:%S')).total_seconds() / 60
            except ValueError:
                continue
            name = d['name'] or d['sn']
            if gap >= limit and in_hours and not d['offline_alerted']:
                conn.execute("UPDATE adms_devices SET offline_alerted = 1 WHERE sn = ?", (d['sn'],))
                admin_notes.add_alert(conn, 'device_offline', f'جهاز البصمة «{name}» لا يتصل',
                                      f"آخر اتصال {d['last_seen'][11:16]} (قبل {int(gap)} دقيقة) — تحقق من كهرباء الجهاز وشبكته. "
                                      "البصمات محفوظة فيه وتصل عند عودته.", '/dashboard#devices')
                conn.execute("INSERT INTO audit_log (username, action_type, target_type, new_value, timestamp) VALUES (?, ?, ?, ?, ?)",
                             ('النظام', 'device_offline', 'device', f"{name}: آخر اتصال {d['last_seen']}", now.strftime('%Y-%m-%d %H:%M:%S')))
            elif gap < 3 and d['offline_alerted']:
                conn.execute("UPDATE adms_devices SET offline_alerted = 0 WHERE sn = ?", (d['sn'],))
                admin_notes.add_alert(conn, 'device_online', f'عاد جهاز البصمة «{name}» للاتصال',
                                      'تصل البصمات المحفوظة فيه تلقائياً.', '/dashboard#devices')
        conn.commit()
    finally:
        conn.close()
