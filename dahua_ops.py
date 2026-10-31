"""
إدارة أجهزة Dahua بكامل قدراتها (بجانب ZKTeco) — عبر واجهة HTTP الرسمية في الجهاز (CGI، Digest):

  • معلومات الجهاز: الطراز والرقم التسلسلي والإصدار ووقت الجهاز وعدد المستخدمين/الوجوه/البطاقات/البصمات/السجلات.
  • الوقت: ضبط ساعة الجهاز على وقت الخادم (Asia/Amman).
  • المستخدمون: قراءة المسجّلين في الجهاز، رفع الموظفين إليه (إضافة أو تحديث الاسم)، حذف المحدد أو الكل.
  • الوجوه والبطاقات وبصمات الإصبع: نسخها من جهاز Dahua إلى أجهزة Dahua أخرى، ورفع صورة وجه لموظف.
  • الباب: فتح عن بُعد. الصيانة: إعادة التشغيل، مسح سجلات الجهاز (بعد سحبها).
  • المراقبة الحية داخل الشبكة: اشتراك في أحداث الجهاز (eventManager attach) فتُسجَّل كل بصمة لحظة حدوثها.

واجهة المستخدمين الحديثة (AccessUser / AccessFace / AccessCard / AccessFingerprint) هي الأساس، ومع الأجهزة
الأقدم يُستخدم جدول البطاقات القديم (recordUpdater AccessControlCard). ما لا يدعمه طراز ما يظهر برسالة واضحة.
الأجهزة لا تُستدعى إلا بطلب صريح من المدير (عدا المراقبة الحية والسحب التلقائي).
"""
import base64
import io
import json
import re
import threading
import time
from collections import deque
from datetime import datetime

from flask import jsonify, request

import db
import dahua
from dahua import DahuaError, bp, _admin_ok, _deny, _audit, _dec, _now

BATCH = 10                      # حدّ الأجهزة لعمليات insertMulti / updateMulti في الطلب الواحد
NAME_MAX = 30


# ---------------------------------------------------------------
#   الطلبات
# ---------------------------------------------------------------
def _url(dev, path):
    scheme = 'https' if dev.get('use_https') else 'http'
    return f"{scheme}://{dev['host']}:{int(dev.get('port') or (443 if dev.get('use_https') else 80))}{path}"


def _auth(dev):
    from requests.auth import HTTPDigestAuth
    pw = _dec(dev.get('password_enc'))
    if pw is None:
        raise DahuaError('تعذّر قراءة كلمة مرور الجهاز المحفوظة — أعد إدخالها من «تعديل».')
    return HTTPDigestAuth(dev.get('username') or 'admin', pw)


def req(dev, path, params=None, body=None, timeout=15, unsupported=None):
    """GET (أو POST بجسم JSON). يرجع النص. unsupported: رسالة تظهر إن لم يدعم الجهاز الطلب."""
    import requests
    if dev.get('use_https'):
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        if body is None:
            r = requests.get(_url(dev, path), params=params, auth=_auth(dev), timeout=timeout, verify=False)
        else:
            r = requests.post(_url(dev, path), params=params, auth=_auth(dev), timeout=timeout, verify=False,
                              data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
                              headers={'Content-Type': 'application/json'})
    except requests.exceptions.ConnectTimeout:
        raise DahuaError(f"الجهاز {dev['host']} لا يرد (انتهت المهلة) — تأكد أنه على شبكة المدرسة نفسها.")
    except requests.exceptions.ConnectionError:
        raise DahuaError(f"تعذّر الاتصال بالجهاز {dev['host']}:{dev.get('port')} — تحقق من العنوان والمنفذ واتصال الشبكة.")
    except requests.exceptions.RequestException as e:
        raise DahuaError(f'خطأ في الاتصال: {type(e).__name__}')
    if r.status_code == 401:
        raise DahuaError('اسم المستخدم أو كلمة المرور غير صحيحة (حساب صفحة الجهاز). تكرار المحاولة الخاطئة يقفل الحساب مؤقتاً.')
    if r.status_code in (400, 404, 501) or (r.status_code < 400 and _is_error(r.text) and unsupported):
        raise DahuaError(unsupported or 'الجهاز لا يدعم هذا الطلب (طراز أو إصدار مختلف).')
    if r.status_code >= 400:
        raise DahuaError(f'رد الجهاز بخطأ HTTP {r.status_code}')
    r.encoding = r.encoding or 'utf-8'
    return r.text


def _is_error(text):
    t = (text or '').strip()
    return t.startswith('Error') or t.startswith('<html') and 'Error' in t


def parse(text):
    """رد الجهاز: JSON في الإصدارات الحديثة، أو key=value في القديمة. يرجع dict/list."""
    t = (text or '').strip()
    if t[:1] in '{[':
        try:
            return json.loads(t)
        except ValueError:
            pass
    return dahua._kv(t)


