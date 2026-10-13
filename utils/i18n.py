"""ترجمة رسائل الخادم إلى الإنجليزية عند اختيار المستخدم لها (كوكي lang=en).
تستخدم القاموس نفسه الذي تستخدمه الواجهة: static/i18n/en.json"""
import json
import os
import re

_AR = re.compile(r'[؀-ۿ]')
_D = None


def _load():
    global _D
    if _D is None:
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'i18n', 'en.json')
        try:
            with open(p, encoding='utf-8') as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            raw = {'exact': {}, 'patterns': []}
        exact = {_norm(k): v for k, v in raw['exact'].items()}
        pats = []
        for lits, out in raw['patterns']:
            if any(not x.strip() for x in lits[1:-1]):
                continue
            # المسافات حول الأجزاء الثابتة تُحترم حتى لا يطابق «{0} م» آخر كلمة «النظام»
            parts = [re.escape(re.sub(r'\s+', ' ', re.sub(r'[\u064B-\u0652\u0640]', '', x))).replace('\\ ', '\\s+') for x in lits]
            rx = '^' + '([\\s\\S]+?)'.join(parts) + '$'
            try:
                pats.append((re.compile(rx), out, [_norm(x) for x in lits if x.strip()]))
            except re.error:
                pass
        pats.sort(key=lambda p: -len(''.join(p[2])))   # الأكثر تحديداً أولاً
        _D = (exact, pats)
    return _D


def _norm(s):
    return re.sub(r'\s+', ' ', re.sub(r'[\u064B-\u0652\u0640]', '', s)).strip()


def tr(text):
    """يترجم نصاً عربياً إلى الإنجليزية إن وُجد في القاموس، وإلا يترجم مقاطعه المعروفة"""
    if not isinstance(text, str) or not _AR.search(text):
        return text
    exact, pats = _load()
    s = _norm(text)
    if s in exact:
        return exact[s]
    if '؛' in s:
        return '; '.join(tr(x) for x in re.split(r'\s*؛\s*', s))
    for rx, out, need in pats:
        if len(s) > 400 or any(n not in s for n in need):
            continue
        m = rx.match(s)
        if m:
            return re.sub(r'\{(\d+)\}', lambda g: tr((m.group(int(g.group(1))) or '').strip()), out)

    def seg(mo):
        k = _norm(mo.group(0))
        if k in exact:
            return exact[k]
        return ' '.join(exact.get(w, w) if len(w) > 2 else w for w in k.split(' '))
    return re.sub(r'[؀-ۿ][؀-ۿ\s/،؛\-]*[؀-ۿ]|[؀-ۿ]', seg, s).replace('،', ',').replace('؛', ';').replace('؟', '?')


def ui_lang(request):
    return 'en' if request.cookies.get('lang') == 'en' else 'ar'


_JSON_KEYS = ('error', 'message', 'warning', 'reason', 'kind_label')


def translate_json(obj):
    """يترجم حقول الرسائل فقط (لا البيانات) داخل استجابة JSON"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _JSON_KEYS and isinstance(v, str):
                obj[k] = tr(v)
            elif k in ('results', 'done') and isinstance(v, list):
                obj[k] = [translate_json(x) if isinstance(x, dict) else tr(x) for x in v]
    return obj
