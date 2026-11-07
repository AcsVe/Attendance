"""خادم تجريبي لفحص المظهر: قاعدة SQLite مؤقتة ببيانات عربية أو إنجليزية، ثم تشغيل التطبيق على منفذ محلي.

python tests/audit_server.py <مسار القاعدة> <ar|en> <المنفذ>
لا يقرأ قاعدة المدرسة ولا إعداداتها؛ كل البيانات هنا مصطنعة للفحص فقط.
"""
import os
import sys
from datetime import date, timedelta

DB, LANG, PORT = sys.argv[1], sys.argv[2], int(sys.argv[3])
for ext in ('', '-wal', '-shm'):
    if os.path.exists(DB + ext):
        os.remove(DB + ext)
os.environ['ATTENDANCE_DB_PATH'] = DB
os.environ.pop('BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
db.init_db()
import app as A  # noqa: E402

AR = LANG == 'ar'
DEPTS = ['الإدارة', 'المعلمون', 'الحراسة'] if AR else ['Administration', 'Teachers', 'Security']
NAMES = (['سامي خالد', 'ليلى أحمد', 'خالد يوسف', 'منى سالم', 'عمر حسن', 'هدى علي'] if AR
         else ['Sami Khaled', 'Laila Ahmad', 'Khaled Yousef', 'Mona Salem', 'Omar Hasan', 'Huda Ali'])
TXT = (lambda a, e: a) if AR else (lambda a, e: e)

conn = db.get_db()
for i, n in enumerate(NAMES):
    conn.execute("INSERT INTO employees (name, dept, device_uid, job_title, phone, email) VALUES (?, ?, ?, ?, ?, ?)",
                 (n, DEPTS[i % 3], str(100 + i), TXT('معلم', 'Teacher'), f'07900000{i}', f'user{i}@school.jo'))
start = date.today() - timedelta(days=20)
for d in range(20):
    day = start + timedelta(days=d)
    if day.weekday() in (4, 5):
        continue
    for i, n in enumerate(NAMES):
        if (d + i) % 7 == 0:
            continue                                   # غياب
        tin = f'0{7 + (d + i) % 3}:{(d * 7 + i * 5) % 60:02d}'
        tout = f'1{4 + (d + i) % 2}:{(d * 3 + i) % 60:02d}'
        conn.execute("INSERT INTO punches (name, date, dept, time_in, time_out) VALUES (?, ?, ?, ?, ?)",
                     (n, day.isoformat(), DEPTS[i % 3], tin, tout))
d0 = (start + timedelta(days=3)).isoformat()
conn.execute("INSERT INTO dept_attendance_settings (dept, attendance_time, departure_time) VALUES (?, '07:30', '14:30')", (DEPTS[1],))
conn.execute("INSERT INTO official_holidays (date, label) VALUES (?, ?)", ((start + timedelta(days=10)).isoformat(), TXT('عيد الاستقلال', 'Independence Day')))
conn.execute("INSERT INTO late_permissions (name, date, minutes, label) VALUES (?, ?, 30, ?)", (NAMES[0], d0, TXT('مراجعة طبية', 'Medical visit')))
conn.execute("INSERT INTO departure_permissions (name, date, departure_time, return_time, reason) VALUES (?, ?, '10:00', '11:00', ?)",
             (NAMES[1], d0, TXT('مهمة رسمية', 'Official errand')))
conn.execute("INSERT INTO manual_time_entries (name, date, time_in, time_out, reason) VALUES (?, ?, '07:30', '14:30', ?)",
             (NAMES[2], d0, TXT('نسيان البصمة', 'Forgot to punch')))
conn.execute("INSERT INTO date_exceptions (name, date, reason) VALUES (?, ?, ?)", (NAMES[3], d0, TXT('دورة تدريبية', 'Training course')))
conn.execute("INSERT INTO absence_reasons (name, date, reason) VALUES (?, ?, ?)", (NAMES[4], d0, TXT('مرض', 'Sick')))
conn.execute("INSERT INTO devices (name, ip, port, location) VALUES (?, '192.168.1.201', 4370, ?)", (TXT('جهاز المدخل', 'Entrance device'), TXT('المدخل الرئيسي', 'Main entrance')))
conn.execute("INSERT INTO shifts (name, start_time, end_time, days) VALUES (?, '14:00', '22:00', '6,0,1,2,3,4')", (TXT('المسائية', 'Evening'),))
conn.execute("INSERT INTO employee_shifts (name, shift_id, date_from, created_by) VALUES (?, 1, ?, 'admin')", (NAMES[5], start.isoformat()))
conn.commit()
A.run_full_analysis(conn)
conn.commit()
conn.close()

from werkzeug.serving import make_server  # noqa: E402
print('ready', flush=True)
make_server('127.0.0.1', PORT, A.app, threaded=True).serve_forever()
