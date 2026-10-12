"""
إرسال البريد الإلكتروني - منقول عن نفس منطق النسخة المكتبية
(home.py -> _send_email_with_attachment / _build_bilingual_email_body)،
مع دعم مسارين هنا: SMTP التقليدي (send_email، متوافق مع Microsoft
365/Exchange Online بإعدادات smtp.office365.com:587 + STARTTLS)
و Microsoft Graph API (graph_email_sender.py - بديل حديث بمصادقة تطبيق
Azure AD بدل اسم مستخدم/كلمة مرور). send_email_auto أدناه يختار
الطريقة الفعّالة حسب إعداد "email_method" المحفوظ.

ملاحظة نطاق: النسخة المكتبية تعرض أيضاً سبب كل غياب/تأخير من جداول
"absence_reasons"/"late_reasons" غير الموجودة بقاعدة بيانات هذا النظام
بعد - لذا تُعرض هنا فقط الأسماء والتواريخ (وللمتأخرين: عدد دقائق
التأخير) بدون عمود سبب.
"""
import base64
import mimetypes
import smtplib
from datetime import datetime
from email.message import EmailMessage


def build_bilingual_email_body(rows, report_label_ar, report_label_en, org_name, absence_reasons=None, logo_path=None):
    """
    rows: قائمة قواميس من report_cache (بعد الفلترة) - كل عنصر فيه
          name, dept, date, status, late_minutes
    absence_reasons: {(name, date): reason} اختياري - سبب الغياب لو مسجَّل
        (من جدول absence_reasons) - نفس قاعدة النسخة المكتبية بالضبط:
        لو فيه سبب مسجَّل فعلياً يظهر، ولو ما فيه يظهر الاسم والتاريخ فقط
        بدون أي عبارة إضافية ("بدون سبب مسجل" لا تُذكر أبداً).
    logo_path: مسار ملف شعار المؤسسة (اختياري) - يُضمَّن كصورة base64
        داخل نص HTML مباشرةً (بدون مرفق منفصل) لو الملف موجوداً وقابلاً
        للقراءة، ويُتجاهَل بصمت غير ذلك.
    يُرجع (نص عادي ثنائي اللغة, نص HTML ثنائي اللغة بتلوين المتأخرين بالأحمر)
    """
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    org = org_name or 'نظام تحليل سجلات الحضور والانصراف'
    absence_reasons = absence_reasons or {}

    logo_html = ''
    if logo_path:
        try:
            mime = mimetypes.guess_type(logo_path)[0] or 'image/png'
            with open(logo_path, 'rb') as f:
                b64 = base64.b64encode(f.read()).decode('ascii')
            logo_html = f'<div style="text-align:center;margin-bottom:10px"><img src="data:{mime};base64,{b64}" style="max-height:60px;max-width:220px"></div>'
        except OSError:
            logo_html = ''

    absentees = sorted([r for r in rows if r.get('status') == 'غائب'], key=lambda r: r.get('date') or '')
    # ===== 'متأخر' بالنظام تعني بالفعل "تجاوز فترة السماح" - نفس معنى
    # طلب المستخدم بعدم ذكر من كان تأخيره ضمن فترة السماح ("تأخير بسيط") =====
    lates = sorted([r for r in rows if r.get('status') == 'متأخر'], key=lambda r: r.get('date') or '')

    absentees_ar, absentees_en = [], []
    for r in absentees:
        reason = absence_reasons.get((r['name'], r['date']))
        if reason:
            absentees_ar.append(f"• {r['name']} ({r['date']}) — السبب: {reason}")
            absentees_en.append(f"- {r['name']} ({r['date']}) - Reason:")
            absentees_en.append(f"    {reason}")
        else:
            absentees_ar.append(f"• {r['name']} ({r['date']})")
            absentees_en.append(f"- {r['name']} ({r['date']})")

    late_ar, late_en, late_html = [], [], []
    for r in lates:
        mins = r.get('late_minutes')
        if mins:
            late_ar.append(f"• {r['name']} — {r['date']} — تأخر {int(mins)} دقيقة")
            late_en.append(f"- {r['name']} - {r['date']} - late by {int(mins)} min")
        else:
            late_ar.append(f"• {r['name']} — {r['date']}")
            late_en.append(f"- {r['name']} - {r['date']}")
        late_html.append(
            f'<div style="color:#c0392b">• {r["name"]} — {r["date"]}'
            + (f' — تأخر {int(mins)} دقيقة' if mins else '') + '</div>'
        )

    arabic_part = (
        f"مرفق {report_label_ar} من نظام تحليل سجلات الحضور والانصراف.\n\n"
        f"المؤسسة: {org}\n"
        f"تاريخ الإصدار: {now_str}\n"
    )
    if absentees_ar:
        arabic_part += "\nأسماء الغائبين:\n" + "\n".join(absentees_ar) + "\n"
    if late_ar:
        arabic_part += "\nأسماء المتأخرين (تجاوزوا فترة السماح):\n" + "\n".join(late_ar) + "\n"

    english_part = (
        f"Attached {report_label_en} from the Attendance & Departure Analysis System.\n\n"
        f"Organization: {org}\n"
        f"Issued on: {now_str}\n"
    )
    if absentees_en:
        english_part += "\nAbsent Employees:\n" + "\n".join(absentees_en) + "\n"
    if late_en:
        english_part += "\nLate Employees (beyond grace period):\n" + "\n".join(late_en) + "\n"

    plain_body = arabic_part + "\n" + ("-" * 40) + "\n\n" + english_part

    def _html_absent_line(r):
        reason = absence_reasons.get((r['name'], r['date']))
        if reason:
            return f'<div>• {r["name"]} ({r["date"]}) — السبب: {reason}</div>'
        return f'<div>• {r["name"]} ({r["date"]})</div>'

    html_absent = ''.join(_html_absent_line(r) for r in absentees)
    html_body = f"""
    <div style="font-family:Tajawal,Arial,sans-serif;font-size:14px">
      {logo_html}
      <div dir="rtl" style="text-align:right">
        <p>مرفق {report_label_ar} من نظام تحليل سجلات الحضور والانصراف.</p>
        <p><b>المؤسسة:</b> {org}<br><b>تاريخ الإصدار:</b> {now_str}</p>
        {f'<p><b>أسماء الغائبين:</b></p>{html_absent}' if absentees else ''}
        {f'<p><b>أسماء المتأخرين (تجاوزوا فترة السماح):</b></p>{"".join(late_html)}' if lates else ''}
      </div>
      <hr>
      <div dir="ltr" style="text-align:left">
        <p>Attached {report_label_en} from the Attendance &amp; Departure Analysis System.</p>
        <p><b>Organization:</b> {org}<br><b>Issued on:</b> {now_str}</p>
      </div>
    </div>
    """
    return plain_body, html_body


