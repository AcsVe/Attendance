"""
طبقة التكامل مع أجهزة البصمة ZKTeco - منقولة بنفس منطق النسخة المكتبية
(home.py) لكن عبر الشبكة مباشرة (TCP/IP، بروتوكول ZK القياسي) بدل الاعتماد
على كابل USB محلي أو ملف att.mdb حصراً. تستخدم حزمة pyzk المُضمَّنة بالمشروع
(مجلد zk/ - راجع zk/NOTICE.md) - لا تحتاج تثبيت أي شيء إضافي، وتعمل على أي
نظام تشغيل (ويندوز/لينكس) طالما الجهاز قابل للوصول بالشبكة على نفس المنفذ
(افتراضياً 4370).

كل الدوال هنا "أفضل جهد" (best-effort): أي خطأ اتصال أو استثناء من الجهاز
يُلتقط ويُعاد كنص عربي واضح بدل ما يكسر الطلب بالكامل - المستخدم يشوف بالضبط
أي جهاز فشل ولماذا، تماماً متل تنبيهات النسخة المكتبية.
"""
import threading
from collections import deque
from datetime import datetime

from zk import ZK
from zk.user import User as ZKUser
from zk.exception import ZKNetworkError, ZKErrorConnection, ZKErrorResponse

import db

CONNECT_TIMEOUT = 8


def set_user_overwrite(conn, uid, name, privilege=0, password='', group_id='', user_id='', card=0):
    """نفس conn.set_user لكن بمنطق "استبدال/overwrite" فعلي بدل الاعتماد على
    أن الجهاز يقبل CMD_USER_WRQ كإنشاء أو تحديث تلقائياً - بعض أجهزة ZKTeco
    (أو بعض حالات تعارض uid/user_id) ترفض الأمر برسالة "Can't set user" لو
    كان الرقم محجوزاً ببيانات متعارضة. نحاول set_user مباشرة أولاً (أسرع،
    ويحافظ على القوالب الحيوية المرتبطة بنفس uid لو الجهاز قبِلها)، ولو فشل
    نحذف المستخدم بنفس uid (نتجاهل فشل الحذف - يعني مو موجود أصلاً) ثم نعيد
    محاولة set_user مرة وحدة - لو فشلت هالمرة كمان، نرفع الاستثناء الأصلي
    حتى تظهر رسالة واضحة للمستخدم بدل صمت أو رسالة مضلِّلة."""
    try:
        conn.set_user(uid=uid, name=name, privilege=privilege, password=password,
                       group_id=group_id, user_id=user_id, card=card)
        return
    except Exception as first_error:
        try:
            conn.delete_user(uid=uid)
        except Exception:
            pass  # المستخدم غير موجود أصلاً بهذا uid - طبيعي، نكمل لإعادة المحاولة
        try:
            conn.set_user(uid=uid, name=name, privilege=privilege, password=password,
                           group_id=group_id, user_id=user_id, card=card)
        except Exception:
            raise first_error  # نفس رسالة الخطأ الأصلية أوضح للمستخدم من خطأ إعادة المحاولة


def _connect(device_row):
    pwd = device_row['password'] or '0'
    try:
        pwd = int(pwd)
    except (TypeError, ValueError):
        pwd = 0
    zk = ZK(device_row['ip'], port=int(device_row['port'] or 4370), timeout=CONNECT_TIMEOUT,
            password=pwd, force_udp=False, ommit_ping=False)
    return zk.connect()


def test_connection(device_row):
    """يتصل بالجهاز ويجلب معلوماته الأساسية - يُستخدم لزر "اختبار الاتصال"."""
    try:
        conn = _connect(device_row)
        try:
            info = {
                'ok': True,
                'device_name': _safe(conn.get_device_name),
                'firmware': _safe(conn.get_firmware_version),
                'serial': _safe(conn.get_serialnumber),
                'platform': _safe(conn.get_platform),
                'user_count': len(conn.get_users()),
                'time': str(_safe(conn.get_time)),
            }
            return info
        finally:
            conn.disconnect()
    except (ZKNetworkError, ZKErrorConnection, ZKErrorResponse) as e:
        return {'ok': False, 'error': f'تعذّر الاتصال بالجهاز: {e}'}
    except Exception as e:
        return {'ok': False, 'error': f'خطأ غير متوقع أثناء الاتصال: {e}'}