def _ok(text):
    t = (text or '').strip()
    if not t or t == 'OK' or t.startswith('OK'):
        return True
    data = parse(t)
    if isinstance(data, dict):
        if data.get('FailCodes') and any(int(c or 0) for c in data.get('FailCodes') if str(c).lstrip('-').isdigit()):
            return False
        return not _is_error(t)
    return True


def _grouped(kv, prefix):
    """key=value: «info[0].UserID=1» → [{'UserID': '1'}, …] (الإصدارات القديمة)"""
    groups = {}
    for k, v in kv.items():
        m = re.match(re.escape(prefix) + r'\[(\d+)\]\.(\w+)', k)
        if m:
            groups.setdefault(int(m.group(1)), {})[m.group(2)] = v
    return [g for _, g in sorted(groups.items())]


# ---------------------------------------------------------------
#   معلومات وصيانة
# ---------------------------------------------------------------
def _count(dev, cgi):
    try:
        text = req(dev, f'/cgi-bin/{cgi}.cgi', {'action': 'startFind'}, timeout=10, unsupported='x')
        d = parse(text)
        token, total = d.get('Token'), d.get('Total')
        if token is not None:
            try:
                req(dev, f'/cgi-bin/{cgi}.cgi', {'action': 'stopFind', 'Token': token}, timeout=5)
            except DahuaError:
                pass
        return int(total) if total is not None else None
    except (DahuaError, ValueError, AttributeError):
        return None


def device_info(dev):
    info = dahua._kv(req(dev, '/cgi-bin/magicBox.cgi', {'action': 'getSystemInfo'}))
    out = {'model': info.get('deviceType') or info.get('updateSerial') or '', 'serial': info.get('serialNumber') or '',
           'server_time': _now()}
    for action, key in (('getSoftwareVersion', 'version'), ('getDeviceType', 'type')):
        try:
            kv = dahua._kv(req(dev, '/cgi-bin/magicBox.cgi', {'action': action}, timeout=6))
            out[key] = kv.get('version') or kv.get('type') or next(iter(kv.values()), '')
        except DahuaError:
            pass
    try:
        out['device_time'] = dahua._kv(req(dev, '/cgi-bin/global.cgi', {'action': 'getCurrentTime'}, timeout=6)).get('result', '')
    except DahuaError:
        out['device_time'] = ''
    out['users'] = _count(dev, 'AccessUser')
    out['faces'] = _count(dev, 'AccessFace')
    out['cards'] = _count(dev, 'AccessCard')
    out['fingerprints'] = _count(dev, 'AccessFingerprint')
    try:
        kv = dahua._kv(req(dev, '/cgi-bin/recordFinder.cgi', {'action': 'getQuerySize', 'name': 'AccessControlCardRec'}, timeout=8))
        out['records'] = int(kv.get('count')) if kv.get('count', '').isdigit() else None
    except DahuaError:
        out['records'] = None
    return out


def _server_now():
    tz = dahua._TZ
    return datetime.now(tz).replace(tzinfo=None) if tz else datetime.now()


def sync_time(dev):
    now = _server_now().strftime('%Y-%m-%d %H:%M:%S')
    text = req(dev, '/cgi-bin/global.cgi', {'action': 'setCurrentTime', 'time': now},
               unsupported='الجهاز لم يقبل ضبط الوقت.')
    if not _ok(text):
        raise DahuaError('الجهاز لم يقبل ضبط الوقت.')
    return {'device_time': now}


def reboot(dev):
    req(dev, '/cgi-bin/magicBox.cgi', {'action': 'reboot'}, timeout=8, unsupported='الجهاز لا يدعم إعادة التشغيل عن بُعد.')
    return {}


def open_door(dev, channel=1):
    text = req(dev, '/cgi-bin/accessControl.cgi', {'action': 'openDoor', 'channel': int(channel or 1), 'Type': 'Remote'},
               unsupported='هذا الطراز لا يتحكم بقفل باب (جهاز حضور فقط)، أو أن القفل غير موصول.')
    if not _ok(text):
        raise DahuaError('الجهاز رفض فتح الباب.')
    return {}


def clear_records(dev):
    text = req(dev, '/cgi-bin/recordUpdater.cgi', {'action': 'clear', 'name': 'AccessControlCardRec'}, timeout=30,
               unsupported='الجهاز لا يدعم مسح السجلات عن بُعد — امسحها من صفحة الجهاز.')
    if not _ok(text):
        raise DahuaError('الجهاز رفض مسح السجلات.')
    return {}


