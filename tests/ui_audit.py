"""فحص مظهر لوحة التحكم في متصفح حقيقي: كل تبويب، بالعربية والإنجليزية، على الحاسوب والهاتف.

يفحص: أخطاء JavaScript، والتباين، والخط الأصغر من 13px، والخروج الأفقي عن الشاشة، واتجاه النص
(نص يبدأ بلغة ومعه أرقام أو علامات داخل عنصر باتجاه اللغة الأخرى فيظهر مقلوباً)، والنصوص غير المترجمة
(أي حرف عربي في الواجهة الإنجليزية حين تكون البيانات كلها إنجليزية).

ثلاث جولات: واجهة عربية ببيانات عربية، وواجهة إنجليزية ببيانات عربية (للاتجاه)، وواجهة إنجليزية ببيانات
إنجليزية (للترجمة). البيانات مصطنعة في قاعدة مؤقتة (tests/audit_server.py) ولا يُمسّ شيء حقيقي.

التشغيل:  python tests/ui_audit.py        (E2E_CHANNEL=chrome|msedge|chromium، E2E_OUT=مجلد الصور)
النتيجة يجب أن تكون 0 ملاحظات.
"""
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get('E2E_OUT') or tempfile.mkdtemp(prefix='att-ui-')
os.makedirs(OUT, exist_ok=True)

TABS = re.findall(r'data-tab="([a-z-]+)"', open(os.path.join(ROOT, 'templates', 'dashboard.html'), encoding='utf-8').read())
TABS = list(dict.fromkeys(TABS))
# عناصر تبقى بالعربية عمداً في الواجهة الإنجليزية: زر تبديل اللغة، واسم المستخدم «مدير النظام» المحفوظ في القاعدة
UNTRANSLATED_OK = ['العربية', 'مدير النظام']

