"""
تصدير تقرير الحضور والانصراف بصيغة PDF - مطابق لمحتوى التقارير الأصلية
بالنسخة المكتبية (نفس الأعمدة والترتيب)، مع دعم كامل للعربية RTL عبر
arabic_reshaper + python-bidi وخط Noto Naskh Arabic المضمَّن بالمشروع
(لا يعتمد على أي خط عربي مثبّت على السيرفر).
"""
import io
import os
from datetime import datetime

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph,
                                 Spacer, Image)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader

FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'fonts', 'NotoNaskhArabic-Regular.ttf')
_FONT_REGISTERED = False


def _ensure_font():
    global _FONT_REGISTERED
    if not _FONT_REGISTERED:
        pdfmetrics.registerFont(TTFont('Arabic', FONT_PATH))
        _FONT_REGISTERED = True


import contextvars
# دالة ترجمة اختيارية (الواجهة الإنجليزية): تُضبط لكل طلب من app.py قبل بناء التقرير
TRANSLATE = contextvars.ContextVar('pdf_translate', default=None)


def ar(text):
    """يُعيد تشكيل النص العربي وترتيبه للعرض الصحيح (RTL) داخل PDF."""
    if text is None:
        return ''
    text = str(text)
    if not text:
        return ''
    fn = TRANSLATE.get()
    if fn:
        text = fn(text)
    try:
        reshaped = arabic_reshaper.reshape(text)
        return get_display(reshaped)
    except Exception:
        return text


STATUS_COLORS = {
    'في الوقت': colors.HexColor('#e6f7ee'),
    'تأخير بسيط': colors.HexColor('#fff8e1'),
    'متأخر': colors.HexColor('#fdecea'),
    'غائب': colors.HexColor('#fdecea'),
    'عطلة أسبوعية': colors.HexColor('#eef1f6'),
    'عطلة رسمية': colors.HexColor('#eef1f6'),
    'استثناء': colors.HexColor('#ede7f6'),
    'بدون سجل دخول': colors.HexColor('#fff3e0'),
}


