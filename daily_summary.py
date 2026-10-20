"""
الملخص اليومي للإدارة (إشعار على تطبيق Att Dashboard):
• صباحاً: كم حضر من الموظفين، ومن لم يحضر بعد (بلا المجازين/المستثنين/أقسام الدوام المفتوح)، وعدد المتأخرين.
• مساءً: من نسي تسجيل الانصراف اليوم (يُرسل فقط إن وُجد أحد).
الوقت الافتراضي: بعد وقت الحضور بنصف ساعة، وبعد وقت الانصراف بساعة ونصف — ويمكن تحديده من الإعدادات.
"""
from datetime import datetime, timedelta

import db

LATE = ('متأخر', 'تأخير بسيط')


def _plus(hhmm, minutes):
    try:
        return (datetime.strptime(hhmm[:5], '%H:%M') + timedelta(minutes=minutes)).strftime('%H:%M')
    except (ValueError, TypeError):
        return None


def _names(lst, n=6):
    return '، '.join(lst[:n]) + (f' و{len(lst) - n} غيرهم' if len(lst) > n else '')


def _mark(conn, key, value):
    conn.execute("INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def tick(now=None):
    cfg = db.get_all_settings()
    if cfg.get('daily_summary_enabled', '1') != '1':
        return
    now = now or datetime.now()
    today, hm, wd = now.strftime('%Y-%m-%d'), now.strftime('%H:%M'), now.weekday()
    sat_work = cfg.get('sat_time_enabled') == '1'
    if wd == 4 or (wd == 5 and not sat_work):
        return
    att = (cfg.get('sat_attendance_time') if wd == 5 else '') or cfg.get('attendance_time') or '08:00'
    dep = (cfg.get('sat_departure_time') if wd == 5 else '') or cfg.get('departure_time') or '15:00'
    morning = cfg.get('summary_morning_time') or _plus(att, 30)
    evening = cfg.get('summary_evening_time') or _plus(dep, 90)
    do_morning = morning and hm >= morning and cfg.get('summary_morning_sent') != today
    do_evening = evening and hm >= evening and cfg.get('summary_evening_sent') != today
    if not (do_morning or do_evening):
        return
    conn = db.get_db()
    try:
        if conn.execute("SELECT 1 FROM official_holidays WHERE date = ?", (today,)).fetchone():
            _mark(conn, 'summary_morning_sent', today)
            _mark(conn, 'summary_evening_sent', today)
            conn.commit()
            return
        import app as app_module
        import admin_notes
        app_module.run_full_analysis(conn)   # أحدث النتائج قبل الملخص
        conn.commit()
        rc = {r['name']: dict(r) for r in conn.execute("SELECT * FROM report_cache WHERE date = ?", (today,))}
        if do_morning:
            excluded = {d.strip() for d in (cfg.get('excluded_depts') or '').split(',') if d.strip()}
            open_depts = {r['dept'] for r in conn.execute("SELECT dept FROM dept_attendance_settings WHERE open_hours = 1")}
            exc = {r['name'] for r in conn.execute("SELECT name FROM date_exceptions WHERE date = ?", (today,))}
            exc |= {n for (n, d) in __import__('vacations').approved_days(conn) if d == today}
            expected = [r['name'] for r in conn.execute("SELECT name, dept FROM employees WHERE active = 1 ORDER BY dept, name")
                        if (r['dept'] or '') not in excluded and (r['dept'] or '') not in open_depts and r['name'] not in exc]
            present = {n for n, r in rc.items() if r.get('time_in')}
            present |= {r['name'] for r in conn.execute("SELECT DISTINCT name FROM mobile_punches WHERE date = ? AND status = 'accepted'", (today,))}
            absent = [n for n in expected if n not in present]
            late = [n for n, r in rc.items() if r.get('status') in LATE]
            body = f"حضر {len([n for n in expected if n in present])} من {len(expected)}"
            if absent:
                body += f" — لم يحضر بعد {len(absent)}: {_names(absent)}"
            if late:
                body += f" — متأخرون {len(late)}: {_names(late, 4)}"
            if exc:
                body += f" — في إجازة/استثناء: {len(exc)}"
            admin_notes.add_alert(conn, 'summary_morning', 'ملخص الحضور الصباحي', body, '/dashboard#reports', audience='staff')
            _mark(conn, 'summary_morning_sent', today)
        if do_evening:
            missing = sorted(n for n, r in rc.items() if r.get('out_flag'))
            if missing:
                admin_notes.add_alert(conn, 'summary_evening', f'لم يسجّلوا الانصراف اليوم: {len(missing)}',
                                      _names(missing, 8) + ' — يصلهم في التطبيق اقتراح «طلب تصحيح»', '/dashboard#reports', audience='staff')
            _mark(conn, 'summary_evening_sent', today)
        conn.commit()
    finally:
        conn.close()