AUDIT_JS = r"""(args) => {
  const [scopeSel, checkArabic, okList] = args;
  const scope = document.querySelector(scopeSel) || document.body;
  const lum = (c) => { const m = c.match(/[\d.]+/g); if (!m) return null; const [r, g, b] = m.slice(0, 3).map((v) => { v = v / 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
    return { l: 0.2126 * r + 0.7152 * g + 0.0722 * b, a: m.length > 3 ? Number(m[3]) : 1 }; };
  const bgOf = (el) => { while (el) { const s = getComputedStyle(el); const L = lum(s.backgroundColor);
      if (s.backgroundImage !== 'none') return null; if (L && L.a > 0.9) return L.l; el = el.parentElement; } return 1; };
  const AR = /[؀-ۿ]/, LA = /[A-Za-z]/, NEUTRAL = /[0-9٠-٩.:*?؟()\-–—%/]/;
  const firstStrong = (t) => { for (const ch of t) { if (AR.test(ch)) return 'rtl'; if (LA.test(ch)) return 'ltr'; } return null; };
  const isolated = (n) => n.nodeType === 1 && (n.tagName === 'BDI' || n.hasAttribute('dir') || getComputedStyle(n).unicodeBidi === 'plaintext');
  // النص بين علامتي العزل (U+2068…U+2069) يأخذ اتجاهه بنفسه
  const textOf = (n) => n.nodeType === 3 ? n.textContent.replace(/\u2068[^\u2069]*\u2069/g, ' ') : (isolated(n) ? ' ' : [...n.childNodes].map(textOf).join(''));
  const out = { contrast: [], small: [], bidi: [], untranslated: [] };
  const seen = new Set();
  const add = (k, list, msg) => { if (!seen.has(k)) { seen.add(k); out[list].push(msg.slice(0, 150)); } };
  [document.querySelector('.topbar, header'), scope].filter(Boolean).forEach((root) => root.querySelectorAll('*').forEach((el) => {
    if (!el.offsetParent && getComputedStyle(el).position !== 'fixed') return;
    const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim().length > 1);
    if (!own) return;
    const s = getComputedStyle(el); if (s.visibility === 'hidden') return;
    // الشفافية الفعلية = حاصل ضرب شفافية العنصر وكل آبائه (المكتبات تُبهت الأب لا النص نفسه)
    let op = 1; for (let n = el; n; n = n.parentElement) op *= Number(getComputedStyle(n).opacity);
    if (op < 0.15) return;
    if (el.closest('canvas,svg,option,select,script,style,.leaflet-container')) return;
    const fs = parseFloat(s.fontSize), fw = Number(s.fontWeight) || 400;
    const txt = el.textContent.replace(/\s+/g, ' ').trim().slice(0, 50);
    let fg = lum(s.color); const bg = bgOf(el);
    if (fg && bg !== null && op < 1) fg = { l: fg.l * op + bg * (1 - op), a: fg.a };   // تقريب: مزج الإضاءة مع الخلفية
    const fieldOff = el.tagName === 'LABEL' && el.closest('.form-group') && el.closest('.form-group').querySelector('input:disabled,select:disabled,textarea:disabled');   // تسمية حقل معطّل مستثناة كالحقل نفسه
    if (fg && bg !== null && !fieldOff && !el.closest(':disabled,[disabled]')) {
      const ratio = (Math.max(fg.l, bg) + 0.05) / (Math.min(fg.l, bg) + 0.05);
      const large = fs >= 24 || (fs >= 18.6 && fw >= 700);
      if (ratio < (large ? 3 : 4.5)) add('c' + txt, 'contrast', `${ratio.toFixed(2)} «${txt}» ${el.tagName}.${el.className}`);
    }
    // تاريخ ووقت بلا حروف (2026-11-06 18:05) داخل عنصر من اليمين لليسار: يظهر الوقت قبل التاريخ
    const own2 = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join(' ').trim();
    if (s.direction === 'rtl' && /^\d{4}-\d{2}-\d{2}[ T]\d{1,2}:\d{2}/.test(own2) && s.unicodeBidi !== 'plaintext')
      add('t' + own2, 'bidi', `rtl «${own2.slice(0, 40)}» ${el.tagName}.${el.className}`);
    if (fs < 13) add('s' + txt, 'small', `${fs}px «${txt}» ${el.tagName}.${el.className}`);
    const full = s.unicodeBidi === 'plaintext' ? '' : [...el.childNodes].map(textOf).join('').replace(/\s+/g, ' ').trim();
    const want = firstStrong(full);
    if (want && want !== s.direction && NEUTRAL.test(full) && (AR.test(full) && LA.test(full) || want === 'rtl' ? true : /^[^A-Za-z]|[^A-Za-z0-9]$/.test(full))
        && !el.closest('code,pre,kbd,input,textarea')) add('d' + full, 'bidi', `${s.direction} «${full.slice(0, 60)}» ${el.tagName}.${el.className}`);
    if (checkArabic && !el.closest('[data-content]')) {   // data-content: محتوى يكتبه المستخدم (اسم بلغتين مثلاً)
      const ownTxt = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join(' ').replace(/\s+/g, ' ').trim();
      if (AR.test(ownTxt) && !okList.some((w) => ownTxt === w)) add('u' + ownTxt, 'untranslated', `«${ownTxt.slice(0, 70)}» ${el.tagName}.${el.className}`);
    }
  }));
  // عناصر تفيض عن بطاقتها
  out.overflow = document.documentElement.scrollWidth - innerWidth;
  return out;
}"""


def start_server(db, lang, port):
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, 'tests', 'audit_server.py'), db, lang, str(port)],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(120):
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{port}/login', timeout=1)
            return proc
        except Exception:
            time.sleep(0.5)
    proc.terminate()
    raise SystemExit('the test server did not start')


