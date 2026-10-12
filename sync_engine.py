"""
مزامنة بيانات محلية <-> قاعدة بيانات مركزية سحابية.

الفكرة: بدل تشارك ملف SQLite نفسه بين عدة نسخ (خطر تلف/تعارض حقيقي عند
الكتابة من أكثر من جهاز بنفس الوقت)، كل "فرع" (نسخة محلية يشتغل عليها
مسؤول تقني - سحب من الأجهزة، تعديل موظفين) يحتفظ بقاعدته الخاصة، ويرفع
فقط التغييرات الجديدة (موظفين/بصمات) لنسخة أخرى من نفس النظام تعمل كـ
"القاعدة الرئيسية" (مثلاً نسخة مستضافة سحابياً يدخل عليها موظف الموارد
البشرية للقراءة والتحليل والتقارير مباشرة) عبر طلب HTTP واحد بضغطة زر
"نشر ومزامنة" - وليس مزامنة تلقائية مستمرة ولا قاعدة بيانات مشتركة فعلياً.

المصادقة بين الفرع والمركزي: مفتاح نصي بسيط (sync_api_key) يجب أن يكون
مطابقاً تماماً على الجهتين - يُرسَل برأس HTTP (X-Sync-Key) بدل تسجيل دخول
عادي، لأنه اتصال بين خادمين لا بين متصفح ومستخدم.
"""
import requests

_TIMEOUT = 30


def get_unsynced_payload(conn):
    """يجمع كل صفوف employees/punches غير المرفوعة بعد (synced = 0) بصيغة
    قابلة للتحويل لـJSON مباشرة، مع أرقام id المحلية (تُستخدم فقط محلياً
    بعد نجاح الرفع لتعليمها synced = 1 - لا معنى لها بالقاعدة المركزية)."""
    employees = [dict(r) for r in conn.execute(
        "SELECT id, name, dept, device_uid, active FROM employees WHERE synced = 0").fetchall()]
    punches = [dict(r) for r in conn.execute(
        "SELECT id, name, date, dept, time_in, time_out, batch_id FROM punches WHERE synced = 0").fetchall()]
    return {'employees': employees, 'punches': punches}


def mark_synced(conn, employee_ids, punch_ids):
    if employee_ids:
        placeholders = ','.join('?' * len(employee_ids))
        conn.execute(f"UPDATE employees SET synced = 1 WHERE id IN ({placeholders})", employee_ids)
    if punch_ids:
        placeholders = ','.join('?' * len(punch_ids))
        conn.execute(f"UPDATE punches SET synced = 1 WHERE id IN ({placeholders})", punch_ids)
    conn.commit()


def push_to_central(central_url, api_key, payload):
    """يرسل التغييرات المحلية (payload من get_unsynced_payload) للنسخة
    المركزية عبر HTTP POST. يُرجع dict: {ok, added, updated, imported, error}."""
    if not central_url or not central_url.strip():
        return {'ok': False, 'error': 'يرجى تعبئة "رابط القاعدة الرئيسية" بالإعدادات أولاً'}
    if not api_key or not api_key.strip():
        return {'ok': False, 'error': 'يرجى تعبئة "مفتاح المزامنة" بالإعدادات أولاً (يجب أن يطابق نفس '
                                       'المفتاح المضبوط على القاعدة الرئيسية)'}
    url = central_url.strip().rstrip('/') + '/api/sync/receive'
    try:
        resp = requests.post(url, json=payload, headers={'X-Sync-Key': api_key.strip()}, timeout=_TIMEOUT)
    except requests.exceptions.RequestException as e:
        return {'ok': False, 'error': f'تعذّر الاتصال بالقاعدة الرئيسية: {e}'}

    if resp.status_code == 401:
        return {'ok': False, 'error': 'مفتاح المزامنة غير مطابق - تأكد أنه نفس القيمة المضبوطة بإعدادات '
                                       'القاعدة الرئيسية بالضبط'}
    if resp.status_code == 404:
        return {'ok': False, 'error': 'الرابط لا يستضيف نسخة من هذا النظام (نقطة /api/sync/receive غير '
                                       'موجودة) - تأكد من صحة الرابط'}
    try:
        data = resp.json()
    except ValueError:
        return {'ok': False, 'error': f'رد غير متوقَّع من القاعدة الرئيسية (HTTP {resp.status_code})'}
    if resp.status_code != 200:
        return {'ok': False, 'error': data.get('error', f'فشل الرفع (HTTP {resp.status_code})')}
    return data


def receive_sync(conn, payload, run_full_analysis_fn):
    """الجهة المركزية: يدمج موظفين/بصمات مُستلَمة من فرع محلي. الموظفون
    يُطابَقون/يُحدَّثون بنفس منطق استيراد الموظفين (device_uid أو الاسم)،
    والبصمات تُدرَج مباشرة (لا تكرار حقيقي متوقَّع بين الفروع لأن كل فرع
    يرفع بصماته هو فقط) ثم يُعاد تحليل كامل البيانات فوراً حتى تظهر
    التقارير محدَّثة للحظتها بلا أي إجراء إضافي من موظف الموارد البشرية."""
    employees = payload.get('employees') or []
    punches = payload.get('punches') or []

    added = updated = 0
    for emp in employees:
        name = (emp.get('name') or '').strip()
        if not name:
            continue
        dept = (emp.get('dept') or '').strip()
        device_uid = (emp.get('device_uid') or '').strip() or None
        existing = conn.execute(
            "SELECT id FROM employees WHERE (device_uid IS NOT NULL AND device_uid != '' AND device_uid = ?) "
            "OR name = ?", (device_uid or '', name)
        ).fetchone()
        if existing:
            conn.execute("UPDATE employees SET dept = ?, device_uid = COALESCE(?, device_uid), "
                         "active = ? WHERE id = ?",
                         (dept, device_uid, int(emp.get('active', 1)), existing['id']))
            updated += 1
        else:
            try:
                conn.execute(
                    "INSERT INTO employees (name, dept, device_uid, active) VALUES (?, ?, ?, ?)",
                    (name, dept, device_uid, int(emp.get('active', 1)))
                )
                added += 1
            except Exception:
                conn.execute("UPDATE employees SET dept = ?, device_uid = COALESCE(?, device_uid) "
                             "WHERE name = ?", (dept, device_uid, name))
                updated += 1

    imported = 0
    if punches:
        conn.executemany(
            "INSERT INTO punches (name, date, dept, time_in, time_out, batch_id) VALUES (?, ?, ?, ?, ?, ?)",
            [(p.get('name', ''), p.get('date', ''), p.get('dept', ''), p.get('time_in', ''),
              p.get('time_out', ''), p.get('batch_id', '')) for p in punches if p.get('name') and p.get('date')]
        )
        imported = len(punches)

    conn.commit()
    if added or updated or imported:
        run_full_analysis_fn(conn)
        conn.commit()

    return {'ok': True, 'employees_added': added, 'employees_updated': updated, 'punches_imported': imported}
