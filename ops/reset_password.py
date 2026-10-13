"""إعادة تعيين كلمة مرور مستخدم النظام من الكمبيوتر نفسه (عند نسيان كلمة مرور المدير الوحيد).
    python ops/reset_password.py            # يسأل عن اسم المستخدم وكلمة المرور الجديدة
"""
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_env  # noqa: E402

load_env()
import db  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

db.init_db()
conn = db.get_db()
users = conn.execute("SELECT username, role FROM users ORDER BY id").fetchall()
print('\nالمستخدمون:', ', '.join(f"{u['username']} ({u['role']})" for u in users))
name = input('اسم المستخدم: ').strip()
row = conn.execute("SELECT id FROM users WHERE username = ?", (name,)).fetchone()
if not row:
    sys.exit('✖ لا يوجد مستخدم بهذا الاسم')
pw = getpass.getpass('كلمة المرور الجديدة (8 أحرف على الأقل، لا تظهر أثناء الكتابة): ')
if len(pw) < 8 or pw != getpass.getpass('أعد كتابتها: '):
    sys.exit('✖ قصيرة أو غير متطابقة')
conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(pw), row['id']))
conn.execute("INSERT INTO audit_log (username, action_type, target_type, new_value) VALUES ('(الكمبيوتر)', 'password_reset', 'user', ?)", (name,))
conn.commit()
print(f'✓ تم تغيير كلمة مرور «{name}» — ادخل بها الآن')
