"""
نسخة احتياطية لملف قاعدة البيانات (attendance_web.db) على OneDrive تابع
لمؤسسة المستخدم - عبر نفس تطبيق Microsoft Graph API المسجَّل أصلاً لميزة
إرسال البريد (graph_email_sender.py)، بإضافة صلاحية Application واحدة
فقط: Files.ReadWrite.All (مع موافقة المدير) - لا حاجة لتسجيل تطبيق جديد
ولا لأي حساب Google، ومجاني بالكامل ضمن اشتراك Microsoft 365 الحالي.

بديل لمشاركة ملف SQLite يدوياً عبر رابط Google Drive (يحتاج تسجيل دخول
Google غير متوفر لحسابات Microsoft 365 المؤسسية).
"""
import os

import requests

from graph_email_sender import _get_access_token

_GRAPH_BASE = 'https://graph.microsoft.com/v1.0'
_SIMPLE_UPLOAD_LIMIT = 4 * 1024 * 1024  # حد PUT المباشر حسب توثيق Graph
_CHUNK_SIZE = 5 * 1024 * 1024  # مضاعف لـ320KiB كما يوصي توثيق Graph لجلسات الرفع


def _drive_item_url(upn, folder, filename):
    folder = (folder or '').strip().strip('/')
    path = f'{folder}/{filename}' if folder else filename
    return f'{_GRAPH_BASE}/users/{upn}/drive/root:/{path}:'


def upload_file(tenant_id, client_id, client_secret, upn, folder, local_path, remote_filename=None):
    """يرفع local_path لمجلد folder بـOneDrive تبع upn - يستخدم PUT مباشر
    للملفات الصغيرة (<4MB) وجلسة رفع مجزَّأة (upload session) للملفات
    الأكبر (قاعدة بيانات فيها آلاف البصمات قد تتجاوز هذا الحد بسهولة).
    يُرجع dict: {ok, webUrl} أو {ok: False, error}."""
    if not (tenant_id and client_id and client_secret and upn):
        return {'ok': False, 'error': 'إعدادات Graph غير مكتملة (Tenant ID/Client ID/Client Secret) - '
                                       'راجع إعدادات البريد بتبويب "الجدولة التلقائية" أولاً'}
    if not os.path.isfile(local_path):
        return {'ok': False, 'error': f'الملف غير موجود: {local_path}'}

    try:
        token = _get_access_token(tenant_id, client_id, client_secret)
    except RuntimeError as e:
        return {'ok': False, 'error': str(e)}

    filename = remote_filename or os.path.basename(local_path)
    item_url = _drive_item_url(upn, folder, filename)
    size = os.path.getsize(local_path)
    headers = {'Authorization': f'Bearer {token}'}

    try:
        if size <= _SIMPLE_UPLOAD_LIMIT:
            with open(local_path, 'rb') as fh:
                resp = requests.put(f'{item_url}/content', headers=headers, data=fh, timeout=60)
        else:
            resp = _upload_large_file(item_url, headers, local_path, size)
    except requests.RequestException as e:
        return {'ok': False, 'error': f'تعذّر الاتصال بـ Microsoft Graph: {e}'}

    if resp.status_code not in (200, 201):
        try:
            detail = resp.json().get('error', {}).get('message', '') or resp.text[:300]
        except ValueError:
            detail = resp.text[:300]
        return {'ok': False, 'error': f'فشل الرفع لـOneDrive (كود {resp.status_code}): {detail}'}

    data = resp.json()
    return {'ok': True, 'webUrl': data.get('webUrl', '')}


def _upload_large_file(item_url, headers, local_path, size):
    """جلسة رفع مجزَّأة (Graph upload session) - مطلوبة إجبارياً للملفات
    الأكبر من 4 ميجابايت. تُرجع كائن requests.Response للطلب الأخير
    (يحوي بيانات الملف النهائي عند النجاح)."""
    session_resp = requests.post(f'{item_url}/createUploadSession', headers=headers,
                                  json={'item': {'@microsoft.graph.conflictBehavior': 'replace'}}, timeout=30)
    session_resp.raise_for_status()
    upload_url = session_resp.json()['uploadUrl']

    with open(local_path, 'rb') as fh:
        start = 0
        resp = None
        while start < size:
            chunk = fh.read(_CHUNK_SIZE)
            end = start + len(chunk) - 1
            resp = requests.put(
                upload_url,
                headers={'Content-Length': str(len(chunk)), 'Content-Range': f'bytes {start}-{end}/{size}'},
                data=chunk, timeout=120,
            )
            if resp.status_code not in (200, 201, 202):
                return resp
            start += len(chunk)
    return resp
