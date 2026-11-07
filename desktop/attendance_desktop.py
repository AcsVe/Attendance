"""نسخة سطح المكتب من نظام الحضور والانصراف: برنامج واحد يعمل على كمبيوتر ويندوز دون خادم أو نفق أو إعداد يدوي.

خيار إضافي بجانب التثبيت على الخادم (لا يغيّره)، مناسب للتجربة والتقييم ولمؤسسة صغيرة على جهاز واحد:
• يشغّل النظام نفسه (الكود والقوالب والقاعدة نفسها) بخادم Waitress على http://localhost ويفتح المتصفح.
• البيانات في %LOCALAPPDATA%\\IAJ Attendance (القاعدة والنسخ والسجل)؛ لا يمسّها التحديث ولا إلغاء التثبيت.
• أول تشغيل: يُنشأ حساب المدير admin بكلمة مرور عشوائية تظهر في النافذة وتُحفظ في ملف «first-sign-in.txt» في مجلد البيانات.
• تشغيله مرة ثانية والنظام يعمل يفتح المتصفح فقط.
• الوصول من أجهزة الشبكة (الهاتف وأجهزة البصمة بنمط ADMS) يُفعَّل بالخيار --lan.

نصوص النافذة بالإنجليزية لأن نافذة الأوامر في ويندوز لا تعرض العربية سليمة.

    AttendanceDesktop.exe [--lan] [--port 8003] [--no-browser] [--selftest]
"""
import argparse
import logging
import logging.handlers
import os
import secrets
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

APP_TITLE = 'IAJ Attendance'


def app_dir():
    """مجلد ملفات البرنامج: مجلد البرنامج المبني، أو جذر المستودع عند التشغيل من المصدر."""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_root():
    base = os.environ.get('ATTENDANCE_DESKTOP_HOME')
    if base:
        return base
    if os.name == 'nt':
        return os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), APP_TITLE)
    return os.path.join(os.path.expanduser('~'), '.iaj-attendance')


def answering(port):
    """هل يعمل النظام على هذا المنفذ (نسخة سابقة من البرنامج)؟"""
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/login', timeout=2) as r:
            return r.headers.get('Server', '').startswith('ATTENDANCE') or r.status == 200
    except Exception:
        return False


def port_free(port, host):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def prepare(root, lan, port):
    """متغيرات البيئة قبل استيراد النظام: مسارات البيانات، والعنوان المحلي، وكلمة مرور المدير في أول تشغيل."""
    data = os.path.join(root, 'data')
    os.makedirs(data, exist_ok=True)
    os.makedirs(os.path.join(root, 'logs'), exist_ok=True)
    db_path = os.path.join(data, 'attendance_web.db')
    first = not os.path.exists(db_path)
    os.environ['DATA_DIR'] = data
    os.environ['ATTENDANCE_DB_PATH'] = db_path
    os.environ.setdefault('BACKUP_DIR', os.path.join(root, 'backups'))
    os.environ['HOST'] = '0.0.0.0' if lan else '127.0.0.1'
    os.environ['PORT'] = str(port)
    # عنوان http محلي: ملفات تعريف الارتباط غير مقيّدة بـ https (المتصفح يعدّ localhost آمناً)
    os.environ['BASE_URL'] = f'http://localhost:{port}'
    os.environ['ATTENDANCE_EDITION'] = 'desktop'
    password = None
    if first:
        password = secrets.token_urlsafe(9)
        os.environ['ATTENDANCE_ADMIN_PASSWORD'] = password
        with open(os.path.join(root, 'first-sign-in.txt'), 'w', encoding='utf-8') as fh:
            fh.write('IAJ Attendance - first sign-in\n'
                     f'Address : http://localhost:{port}\n'
                     'Username: admin\n'
                     f'Password: {password}\n\n'
                     'Change the password after signing in (Users tab), then delete this file.\n'
                     'غيّر كلمة المرور بعد الدخول (تبويب «المستخدمون»)، ثم احذف هذا الملف.\n')
    return password


