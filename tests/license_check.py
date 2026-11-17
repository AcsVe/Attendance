"""فحص اشتراك النسخة المستضافة (utils/license.py) على نسخة مؤقتة من التطبيق: الحالات، وما يتوقف وما يبقى مفتوحاً بعد
الإيقاف، والربط بالملف المشترك.

    python tests/license_check.py            (يخرج بالرمز 0 إن نجحت كل الفحوص)
لا يمسّ قاعدة المدرسة: قاعدة مؤقتة وبيانات مصطنعة.
"""
import json
import os
import sys
import tempfile
from datetime import timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix='att-license-')
os.environ['ATTENDANCE_DB_PATH'] = os.path.join(TMP, 'att.db')
os.environ['PAGE_SHIELD'] = '0'          # الصفحات المشفّرة لا تُقرأ في الفحص
for k in ('BASE_URL', 'LICENSE_UNTIL', 'LICENSE_WARN_DAYS', 'LICENSE_GRACE_DAYS', 'LICENSE_CONTACT', 'LICENSE_FILE', 'LICENSE_ID'):
    os.environ.pop(k, None)
sys.path.insert(0, ROOT)

import db  # noqa: E402
db.init_db()
import app as A  # noqa: E402
from utils import license as L  # noqa: E402

app = A.app
failed = []


def check(name, cond):
    print(('PASS ' if cond else 'FAIL ') + name)
    if not cond:
        failed.append(name)


def until(days, **env):
    os.environ['LICENSE_UNTIL'] = (L._today() + timedelta(days=days)).isoformat()
    os.environ.update(env)


def state():
    return L.status()['state']


def admin():
    c = app.test_client()
    r = c.post('/login', data={'username': 'admin', 'password': os.environ.get('ATTENDANCE_ADMIN_PASSWORD') or 'admin123'})
    assert r.status_code in (200, 302), r.status_code
    return c


c = admin()
check('without a date nothing changes', state() == 'none' and c.get('/dashboard').status_code == 200
      and b'license-alert' not in c.get('/dashboard').data)
until(100); check('far from the end: ok, no banner', state() == 'ok' and b'license-alert' not in c.get('/dashboard').data)
until(10, LICENSE_CONTACT='0790000000'); page = c.get('/dashboard').data.decode()
check('near the end: warn + banner with the contact', state() == 'warn' and 'license-alert' in page and '0790000000' in page)
until(-3); check('in the grace: banner and the pages keep working', state() == 'grace' and c.get('/dashboard').status_code == 200
                 and b'license-alert' in c.get('/dashboard').data)
until(-3, LICENSE_GRACE_DAYS='1'); check('shorter grace expires it', state() == 'expired')
os.environ.pop('LICENSE_GRACE_DAYS')
until(-9, LICENSE_CONTACT='0790000000')
r = c.get('/dashboard')
check('expired: the dashboard answers 403 with the contact', state() == 'expired' and r.status_code == 403 and b'0790000000' in r.data)
check('expired: the admin API answers 403 JSON', c.get('/api/employees').status_code == 403 and c.get('/api/employees').get_json().get('license') == 'expired')
check('expired: the employee app and the kiosk are paused', app.test_client().get('/me/login').status_code == 403 and app.test_client().get('/kiosk').status_code == 403)
check('expired: sign-in, sign-out and password recovery stay open', all(app.test_client().get(p).status_code == 200 for p in ('/login', '/forgot')))
check('expired: the fingerprint devices keep recording (/iclock, /dahua/push)',
      app.test_client().get('/iclock/getrequest?SN=X1').status_code != 403 and app.test_client().post('/dahua/push', data=b'').status_code != 403)
check('expired: English paused page on request', b'The subscription for this system has ended' in app.test_client().get('/dashboard?lang=en').data)
until(100); check('renewed: back at once', state() == 'ok' and c.get('/dashboard').status_code == 200)
os.environ['LICENSE_UNTIL'] = 'not-a-date'; check('an invalid date is ignored', state() == 'none' and c.get('/dashboard').status_code == 200)
os.environ.pop('LICENSE_UNTIL')

f = os.path.join(TMP, 'licenses.json')
os.environ.update(LICENSE_FILE=f, LICENSE_ID='rasatt')
check('linked but the file is missing: falls back to .env, keeps working', state() == 'none' and c.get('/dashboard').status_code == 200)
day = lambda n: (L._today() + timedelta(days=n)).isoformat()
open(f, 'w').write(json.dumps({'rasatt': {'until': day(-9), 'contact': 'c-1'}}))
check('file entry expired: paused at once, contact from the file', state() == 'expired' and L.status()['contact'] == 'c-1' and c.get('/dashboard').status_code == 403)
open(f, 'w').write(json.dumps({'rasatt': {'until': day(100)}})); check('file renewed: back at once, no restart', state() == 'ok' and c.get('/dashboard').status_code == 200)
open(f, 'w').write(json.dumps({'rasatt': {'until': day(4), 'warn_days': 5}})); check('warn days from the file', state() == 'warn')
open(f, 'w').write(json.dumps({'rasatt': {'until': day(-2), 'grace_days': 5}})); check('grace days from the file', state() == 'grace')
open(f, 'w').write(json.dumps({'rasb': {'until': day(-99)}})); check("another system's entry does not affect this one", state() == 'none')
os.environ['LICENSE_UNTIL'] = day(-99); check('linked: the file wins over .env', state() == 'none')
open(f, 'w').write('{not json'); check('a corrupt file falls back to .env instead of crashing', state() == 'expired')

print('RESULT', 'ALL PASS' if not failed else f'{len(failed)} FAIL')
os._exit(1 if failed else 0)
