"""
استيراد ملف من رابط سحابي (Google Drive / OneDrive / Dropbox / أو أي رابط
تنزيل مباشر آخر) - بديل عن رفع الملف يدوياً من جهاز المستخدم، مفيد خصوصاً
لو الملف موجود بمساحة تخزين سحابية وصعب/بطيء تنزيله للجهاز أولاً (كما
بحالات Termux/أندرويد).

القرار المعتمد: بدون أي OAuth أو اعتماد Google/Microsoft API (يحتاج
تسجيل تطبيق واعتمادات يديرها المطوّر، ونظام لتخزين/تجديد التوكنات) - يكتفي
بتحويل روابط "المشاركة العامة" المعروفة (انسخ الرابط -> "أي شخص لديه
الرابط يمكنه العرض/التنزيل") إلى صيغة تنزيل مباشرة، ثم تنزيل الملف عبر
HTTP عادي. أي رابط تنزيل مباشر آخر (غير هذه الخدمات) يُستخدم كما هو دون أي
تحويل - فيدعم فعلياً "أي رابط جديد" يحدده المستخدم، وليس فقط الخدمات
الثلاث المذكورة.
"""
import os
import re
import tempfile
import uuid
from urllib.parse import urlparse, parse_qs, urlencode

import requests

# مهلة على شكل (مهلة الاتصال, مهلة القراءة) بدل رقم واحد - تفشل بسرعة
# وبخطأ واضح بدل "التعليق" الطويل لو الخادم البعيد وصل لكن يرد ببطء شديد
# (كما يحصل أحياناً مع صفحات تسجيل دخول SharePoint/OneDrive المعاد توجيهها)
_TIMEOUT = (10, 25)
_CHUNK = 65536
# ملفات SQLite لبعض الأجهزة (سجل بصمات عدة سنوات) قد تتجاوز الغيغابايت بسهولة -
# الحد قابل للتعديل عبر متغيّر البيئة CLOUD_IMPORT_MAX_MB لو احتاج موقع معيّن
# حداً أكبر، ويمنع أيضاً "تعليق" التنزيل لو الرابط أشار بالخطأ لملف ضخم فعلاً
_MAX_BYTES = int(os.environ.get('CLOUD_IMPORT_MAX_MB', '2048')) * 1024 * 1024


def _google_drive_direct_url(url):
    host = urlparse(url).netloc.lower()
    if 'drive.google.com' not in host and 'docs.google.com' not in host:
        return None
    m = re.search(r'/file/d/([a-zA-Z0-9_-]+)', url) or re.search(r'[?&]id=([a-zA-Z0-9_-]+)', url)
    if not m:
        return None
    return f'https://drive.google.com/uc?export=download&id={m.group(1)}'


def _dropbox_direct_url(url):
    parsed = urlparse(url)
    if 'dropbox.com' not in parsed.netloc.lower():
        return None
    # dl=0 تعرض صفحة معاينة Dropbox نفسها - dl=1 يجبرها على تنزيل مباشر
    q = parse_qs(parsed.query)
    q['dl'] = ['1']
    return parsed._replace(query=urlencode(q, doseq=True)).geturl()


def _onedrive_direct_url(url):
    host = urlparse(url).netloc.lower()
    if not any(h in host for h in ('onedrive.live.com', '1drv.ms', 'sharepoint.com')):
        return None
    parsed = urlparse(url)
    if 'download=' in parsed.query:
        new_query = re.sub(r'download=\d', 'download=1', parsed.query)
    else:
        new_query = (parsed.query + '&' if parsed.query else '') + 'download=1'
    return parsed._replace(query=new_query).geturl()


def resolve_direct_url(url):
    """يحوّل روابط المشاركة المعروفة (Google Drive/OneDrive/SharePoint/
    Dropbox) لصيغة تنزيل مباشر - أي رابط آخر (تنزيل مباشر أصلاً، أو من أي
    خدمة أخرى لم تُدرَج هنا) يُرجَع كما هو بلا أي تعديل."""
    for resolver in (_google_drive_direct_url, _dropbox_direct_url, _onedrive_direct_url):
        direct = resolver(url)
        if direct:
            return direct
    return url


def _filename_from_response(resp):
    cd = resp.headers.get('content-disposition', '')
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd)
    if m:
        return m.group(1)
    path = urlparse(resp.url).path
    return os.path.basename(path) or ''