def _safe(fn, default=''):
    try:
        return fn()
    except Exception:
        return default


def pull_attendance(device_row, date_from=None, date_to=None, uid_to_employee=None):
    """
    يسحب كل سجلات البصمة الخام من الجهاز (get_attendance) ويجمّعها لكل
    (موظف، تاريخ): أول بصمة باليوم = وقت الحضور، آخر بصمة = وقت الانصراف
    (نفس منطق "التجميع" بالنسخة المكتبية - أقرب بصمتين لبداية/نهاية اليوم).

    uid_to_employee: {device_uid_str: employee_name} - خريطة المطابقة
    (من جدول employees.device_uid) - أي بصمة لرقم غير مسجَّل بالخريطة تُرجَع
    ضمن unmatched_uids بدل ما تُفقد بصمت.

    يُرجع dict: {ok, rows: [{name, date, time_in, time_out}], unmatched_uids, error}
    """
    uid_to_employee = uid_to_employee or {}
    try:
        conn = _connect(device_row)
    except Exception as e:
        return {'ok': False, 'error': f'تعذّر الاتصال بالجهاز «{device_row["name"]}»: {e}'}

    try:
        try:
            records = conn.get_attendance() or []
        finally:
            conn.disconnect()
    except Exception as e:
        return {'ok': False, 'error': f'تعذّر سحب البصمات من «{device_row["name"]}»: {e}'}

    # ===== تجميع: {(uid, date_str): [datetime, ...]} =====
    buckets = {}
    unmatched_uids = set()
    for rec in records:
        try:
            ts = rec.timestamp
            uid = str(rec.user_id).strip()
        except AttributeError:
            continue
        if date_from and ts.date() < date_from:
            continue
        if date_to and ts.date() > date_to:
            continue
        if uid not in uid_to_employee:
            unmatched_uids.add(uid)
            continue
        key = (uid, ts.strftime('%Y-%m-%d'))
        buckets.setdefault(key, []).append(ts)

    rows = []
    for (uid, date_str), stamps in buckets.items():
        stamps.sort()
        name = uid_to_employee[uid]
        time_in = stamps[0].strftime('%H:%M:%S')
        time_out = stamps[-1].strftime('%H:%M:%S') if len(stamps) > 1 else ''
        rows.append({'name': name, 'date': date_str, 'time_in': time_in, 'time_out': time_out})

    return {'ok': True, 'rows': rows, 'unmatched_uids': sorted(unmatched_uids)}


def push_employees(device_row, employees):
    """يرفع قائمة موظفين (لازم device_uid رقمي لكل واحد) كمستخدمين على
    الجهاز مباشرة - set_user لكل موظف. يُرجع نتيجة كل موظف على حدة."""
    try:
        conn = _connect(device_row)
    except Exception as e:
        return {'ok': False, 'error': f'تعذّر الاتصال بالجهاز: {e}'}

    results = []
    try:
        for emp in employees:
            uid_raw = (emp.get('device_uid') or '').strip()
            if not uid_raw:
                results.append({'name': emp['name'], 'ok': False, 'error': 'بدون رقم بصمة (device_uid)'})
                continue
            try:
                uid = int(uid_raw)
                set_user_overwrite(conn, uid=uid, name=emp['name'][:24], privilege=0, user_id=str(uid))
                results.append({'name': emp['name'], 'ok': True})
            except Exception as e:
                results.append({'name': emp['name'], 'ok': False, 'error': str(e)})
    finally:
        conn.disconnect()
    return {'ok': True, 'results': results}