def send_email(host, port, sender, password, recipients, subject, plain_body,
               html_body=None, attachment_bytes=None, attachment_filename=None, use_tls=True):
    """
    يرسل بريداً عبر SMTP. يرمي استثناء عند أي فشل (اتصال/مصادقة/إرسال) -
    على المستدعي التقاطه وتسجيله بسجل التشغيل، حتى لا تتوقف بقية مهام
    الجدولة بسبب فشل بريد واحد.
    """
    if not (host and sender and password and recipients):
        raise ValueError('إعدادات SMTP غير مكتملة (المضيف/المرسل/كلمة المرور/المستلمون)')

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = ', '.join(recipients)
    msg.set_content(plain_body)
    if html_body:
        msg.add_alternative(html_body, subtype='html')

    if attachment_bytes is not None and attachment_filename:
        msg.add_attachment(attachment_bytes, maintype='application', subtype='pdf', filename=attachment_filename)

    with smtplib.SMTP(host, int(port), timeout=30) as server:
        if use_tls:
            server.starttls()
        server.login(sender, password)
        server.send_message(msg)


def send_email_auto(settings, recipients, subject, plain_body, html_body=None,
                     attachment_bytes=None, attachment_filename=None):
    """
    نقطة استدعاء واحدة تختار طريقة الإرسال الفعّالة حسب إعداد
    email_method المحفوظ (smtp افتراضياً، أو graph) - تستخدمها الجدولة
    التلقائية والتصدير الفوري وزر اختبار البريد معاً، بدل تكرار فرع
    smtp/graph في كل موضع استدعاء على حدة.
    """
    method = (settings.get('email_method') or 'smtp').strip()
    if method == 'graph':
        import graph_email_sender
        graph_email_sender.send_email(
            settings.get('graph_tenant_id'), settings.get('graph_client_id'),
            settings.get('graph_client_secret'), settings.get('graph_sender_upn'),
            recipients, subject, plain_body, html_body, attachment_bytes, attachment_filename,
        )
    else:
        send_email(
            settings.get('smtp_host'), settings.get('smtp_port'), settings.get('smtp_sender_email'),
            settings.get('smtp_sender_password'), recipients, subject, plain_body, html_body,
            attachment_bytes, attachment_filename,
        )