# ---------------------------------------------------------------
#   المستخدمون
# ---------------------------------------------------------------
def _find_all(dev, cgi, key_names=('Info', 'UserList', 'CardList', 'FaceList', 'FingerprintList'), cond=None):
    """startFind / doFind / stopFind — يرجع قائمة العناصر، أو None إن لم يدعم الجهاز الواجهة."""
    params = {'action': 'startFind'}
    for k, v in (cond or {}).items():
        params[f'Condition.{k}'] = v
    try:
        d = parse(req(dev, f'/cgi-bin/{cgi}.cgi', params, timeout=15, unsupported='x'))
    except DahuaError as e:
        if str(e) == 'x':
            return None
        raise
    token = d.get('Token') if isinstance(d, dict) else None
    if token is None:
        return None
    total = int(d.get('Total') or 0)
    items, offset = [], 0
    try:
        while offset < max(total, 1) and offset < 20000:
            page = parse(req(dev, f'/cgi-bin/{cgi}.cgi', {'action': 'doFind', 'Token': token, 'Offset': offset, 'Count': 100},
                             timeout=20))
            got = []
            if isinstance(page, dict):
                for k in key_names:
                    if isinstance(page.get(k), list):
                        got = page[k]
                        break
                else:
                    for k in key_names:
                        got = _grouped(page, k)
                        if got:
                            break
            if not got:
                break
            items.extend(got)
            offset += len(got)
            if len(got) < 100 and offset >= total:
                break
    finally:
        try:
            req(dev, f'/cgi-bin/{cgi}.cgi', {'action': 'stopFind', 'Token': token}, timeout=5)
        except DahuaError:
            pass
    return items


def _legacy_cards(dev):
    """الأجهزة الأقدم: جدول البطاقات AccessControlCard (فيه UserID والاسم ورقم البطاقة)"""
    text = req(dev, '/cgi-bin/recordFinder.cgi', {'action': 'find', 'name': 'AccessControlCard', 'count': 5000}, timeout=30,
               unsupported='الجهاز لا يتيح قراءة المستخدمين عبر الشبكة.')
    return _grouped(dahua._kv(text), 'records')


def list_users(dev):
    """[{uid, name, card, has_face, fingerprints, password}] — من الواجهة الحديثة، أو جدول البطاقات القديم"""
    users = _find_all(dev, 'AccessUser')
    out = {}
    if users is not None:
        for u in users:
            uid = str(u.get('UserID') or '').strip()
            if uid:
                out[uid] = {'uid': uid, 'name': u.get('UserName') or '', 'card': '', 'has_face': False, 'fingerprints': 0,
                            'password': bool(u.get('Password'))}
        for c in _find_all(dev, 'AccessCard') or []:
            uid = str(c.get('UserID') or '')
            if uid in out:
                out[uid]['card'] = str(c.get('CardNo') or '')
        for f in _find_all(dev, 'AccessFace') or []:
            uid = str(f.get('UserID') or '')
            if uid in out:
                out[uid]['has_face'] = True
        for f in _find_all(dev, 'AccessFingerprint') or []:
            uid = str(f.get('UserID') or '')
            if uid in out:
                out[uid]['fingerprints'] += 1
        mode = 'v2'
    else:
        for c in _legacy_cards(dev):
            uid = str(c.get('UserID') or '').strip()
            if uid:
                out[uid] = {'uid': uid, 'name': c.get('CardName') or '', 'card': c.get('CardNo') or '',
                            'has_face': None, 'fingerprints': None, 'password': bool(c.get('Password')),
                            'recno': c.get('RecNo') or ''}
        mode = 'legacy'
    rows = sorted(out.values(), key=lambda x: (len(x['uid']), x['uid']))
    return rows, mode


def _user_payload(uid, name):
    return {'UserID': str(uid), 'UserName': (name or '')[:NAME_MAX], 'UserType': 0, 'Authority': 2,
            'Doors': [0], 'TimeSections': [255], 'ValidFrom': '2000-01-01 00:00:00', 'ValidTo': '2037-12-31 23:59:59'}


def _multi(dev, cgi, action, list_key, items):
    """insertMulti / updateMulti على دفعات؛ يرجع عدد الناجح والفاشل"""
    ok = fail = 0
    for i in range(0, len(items), BATCH):
        part = items[i:i + BATCH]
        text = req(dev, f'/cgi-bin/{cgi}.cgi', {'action': action}, body={list_key: part}, timeout=30,
                   unsupported=f'الجهاز لا يدعم {cgi}.')
        d = parse(text)
        codes = d.get('FailCodes') if isinstance(d, dict) else None
        if codes:
            bad = sum(1 for c in codes if str(c) not in ('0', ''))
            fail += bad
            ok += len(part) - bad
        elif _ok(text):
            ok += len(part)
        else:
            fail += len(part)
    return ok, fail