def download_from_url(url, dest_dir=None, timeout=_TIMEOUT):
    """ينزّل ملفاً من رابط (بعد تحويل روابط المشاركة المعروفة لصيغة تنزيل
    مباشرة) إلى ملف مؤقت. يُرجع dict: {ok, path, filename} أو {ok: False, error}."""
    if not url or not url.strip():
        return {'ok': False, 'error': 'يرجى إدخال رابط الملف'}
    url = url.strip()
    if not url.lower().startswith(('http://', 'https://')):
        return {'ok': False, 'error': 'الرابط غير صالح - يجب أن يبدأ بـ http:// أو https://'}

    direct_url = resolve_direct_url(url)
    dest_dir = dest_dir or tempfile.gettempdir()
    tmp_path = os.path.join(dest_dir, f'cloud_{uuid.uuid4().hex}')

    try:
        resp = requests.get(direct_url, stream=True, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()

        # ===== ملفات Google Drive الكبيرة (أو المشكوك بها لدى فاحص
        # الفيروسات) تُرجع صفحة تحذير HTML بدل الملف مباشرة ("Google Drive -
        # Virus scan warning"). أوثق طريقة لتجاوزها هي أخذ قيمة action من
        # النموذج <form id="download-form"> الموجود بالصفحة نفسها (يحوي كل
        # المعاملات المطلوبة بما فيها uuid وconfirm بصيغتها الصحيحة، ويدعم
        # النطاق الأحدث drive.usercontent.google.com) - نعتمد هذا أولاً، ثم
        # نرجع لاستخراج "confirm=<token>" يدوياً كخطة بديلة فقط =====
        content_type = resp.headers.get('content-type', '')
        if 'drive.google.com' in direct_url and 'text/html' in content_type:
            html = resp.text
            form_action = re.search(
                r'<form[^>]+id="download-form"[^>]+action="([^"]+)"', html
            )
            confirm_url = None
            if form_action:
                action_url = form_action.group(1).replace('&amp;', '&')
                # ===== النموذج غالباً يحوي حقول input إضافية (id/export/
                # confirm/uuid) لازم تُضاف كمعاملات - نجمعها كلها بدل
                # الاكتفاء بـaction وحده =====
                hidden_inputs = re.findall(
                    r'<input[^>]+type="hidden"[^>]+name="([^"]+)"[^>]+value="([^"]*)"', html
                )
                if hidden_inputs:
                    sep = '&' if '?' in action_url else '?'
                    action_url += sep + urlencode(dict(hidden_inputs))
                confirm_url = action_url
            else:
                m = re.search(r'confirm=([0-9A-Za-z_-]+)', html)
                if not m:
                    m = re.search(r'name="confirm"\s+value="([0-9A-Za-z_-]+)"', html)
                if m:
                    confirm_url = direct_url + f'&confirm={m.group(1)}'

            if not confirm_url:
                return {'ok': False, 'error': 'تعذّر تنزيل الملف من Google Drive - تأكد أن إعداد المشاركة '
                                               '"أي شخص لديه الرابط" مفعَّل على الملف'}

            resp = requests.get(confirm_url, stream=True, timeout=timeout, allow_redirects=True)
            resp.raise_for_status()
            content_type = resp.headers.get('content-type', '')
            # ===== لو رجعت صفحة HTML مرة ثانية بعد التأكيد (تغيّر شكل صفحة
            # التحذير، أو الملف يحتاج فحصاً يدوياً لا يمكن تجاوزه تلقائياً) -
            # نتوقف بخطأ واضح بدل حفظ صفحة الويب وكأنها الملف نفسه =====
            if 'text/html' in content_type:
                return {'ok': False, 'error': 'تعذّر تجاوز صفحة تحذير فحص الفيروسات من Google Drive تلقائياً '
                                               '(قد يكون الملف كبيراً جداً أو نوعه يتطلب تأكيداً يدوياً من '
                                               'المتصفح). جرّب: 1) فتح الرابط بالمتصفح والضغط على "تنزيل على '
                                               'أي حال" ثم رفع الملف من جهازك مباشرة، أو 2) استخدام رابط تنزيل '
                                               'مباشر من خدمة أخرى (Dropbox/OneDrive).'}

        # ===== أي رابط آخر (غير Google Drive) يرجع صفحة HTML بدل الملف
        # نفسه غالباً معناه أن الملف يحتاج تسجيل دخول ما قدرنا نكمله تلقائياً
        # (شائع جداً مع روابط OneDrive/SharePoint الخاصة بمؤسسة عند تقييد
        # المشاركة لموظفي المؤسسة فقط، أو الرابط "خاص" مو "عام") - نرجّع
        # خطأ واضح فوراً بدل تنزيل الصفحة كأنها الملف (يفشل لاحقاً بشكل مبهم
        # عند محاولة قراءتها كـExcel/SQLite) أو التعليق بمحاولات إعادة توجيه
        # طويلة =====
        elif 'text/html' in content_type:
            return {'ok': False, 'error': 'الرابط رجّع صفحة ويب (HTML) بدل الملف نفسه - غالباً لأن الملف يحتاج '
                                           'تسجيل دخول (شائع مع روابط OneDrive/SharePoint الخاصة بمؤسسة أو '
                                           'مدرسة/جامعة) أو لأن رابط المشاركة غير مضبوط على "أي شخص لديه '
                                           'الرابط". جرّب: 1) تغيير إعداد مشاركة الملف إلى "أي شخص لديه الرابط"، '
                                           'أو 2) رفع الملف مباشرة من جهازك بدل استخدام رابط.'}

        filename = _filename_from_response(resp)
        total = 0
        with open(tmp_path, 'wb') as out:
            for chunk in resp.iter_content(chunk_size=_CHUNK):
                if not chunk:
                    continue
                total += len(chunk)
                if total > _MAX_BYTES:
                    out.close()
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                    max_mb = _MAX_BYTES // (1024 * 1024)
                    return {'ok': False, 'error': f'الملف بالرابط أكبر من الحد المسموح ({max_mb} ميجابايت) - تأكد '
                                                   'أن الرابط يشير للملف الصحيح، أو تواصل مع مسؤول النظام لرفع '
                                                   'هذا الحد (متغيّر البيئة CLOUD_IMPORT_MAX_MB)'}
                out.write(chunk)
        if os.path.getsize(tmp_path) == 0:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return {'ok': False, 'error': 'الملف الذي تم تنزيله من الرابط فارغ - تأكد من صحة الرابط وأنه متاح '
                                           'للجميع (رابط مشاركة عام)'}
        return {'ok': True, 'path': tmp_path, 'filename': filename}
    except requests.exceptions.RequestException as e:
        return {'ok': False, 'error': f'تعذّر تنزيل الملف من الرابط: {e}'}