def clear_device_attendance(device_row):
    """يمسح كل سجلات الحضور المخزَّنة على الجهاز نفسه (بعد سحبها بنجاح) -
    عملية لا يمكن التراجع عنها، يجب تأكيدها بالواجهة قبل الاستدعاء."""
    try:
        conn = _connect(device_row)
        try:
            conn.clear_attendance()
            return {'ok': True}
        finally:
            conn.disconnect()
    except Exception as e:
        return {'ok': False, 'error': f'تعذّر مسح بيانات الجهاز: {e}'}


def query_device_users(device_row):
    """يستعلم من الجهاز نفسه عن قائمة المستخدمين المسجَّلين عليه فعلياً
    (uid الداخلي، رقم البصمة/user_id، الاسم، الصلاحية) - عكس قائمة الموظفين
    المحفوظة بقاعدة بيانات التطبيق، هاي القائمة تعكس الواقع الفعلي على
    الجهاز، وتساعد تحديد/حذف مستخدمين موجودين على الجهاز بس مو بالتطبيق (أو
    العكس) بدل الاعتماد على كتابة أرقام البصمة يدوياً."""
    try:
        conn = _connect(device_row)
    except Exception as e:
        return {'ok': False, 'error': f'تعذّر الاتصال بالجهاز: {e}'}
    try:
        users = conn.get_users()
        rows = [{'uid': u.uid, 'user_id': u.user_id or str(u.uid), 'name': u.name or '',
                 'privilege': u.privilege} for u in users]
        rows.sort(key=lambda r: r['uid'])
        return {'ok': True, 'rows': rows}
    except Exception as e:
        return {'ok': False, 'error': f'تعذّر قراءة قائمة المستخدمين من الجهاز: {e}'}
    finally:
        conn.disconnect()


def delete_device_users(device_row, device_uids=None):
    """يحذف مستخدمين محدَّدين من الجهاز (device_uids)، أو كل المستخدمين
    لو تُركت فارغة - عملية لا يمكن التراجع عنها."""
    try:
        conn = _connect(device_row)
    except Exception as e:
        return {'ok': False, 'error': f'تعذّر الاتصال بالجهاز: {e}'}

    results = []
    try:
        if not device_uids:
            all_users = conn.get_users()
            device_uids = [str(u.user_id or u.uid) for u in all_users]
        for uid_raw in device_uids:
            try:
                uid = int(uid_raw)
                conn.delete_user(uid=uid)
                results.append({'uid': uid_raw, 'ok': True})
            except Exception as e:
                results.append({'uid': uid_raw, 'ok': False, 'error': str(e)})
    finally:
        conn.disconnect()
    return {'ok': True, 'results': results}


def unlock_door(device_row, seconds=3):
    """يفتح قفل الباب المتصل بالجهاز (ريليه) - يعمل فقط للأجهزة التي لديها
    قفل فعلي موصول؛ غير ذلك بيرجع نجاح بدون أي أثر مرئي."""
    try:
        conn = _connect(device_row)
        try:
            conn.unlock(int(seconds or 3))
            return {'ok': True}
        finally:
            conn.disconnect()
    except Exception as e:
        return {'ok': False, 'error': f'تعذّر فتح الباب: {e}'}