def build_report_pdf(rows, org_name, filters_desc, stats, generated_by, times_desc=None, logo_path=None):
    """
    rows: قائمة قواميس (name, dept, date, time_in, time_out, status, late_minutes, working_hours)
    org_name: اسم الجهة (من الإعدادات)
    filters_desc: نص وصفي مختصر للفلاتر المطبَّقة (قسم/موظف/فترة/نوع تقرير)
    stats: قاموس بالإحصاءات الملخّصة (total, ontime, late, absent, holiday, avg_hours, avg_late)
    generated_by: اسم المستخدم الذي أنشأ التقرير
    times_desc: نص يوضّح وقت الحضور/الانصراف المعتمد على هذا التقرير - وقت
        القسم الخاص لو محدَّد قسم وله وقت مخصَّص، وإلا الوقت العام (وربما
        وقت السبت الخاص لو مفعَّل) - يُعرض بالترويسة حتى يُعرف بالضبط أي
        وقت طُبِّق دون الرجوع لتبويب الإعدادات
    logo_path: مسار ملف شعار المؤسسة (اختياري) - يُعرض بأعلى التقرير لو
        الملف موجوداً وقابلاً للقراءة، ويُتجاهَل بصمت لو تعذّرت قراءته

    يُرجع bytes لملف PDF جاهز.
    """
    _ensure_font()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        rightMargin=15 * mm, leftMargin=15 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
    )

    title_style = ParagraphStyle('title', fontName='Arabic', fontSize=16, alignment=TA_CENTER,
                                  textColor=colors.HexColor('#1a2332'), spaceAfter=4)
    sub_style = ParagraphStyle('sub', fontName='Arabic', fontSize=10, alignment=TA_CENTER,
                                textColor=colors.HexColor('#5a6472'), spaceAfter=2)
    meta_style = ParagraphStyle('meta', fontName='Arabic', fontSize=9, alignment=TA_CENTER,
                                 textColor=colors.HexColor('#8a93a2'))

    story = []
    if logo_path:
        try:
            reader = ImageReader(logo_path)
            iw, ih = reader.getSize()
            max_h = 18 * mm
            scale = max_h / float(ih)
            story.append(Image(logo_path, width=iw * scale, height=max_h, hAlign='CENTER'))
            story.append(Spacer(1, 4))
        except Exception:
            pass  # شعار تالف/غير مقروء - نتجاهله بصمت بدل تعطيل توليد التقرير كله
    story.append(Paragraph(ar(org_name or 'نظام تحليل سجلات الحضور والانصراف'), title_style))
    story.append(Paragraph(ar('تقرير الحضور والانصراف'), sub_style))
    if filters_desc:
        story.append(Paragraph(ar(filters_desc), meta_style))
    if times_desc:
        story.append(Paragraph(ar(times_desc), meta_style))
    story.append(Paragraph(
        ar(f"تاريخ الإصدار: {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  بواسطة: {generated_by or ''}"),
        meta_style
    ))
    story.append(Spacer(1, 8))

    # ===== بطاقات الإحصاء الملخّصة =====
    stat_labels = [
        ('الإجمالي', stats.get('total', 0)),
        ('في الوقت', stats.get('ontime', 0)),
        ('المتأخرون', stats.get('late', 0)),
        ('الغائبون', stats.get('absent', 0)),
        ('عطلة أسبوعية', stats.get('holiday', 0)),
        ('متوسط ساعات العمل', stats.get('avg_hours', 0)),
        ('متوسط التأخير (د)', stats.get('avg_late', 0)),
    ]
    stat_header = [ar(lbl) for lbl, _ in stat_labels]
    stat_values = [str(val) for _, val in stat_labels]
    stat_table = Table([stat_header, stat_values], colWidths=[36 * mm] * len(stat_labels))
    stat_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Arabic'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a2332')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#f4f6f9')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d5dae2')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(stat_table)
    story.append(Spacer(1, 10))

    # ===== جدول السجلات التفصيلي - نفس أعمدة تصدير CSV بالضبط (بما فيها
    # عمود المناوبة - فاضي لغير المناوبين أو عند تعطيل نظام المناوبتين) =====
    headers = ['الاسم', 'القسم', 'التاريخ', 'وقت الحضور', 'وقت الانصراف', 'الحالة', 'دقائق التأخير', 'ساعات العمل', 'المناوبة']
    table_data = [[ar(h) for h in headers]]
    row_bg = []
    for i, r in enumerate(rows):
        table_data.append([
            ar(r.get('name', '')),
            ar(r.get('dept', '') or ''),
            r.get('date', '') or '',
            r.get('time_in', '') or '—',
            r.get('time_out', '') or '—',
            ar(r.get('status', '')),
            str(r.get('late_minutes', 0) or 0),
            str(r.get('working_hours', 0) or 0),
            ar(r.get('shift', '') or '—'),
        ])
        row_bg.append(STATUS_COLORS.get(r.get('status', ''), colors.white))

    col_widths = [36 * mm, 26 * mm, 24 * mm, 22 * mm, 22 * mm, 26 * mm, 22 * mm, 22 * mm, 40 * mm]
    tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ('FONTNAME', (0, 0), (-1, -1), 'Arabic'),
        ('FONTSIZE', (0, 0), (-1, -1), 8.5),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a2332')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#d5dae2')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fafbfc')]),
    ]
    for i, bg in enumerate(row_bg, start=1):
        if bg != colors.white:
            style_cmds.append(('BACKGROUND', (5, i), (5, i), bg))
    tbl.setStyle(TableStyle(style_cmds))
    story.append(tbl)

    if not rows:
        story.append(Spacer(1, 12))
        story.append(Paragraph(ar('لا توجد سجلات مطابقة للفلاتر المحددة'), sub_style))

    doc.build(story)
    return buf.getvalue()
