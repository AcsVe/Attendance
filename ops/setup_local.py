"""إعداد ملف .env لنظام الحضور على هذا الجهاز (مرة واحدة). يقرأ إعدادات موقع الجائزة IAJ إن وجده (مجلد Drive + رمز Cloudflare)."""
import getpass
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import BASE  # noqa: E402

ENV = os.path.join(BASE, '.env')


def read_env(path):
    out = {}
    if os.path.isfile(path):
        for raw in open(path, encoding='utf-8-sig', errors='ignore'):
            line = raw.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def find_iaj():
    """مجلد موقع الجائزة على نفس الجهاز (للاستفادة من BACKUP_DIR وCF_API_TOKEN)"""
    cands = [os.environ.get('IAJ_DIR', '')]
    parent = os.path.dirname(BASE)
    try:
        cands += [os.path.join(parent, d) for d in os.listdir(parent)]
    except OSError:
        pass
    for drive in 'CDEFG':
        cands += [f'{drive}:\\IAJ', f'{drive}:\\IAJ-main', f'{drive}:\\iaj']
    for d in cands:
        if d and os.path.isfile(os.path.join(d, 'standby', 'cf_switch.py')) and os.path.isfile(os.path.join(d, '.env')):
            return d
    return ''


def ask(label, default='', secret=False):
    shown = ' [مخفي]' if secret and default else (f' [{default}]' if default else '')
    v = (getpass.getpass if secret else input)(f'  {label}{shown}: ').strip()
    return v or default


def set_admin_password(pw):
    """كلمة مرور حساب admin (بدل الافتراضية admin123)"""
    sys.path.insert(0, BASE)
    from common import load_env
    load_env()
    import db
    db.init_db()
    from werkzeug.security import generate_password_hash
    conn = db.get_db()
    try:
        n = conn.execute("UPDATE users SET password_hash = ? WHERE username = 'admin'", (generate_password_hash(pw),)).rowcount
        conn.commit()
    finally:
        conn.close()
    print('  ✓ تم تعيين كلمة مرور admin' if n else '  (لا يوجد حساب باسم admin — تُركت الحسابات كما هي)')


def main():
    cur = read_env(ENV)
    iaj = find_iaj()
    ie = read_env(os.path.join(iaj, '.env')) if iaj else {}
    if iaj:
        print(f'  وُجد موقع الجائزة في: {iaj}  (سآخذ منه مجلد Drive ورمز Cloudflare)')
    bk_default = cur.get('BACKUP_DIR') or (os.path.join(ie['BACKUP_DIR'], 'attendance') if ie.get('BACKUP_DIR') else '')
    print('\n  إعدادات نظام الحضور والانصراف (اضغط Enter لقبول القيمة بين القوسين أو للتخطي)\n')
    vals = dict(cur)
    vals.setdefault('SECRET_KEY', secrets.token_urlsafe(48))
    vals['BASE_URL'] = ask('عنوان الموقع', cur.get('BASE_URL', 'https://3.iajaward.org'))
    vals['PORT'] = cur.get('PORT', '8003')
    vals['BACKUP_DIR'] = ask('مجلد النسخ الاحتياطية (داخل Google Drive)', bk_default)
    vals['CF_API_TOKEN'] = cur.get('CF_API_TOKEN') or ie.get('CF_API_TOKEN', '') or ask('رمز Cloudflare API', '', True)
    order = ['SECRET_KEY', 'BASE_URL', 'PORT', 'BACKUP_DIR', 'CF_API_TOKEN']
    keys = order + [k for k in vals if k not in order]
    with open(ENV, 'w', encoding='utf-8') as fh:
        fh.write('# إعدادات نظام الحضور على هذا الجهاز — لا ترفع هذا الملف ولا تشاركه\n')
        for k in keys:
            if vals.get(k):
                fh.write(f'{k}={vals[k]}\n')
    print(f'\n  ✓ حُفظت الإعدادات في {ENV}')
    print('\n  كلمة مرور حساب admin (8 أحرف على الأقل) — Enter لتركها كما هي:')
    while True:
        pw = getpass.getpass('  كلمة المرور: ').strip()
        if not pw:
            break
        if len(pw) < 8:
            print('  قصيرة — 8 أحرف على الأقل')
            continue
        if getpass.getpass('  أعد كتابتها: ').strip() != pw:
            print('  غير متطابقتين — أعد المحاولة')
            continue
        set_admin_password(pw)
        break


if __name__ == '__main__':
    main()
