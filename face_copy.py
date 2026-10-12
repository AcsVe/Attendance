"""
نسخ بصمة الوجه بين أجهزة ZKTeco - منقول حرفياً عن نفس منطق النسخة المكتبية
(home.py._face_sync_thread_body): pyzk لإنشاء/تحديث الموظف (الاسم، الصلاحية،
كلمة السر، البطاقة) على الجهاز الهدف أولاً، ثم مكوّن COM (zkemkeeper.dll -
نفس مكوّن برنامج ZKTime الرسمي) لقراءة/كتابة بصمة الوجه نفسها فقط
(GetUserFaceStr/SetUserFaceStr) - pyzk لا يدعم بيانات الوجه إطلاقاً.

ميزة Windows حصراً (COM automation + عادةً بايثون 32-bit تحديداً حسب نسخة
الجهاز) - نفس القيد الموجود بالنسخة المكتبية بالضبط، فنتحقق من توفرها بأمان
ونُرجع رسالة عربية واضحة بدل انهيار الطلب لو غير متاحة (مثلاً أثناء التشغيل
على خادم لينكس بمرحلة النشر الثانية).
"""
from zk import ZK
from zk.exception import ZKNetworkError, ZKErrorConnection, ZKErrorResponse
from zk_devices import set_user_overwrite

try:
    import win32com.client as win32com_client
    import pythoncom
    WIN32COM_AVAILABLE = True
except ImportError:
    win32com_client = None
    pythoncom = None
    WIN32COM_AVAILABLE = False

FACE_INDEX = 50  # ثابت مؤكَّد من تجربة فعلية بالنسخة المكتبية - فهرس بصمة الوجه


def copy_face_templates(source_device_row, target_device_rows, employees, manual_password=''):
    """
    employees: قائمة قواميس {device_uid, name} - لازم device_uid رقمي.
    manual_password: كلمة سر مشتركة تُستخدم عند الكتابة لو كلمة سر الجهاز
        المصدر "للكتابة فقط" (Write-Only - الحالة الشائعة بمعظم الأجهزة).

    يُرجع dict: {ok, log: [نص لكل خطوة], results: {device_name: {success, failed}}}
    """
    if not WIN32COM_AVAILABLE:
        return {'ok': False, 'error': 'هذه الميزة تحتاج مكتبة pywin32 (وعادةً بايثون 32-بت) '
                                       'على نفس الجهاز الذي يشغّل النظام - غير متاحة هنا حالياً.'}

    pythoncom.CoInitialize()
    try:
        return _copy_face_templates_body(source_device_row, target_device_rows, employees, manual_password)
    finally:
        pythoncom.CoUninitialize()


