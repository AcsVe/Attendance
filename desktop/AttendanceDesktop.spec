# -*- mode: python -*-
# بناء نسخة سطح المكتب (مجلد واحد): pyinstaller desktop/AttendanceDesktop.spec --noconfirm
# القوالب والملفات الثابتة تُنسخ كما هي؛ الكود يُضمَّن مترجَماً (pyc) لا نصاً مصدرياً.
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))

datas = [(os.path.join(ROOT, 'templates'), 'templates'), (os.path.join(ROOT, 'static'), 'static')]
binaries = []
hidden = ['shares', 'vacations', 'scheduler', 'waitress'] + collect_submodules('zk')
# APScheduler يجد أنواع الجدولة من بيانات الحزمة (entry points)، فتُنسخ كاملة.
# openpyxl/xlrd: محرّكا قراءة Excel يستدعيهما pandas بالاسم وقت الاستيراد فقط، فلا يراهما
# المحلّل الساكن — لذلك نضمّهما صراحةً وإلا فشل استيراد ملفات الموظفين (.xlsx/.xls).
for pkg in ('apscheduler', 'tzdata', 'reportlab', 'pywebpush', 'py_vapid', 'http_ece',
            'openpyxl', 'et_xmlfile', 'xlrd'):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hidden += h
    except Exception:
        pass
hidden += ['openpyxl', 'xlrd', 'et_xmlfile']
# كل وحدات النظام في جذر المستودع (بعضها يُستورد داخل الدوال)
skip = {'serve'}
hidden += [f[:-3] for f in os.listdir(ROOT) if f.endswith('.py') and f[:-3] not in skip]
hidden += ['utils.' + f[:-3] for f in os.listdir(os.path.join(ROOT, 'utils')) if f.endswith('.py') and f != '__init__.py']

a = Analysis([os.path.join(ROOT, 'desktop', 'attendance_desktop.py')],
             pathex=[ROOT],
             binaries=binaries,
             datas=datas,
             hiddenimports=hidden,
             excludes=['tkinter', 'pytest', 'playwright', 'matplotlib', 'IPython'],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='AttendanceDesktop',
          icon=os.path.join(ROOT, 'static', 'icons', 'favicon.ico'), console=True, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name='AttendanceDesktop', upx=False)
