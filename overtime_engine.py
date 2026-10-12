"""
محرك حساب العمل الإضافي - منقول بأمانة عن نفس قواعد النسخة المكتبية
(home.py -> _calc_ot_records): يقارن وقت الانصراف الفعلي بوقت الانصراف
المقرر (وقت القسم/العام، أو وقت نهاية المناوبة لمن هم على نظام
المناوبتين، أو ساعات مخصّصة يحددها المستخدم لهذا الحساب فقط)، ويحتسب
العمل الإضافي فقط إذا تجاوز الفرق حد "فترة السماح" (grace period) -
فترة السماح حد فاصل (threshold) فقط، ولا تُخصم من عدد دقائق العمل
الإضافي النهائي.
"""
import pandas as pd

from attendance_engine import parse_time_str, parse_time_val, to_minutes, is_weekend_date


def calculate(rows, settings, dept_times, shift1_names, shift2_names,
              grace_minutes=0, use_custom_hours=False, custom_end=None):
    """
    rows: قائمة قواميس من report_cache (بعد فلترة الاسم/التاريخ سلفاً) -
          كل عنصر فيه name, dept, date, time_out, shift
    settings: من db.get_all_settings()
    dept_times: {dept: (attendance_time_parsed_or_None, departure_time_parsed_or_None)}
    shift1_names / shift2_names: قوائم أسماء المناوبين
    grace_minutes: فترة السماح بالدقائق - أي فرق أقل أو يساوي هذا الحد لا
        يُحتسب عملاً إضافياً إطلاقاً
    use_custom_hours: لو True، يُستخدم custom_end كوقت انصراف مقرر موحّد
        لكل الصفوف (يتجاوز وقت القسم/المناوبة)
    custom_end: نص وقت HH:MM (مطلوب لو use_custom_hours=True)

    يُرجع قائمة قواميس: name, dept, date, time_out, scheduled_end,
    ot_minutes, is_weekend - فقط للصفوف التي لها عمل إضافي فعلي (> 0)
    """
    shift1_names = set(shift1_names or [])
    shift2_names = set(shift2_names or [])

    default_end = parse_time_str(settings.get('departure_time', '15:00'))
    shift1_end = parse_time_str(settings.get('shift1_end')) if settings.get('shift1_end') else None
    shift2_end = parse_time_str(settings.get('shift2_end')) if settings.get('shift2_end') else None
    custom_end_t = parse_time_str(custom_end) if (use_custom_hours and custom_end) else None

    records = []
    for row in rows:
        time_out_str = row.get('time_out')
        checkout = parse_time_val(time_out_str)
        if checkout is None:
            continue

        name = row.get('name')
        dept = row.get('dept')

        if use_custom_hours and custom_end_t is not None:
            scheduled_end = custom_end_t
        elif name in shift2_names and shift2_end is not None:
            scheduled_end = shift2_end
        elif name in shift1_names and shift1_end is not None:
            scheduled_end = shift1_end
        else:
            dep_override = dept_times.get(dept, (None, None))[1]
            scheduled_end = dep_override or default_end

        if scheduled_end is None:
            continue

        raw_diff = to_minutes(checkout) - to_minutes(scheduled_end)
        ot_minutes = raw_diff if raw_diff > grace_minutes else 0
        if ot_minutes <= 0:
            continue

        date_val = pd.to_datetime(row.get('date'), errors='coerce')
        records.append({
            'name': name,
            'dept': dept or '',
            'date': row.get('date'),
            'time_out': time_out_str,
            'scheduled_end': scheduled_end.strftime('%H:%M'),
            'ot_minutes': int(ot_minutes),
            'is_weekend': bool(is_weekend_date(date_val)) if pd.notna(date_val) else False,
        })

    return records


def format_duration(total_minutes):
    """يحوّل عدد الدقائق إلى نص مقروء مثل '2h 15m' أو '45m'."""
    total_minutes = int(round(total_minutes))
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"
