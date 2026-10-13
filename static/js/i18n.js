/* =====================================================================
   ترجمة الواجهة (العربية ⇄ English)
   - اللغة تُحفظ في كوكي lang (يقرؤها الخادم أيضاً لترجمة رسائل الأخطاء)
   - عند اختيار الإنجليزية: تُترجم النصوص الظاهرة وخصائص placeholder/title/aria-label/alt
     من القاموس static/i18n/en.js، بما فيها ما يُضاف لاحقاً للصفحة (MutationObserver)،
     ورسائل alert/confirm/prompt، وتنسيق التواريخ والأرقام.
   - البيانات نفسها (أسماء الموظفين…) لا تُترجم؛ و <option> بلا value تُحفظ قيمتها الأصلية أولاً.
   ===================================================================== */
(function () {
  function getLang() { var m = document.cookie.match(/(?:^|; )lang=(en|ar)/); return m ? m[1] : 'ar'; }
  var LANG = getLang();
  window.UI_LANG = LANG;
  window.setUiLang = function (l) {
    document.cookie = 'lang=' + l + '; path=/; max-age=31536000; samesite=lax';
    location.reload();
  };
  window.toggleUiLang = function () { window.setUiLang(LANG === 'en' ? 'ar' : 'en'); };
  if (LANG !== 'en') return;

  var D = window.I18N_EN || { exact: {}, patterns: [] };
  var AR = /[؀-ۿ]/;
  var EXACT = {};
  Object.keys(D.exact).forEach(function (k) { EXACT[norm(k)] = D.exact[k]; });
  function norm(s) { return s.replace(/[\u064B-\u0652\u0640]/g, '').replace(/\s+/g, ' ').trim(); }   // بدون تشكيل وتطويل
  function esc(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
  var PATS = D.patterns.filter(function (p) {
    // نتجنّب الأنماط ذات المتغيّرات المتجاورة (تسبّب بطئاً شديداً في المطابقة)
    var lits = p[0];
    for (var i = 1; i < lits.length - 1; i++) if (!lits[i].trim()) return false;
    return true;
  }).map(function (p) {
    // المسافات حول الأجزاء الثابتة تُحترم (\s+) حتى لا يطابق «{0} م» آخر كلمة «النظام»
    var lits = p[0], re = '^';
    for (var i = 0; i < lits.length; i++) {
      var raw = lits[i].replace(/[\u064B-\u0652\u0640]/g, '').replace(/\s+/g, ' ');
      re += esc(raw).replace(/ /g, '\\s+');
      if (i < lits.length - 1) re += '([\\s\\S]+?)';
    }
    var need = lits.map(function (x) { return norm(x); }).filter(function (x) { return x; });
    try { return { re: new RegExp(re + '$'), out: p[1], need: need }; } catch (e) { return null; }
  }).filter(Boolean).sort(function (x, y) { return y.need.join('').length - x.need.join('').length; });   // الأكثر تحديداً أولاً

  var cache = {};
  function T(raw) {
    if (!raw || !AR.test(raw)) return raw;
    if (cache.hasOwnProperty(raw)) return cache[raw];
    var lead = raw.match(/^\s*/)[0], trail = raw.match(/\s*$/)[0], s = norm(raw), out = null;
    if (EXACT.hasOwnProperty(s)) out = EXACT[s];
    if (out === null) {
      // بادئة/لاحقة رموز (⚠ ✓ 🔍 * : …)
      var m = s.match(/^([^؀-ۿ«(]*)([\s\S]*?)([\s:*…\.\)»]*)$/);
      if (m && EXACT.hasOwnProperty(norm(m[2]))) out = m[1] + EXACT[norm(m[2])] + m[3];
    }
    if (out === null && s.indexOf('؛') > 0) {
      out = s.split(/\s*؛\s*/).map(T).join('; ');
    }
    if (out === null) {
      for (var i = 0; i < PATS.length && s.length < 400; i++) {
        var ok = true;
        for (var q = 0; q < PATS[i].need.length; q++) if (s.indexOf(PATS[i].need[q]) < 0) { ok = false; break; }
        if (!ok) continue;
        var mm = PATS[i].re.exec(s);
        if (mm) { out = PATS[i].out.replace(/\{(\d+)\}/g, function (_, n) { return T((mm[+n] || '').trim()); }); break; }
      }
    }
    if (out === null) {
      // ترجمة المقاطع العربية داخل نص مختلط (أرقام/أسماء/رموز)
      out = s.replace(/[؀-ۿ][؀-ۿ\s\/،؛\-]*[؀-ۿ]|[؀-ۿ]/g, function (seg) {
        var k = norm(seg);
        if (EXACT.hasOwnProperty(k)) return EXACT[k];
        return k.split(' ').map(function (w) { return (w.length > 2 && EXACT.hasOwnProperty(w)) ? EXACT[w] : w; }).join(' ');   // كلمة من حرفين أو أقل (اسم قسم مثلاً) تبقى كما هي
      }).replace(/،/g, ',').replace(/؛/g, ';').replace(/؟/g, '?');
    }
    out = lead + out + trail;
    cache[raw] = out;
    return out;
  }
  window.T = T;

  var ATTRS = ['placeholder', 'title', 'aria-label', 'alt'];
  var SKIP = { SCRIPT: 1, STYLE: 1, TEXTAREA: 1, CODE: 1, NOSCRIPT: 1 };
  function skipNode(el) {
    for (var e = el; e && e.nodeType === 1; e = e.parentElement) { if (SKIP[e.tagName] || e.hasAttribute('data-notr') || e.isContentEditable) return true; }
    return false;
  }
  function doText(n) {
    var v = n.nodeValue;
    if (!v || !AR.test(v) || skipNode(n.parentElement)) return;
    var p = n.parentElement;
    if (p && p.tagName === 'OPTION' && !p.hasAttribute('value')) p.setAttribute('value', p.textContent);
    if (done.has(n) && done.get(n) === v) return;
    var t = T(v);
    if (t !== v) n.nodeValue = t;
    done.set(n, t);
  }
  function doEl(el) {
    if (el.nodeType !== 1 || skipNode(el)) return;
    for (var i = 0; i < ATTRS.length; i++) {
      var a = el.getAttribute(ATTRS[i]);
      if (a && AR.test(a)) { var ta = T(a); if (ta !== a) el.setAttribute(ATTRS[i], ta); }
    }
    if ((el.tagName === 'INPUT') && (el.type === 'button' || el.type === 'submit') && AR.test(el.value)) el.value = T(el.value);
  }
  function walk(root) {
    if (root.nodeType === 3) { doText(root); return; }
    if (root.nodeType !== 1 && root.nodeType !== 9 && root.nodeType !== 11) return;
    if (root.nodeType === 1) doEl(root);
    var w = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, null);
    var n; while ((n = w.nextNode())) { if (n.nodeType === 3) doText(n); else doEl(n); }
  }

  // اتجاه الصفحة ولغتها
  document.documentElement.lang = 'en';
  document.documentElement.dir = 'ltr';

  var done = new WeakMap();   // عقدة ← آخر قيمة كتبناها (لا نعيد معالجتها)
  var busy = false;
  var mo = new MutationObserver(function (muts) {
    if (busy) return; busy = true;
    try {
      for (var i = 0; i < muts.length; i++) {
        var m = muts[i];
        if (m.type === 'childList') { for (var j = 0; j < m.addedNodes.length; j++) walk(m.addedNodes[j]); }
        else if (m.type === 'characterData') doText(m.target);
        else if (m.type === 'attributes') doEl(m.target);
      }
    } finally { mo.takeRecords(); busy = false; }   // نتجاهل التغييرات التي أحدثناها نحن
  });
  function fixTitle() {
    var t = document.title;
    if (!t || !AR.test(t)) return;
    var nt = t.split(' — ').map(T).join(' — ');
    if (nt !== t) document.title = nt;     // لا نعيد الكتابة إن لم يتغيّر شيء (يمنع الحلقة اللانهائية)
  }
  function start() {
    walk(document.body || document.documentElement);
    fixTitle();
    mo.observe(document.documentElement, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });
    // عنوان الصفحة يتغيّر من الكود (showTab)
    var titleEl = document.querySelector('title');
    if (titleEl) new MutationObserver(fixTitle).observe(titleEl, { childList: true, characterData: true, subtree: true });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();

  // رسائل المتصفح
  var _a = window.alert, _c = window.confirm, _p = window.prompt;
  window.alert = function (m) { return _a.call(window, T(String(m))); };
  window.confirm = function (m) { return _c.call(window, T(String(m))); };
  window.prompt = function (m, d) { return _p.call(window, T(String(m)), d); };

  // التواريخ والأرقام بالإنجليزية بدل العربية
  function fix(loc) { return (!loc || /^ar/.test(String(loc))) ? 'en-GB' : loc; }
  ['toLocaleDateString', 'toLocaleTimeString', 'toLocaleString'].forEach(function (fn) {
    var orig = Date.prototype[fn];
    Date.prototype[fn] = function (loc, opt) { return orig.call(this, fix(loc), opt); };
  });
  var nOrig = Number.prototype.toLocaleString;
  Number.prototype.toLocaleString = function (loc, opt) { return nOrig.call(this, fix(loc), opt); };
})();
