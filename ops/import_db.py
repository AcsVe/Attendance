"""نقل قاعدة بيانات موجودة (attendance_web.db من النسخة القديمة على الكمبيوتر أو الهاتف) إلى هذا النظام.

    python ops/import_db.py                 # يسأل عن مسار الملف
    python ops/import_db.py PATH --yes

• يفحص الملف أولاً (سليم وفيه جداول النظام)، ويحفظ نسخة أمان من القاعدة الحالية في data/before-import-<وقت>.db
"""
import os
import shutil
import sqlite3
import sys
from contextlib import closing

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import BASE, data_dir, db_path, die, load_env, stamp, t  # noqa: E402


def main():
    load_env()
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    src = args[0] if args else input(t('  مسار ملف attendance_web.db القديم (اسحب الملف إلى هذه النافذة): ', '  Path of the old attendance_web.db file (drag the file into this window): ')).strip().strip('"')
    if not src:
        die(t('تم الإلغاء', 'Cancelled'))
    if not os.path.isfile(src):
        die(t(f'الملف غير موجود: {src}', f'File not found: {src}'))
    try:
        with closing(sqlite3.connect(f'file:{src}?mode=ro', uri=True)) as c:
            ok = c.execute('PRAGMA integrity_check').fetchone()[0]
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.DatabaseError as e:
        die(t(f'ليس ملف قاعدة بيانات صالحاً: {e}', f'Not a valid database file: {e}'))
    if ok != 'ok' or not {'users', 'employees'} <= tables:
        die(t('الملف تالف أو ليس قاعدة نظام الحضور (لا توجد جداول users/employees)', 'The file is damaged or is not an attendance database (no users/employees tables)'))
    dst = db_path()
    if os.path.abspath(src) == os.path.abspath(dst):
        die(t('هذا هو ملف النظام نفسه', 'This is the system\'s own database file'))
    if '--yes' not in sys.argv and input(t('  ستُستبدل بيانات هذا النظام بالملف المختار. اكتب YES: ', '  The data of this system will be replaced by the chosen file. Type YES: ')).strip() != 'YES':
        die(t('تم الإلغاء', 'Cancelled'))
    os.makedirs(data_dir(), exist_ok=True)
    if os.path.isfile(dst):
        safe = os.path.join(data_dir(), f'before-import-{stamp()}.db')
        with closing(sqlite3.connect(dst, timeout=60)) as s, closing(sqlite3.connect(safe)) as d:
            s.backup(d)
        print(t(f'  ✓ نسخة أمان من البيانات الحالية: {safe}', f'  ✓ Safety copy of the current data: {safe}'))
    tmp = dst + '.import'
    with closing(sqlite3.connect(f'file:{src}?mode=ro', uri=True)) as s, closing(sqlite3.connect(tmp)) as d:
        s.backup(d)
    for ext in ('-wal', '-shm'):
        if os.path.exists(dst + ext):
            os.remove(dst + ext)
    os.replace(tmp, dst)
    # الشعار القديم إن كان بجانب الملف (static/uploads)
    old_up = os.path.join(os.path.dirname(os.path.abspath(src)), 'static', 'uploads')
    if os.path.isdir(old_up):
        new_up = os.path.join(BASE, 'static', 'uploads')
        os.makedirs(new_up, exist_ok=True)
        for f in os.listdir(old_up):
            shutil.copy2(os.path.join(old_up, f), new_up)
    sys.path.insert(0, BASE)
    import db
    db.init_db()   # يضيف أي أعمدة/جداول جديدة
    print(t('  ✓ نُقلت البيانات. شغّل النظام وادخل بحساباتكم القديمة.', '  ✓ Data moved. Start the system and sign in with your old accounts.'))


if __name__ == '__main__':
    main()