def copy_fingerprint_templates(source_device_row, target_device_rows, device_uids):
    """
    ميزة تجريبية (نفس تصنيف النسخة المكتبية) - تنسخ قوالب بصمة الإصبع
    لمستخدمين محدَّدين من جهاز مصدر لعدة أجهزة هدف. تعتمد على get_templates
    (تُرجع كل القوالب المخزَّنة على الجهاز المصدر دفعة واحدة) ثم
    save_user_template لكل جهاز هدف - أبطأ وأقل ضماناً من pyzk نفسها،
    فأي فشل لموظف/جهاز بعينه يُسجَّل بدون ما يوقف بقية العملية.
    """
    try:
        src = _connect(source_device_row)
    except Exception as e:
        return {'ok': False, 'error': f'تعذّر الاتصال بالجهاز المصدر: {e}'}

    try:
        templates = src.get_templates()
        all_users = src.get_users()
        # ===== users: نفس "رقم البصمة" المخزَّن بجدول الموظفين
        # (employees.device_uid) هو user_id بمصطلح pyzk، أما uid فهو رقم
        # الخانة الداخلي على الجهاز نفسه (قد يختلف بين جهازين لنفس
        # الموظف) - لازم نربط القوالب (مفهرَسة بـuid الداخلي) بـuser_id
        # الحقيقي حتى تُطابق device_uid المُدخَل من الواجهة بشكل صحيح =====
        uid_to_userid = {u.uid: str(u.user_id or u.uid) for u in all_users}
        users = {str(u.user_id or u.uid): u for u in all_users}
    except Exception as e:
        src.disconnect()
        return {'ok': False, 'error': f'تعذّر جلب القوالب من الجهاز المصدر: {e}'}
    src.disconnect()

    wanted = set(device_uids) if device_uids else set(users.keys())
    by_uid = {}
    for t in templates:
        user_id_str = uid_to_userid.get(t.uid)
        if user_id_str and user_id_str in wanted:
            by_uid.setdefault(user_id_str, []).append(t)

    results = []
    for target in target_device_rows:
        try:
            tconn = _connect(target)
        except Exception as e:
            results.append({'device': target['name'], 'ok': False, 'error': f'تعذّر الاتصال: {e}'})
            continue
        for uid_str, finger_templates in by_uid.items():
            try:
                src_user = users[uid_str]
                # ===== نبني كائن مستخدم جديد بنفس uid الداخلي المُنشَأ للتو
                # بالجهاز الهدف (uid=device_uid دائماً - نفس اتفاقية
                # push_employees) بدل إعادة استخدام uid المصدر الداخلي، لأنه
                # قد يختلف بين الجهازين لنفس الموظف =====
                target_uid = int(uid_str)
                set_user_overwrite(tconn, uid=target_uid, name=src_user.name or '', privilege=0, user_id=str(uid_str))
                target_user = ZKUser(uid=target_uid, name=src_user.name or '', privilege=0,
                                      user_id=str(uid_str))
                tconn.save_user_template(target_user, finger_templates)
                results.append({'device': target['name'], 'uid': uid_str, 'ok': True})
            except Exception as e:
                results.append({'device': target['name'], 'uid': uid_str, 'ok': False, 'error': str(e)})
        tconn.disconnect()

    return {'ok': True, 'results': results}


# ============================================================
# ===== مراقبة حية (Live Capture) =====
# ============================================================
# ===== حالة عامة بالعملية (نفس مبدأ متغيّر واحد مشترك بالنسخة المكتبية) -
# كافية لعملية واحدة نشطة بكل مرة (لا حاجة لتزامن معقّد بتطبيق ويب بمستخدم
# إداري واحد أو قليل يشغّل هذه الميزة بلحظة معيّنة) =====
_live_state = {
    'running': False,
    'threads': [],
    'events': deque(maxlen=300),
    'next_id': 1,
    'lock': threading.Lock(),
}


