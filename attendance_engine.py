"""
محرك حساب الحضور/الانصراف - منقول بأمانة عن نفس قواعد النسخة المكتبية
(home.py): أولوية الاستثناء الشخصي > العطلة الرسمية > العطلة الأسبوعية
(جمعة/سبت) > الغياب العادي > بدون سجل دخول > مقارنة دقائق التأخير.
يدعم أيضاً: مناوبتين مستقلتين، وقت حضور/انصراف خاص بالقسم، ووقت إضافي
خاص بيوم السبت تحديداً (يتفوّق على وقت القسم/العام فقط لمن حضر فعلياً
يوم السبت - الغياب يوم السبت يبقى "عطلة أسبوعية" دائماً).
"""
from datetime import datetime
import pandas as pd


def parse_time_str(s):
    """يحوّل نص وقت HH:MM إلى datetime.time - يرمي ValueError لو غير صالح."""
    if not s:
        return None
    s = str(s).strip()
    for fmt in ('%H:%M', '%H:%M:%S'):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"صيغة وقت غير صحيحة: {s}")


def parse_time_val(v):
    """يحوّل قيمة وقت (نص أو datetime أو NaN) لكائن time، أو None لو فاضية/غير صالحة."""
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    s = str(v).strip()
    if not s or s.lower() == 'nan':
        return None
    try:
        return parse_time_str(s)
    except ValueError:
        try:
            return pd.to_datetime(s).time()
        except Exception:
            return None


def to_minutes(t):
    if t is None:
        return 0
    return t.hour * 60 + t.minute


def is_weekend_date(d):
    """الجمعة (4) أو السبت (5) - عطلة أسبوعية بالتقويم الأسبوعي المحلي."""
    if d is None or pd.isna(d):
        return False
    try:
        return d.weekday() in (4, 5)
    except (AttributeError, ValueError):
        return False


def is_saturday(d):
    if d is None or pd.isna(d):
        return False
    try:
        return d.weekday() == 5
    except (AttributeError, ValueError):
        return False


def compute_status(is_absent, is_tin_na, is_tout_na, late_minutes, late_threshold,
                    is_weekend, is_official_holiday=False, is_date_exception=False):
    if is_date_exception:
        return 'استثناء'
    if is_absent or (is_tin_na and is_tout_na):
        if is_official_holiday:
            return 'عطلة رسمية'
        return 'عطلة أسبوعية' if is_weekend else 'غائب'
    if is_tin_na:
        return 'بدون سجل دخول'
    if late_minutes > late_threshold:
        return 'متأخر'
    if late_minutes > 0:
        return 'تأخير بسيط'
    return 'في الوقت'


def _valid_time(t):
    return t is not None and not (isinstance(t, float) and pd.isna(t)) and not pd.isna(t)


def merge_same_day(df):
    """سجل واحد لكل موظف في كل يوم: إذا جاءت حركات اليوم من أكثر من مصدر (جهاز البصمة + تطبيق الهاتف،
    أو سُحب الجهاز مرتين) يُؤخذ أبكر حضور وآخر انصراف — فإذا نسي الموظف هاتفه تكمّل بصمة الجهاز يومه والعكس."""
    if df.empty:
        return df
    key = df['name'].astype(str) + '|' + df['date_parsed'].dt.strftime('%Y-%m-%d').fillna('')
    if not key.duplicated().any():
        return df
    df = df.assign(_k=key)
    keep = []
    for _k, g in df.groupby('_k', sort=False):
        first = g.index[0]
        if len(g) > 1:
            ins = [t for t in g['time_in_parsed'] if _valid_time(t)]
            outs = [t for t in list(g['time_out_parsed']) + list(g['time_in_parsed']) if _valid_time(t)]
            df.at[first, 'time_in_parsed'] = min(ins) if ins else None
            df.at[first, 'time_out_parsed'] = max(outs) if outs else None
            if not str(df.at[first, 'dept'] or '').strip():
                depts = [d for d in g['dept'] if str(d or '').strip()]
                if depts:
                    df.at[first, 'dept'] = depts[0]
        keep.append(first)
    return df.loc[keep].drop(columns=['_k']).reset_index(drop=True)


