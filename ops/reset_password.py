"""إعادة تعيين كلمة مرور مستخدم النظام من الكمبيوتر نفسه (عند نسيان كلمة مرور المدير الوحيد).
    python ops/reset_password.py            # يسأل عن اسم المستخدم وكلمة المرور الجديدة
"""
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_env, t  # noqa: E402

load_env()
import db  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

db.init_db()
conn = db.get_db()
users = conn.execute("SELECT username, role FROM users ORDER BY id").fetchall()
print(t('\nالمستخدمون:', '\nUsers:'), ', '.join(f"{u['username']} ({u['role']})" for u in users))
name = input(t('اسم المستخدم: ', 'User name: ')).strip()
row = conn.execute("SELECT id FROM users WHERE username = ?", (name,)).fetchone()
if not row:
    sys.exit(t('✖ لا يوجد مستخدم بهذا الاسم', '✖ No user with this name'))
pw = getpass.getpass(t('كلمة المرور الجديدة (8 أحرف على الأقل، لا تظهر أثناء الكتابة): ', 'New password (at least 8 characters, hidden while typing): '))
if len(pw) < 8 or pw != getpass.getpass(t('أعد كتابتها: ', 'Type it again: ')):
    sys.exit(t('✖ قصيرة أو غير متطابقة', '✖ Too short or not matching'))
conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(pw), row['id']))
conn.execute("INSERT INTO audit_log (username, action_type, target_type, new_value) VALUES ('(الكمبيوتر)', 'password_reset', 'user', ?)", (name,))
conn.commit()
print(t(f'✓ تم تغيير كلمة مرور «{name}» — ادخل بها الآن', f'✓ Password of "{name}" changed - sign in with it now'))
