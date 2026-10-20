"""
الجدولة التلقائية - مهمة واحدة عامة (سحب اختياري من الأجهزة + تحليل +
إرسال تقرير بالبريد) تعمل داخل عملية Flask نفسها عبر APScheduler، بديلاً
عن اعتماد النسخة المكتبية (home.py) على Windows Task Scheduler الخارجي.

ملاحظة نطاق: هذه نسخة أبسط من نظام "مهام متعددة" بالنسخة المكتبية (كل
مهمة باسمها الخاص وفلاتر قسم/تاريخ مستقلة) - هنا مهمة واحدة عامة بإعدادات
مشتركة (وقت + أيام + فلتر حالة)، وهي الخيار الأسهل للتجربة أولاً.
"""
import json
import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

import db
from app_helpers import STATUS_FILTERS

logger = logging.getLogger('scheduler')

_scheduler = None


def _apply_status_filter(rows, status_filter):
    if status_filter == 'absent':
        return [r for r in rows if r['status'] == 'غائب']
    if status_filter == 'late':
        return [r for r in rows if r['status'] == 'متأخر']
    if status_filter == 'absent_or_late':
        return [r for r in rows if r['status'] in ('غائب', 'متأخر')]
    if status_filter == 'present_all':
        return [r for r in rows if r['status'] in ('في الوقت', 'متأخر', 'تأخير بسيط')]
    if status_filter == 'ontime':
        return [r for r in rows if r['status'] == 'في الوقت']
    if status_filter == 'no_checkin':
        return [r for r in rows if r['status'] == 'بدون سجل دخول']
    if status_filter == 'weekend':
        return [r for r in rows if r['status'] == 'عطلة أسبوعية']
    if status_filter == 'official_holiday':
        return [r for r in rows if r['status'] == 'عطلة رسمية']
    return rows  # 'all'


def run_scheduled_report(manual_trigger=False):
    """
    ينفّذ دورة الجدولة الكاملة مرة واحدة: سحب اختياري من الأجهزة، ثم
    تحليل، ثم فلترة report_cache حسب الإعداد المحفوظ، ثم بناء تقرير PDF
    ونص بريد ثنائي اللغة، ثم إرساله عبر SMTP. يُسجّل نتيجة التشغيل
    (نجاح/فشل + رسالة) بإعدادات "آخر تشغيل" دائماً - سواء استُدعيت من
    الجدولة التلقائية أو من زر "تشغيل الآن" اليدوي بالواجهة.

    يُرجع dict: {ok, message} - لا يرمي استثناء أبداً (يُسجَّل أي خطأ
    كفشل بدل إيقاف بقية النظام أو عملية الجدولة الخلفية).
    """
    # الاستيراد هنا (لا بأعلى الملف) لتفادي أي حلقة استيراد مع app.py،
    # الذي يستورد هذا الملف بدوره لتشغيل المجدول عند بدء التطبيق.
    import app as app_module
    from pdf_export import build_report_pdf
    import email_sender

    conn = db.get_db()
    settings = db.get_all_settings()
    try:
        pull_summary = ''
        if settings.get('schedule_pull_before') == '1':
            pull_result = app_module.pull_from_devices(conn)
            if pull_result.get('ok'):
                pull_summary = f"سحب {pull_result.get('imported', 0)} سجل من الأجهزة قبل التحليل. "
            else:
                pull_summary = f"تعذّر السحب من الأجهزة ({pull_result.get('error', '')}) - جرت المتابعة بالبيانات الموجودة. "

        has_punches = conn.execute("SELECT 1 FROM punches LIMIT 1").fetchone() is not None
        has_forced = conn.execute("SELECT 1 FROM forced_absences LIMIT 1").fetchone() is not None
        if not has_punches and not has_forced:
            _record_run(conn, False, pull_summary + 'لا توجد بيانات مرفوعة/مسحوبة للتحليل بعد')
            return {'ok': False, 'message': pull_summary + 'لا توجد بيانات مرفوعة/مسحوبة للتحليل بعد'}

        app_module.run_full_analysis(conn)

        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM report_cache ORDER BY date DESC, time_in ASC").fetchall()]
        filtered = _apply_status_filter(rows, settings.get('schedule_status_filter', 'absent_or_late'))

        if not filtered:
            msg = pull_summary + 'لا توجد أي سجلات تطابق فلتر الحالة المحدَّد للجدولة - لم يُرسَل بريد'
            _record_run(conn, True, msg)
            return {'ok': True, 'message': msg}

        recipients = [r.strip() for r in (settings.get('smtp_recipients') or '').replace(';', ',').split(',') if r.strip()]
        if not recipients:
            msg = pull_summary + 'لا يوجد مستلمون محدَّدون بإعدادات البريد - لم يُرسَل شيء'
            _record_run(conn, False, msg)
            return {'ok': False, 'message': msg}

        status_label = STATUS_FILTERS.get(settings.get('schedule_status_filter', 'absent_or_late'), 'الكل')
        stats = {
            'total': len(filtered),
            'ontime': sum(1 for r in filtered if r['status'] == 'في الوقت'),
            'late': sum(1 for r in filtered if r['status'] in ('متأخر', 'تأخير بسيط')),
            'absent': sum(1 for r in filtered if r['status'] == 'غائب'),
            'holiday': sum(1 for r in filtered if r['status'] == 'عطلة أسبوعية'),
            'avg_hours': 0, 'avg_late': 0,
        }
        org_name = settings.get('org_name')
        logo_path = app_module.get_logo_path(settings)
        pdf_bytes = build_report_pdf(filtered, org_name, f"تقرير مجدول تلقائي - {status_label}", stats,
                                       'الجدولة التلقائية', None, logo_path)

        reason_rows = conn.execute("SELECT name, date, reason FROM absence_reasons").fetchall()
        absence_reasons = {(r['name'], r['date']): r['reason'] for r in reason_rows}
        plain_body, html_body = email_sender.build_bilingual_email_body(
            filtered, 'تقرير مجدول تلقائي', 'an automatically scheduled report', org_name, absence_reasons, logo_path)
        subject = f"{org_name} - تقرير مجدول تلقائي - {datetime.now().strftime('%Y-%m-%d')}"
        filename = f"scheduled_report_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"

        email_sender.send_email_auto(settings, recipients, subject, plain_body, html_body, pdf_bytes, filename)
        msg = pull_summary + f"تم إرسال التقرير المجدول بنجاح إلى: {', '.join(recipients)} ({len(filtered)} سجل)"
        _record_run(conn, True, msg)
        return {'ok': True, 'message': msg}

    except Exception as e:
        logger.exception('فشل تشغيل الجدولة التلقائية')
        _record_run(conn, False, f'خطأ أثناء تنفيذ الجدولة: {e}')
        return {'ok': False, 'message': f'خطأ أثناء تنفيذ الجدولة: {e}'}
    finally:
        conn.close()