report = []
servers = {'ar': start_server(os.path.join(OUT, 'ar.db'), 'ar', 5191), 'en': start_server(os.path.join(OUT, 'en.db'), 'en', 5192)}
PORTS = {'ar': 5191, 'en': 5192}
try:
    with sync_playwright() as p:
        kw = {'executable_path': os.environ['PW_EXE']} if os.environ.get('PW_EXE') else {'channel': os.environ.get('E2E_CHANNEL', 'chrome')}
        browser = p.chromium.launch(**kw)
        for ui, data in (('ar', 'ar'), ('en', 'ar'), ('en', 'en')):
            base = f'http://127.0.0.1:{PORTS[data]}'
            for vp_name, vp in (('desktop', {'viewport': {'width': 1366, 'height': 900}}), ('phone', dict(p.devices['iPhone 13']))):
                ctx = browser.new_context(**vp)
                ctx.add_cookies([{'name': 'lang', 'value': ui, 'url': base}])
                page = ctx.new_page()
                errs = []
                page.on('pageerror', lambda e: errs.append(str(e)))
                page.on('console', lambda m: errs.append(m.text) if m.type == 'error' and 'favicon' not in m.text else None)
                page.goto(base + '/login', wait_until='networkidle')
                report.append((vp_name, ui, data, 'login', page.evaluate(AUDIT_JS, ['body', ui == 'en' and data == 'en', UNTRANSLATED_OK]), list(errs)))
                errs.clear()
                page.fill('input[name=username]', 'admin')
                page.fill('input[name=password]', os.environ.get('ATTENDANCE_ADMIN_PASSWORD') or 'admin123')
                page.click('button[type=submit]')
                page.wait_for_load_state('networkidle')
                for t in TABS:
                    page.evaluate(f"showTab('{t}')")
                    try:
                        page.wait_for_load_state('networkidle', timeout=8000)
                    except Exception:
                        pass
                    page.wait_for_timeout(500)
                    res = page.evaluate(AUDIT_JS, [f'#tab-{t}', ui == 'en' and data == 'en', UNTRANSLATED_OK])
                    report.append((vp_name, ui, data, t, res, list(errs)))
                    errs.clear()
                    if os.environ.get('SHOTS'):
                        page.screenshot(path=os.path.join(OUT, f'{vp_name}-{ui}{data}-{t}.jpg'), type='jpeg', quality=45)
                # صفحات خارج لوحة التحكم: شاشة العرض، وجهاز المدخل، وتطبيق الموظف
                for u in ('/display/audit-display-token-000001', '/display/not-a-real-token-0000000', '/kiosk', '/me/logout', '/me/login', '/me/forgot', '/app'):
                    page.goto(base + u, wait_until='networkidle')
                    page.wait_for_timeout(600)
                    if 'not-a-real' in u:   # الرابط غير الصحيح يُرجع 404 عمداً
                        errs[:] = [e for e in errs if '404' not in e]
                    report.append((vp_name, ui, data, u, page.evaluate(AUDIT_JS, ['body', ui == 'en' and data == 'en', UNTRANSLATED_OK]), list(errs)))
                    errs.clear()
                page.goto(base + '/me/login', wait_until='networkidle')
                page.fill('#mu', 'emp1')
                page.fill('#mp', 'emp12345')
                page.click('#f button[type=submit]')
                page.wait_for_load_state('networkidle')
                page.wait_for_timeout(1200)
                report.append((vp_name, ui, data, '/me', page.evaluate(AUDIT_JS, ['body', ui == 'en' and data == 'en', UNTRANSLATED_OK]), list(errs)))
                errs.clear()
                if os.environ.get('SHOTS'):
                    page.screenshot(path=os.path.join(OUT, f'{vp_name}-{ui}{data}-me.jpg'), type='jpeg', quality=45, full_page=True)
                ctx.close()
        browser.close()
finally:
    for s in servers.values():
        s.terminate()

import json  # noqa: E402
with open(os.path.join(OUT, 'report.json'), 'w', encoding='utf-8') as fh:
    json.dump(report, fh, ensure_ascii=False)

bad = 0
for vp_name, ui, data, t, res, errs in report:
    issues = []
    if res['overflow'] > 2:
        issues.append(f"horizontal overflow {res['overflow']}px")
    issues += ['contrast ' + x for x in res['contrast']] + ['small ' + x for x in res['small']]
    issues += ['direction ' + x for x in res['bidi']] + ['untranslated ' + x for x in res['untranslated']]
    issues += ['JS ' + e for e in errs]
    if issues:
        bad += len(issues)
        print(f'[{vp_name} ui={ui} data={data}] {t}')
        for i in issues[:15]:
            print('   ', i)
        if len(issues) > 15:
            print(f'    … {len(issues) - 15} more')
print(f'\n{len(report)} page views, {bad} issue(s). Output: {OUT}')
sys.exit(1 if bad else 0)