def push_users(dev, employees):
    """employees: [{name, device_uid}] → إضافة الجديد وتحديث اسم الموجود. يرجع ملخصاً."""
    emps = [(str(e['device_uid']).strip(), e['name']) for e in employees if str(e.get('device_uid') or '').strip()]
    if not emps:
        return {'added': 0, 'updated': 0, 'failed': 0}
    existing, mode = list_users(dev)
    have = {u['uid']: u for u in existing}
    if mode == 'v2':
        new = [_user_payload(uid, name) for uid, name in emps if uid not in have]
        upd = [_user_payload(uid, name) for uid, name in emps if uid in have and (have[uid]['name'] or '') != name[:NAME_MAX]]
        a_ok, a_fail = _multi(dev, 'AccessUser', 'insertMulti', 'UserList', new) if new else (0, 0)
        u_ok, u_fail = _multi(dev, 'AccessUser', 'updateMulti', 'UserList', upd) if upd else (0, 0)
        return {'added': a_ok, 'updated': u_ok, 'failed': a_fail + u_fail, 'unchanged': len(emps) - len(new) - len(upd)}
    added = updated = failed = 0
    for uid, name in emps:
        params = {'name': 'AccessControlCard', 'CardName': name[:NAME_MAX], 'UserID': uid, 'CardStatus': 0, 'CardType': 0,
                  'Doors[0]': 0}
        if uid in have:
            if (have[uid]['name'] or '') == name[:NAME_MAX]:
                continue
            params.update({'action': 'update', 'recno': have[uid].get('recno')})
        else:
            params.update({'action': 'insert', 'CardNo': have.get(uid, {}).get('card') or uid})
        text = req(dev, '/cgi-bin/recordUpdater.cgi', params, unsupported='الجهاز لا يقبل إضافة المستخدمين عبر الشبكة.')
        if _ok(text):
            if uid in have:
                updated += 1
            else:
                added += 1
        else:
            failed += 1
    return {'added': added, 'updated': updated, 'failed': failed}


def delete_users(dev, uids=None):
    """uids=None يحذف كل المستخدمين (ووجوههم وبطاقاتهم وبصماتهم)"""
    existing, mode = list_users(dev)
    if mode == 'v2':
        if uids is None:
            text = req(dev, '/cgi-bin/AccessUser.cgi', {'action': 'removeAll'}, timeout=60)
            return {'deleted': len(existing) if _ok(text) else 0}
        n = 0
        uids = [str(u) for u in uids]
        for i in range(0, len(uids), BATCH):
            part = uids[i:i + BATCH]
            params = {'action': 'removeMulti', **{f'UserIDList[{j}]': u for j, u in enumerate(part)}}
            if _ok(req(dev, '/cgi-bin/AccessUser.cgi', params, timeout=30)):
                n += len(part)
        return {'deleted': n}
    want = None if uids is None else {str(u) for u in uids}
    n = 0
    for u in existing:
        if (want is None or u['uid'] in want) and u.get('recno'):
            if _ok(req(dev, '/cgi-bin/recordUpdater.cgi', {'action': 'remove', 'name': 'AccessControlCard', 'recno': u['recno']})):
                n += 1
    return {'deleted': n}


# ---------------------------------------------------------------
#   الوجوه والبطاقات وبصمات الإصبع
# ---------------------------------------------------------------
def _list_face(dev, uid):
    d = parse(req(dev, '/cgi-bin/AccessFace.cgi', {'action': 'list', 'UserIDList[0]': uid}, timeout=20,
                  unsupported='الجهاز لا يتيح قراءة صور الوجوه.'))
    for item in (d.get('FaceDataList') or d.get('FaceList') or []) if isinstance(d, dict) else []:
        if str(item.get('UserID')) == str(uid):
            return item
    return None


def _list_fingers(dev, uid):
    d = parse(req(dev, '/cgi-bin/AccessFingerprint.cgi', {'action': 'list', 'UserID': uid}, timeout=20,
                  unsupported='الجهاز لا يتيح قراءة بصمات الإصبع.'))
    if isinstance(d, dict):
        data = d.get('FingerprintData') or d.get('FingerprintList') or []
        return data if isinstance(data, list) else [data]
    return []


def _upsert(dev, cgi, list_key, item):
    ok, _ = _multi(dev, cgi, 'insertMulti', list_key, [item])
    if not ok:
        ok, _ = _multi(dev, cgi, 'updateMulti', list_key, [item])
    return bool(ok)


