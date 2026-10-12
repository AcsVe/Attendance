"""
إرسال البريد الإلكتروني عبر Microsoft Graph API (Application Permissions -
Client Credentials Flow) - بديل حديث لمسار SMTP AUTH التقليدي (email_sender.py)،
مفيد خصوصاً للمؤسسات التي عطّلت SMTP AUTH بمستأجر Microsoft 365 الخاص بها
(التوجّه الافتراضي الحالي لمايكروسوفت لكل المستأجرين الجدد).

المتطلبات على جهة Azure AD / Entra ID (خارج هذا النظام تماماً - يقوم بها
مدير المستأجر مرة واحدة):
  1. تسجيل تطبيق جديد (App registrations -> New registration).
  2. إضافة صلاحية API من نوع "Application permissions" -> Microsoft Graph
     -> Mail.Send، ثم الضغط على "Grant admin consent".
  3. إنشاء "Client secret" جديد (Certificates & secrets) ونسخ قيمته فوراً
     (لا تظهر مجدداً بعد إغلاق الصفحة).
  4. (يُستحسن بشدة) تقييد التطبيق بصندوق بريد واحد فقط عبر
     "Application Access Policy" بدل تركه يرسل نيابة عن أي مستخدم
     بالمستأجر - راجع توثيق مايكروسوفت لـ New-ApplicationAccessPolicy.

الإعدادات المطلوبة هنا (Tenant ID، Client ID، Client Secret، وبريد
المُرسِل UPN) تُدخَل بتبويب "الجدولة التلقائية" بالواجهة، وتُحفَظ بنفس
جدول app_settings المستخدَم لإعدادات SMTP.
"""
import base64

import requests

_TOKEN_URL = 'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token'
_SEND_MAIL_URL = 'https://graph.microsoft.com/v1.0/users/{upn}/sendMail'


def _get_access_token(tenant_id, client_id, client_secret):
    try:
        resp = requests.post(
            _TOKEN_URL.format(tenant=tenant_id),
            data={
                'client_id': client_id,
                'client_secret': client_secret,
                'scope': 'https://graph.microsoft.com/.default',
                'grant_type': 'client_credentials',
            },
            timeout=20,
        )
    except requests.RequestException as e:
        raise RuntimeError(f'تعذّر الاتصال بخادم مصادقة Azure AD: {e}')

    if resp.status_code != 200:
        try:
            detail = resp.json().get('error_description', '') or resp.text[:300]
        except ValueError:
            detail = resp.text[:300]
        raise RuntimeError(f'فشل الحصول على رمز دخول من Azure AD (كود {resp.status_code}): {detail}')

    token = resp.json().get('access_token')
    if not token:
        raise RuntimeError('لم يُرجِع Azure AD رمز دخول صالحاً')
    return token


def send_email(tenant_id, client_id, client_secret, sender_upn, recipients, subject,
               plain_body, html_body=None, attachment_bytes=None, attachment_filename=None):
    """
    يرسل بريداً عبر Microsoft Graph API نيابة عن sender_upn، بنفس تعاقد
    email_sender.send_email بمسار SMTP (نفس اسم الدالة والوسائط، يختلف
    فقط بآلية النقل) - يرمي استثناء عند أي فشل (مصادقة/صلاحيات/إرسال)
    على المستدعي التقاطه وتسجيله.
    """
    if not (tenant_id and client_id and client_secret and sender_upn and recipients):
        raise ValueError('إعدادات Graph غير مكتملة (Tenant ID/Client ID/Client Secret/بريد المُرسِل/المستلمون)')

    token = _get_access_token(tenant_id, client_id, client_secret)

    message = {
        'subject': subject,
        'body': {
            'contentType': 'HTML' if html_body else 'Text',
            'content': html_body or plain_body,
        },
        'toRecipients': [{'emailAddress': {'address': r}} for r in recipients],
    }
    if attachment_bytes is not None and attachment_filename:
        message['attachments'] = [{
            '@odata.type': '#microsoft.graph.fileAttachment',
            'name': attachment_filename,
            'contentType': 'application/pdf',
            'contentBytes': base64.b64encode(attachment_bytes).decode('ascii'),
        }]

    try:
        resp = requests.post(
            _SEND_MAIL_URL.format(upn=sender_upn),
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            json={'message': message, 'saveToSentItems': True},
            timeout=30,
        )
    except requests.RequestException as e:
        raise RuntimeError(f'تعذّر الاتصال بـ Microsoft Graph: {e}')

    if resp.status_code not in (200, 202):
        try:
            detail = resp.json().get('error', {}).get('message', '') or resp.text[:300]
        except ValueError:
            detail = resp.text[:300]
        raise RuntimeError(f'فشل إرسال البريد عبر Graph (كود {resp.status_code}): {detail}')
