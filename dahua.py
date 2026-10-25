"""
أجهزة Dahua للحضور (مثل ASA3223A-W بصمة الوجه) — بجانب أجهزة ZKTeco في القاعدة نفسها.

ثلاث طرق، وكلها تكتب في الجداول نفسها (dahua_logs ثم punches / device_punch_times بالمصدر 'dahua'):
  1) السحب داخل شبكة المدرسة: واجهة CGI الرسمية في الجهاز (HTTP + Digest)
       /cgi-bin/recordFinder.cgi?action=find&name=AccessControlCardRec&StartTime=..&EndTime=..
     قراءة فقط: لا يتوقف الجهاز ولا تُمسح سجلاته. ويمكن جعله تلقائياً كل بضع دقائق.
  2) الإرسال عبر الإنترنت: الجهاز (Auto Upload / HTTP Push) يرسل إلى
       https://3.iajaward.org/dahua/push/<الرمز>
     صيغ الرسائل تختلف بين إصدارات البرنامج الثابت، فالمستقبِل يقرأ JSON وmultipart وkey=value،
     ويحفظ آخر رسالة خام لكل مرسِل للتشخيص. المرسِل بلا رمز صحيح يظهر «بانتظار الموافقة»
     وتُحفظ بصماته معلّقة ثم تُطبَّق كلها عند الموافقة (لا يضيع شيء).
  3) رفع ملف: تقرير السجلات المُصدَّر من SmartPSS Lite / SmartPSS AC (xlsx / xls / csv).
     (تصدير USB من الجهاز نفسه مشفَّر ولا يُقرأ خارج برامج Dahua.)

مطابقة الموظف: رقم المستخدم في الجهاز (User ID) = «رقم البصمة» للموظف في النظام (device_uid)،
وإن لم يوجد يُطابَق بالاسم المطابق تماماً (في الملفات).
"""
import base64
import hashlib
import io
import json
import re
import secrets
import threading
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request, jsonify, session

import db

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo('Asia/Amman')
except Exception:   # noqa: BLE001 — بلا tzdata: نعتمد توقيت الخادم المحلي
    _TZ = None

bp = Blueprint('dahua', __name__)
SOURCE = 'dahua'
_PULL_LOCK = threading.Lock()
MAX_HELD_PER_SENDER = 5000      # بصمات معلّقة لمرسِل غير معتمد (حماية من الإغراق)
MAX_PENDING_SENDERS = 30
REC_PAGE = 500