def copy_between(src, targets, what=('face', 'card', 'fingerprint'), uids=None):
    """ينسخ من جهاز Dahua إلى أجهزة Dahua أخرى: المستخدم أولاً، ثم وجهه/بطاقته/بصماته."""
    users, mode = list_users(src)
    if mode != 'v2':
        raise DahuaError('الجهاز المصدر من إصدار قديم لا يتيح قراءة الوجوه والبصمات عبر الشبكة.')
    if uids:
        want = {str(u) for u in uids}
        users = [u for u in users if u['uid'] in want]
    per = {t['name']: {'users': 0, 'faces': 0, 'cards': 0, 'fingerprints': 0, 'errors': []} for t in targets}
    for t in targets:
        try:
            ok, _ = _multi(t, 'AccessUser', 'insertMulti', 'UserList', [_user_payload(u['uid'], u['name']) for u in users])
            per[t['name']]['users'] = ok
        except DahuaError as e:
            per[t['name']]['errors'].append(str(e))
    for u in users:
        face = fingers = None
        if 'face' in what and u['has_face']:
            try:
                face = _list_face(src, u['uid'])
            except DahuaError:
                face = None
        if 'fingerprint' in what and u['fingerprints']:
            try:
                fingers = _list_fingers(src, u['uid'])
            except DahuaError:
                fingers = None
        for t in targets:
            r = per[t['name']]
            try:
                if face:
                    item = {'UserID': u['uid']}
                    if face.get('PhotoData'):
                        item['PhotoData'] = face['PhotoData'] if isinstance(face['PhotoData'], list) else [face['PhotoData']]
                    if face.get('FaceData'):
                        item['FaceData'] = face['FaceData'] if isinstance(face['FaceData'], list) else [face['FaceData']]
                    if _upsert(t, 'AccessFace', 'FaceList', item):
                        r['faces'] += 1
                if 'card' in what and u['card']:
                    if _upsert(t, 'AccessCard', 'CardList', {'UserID': u['uid'], 'CardNo': u['card'], 'CardType': 0}):
                        r['cards'] += 1
                if fingers:
                    if _upsert(t, 'AccessFingerprint', 'FingerprintList', {'UserID': u['uid'], 'FingerprintData': fingers}):
                        r['fingerprints'] += 1
            except DahuaError as e:
                if len(r['errors']) < 5 and str(e) not in r['errors']:
                    r['errors'].append(str(e))
    return {'users': len(users), 'per_target': per}


def prepare_photo(data):
    """صورة الوجه: JPEG، أطول ضلع 640 بكسل، وأقل من 100 كيلوبايت (حدّ الأجهزة)"""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        if len(data) > 100_000 or not data[:3] == b'\xff\xd8\xff':
            raise DahuaError('ارفع صورة JPEG أصغر من 100 كيلوبايت (مكتبة معالجة الصور غير مثبّتة على الخادم).')
        return data
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert('RGB')
    except Exception:   # noqa: BLE001 — ليست صورة
        raise DahuaError('الملف ليس صورة صالحة.')
    if min(img.size) < 150:
        raise DahuaError('الصورة صغيرة جداً — استخدم صورة واضحة للوجه بعرض 150 بكسل على الأقل.')
    img.thumbnail((640, 640))
    for q in (90, 80, 70, 60, 50, 40):
        buf = io.BytesIO()
        img.save(buf, 'JPEG', quality=q)
        if buf.tell() <= 100_000:
            return buf.getvalue()
    img.thumbnail((400, 400))
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=60)
    return buf.getvalue()


def upload_face(dev, uid, name, jpeg):
    """يضيف المستخدم إن لم يكن موجوداً ثم صورة وجهه"""
    try:
        _multi(dev, 'AccessUser', 'insertMulti', 'UserList', [_user_payload(uid, name)])
    except DahuaError:
        pass
    item = {'UserID': str(uid), 'PhotoData': [base64.b64encode(jpeg).decode()]}
    if not _upsert(dev, 'AccessFace', 'FaceList', item):
        raise DahuaError('الجهاز لم يقبل الصورة — جرّب صورة أوضح للوجه من الأمام وبإضاءة جيدة.')
    return {}


# ---------------------------------------------------------------
#   المراقبة الحية داخل الشبكة (eventManager attach)
# ---------------------------------------------------------------
_LIVE = {}                      # dev_id → {'stop': Event, 'thread': Thread, 'state': str, 'since': str}
_EVENTS = deque(maxlen=200)
_EV_ID = [0]
_LIVE_LOCK = threading.Lock()


def _event_items(part):
    """جزء من تيار الأحداث → [(uid, datetime_or_epoch, status)]"""
    out = []
    for m in re.finditer(r'Code=AccessControl;action=\w+;index=\d+;data=(\{.*?\})\s*(?=(?:--|Code=|$))', part, re.S):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        uid = str(data.get('UserID') or data.get('CardNo') or '').strip()
        t = data.get('CreateTime') or data.get('UTC') or data.get('RealUTC')
        status = data.get('Status')
        out.append((uid, t, status, data.get('CardName') or data.get('UserName') or ''))
    return out


