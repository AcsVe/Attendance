"""نسخة احتياطية سحابية ثانية في Neon (بجانب Google Drive) — تعمل من الكمبيوتر ومن الهاتف.

    python neon_store.py push FILE      # رفع ملف نسخة (يتخطى إن لم تتغير البيانات منذ آخر رفع)
    python neon_store.py pull DIR       # تنزيل أحدث نسخة إلى مجلد (بنفس اسمها الأصلي)
    python neon_store.py info           # آخر نسخة محفوظة في Neon
    python neon_store.py test           # فحص الاتصال

• الرابط في .env:  NEON_BACKUP_URL=postgresql://...   (أو NEON_DATABASE_URL / CLOUD_DATABASE_URL)
• يُحفظ في جدول iaj_cloud_backups داخل قاعدة Neon نفسها — آخر 3 نسخ لكل موقع فقط.
• Python خالص (pg8000) — لا يحتاج برامج إضافية على Windows ولا على Termux.
"""
import gzip
import hashlib
import os
import ssl
import sys
from urllib.parse import parse_qs, unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
SITE = os.environ.get('NEON_SITE') or 'attendance'
KEEP = 3
EN = os.environ.get('IAJ_LANG', os.environ.get('LANG_UI', '')) == 'en'


def t(ar, en):
    return en if EN else ar


def _load_env():
    for p in (os.path.join(BASE, '.env'), os.path.join(BASE, 'IAJ.env')):
        if os.path.isfile(p):
            for raw in open(p, encoding='utf-8-sig', errors='ignore'):
                line = raw.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and v and k not in os.environ:
                        os.environ[k] = v


def _url():
    _load_env()
    for k in ('NEON_BACKUP_URL', 'NEON_DATABASE_URL', 'CLOUD_DATABASE_URL'):
        if os.environ.get(k, '').strip():
            return os.environ[k].strip()
    return ''


def connect():
    url = _url()
    if not url:
        raise SystemExit(t('لا يوجد رابط Neon (NEON_BACKUP_URL) في .env', 'No Neon link (NEON_BACKUP_URL) in .env'))
    try:
        import pg8000.native
    except ImportError:
        raise SystemExit(t('ثبّت المكتبة: pip install pg8000', 'Install the library: pip install pg8000'))
    u = urlparse(url)
    con = pg8000.native.Connection(
        user=unquote(u.username or ''), password=unquote(u.password or ''), host=u.hostname,
        port=u.port or 5432, database=(u.path or '/').lstrip('/') or 'postgres',
        ssl_context=None if parse_qs(u.query).get('sslmode', [''])[0] == 'disable' else ssl.create_default_context(),
        timeout=60)
    con.run("""CREATE TABLE IF NOT EXISTS iaj_cloud_backups (
                 id SERIAL PRIMARY KEY, site TEXT NOT NULL, name TEXT NOT NULL,
                 created TIMESTAMPTZ NOT NULL DEFAULT now(), sha TEXT, size INTEGER, data BYTEA NOT NULL)""")
    return con


def content_sha(path):
    """بصمة المحتوى (بعد فك الضغط — حتى لا يختلف ملفان متطابقان بسبب وقت الضغط)"""
    h = hashlib.sha256()
    opener = gzip.open if path.endswith('.gz') else open
    with opener(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _marker():
    d = os.path.join(BASE, 'logs')
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f'neon_last_push_{SITE}.txt')


def push(path, force=False):
    sha = content_sha(path)
    mk = _marker()
    if not force and os.path.isfile(mk) and open(mk).read().strip() == sha:
        print(t('Neon: لا تغيير منذ آخر رفع — تخطّي', 'Neon: no change since last upload - skipped'))
        return False
    data = open(path, 'rb').read()
    con = connect()
    try:
        con.run('INSERT INTO iaj_cloud_backups (site, name, sha, size, data) VALUES (:s, :n, :h, :z, :d)',
                s=SITE, n=os.path.basename(path), h=sha, z=len(data), d=data)
        con.run('DELETE FROM iaj_cloud_backups WHERE site = :s AND id NOT IN '
                '(SELECT id FROM iaj_cloud_backups WHERE site = :s ORDER BY id DESC LIMIT :k)', s=SITE, k=KEEP)
    finally:
        con.close()
    open(mk, 'w').write(sha)
    print(t(f'✓ Neon: رُفعت {os.path.basename(path)} ({len(data) // 1024} KB)', f'✓ Neon: uploaded {os.path.basename(path)} ({len(data) // 1024} KB)'))
    return True


def latest(con):
    rows = con.run('SELECT id, name, created, size FROM iaj_cloud_backups WHERE site = :s ORDER BY id DESC LIMIT 1', s=SITE)
    return rows[0] if rows else None


def pull(dest):
    con = connect()
    try:
        row = latest(con)
        if not row:
            raise SystemExit(t(f'لا توجد نسخة لـ {SITE} في Neon بعد', f'No backup for {SITE} in Neon yet'))
        data = con.run('SELECT data FROM iaj_cloud_backups WHERE id = :i', i=row[0])[0][0]
    finally:
        con.close()
    os.makedirs(dest, exist_ok=True)
    out = os.path.join(dest, row[1])
    with open(out, 'wb') as fh:
        fh.write(data)
    print(t(f'✓ من Neon: {row[1]} ({row[2]:%Y-%m-%d %H:%M})', f'✓ From Neon: {row[1]} ({row[2]:%Y-%m-%d %H:%M})'))
    return out


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'info'
    if cmd == 'push' and len(sys.argv) > 2:
        push(sys.argv[2], force='--force' in sys.argv)
    elif cmd == 'pull' and len(sys.argv) > 2:
        pull(sys.argv[2])
    elif cmd in ('info', 'test'):
        con = connect()
        try:
            row = latest(con)
        finally:
            con.close()
        print(t('✓ الاتصال بـ Neon يعمل', '✓ Neon connection works'))
        print(t(f'  آخر نسخة لـ {SITE}: ', f'  Latest backup for {SITE}: ') +
              (f'{row[1]}  ({row[2]:%Y-%m-%d %H:%M}, {row[3] // 1024} KB)' if row else t('لا توجد بعد', 'none yet')))
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