OUT_COLS = ['name', 'dept', 'date', 'weekday', 'time_in', 'time_out', 'status', 'late_minutes',
            'working_hours', 'shift', 'early_minutes', 'out_flag', 'break_minutes']


def analyze(punches_df, settings, dept_times, manual_entries, date_exceptions,
            official_holidays, shift1_names=None, shift2_names=None,
            late_permissions=None, departure_permissions=None, device_breaks=None):
    """
    punches_df: أعمدة name, date (نص YYYY-MM-DD), dept, time_in, time_out
    settings: قاموس من db.get_all_settings()
    dept_times: {dept: (attendance_time_str, departure_time_str)}
    manual_entries: {(name, date_str): (time_in, time_out)}
    date_exceptions: set of (name, date_str)
    official_holidays: set of date_str
    shift1_names / shift2_names: قوائم أسماء المناوبين (اختياري)
    late_permissions: {(name, date_str): {'minutes': int, 'custom_attendance_time': str|None}}
        - custom_attendance_time (لو موجود): يُعاد حساب التأخير بالكامل بمقارنة
          وقت الحضور الفعلي بهذا الوقت بدل الوقت الافتراضي/وقت القسم/وقت السبت.
        - minutes (لو مافي custom_attendance_time أو بالإضافة له): تُخصم من
          دقائق التأخير الخام (لا تقل عن صفر).
        - يُطبَّق بعد الحساب الأولي للتأخير وقبل تحديد الحالة، لذا قد يُعيد
          الحالة من "متأخر" إلى "في الوقت".
    device_breaks: {(name, date_str): [('HH:MM:SS', 'HH:MM:SS'), ...]} — خروج/عودة من البصمات الوسطى في جهاز البصمة
        (أول بصمة = حضور، آخر بصمة = انصراف، وما بينهما أزواج خروج ← عودة). تُخصم من ساعات العمل
        مع إذن المغادرة دون تكرار الفترات المتداخلة، ومجموعها في break_minutes.
    departure_permissions: {(name, date_str): {'departure_time': str, 'return_time': str}}
        - تخصم مدة المغادرة المؤقتة من ساعات العمل المحسوبة فقط، بدون أي
          تأثير على التأخير أو تصنيف الحالة.

    يُرجع DataFrame فيه: name, dept, date, weekday, time_in, time_out,
    status, late_minutes, working_hours, shift, early_minutes, out_flag

    نسيان الانصراف (حضور بلا انصراف بعد انتهاء الدوام):
      out_flag = 'missing' ← «بدون سجل انصراف» (الحالة لا تتغيّر حتى لا تضيع معلومة التأخير)
      out_flag = 'auto'    ← أُغلق تلقائياً بوقت نهاية الدوام (إن فُعّل auto_checkout) — يُراجَع
    المغادرة المبكرة: early_minutes = نهاية الدوام المقررة − الانصراف الفعلي (بعد خصم إذن المغادرة
      المتداخل معها)، وتُحتسب فقط إن تجاوزت حد التأخير وفي أيام العمل.
    """
    df = punches_df.copy()
    if df.empty:
        return pd.DataFrame(columns=OUT_COLS)

    shift1_names = set(shift1_names or [])
    shift2_names = set(shift2_names or [])
    shift_enabled = settings.get('shift_enabled', '0') == '1'
    late_permissions = late_permissions or {}
    departure_permissions = departure_permissions or {}
    device_breaks = device_breaks or {}

    att_time = parse_time_str(settings.get('attendance_time', '09:00'))
    dep_time = parse_time_str(settings.get('departure_time', '15:00'))
    late_th = int(settings.get('late_threshold', '5') or 5)
    shift1_start = parse_time_str(settings.get('shift1_start', '08:30'))
    shift2_start = parse_time_str(settings.get('shift2_start', '15:00'))

    sat_enabled = settings.get('sat_time_enabled', '0') == '1'
    sat_att_time = parse_time_str(settings.get('sat_attendance_time', '')) if (sat_enabled and settings.get('sat_attendance_time')) else None
    sat_dep_time = parse_time_str(settings.get('sat_departure_time', '')) if (sat_enabled and settings.get('sat_departure_time')) else None

    excluded_depts = {d.strip() for d in settings.get('excluded_depts', '').split(',') if d.strip()}
    open_depts = set(settings.get('_open_depts') or [])   # أقسام بدوام مفتوح (بلا وقت حضور): لا يُحتسب تأخير
    auto_checkout = settings.get('auto_checkout', '0') == '1'
    shift1_end = parse_time_str(settings.get('shift1_end')) if settings.get('shift1_end') else None
    shift2_end = parse_time_str(settings.get('shift2_end')) if settings.get('shift2_end') else None
    # «الآن» (بتوقيت النظام) لمعرفة هل انتهى دوام اليوم — اليوم الجاري لا يُعدّ نسياناً قبل نهاية الدوام
    _now = settings.get('_now') or datetime.now().strftime('%Y-%m-%d %H:%M')
    today_s, now_min = _now[:10], to_minutes(parse_time_str(_now[11:16]))
    AFTER_END_MIN = 60   # مهلة بعد نهاية الدوام (للعمل الإضافي) قبل اعتبار الانصراف منسياً

    df['date_parsed'] = pd.to_datetime(df['date'], errors='coerce')
    df['time_in_parsed'] = df['time_in'].apply(parse_time_val)
    df['time_out_parsed'] = df['time_out'].apply(parse_time_val)

    if excluded_depts:
        df = df[~df['dept'].isin(excluded_depts)].reset_index(drop=True)
    if df.empty:
        return pd.DataFrame(columns=OUT_COLS)

    df = merge_same_day(df)

    df['is_shift'] = df['name'].isin(shift1_names | shift2_names) if shift_enabled else False
    df['shift_number'] = df['name'].apply(lambda n: 2 if n in shift2_names else 1)

    # ===== الإدخال اليدوي - أعلى أولوية، يكتب فوق أي بصمة فعلية لنفس
    # (الاسم، التاريخ) =====
    for idx, row in df.iterrows():
        date_str = row['date_parsed'].strftime('%Y-%m-%d') if pd.notna(row['date_parsed']) else None
        key = (row['name'], date_str)
        if key in manual_entries:
            m_in, m_out = manual_entries[key]
            row_date = row['date_parsed']
            if pd.isna(row_date):
                continue
            if m_in:
                t_in = parse_time_val(m_in)
                if t_in:
                    df.at[idx, 'time_in_parsed'] = pd.Timestamp.combine(row_date.date(), t_in)
            if m_out:
                t_out = parse_time_val(m_out)
                if t_out:
                    df.at[idx, 'time_out_parsed'] = pd.Timestamp.combine(row_date.date(), t_out)

    def get_window(row):
        dept = row.get('dept')
        row_date = row.get('date_parsed')
        sat = pd.notna(row_date) and is_saturday(row_date)
        if sat and sat_att_time is not None:
            start = sat_att_time
        else:
            start = dept_times.get(dept, (None, None))[0] or att_time
        if sat and sat_dep_time is not None:
            end = sat_dep_time
        else:
            end = dept_times.get(dept, (None, None))[1] or dep_time
        return start, end

    def row_date_str(row):
        row_date = row.get('date_parsed')
        return row_date.strftime('%Y-%m-%d') if pd.notna(row_date) else None

    def calc_late(row):
        t = row.get('time_in_parsed')
        if t is None or pd.isna(t) or row.get('dept') in open_depts:
            return 0
        perm = late_permissions.get((row['name'], row_date_str(row)))
        custom_att = perm.get('custom_attendance_time') if perm else None
        if custom_att:
            base = parse_time_str(custom_att)
        elif row.get('is_shift'):
            base = shift2_start if row.get('shift_number') == 2 and shift2_start else shift1_start
        else:
            start, _ = get_window(row)
            base = start
        raw = max(0, to_minutes(t) - to_minutes(base))
        if perm and perm.get('minutes'):
            try:
                raw = max(0, raw - int(perm['minutes']))
            except (TypeError, ValueError):
                pass
        return raw

    def _absences(row, start, end):
        """فترات الغياب داخل اليوم (إذن مغادرة + خروج من جهاز البصمة) بالدقائق على محور [الحضور، الانصراف]"""
        perm_iv, brk_iv = [], []

        def add(lst, a, b):
            try:
                p1, p2 = to_minutes(parse_time_str(str(a)[:8])), to_minutes(parse_time_str(str(b)[:8]))
            except (ValueError, TypeError, AttributeError):
                return
            if p2 < p1:
                p2 += 24 * 60
            if end > 24 * 60 and p1 < start:   # دوام يمتد بعد منتصف الليل وفترة بعده
                p1, p2 = p1 + 24 * 60, p2 + 24 * 60
            # الجزء الواقع بين الحضور والانصراف فقط: إذن في أول الدوام أو آخره لم يكن ضمن المدة المحسوبة أصلاً
            a2, b2 = max(p1, start), min(p2, end)
            if b2 > a2:
                lst.append((a2, b2))
        perm = departure_permissions.get((row['name'], row_date_str(row)))
        if perm and perm.get('departure_time') and perm.get('return_time'):
            add(perm_iv, perm['departure_time'], perm['return_time'])
        for a, b in device_breaks.get((row['name'], row_date_str(row)), []):
            add(brk_iv, a, b)
        return perm_iv, brk_iv

    def _union_len(ivs):
        total, cur_a, cur_b = 0, None, None
        for a, b in sorted(ivs):
            if cur_b is None or a > cur_b:
                if cur_b is not None:
                    total += cur_b - cur_a
                cur_a, cur_b = a, b
            else:
                cur_b = max(cur_b, b)
        return total + ((cur_b - cur_a) if cur_b is not None else 0)

    def _span(row):
        tin, tout = row.get('time_in_parsed'), row.get('time_out_parsed')
        if tin is None or tout is None or pd.isna(tin) or pd.isna(tout):
            return None
        start, end = to_minutes(tin), to_minutes(tout)
        if end < start:
            end += 24 * 60
        return start, end

    def calc_hours(row):
        sp = _span(row)
        if not sp:
            return 0.0
        start, end = sp
        perm_iv, brk_iv = _absences(row, start, end)
        deduct = _union_len(perm_iv + brk_iv)   # فترة يغطيها الإذن والبصمة معاً تُخصم مرة واحدة
        return round(max(0.0, (end - start - deduct) / 60), 2)

    def calc_breaks(row):
        sp = _span(row)
        if not sp:
            return 0
        return int(_union_len(_absences(row, *sp)[1]))

    def sched_end(row):
        """وقت نهاية الدوام المقرر لهذا الصف (None لأقسام الدوام المفتوح)"""
        if row.get('dept') in open_depts:
            return None
        perm = late_permissions.get((row['name'], row_date_str(row)))
        if perm and perm.get('custom_departure_time'):
            try:
                return parse_time_str(perm['custom_departure_time'])
            except ValueError:
                pass
        if row.get('is_shift'):
            return (shift2_end if row.get('shift_number') == 2 else shift1_end) or get_window(row)[1]
        return get_window(row)[1]

    def is_work_day(row):
        d = row_date_str(row)
        if d is None or d in official_holidays or (row['name'], d) in date_exceptions:
            return False
        wd = row['date_parsed'].weekday()
        return wd != 4 and not (wd == 5 and not sat_enabled)

    # ===== نسيان الانصراف: حضور بلا انصراف (أو انصراف = الحضور نفسه من بصمة واحدة/حضور الهاتف) =====
    df['out_flag'] = ''
    for idx, row in df.iterrows():
        tin, tout = row.get('time_in_parsed'), row.get('time_out_parsed')
        if not _valid_time(tin):
            continue
        tin_t = tin.time() if hasattr(tin, 'time') and callable(tin.time) else tin
        tout_t = (tout.time() if hasattr(tout, 'time') and callable(tout.time) else tout) if _valid_time(tout) else None
        if tout_t is not None and to_minutes(tout_t) != to_minutes(tin_t):
            continue
        d = row_date_str(row)
        end = sched_end(row)
        if d is None:
            continue
        ended = d < today_s or (d == today_s and end is not None and now_min >= to_minutes(end) + AFTER_END_MIN)
        if not ended:
            continue   # اليوم الجاري ولم ينتهِ الدوام بعد: الموظف ما زال في عمله
        if auto_checkout and end is not None and to_minutes(end) > to_minutes(tin_t):
            df.at[idx, 'time_out_parsed'] = end
            df.at[idx, 'out_flag'] = 'auto'
        else:
            df.at[idx, 'time_out_parsed'] = None
            df.at[idx, 'out_flag'] = 'missing'

    def calc_early(row):
        if row.get('out_flag') or not is_work_day(row):
            return 0
        tin, tout = row.get('time_in_parsed'), row.get('time_out_parsed')
        if not _valid_time(tin) or not _valid_time(tout):
            return 0
        end = sched_end(row)
        if end is None:
            return 0
        o, e, i = to_minutes(tout), to_minutes(end), to_minutes(tin)
        if o <= i or o >= e:      # لا انصراف فعلي بعد (= وقت الحضور)، أو انصراف بعد منتصف الليل/بعد نهاية الدوام
            return 0
        if row_date_str(row) == today_s and now_min < e:
            return 0              # اليوم الجاري قبل نهاية الدوام: قد يكون خروجاً لم يكتمل يومه بعد
        early = e - o
        perm = departure_permissions.get((row['name'], row_date_str(row)))
        if perm:                  # إذن مغادرة يغطي جزءاً من الفترة [الانصراف، نهاية الدوام]
            try:
                p1, p2 = to_minutes(parse_time_str(perm.get('departure_time'))), to_minutes(parse_time_str(perm.get('return_time')))
                early -= max(0, min(p2, e) - max(p1, o))
            except (ValueError, TypeError, AttributeError):
                pass
        return early if early > late_th else 0

    df['late_minutes'] = df.apply(calc_late, axis=1)
    df['working_hours'] = df.apply(calc_hours, axis=1)
    df['early_minutes'] = df.apply(calc_early, axis=1)
    df['break_minutes'] = df.apply(calc_breaks, axis=1)

    def get_status(row):
        tin, tout = row.get('time_in_parsed'), row.get('time_out_parsed')
        is_tin_na = tin is None or pd.isna(tin)
        is_tout_na = tout is None or pd.isna(tout)
        is_absent = is_tin_na and is_tout_na
        date_str = row['date_parsed'].strftime('%Y-%m-%d') if pd.notna(row['date_parsed']) else None
        is_exc = (row['name'], date_str) in date_exceptions
        is_holiday = date_str in official_holidays
        is_weekend = is_weekend_date(row['date_parsed'])
        return compute_status(is_absent, is_tin_na, is_tout_na, row['late_minutes'], late_th,
                               is_weekend, is_holiday, is_exc)

    df['status'] = df.apply(get_status, axis=1)
    df['weekday'] = df['date_parsed'].dt.weekday

    # ===== عمود فترة المناوبة - نص وصفي يوضّح للمستخدم أي مناوبة (وأي
    # فترة زمنية) طُبِّقت على هذا الصف بالتحديد؛ فاضي لغير المناوبين أو
    # عند تعطيل نظام المناوبتين بالكامل =====
    shift1_start_s = settings.get('shift1_start', '') or ''
    shift1_end_s = settings.get('shift1_end', '') or ''
    shift2_start_s = settings.get('shift2_start', '') or ''
    shift2_end_s = settings.get('shift2_end', '') or ''

    def get_shift_label(row):
        if not shift_enabled or not row.get('is_shift'):
            return ''
        if row.get('shift_number') == 2:
            return f"المناوبة الثانية ({shift2_start_s}–{shift2_end_s})"
        return f"المناوبة الأولى ({shift1_start_s}–{shift1_end_s})"

    df['shift'] = df.apply(get_shift_label, axis=1)

    def fmt_time(t):
        return t.strftime('%H:%M') if (t is not None and not pd.isna(t)) else ''

    df['time_in'] = df['time_in_parsed'].apply(fmt_time)
    df['time_out'] = df['time_out_parsed'].apply(fmt_time)
    df['date'] = df['date_parsed'].dt.strftime('%Y-%m-%d')

    return df[OUT_COLS]