def _handle_events(dev, items):
    mode = dev.get('time_mode') or 'utc'
    good = []
    for uid, t, status, hint in items:
        dt = dahua.parse_time(t, mode) if t else datetime.now()
        if not uid or dt is None:
            continue
        ok = status in (None, 1, '1', True, 'true')
        _EV_ID[0] += 1
        _EVENTS.append({'id': _EV_ID[0], 'device': dev['name'], 'uid': uid, 'time': dt.strftime('%Y-%m-%d %H:%M:%S'),
                        'ok': ok, 'name': ''})
        if ok:
            good.append((uid, dt, hint))
    if not good:
        return
    conn = db.get_db()
    try:
        names = dahua._name_map(conn)
        for e in list(_EVENTS)[-len(items):]:
            e['name'] = names.get(e['uid']) or names.get(e['uid'].lstrip('0') or '0') or ''
        res = dahua.store(conn, f"pull:{dev['id']}", good)
        conn.execute("UPDATE dahua_devices SET last_rec_ts = MAX(COALESCE(last_rec_ts, ''), ?) WHERE id = ?",
                     (max(x[1] for x in good).strftime('%Y-%m-%d %H:%M:%S'), dev['id']))
        conn.commit()
    finally:
        conn.close()
    if res.get('applied'):
        dahua._analyze_soon()


def _live_loop(dev_id, stop):
    import requests
    backoff = 5
    while not stop.is_set():
        conn = db.get_db()
        try:
            row = conn.execute("SELECT * FROM dahua_devices WHERE id = ?", (dev_id,)).fetchone()
        finally:
            conn.close()
        if not row or not row['active'] or not row['live']:
            break
        dev = dict(row)
        st = _LIVE.get(dev_id)
        try:
            r = requests.get(_url(dev, '/cgi-bin/eventManager.cgi'),
                             params={'action': 'attach', 'codes': '[AccessControl]', 'heartbeat': 20},
                             auth=_auth(dev), stream=True, timeout=(8, 60), verify=False)
            if r.status_code != 200:
                raise DahuaError(f'HTTP {r.status_code}')
            if st:
                st['state'] = 'connected'
                st['since'] = _now()
            backoff = 5
            buf = ''
            for chunk in r.iter_content(chunk_size=None, decode_unicode=False):
                if stop.is_set():
                    break
                buf += chunk.decode('utf-8', 'replace')
                parts = buf.split('--myboundary')
                buf = parts.pop()                     # the part still arriving
                for part in parts:
                    if 'AccessControl' in part:
                        _handle_events(dev, _event_items(part))
                if len(buf) > 200_000:
                    buf = ''
            if 'AccessControl' in buf:
                _handle_events(dev, _event_items(buf))
        except Exception as e:   # noqa: BLE001 — يعيد الاتصال تلقائياً
            if st:
                st['state'] = f'reconnecting: {type(e).__name__}'
        stop.wait(backoff)
        backoff = min(backoff * 2, 120)
    with _LIVE_LOCK:
        _LIVE.pop(dev_id, None)


def ensure_live():
    """من المجدول كل دقيقة: يبدأ المراقبة للأجهزة المفعّلة لها، ويوقفها للباقي"""
    conn = db.get_db()
    try:
        want = {r['id'] for r in conn.execute("SELECT id FROM dahua_devices WHERE active = 1 AND live = 1")}
    finally:
        conn.close()
    with _LIVE_LOCK:
        for dev_id in list(_LIVE):
            if dev_id not in want:
                _LIVE[dev_id]['stop'].set()
        for dev_id in want:
            if dev_id not in _LIVE:
                stop = threading.Event()
                th = threading.Thread(target=_live_loop, args=(dev_id, stop), daemon=True, name=f'dahua-live-{dev_id}')
                _LIVE[dev_id] = {'stop': stop, 'thread': th, 'state': 'connecting', 'since': _now()}
                th.start()


def live_state():
    return {str(k): {'state': v['state'], 'since': v['since']} for k, v in _LIVE.items()}


# ---------------------------------------------------------------
#   واجهة الإدارة
# ---------------------------------------------------------------
def _devices(conn, ids):
    ids = [int(i) for i in ids or [] if str(i).isdigit()]
    if not ids:
        return []
    return [dict(r) for r in conn.execute(f"SELECT * FROM dahua_devices WHERE id IN ({','.join('?' * len(ids))})", ids)]


def _run(devs, fn, *args):
    out = []
    for d in devs:
        try:
            out.append({'device': d['name'], 'id': d['id'], 'ok': True, **(fn(d, *args) or {})})
        except DahuaError as e:
            out.append({'device': d['name'], 'id': d['id'], 'ok': False, 'error': str(e)})
    return out