def _copy_face_templates_body(source_device_row, target_device_rows, employees, manual_password):
    log = []
    collected = {}  # device_uid -> {name, face_str, face_len, privilege, card, password}

    # ===== الخطوة 1: نقرأ الصلاحية/كلمة السر/البطاقة من الجهاز المصدر
    # عبر pyzk (أوثق من قراءتها عبر zkemkeeper) =====
    privilege_map = {}
    try:
        zk_source = ZK(source_device_row['ip'], port=int(source_device_row['port'] or 4370), timeout=15, ommit_ping=True)
        conn_source = zk_source.connect()
        for u in conn_source.get_users():
            privilege_map[str(u.user_id).strip()] = {'privilege': u.privilege, 'card': u.card or 0, 'password': u.password or ''}
        conn_source.disconnect()
    except Exception as e:
        log.append(f"(تعذّرت قراءة الصلاحيات عبر pyzk - سنكمل بصلاحية عادية افتراضية): {e}")

    # ===== الخطوة 2: نقرأ بصمة الوجه نفسها عبر zkemkeeper (COM) =====
    try:
        zk = win32com_client.Dispatch('zkemkeeper.ZKEM.1')
        connected = zk.Connect_Net(source_device_row['ip'], int(source_device_row['port'] or 4370))
        if not connected:
            return {'ok': False, 'error': f"تعذّر الاتصال بالجهاز المصدر ({source_device_row['name']})"}

        for emp in employees:
            uid = (emp.get('device_uid') or '').strip()
            name = emp.get('name', '')
            if not uid:
                log.append(f"\"{name}\" - بدون رقم بصمة (device_uid)، تم تخطّيه")
                continue
            try:
                result = zk.GetUserFaceStr(1, str(uid), FACE_INDEX, "", 0)
            except Exception as e:
                log.append(f"\"{name}\" (رقم {uid}) - خطأ بالقراءة: {e}")
                continue
            success, face_str, face_len = result[0], result[1], result[2]
            if not success or not face_str:
                log.append(f"\"{name}\" (رقم {uid}) بدون بصمة وجه مسجّلة على الجهاز المصدر - تم تخطّيه")
                continue
            extra = privilege_map.get(str(uid).strip(), {'privilege': 0, 'card': 0, 'password': ''})
            final_password = manual_password if manual_password else extra['password']
            collected[uid] = {
                'name': name, 'face_str': face_str, 'face_len': face_len,
                'privilege': extra['privilege'], 'card': extra['card'], 'password': final_password,
            }
            log.append(f"\"{name}\" — تمت قراءة بصمة الوجه بنجاح (الطول: {face_len})")
        zk.Disconnect()
    except Exception as e:
        return {'ok': False, 'error': f"فشل الاتصال بالجهاز المصدر ({source_device_row['name']}): {e}"}

    if not collected:
        return {'ok': False, 'error': 'لم يتم العثور على أي بصمة وجه صالحة للموظفين المحدَّدين على الجهاز المصدر'}

    results = {}
    for target in target_device_rows:
        target_name = target['name']
        success_count, failed = 0, []

        # ===== إنشاء/تحديث الموظف (الاسم/الصلاحية) عبر pyzk قبل نسخ الوجه =====
        try:
            zk_target = ZK(target['ip'], port=int(target['port'] or 4370), timeout=15, ommit_ping=True)
            conn_target = zk_target.connect()
            for uid, data in collected.items():
                try:
                    set_user_overwrite(conn_target, uid=int(uid), name=str(data['name'])[:24], privilege=data['privilege'],
                                        password=data['password'], group_id='', user_id=str(uid), card=data['card'])
                except Exception as e:
                    log.append(f"[{target_name}] تعذّر إنشاء/تحديث \"{data['name']}\" عبر pyzk: {e}")
            conn_target.disconnect()
        except Exception as e:
            log.append(f"[{target_name}] — تعذّر الاتصال عبر pyzk لإنشاء الموظفين: {e}")

        # ===== نسخ بصمة الوجه نفسها عبر zkemkeeper =====
        try:
            zk2 = win32com_client.Dispatch('zkemkeeper.ZKEM.1')
            connected2 = zk2.Connect_Net(target['ip'], int(target['port'] or 4370))
            if not connected2:
                log.append(f"[{target_name}] — تعذّر الاتصال")
                results[target_name] = {'success': 0, 'failed': [{'name': d['name'], 'error': 'تعذّر الاتصال'} for d in collected.values()]}
                continue
            for uid, data in collected.items():
                try:
                    write_ok = zk2.SetUserFaceStr(1, uid, FACE_INDEX, data['face_str'], data['face_len'])
                    if write_ok:
                        success_count += 1
                        log.append(f"[{target_name}] ✓ نُسخت بصمة وجه \"{data['name']}\" بنجاح")
                    else:
                        failed.append({'name': data['name'], 'error': 'فشلت الكتابة على الجهاز'})
                except Exception as e:
                    failed.append({'name': data['name'], 'error': str(e)})
            zk2.Disconnect()
        except Exception as e:
            log.append(f"[{target_name}] — خطأ COM: {e}")
            failed.extend({'name': d['name'], 'error': str(e)} for d in collected.values() if d['name'] not in [f['name'] for f in failed])

        results[target_name] = {'success': success_count, 'failed': failed}

    return {'ok': True, 'log': log, 'results': results}
