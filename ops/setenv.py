"""تعديل قيمة في ملف .env:  python ops/setenv.py KEY VALUE"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
key, val = sys.argv[1], sys.argv[2]
path = os.path.join(BASE, '.env')
lines = open(path, encoding='utf-8-sig').read().splitlines() if os.path.isfile(path) else []
lines = [ln for ln in lines if not ln.strip().startswith(key + '=')] + [f'{key}={val}']
open(path, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
print(f'{key}={val}')