@bp.route('/api/dahua/manage', methods=['POST'])
def api_manage():
    """عمليات على الأجهزة المحددة: info / time_sync / reboot / open_door / live_on / live_off / clear_records"""
    if not _admin_ok():
        return _deny()
    d = request.get_json(silent=True) or {}
    action = d.get('action')
    if action not in ('info', 'time_sync', 'reboot', 'open_door', 'live_on', 'live_off', 'clear_records'):
        return jsonify({'ok': False, 'error': 'طلب غير صالح'}), 400
    conn = db.get_db()
    try:
        devs = _devices(conn, d.get('ids'))
        if not devs:
            return jsonify({'ok': False, 'error': 'حدّد جهازاً واحداً على الأقل'}), 400
        if action in ('live_on', 'live_off'):
            conn.execute(f"UPDATE dahua_devices SET live = ? WHERE id IN ({','.join('?' * len(devs))})",
                         [1 if action == 'live_on' else 0, *[x['id'] for x in devs]])
            _audit(conn, f'dahua_{action}', ', '.join(x['name'] for x in devs))
            conn.commit()
            ensure_live()
            return jsonify({'ok': True})
        if action == 'clear_records':
            if d.get('confirm') != 'مسح':
                return jsonify({'ok': False, 'error': 'اكتب كلمة «مسح» للتأكيد'}), 400
            # الحماية: سحب كل الجديد قبل المسح، ولا يُمسح جهاز فشل سحبه
            results = []
            for x in devs:
                pulled = dahua.pull_device(conn, x)
                if not pulled.get('ok'):
                    results.append({'device': x['name'], 'ok': False, 'error': 'لم يُمسح: تعذّر سحب سجلاته أولاً — ' + pulled.get('error', '')})
                    continue
                results += _run([x], clear_records)
            _audit(conn, 'dahua_clear_records', '; '.join(f"{r['device']}: {'تم' if r['ok'] else r['error']}" for r in results))
            conn.commit()
            return jsonify({'ok': True, 'results': results})
        fn = {'info': device_info, 'time_sync': sync_time, 'reboot': reboot, 'open_door': open_door}[action]
        args = (d.get('channel') or 1,) if action == 'open_door' else ()
        results = _run(devs, fn, *args)
        for r in results:
            if action == 'info' and r['ok']:
                conn.execute("UPDATE dahua_devices SET model = ?, serial = ?, last_error = '' WHERE id = ?",
                             (r.get('model') or '', r.get('serial') or '', r['id']))
        if action != 'info':
            _audit(conn, f'dahua_{action}', '; '.join(f"{r['device']}: {'تم' if r['ok'] else r['error']}" for r in results))
        conn.commit()
        return jsonify({'ok': True, 'results': results})
    finally:
        conn.close()


@bp.route('/api/dahua/devices/<int:dev_id>/users', methods=['GET'])
def api_users(dev_id):
    if not _admin_ok():
        return _deny()
    conn = db.get_db()
    try:
        devs = _devices(conn, [dev_id])
        uid_map = dahua._name_map(conn)
    finally:
        conn.close()
    if not devs:
        return jsonify({'ok': False, 'error': 'الجهاز غير موجود'}), 404
    try:
        rows, mode = list_users(devs[0])
    except DahuaError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    for r in rows:
        r['employee'] = uid_map.get(r['uid']) or uid_map.get(r['uid'].lstrip('0') or '0') or ''
        r.pop('recno', None)
    missing = sorted(set(uid_map) - {r['uid'] for r in rows}, key=lambda x: (len(x), x))
    return jsonify({'ok': True, 'mode': mode, 'rows': rows,
                    'missing': [{'uid': u, 'name': uid_map[u]} for u in missing]})


@bp.route('/api/dahua/devices/<int:dev_id>/users/delete', methods=['POST'])
def api_users_delete(dev_id):
    if not _admin_ok():
        return _deny()
    d = request.get_json(silent=True) or {}
    everyone = d.get('all') is True
    uids = None if everyone else [str(u)[:40] for u in (d.get('uids') or []) if str(u).strip()]
    if not everyone and not uids:
        return jsonify({'ok': False, 'error': 'حدّد مستخدماً واحداً على الأقل'}), 400
    if everyone and d.get('confirm') != 'حذف الكل':
        return jsonify({'ok': False, 'error': 'اكتب «حذف الكل» للتأكيد'}), 400
    conn = db.get_db()
    try:
        devs = _devices(conn, [dev_id])
        if not devs:
            return jsonify({'ok': False, 'error': 'الجهاز غير موجود'}), 404
        try:
            res = delete_users(devs[0], uids)
        except DahuaError as e:
            return jsonify({'ok': False, 'error': str(e)}), 400
        _audit(conn, 'dahua_delete_users', f"{devs[0]['name']}: {'الكل' if everyone else ', '.join(uids)} → {res['deleted']}")
        conn.commit()
        return jsonify({'ok': True, **res})
    finally:
        conn.close()


