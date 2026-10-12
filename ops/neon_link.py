"""ربط النسخ الاحتياطي بـ Neon (مرة واحدة على الكمبيوتر): يحفظ الرابط في .env ويختبره ويرفع أول نسخة."""
import getpass
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
ENV = os.path.join(BASE, '.env')


def set_env(key, val):
    lines = open(ENV, encoding='utf-8-sig').read().splitlines() if os.path.isfile(ENV) else []
    lines = [ln for ln in lines if not ln.strip().startswith(key + '=')] + [f'{key}={val}']
    open(ENV, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')


def main():
    print('\n  الصق رابط Neon لهذا النظام (DATABASE_URL من Render، يبدأ بـ postgresql://)')
    print('  في PowerShell/CMD الصق بزر الفأرة الأيمن — لا يظهر شيء أثناء اللصق، ثم Enter\n')
    url = ''.join(ch for ch in getpass.getpass('  الرابط: ') if ch.isprintable()).strip()
    if '://' not in url:
        print('\n  ✖ الرابط لم يُلصق صحيحاً — أعد المحاولة (زر الفأرة الأيمن للصق)')
        sys.exit(1)
    os.environ['NEON_BACKUP_URL'] = url
    sys.path.insert(0, HERE)
    import neon_store
    try:
        con = neon_store.connect()
        con.close()
    except BaseException as e:   # noqa: BLE001
        print(f'\n  ✖ تعذّر الاتصال بـ Neon: {e}')
        sys.exit(1)
    set_env('NEON_BACKUP_URL', url)
    print('\n  ✓ حُفظ الرابط في .env والاتصال يعمل — رفع أول نسخة الآن…\n')
    BACKUP_CMD = [sys.executable] + sys.argv[1:]
    if BACKUP_CMD[1:]:
        subprocess.call(BACKUP_CMD)


if __name__ == '__main__':
    main()
