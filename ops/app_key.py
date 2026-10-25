"""Android app keys: the signing secrets go to GitHub (this repository is public) and the employee app gets a
new APP_KEY. Run on the school PC with app_key.bat; values are copied to the clipboard one at a time and are
never printed.

    python ops/app_key.py            # create the new APP_KEY (once) and copy the 4 GitHub secrets
    python ops/app_key.py --status   # is the new key in use, and until when old app versions are accepted
    python ops/app_key.py --end      # stop accepting old app versions now

The new key is kept in the database (app_settings.mobile_app_key), so the standby phone gets it with the
backups. Old app versions (built with the old, published key) keep working for 14 days, then are refused.
"""
import os
import secrets
import subprocess
import sys
import webbrowser
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'ops'))
from common import load_env, t  # noqa: E402

REPO = 'AcsVe/Attendance'
KS_PATH = 'android/keystore/release.jks'
DAYS = 14


def _now():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo('Asia/Amman')).replace(tzinfo=None)
    except Exception:
        return datetime.now()


def _git_file(path):
    """The file as it is in the working tree, or its last version in the git history (it was removed from
    the repository once the secrets moved to GitHub)."""
    full = os.path.join(BASE, path)
    if os.path.isfile(full):
        with open(full, 'rb') as fh:
            return fh.read()
    try:
        rev = subprocess.run(['git', 'log', '-n1', '--format=%H', '--', path], cwd=BASE, capture_output=True,
                             text=True, check=True).stdout.strip()
        for r in (rev, rev + '^'):
            out = subprocess.run(['git', 'show', f'{r}:{path}'], cwd=BASE, capture_output=True)
            if out.returncode == 0 and out.stdout:
                return out.stdout
    except Exception:
        pass
    return None


def _old_password():
    """From android/signing.properties if there is one, else from the last version of android/app.properties
    that still held it (before the secrets moved to GitHub)."""
    texts = []
    local = os.path.join(BASE, 'android', 'signing.properties')
    if os.path.isfile(local):
        with open(local, encoding='utf-8', errors='ignore') as fh:
            texts.append(fh.read())
    try:
        rev = subprocess.run(['git', 'log', '-n1', '-S', 'KEYSTORE_PASSWORD=', '--format=%H', '--',
                              'android/app.properties'], cwd=BASE, capture_output=True, text=True,
                             check=True).stdout.strip()
        for r in (rev, rev + '^'):
            out = subprocess.run(['git', 'show', f'{r}:android/app.properties'], cwd=BASE, capture_output=True)
            if out.returncode == 0:
                texts.append(out.stdout.decode('utf-8', 'ignore'))
    except Exception:
        pass
    for text in texts:
        for line in text.splitlines():
            if line.strip().startswith('KEYSTORE_PASSWORD='):
                v = line.split('=', 1)[1].strip()
                if v:
                    return v
    return None


def _copy(value):
    if os.name == 'nt':
        subprocess.run(['clip'], input=value.encode('utf-8'), check=True)
        return True
    for cmd in (['termux-clipboard-set'], ['xclip', '-selection', 'clipboard'], ['pbcopy']):
        try:
            subprocess.run(cmd, input=value.encode('utf-8'), check=True)
            return True
        except Exception:
            continue
    return False


def ensure_key(db):
    key = db.get_setting('mobile_app_key', '')
    if key:
        return key, False
    env = os.environ.get('MOBILE_APP_KEY', '')
    from mobile import LEGACY_APP_KEY
    key = env if env and env != LEGACY_APP_KEY else secrets.token_urlsafe(32)
    db.set_setting('mobile_app_key', key)
    db.set_setting('mobile_app_key_legacy_until', (_now() + timedelta(days=DAYS)).strftime('%Y-%m-%d %H:%M'))
    return key, True


def main():
    load_env()
    import db
    db.init_db()
    if '--status' in sys.argv or '--end' in sys.argv:
        if '--end' in sys.argv:
            db.set_setting('mobile_app_key_legacy_until', _now().strftime('%Y-%m-%d %H:%M'))
        has = bool(db.get_setting('mobile_app_key', ''))
        until = db.get_setting('mobile_app_key_legacy_until', '')
        print(t(f'  المفتاح الجديد: {"مُفعّل" if has else "غير مُنشأ بعد"}', f'  New APP_KEY: {"in use" if has else "not created yet"}'))
        if has:
            old = until and _now().strftime('%Y-%m-%d %H:%M') < until
            print(t(f'  النسخ القديمة من التطبيق: {"مقبولة حتى " + until if old else "مرفوضة"}',
                    f'  Old app versions: {"accepted until " + until if old else "refused"}'))
        return
    key, made = ensure_key(db)
    ks = _git_file(KS_PATH)
    pw = _old_password()
    if not ks or not pw:
        print(t('  ✖ لم أجد مفتاح التوقيع أو كلمة مروره في المستودع', '  [X] Signing key or its password not found in the repository history'))
        sys.exit(1)
    import base64
    items = [('ANDROID_KEYSTORE_B64', base64.b64encode(ks).decode()), ('ANDROID_KEYSTORE_PASSWORD', pw),
             ('ANDROID_KEY_ALIAS', 'attendance'), ('ATT_APP_KEY', key)]
    if made:
        print(t(f'\n  ✓ أُنشئ مفتاح جديد للتطبيق. النسخ القديمة تبقى تعمل {DAYS} يوماً.',
                f'\n  [OK] New app key created. Old app versions keep working for {DAYS} days.'))
    print(t('\n  أضف 4 أسرار في GitHub. سأنسخ كل قيمة ثم أفتح الصفحة:', '\n  Add 4 secrets in GitHub. Each value is copied for you; nothing is shown on screen.'))
    url = f'https://github.com/{REPO}/settings/secrets/actions/new'
    for i, (name, value) in enumerate(items, 1):
        input(t(f'\n  [{i}/4] اضغط Enter لنسخ قيمة {name}', f'\n  [{i}/4] Press Enter to copy the value of {name} ') )
        if not _copy(value):
            print(t('  ✖ تعذّر النسخ إلى الحافظة', '  [X] Could not copy to the clipboard'))
            sys.exit(1)
        webbrowser.open(url)
        print(t(f'  ✓ نُسخت. في GitHub: Name = {name} ، Secret = الصق (Ctrl+V) ، ثم Add secret',
                f'  [OK] Copied. In GitHub: Name = {name}, Secret = paste (Ctrl+V), then "Add secret".'))
        input(t('  ثم اضغط Enter هنا', '  Then press Enter here '))
    _copy(' ')                                        # do not leave a secret in the clipboard
    print(t('\n  ✓ تمت الأسرار. الآن: Actions ← Android APKs ← Run workflow (فتحتها لك).',
            '\n  [OK] Secrets done. Now: Actions > Android APKs > "Run workflow" (opened for you).'))
    webbrowser.open(f'https://github.com/{REPO}/actions/workflows/android.yml')
    print(t('  بعد انتهاء البناء (~5 دقائق) شغّل update.bat، وأبلغ الموظفين بتحديث التطبيق من صفحة /app.',
            '  When the build finishes (~5 minutes) run update.bat, and ask the employees to update the app from the /app page.'))


if __name__ == '__main__':
    main()