@bp.route('/api/dahua/push-employees', methods=['POST'])
def api_push_employees():
    """رفع الموظفين (من لديهم «رقم بصمة») إلى أجهزة Dahua المحددة — الكل أو أسماء محددة"""
    if not _admin_ok():
        return _deny()
    d = request.get_json(silent=True) or {}
    conn = db.get_db()
    try:
        devs = _devices(conn, d.get('ids'))
        if not devs:
            return jsonify({'ok': False, 'error': 'حدّد جهازاً واحداً على الأقل'}), 400
        q = "SELECT name, device_uid FROM employees WHERE active = 1 AND device_uid IS NOT NULL AND device_uid != ''"
        emps = [dict(r) for r in conn.execute(q)]
        names = d.get('names')
        if names:
            want = set(names)
            emps = [e for e in emps if e['name'] in want]
        if not emps:
            return jsonify({'ok': False, 'error': 'لا يوجد موظفون لديهم «رقم بصمة» للرفع'}), 400
        results = _run(devs, push_users, emps)
        _audit(conn, 'dahua_push_employees', '; '.join(
            f"{r['device']}: " + (f"+{r['added']} ~{r['updated']} ✗{r['failed']}" if r['ok'] else r['error']) for r in results))
        conn.commit()
        return jsonify({'ok': True, 'employees': len(emps), 'results': results})
    finally:
        conn.close()


@bp.route('/api/dahua/copy', methods=['POST'])
def api_copy():
    if not _admin_ok():
        return _deny()
    d = request.get_json(silent=True) or {}
    what = [w for w in (d.get('what') or []) if w in ('face', 'card', 'fingerprint')]
    conn = db.get_db()
    try:
        src = _devices(conn, [d.get('source_id')])
        targets = [t for t in _devices(conn, d.get('target_ids')) if not src or t['id'] != src[0]['id']]
        if not src or not targets:
            return jsonify({'ok': False, 'error': 'حدّد الجهاز المصدر وجهازاً هدفاً واحداً على الأقل'}), 400
        if not what:
            return jsonify({'ok': False, 'error': 'اختر ما يُنسخ: الوجوه أو البطاقات أو بصمات الإصبع'}), 400
        try:
            res = copy_between(src[0], targets, what, d.get('uids') or None)
        except DahuaError as e:
            return jsonify({'ok': False, 'error': str(e)}), 400
        _audit(conn, 'dahua_copy', f"{src[0]['name']} → {', '.join(t['name'] for t in targets)}: {what}")
        conn.commit()
        return jsonify({'ok': True, **res})
    finally:
        conn.close()


@bp.route('/api/dahua/face-photo', methods=['POST'])
def api_face_photo():
    if not _admin_ok():
        return _deny()
    f = request.files.get('photo')
    name = (request.form.get('name') or '').strip()
    ids = [i for i in (request.form.get('ids') or '').split(',') if i.strip()]
    if not f or not name or not ids:
        return jsonify({'ok': False, 'error': 'اختر الموظف والصورة وجهازاً واحداً على الأقل'}), 400
    data = f.read()
    if len(data) > 10_000_000:
        return jsonify({'ok': False, 'error': 'الصورة أكبر من 10 ميغابايت'}), 400
    conn = db.get_db()
    try:
        emp = conn.execute("SELECT name, device_uid FROM employees WHERE name = ?", (name,)).fetchone()
        if not emp or not (emp['device_uid'] or '').strip():
            return jsonify({'ok': False, 'error': 'هذا الموظف بلا «رقم بصمة» — أضفه من قائمة الموظفين أولاً'}), 400
        try:
            jpeg = prepare_photo(data)
        except DahuaError as e:
            return jsonify({'ok': False, 'error': str(e)}), 400
        results = _run(_devices(conn, ids), upload_face, emp['device_uid'].strip(), emp['name'], jpeg)
        _audit(conn, 'dahua_face_photo', f"{emp['name']}: " + '; '.join(f"{r['device']}: {'تم' if r['ok'] else r['error']}" for r in results))
        conn.commit()
        return jsonify({'ok': True, 'results': results})
    finally:
        conn.close()


@bp.route('/api/dahua/live', methods=['GET'])
def api_live():
    if not _admin_ok():
        return _deny()
    since = int(request.args.get('since') or 0)
    return jsonify({'ok': True, 'state': live_state(), 'events': [e for e in _EVENTS if e['id'] > since]})