# ---------------------------------------------------------------
#   الجداول (ترحيل آلي عند الإقلاع — لا يمس بيانات ZKTeco)
# ---------------------------------------------------------------
def init_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS dahua_devices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        host TEXT NOT NULL,
        port INTEGER NOT NULL DEFAULT 80,
        use_https INTEGER NOT NULL DEFAULT 0,
        username TEXT NOT NULL DEFAULT 'admin',
        password_enc TEXT,
        time_mode TEXT NOT NULL DEFAULT 'utc',
        auto_pull INTEGER NOT NULL DEFAULT 1,
        active INTEGER NOT NULL DEFAULT 1,
        location TEXT,
        model TEXT,
        serial TEXT,
        last_pull TEXT,
        last_rec_ts TEXT,
        last_error TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS dahua_senders (
        key TEXT PRIMARY KEY,
        name TEXT,
        approved INTEGER NOT NULL DEFAULT 0,
        time_mode TEXT NOT NULL DEFAULT 'utc',
        last_seen TEXT,
        last_ip TEXT,
        messages INTEGER NOT NULL DEFAULT 0,
        punches INTEGER NOT NULL DEFAULT 0,
        last_raw TEXT,
        last_note TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS dahua_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        user_id TEXT NOT NULL,
        ts TEXT NOT NULL,
        matched TEXT NOT NULL DEFAULT '',
        applied INTEGER NOT NULL DEFAULT 0,
        received_at TEXT DEFAULT (datetime('now')),
        UNIQUE (user_id, ts)
    )''')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dahua_logs_src ON dahua_logs (source, applied)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dahua_logs_ts ON dahua_logs (ts)")


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _admin_ok():
    return bool(session.get('user_id')) and (session.get('role') == 'admin' or session.get('can_push_devices'))


def _deny():
    if not session.get('user_id'):
        return jsonify({'ok': False, 'error': 'يرجى تسجيل الدخول أولاً'}), 401
    return jsonify({'ok': False, 'error': 'ليس لديك صلاحية لهذا الإجراء'}), 403


# ---------------------------------------------------------------
#   كلمة مرور الجهاز: مشفّرة في القاعدة بمفتاح الجلسات، ولا تُعاد للواجهة أبداً
# ---------------------------------------------------------------
def _fernet():
    from cryptography.fernet import Fernet
    import app as app_module
    raw = hashlib.sha256(('dahua|' + str(app_module.app.secret_key)).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def _enc(pw):
    return _fernet().encrypt((pw or '').encode()).decode() if pw else ''


def _dec(token):
    if not token:
        return ''
    try:
        return _fernet().decrypt(token.encode()).decode()
    except Exception:   # noqa: BLE001 — تغيّر مفتاح الجلسات
        return None


# ---------------------------------------------------------------
#   الوقت: Dahua يرسل ثواني (epoch). أغلب الأجهزة بتوقيت UTC الصحيح، وبعضها يرسل
#   الوقت المحلي على أنه UTC — الخيار time_mode لكل جهاز ('utc' أو 'local').
# ---------------------------------------------------------------
def epoch_to_local(sec, mode='utc'):
    sec = int(float(sec))
    if sec > 10 ** 11:          # ميلي ثانية
        sec //= 1000
    if mode == 'local':
        return datetime(1970, 1, 1) + timedelta(seconds=sec)
    dt = datetime.fromtimestamp(sec, timezone.utc)
    return dt.astimezone(_TZ).replace(tzinfo=None) if _TZ else datetime.fromtimestamp(sec)


def local_to_epoch(dt, mode='utc'):
    if mode == 'local':
        return int((dt - datetime(1970, 1, 1)).total_seconds())
    if _TZ:
        return int(dt.replace(tzinfo=_TZ).timestamp())
    return int(dt.timestamp())


def parse_time(value, mode='utc'):
    """ثوانٍ، أو نص «2026-10-25 07:30:00» / ISO / «2026/10/25 07:30» (يُعامل النص كوقت محلي)"""
    if value is None:
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and re.fullmatch(r'\s*\d{9,13}(\.\d+)?\s*', value)):
        try:
            return epoch_to_local(value, mode)
        except (ValueError, OverflowError, OSError):
            return None
    s = str(value).strip().replace('T', ' ').replace('/', '-')
    s = re.sub(r'(Z|[+-]\d{2}:?\d{2})$', '', s).strip()
    s = s.split('.')[0]
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%d-%m-%Y %H:%M:%S', '%d-%m-%Y %H:%M'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------
#   الحفظ المشترك لكل الطرق
# ---------------------------------------------------------------
def _name_map(conn):
    import app as app_module
    return app_module._uid_employee_map(conn)


def store(conn, source, items, apply=True, names=None):
    """items: [(user_id, datetime, name_hint)] → dahua_logs، ثم (إن apply) punches وdevice_punch_times.
    يرجع dict: received / new / matched / unmatched (أرقام غير مطابقة)."""
    uid_map = _name_map(conn)
    by_name = names if names is not None else {}
    new = matched_new = 0
    unmatched = set()
    for uid, dt, hint in items:
        uid = str(uid or '').strip()[:40]
        if not uid or dt is None:
            continue
        if re.fullmatch(r'\d+\.0', uid):
            uid = uid[:-2]
        name = uid_map.get(uid) or uid_map.get(uid.lstrip('0') or '0') or (by_name.get(hint) if hint else None) or ''
        cur = conn.execute("INSERT OR IGNORE INTO dahua_logs (source, user_id, ts, matched) VALUES (?, ?, ?, ?)",
                           (source, uid, dt.strftime('%Y-%m-%d %H:%M:%S'), name))
        if cur.rowcount:
            new += 1
            if name:
                matched_new += 1
            else:
                unmatched.add(uid)
    applied = apply_pending(conn, source) if apply else 0
    return {'received': len(items), 'new': new, 'matched': matched_new, 'applied': applied,
            'unmatched': sorted(unmatched, key=lambda x: (len(x), x))}


def apply_pending(conn, source=None):
    """يطبّق بصمات dahua_logs غير المطبّقة (والمطابقة لموظف) على جداول الحضور — أول/آخر بصمة باليوم"""
    q = "SELECT id, matched, ts FROM dahua_logs WHERE applied = 0 AND matched != ''"
    args = []
    if source:
        q += " AND source = ?"
        args.append(source)
    rows = conn.execute(q, args).fetchall()
    if not rows:
        return 0
    by_day = {}
    for r in rows:
        d, t = r['ts'][:10], r['ts'][11:19]
        by_day.setdefault((r['matched'], d), []).append(t)
        conn.execute("INSERT OR IGNORE INTO device_punch_times (name, date, time, source) VALUES (?, ?, ?, ?)",
                     (r['matched'], d, t, SOURCE))
    depts = {r['name']: r['dept'] or '' for r in conn.execute("SELECT name, dept FROM employees")}
    for (name, d), times in by_day.items():
        lo, hi = min(times), max(times)
        ex = conn.execute("SELECT id, time_in, time_out FROM punches WHERE name = ? AND date = ? AND batch_id = ?",
                          (name, d, SOURCE)).fetchone()
        if ex:
            t_in = min(ex['time_in'] or lo, lo)
            t_out = max(ex['time_out'] or ex['time_in'] or hi, hi)
            conn.execute("UPDATE punches SET time_in = ?, time_out = ? WHERE id = ?",
                         (t_in, t_out if t_out != t_in else '', ex['id']))
        else:
            conn.execute("INSERT INTO punches (name, date, dept, time_in, time_out, batch_id) VALUES (?, ?, ?, ?, ?, ?)",
                         (name, d, depts.get(name, ''), lo, hi if hi != lo else '', SOURCE))
    conn.executemany("UPDATE dahua_logs SET applied = 1 WHERE id = ?", [(r['id'],) for r in rows])
    conn.execute("INSERT INTO app_settings (key, value) VALUES ('adms_dirty', '1') "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value")
    return len(rows)


def rematch(conn):
    """بعد إضافة «رقم البصمة» لموظف: يطابق السجلات غير المطابقة، ثم يطبّقها (إلا المعلّقة لمرسِل غير معتمد)"""
    uid_map = _name_map(conn)
    n = 0
    for r in conn.execute("SELECT id, user_id FROM dahua_logs WHERE matched = ''").fetchall():
        name = uid_map.get(r['user_id']) or uid_map.get(r['user_id'].lstrip('0') or '0')
        if name:
            conn.execute("UPDATE dahua_logs SET matched = ? WHERE id = ?", (name, r['id']))
            n += 1
    approved = {r['key'] for r in conn.execute("SELECT key FROM dahua_senders WHERE approved = 1")}
    for (src,) in conn.execute("SELECT DISTINCT source FROM dahua_logs WHERE applied = 0 AND matched != ''").fetchall():
        if not src.startswith('push:') or src[5:] in approved:
            apply_pending(conn, src)
    return n


def _analyze_soon():
    import adms
    threading.Thread(target=adms.flush, kwargs={'throttle': 60}, daemon=True).start()


# ---------------------------------------------------------------
#   1) السحب داخل الشبكة (CGI)
# ---------------------------------------------------------------
def _kv(text):
    out = {}
    for line in (text or '').splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            out[k.strip()] = v.strip()
    return out


class DahuaError(Exception):
    pass


def _get(dev, path, params=None, timeout=8):
    import requests
    from requests.auth import HTTPDigestAuth
    pw = _dec(dev.get('password_enc'))
    if pw is None:
        raise DahuaError('تعذّر قراءة كلمة مرور الجهاز المحفوظة — أعد إدخالها من «تعديل».')
    scheme = 'https' if dev.get('use_https') else 'http'
    url = f"{scheme}://{dev['host']}:{int(dev.get('port') or (443 if dev.get('use_https') else 80))}{path}"
    try:
        if dev.get('use_https'):
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        r = requests.get(url, params=params, auth=HTTPDigestAuth(dev.get('username') or 'admin', pw),
                         timeout=timeout, verify=False)
    except requests.exceptions.ConnectTimeout:
        raise DahuaError(f"الجهاز {dev['host']} لا يرد (انتهت المهلة) — تأكد أنه على شبكة المدرسة نفسها وأن عنوانه ثابت.")
    except requests.exceptions.ConnectionError:
        raise DahuaError(f"تعذّر الاتصال بالجهاز {dev['host']}:{dev.get('port')} — تحقق من العنوان والمنفذ (الافتراضي 80) واتصال Wi-Fi.")
    except requests.exceptions.RequestException as e:
        raise DahuaError(f'خطأ في الاتصال: {type(e).__name__}')
    if r.status_code == 401:
        raise DahuaError('اسم المستخدم أو كلمة المرور غير صحيحة (حساب الدخول إلى صفحة الجهاز). '
                         'تنبيه: تكرار المحاولات الخاطئة يقفل الحساب في الجهاز مؤقتاً.')
    if r.status_code == 404:
        raise DahuaError('الجهاز لا يدعم هذا الطلب (CGI). فعّل CGI من إعدادات الجهاز: الميزات ← إعدادات الخصوصية ← CGI.')
    if r.status_code >= 400:
        raise DahuaError(f'رد الجهاز بخطأ HTTP {r.status_code}')
    return r.text


def test_device(dev):
    info = _kv(_get(dev, '/cgi-bin/magicBox.cgi', {'action': 'getSystemInfo'}))
    now_dev = _kv(_get(dev, '/cgi-bin/global.cgi', {'action': 'getCurrentTime'})).get('result', '')
    out = {'ok': True, 'model': info.get('deviceType') or info.get('updateSerial') or '',
           'serial': info.get('serialNumber') or '', 'device_time': now_dev, 'server_time': _now()}
    # آخر سجل في الجهاز خلال يومين — ليتأكد المدير أن الوقت المعروض صحيح (خيار التوقيت)
    try:
        recs = fetch_records(dev, datetime.now() - timedelta(days=2), datetime.now() + timedelta(hours=1), limit_pages=3)
        if recs:
            last = max(recs, key=lambda x: x[1])
            out['last_record'] = {'user_id': last[0], 'time': last[1].strftime('%Y-%m-%d %H:%M:%S')}
    except DahuaError as e:
        out['records_error'] = str(e)
    return out


def _parse_records(text, mode):
    groups = {}
    for k, v in _kv(text).items():
        m = re.match(r'records\[(\d+)\]\.(\w+)$', k)
        if m:
            groups.setdefault(int(m.group(1)), {})[m.group(2)] = v
    out = []
    for _, g in sorted(groups.items()):
        status = g.get('Status')
        if status not in (None, '', '1', 'true', 'True'):
            continue        # محاولة مرفوضة (وجه غير معروف…)
        uid = g.get('UserID') or g.get('UserId') or ''
        dt = parse_time(g.get('CreateTime'), mode)
        if uid and dt:
            out.append((uid, dt, g.get('CardName') or ''))
    return out, len(groups)


def fetch_records(dev, start, end, limit_pages=400):
    """يقرأ سجلات الحضور بين وقتين (بالتقسيم إلى صفحات)؛ قراءة فقط"""
    mode = dev.get('time_mode') or 'utc'
    all_recs, seen = [], set()
    t0 = local_to_epoch(start, mode)
    t1 = local_to_epoch(end, mode)
    for _ in range(limit_pages):
        text = _get(dev, '/cgi-bin/recordFinder.cgi', {
            'action': 'find', 'name': 'AccessControlCardRec',
            'StartTime': t0, 'EndTime': t1, 'count': REC_PAGE}, timeout=20)
        recs, raw_n = _parse_records(text, mode)
        if raw_n == 0 and 'found=' not in text and 'records' not in text:
            if 'Error' in text or 'error' in text:
                raise DahuaError('الجهاز رفض طلب السجلات: ' + text.strip()[:120])
        fresh = 0
        for r in recs:
            key = (r[0], r[1])
            if key not in seen:
                seen.add(key)
                all_recs.append(r)
                fresh += 1
        if raw_n < REC_PAGE or not recs:
            break
        nxt = local_to_epoch(max(r[1] for r in recs), mode)
        if nxt <= t0 and not fresh:
            nxt = t0 + 1
        t0 = nxt
    return all_recs


def pull_device(conn, dev, start=None, end=None):
    dev = dict(dev)
    if start is None:
        if dev.get('last_rec_ts'):
            start = datetime.strptime(dev['last_rec_ts'][:19], '%Y-%m-%d %H:%M:%S') - timedelta(minutes=10)
        else:
            start = datetime.now() - timedelta(days=31)
    end = end or (datetime.now() + timedelta(hours=1))
    try:
        recs = fetch_records(dev, start, end)
    except DahuaError as e:
        conn.execute("UPDATE dahua_devices SET last_error = ?, last_pull = ? WHERE id = ?", (str(e), _now(), dev['id']))
        conn.commit()
        return {'device': dev['name'], 'ok': False, 'error': str(e)}
    res = store(conn, f"pull:{dev['id']}", recs)
    last = max((r[1] for r in recs), default=None)
    conn.execute("UPDATE dahua_devices SET last_pull = ?, last_error = '', last_rec_ts = COALESCE(?, last_rec_ts) WHERE id = ?",
                 (_now(), last.strftime('%Y-%m-%d %H:%M:%S') if last else None, dev['id']))
    conn.commit()
    return {'device': dev['name'], 'ok': True, 'count': res['new'], **res}


def pull_all(conn, ids=None, start=None, end=None, auto_only=False):
    q = "SELECT * FROM dahua_devices WHERE active = 1"
    if auto_only:
        q += " AND auto_pull = 1"
    devs = [dict(r) for r in conn.execute(q)]
    if ids:
        ids = {int(i) for i in ids}
        devs = [d for d in devs if d['id'] in ids]
    if not devs:
        return []
    with _PULL_LOCK:
        out = [pull_device(conn, d, start, end) for d in devs]
    if any(r.get('applied') for r in out):
        _analyze_soon()
    return out


def tick():
    """من المجدول كل دقيقة: سحب تلقائي من أجهزة الشبكة كل N دقيقة (قراءة فقط، خفيف على الجهاز)"""
    try:
        every = max(1, int(db.get_setting('dahua_pull_every', '5') or 5))
    except ValueError:
        every = 5
    if db.get_setting('dahua_auto_pull', '1') != '1' or datetime.now().minute % every:
        return
    if _PULL_LOCK.locked():
        return
    conn = db.get_db()
    try:
        pull_all(conn, auto_only=True)
    finally:
        conn.close()


# ---------------------------------------------------------------
#   2) الاستقبال عبر الإنترنت
# ---------------------------------------------------------------
_UID_KEYS = ('UserID', 'UserId', 'userID', 'userId', 'user_id', 'PersonID', 'PersonId', 'personId',
             'EmployeeNo', 'employeeNo', 'EmployeeID')
_TIME_KEYS = ('RealUTC', 'CreateTime', 'UTC', 'EventTime', 'Time', 'DateTime', 'time', 'createTime', 'AttendanceTime')
_SN_KEYS = ('DeviceID', 'DeviceId', 'deviceId', 'SerialNo', 'SerialNumber', 'serialNumber', 'SN', 'sn', 'DevID')


def push_token():
    t = db.get_setting('dahua_push_token', '')
    if not t:
        t = secrets.token_urlsafe(18)
        db.set_setting('dahua_push_token', t)
    return t


def _walk(obj, found, sns, depth=0):
    if depth > 8:
        return
    if isinstance(obj, list):
        for x in obj[:2000]:
            _walk(x, found, sns, depth + 1)
        return
    if not isinstance(obj, dict):
        return
    for k in _SN_KEYS:
        if obj.get(k) and isinstance(obj[k], (str, int)):
            sns.append(str(obj[k]))
    uid = next((obj[k] for k in _UID_KEYS if obj.get(k) not in (None, '')), None)
    if uid is not None and isinstance(uid, (str, int)):
        tkey = next((k for k in _TIME_KEYS if obj.get(k) not in (None, '')), None)
        status = obj.get('Status', obj.get('status'))
        ok = status in (None, '', 1, '1', True, 'true', 'True') and str(obj.get('ErrorCode', '0') or '0') in ('0',)
        if ok:
            found.append({'uid': str(uid), 'time': obj.get(tkey) if tkey else None, 'tkey': tkey,
                          'name': obj.get('CardName') or obj.get('UserName') or obj.get('Name') or ''})
    for v in obj.values():
        if isinstance(v, (dict, list)):
            _walk(v, found, sns, depth + 1)


def _kv_blocks(text):
    """نص key=value (مثل رسائل eventManager)؛ يحوّل events[0].Data.UserID=.. إلى قواميس"""
    groups = {}
    for k, v in _kv(text).items():
        m = re.match(r'(?:\w+\[(\d+)\]\.)?(?:[\w.\[\]]*\.)?(\w+)$', k)
        if m:
            groups.setdefault(m.group(1) or '0', {})[m.group(2)] = v
    return list(groups.values())


def parse_push_body(body, content_type):
    """يرجع (قائمة الأحداث، الأرقام التسلسلية المذكورة، نص خام مختصر للتشخيص)"""
    found, sns, texts = [], [], []
    ct = (content_type or '').lower()
    if 'multipart' in ct:
        m = re.search(r'boundary="?([^";]+)"?', content_type or '', re.I)
        parts = body.split(b'--' + m.group(1).encode()) if m else [body]
        for p in parts:
            head, _, data = p.partition(b'\r\n\r\n')
            if b'image/' in head.lower() or not data.strip():
                continue
            texts.append(data.decode('utf-8', 'replace').strip())
    else:
        texts.append(body.decode('utf-8', 'replace').strip())
    for t in texts:
        t = t.strip().strip('-').strip()
        if not t:
            continue
        parsed = None
        for cand in (t, t[t.find('{'):] if '{' in t else ''):
            if cand:
                try:
                    parsed = json.loads(cand)
                    break
                except ValueError:
                    pass
        if parsed is not None:
            _walk(parsed, found, sns)
        elif '=' in t:
            _walk(_kv_blocks(t), found, sns)
    raw = '\n'.join(texts)
    raw = re.sub(r'([A-Za-z0-9+/=]{200})[A-Za-z0-9+/=]+', r'\1…', raw)     # صور base64
    return found, sns, raw[:4000]


def _client_ip():
    return (request.headers.get('CF-Connecting-IP') or request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
            or request.remote_addr or '')


def _ok_reply():
    return jsonify({'Result': True, 'Code': 200, 'Message': 'OK', 'ok': True})


@bp.route('/dahua/push', methods=['GET', 'POST', 'PUT'], strict_slashes=False)
@bp.route('/dahua/push/<token>', methods=['GET', 'POST', 'PUT'])
@bp.route('/dahua/push/<token>/<path:rest>', methods=['GET', 'POST', 'PUT'])
def push_receive(token=None, rest=None):
    body = request.get_data(cache=False) or b''
    if len(body) > 3_000_000:
        return jsonify({'Result': False, 'Message': 'too large'}), 413
    good_token = bool(token) and secrets.compare_digest(token, push_token())
    if token and not good_token:
        return jsonify({'Result': False, 'Message': 'bad token'}), 403
    if request.method == 'GET' and not body:
        return _ok_reply()      # فحص اتصال/نبضة من الجهاز
    events, sns, raw = parse_push_body(body, request.content_type)
    args = request.args.to_dict()
    if args:
        _walk(args, events, sns)
    sn = (sns[0] if sns else '')[:64]
    key = ('sn:' + sn) if sn else ('ip:' + _client_ip())[:70]
    conn = db.get_db()
    try:
        s = conn.execute("SELECT * FROM dahua_senders WHERE key = ?", (key,)).fetchone()
        if s is None:
            if not good_token and conn.execute("SELECT COUNT(*) FROM dahua_senders WHERE approved = 0").fetchone()[0] >= MAX_PENDING_SENDERS:
                return jsonify({'Result': False, 'Message': 'pending limit'}), 429
            conn.execute("INSERT INTO dahua_senders (key, name, approved, time_mode) VALUES (?, ?, ?, 'auto')",
                         (key, ('جهاز Dahua ' + (sn[-6:] if sn else _client_ip())), 1 if good_token else 0))
            s = conn.execute("SELECT * FROM dahua_senders WHERE key = ?", (key,)).fetchone()
            if not good_token:
                try:
                    import admin_notes
                    admin_notes.add_alert(conn, 'device_new', 'جهاز Dahua جديد بانتظار الموافقة',
                                          f'أرسل جهاز ({key[3:]}) بيانات إلى الموقع. وافق عليه من أجهزة البصمة ← أجهزة Dahua.',
                                          '/dashboard#devices')
                except Exception:   # noqa: BLE001
                    pass
        elif good_token and not s['approved']:
            conn.execute("UPDATE dahua_senders SET approved = 1 WHERE key = ?", (key,))
        approved = bool(s['approved']) or good_token
        mode = s['time_mode'] or 'utc'
        items = []
        for e in events:
            v = e['time']
            # RealUTC = توقيت عالمي حقيقي دائماً؛ UTC في رسائل Dahua غالباً «محلي على أنه UTC»
            m = 'utc' if e['tkey'] == 'RealUTC' else ('local' if e['tkey'] == 'UTC' and mode == 'auto' else mode)
            dt = parse_time(v, 'utc' if m == 'auto' else m) if v not in (None, '') else datetime.now()
            items.append((e['uid'], dt, e['name']))
        held = 0
        if not approved:
            held = conn.execute("SELECT COUNT(*) FROM dahua_logs WHERE source = ?", ('push:' + key,)).fetchone()[0]
        res = store(conn, 'push:' + key, items if held < MAX_HELD_PER_SENDER else [], apply=approved)
        note = (f"{len(events)} حدث، {res['new']} جديد" if events else 'رسالة بلا بصمات (نبضة أو نوع آخر)')
        conn.execute("UPDATE dahua_senders SET last_seen = ?, last_ip = ?, messages = messages + 1, punches = punches + ?, "
                     "last_raw = ?, last_note = ? WHERE key = ?",
                     (_now(), _client_ip(), res['new'], raw, note, key))
        conn.commit()
        if approved and res.get('applied'):
            _analyze_soon()
    finally:
        conn.close()
    return _ok_reply()


# ---------------------------------------------------------------
#   3) رفع ملف من SmartPSS (xlsx / xls / csv)
# ---------------------------------------------------------------
_H_ID = ('person id', 'personid', 'user id', 'userid', 'employee id', 'employee no', 'staff id', 'id',
         'رقم المستخدم', 'رقم الموظف', 'رقم الشخص', 'المعرف', 'الرقم', 'رقم البصمة', '人员编号', '工号')
_H_NAME = ('name', 'person name', 'user name', 'username', 'الاسم', 'اسم الموظف', '姓名')
_H_DT = ('time', 'date time', 'datetime', 'date and time', 'attendance time', 'punch time', 'check time', 'record time',
         'event time', 'swipe time', 'الوقت', 'التاريخ والوقت', 'وقت الحضور', 'وقت البصمة', '时间', '打卡时间')
_H_DATE = ('date', 'attendance date', 'التاريخ', '日期')


def _norm(h):
    return re.sub(r'\s+', ' ', str(h or '')).strip().lower().strip(':')


def _find_col(headers, names, exclude=()):
    for want in names:
        for i, h in enumerate(headers):
            if i not in exclude and h == want:
                return i
    for want in names:
        if len(want) < 4:
            continue
        for i, h in enumerate(headers):
            if i not in exclude and want in h:
                return i
    return None


def _cell_time(v):
    if v is None:
        return None
    if hasattr(v, 'hour') and not hasattr(v, 'year'):
        return f'{v.hour:02d}:{v.minute:02d}:{getattr(v, "second", 0):02d}'
    s = str(v).strip()
    m = re.fullmatch(r'(\d{1,2}):(\d{2})(?::(\d{2}))?', s)
    if m:
        return f'{int(m.group(1)):02d}:{m.group(2)}:{m.group(3) or "00"}'
    return None


def _cell_dt(v):
    if v is None or v == '':
        return None
    if hasattr(v, 'to_pydatetime'):
        v = v.to_pydatetime()
    if isinstance(v, datetime):
        return v.replace(tzinfo=None, microsecond=0)
    return parse_time(str(v), 'local')


def _cell_date(v):
    if v is None or v == '':
        return None
    if hasattr(v, 'to_pydatetime'):
        v = v.to_pydatetime()
    if isinstance(v, datetime):
        return v.date()
    if hasattr(v, 'year') and hasattr(v, 'month'):
        return v
    s = str(v).strip().split(' ')[0].replace('/', '-')
    for fmt in ('%Y-%m-%d', '%d-%m-%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def read_rows(filename, data):
    """يرجع قائمة صفوف (قوائم خلايا) من xlsx/xls/csv"""
    ext = (filename or '').lower().rsplit('.', 1)[-1]
    if ext == 'xlsx':
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        rows = []
        for ws in wb.worksheets:
            rows.extend([list(r) for r in ws.iter_rows(values_only=True)])
            rows.append([])
        return rows
    if ext == 'xls':
        import xlrd
        book = xlrd.open_workbook(file_contents=data)
        rows = []
        for sh in book.sheets():
            for i in range(sh.nrows):
                row = []
                for c in sh.row(i):
                    if c.ctype == xlrd.XL_CELL_DATE:
                        row.append(xlrd.xldate.xldate_as_datetime(c.value, book.datemode))
                    else:
                        row.append(c.value)
                rows.append(row)
            rows.append([])
        return rows
    if ext in ('csv', 'txt'):
        import csv
        for enc in ('utf-8-sig', 'utf-16', 'cp1256', 'latin-1'):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        sample = text[:4000]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
        except csv.Error:
            dialect = csv.excel
        return [r for r in csv.reader(io.StringIO(text), dialect)]
    raise ValueError('صيغة غير مدعومة — ارفع ملف xlsx أو xls أو csv المُصدَّر من SmartPSS.')


def parse_file(filename, data):
    """يكتشف صف العناوين والأعمدة تلقائياً. يرجع (items، وصف الأعمدة المكتشفة)"""
    rows = read_rows(filename, data)
    items, desc = [], None
    i = 0
    while i < len(rows):
        headers = [_norm(h) for h in rows[i]]
        id_c = _find_col(headers, _H_ID)
        name_c = _find_col(headers, _H_NAME, exclude={id_c})
        dt_c = _find_col(headers, _H_DT, exclude={id_c, name_c})
        date_c = _find_col(headers, _H_DATE, exclude={id_c, name_c, dt_c})
        if id_c is None and name_c is None or (dt_c is None and date_c is None):
            i += 1
            continue
        # صف عناوين مكتشف: نقرأ ما بعده حتى صف فارغ تماماً أو صف عناوين جديد
        j = i + 1
        time_cols = None
        while j < len(rows) and any(c not in (None, '') for c in rows[j]):
            r = rows[j]
            cell = lambda c: r[c] if c is not None and c < len(r) else None   # noqa: E731
            uid = cell(id_c)
            uid = '' if uid is None else str(uid).strip()
            hint = str(cell(name_c) or '').strip()
            dt = _cell_dt(cell(dt_c)) if dt_c is not None else None
            stamps = []
            if dt and (dt.hour or dt.minute or dt.second or date_c is None):
                stamps = [dt]
            else:
                d = _cell_date(cell(date_c)) or (dt.date() if dt else None)
                if d:
                    if time_cols is None:      # كل عمود فيه أوقات (حضور/انصراف/بصمة 1…) يُعدّ بصمة
                        time_cols = [c for c in range(len(headers)) if c not in (id_c, name_c, date_c)
                                     and _cell_time(cell(c))]
                    for c in time_cols:
                        t = _cell_time(cell(c))
                        if t:
                            stamps.append(datetime.strptime(f'{d} {t}', '%Y-%m-%d %H:%M:%S'))
            for st in stamps:
                items.append((uid or ('name:' + hint), st, hint))
            j += 1
        if desc is None:
            desc = {'id': rows[i][id_c] if id_c is not None else None,
                    'name': rows[i][name_c] if name_c is not None else None,
                    'time': rows[i][dt_c] if dt_c is not None else None,
                    'date': rows[i][date_c] if date_c is not None else None}
        i = j
    return items, desc


# ---------------------------------------------------------------
#   واجهة الإدارة
# ---------------------------------------------------------------
_PUBLIC = ('id', 'name', 'host', 'port', 'use_https', 'username', 'time_mode', 'auto_pull', 'active', 'location',
           'model', 'serial', 'last_pull', 'last_rec_ts', 'last_error')


def _audit(conn, action, value):
    try:
        import app as app_module
        app_module.log_audit(conn, action, 'device', new_value=str(value)[:500])
    except Exception:   # noqa: BLE001
        pass


@bp.route('/api/dahua/overview', methods=['GET'])
def api_overview():
    if not session.get('user_id'):
        return _deny()
    conn = db.get_db()
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        devs = []
        for r in conn.execute("SELECT * FROM dahua_devices ORDER BY name"):
            d = {k: r[k] for k in _PUBLIC}
            d['has_password'] = bool(r['password_enc'])
            src = f"pull:{r['id']}"
            d['today'] = conn.execute("SELECT COUNT(*) FROM dahua_logs WHERE source = ? AND ts LIKE ?", (src, today + '%')).fetchone()[0]
            d['total'] = conn.execute("SELECT COUNT(*) FROM dahua_logs WHERE source = ?", (src,)).fetchone()[0]
            d['unmatched'] = [x[0] for x in conn.execute(
                "SELECT DISTINCT user_id FROM dahua_logs WHERE source = ? AND matched = '' LIMIT 50", (src,))]
            devs.append(d)
        senders = []
        for r in conn.execute("SELECT * FROM dahua_senders ORDER BY approved, last_seen DESC"):
            s = dict(r)
            src = 'push:' + r['key']
            s['today'] = conn.execute("SELECT COUNT(*) FROM dahua_logs WHERE source = ? AND ts LIKE ?", (src, today + '%')).fetchone()[0]
            s['held'] = conn.execute("SELECT COUNT(*) FROM dahua_logs WHERE source = ? AND applied = 0", (src,)).fetchone()[0]
            s['unmatched'] = [x[0] for x in conn.execute(
                "SELECT DISTINCT user_id FROM dahua_logs WHERE source = ? AND matched = '' LIMIT 50", (src,))]
            if not _admin_ok():
                s.pop('last_raw', None)
            senders.append(s)
        out = {'ok': True, 'devices': devs, 'senders': senders,
               'auto_pull': db.get_setting('dahua_auto_pull', '1') == '1',
               'pull_every': db.get_setting('dahua_pull_every', '5') or '5'}
        if _admin_ok():
            out['push_url'] = f"https://{request.host}/dahua/push/{push_token()}"
            out['push_host'] = request.host
        return jsonify(out)
    finally:
        conn.close()


def _clean_device(d, partial=False):
    out = {}
    if 'name' in d or not partial:
        out['name'] = (d.get('name') or '').strip()[:80]
        if not out['name']:
            raise ValueError('اسم الجهاز مطلوب')
    if 'host' in d or not partial:
        host = (d.get('host') or '').strip()
        if not re.fullmatch(r'[A-Za-z0-9.\-]{1,120}', host):
            raise ValueError('عنوان IP غير صالح (مثال: 192.168.1.108)')
        out['host'] = host
    if 'port' in d or not partial:
        try:
            port = int(d.get('port') or (443 if d.get('use_https') else 80))
        except (TypeError, ValueError):
            port = 0
        if not 1 <= port <= 65535:
            raise ValueError('المنفذ غير صالح')
        out['port'] = port
    for k in ('use_https', 'auto_pull', 'active'):
        if k in d:
            out[k] = 1 if d.get(k) in (True, 1, '1', 'on', 'true') else 0
    if 'username' in d or not partial:
        out['username'] = (d.get('username') or 'admin').strip()[:60]
    if d.get('time_mode') in ('utc', 'local'):
        out['time_mode'] = d['time_mode']
    if 'location' in d:
        out['location'] = (d.get('location') or '').strip()[:120]
    if d.get('password'):
        out['password_enc'] = _enc(d['password'])
    return out


@bp.route('/api/dahua/devices', methods=['POST'])
def api_device_add():
    if not _admin_ok():
        return _deny()
    d = request.get_json(silent=True) or {}
    try:
        row = _clean_device(d)
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    if not row.get('password_enc'):
        return jsonify({'ok': False, 'error': 'كلمة مرور الجهاز مطلوبة (كلمة الدخول إلى صفحة الجهاز)'}), 400
    conn = db.get_db()
    try:
        cols = ', '.join(row)
        cur = conn.execute(f"INSERT INTO dahua_devices ({cols}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
        _audit(conn, 'dahua_add', f"{row['name']} {row['host']}")
        conn.commit()
        return jsonify({'ok': True, 'id': cur.lastrowid})
    finally:
        conn.close()


@bp.route('/api/dahua/devices/<int:dev_id>', methods=['POST'])
def api_device_edit(dev_id):
    if not _admin_ok():
        return _deny()
    d = request.get_json(silent=True) or {}
    try:
        row = _clean_device(d, partial=True)
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    if not row:
        return jsonify({'ok': True})
    conn = db.get_db()
    try:
        if not conn.execute("SELECT 1 FROM dahua_devices WHERE id = ?", (dev_id,)).fetchone():
            return jsonify({'ok': False, 'error': 'الجهاز غير موجود'}), 404
        conn.execute(f"UPDATE dahua_devices SET {', '.join(k + ' = ?' for k in row)} WHERE id = ?", [*row.values(), dev_id])
        _audit(conn, 'dahua_edit', f"{dev_id}: {', '.join(k for k in row if k != 'password_enc')}"
               + (' + كلمة المرور' if 'password_enc' in row else ''))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


@bp.route('/api/dahua/devices/bulk', methods=['POST'])
def api_devices_bulk():
    if not _admin_ok():
        return _deny()
    d = request.get_json(silent=True) or {}
    ids = [int(i) for i in (d.get('ids') or []) if str(i).isdigit()]
    action = d.get('action')
    if not ids or action not in ('enable', 'disable', 'delete', 'auto_on', 'auto_off', 'test', 'pull'):
        return jsonify({'ok': False, 'error': 'طلب غير صالح'}), 400
    conn = db.get_db()
    try:
        if action == 'test':
            out = []
            for r in conn.execute(f"SELECT * FROM dahua_devices WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall():
                try:
                    res = test_device(dict(r))
                    conn.execute("UPDATE dahua_devices SET model = ?, serial = ?, last_error = '' WHERE id = ?",
                                 (res['model'], res['serial'], r['id']))
                    out.append({'device': r['name'], **res})
                except DahuaError as e:
                    conn.execute("UPDATE dahua_devices SET last_error = ? WHERE id = ?", (str(e), r['id']))
                    out.append({'device': r['name'], 'ok': False, 'error': str(e)})
            conn.commit()
            return jsonify({'ok': True, 'results': out})
        if action == 'pull':
            start = end = None
            try:
                if d.get('date_from'):
                    start = datetime.strptime(d['date_from'], '%Y-%m-%d')
                if d.get('date_to'):
                    end = datetime.strptime(d['date_to'], '%Y-%m-%d') + timedelta(days=1)
            except ValueError:
                return jsonify({'ok': False, 'error': 'تاريخ غير صالح'}), 400
            if start and not end:
                end = datetime.now() + timedelta(hours=1)
            res = pull_all(conn, ids, start, end)
            _audit(conn, 'dahua_pull', '; '.join(f"{r['device']}: {r.get('count', r.get('error'))}" for r in res))
            conn.commit()
            return jsonify({'ok': True, 'results': res})
        ph = ','.join('?' * len(ids))
        if action == 'delete':
            # الحذف المحمي: السجلات المسحوبة تبقى في القاعدة (تبقى ضمن الحضور)، ويُحذف الجهاز من القائمة فقط
            conn.execute(f"DELETE FROM dahua_devices WHERE id IN ({ph})", ids)
        else:
            col, val = {'enable': ('active', 1), 'disable': ('active', 0),
                        'auto_on': ('auto_pull', 1), 'auto_off': ('auto_pull', 0)}[action]
            conn.execute(f"UPDATE dahua_devices SET {col} = ? WHERE id IN ({ph})", [val, *ids])
        _audit(conn, f'dahua_{action}', ids)
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


@bp.route('/api/dahua/senders/bulk', methods=['POST'])
def api_senders_bulk():
    if not _admin_ok():
        return _deny()
    d = request.get_json(silent=True) or {}
    keys = [str(k)[:80] for k in (d.get('keys') or []) if k]
    action = d.get('action')
    if not keys or action not in ('approve', 'block', 'delete', 'rename', 'time_utc', 'time_local', 'time_auto'):
        return jsonify({'ok': False, 'error': 'طلب غير صالح'}), 400
    conn = db.get_db()
    try:
        applied = 0
        for k in keys:
            if action == 'approve':
                conn.execute("UPDATE dahua_senders SET approved = 1 WHERE key = ?", (k,))
                applied += apply_pending(conn, 'push:' + k)
            elif action == 'block':
                conn.execute("UPDATE dahua_senders SET approved = 0 WHERE key = ?", (k,))
            elif action == 'delete':
                conn.execute("DELETE FROM dahua_senders WHERE key = ?", (k,))
                conn.execute("DELETE FROM dahua_logs WHERE source = ? AND applied = 0", ('push:' + k,))   # المعلّقة فقط
            elif action.startswith('time_'):
                conn.execute("UPDATE dahua_senders SET time_mode = ? WHERE key = ?", (action[5:], k))
            elif action == 'rename' and (d.get('name') or '').strip():
                conn.execute("UPDATE dahua_senders SET name = ? WHERE key = ?", (d['name'].strip()[:60], k))
        _audit(conn, f'dahua_sender_{action}', ', '.join(keys))
        conn.commit()
        if applied:
            _analyze_soon()
        return jsonify({'ok': True, 'applied': applied})
    finally:
        conn.close()


@bp.route('/api/dahua/settings', methods=['POST'])
def api_settings():
    if not _admin_ok():
        return _deny()
    d = request.get_json(silent=True) or {}
    if 'auto_pull' in d:
        db.set_setting('dahua_auto_pull', '1' if d['auto_pull'] else '0')
    if 'pull_every' in d:
        try:
            n = int(d['pull_every'])
        except (TypeError, ValueError):
            n = 0
        if n not in (1, 2, 3, 5, 10, 15, 30, 60):
            return jsonify({'ok': False, 'error': 'المدة غير صالحة'}), 400
        db.set_setting('dahua_pull_every', str(n))
    if d.get('new_token'):
        db.set_setting('dahua_push_token', secrets.token_urlsafe(18))
    return jsonify({'ok': True})


@bp.route('/api/dahua/rematch', methods=['POST'])
def api_rematch():
    if not _admin_ok():
        return _deny()
    conn = db.get_db()
    try:
        n = rematch(conn)
        conn.commit()
    finally:
        conn.close()
    if n:
        _analyze_soon()
    return jsonify({'ok': True, 'matched': n})


@bp.route('/api/dahua/import', methods=['POST'])
def api_import():
    if not _admin_ok():
        return _deny()
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'ok': False, 'error': 'اختر الملف أولاً'}), 400
    data = f.read()
    if len(data) > 30_000_000:
        return jsonify({'ok': False, 'error': 'الملف أكبر من 30 ميغابايت'}), 400
    try:
        items, desc = parse_file(f.filename, data)
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:   # noqa: BLE001 — ملف تالف
        return jsonify({'ok': False, 'error': f'تعذّرت قراءة الملف ({type(e).__name__}) — تأكد أنه تقرير السجلات المُصدَّر من SmartPSS.'}), 400
    if not items:
        return jsonify({'ok': False, 'error': 'لم أجد في الملف عمود رقم/اسم الموظف مع عمود الوقت. '
                                              'صدِّر «سجلات الحضور الأصلية» (Original Records / Attendance Records) من SmartPSS.'}), 400
    conn = db.get_db()
    try:
        names = {r['name']: r['name'] for r in conn.execute("SELECT name FROM employees WHERE active = 1")}
        res = store(conn, 'file', items, names=names)
        _audit(conn, 'dahua_import', f"{f.filename}: {res['new']} بصمة جديدة من {res['received']}")
        conn.commit()
    finally:
        conn.close()
    if res['applied']:
        _analyze_soon()
    days = sorted({it[1].strftime('%Y-%m-%d') for it in items})
    return jsonify({'ok': True, **res, 'columns': {k: (str(v) if v is not None else None) for k, v in (desc or {}).items()},
                    'date_from': days[0], 'date_to': days[-1]})