def _record_live_punch_and_analyze(name, date_str, time_str):
    """يُدرج/يحدّث بصمة موظف بجدول punches فور وصولها من المراقبة الحية،
    ثم يعيد تشغيل التحليل الكامل مباشرة - بهيك التقارير/الإحصائيات/لوحة
    التحكم تعكس حالة التأخير الفعلية فوراً بدون الحاجة لضغط "تحليل
    البيانات" يدوياً بعد كل بصمة.

    التجميع: أول بصمة باليوم = وقت الحضور، وكل بصمة بعدها تحدّث وقت
    الانصراف لآخر وقت وصل (نفس منطق سحب الأجهزة/استيراد att.mdb: أول/آخر
    بصمة باليوم) - بصف واحد فقط لكل (موظف، تاريخ) بدل صف جديد بكل بصمة."""
    conn = db.get_db()
    try:
        emp = conn.execute("SELECT dept FROM employees WHERE name = ?", (name,)).fetchone()
        dept = emp['dept'] if emp else ''
        existing = conn.execute(
            "SELECT id, time_in, time_out FROM punches WHERE name = ? AND date = ?", (name, date_str)
        ).fetchone()
        if existing:
            new_time_in = min(existing['time_in'], time_str) if existing['time_in'] else time_str
            new_time_out = max(existing['time_out'] or existing['time_in'] or time_str, time_str)
            conn.execute("UPDATE punches SET time_in = ?, time_out = ? WHERE id = ?",
                         (new_time_in, new_time_out, existing['id']))
        else:
            conn.execute(
                "INSERT INTO punches (name, date, dept, time_in, time_out, batch_id) VALUES (?, ?, ?, ?, ?, ?)",
                (name, date_str, dept, time_str, time_str, 'live')
            )
        conn.commit()

        # استيراد مؤجَّل (لا بأعلى الملف) لتفادي حلقة استيراد مع app.py، الذي
        # يستورد zk_devices بدوره - نفس أسلوب scheduler.py بالضبط
        import app as app_module
        app_module.run_full_analysis(conn)
        conn.commit()
    finally:
        conn.close()


def _live_worker(device_row, uid_to_employee):
    try:
        conn = _connect(device_row)
    except Exception as e:
        with _live_state['lock']:
            _live_state['events'].append({
                'id': _live_state['next_id'], 'device': device_row['name'],
                'time': datetime.now().strftime('%H:%M:%S'), 'name': '', 'uid': '',
                'error': f'تعذّر الاتصال: {e}',
            })
            _live_state['next_id'] += 1
        return
    try:
        for attendance in conn.live_capture(new_timeout=5):
            if not _live_state['running']:
                break
            if attendance is None:
                continue
            uid_str = str(attendance.user_id)
            matched_name = uid_to_employee.get(uid_str)
            event = {
                'id': _live_state['next_id'], 'device': device_row['name'],
                'time': attendance.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                'uid': uid_str, 'name': matched_name or f'رقم بصمة غير مسجَّل ({uid_str})',
            }
            if matched_name:
                try:
                    _record_live_punch_and_analyze(
                        matched_name, attendance.timestamp.strftime('%Y-%m-%d'),
                        attendance.timestamp.strftime('%H:%M:%S'))
                    event['analyzed'] = True
                except Exception as e:
                    event['analyzed'] = False
                    event['analyze_error'] = str(e)
            with _live_state['lock']:
                _live_state['events'].append(event)
                _live_state['next_id'] += 1
    except Exception as e:
        with _live_state['lock']:
            _live_state['events'].append({
                'id': _live_state['next_id'], 'device': device_row['name'],
                'time': datetime.now().strftime('%H:%M:%S'), 'name': '', 'uid': '',
                'error': f'انقطع الاتصال أثناء المراقبة: {e}',
            })
            _live_state['next_id'] += 1
    finally:
        try:
            conn.disconnect()
        except Exception:
            pass


def start_live_capture(device_rows, uid_to_employee):
    if _live_state['running']:
        return {'ok': False, 'error': 'المراقبة الحية قيد التشغيل بالفعل'}
    _live_state['running'] = True
    _live_state['threads'] = []
    for dev in device_rows:
        th = threading.Thread(target=_live_worker, args=(dev, uid_to_employee), daemon=True)
        th.start()
        _live_state['threads'].append(th)
    return {'ok': True}


def stop_live_capture():
    _live_state['running'] = False
    return {'ok': True}


def get_live_events(since_id=0):
    with _live_state['lock']:
        events = [e for e in _live_state['events'] if e['id'] > since_id]
    return {'ok': True, 'running': _live_state['running'], 'events': events}
