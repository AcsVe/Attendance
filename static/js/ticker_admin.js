/* ===== تبويب «الشريط الإعلاني» في لوحة التحكم — نفس إعدادات نظامي التذاكر والقاعات.
   العرض نفسه في templates/_ticker.html (يقرأ /api/ticker)، والحفظ في /api/ticker-settings. ===== */
let tickerQuillInstance = null;
let tickerQuillEnInstance = null;

function makeTickerQuill(selector) {
  const SizeStyle = Quill.import('attributors/style/size');
  SizeStyle.whitelist = ['12px', '16px', '22px', '32px'];
  Quill.register(SizeStyle, true);
  return new Quill(selector, {
    theme: 'snow',
    modules: {
      toolbar: [
        ['bold', 'italic', 'underline'],
        [{ color: [] }, { background: [] }],
        [{ size: ['12px', '16px', '22px', '32px'] }],
        ['link'],
        ['clean'],
      ],
    },
  });
}
function getTickerQuill() {
  if (!tickerQuillInstance) {
    tickerQuillInstance = makeTickerQuill('#tickerQuill');
    tickerQuillInstance.root.setAttribute('dir', 'rtl');   // المحتوى العربي يُكتب من اليمين
  }
  return tickerQuillInstance;
}
function getTickerQuillEn() {
  if (!tickerQuillEnInstance) tickerQuillEnInstance = makeTickerQuill('#tickerQuillEn');
  return tickerQuillEnInstance;
}

function previewTickerColors() {   // شكل الشريط أعلى الصفحة يتبع الألوان والشفافية أثناء التحريك (الحفظ بزر «حفظ»)
  const op = parseInt(document.getElementById('tickerBgOpacity').value, 10) || 0;
  document.getElementById('tickerBgOpacityVal').textContent = op + '%';
  const bar = document.getElementById('globalTicker');
  if (!bar) return;
  const n = parseInt(document.getElementById('tickerBgColor').value.slice(1), 16);
  bar.style.background = op > 0 ? `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${op / 100})` : '';
  bar.style.setProperty('--ticker-text', document.getElementById('tickerTextColor').value);
}

async function loadTickerSettings() {
  if (typeof Quill === 'undefined') { toast('تعذّر تحميل محرر النص — تحقق من الاتصال بالإنترنت', true); return; }
  const cfg = await fetch('/api/ticker-settings').then(r => r.json());
  getTickerQuill().root.innerHTML = cfg.html || '';
  getTickerQuillEn().root.innerHTML = cfg.htmlEn || '';
  document.getElementById('tickerEnabled').checked = !!cfg.enabled;
  document.getElementById('tickerSpeed').value = cfg.speedSeconds || 25;
  document.getElementById('tickerRssUrl').value = cfg.rssUrl || '';
  document.getElementById('tickerRssColor').value = cfg.rssColor || '#ffffff';
  document.getElementById('tickerRssFontSize').value = cfg.rssFontSize || 16;
  document.getElementById('tickerRssBold').checked = cfg.rssBold !== false;
  document.getElementById('tickerLogoBetween').checked = !!cfg.logoBetween;
  document.getElementById('tickerPulse').checked = !!cfg.pulse;
  document.getElementById('tickerPulseSpeed').value = cfg.pulseSeconds || 1.6;
  document.getElementById('tickerPulseSpeedRow').style.display = cfg.pulse ? '' : 'none';
  document.getElementById('tickerShadow').value = cfg.textShadow || 'light';
  document.getElementById('tickerBgColor').value = cfg.bgColor || '#1B3358';
  document.getElementById('tickerBgOpacity').value = cfg.bgOpacity || 0;
  document.getElementById('tickerBgOpacityVal').textContent = (cfg.bgOpacity || 0) + '%';
  document.getElementById('tickerTextColor').value = cfg.textColor || '#ffffff';
  if (typeof PERMS !== 'undefined' && !PERMS.can_edit_org_settings) {
    _disableContainer('#tab-ticker');
    getTickerQuill().disable(); getTickerQuillEn().disable();
  }
}

async function saveTickerSettings() {
  if (typeof Quill === 'undefined') return;
  const res = await fetch('/api/ticker-settings', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      enabled: document.getElementById('tickerEnabled').checked,
      html: getTickerQuill().root.innerHTML,
      htmlEn: getTickerQuillEn().root.innerHTML,
      speedSeconds: parseInt(document.getElementById('tickerSpeed').value, 10) || 25,
      rssUrl: document.getElementById('tickerRssUrl').value.trim(),
      rssColor: document.getElementById('tickerRssColor').value,
      rssFontSize: parseInt(document.getElementById('tickerRssFontSize').value, 10) || 16,
      rssBold: document.getElementById('tickerRssBold').checked,
      logoBetween: document.getElementById('tickerLogoBetween').checked,
      pulse: document.getElementById('tickerPulse').checked,
      pulseSeconds: parseFloat(document.getElementById('tickerPulseSpeed').value) || 1.6,
      textShadow: document.getElementById('tickerShadow').value,
      bgColor: document.getElementById('tickerBgColor').value,
      bgOpacity: parseInt(document.getElementById('tickerBgOpacity').value, 10) || 0,
      textColor: document.getElementById('tickerTextColor').value,
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) { toast(data.error || 'حدث خطأ غير متوقع', true); return; }
  toast('تم الحفظ');
  if (window.reloadTicker) window.reloadTicker();   // الشريط في هذه الصفحة يتبع الإعدادات الجديدة فوراً
}

// يُحمَّل محتوى التبويب عند فتحه (من القائمة أو من رابط #ticker)
(function () {
  const orig = window.showTab;
  if (typeof orig !== 'function') return;
  window.showTab = function (tab, opts) {
    const r = orig.apply(this, arguments);
    if (tab === 'ticker') loadTickerSettings();
    return r;
  };
  if (location.hash === '#ticker') setTimeout(() => loadTickerSettings(), 300);
})();
