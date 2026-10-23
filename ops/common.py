"""أدوات مشتركة للخادم المحلي (الكمبيوتر) والهاتف: قراءة .env ومسارات البيانات والنسخ."""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Windows command windows cannot show Arabic (boxes), so the PC uses English; the phone (Termux) stays Arabic.
# Force either with IAJ_LANG=ar / IAJ_LANG=en.
_LANG = os.environ.get('IAJ_LANG') or os.environ.get('LANG_UI') or ('en' if os.name == 'nt' else 'ar')
EN = _LANG == 'en'
_ASCII = {'✓': '[OK]', '✅': '[OK]', '✖': '[X]', '❌': '[X]', '⚠': '[!]', '←': '<-', '→': '->', '★': '*', '•': '-',
          '🟢': '[OK]', '🔴': '[X]', '✋': '[!]', '…': '...', '—': '-', '–': '-', '«': '"', '»': '"'}


def _plain(text):
    for k, v in _ASCII.items():
        text = text.replace(k, v)
    return text


def t(ar, en):
    if not EN:
        return ar
    return _plain(en) if os.name == 'nt' else en


def load_env():
    """يقرأ .env (لا يستبدل متغيراً موجوداً مسبقاً). الافتراضي: قاعدة SQLite ومجلد data داخل المشروع."""
    path = os.path.join(BASE, '.env')
    if os.path.isfile(path):
        with open(path, encoding='utf-8-sig', errors='ignore') as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    os.environ.setdefault('DATA_DIR', os.path.join(BASE, 'data'))
    # التطبيق يقرأ مسار القاعدة من ATTENDANCE_DB_PATH — نوجّهه لمجلد data (خارج الكود، لا يلمسه التحديث)
    os.environ.setdefault('ATTENDANCE_DB_PATH', os.path.join(os.environ['DATA_DIR'], 'attendance_web.db'))
    if os.environ.get('SECRET_KEY') and not os.environ.get('ATTENDANCE_SECRET_KEY'):
        os.environ['ATTENDANCE_SECRET_KEY'] = os.environ['SECRET_KEY']


def data_dir():
    return os.environ.get('DATA_DIR') or os.path.join(BASE, 'data')


def db_path():
    return os.environ.get('ATTENDANCE_DB_PATH') or os.path.join(data_dir(), 'attendance_web.db')


def uploads_dir():
    """شعار المؤسسة المرفوع (الملف الوحيد الذي يرفعه النظام)"""
    return os.path.join(BASE, 'static', 'uploads')


def backup_root():
    return os.environ.get('BACKUP_DIR') or os.path.join(BASE, 'backups')


def stamp():
    """وقت عمّان (للترتيب ولأسماء الملفات)"""
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo('Asia/Amman')).strftime('%Y-%m-%d_%H%M%S')
    except Exception:
        return datetime.now().strftime('%Y-%m-%d_%H%M%S')


def die(msg, code=1):
    print('\n✖ ' + msg)
    sys.exit(code)