def _record_run(conn, success, message):
    now = datetime.now()
    conn.execute("INSERT INTO app_settings (key, value) VALUES ('schedule_last_run_at', ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (now.strftime('%Y-%m-%d %H:%M'),))
    conn.execute("INSERT INTO app_settings (key, value) VALUES ('schedule_last_run_status', ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value", ('success' if success else 'error',))
    conn.execute("INSERT INTO app_settings (key, value) VALUES ('schedule_last_run_message', ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (message,))
    conn.execute("INSERT INTO app_settings (key, value) VALUES ('schedule_last_run_date', ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (now.strftime('%Y-%m-%d'),))
    conn.commit()


_last_hourly = ''


def _tick():
    """يُستدعى كل دقيقة من المجدول الخلفي - يتحقق هل حان وقت التشغيل
    المحدَّد بالإعدادات، وهل لم تُنفَّذ الجدولة اليوم مسبقاً بعد."""
    # مراقبة الحضور أثناء الدوام: رصد الهواتف المنقطعة والفحوص الفائتة (مستقل عن التقرير المجدول)
    try:
        import mobile
        mobile.presence_sweep()
        mobile.leave_sweep()
    except Exception:   # noqa: BLE001 — لا يعطّل بقية المهام
        logger.exception('presence sweep failed')
    try:
        import adms
        adms.flush()      # تحليل ما وصل من الأجهزة عبر الإنترنت ولم يُحلَّل بعد
    except Exception:   # noqa: BLE001
        logger.exception('adms flush failed')
    # إعادة تحليل كل ساعة (الدقيقة 5): يُظهر «بدون سجل انصراف» / الإغلاق التلقائي بعد انتهاء دوام اليوم
    # دون انتظار حركة جديدة
    try:
        global _last_hourly
        h = datetime.now().strftime('%Y-%m-%d %H')
        if datetime.now().minute >= 5 and _last_hourly != h:
            _last_hourly = h
            import mobile
            mobile.schedule_analysis(1)
    except Exception:   # noqa: BLE001
        logger.exception('hourly analysis failed')
    settings = db.get_all_settings()
    if settings.get('schedule_enabled') != '1':
        return
    now = datetime.now()
    target_time = settings.get('schedule_time', '07:00')
    if now.strftime('%H:%M') != target_time:
        return
    if settings.get('schedule_last_run_date') == now.strftime('%Y-%m-%d'):
        return  # اشتغلت اليوم فعلاً - لا نكررها لبقية الدقيقة
    days_json = settings.get('schedule_days_json', '[]')
    try:
        days = json.loads(days_json) if days_json else []
    except (TypeError, ValueError):
        days = []
    if days and now.weekday() not in days:
        return
    logger.info('تشغيل الجدولة التلقائية المجدولة الآن')
    run_scheduled_report(manual_trigger=False)


def start_scheduler():
    """يبدأ المجدول الخلفي مرة واحدة فقط لكل عملية - يُستدعى من app.py
    عند بدء التطبيق (محمي من التكرار بسبب Flask debug reloader)."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(_tick, 'interval', minutes=1, id='schedule_tick', replace_existing=True)
    _scheduler.start()
    logger.info('بدأ المجدول الخلفي للجدولة التلقائية (فحص كل دقيقة)')
    return _scheduler
