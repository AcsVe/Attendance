"""
نسخة احتياطية لملف قاعدة البيانات على Google Drive عبر حساب خدمة (Service
Account) - بديل لطريقة OneDrive/Graph لمن لا يملك صلاحية "Global Admin"
على مستأجر Microsoft 365 (مطلوبة إجبارياً هناك لمنح "Admin consent").

يعمل بدون أي مكتبة تشفير خارجية (لا cryptography ولا google-auth) - توقيع
JWT لحساب الخدمة مبني يدوياً بوحدة pure_google_jwt.py، لتجنّب مشكلة معروفة:
حزمة cryptography (تبعية google-auth الأساسية) تحتاج تجميعاً من المصدر
(Rust) على منصّات مثل Termux/أندرويد بدون wheel جاهز - تماماً نفس مشكلة
pyodbc سابقاً بهذا المشروع، فتُستبعَد لنفس السبب.

الإعداد المطلوب من المستخدم (لمرة واحدة، بواجهة Google Cloud Console):
  1. إنشاء مشروع + تفعيل Google Drive API.
  2. إنشاء Service Account وتنزيل ملف JSON (Keys -> Add Key -> JSON).
  3. مشاركة مجلد على Drive الشخصي مع بريد الـService Account (حقل
     client_email بملف JSON) بصلاحية Editor.
  4. نسخ معرّف ذلك المجلد (Folder ID) من رابطه على Drive.
"""
import json
import os

import requests

from pure_google_jwt import make_signed_jwt

_TOKEN_URL = 'https://oauth2.googleapis.com/token'
_UPLOAD_URL = 'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable'
_SCOPE = 'https://www.googleapis.com/auth/drive.file'


def _load_service_account(json_path):
    if not json_path or not os.path.isfile(json_path):
        return None, f'ملف بيانات اعتماد Google (JSON) غير موجود بهذا المسار على جهاز الخادم: {json_path}'
    try:
        with open(json_path, 'r', encoding='utf-8') as fh:
            info = json.load(fh)
    except (OSError, ValueError) as e:
        return None, f'تعذّر قراءة ملف بيانات الاعتماد: {e}'
    if info.get('type') != 'service_account' or not info.get('private_key') or not info.get('client_email'):
        return None, ('ملف JSON هذا ليس بيانات اعتماد Service Account صالحة - تأكد أنه نفس الملف الذي '
                       'نزّلته من Google Cloud Console (Keys -> Add Key -> JSON)')
    return info, None


def _get_access_token(service_account_info):
    assertion = make_signed_jwt(service_account_info, _SCOPE)
    try:
        resp = requests.post(_TOKEN_URL, data={
            'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
            'assertion': assertion,
        }, timeout=20)
    except requests.RequestException as e:
        raise RuntimeError(f'تعذّر الاتصال بخادم مصادقة Google: {e}')
    if resp.status_code != 200:
        try:
            detail = resp.json().get('error_description', '') or resp.text[:300]
        except ValueError:
            detail = resp.text[:300]
        raise RuntimeError(f'فشل الحصول على رمز دخول من Google (كود {resp.status_code}): {detail}')
    token = resp.json().get('access_token')
    if not token:
        raise RuntimeError('لم يُرجِع Google رمز دخول صالحاً')
    return token


def upload_file(json_path, folder_id, local_path, remote_filename=None):
    """يرفع local_path لمجلد folder_id بـGoogle Drive (مشترَك مسبقاً مع
    بريد الـService Account بصلاحية Editor). يُرجع dict: {ok, webViewLink}
    أو {ok: False, error}."""
    info, err = _load_service_account(json_path)
    if err:
        return {'ok': False, 'error': err}
    if not folder_id:
        return {'ok': False, 'error': 'يرجى تعبئة معرّف المجلد (Folder ID) على Google Drive وحفظه أولاً'}
    if not os.path.isfile(local_path):
        return {'ok': False, 'error': f'الملف غير موجود: {local_path}'}

    try:
        token = _get_access_token(info)
    except RuntimeError as e:
        return {'ok': False, 'error': str(e)}

    filename = remote_filename or os.path.basename(local_path)
    metadata = {'name': filename, 'parents': [folder_id]}
    try:
        session_resp = requests.post(
            _UPLOAD_URL,
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json; charset=UTF-8'},
            data=json.dumps(metadata), timeout=30,
        )
    except requests.RequestException as e:
        return {'ok': False, 'error': f'تعذّر الاتصال بـ Google Drive: {e}'}

    if session_resp.status_code != 200:
        try:
            detail = session_resp.json().get('error', {}).get('message', '') or session_resp.text[:300]
        except ValueError:
            detail = session_resp.text[:300]
        return {'ok': False, 'error': f'فشل بدء جلسة الرفع (كود {session_resp.status_code}): {detail} - تأكد أن '
                                       'المجلد مشارَك فعلياً مع بريد الـService Account بصلاحية Editor، ومعرّف '
                                       'المجلد (Folder ID) صحيح.'}

    upload_url = session_resp.headers.get('Location')
    if not upload_url:
        return {'ok': False, 'error': 'لم يُرجِع Google رابط جلسة رفع صالحاً'}

    size = os.path.getsize(local_path)
    try:
        with open(local_path, 'rb') as fh:
            put_resp = requests.put(upload_url, data=fh, headers={'Content-Length': str(size)}, timeout=300)
    except requests.RequestException as e:
        return {'ok': False, 'error': f'تعذّر رفع محتوى الملف: {e}'}

    if put_resp.status_code not in (200, 201):
        try:
            detail = put_resp.json().get('error', {}).get('message', '') or put_resp.text[:300]
        except ValueError:
            detail = put_resp.text[:300]
        return {'ok': False, 'error': f'فشل رفع الملف (كود {put_resp.status_code}): {detail}'}

    data = put_resp.json()
    file_id = data.get('id', '')
    return {'ok': True, 'fileId': file_id, 'webViewLink': f'https://drive.google.com/file/d/{file_id}/view'}