def setup_logging(root):
    handler = logging.handlers.RotatingFileHandler(os.path.join(root, 'logs', 'server.log'),
                                                   maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    return logging.getLogger('attendance.desktop')


def load_system():
    base = app_dir()
    os.chdir(base)
    for p in (base, os.path.join(base, 'ops')):
        if p not in sys.path:
            sys.path.insert(0, p)
    import db
    db.init_db()
    from app import app
    return app


def selftest(root):
    """فحص البناء: يشغّل النظام على قاعدة مؤقتة، ويتحقق من صفحة الدخول والدخول ولوحة التحكم، ثم يخرج."""
    import tempfile
    os.environ['ATTENDANCE_DESKTOP_HOME'] = tempfile.mkdtemp(prefix='att-selftest-')
    root = data_root()
    os.environ['DISABLE_SCHEDULER'] = '1'
    password = prepare(root, False, 0)
    app = load_system()
    c = app.test_client()
    page = c.get('/login')
    assert page.status_code == 200, page.status_code
    r = c.post('/login', data={'username': 'admin', 'password': password})
    assert r.status_code == 302 and '/login' not in r.headers.get('Location', ''), 'sign-in failed'
    dash = c.get(r.headers['Location'])
    assert dash.status_code == 200, f'dashboard did not open ({dash.status_code})'
    assert c.get('/api/employees').status_code in (200, 404), 'the data API did not answer'
    for path in ('/static/i18n/en.js', '/static/css/style.css', '/static/icons/favicon.ico'):
        if os.path.exists(os.path.join(app_dir(), path.lstrip('/'))):
            assert c.get(path).status_code == 200, path
    print('selftest ok')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog='AttendanceDesktop', description='IAJ Attendance (desktop edition)')
    ap.add_argument('--lan', action='store_true', help='accept connections from other devices on the network')
    ap.add_argument('--port', type=int, default=int(os.environ.get('ATTENDANCE_DESKTOP_PORT') or 8003))
    ap.add_argument('--no-browser', action='store_true')
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest(data_root())

    root = data_root()
    os.makedirs(root, exist_ok=True)
    url = f'http://localhost:{args.port}'
    if answering(args.port):
        print(f'{APP_TITLE} is already running: {url}')
        if not args.no_browser:
            webbrowser.open(url)
        time.sleep(2)
        return 0
    host = '0.0.0.0' if args.lan else '127.0.0.1'
    port = args.port
    while not port_free(port, host) and port < args.port + 20:
        port += 1
    url = f'http://localhost:{port}'
    password = prepare(root, args.lan, port)
    log = setup_logging(root)

    print('=' * 62)
    print(f'  {APP_TITLE} - desktop edition')
    print('=' * 62)
    print('  Starting, please wait...')
    try:
        app = load_system()
    except Exception:
        log.exception('The system failed to start')
        print('\n  The system could not start. Details are in:')
        print('  ' + os.path.join(root, 'logs', 'server.log'))
        input('\n  Press Enter to close this window.')
        return 1
    if os.environ.get('DISABLE_SCHEDULER') != '1':
        try:
            import scheduler
            scheduler.start_scheduler()
        except Exception:
            log.exception('Scheduler did not start')

    print(f'\n  Open in the browser : {url}')
    if args.lan:
        try:
            ip = socket.gethostbyname(socket.gethostname())
            print(f'  From other devices  : http://{ip}:{port}')
        except OSError:
            pass
    if password:
        print('\n  First sign-in   username: admin')
        print(f'                  password: {password}')
        print('  (also saved in ' + os.path.join(root, 'first-sign-in.txt') + ')')
        print('  Change the password after signing in.')
    print(f'\n  Data folder: {root}')
    print('\n  Keep this window open while using the system. Close it to stop.')

    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    from waitress import serve
    log.info('ATTENDANCE desktop on %s (data: %s)', url, root)
    serve(app, host=host, port=port, threads=8, max_request_body_size=2 * 1024 ** 3, channel_timeout=600,
          ident='ATTENDANCE')
    return 0


if __name__ == '__main__':
    sys.exit(main())
