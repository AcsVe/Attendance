/* نظام تحليل الحضور والانصراف - منطق الواجهة الأمامية (SPA في تبويبات) */

/* ===== فلترة عامة لكل الجداول - تُضاف تلقائياً لأي <table class="dt-filterable">
   بصف إدخال أسفل رأس الجدول مباشرة، وتفلتر صفوف الـtbody الظاهرة حسب نص كل
   عمود لحظياً (بدون أي تعديل لدوال تحميل كل جدول على حدة). عمود بصندوق
   اختيار (تحديد الكل) يُستثنى من الفلترة بوضع class="no-filter" على <th> */
function initTableFilters() {
  document.querySelectorAll('table.dt-filterable').forEach(table => {
    const headRow = table.querySelector('thead tr');
    if (!headRow || table.querySelector('thead tr.dt-filter-row')) return;
    const filterRow = document.createElement('tr');
    filterRow.className = 'dt-filter-row';
    Array.from(headRow.children).forEach(th => {
      const cell = document.createElement('th');
      if (!th.classList.contains('no-filter')) {
        const input = document.createElement('input');
        input.type = 'text';
        input.placeholder = 'فلترة...';
        input.className = 'search-input dt-filter-input';
        input.style.cssText = 'width:100%;font-size:.78rem;padding:4px 6px;font-weight:normal';
        input.addEventListener('input', () => filterTable(table));
        cell.appendChild(input);
      }
      filterRow.appendChild(cell);
    });
    table.querySelector('thead').appendChild(filterRow);
  });
}

function filterTable(table) {
  const filterCells = Array.from(table.querySelectorAll('thead tr.dt-filter-row th'));
  const values = filterCells.map(th => {
    const input = th.querySelector('input');
    return input ? input.value.trim().toLowerCase() : '';
  });
  const tbody = table.querySelector('tbody');
  if (!tbody) return;
  Array.from(tbody.rows).forEach(row => {
    let visible = true;
    Array.from(row.cells).forEach((cell, i) => {
      const v = values[i];
      if (v && !cell.textContent.toLowerCase().includes(v)) visible = false;
    });
    row.style.display = visible ? '' : 'none';
  });
}

function applyAllTableFilters() {
  document.querySelectorAll('table.dt-filterable').forEach(filterTable);
}

/* ===== فرز عام لكل الجداول - يُضاف تلقائياً لأي <table class="dt-filterable">
   (نفس آلية الفلترة العامة أعلاه بالضبط): الضغط على عنوان أي عمود يفرز
   صفوف الجدول تصاعدياً/تنازلياً حسب محتوى ذلك العمود (رقمياً لو كل القيم
   أرقام، وإلا أبجدياً عربياً) - عمود صندوق الاختيار (no-filter) يُستثنى
   تلقائياً لأنه غير قابل للفرز أصلاً ===== */
function initTableSorting(root) {
  (root || document).querySelectorAll('table').forEach(table => {
    if (table.dataset.sortReady || table.classList.contains('no-sort')) return;
    const headRow = table.querySelector('thead tr');
    const tbody = table.querySelector('tbody');
    if (!headRow || !tbody) return;
    table.dataset.sortReady = '1';
    Array.from(headRow.children).forEach((th, idx) => {
      // عمود صندوق الاختيار أو عمود الأزرار (بدون عنوان) لا يُفرز
      if (th.classList.contains('no-filter') || th.classList.contains('no-sort') || th.querySelector('input') || !th.textContent.trim()) return;
      if (th.getAttribute('onclick')) return;   // جداول لها فرز خاص من الخادم (التقارير)
      th.classList.add('dt-sortable');
      th.title = 'اضغط للفرز تصاعدياً/تنازلياً';
      const arrow = document.createElement('span');
      arrow.className = 'dt-sort-arrow';
      th.appendChild(arrow);
      th.addEventListener('click', () => {
        const dir = th.dataset.sortDir === 'asc' ? 'desc' : 'asc';
        headRow.querySelectorAll('th').forEach(h => { h.dataset.sortDir = ''; const a = h.querySelector('.dt-sort-arrow'); if (a) a.textContent = ''; });
        th.dataset.sortDir = dir;
        arrow.textContent = dir === 'asc' ? '▲' : '▼';
        table.dataset.sortCol = idx;
        table.dataset.sortDir = dir;
        sortTableRows(table);
      });
    });
    // عند إعادة تحميل الصفوف (تحديث/بحث) يبقى الفرز المختار مطبَّقاً
    new MutationObserver(() => {
      if (table._sorting || table.dataset.sortCol === undefined) return;
      sortTableRows(table);
    }).observe(tbody, { childList: true });
  });
}

function _sortKey(text) {
  const t = text.trim();
  const n = t.replace(/[,\s%]/g, '').replace(/[٠-٩]/g, d => '٠١٢٣٤٥٦٧٨٩'.indexOf(d));
  return /^-?\d+(\.\d+)?$/.test(n) ? { num: parseFloat(n) } : { str: t };
}

function sortTableRows(table) {
  const tbody = table.querySelector('tbody');
  const col = +table.dataset.sortCol, mult = table.dataset.sortDir === 'desc' ? -1 : 1;
  const rows = Array.from(tbody.rows);
  const sortable = rows.filter(r => r.cells.length > col && !(r.cells.length === 1 && r.cells[0].colSpan > 1));
  if (sortable.length < 2) return;
  sortable.sort((a, b) => {
    const x = _sortKey(a.cells[col].textContent), y = _sortKey(b.cells[col].textContent);
    if (x.str === '' && y.str !== '') return 1;          // الفارغ دائماً بالأسفل
    if (y.str === '' && x.str !== '') return -1;
    if ('num' in x && 'num' in y) return (x.num - y.num) * mult;
    return String(x.str ?? x.num).localeCompare(String(y.str ?? y.num), 'ar', { numeric: true }) * mult;
  });
  table._sorting = true;
  sortable.forEach(r => tbody.appendChild(r));
  setTimeout(() => { table._sorting = false; }, 0);
}

// جداول تُبنى لاحقاً (ملف الموظف، النوافذ) تحصل على الفرز تلقائياً
new MutationObserver(muts => {
  for (const m of muts) for (const n of m.addedNodes) {
    if (n.nodeType === 1 && (n.tagName === 'TABLE' || n.querySelector && n.querySelector('table'))) { initTableSorting(n.parentNode || document); return; }
  }
}).observe(document.documentElement, { childList: true, subtree: true });

/* ===== تحديد الكل / حذف المحدد - عام لأي جدول فيه عمود صندوق اختيار
   بـ class="row-check" و data-id على كل صف ===== */
function toggleSelectAll(tbodyId, checked) {
  document.querySelectorAll(`#${tbodyId} .row-check`).forEach(cb => { cb.checked = checked; });
}

async function bulkDeleteSelected(tbodyId, urlBuilder, reloadFn, opts = {}) {
  const boxes = Array.from(document.querySelectorAll(`#${tbodyId} .row-check:checked`))
    .filter(cb => cb.closest('tr').style.display !== 'none'); // نتجاهل صفوف مخفية بالفلترة
  if (!boxes.length) { toast('حدّد عنصراً واحداً على الأقل', true); return; }
  if (!confirm(`حذف ${boxes.length} عنصر محدَّد؟ لا يمكن التراجع.`)) return;
  let ok = 0, fail = 0;
  for (const cb of boxes) {
    try {
      if (opts.customDelete) {
        await opts.customDelete(cb);
      } else {
        await api(urlBuilder(cb.dataset.id), { method: 'DELETE' });
      }
      ok++;
    } catch (e) { fail++; }
  }
  toast(fail ? `تم حذف ${ok}، وفشل حذف ${fail}` : `تم حذف ${ok} عنصر`);
  reloadFn();
}

const PAGE_TITLES = {
  dashboard: 'لوحة التحكم', upload: 'رفع البيانات والتحليل', reports: 'التقارير',
  overtime: 'العمل الإضافي', compare: 'المقارنات', blueprint: 'النظرة الشاملة', export: 'التصدير',
  manual: 'الإدخال اليدوي', exceptions: 'استثناءات التواريخ', 'absence-reasons': 'أسباب الغياب',
  holidays: 'العطل الرسمية',
  permissions: 'أذونات التأخير والمغادرة', employees: 'الموظفون', devices: 'أجهزة البصمة',
  'dept-times': 'أوقات الأقسام', settings: 'الإعدادات العامة', schedule: 'الجدولة التلقائية',
  audit: 'سجل التدقيق', users: 'المستخدمون والصلاحيات', maintenance: 'أدوات الصيانة',
};

let currentTab = 'dashboard';
let reportState = { type: 'all', page: 1, sort: '', dir: 'asc' };

/* ===== الصلاحيات: مطابقة للنسخة المكتبية (home.py) - كل التبويبات ظاهرة
   لأي مستخدم مسجَّل دخول عدا "المستخدمون" (admin فقط)، وأزرار/حقول
   محدَّدة تُعطَّل حسب 4 صلاحيات دقيقة (can_manage_employees/
   can_push_devices/can_edit_org_settings) - نفس فلسفة تعطيل الأزرار
   هناك، فرق إنه هنا مُطبَّق أيضاً بالخادم (403) لأن هذا تطبيق ويب. */
const CURRENT_ROLE = document.body.dataset.role || 'viewer';
const PERMS = {
  can_manage_employees: document.body.dataset.canManageEmployees === '1',
  can_push_devices: document.body.dataset.canPushDevices === '1',
  can_edit_org_settings: document.body.dataset.canEditOrgSettings === '1',
};

function _disableContainer(selector) {
  document.querySelectorAll(`${selector} input, ${selector} select, ${selector} textarea, ${selector} button`)
    .forEach(el => { el.disabled = true; el.title = 'ليس لديك صلاحية لهذا الإجراء'; });
}

function applyRolePermissions() {
  if (CURRENT_ROLE !== 'admin') {
    document.querySelectorAll('[data-tab="users"], [data-tab="maintenance"]').forEach(el => { el.style.display = 'none'; });
  }
  if (!PERMS.can_manage_employees) {
    _disableContainer('#empAddCard');
    _disableContainer('#empImportCard');
  }
  if (!PERMS.can_push_devices) {
    _disableContainer('#tab-devices');
  }
  if (!PERMS.can_edit_org_settings) {
    _disableContainer('#tab-settings');
    _disableContainer('#tab-dept-times');
  }
}

function toast(msg, isError) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast show' + (isError ? ' error' : '');
  setTimeout(() => { el.className = 'toast'; }, 3000);
}

async function api(url, opts) {
  const res = await fetch(url, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts || {}));
  if (res.status === 401) { window.location.href = '/login'; return null; }
  const data = await res.json();
  if (!data.ok) { toast(data.error || 'حدث خطأ غير متوقع', true); throw new Error(data.error || 'error'); }
  return data;
}

function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
  document.getElementById('sidebarOverlay').classList.toggle('open');
}

/* ===== مجموعات القائمة الجانبية: طيّ/فتح يُحفظ لكل مستخدم على هذا الجهاز ===== */
function _navCollapsed() { try { return JSON.parse(localStorage.getItem('att_nav_collapsed') || '[]'); } catch (e) { return []; } }
function toggleNavGroup(id, open) {
  const g = document.querySelector(`.nav-group[data-group="${id}"]`);
  if (!g) return;
  const collapsed = open === undefined ? !g.classList.contains('collapsed') : !open;
  g.classList.toggle('collapsed', collapsed);
  g.querySelector('.nav-group-title').setAttribute('aria-expanded', String(!collapsed));
  const list = _navCollapsed().filter(x => x !== id);
  if (collapsed) list.push(id);
  try { localStorage.setItem('att_nav_collapsed', JSON.stringify(list)); } catch (e) {}
}
function initNavGroups() {
  _navCollapsed().forEach(id => { const g = document.querySelector(`.nav-group[data-group="${id}"]`); if (g) g.classList.add('collapsed'); });
  // مجموعة كل عناصرها مخفية بالصلاحيات تُخفى كاملة
  document.querySelectorAll('.nav-group:not(.nav-fav-group)').forEach(g => {
    const visible = Array.from(g.querySelectorAll('.nav-item')).some(b => b.style.display !== 'none');
    g.style.display = visible ? '' : 'none';
  });
}

/* ===== موضع التمرير لكل تبويب: يعود كما كان بعد التحديث (F5) أو الرجوع للتبويب ===== */
const _scrollKey = t => 'att_scroll_' + t;
window.addEventListener('scroll', () => {
  clearTimeout(window._scrollSaveT);
  window._scrollSaveT = setTimeout(() => { try { sessionStorage.setItem(_scrollKey(currentTab), String(window.scrollY)); } catch (e) {} }, 150);
}, { passive: true });
function _restoreScroll(tab) {
  let y = 0; try { y = +sessionStorage.getItem(_scrollKey(tab)) || 0; } catch (e) {}
  if (!y) { window.scrollTo(0, 0); return; }
  // المحتوى يُحمَّل من الخادم؛ نعيد المحاولة حتى يصبح طول الصفحة كافياً
  let n = 0;
  const tryIt = () => { if (document.body.scrollHeight - window.innerHeight >= y - 5 || n++ > 20) window.scrollTo(0, y); else setTimeout(tryIt, 100); };
  tryIt();
}

function showTab(tab, opts) {
  opts = opts || {};
  const btn = document.querySelector(`.nav-item:not(.nav-fav)[data-tab="${tab}"]`);
  if (!document.getElementById('tab-' + tab) || (btn && btn.style.display === 'none')) tab = 'dashboard';
  currentTab = tab;
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.getElementById('tab-' + tab).classList.add('active');
  document.querySelectorAll('.nav-item, .mobile-nav-item').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  document.getElementById('pageTitle').textContent = PAGE_TITLES[tab] || tab;
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('sidebarOverlay').classList.remove('open');
  document.title = (PAGE_TITLES[tab] || tab) + ' — نظام الحضور والانصراف';
  const active = document.querySelector(`.nav-item:not(.nav-fav)[data-tab="${tab}"]`);
  if (active) {
    const g = active.closest('.nav-group');
    if (g && g.classList.contains('collapsed')) toggleNavGroup(g.dataset.group, true);
    active.scrollIntoView({ block: 'nearest' });
  }
  if (!opts.keepScroll) setTimeout(() => _restoreScroll(tab), 0);
  // ===== نسجّل التبويب الحالي بعنوان الصفحة (hash) وبتاريخ التصفّح
  // (history) بدل تركه بذاكرة JS فقط - هيك زر "رجوع" بالتلفون يتنقّل
  // بين التبويبات داخل نفس التطبيق (بدل ما يطلع فوراً لصفحة تسجيل
  // الدخول بذاكرة المتصفح ويبدو وكأن المستخدم خرج من حسابه)، وتحديث
  // الصفحة (refresh) يرجّع نفس التبويب المفتوح (بدل الرجوع دائماً
  // للوحة التحكم) لأن العنوان بعد التحديث بيضل فيه اسم التبويب =====
  try { sessionStorage.setItem('att_last_tab', tab); } catch (e) {}
  if (!opts.skipHistory) {
    const newHash = '#' + tab;
    if (window.location.hash !== newHash) {
      history.pushState({ tab }, '', newHash);
    }
  }
  refreshCurrentTab();
}

window.addEventListener('popstate', (e) => {
  const tab = (e.state && e.state.tab) || (window.location.hash || '').replace('#', '') || 'dashboard';
  showTab(tab, { skipHistory: true });
});

function refreshCurrentTab() {
  const loaders = {
    dashboard: loadStats, upload: () => {}, reports: () => loadReports(1),
    overtime: () => {}, compare: () => loadCompare(), blueprint: loadBlueprint, export: () => {},
    manual: loadManualEntries, exceptions: loadDateExceptions, 'absence-reasons': loadAbsenceReasons,
    holidays: loadHolidays,
    permissions: loadPermissions, employees: loadEmployees, devices: loadDevices, 'dept-times': loadDeptTimes,
    settings: loadSettings, schedule: loadScheduleSettings, audit: loadAuditLog, users: loadUsers,
    ...(window.EXTRA_LOADERS || {}),
  };
  loadMetaInto();
  Promise.resolve((loaders[currentTab] || (() => {}))()).then(() => {
    applyRolePermissions();
    applyAllTableFilters();
  });
}

function goToReport(rt) {
  showTab('reports');
  setReportType(rt);
}

/* ===== إشعار "آخر سحب/استيراد بصمات" عند فتح التطبيق - يمنع تكرار نفس
   عملية السحب/الاستيراد الطويلة (خصوصاً ملفات SQLite ضخمة عبر رابط سحابي
   قد تأخذ دقائق) بدون داعٍ لو أصلاً صارت مؤخراً. يظهر مرة وحدة بالجلسة
   (sessionStorage) حتى لا يتكرر إزعاجه كل ما تبدّل المستخدم تبويب ===== */
async function loadLastImportNotice() {
  const box = document.getElementById('lastImportNotice');
  if (!box) return;
  if (sessionStorage.getItem('lastImportNoticeDismissed') === '1') return;
  try {
    const res = await fetch('/api/last-import-notice');
    const data = await res.json();
    if (!data.ok || !data.has_notice) return;
    box.style.display = 'block';
    box.innerHTML = `
      <div class="alert" style="background:#eaf4f8;border:1px solid var(--primary-light);color:#124a5f;display:flex;justify-content:space-between;align-items:flex-start;gap:10px;padding:12px 14px;border-radius:8px;margin-bottom:14px">
        <div>
          <i class="fas fa-info-circle" aria-hidden="true"></i>
          <b>آخر عملية سحب/استيراد بصمات:</b> ${escapeHtml(data.label)} — ${escapeHtml(data.timestamp)}
          ${data.username ? ' بواسطة ' + escapeHtml(data.username) : ''}
          ${data.detail ? `<br><span style="font-size:.85rem">${escapeHtml(data.detail)}</span>` : ''}
          <br><span style="font-size:.8rem">تأكّد من هذا قبل تكرار نفس عملية السحب/الاستيراد لتفادي الانتظار غير الضروري (خصوصاً لملفات كبيرة).</span>
        </div>
        <button class="btn btn-outline btn-sm" style="white-space:nowrap" onclick="dismissLastImportNotice()" aria-label="إغلاق" title="إغلاق"><i class="fas fa-times" aria-hidden="true"></i></button>
      </div>`;
  } catch (e) {}
}

function dismissLastImportNotice() {
  sessionStorage.setItem('lastImportNoticeDismissed', '1');
  const box = document.getElementById('lastImportNotice');
  if (box) box.style.display = 'none';
}

/* ===== الساعة الحية ===== */
function tickClock() {
  const t = document.getElementById('clockTime'), d = document.getElementById('clockDate');
  if (!t || !d) return;
  const en = document.documentElement.lang === 'en', now = new Date(), loc = en ? 'en-GB' : 'ar-EG';
  t.textContent = now.toLocaleTimeString(loc, { hour: '2-digit', minute: '2-digit', hour12: !en });
  d.textContent = now.toLocaleDateString(loc, { weekday: 'short', day: 'numeric', month: 'short' });
}
setInterval(tickClock, 1000);
tickClock();

/* ===== تحميل الأقسام/الموظفين لكل قوائم الفلترة ===== */
let EMPLOYEES_FULL = []; // [{name, dept}] - لتصفية قائمة الموظفين حسب القسم المختار
let LATE_LABELS = []; // أسباب تأخير سبق إدخالها (لصندوق "تسجيل حدث" السريع)
let ABSENCE_REASON_OPTIONS = []; // أسباب غياب سبق إدخالها (لنفس الصندوق)

// ===== أزواج (قسم/موظف) يجب أن يُصفّى فيها حقل الموظف تلقائياً حسب
// القسم المختار بجانبه - كانت المشكلة سابقاً إن اختيار قسم لا يغيّر
// إطلاقاً قائمة الموظفين المعروضة (تبقى كل موظفي القاعدة) =====
const DEPT_EMPLOYEE_PAIRS = [
  ['dashDept', 'dashEmployee'], ['repDept', 'repEmployee'],
  ['arDept', 'arEmployee'], ['expDept', 'expEmployee'],
];

function _employeeNamesForDept(dept) {
  if (!dept) return EMPLOYEES_FULL.map(e => e.name);
  return EMPLOYEES_FULL.filter(e => (e.dept || '') === dept).map(e => e.name);
}

function refreshEmployeeOptionsForDept(deptId, empId) {
  const deptEl = document.getElementById(deptId);
  const empEl = document.getElementById(empId);
  if (!deptEl || !empEl) return;
  const dept = deptEl.value;
  const names = _employeeNamesForDept(dept);
  if (empEl.multiple) {
    // ===== قائمة متعددة الاختيار (مثل repEmployee) - نحافظ على أي أسماء
    // مختارة حالياً ما زالت ضمن قائمة القسم الجديد، بدل تفريغها بالكامل =====
    fillMultiSelect(empId, names);
  } else {
    const placeholder = dept ? `كل موظفي قسم "${dept}"` : 'كل الموظفين';
    fillSelect(empId, names, placeholder);
  }
}

// ===== يحدّد كل الأسماء المعروضة حالياً بقائمة موظف متعددة الاختيار
// (بعد تصفيتها حسب القسم المجاور) دفعة وحدة - يلبّي طلب "شخصين أو أكثر
// من نفس القسم" بضغطة واحدة بدل تحديدهم واحداً واحداً بـCtrl+ضغط =====
function selectAllFilteredEmployees(deptId, empId) {
  const empEl = document.getElementById(empId);
  if (!empEl) return;
  Array.from(empEl.options).forEach(o => { o.selected = true; });
  empEl.dispatchEvent(new Event('change'));
}

function _wireDeptEmployeeFilters() {
  DEPT_EMPLOYEE_PAIRS.forEach(([deptId, empId]) => {
    const deptEl = document.getElementById(deptId);
    if (!deptEl || deptEl.dataset.deptFilterWired) return;
    deptEl.dataset.deptFilterWired = '1';
    // ===== نسجّلها أولاً (قبل أي onchange موجود أصلاً بالـHTML) حتى تُحدَّث
    // قائمة الموظفين فوراً قبل استدعاء أي تحميل بيانات آخر مرتبط بنفس الحدث =====
    deptEl.addEventListener('change', () => refreshEmployeeOptionsForDept(deptId, empId));
  });
}

async function loadMetaInto() {
  const data = await api('/api/meta');
  if (!data) return;
  const deptSelects = ['dashDept', 'repDept', 'arDept', 'expDept'];
  const empSelects = ['dashEmployee', 'repEmployee', 'arEmployee', 'expEmployee'];
  EMPLOYEES_FULL = data.employees_full || data.employees.map(n => ({ name: n, dept: '' }));
  LATE_LABELS = data.late_labels || [];
  ABSENCE_REASON_OPTIONS = data.absence_reason_options || [];
  deptSelects.forEach(id => fillSelect(id, data.departments, 'كل الأقسام'));
  // ===== كل حقل موظف يُملأ بموظفي القسم المختار حالياً بجانبه فقط (فاضي =
  // كل الموظفين) بدل قائمة موظفي القاعدة الكاملة دائماً =====
  DEPT_EMPLOYEE_PAIRS.forEach(([deptId, empId]) => refreshEmployeeOptionsForDept(deptId, empId));
  _wireDeptEmployeeFilters();
  const nameListIds = ['manNameList', 'excNameList', 'lpNameList', 'dpNameList'];
  const optsHtml = data.employees.map(n => `<option value="${escapeHtml(n)}">`).join('');
  nameListIds.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = optsHtml;
  });
  fillMultiSelect('otNames', data.employees);
  fillMultiSelect('excBulkNames', data.employees);
  fillMultiSelect('faNames', data.employees);
  DEPTS_CACHE = data.departments || [];
  _fillDeptMultiSelect(document.getElementById('usrDepts'), []);
}

function fillMultiSelect(id, values) {
  const el = document.getElementById(id);
  if (!el) return;
  const selected = new Set(Array.from(el.selectedOptions).map(o => o.value));
  el.innerHTML = values.map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join('');
  Array.from(el.options).forEach(o => { o.selected = selected.has(o.value); });
}

function fillSelect(id, values, placeholder) {
  const el = document.getElementById(id);
  if (!el) return;
  const current = el.value;
  el.innerHTML = `<option value="">${placeholder}</option>` + values.map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join('');
  el.value = current;
}

function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/* ============ DASHBOARD ============ */
function clearDashFilters() {
  ['dashDept', 'dashEmployee', 'dashFrom', 'dashTo'].forEach(id => document.getElementById(id).value = '');
  loadStats();
}

function dashParams() {
  const p = new URLSearchParams();
  const dept = document.getElementById('dashDept').value;
  const emp = document.getElementById('dashEmployee').value;
  const from = document.getElementById('dashFrom').value;
  const to = document.getElementById('dashTo').value;
  if (dept) p.set('dept', dept);
  if (emp) p.set('employee', emp);
  if (from) p.set('date_from', from);
  if (to) p.set('date_to', to);
  return p;
}

async function loadStats() {
  const data = await api('/api/stats?' + dashParams().toString());
  if (!data) return;
  document.getElementById('stTotal').textContent = data.total;
  document.getElementById('stOntime').textContent = data.ontime;
  document.getElementById('stLate').textContent = data.late;
  document.getElementById('stAbsent').textContent = data.absent;
  document.getElementById('stHoliday').textContent = data.holiday;
  document.getElementById('stSatPresent').textContent = data.sat_present;
  document.getElementById('stAvgHours').textContent = data.avg_hours;
  document.getElementById('stAvgLate').textContent = data.avg_late;
}

/* ============ UPLOAD & ANALYZE ============ */
let uploadColumns = [];
let uploadCloudUrl = null; // رابط سحابي بديل عن الملف - يُضبط عبر loadUploadFromUrl()

function _handleUploadPreview(data) {
  if (!data.ok) { toast(data.error || 'خطأ بقراءة الملف', true); return; }
  if (data.needs_mapping) {
    uploadColumns = data.columns;
    ['mapName', 'mapDate', 'mapTimeIn', 'mapTimeOut'].forEach(id => {
      document.getElementById(id).innerHTML = uploadColumns.map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('');
    });
    document.getElementById('mapDept').innerHTML = '<option value="">-- بدون --</option>' +
      uploadColumns.map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('');
    document.getElementById('mappingBox').style.display = 'block';
  }
}

function onUploadFileChange() {
  document.getElementById('mappingBox').style.display = 'none';
  uploadCloudUrl = null;
  const f = document.getElementById('uploadFile').files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append('file', f);
  fetch('/api/upload', { method: 'POST', body: fd }).then(r => r.json()).then(_handleUploadPreview)
    .catch(() => toast('تعذّر رفع الملف', true));
}

function loadUploadFromUrl() {
  const url = document.getElementById('uploadUrl').value.trim();
  if (!url) { toast('يرجى إدخال رابط الملف', true); return; }
  document.getElementById('mappingBox').style.display = 'none';
  document.getElementById('uploadFile').value = '';
  uploadCloudUrl = url;
  const fd = new FormData();
  fd.append('cloud_url', url);
  fetch('/api/upload', { method: 'POST', body: fd }).then(r => r.json()).then(_handleUploadPreview)
    .catch(() => toast('تعذّر تحميل الملف من الرابط', true));
}

function doUpload() {
  const f = document.getElementById('uploadFile').files[0];
  if (!f && !uploadCloudUrl) { toast('يرجى اختيار ملف أو إدخال رابط أولاً', true); return; }
  const fd = new FormData();
  if (f) fd.append('file', f); else fd.append('cloud_url', uploadCloudUrl);
  fd.append('name_col', document.getElementById('mapName').value);
  fd.append('date_col', document.getElementById('mapDate').value);
  fd.append('time_in_col', document.getElementById('mapTimeIn').value);
  fd.append('time_out_col', document.getElementById('mapTimeOut').value);
  fd.append('dept_col', document.getElementById('mapDept').value);
  fetch('/api/upload', { method: 'POST', body: fd }).then(r => r.json()).then(data => {
    if (!data.ok) { toast(data.error || 'فشل الاستيراد', true); return; }
    toast(`تم استيراد ${data.imported} سجلاً بنجاح`);
    if (data.warning) toast(data.warning, true);
    document.getElementById('mappingBox').style.display = 'none';
    document.getElementById('uploadFile').value = '';
    document.getElementById('uploadUrl').value = '';
    uploadCloudUrl = null;
  }).catch(() => toast('تعذّر رفع الملف', true));
}

async function runAnalyze() {
  const box = document.getElementById('analyzeResult');
  box.innerHTML = '<span class="spinner"></span> جارٍ التحليل...';
  try {
    const data = await api('/api/analyze', { method: 'POST' });
    box.innerHTML = `<div class="alert alert-success">تم التحليل بنجاح - ${data.rows} سجل جاهز في تبويب التقارير.</div>`;
    toast('تم التحليل بنجاح');
    loadMetaInto();
  } catch (e) {
    box.innerHTML = '<div class="alert alert-error">فشل التحليل - راجع الرسالة أعلى الصفحة.</div>';
  }
}

async function clearPunches() {
  if (!confirm('سيتم حذف كل البيانات المرفوعة ونتائج التحليل الحالية. متابعة؟')) return;
  await api('/api/punches/clear', { method: 'POST' });
  toast('تم مسح البيانات');
  document.getElementById('analyzeResult').innerHTML = '';
}

/* ============ REPORTS ============ */
function setReportType(rt) {
  reportState.type = rt;
  reportState.page = 1;
  document.querySelectorAll('#tab-reports .filter-btn').forEach(b => b.classList.toggle('active', b.dataset.rt === rt));
  loadReports(1);
}

function sortReports(col) {
  if (reportState.sort === col) {
    reportState.dir = reportState.dir === 'asc' ? 'desc' : 'asc';
  } else {
    reportState.sort = col;
    reportState.dir = 'asc';
  }
  document.querySelectorAll('#tab-reports [id^="repArrow-"]').forEach(s => s.textContent = '');
  const arrow = document.getElementById('repArrow-' + col);
  if (arrow) arrow.textContent = reportState.dir === 'asc' ? ' ▲' : ' ▼';
  loadReports(reportState.page);
}

function repParams(page) {
  const p = new URLSearchParams();
  p.set('report_type', reportState.type);
  p.set('page', page);
  p.set('page_size', 50);
  if (reportState.sort) { p.set('sort', reportState.sort); p.set('dir', reportState.dir); }
  const dept = document.getElementById('repDept').value;
  // ===== repEmployee صار قائمة متعددة الاختيار (multi-select) - نجمع كل
  // الأسماء المحدَّدة معاً كقائمة employees مفصولة بفاصلة، بدل موظف واحد
  // فقط - بدون أي تحديد = كل الموظفين (نفس السلوك السابق) =====
  const empSelected = Array.from(document.getElementById('repEmployee').selectedOptions).map(o => o.value).filter(Boolean);
  const from = document.getElementById('repFrom').value;
  const to = document.getElementById('repTo').value;
  const q = document.getElementById('repSearch').value;
  if (dept) p.set('dept', dept);
  if (empSelected.length) p.set('employees', empSelected.join(','));
  if (from) p.set('date_from', from);
  if (to) p.set('date_to', to);
  if (q) p.set('q', q);
  return p;
}

const STATUS_BADGE = {
  'في الوقت': 'badge-ontime', 'متأخر': 'badge-late', 'تأخير بسيط': 'badge-late',
  'غائب': 'badge-absent', 'عطلة أسبوعية': 'badge-holiday', 'عطلة رسمية': 'badge-official',
  'استثناء': 'badge-exception', 'بدون سجل دخول': 'badge-none',
};

// ===== حالات يمكن النقر على شارتها بجدول التقارير لفتح تبويب تسجيل
// الحدث مباشرة (إذن تأخير/سبب غياب) - بدل الاضطرار للبحث عن نفس الموظف/
// التاريخ يدوياً في تبويب آخر، تماماً كسلوك النسخة المكتبية (home.py) عند
// النقر على هذه الحالات بجدول النتائج =====
const _CLICKABLE_REPORT_STATUSES = { 'متأخر': 'late', 'تأخير بسيط': 'late', 'غائب': 'absent' };

function _reportStatusCell(r) {
  const badge = `<span class="badge ${STATUS_BADGE[r.status] || 'badge-none'}">${escapeHtml(r.status)}</span>`;
  const kind = _CLICKABLE_REPORT_STATUSES[r.status];
  if (!kind) return badge;
  return `<span style="cursor:pointer" title="اضغط لتسجيل ${kind === 'late' ? 'إذن تأخير' : 'سبب غياب'} لهذا السجل" ` +
    `onclick="registerReportEvent('${kind}', '${escapeHtml(r.name).replace(/'/g, "\\'")}', '${r.date}')">${badge} <i class="fas fa-pen" style="font-size:.75em;color:var(--muted)" aria-hidden="true"></i></span>`;
}

// ===== صندوق "تسجيل حدث" السريع - يُفتَح مباشرة بالضغط على كلمة "متأخر"/
// "غائب" بجدول التقارير (بدل الانتقال لتبويب آخر والبحث عن نفس الموظف/
// التاريخ يدوياً). يعرض قائمة أسباب سبق إدخالها فعلياً (من late_permissions/
// absence_reasons) لاختيار سريع، مع خيار "سبب جديد (اكتب يدوياً)" ===== */
let _EVT_MODAL_CTX = null; // {kind, name, date}

function registerReportEvent(kind, name, date) {
  _EVT_MODAL_CTX = { kind, name, date };
  document.getElementById('eventModalTitle').textContent = kind === 'late' ? 'تسجيل إذن تأخير' : 'تسجيل سبب غياب';
  document.getElementById('eventModalEmpName').textContent = name;
  document.getElementById('eventModalDate').textContent = date;
  document.getElementById('eventModalResult').innerHTML = '';

  const lateFields = document.getElementById('eventModalLateFields');
  const absentFields = document.getElementById('eventModalAbsentFields');
  lateFields.style.display = kind === 'late' ? 'block' : 'none';
  absentFields.style.display = kind === 'absent' ? 'block' : 'none';

  if (kind === 'late') {
    _fillReasonSelect('evtLateReasonSelect', LATE_LABELS);
    document.getElementById('evtLateManualLabel').value = '';
    document.getElementById('evtLateManualWrap').style.display = LATE_LABELS.length ? 'none' : 'block';
    document.getElementById('evtLateMinutes').value = '';
    document.getElementById('evtLateCustomAtt').value = '';
  } else {
    _fillReasonSelect('evtAbsentReasonSelect', ABSENCE_REASON_OPTIONS);
    document.getElementById('evtAbsentManualLabel').value = '';
    document.getElementById('evtAbsentManualWrap').style.display = ABSENCE_REASON_OPTIONS.length ? 'none' : 'block';
  }
  document.getElementById('eventModalOverlay').classList.add('open');
}

function _fillReasonSelect(selectId, options) {
  const el = document.getElementById(selectId);
  const optsHtml = options.map(o => `<option value="${escapeHtml(o)}">${escapeHtml(o)}</option>`).join('');
  el.innerHTML = optsHtml + `<option value="__manual__">➕ سبب جديد (اكتب يدوياً)</option>`;
}

function _onEvtReasonSelectChange(kind) {
  if (kind === 'late') {
    const isManual = document.getElementById('evtLateReasonSelect').value === '__manual__';
    document.getElementById('evtLateManualWrap').style.display = isManual ? 'block' : 'none';
  } else {
    const isManual = document.getElementById('evtAbsentReasonSelect').value === '__manual__';
    document.getElementById('evtAbsentManualWrap').style.display = isManual ? 'block' : 'none';
  }
}

function closeEventModal() {
  document.getElementById('eventModalOverlay').classList.remove('open');
  _EVT_MODAL_CTX = null;
}

async function saveEventModal() {
  if (!_EVT_MODAL_CTX) return;
  const { kind, name, date } = _EVT_MODAL_CTX;
  const resultEl = document.getElementById('eventModalResult');
  try {
    if (kind === 'late') {
      const select = document.getElementById('evtLateReasonSelect');
      const label = select.value === '__manual__' ? document.getElementById('evtLateManualLabel').value.trim() : select.value;
      const minutes = document.getElementById('evtLateMinutes').value;
      const customAtt = document.getElementById('evtLateCustomAtt').value;
      if (!minutes && !customAtt) {
        resultEl.innerHTML = '<div class="alert alert-error">يرجى تحديد عدد الدقائق أو وقت حضور مخصّص</div>';
        return;
      }
      await api('/api/late-permissions', {
        method: 'POST',
        body: JSON.stringify({ name, date, minutes, custom_attendance_time: customAtt, label }),
      });
      toast('تم حفظ إذن التأخير - لا تنسَ تشغيل "تحليل البيانات" لتحديث التقرير');
    } else {
      const select = document.getElementById('evtAbsentReasonSelect');
      const reason = select.value === '__manual__' ? document.getElementById('evtAbsentManualLabel').value.trim() : select.value;
      if (!reason) {
        resultEl.innerHTML = '<div class="alert alert-error">يرجى اختيار سبب أو كتابته</div>';
        return;
      }
      await api('/api/absence-reasons', { method: 'POST', body: JSON.stringify({ name, date, reason }) });
      toast('تم حفظ سبب الغياب');
    }
    closeEventModal();
    loadMetaInto(); // لتحديث قوائم الأسباب السابقة بإضافة السبب الجديد لو كان يدوياً
    if (currentTab === 'reports') loadReports(reportState.page);
  } catch (e) {
    resultEl.innerHTML = `<div class="alert alert-error">${escapeHtml(e.message || 'حدث خطأ غير متوقع')}</div>`;
  }
}

async function loadReports(page) {
  reportState.page = page || 1;
  const data = await api('/api/reports?' + repParams(reportState.page).toString());
  if (!data) return;
  const tbody = document.getElementById('reportsTable');
  if (!data.rows.length) {
    tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--muted);padding:24px">⚠️ لا توجد سجلات مطابقة</td></tr>';
  } else {
    tbody.innerHTML = data.rows.map(r => `
      <tr>
        <td>${escapeHtml(r.name)}</td>
        <td>${escapeHtml(r.dept || '')}</td>
        <td>${escapeHtml(r.date)}</td>
        <td>${escapeHtml(r.time_in || '—')}</td>
        <td>${escapeHtml(r.time_out || '—')}</td>
        <td>${_reportStatusCell(r)}</td>
        <td>${r.late_minutes || 0}</td>
        <td>${r.working_hours || 0}</td>
        <td>${escapeHtml(r.shift || '—')}</td>
      </tr>`).join('');
  }
  renderPagination(data.total, data.page, data.page_size);
}

function renderPagination(total, page, pageSize) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const el = document.getElementById('reportsPagination');
  if (totalPages <= 1) { el.innerHTML = `<span style="color:var(--muted);font-size:.85rem">${total} سجل</span>`; return; }
  let html = `<button ${page <= 1 ? 'disabled' : ''} onclick="loadReports(${page - 1})" aria-label="الصفحة السابقة" title="الصفحة السابقة"><i class="fas fa-chevron-right" aria-hidden="true"></i></button>`;
  const startP = Math.max(1, page - 2), endP = Math.min(totalPages, page + 2);
  for (let i = startP; i <= endP; i++) {
    html += `<button class="${i === page ? 'active' : ''}" onclick="loadReports(${i})">${i}</button>`;
  }
  html += `<button ${page >= totalPages ? 'disabled' : ''} onclick="loadReports(${page + 1})"><i class="fas fa-chevron-left" aria-hidden="true"></i></button>`;
  html += `<span style="color:var(--muted);font-size:.85rem;margin-inline-start:8px">${total} سجل إجمالاً</span>`;
  el.innerHTML = html;
}

function exportReportsCSV() {
  window.location = '/api/reports/export.csv?' + repParams(1).toString();
}

function exportReportsPDF() {
  window.location = '/api/reports/export.pdf?' + repParams(1).toString();
}

/* ============ تصدير مستقل ============ */
function expParams() {
  const p = new URLSearchParams();
  const dept = document.getElementById('expDept').value;
  const emp = document.getElementById('expEmployee').value;
  const from = document.getElementById('expFrom').value;
  const to = document.getElementById('expTo').value;
  if (dept) p.set('dept', dept);
  if (emp) p.set('employee', emp);
  if (from) p.set('date_from', from);
  if (to) p.set('date_to', to);
  return p;
}

function exportExcelMultiSheet() {
  window.location = '/api/export/excel?' + expParams().toString();
}

async function sendExportEmailNow(btn) {
  if (btn) btn.disabled = true;
  const resultEl = document.getElementById('expResult');
  resultEl.innerHTML = '<p style="color:var(--muted)"><i class="fas fa-spinner fa-spin" aria-hidden="true"></i> جارٍ الإرسال...</p>';
  const body = {
    dept: document.getElementById('expDept').value,
    employee: document.getElementById('expEmployee').value,
    date_from: document.getElementById('expFrom').value,
    date_to: document.getElementById('expTo').value,
    report_type: document.getElementById('expReportType').value,
  };
  try {
    const data = await api('/api/export/send-email', { method: 'POST', body: JSON.stringify(body) });
    if (data) {
      resultEl.innerHTML = `<p style="color:var(--success,#0a6640)"><i class="fas fa-check-circle" aria-hidden="true"></i> ${escapeHtml(data.message)}</p>`;
      toast(data.message);
    }
  } catch (e) {
    resultEl.innerHTML = `<p style="color:#c0392b"><i class="fas fa-times-circle" aria-hidden="true"></i> ${escapeHtml(e.message)}</p>`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

/* ============ OVERTIME ============ */
let lastOvertimeRows = [];

function otPayload() {
  const namesEl = document.getElementById('otNames');
  const names = Array.from(namesEl.selectedOptions).map(o => o.value);
  return {
    names,
    date_from: document.getElementById('otFrom').value,
    date_to: document.getElementById('otTo').value,
    grace_minutes: parseInt(document.getElementById('otGrace').value || '0', 10),
    use_custom_hours: document.getElementById('otUseCustom').checked,
    custom_end: document.getElementById('otCustomEnd').value,
  };
}

async function calcOvertime() {
  const payload = otPayload();
  if (!payload.names.length) { toast('اختر موظفاً واحداً على الأقل', true); return; }
  let data;
  try {
    data = await api('/api/overtime', { method: 'POST', body: JSON.stringify(payload) });
  } catch (e) { return; }
  if (!data) return;
  lastOvertimeRows = data.rows;

  document.getElementById('otSummaryCards').style.display = '';
  document.getElementById('otInstances').textContent = data.summary.instances;
  document.getElementById('otTotalDuration').textContent = data.summary.total_duration;
  document.getElementById('otTopEmployee').textContent = data.summary.top_employee
    ? `${data.summary.top_employee} (${data.summary.top_employee_duration})` : '—';

  const tbody = document.getElementById('otTable');
  if (!data.rows.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:16px">⚠️ لا يوجد عمل إضافي ضمن المعايير المحددة</td></tr>';
    return;
  }
  tbody.innerHTML = data.rows.map(r => `
    <tr>
      <td>${escapeHtml(r.name)}</td>
      <td>${escapeHtml(r.dept || '')}</td>
      <td>${escapeHtml(r.date)}</td>
      <td>${escapeHtml(r.time_out)}</td>
      <td>${escapeHtml(r.scheduled_end)}</td>
      <td>${escapeHtml(r.ot_duration)}</td>
      <td>${r.is_weekend ? '<span class="badge badge-holiday">نعم</span>' : '—'}</td>
    </tr>`).join('');
}

async function exportOvertimeCSV() {
  const payload = otPayload();
  if (!payload.names.length) { toast('اختر موظفاً واحداً على الأقل', true); return; }
  try {
    const res = await fetch('/api/overtime/export.csv', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    if (res.status === 401) { window.location.href = '/login'; return; }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `overtime_report_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (e) {
    toast('تعذّر تصدير الملف', true);
  }
}

/* ============ COMPARISONS ============ */
let compareCriterion = 'dept';
const COMPARE_CAPTIONS = {
  dept: 'مقارنة الأقسام من حيث متوسط التأخير ونسبة الالتزام بالوقت.',
  employee: 'مقارنة الموظفين (أعلى 15 من حيث متوسط التأخير) من حيث التأخير والالتزام.',
  day: 'هل يوم معيّن بالأسبوع أكثر تأخيراً أو التزاماً من غيره؟',
  week: 'هل الوضع يتحسن أو يسوء أسبوعاً بعد أسبوع؟',
  month: 'نفس المقارنة على مستوى شهري.',
};

function setCompareCriterion(cr) {
  compareCriterion = cr;
  document.querySelectorAll('#tab-compare .filter-btn').forEach(b => b.classList.toggle('active', b.dataset.cr === cr));
  document.getElementById('cmpCaption').textContent = COMPARE_CAPTIONS[cr] || '';
  loadCompare();
}

function clearCompareFilters() {
  document.getElementById('cmpFrom').value = '';
  document.getElementById('cmpTo').value = '';
  loadCompare();
}

async function loadCompare() {
  const p = new URLSearchParams();
  p.set('criterion', compareCriterion);
  const from = document.getElementById('cmpFrom').value;
  const to = document.getElementById('cmpTo').value;
  if (from) p.set('date_from', from);
  if (to) p.set('date_to', to);

  const data = await api('/api/compare?' + p.toString());
  if (!data) return;
  if (!data.labels.length) {
    document.getElementById('cmpChartLate').innerHTML = '<p style="color:var(--muted);text-align:center;padding:20px">⚠️ لا توجد بيانات مطابقة (شغّل "تحليل البيانات" أولاً إن لم تفعل)</p>';
    document.getElementById('cmpChartOntime').innerHTML = '';
    return;
  }
  renderBarChart('cmpChartLate', data.labels, data.avg_late, { color: '#e34948', suffix: ' د' });
  renderBarChart('cmpChartOntime', data.labels, data.ontime_pct, { color: '#1baf7a', suffix: '%', max: 100 });
}

/* رسم بياني شريطي بسيط (SVG بدون أي مكتبة خارجية) - أعمدة رفيعة بأطراف
   دائرية، مع تسمية القيمة مباشرة فوق كل عمود، وتلميح (tooltip) عند
   المرور بالفأرة. مناسب لمقارنة حتى ~15 فئة بوضوح. */
function renderBarChart(containerId, labels, values, opts) {
  const el = document.getElementById(containerId);
  const color = opts.color || '#2a78d6';
  const suffix = opts.suffix || '';
  const maxVal = opts.max || Math.max(1, ...values) * 1.15;
  const barW = 34, gap = 18, chartH = 220, labelH = 46;
  const w = Math.max(el.clientWidth || 600, labels.length * (barW + gap) + gap);
  const h = chartH + labelH;

  let bars = '';
  labels.forEach((label, i) => {
    const x = gap + i * (barW + gap);
    const val = values[i] || 0;
    const barH = maxVal > 0 ? (val / maxVal) * chartH : 0;
    const y = chartH - barH;
    bars += `
      <g class="cmp-bar">
        <rect x="${x}" y="${y}" width="${barW}" height="${Math.max(barH, 2)}" rx="4" fill="${color}">
          <title>${escapeHtml(label)}: ${val}${suffix}</title>
        </rect>
        <text x="${x + barW / 2}" y="${y - 6}" text-anchor="middle" font-size="11" fill="var(--text)">${val}${suffix}</text>
        <text x="${x + barW / 2}" y="${chartH + 16}" text-anchor="middle" font-size="10" fill="var(--muted)"
              transform="rotate(-35 ${x + barW / 2} ${chartH + 16})">${escapeHtml(truncateLabel(label))}</text>
      </g>`;
  });

  el.innerHTML = `<div style="overflow-x:auto"><svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="min-width:100%">
    <line x1="0" y1="${chartH}" x2="${w}" y2="${chartH}" stroke="var(--muted)" stroke-width="1" opacity="0.3"/>
    ${bars}
  </svg></div>`;
}

function truncateLabel(s, max) {
  max = max || 14;
  s = String(s);
  return s.length > max ? s.slice(0, max - 1) + '…' : s;
}

/* ============ BLUEPRINT ============ */

/* ألوان الحالات - مأخوذة بترتيب ثابت من نفس النظام اللوني الفئوي المستخدَم
   ببقية الرسوم (renderBarChart)، مع تعيين كل حالة بلون ثابت (لا يتغيّر
   بتغيّر الفلتر) حتى تبقى الهوية اللونية مستقرة بين تحميلة وأخرى. */
const STATUS_PIE_COLORS = {
  'عطلة أسبوعية': '#2a78d6',
  'متأخر': '#eb6834',
  'في الوقت': '#1baf7a',
  'تأخير بسيط': '#eda100',
  'استثناء': '#e87ba4',
  'بدون سجل دخول': '#008300',
  'عطلة رسمية': '#4a3aa7',
  'غائب': '#e34948',
};
const STATUS_PIE_ORDER = Object.keys(STATUS_PIE_COLORS);

function clearBlueprintFilters() {
  document.getElementById('bpFrom').value = '';
  document.getElementById('bpTo').value = '';
  loadBlueprint();
}

async function loadBlueprint() {
  const p = new URLSearchParams();
  const from = document.getElementById('bpFrom').value;
  const to = document.getElementById('bpTo').value;
  if (from) p.set('date_from', from);
  if (to) p.set('date_to', to);

  const data = await api('/api/blueprint?' + p.toString());
  if (!data) return;
  if (data.empty) {
    document.getElementById('bpEmpty').style.display = '';
    document.getElementById('bpContent').style.display = 'none';
    return;
  }
  document.getElementById('bpEmpty').style.display = 'none';
  document.getElementById('bpContent').style.display = '';

  document.getElementById('bpTotal').textContent = data.kpis.total;
  document.getElementById('bpOntimePct').textContent = data.kpis.ontime_pct + '%';
  document.getElementById('bpLatePct').textContent = data.kpis.late_pct + '%';
  document.getElementById('bpAvgHours').textContent = data.kpis.avg_hours;
  document.getElementById('bpAvgLate').textContent = data.kpis.avg_late;

  renderPieChart('bpStatusPie', data.status_counts);
  renderLineChart('bpDailyPresent', data.daily_present.labels, data.daily_present.values, { color: '#2a78d6', suffix: '' });
  renderLineChart('bpDailyLate', data.daily_late.labels, data.daily_late.values, { color: '#e34948', suffix: ' د' });
  renderHBarChart('bpTopDepts', data.top_depts, { color: '#eb6834', suffix: ' د' });
  renderHBarChart('bpTopEmployees', data.top_employees, { color: '#e34948', suffix: ' د' });
}

/* رسم دائري (Donut) لتوزيع الحالات - بترتيب فئوي ثابت (نفس الحالة = نفس
   اللون دائماً)، مع تسمية مباشرة (قيمة + نسبة) بجانب كل شريحة بدل الاعتماد
   على اللون وحده للتمييز، وإجمالي السجلات بمنتصف الحلقة. */
function renderPieChart(containerId, counts) {
  const el = document.getElementById(containerId);
  const entries = STATUS_PIE_ORDER.filter(s => counts[s]).map(s => ({ label: s, value: counts[s], color: STATUS_PIE_COLORS[s] }));
  const total = entries.reduce((a, e) => a + e.value, 0);
  if (!total) {
    el.innerHTML = '<p style="color:var(--muted);padding:10px">لا توجد بيانات</p>';
    return;
  }
  const cx = 90, cy = 90, r = 70, rInner = 40;
  let angle = -90;
  let paths = '';
  entries.forEach(e => {
    const frac = e.value / total;
    const sweep = Math.max(frac * 360, 0.0001);
    const large = sweep > 180 ? 1 : 0;
    const a0 = angle * Math.PI / 180, a1 = (angle + sweep) * Math.PI / 180;
    const x0 = cx + r * Math.cos(a0), y0 = cy + r * Math.sin(a0);
    const x1 = cx + r * Math.cos(a1), y1 = cy + r * Math.sin(a1);
    const xi0 = cx + rInner * Math.cos(a1), yi0 = cy + rInner * Math.sin(a1);
    const xi1 = cx + rInner * Math.cos(a0), yi1 = cy + rInner * Math.sin(a0);
    paths += `<path d="M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${x1.toFixed(2)} ${y1.toFixed(2)} L ${xi0.toFixed(2)} ${yi0.toFixed(2)} A ${rInner} ${rInner} 0 ${large} 0 ${xi1.toFixed(2)} ${yi1.toFixed(2)} Z" fill="${e.color}" stroke="var(--card-bg,#fff)" stroke-width="2">
      <title>${escapeHtml(e.label)}: ${e.value} (${Math.round(frac * 100)}%)</title>
    </path>`;
    angle += sweep;
  });
  const legend = entries.map(e => `
    <div style="display:flex;align-items:center;gap:6px;font-size:13px">
      <span style="width:12px;height:12px;border-radius:3px;background:${e.color};display:inline-block;flex-shrink:0"></span>
      <span style="color:var(--text)">${escapeHtml(e.label)}</span>
      <span style="color:var(--muted)">${e.value} (${Math.round(e.value / total * 100)}%)</span>
    </div>`).join('');
  el.innerHTML = `
    <svg width="180" height="180" viewBox="0 0 180 180" style="flex-shrink:0">${paths}
      <text x="${cx}" y="${cy}" text-anchor="middle" dominant-baseline="middle" font-size="16" font-weight="700" fill="var(--text)">${total}</text>
    </svg>
    <div style="display:flex;flex-direction:column;gap:6px;justify-content:center">${legend}</div>`;
}

/* رسم خطي بسيط لاتجاه يومي (عدد الحاضرين / متوسط التأخير)، مع نقطة قابلة
   للتحويم عند كل يوم تعرض القيمة كاملة، ومساحة مظللة أسفل الخط لتوضيح
   الاتجاه العام دون تشتيت. */
function renderLineChart(containerId, labels, values, opts) {
  opts = opts || {};
  const el = document.getElementById(containerId);
  const color = opts.color || '#2a78d6';
  const suffix = opts.suffix || '';
  if (!labels.length) {
    el.innerHTML = '<p style="color:var(--muted);text-align:center;padding:20px">لا توجد بيانات كافية</p>';
    return;
  }
  const chartH = 160, padTop = 20, padBottom = 34, padSide = 14;
  const stepMin = 46;
  const w = Math.max(el.clientWidth || 600, labels.length * stepMin + padSide * 2);
  const h = chartH + padTop + padBottom;
  const maxVal = opts.max || Math.max(1, ...values) * 1.15;
  const stepX = labels.length > 1 ? (w - padSide * 2) / (labels.length - 1) : 0;
  const points = values.map((v, i) => {
    const x = padSide + i * stepX;
    const y = padTop + chartH - (maxVal > 0 ? (v / maxVal) * chartH : 0);
    return { x, y, v };
  });
  const linePath = points.map((pt, i) => (i === 0 ? 'M' : 'L') + pt.x.toFixed(1) + ' ' + pt.y.toFixed(1)).join(' ');
  const lastX = points[points.length - 1].x.toFixed(1);
  const firstX = points[0].x.toFixed(1);
  const areaPath = `${linePath} L ${lastX} ${padTop + chartH} L ${firstX} ${padTop + chartH} Z`;
  const dots = points.map((pt, i) => `
    <circle cx="${pt.x.toFixed(1)}" cy="${pt.y.toFixed(1)}" r="4" fill="${color}">
      <title>${escapeHtml(labels[i])}: ${pt.v}${suffix}</title>
    </circle>`).join('');
  const everyNth = Math.max(1, Math.ceil(labels.length / 10));
  const xLabels = points.map((pt, i) => i % everyNth === 0
    ? `<text x="${pt.x.toFixed(1)}" y="${padTop + chartH + 20}" text-anchor="middle" font-size="10" fill="var(--muted)">${escapeHtml((labels[i] || '').slice(5))}</text>`
    : '').join('');
  el.innerHTML = `<div style="overflow-x:auto"><svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="min-width:100%">
    <line x1="0" y1="${padTop + chartH}" x2="${w}" y2="${padTop + chartH}" stroke="var(--muted)" stroke-width="1" opacity="0.3"/>
    <path d="${areaPath}" fill="${color}" opacity="0.12"/>
    <path d="${linePath}" fill="none" stroke="${color}" stroke-width="2"/>
    ${dots}
    ${xLabels}
  </svg></div>`;
}

/* رسم شريطي أفقي (Top 10) - تسمية الفئة يميناً وقيمتها بجانب الشريط، مناسب
   لعرض أسماء أقسام/موظفين طويلة نسبياً بدون تشويه أو تدوير النص. */
function renderHBarChart(containerId, items, opts) {
  opts = opts || {};
  const el = document.getElementById(containerId);
  const color = opts.color || '#2a78d6';
  const suffix = opts.suffix || '';
  if (!items || !items.length) {
    el.innerHTML = '<p style="color:var(--muted);text-align:center;padding:20px">لا توجد بيانات</p>';
    return;
  }
  const maxVal = Math.max(1, ...items.map(it => it.value)) * 1.1;
  const barH = 22, gap = 10, labelW = 150;
  const w = Math.max(el.clientWidth || 500, 460);
  const chartW = w - labelW - 60;
  const h = items.length * (barH + gap) + gap;
  let bars = '';
  items.forEach((it, i) => {
    const y = gap + i * (barH + gap);
    const bw = maxVal > 0 ? (it.value / maxVal) * chartW : 0;
    bars += `
      <text x="${labelW - 10}" y="${y + barH / 2 + 4}" text-anchor="end" font-size="12" fill="var(--text)">${escapeHtml(truncateLabel(it.label, 20))}<title>${escapeHtml(it.label)}</title></text>
      <rect x="${labelW}" y="${y}" width="${Math.max(bw, 2)}" height="${barH}" rx="4" fill="${color}">
        <title>${escapeHtml(it.label)}: ${it.value}${suffix}</title>
      </rect>
      <text x="${labelW + Math.max(bw, 2) + 8}" y="${y + barH / 2 + 4}" font-size="12" fill="var(--text)">${it.value}${suffix}</text>`;
  });
  el.innerHTML = `<div style="overflow-x:auto"><svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="min-width:100%">${bars}</svg></div>`;
}

/* ============ MANUAL ENTRIES ============ */
async function saveManualEntry() {
  const payload = {
    name: document.getElementById('manName').value.trim(),
    date: document.getElementById('manDate').value,
    time_in: document.getElementById('manTimeIn').value,
    time_out: document.getElementById('manTimeOut').value,
    reason: document.getElementById('manReason').value.trim(),
  };
  try {
    await api('/api/manual-entries', { method: 'POST', body: JSON.stringify(payload) });
    toast('تم حفظ الإدخال اليدوي - لا تنسَ تشغيل "تحليل البيانات" لتحديث التقرير');
    document.getElementById('manReason').value = '';
    loadManualEntries();
  } catch (e) {}
}

async function loadManualEntries() {
  const data = await api('/api/manual-entries');
  if (!data) return;
  const tbody = document.getElementById('manualTable');
  tbody.innerHTML = data.rows.map(r => `
    <tr>
      <td><input type="checkbox" class="row-check" data-id="${r.id}"></td>
      <td>${escapeHtml(r.name)}</td><td>${escapeHtml(r.date)}</td>
      <td>${escapeHtml(r.time_in || '—')}</td><td>${escapeHtml(r.time_out || '—')}</td>
      <td>${escapeHtml(r.reason)}</td><td>${escapeHtml(r.entered_at)}</td>
      <td><button class="btn btn-red btn-sm" onclick="deleteManualEntry(${r.id})" aria-label="حذف" title="حذف"><i class="fas fa-trash" aria-hidden="true"></i></button></td>
    </tr>`).join('') || '<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:16px">لا توجد إدخالات يدوية</td></tr>';
}

async function deleteManualEntry(id) {
  if (!confirm('حذف هذا الإدخال اليدوي؟')) return;
  await api('/api/manual-entries/' + id, { method: 'DELETE' });
  toast('تم الحذف');
  loadManualEntries();
}

/* ============ DATE EXCEPTIONS ============ */
async function saveDateException() {
  const payload = {
    name: document.getElementById('excName').value.trim(),
    date: document.getElementById('excDate').value,
    reason: document.getElementById('excReason').value.trim(),
  };
  if (!payload.name || !payload.date) { toast('الاسم والتاريخ حقلان إجباريان', true); return; }
  try {
    await api('/api/date-exceptions', { method: 'POST', body: JSON.stringify(payload) });
    toast('تم حفظ الاستثناء - لا تنسَ تشغيل "تحليل البيانات" لتحديث التقرير');
    document.getElementById('excName').value = '';
    document.getElementById('excDate').value = '';
    document.getElementById('excReason').value = '';
    loadDateExceptions();
  } catch (e) {}
}

function excBulkPayload() {
  const names = Array.from(document.getElementById('excBulkNames').selectedOptions).map(o => o.value);
  return {
    names,
    date_from: document.getElementById('excBulkFrom').value,
    date_to: document.getElementById('excBulkTo').value,
    reason: document.getElementById('excBulkReason').value.trim(),
  };
}

async function applyBulkException() {
  const payload = excBulkPayload();
  const box = document.getElementById('excBulkResult');
  if (!payload.names.length) { toast('اختر موظفاً واحداً على الأقل', true); return; }
  if (!payload.date_from || !payload.date_to) { toast('حدّد بداية ونهاية الفترة', true); return; }
  try {
    const data = await api('/api/date-exceptions/bulk', { method: 'POST', body: JSON.stringify(payload) });
    box.innerHTML = `<div class="alert alert-success">تم تسجيل ${data.count} استثناء (${payload.names.length} موظف × الفترة المحددة) - لا تنسَ تشغيل "تحليل البيانات".</div>`;
    toast('تم تطبيق الإجازة الجماعية');
    loadDateExceptions();
  } catch (e) {
    box.innerHTML = '<div class="alert alert-error">فشل تطبيق الإجازة الجماعية.</div>';
  }
}

async function cancelBulkException() {
  const payload = excBulkPayload();
  const box = document.getElementById('excBulkResult');
  if (!payload.names.length) { toast('اختر موظفاً واحداً على الأقل', true); return; }
  if (!payload.date_from || !payload.date_to) { toast('حدّد بداية ونهاية الفترة', true); return; }
  if (!confirm('إلغاء الاستثناءات المسجَّلة لهؤلاء الموظفين خلال هذه الفترة؟')) return;
  try {
    const data = await api('/api/date-exceptions/bulk-cancel', { method: 'POST', body: JSON.stringify(payload) });
    box.innerHTML = `<div class="alert alert-success">تم حذف ${data.deleted} استثناء.</div>`;
    toast('تم الإلغاء');
    loadDateExceptions();
  } catch (e) {
    box.innerHTML = '<div class="alert alert-error">فشل الإلغاء.</div>';
  }
}

async function loadDateExceptions() {
  const data = await api('/api/date-exceptions');
  if (!data) return;
  const tbody = document.getElementById('exceptionsTable');
  tbody.innerHTML = data.rows.map(r => `
    <tr>
      <td><input type="checkbox" class="row-check" data-id="${r.id}"></td>
      <td>${escapeHtml(r.name)}</td><td>${escapeHtml(r.date)}</td><td>${escapeHtml(r.reason || '')}</td>
      <td><button class="btn btn-red btn-sm" onclick="deleteDateException(${r.id})" aria-label="حذف" title="حذف"><i class="fas fa-trash" aria-hidden="true"></i></button></td>
    </tr>`).join('') || '<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:16px">لا توجد استثناءات مسجَّلة</td></tr>';
  loadForcedAbsences();
}

async function deleteDateException(id) {
  if (!confirm('حذف هذا الاستثناء؟')) return;
  await api('/api/date-exceptions/' + id, { method: 'DELETE' });
  toast('تم الحذف');
  loadDateExceptions();
}

/* ============ FORCED ABSENCE ============ */
function faPayload() {
  const names = Array.from(document.getElementById('faNames').selectedOptions).map(o => o.value);
  return {
    names,
    date_from: document.getElementById('faFrom').value,
    date_to: document.getElementById('faTo').value,
    reason: document.getElementById('faReason').value.trim(),
  };
}

async function applyForcedAbsence() {
  const payload = faPayload();
  const box = document.getElementById('faResult');
  if (!payload.names.length) { toast('اختر موظفاً واحداً على الأقل', true); return; }
  if (!payload.date_from || !payload.date_to) { toast('حدّد بداية ونهاية الفترة', true); return; }
  try {
    const data = await api('/api/forced-absences/bulk', { method: 'POST', body: JSON.stringify(payload) });
    box.innerHTML = `<div class="alert alert-success">تم تسجيل ${data.count} حالة غياب إجباري - لا تنسَ تشغيل "تحليل البيانات".</div>`;
    toast('تم تسجيل الغياب الإجباري');
    loadForcedAbsences();
  } catch (e) {
    box.innerHTML = '<div class="alert alert-error">فشل تسجيل الغياب الإجباري.</div>';
  }
}

async function cancelForcedAbsence() {
  const payload = faPayload();
  const box = document.getElementById('faResult');
  if (!payload.names.length) { toast('اختر موظفاً واحداً على الأقل', true); return; }
  if (!payload.date_from || !payload.date_to) { toast('حدّد بداية ونهاية الفترة', true); return; }
  if (!confirm('إلغاء الغياب الإجباري المسجَّل لهؤلاء الموظفين خلال هذه الفترة؟')) return;
  try {
    const data = await api('/api/forced-absences/bulk-cancel', { method: 'POST', body: JSON.stringify(payload) });
    box.innerHTML = `<div class="alert alert-success">تم حذف ${data.deleted} حالة.</div>`;
    toast('تم الإلغاء');
    loadForcedAbsences();
  } catch (e) {
    box.innerHTML = '<div class="alert alert-error">فشل الإلغاء.</div>';
  }
}

async function loadForcedAbsences() {
  const data = await api('/api/forced-absences');
  if (!data) return;
  const tbody = document.getElementById('forcedAbsencesTable');
  tbody.innerHTML = data.rows.map(r => `
    <tr>
      <td><input type="checkbox" class="row-check" data-id="${r.id}"></td>
      <td>${escapeHtml(r.name)}</td><td>${escapeHtml(r.date)}</td><td>${escapeHtml(r.reason || '')}</td>
      <td><button class="btn btn-red btn-sm" onclick="deleteForcedAbsence(${r.id})" aria-label="حذف" title="حذف"><i class="fas fa-trash" aria-hidden="true"></i></button></td>
    </tr>`).join('') || '<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:16px">لا توجد حالات غياب إجباري مسجَّلة</td></tr>';
}

async function deleteForcedAbsence(id) {
  if (!confirm('حذف هذه الحالة؟')) return;
  await api('/api/forced-absences/' + id, { method: 'DELETE' });
  toast('تم الحذف');
  loadForcedAbsences();
}

/* ============ ABSENCE REASONS ============ */
function arRowKey(name, date) {
  return `${name}__${date}`;
}

async function loadAbsenceReasons() {
  const p = new URLSearchParams();
  const dept = document.getElementById('arDept').value;
  const emp = document.getElementById('arEmployee').value;
  const from = document.getElementById('arFrom').value;
  const to = document.getElementById('arTo').value;
  if (dept) p.set('dept', dept);
  if (emp) p.set('employee', emp);
  if (from) p.set('date_from', from);
  if (to) p.set('date_to', to);

  const data = await api('/api/absence-reasons?' + p.toString());
  if (!data) return;
  const tbody = document.getElementById('absenceReasonsTable');
  if (!data.rows.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:16px">⚠️ لا توجد حالات غياب مطابقة (شغّل "تحليل البيانات" أولاً إن لم تفعل)</td></tr>';
    return;
  }
  tbody.innerHTML = data.rows.map(r => {
    const key = arRowKey(r.name, r.date);
    return `
    <tr data-name="${escapeHtml(r.name)}" data-date="${escapeHtml(r.date)}">
      <td><input type="checkbox" class="row-check" data-name="${escapeHtml(r.name)}" data-date="${escapeHtml(r.date)}"></td>
      <td>${escapeHtml(r.name)}</td>
      <td>${escapeHtml(r.dept || '')}</td>
      <td>${escapeHtml(r.date)}</td>
      <td><input type="text" class="search-input" id="arReason-${escapeHtml(key)}" value="${escapeHtml(r.reason || '')}" placeholder="سبب الغياب (اختياري)"></td>
      <td style="white-space:nowrap">
        <button class="btn btn-primary btn-sm" onclick="saveAbsenceReason(this)" aria-label="حفظ" title="حفظ"><i class="fas fa-save" aria-hidden="true"></i></button>
        <button class="btn btn-red btn-sm" onclick="deleteAbsenceReason(this)" aria-label="حذف" title="حذف"><i class="fas fa-trash" aria-hidden="true"></i></button>
      </td>
    </tr>`;
  }).join('');
}

async function bulkDeleteAbsenceReasons() {
  await bulkDeleteSelected('absenceReasonsTable', null, loadAbsenceReasons, {
    customDelete: (cb) => api('/api/absence-reasons/delete', {
      method: 'POST', body: JSON.stringify({ name: cb.dataset.name, date: cb.dataset.date }),
    }),
  });
}

async function saveAbsenceReason(btn) {
  const tr = btn.closest('tr');
  const name = tr.dataset.name, date = tr.dataset.date;
  const reason = document.getElementById('arReason-' + arRowKey(name, date)).value.trim();
  if (!reason) { toast('أدخل نص السبب أولاً، أو استخدم زر الحذف لمسح سبب موجود', true); return; }
  try {
    await api('/api/absence-reasons', { method: 'POST', body: JSON.stringify({ name, date, reason }) });
    toast('تم حفظ سبب الغياب');
  } catch (e) {}
}

async function deleteAbsenceReason(btn) {
  const tr = btn.closest('tr');
  const name = tr.dataset.name, date = tr.dataset.date;
  try {
    await api('/api/absence-reasons/delete', { method: 'POST', body: JSON.stringify({ name, date }) });
    toast('تم حذف السبب');
    loadAbsenceReasons();
  } catch (e) {}
}

/* ============ OFFICIAL HOLIDAYS ============ */
async function saveHoliday() {
  const payload = {
    date: document.getElementById('holDate').value,
    label: document.getElementById('holLabel').value.trim(),
  };
  if (!payload.date) { toast('التاريخ إجباري', true); return; }
  try {
    await api('/api/official-holidays', { method: 'POST', body: JSON.stringify(payload) });
    toast('تم حفظ العطلة - لا تنسَ تشغيل "تحليل البيانات" لتحديث التقرير');
    document.getElementById('holDate').value = '';
    document.getElementById('holLabel').value = '';
    loadHolidays();
  } catch (e) {}
}

async function loadHolidays() {
  const data = await api('/api/official-holidays');
  if (!data) return;
  const tbody = document.getElementById('holidaysTable');
  tbody.innerHTML = data.rows.map(r => `
    <tr>
      <td><input type="checkbox" class="row-check" data-id="${encodeURIComponent(r.date)}"></td>
      <td>${escapeHtml(r.date)}</td><td>${escapeHtml(r.label || '')}</td>
      <td><button class="btn btn-red btn-sm" onclick="deleteHoliday('${encodeURIComponent(r.date)}')" aria-label="حذف" title="حذف"><i class="fas fa-trash" aria-hidden="true"></i></button></td>
    </tr>`).join('') || '<tr><td colspan="4" style="text-align:center;color:var(--muted);padding:16px">لا توجد عطل مسجَّلة</td></tr>';
}

async function deleteHoliday(dateEncoded) {
  if (!confirm('حذف هذه العطلة؟')) return;
  await api('/api/official-holidays/' + dateEncoded, { method: 'DELETE' });
  toast('تم الحذف');
  loadHolidays();
}

/* ============ LATE / DEPARTURE PERMISSIONS ============ */
async function saveLatePermission() {
  const payload = {
    name: document.getElementById('lpName').value.trim(),
    date: document.getElementById('lpDate').value,
    minutes: document.getElementById('lpMinutes').value,
    custom_attendance_time: document.getElementById('lpCustomAtt').value,
    label: document.getElementById('lpLabel').value.trim(),
  };
  if (!payload.name || !payload.date) { toast('الاسم والتاريخ حقلان إجباريان', true); return; }
  if (!payload.minutes && !payload.custom_attendance_time) { toast('يرجى تحديد عدد الدقائق أو وقت حضور مخصّص', true); return; }
  try {
    await api('/api/late-permissions', { method: 'POST', body: JSON.stringify(payload) });
    toast('تم حفظ إذن التأخير - لا تنسَ تشغيل "تحليل البيانات" لتحديث التقرير');
    document.getElementById('lpName').value = '';
    document.getElementById('lpDate').value = '';
    document.getElementById('lpMinutes').value = '';
    document.getElementById('lpCustomAtt').value = '';
    document.getElementById('lpLabel').value = '';
    loadPermissions();
  } catch (e) {}
}

async function saveDeparturePermission() {
  const payload = {
    name: document.getElementById('dpName').value.trim(),
    date: document.getElementById('dpDate').value,
    departure_time: document.getElementById('dpDeparture').value,
    return_time: document.getElementById('dpReturn').value,
    reason: document.getElementById('dpReason').value.trim(),
  };
  if (!payload.name || !payload.date || !payload.departure_time || !payload.return_time) {
    toast('الاسم والتاريخ ووقت المغادرة والعودة حقول إجبارية', true); return;
  }
  try {
    await api('/api/departure-permissions', { method: 'POST', body: JSON.stringify(payload) });
    toast('تم حفظ إذن المغادرة - لا تنسَ تشغيل "تحليل البيانات" لتحديث التقرير');
    document.getElementById('dpName').value = '';
    document.getElementById('dpDate').value = '';
    document.getElementById('dpDeparture').value = '';
    document.getElementById('dpReturn').value = '';
    document.getElementById('dpReason').value = '';
    loadPermissions();
  } catch (e) {}
}

async function loadPermissions() {
  const lp = await api('/api/late-permissions');
  if (lp) {
    const tbody = document.getElementById('latePermTable');
    tbody.innerHTML = lp.rows.map(r => `
      <tr>
        <td><input type="checkbox" class="row-check" data-id="${r.id}"></td>
        <td>${escapeHtml(r.name)}</td><td>${escapeHtml(r.date)}</td><td>${r.minutes || 0}</td>
        <td>${escapeHtml(r.custom_attendance_time || '—')}</td><td>${escapeHtml(r.label || '')}</td>
        <td><button class="btn btn-red btn-sm" onclick="deleteLatePermission(${r.id})" aria-label="حذف" title="حذف"><i class="fas fa-trash" aria-hidden="true"></i></button></td>
      </tr>`).join('') || '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:16px">لا توجد أذونات تأخير مسجَّلة</td></tr>';
  }

  const dp = await api('/api/departure-permissions');
  if (dp) {
    const tbody = document.getElementById('departPermTable');
    tbody.innerHTML = dp.rows.map(r => `
      <tr>
        <td><input type="checkbox" class="row-check" data-id="${r.id}"></td>
        <td>${escapeHtml(r.name)}</td><td>${escapeHtml(r.date)}</td>
        <td>${escapeHtml(r.departure_time)}</td><td>${escapeHtml(r.return_time)}</td><td>${escapeHtml(r.reason || '')}</td>
        <td><button class="btn btn-red btn-sm" onclick="deleteDeparturePermission(${r.id})" aria-label="حذف" title="حذف"><i class="fas fa-trash" aria-hidden="true"></i></button></td>
      </tr>`).join('') || '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:16px">لا توجد أذونات مغادرة مسجَّلة</td></tr>';
  }
}

async function deleteLatePermission(id) {
  if (!confirm('حذف إذن التأخير هذا؟')) return;
  await api('/api/late-permissions/' + id, { method: 'DELETE' });
  toast('تم الحذف');
  loadPermissions();
}

async function deleteDeparturePermission(id) {
  if (!confirm('حذف إذن المغادرة هذا؟')) return;
  await api('/api/departure-permissions/' + id, { method: 'DELETE' });
  toast('تم الحذف');
  loadPermissions();
}

/* ============ AUDIT LOG ============ */
const AUDIT_ACTION_LABELS = {
  create: 'إضافة', update: 'تعديل', delete: 'حذف', login: 'تسجيل دخول', login_failed: 'محاولة دخول فاشلة',
  backup: 'نسخ احتياطي', import: 'استيراد', sync: 'مزامنة', pull: 'سحب من الجهاز', users_bulk: 'إجراء جماعي على المستخدمين',
  employee_edit: 'تعديل بيانات موظف', employee_delete: 'حذف موظف', employees_suspend: 'تعليق موظفين', employees_activate: 'إلغاء تعليق',
  employees_mode: 'تغيير طريقة التوثيق', bulk_dept: 'نقل إلى قسم', notify: 'إرسال إشعار',
  geofence_override: 'منح استثناء موقع', geofence_override_revoke: 'إلغاء استثناء موقع',
  mobile_account: 'إنشاء حساب تطبيق', mobile_create: 'إنشاء حسابات تطبيق', mobile_reset_password: 'كلمات مرور جديدة',
  mobile_unbind: 'فكّ ربط الهاتف', mobile_disable: 'إيقاف حسابات', mobile_enable: 'تفعيل حسابات', mobile_delete: 'حذف حسابات',
  mobile_anywhere_on: 'السماح من أي مكان', mobile_anywhere_off: 'إلغاء «أي مكان»', mobile_settings: 'إعدادات التطبيق',
  site_add: 'إضافة موقع عمل', site_edit: 'تعديل موقع عمل', site_delete: 'حذف موقع عمل',
  password_forgot: 'طلب استعادة كلمة المرور', password_reset: 'تعيين كلمة مرور جديدة', password_request_dismiss: 'تجاهل طلب كلمة المرور',
  purge: 'حذف سجلات (أدوات الصيانة)', mobile_punch_delete: 'حذف حركة هاتف', mobile_unbind: 'فكّ ربط الهاتف',
};
const AUDIT_TARGET_LABELS = {
  manual_entry: 'إدخال يدوي', date_exception: 'استثناء تاريخ', date_exception_bulk: 'استثناء تاريخ (جماعي)', official_holiday: 'عطلة رسمية',
  late_permission: 'إذن تأخير', departure_permission: 'إذن مغادرة', absence_reason: 'سبب غياب', forced_absence: 'غياب مفروض',
  forced_absence_bulk: 'غياب مفروض (جماعي)', user: 'المستخدمون', settings: 'الإعدادات', employee: 'الموظفون', employees: 'الموظفون (جماعي)',
  employee_accounts: 'حسابات التطبيق', work_site: 'مواقع العمل', device: 'أجهزة البصمة', device_attendance: 'سجلات الجهاز',
  device_users: 'مستخدمو الجهاز', device_sqlite: 'استيراد SQLite', device_mdb: 'استيراد MDB', onedrive: 'OneDrive', gdrive: 'Google Drive',
  push: 'إرسال مزامنة', receive: 'استقبال مزامنة', employees_from_sqlite: 'استيراد موظفين', mobile: 'تطبيق الهاتف',
  maintenance: 'أدوات الصيانة', mobile_punches: 'حركات الهاتف',
};

function _auditParams() {
  const p = new URLSearchParams();
  [['q', 'auditSearch'], ['target_type', 'auditType'], ['action_type', 'auditAction'], ['from', 'auditFrom'], ['to', 'auditTo'], ['limit', 'auditLimit']]
    .forEach(([k, id]) => { const v = document.getElementById(id).value; if (v) p.set(k, v); });
  return p;
}

function auditExport() {
  const p = _auditParams(); p.set('format', 'csv'); p.set('limit', '50000');
  window.location = '/api/audit-log?' + p.toString();
}

async function loadAuditLog() {
  const data = await api('/api/audit-log?' + _auditParams().toString());
  if (!data) return;
  const fill = (id, list, labels, allLabel) => {
    const sel = document.getElementById(id), cur = sel.value;
    sel.innerHTML = `<option value="">${allLabel}</option>` + list.map(f => `<option value="${escapeHtml(f.k)}">${escapeHtml(labels[f.k] || f.k)} (${f.n})</option>`).join('');
    sel.value = cur;
  };
  fill('auditType', data.facets.target_type, AUDIT_TARGET_LABELS, 'كل الأنواع');
  fill('auditAction', data.facets.action_type, AUDIT_ACTION_LABELS, 'كل العمليات');
  document.getElementById('auditSummary').textContent = `${data.total} عملية مطابقة` + (data.shown < data.total ? ` — يُعرض أحدث ${data.shown}` : '');
  const tbody = document.getElementById('auditTable');
  tbody.innerHTML = data.rows.map(r => `
    <tr${r.action_type === 'login_failed' ? ' style="background:#fff5f5"' : ''}>
      <td style="white-space:nowrap">${escapeHtml(r.timestamp)}</td><td dir="ltr" style="text-align:right">${escapeHtml(r.username || '')}</td>
      <td>${escapeHtml(AUDIT_ACTION_LABELS[r.action_type] || r.action_type)}</td>
      <td>${escapeHtml(AUDIT_TARGET_LABELS[r.target_type] || r.target_type)}</td>
      <td>${escapeHtml(r.employee_name || '')}</td><td>${escapeHtml(r.date_affected || '')}</td>
      <td><small>${escapeHtml(r.old_value || '')}</small></td><td><small>${escapeHtml(r.new_value || '')}</small></td><td>${escapeHtml(r.reason || '')}</td>
    </tr>`).join('') || '<tr><td colspan="9" style="text-align:center;color:var(--muted);padding:16px">لا توجد سجلات مطابقة</td></tr>';
}

/* ============ EMPLOYEES ============ */
async function addEmployee() {
  const name = document.getElementById('empName').value.trim();
  const dept = document.getElementById('empDept').value.trim();
  const device_uid = document.getElementById('empDeviceUid').value.trim();
  if (!name) { toast('الاسم إجباري', true); return; }
  try {
    await api('/api/employees', { method: 'POST', body: JSON.stringify({ name, dept, device_uid }) });
    toast('تمت الإضافة');
    document.getElementById('empName').value = '';
    document.getElementById('empDept').value = '';
    document.getElementById('empDeviceUid').value = '';
    loadEmployees();
    loadMetaInto();
  } catch (e) {}
}

let pendingEmpSource = null; // {file} أو {cloud_url} أو {local_path} - يُعاد إرساله بعد اختيار الأعمدة يدوياً وقت "needs_mapping"

function _employeeImportFormData(source) {
  const fd = new FormData();
  if (source.file) fd.append('file', source.file);
  else if (source.cloud_url) fd.append('cloud_url', source.cloud_url);
  else fd.append('local_path', source.local_path);
  const updateBox = document.getElementById('empImportUpdateExisting');
  fd.append('update_existing', (updateBox && updateBox.checked) ? '1' : '0');
  return fd;
}

function _finishEmployeeImport(data) {
  document.getElementById('empMappingBox').style.display = 'none';
  let msg = `أُضيف ${data.added}، حُدِّث ${data.updated}، تُجوهل ${data.skipped} (مكرر)`;
  if (data.missing_ac_no) msg += `، ${data.missing_ac_no} صف بدون رقم بصمة (تُجوهل)`;
  toast(msg);
  if (data.warning) toast(data.warning, true);
  document.getElementById('empFile').value = '';
  document.getElementById('empImportUrl').value = '';
  document.getElementById('empLocalPath').value = '';
  pendingEmpSource = null;
  loadEmployees();
  loadMetaInto();
}

function _showEmployeeMapping(data) {
  const cols = data.columns || [];
  const opt = c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`;
  document.getElementById('empMapName').innerHTML = cols.map(opt).join('');
  document.getElementById('empMapAcNo').innerHTML = cols.map(opt).join('');
  document.getElementById('empMapDept').innerHTML = '<option value="">-- بدون --</option>' + cols.map(opt).join('');
  const d = data.detected || {};
  if (d.name_col) document.getElementById('empMapName').value = d.name_col;
  if (d.dept_col) document.getElementById('empMapDept').value = d.dept_col;
  if (d.ac_no_col) document.getElementById('empMapAcNo').value = d.ac_no_col;
  const box = document.getElementById('empMappingBox');
  box.style.display = 'block';
  // ===== المربع يظهر أسفل حقلي الملف/الرابط، وقد لا يلاحظه المستخدم لو
  // كان خارج الجزء الظاهر من الشاشة فيظن أن الاستيراد "فشل" بلا أي إجراء
  // ممكن - نمرّر الشاشة إليه تلقائياً ونبرزه بإطار لوقت قصير =====
  box.scrollIntoView({ behavior: 'smooth', block: 'center' });
  box.style.outline = '2px solid #c0392b';
  box.style.borderRadius = '6px';
  setTimeout(() => { box.style.outline = ''; }, 2500);
  toast('لم نتمكّن من التعرّف على كل الأعمدة تلقائياً - اختر الأعمدة بالمربع الذي ظهر أسفل الصفحة ثم اضغط "تأكيد الاستيراد"', true);
}

function _doEmployeeImport(source) {
  pendingEmpSource = source;
  fetch('/api/employees/import', { method: 'POST', body: _employeeImportFormData(source) }).then(r => r.json()).then(data => {
    if (!data.ok) { toast(data.error || 'فشل الاستيراد', true); return; }
    if (data.needs_mapping) { _showEmployeeMapping(data); return; }
    _finishEmployeeImport(data);
  }).catch(() => toast('تعذّر الاستيراد', true));
}

function importEmployeesFromFile(input) {
  const f = input.files[0];
  if (!f) return;
  _doEmployeeImport({ file: f });
}

// ===== زر "استيراد" صريح بجانب حقل اختيار الملف (بدل الاعتماد فقط على
// onchange عند اختيار الملف) - كان غياب زر واضح يخلّي المستخدم يضغط زر
// "استيراد" الخاص بحقل الرابط بالخطأ بعد اختيار ملف محلي، فتظهر رسالة
// "يرجى إدخال رابط الملف" رغم اختياره ملفاً فعلياً بالأعلى =====
function importEmployeesFromFileButton() {
  const f = document.getElementById('empFile').files[0];
  if (!f) { toast('يرجى اختيار ملف أولاً', true); return; }
  _doEmployeeImport({ file: f });
}

function importEmployeesFromUrl() {
  const url = document.getElementById('empImportUrl').value.trim();
  if (!url) { toast('يرجى إدخال رابط الملف', true); return; }
  _doEmployeeImport({ cloud_url: url });
}

// ===== استيراد من مسار ملف على نفس جهاز الخادم مباشرة (بدون رفع عبر
// المتصفح) - نفس فكرة حقل local_path بميزتي استيراد att.mdb/SQLite،
// مفيد خصوصاً لما النظام يعمل مباشرة على جهاز المستخدم (Termux/ويندوز) =====
function importEmployeesFromLocalPath() {
  const path = document.getElementById('empLocalPath').value.trim();
  if (!path) { toast('يرجى إدخال مسار الملف على جهاز الخادم', true); return; }
  _doEmployeeImport({ local_path: path });
}

function confirmEmployeeImportMapping() {
  if (!pendingEmpSource) { toast('يرجى اختيار الملف أو إدخال الرابط من جديد', true); return; }
  const nameCol = document.getElementById('empMapName').value;
  const deptCol = document.getElementById('empMapDept').value;
  const acNoCol = document.getElementById('empMapAcNo').value;
  if (!nameCol || !acNoCol) { toast('يرجى اختيار عمود الاسم وعمود رقم البصمة', true); return; }
  const fd = _employeeImportFormData(pendingEmpSource);
  fd.append('mapping_confirmed', '1');
  fd.append('name_col', nameCol);
  fd.append('dept_col', deptCol);
  fd.append('ac_no_col', acNoCol);
  fetch('/api/employees/import', { method: 'POST', body: fd }).then(r => r.json()).then(data => {
    if (!data.ok) { toast(data.error || 'فشل الاستيراد', true); return; }
    _finishEmployeeImport(data);
  }).catch(() => toast('تعذّر الاستيراد', true));
}

async function loadEmployees() {
  const data = await api('/api/employees');
  if (!data) return;
  const tbody = document.getElementById('employeesTable');
  tbody.innerHTML = data.rows.map(r => `
    <tr><td><input type="checkbox" class="row-check" data-id="${r.id}"></td><td><a href="#" onclick="openEmployeeCard(${r.id});return false" style="font-weight:700;color:var(--primary-dark)">${escapeHtml(r.name)}</a>${r.active === 0 ? ' <span class="badge badge-absent">معلّق</span>' : ''}</td><td>${escapeHtml(r.dept || '')}</td><td dir="ltr" style="text-align:right">${escapeHtml(r.device_uid || '—')}</td>
    <td style="white-space:nowrap"><button class="btn btn-outline btn-sm" title="ملف الموظف" onclick="openEmployeeCard(${r.id})" aria-label="ملف الموظف"><i class="fas fa-id-card" aria-hidden="true"></i></button> <button class="btn btn-red btn-sm" onclick="deleteEmployee(${r.id})" ${PERMS.can_manage_employees ? '' : 'disabled title="ليس لديك صلاحية لهذا الإجراء"'} aria-label="ليس لديك صلاحية لهذا الإجراء"><i class="fas fa-trash" aria-hidden="true"></i></button></td></tr>
  `).join('') || '<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:16px">لا يوجد موظفون بعد</td></tr>';
}

async function deleteEmployee(id) {
  if (!confirm('حذف هذا الموظف نهائياً؟\nيُحذف حساب التطبيق معه. لإيقافه مؤقتاً استخدم «تعليق» من ملف الموظف.')) return;
  await api('/api/employees/' + id, { method: 'DELETE' });
  toast('تم الحذف');
  loadEmployees();
  loadMetaInto();
}

/* ============ DEVICE MANAGEMENT (ZKTeco) ============ */
let devicesCache = [];
let liveSinceId = 0;
let livePollTimer = null;

function showDeviceSubtab(name) {
  document.querySelectorAll('.device-subtab').forEach(p => p.classList.remove('active'));
  document.getElementById('devsub-' + name).classList.add('active');
  document.querySelectorAll('#tab-devices .subtab-btn').forEach(b => b.classList.toggle('active', b.dataset.subtab === name));
}

/* ===== أجهزة ترسل البصمات عبر الإنترنت (ADMS) ===== */
async function loadAdms() {
  const d = await api('/api/adms/devices').catch(() => null);
  if (!d) return;
  document.getElementById('admsHost').textContent = d.host;
  document.getElementById('admsCount').textContent = d.rows.length;
  document.getElementById('admsTotal').textContent = d.rows.length;
  document.getElementById('admsAll').checked = false;
  document.getElementById('admsTable').innerHTML = d.rows.map(r => `<tr>
    <td><input type="checkbox" class="adms-check" data-sn="${escapeHtml(r.sn)}" onchange="admsSelCount()"></td>
    <td><a href="#" onclick="admsRename('${escapeHtml(r.sn)}', this.textContent);return false" title="تعديل الاسم">${escapeHtml(r.name || r.sn)}</a></td>
    <td dir="ltr" data-notr>${escapeHtml(r.sn)}</td>
    <td>${r.approved ? '<span style="color:#1e8e5a;font-weight:700">مقبول</span>' : '<span style="color:#b45309;font-weight:700">بانتظار الموافقة</span>'}</td>
    <td dir="ltr">${escapeHtml(r.last_seen || '—')}</td><td>${r.today}</td><td>${r.punches}</td>
    <td>${r.unmatched ? `<span style="color:#c0392b">${r.unmatched}</span>` : '0'}</td></tr>`).join('')
    || '<tr><td colspan="8" style="color:var(--muted)">لم يتصل أي جهاز بعد</td></tr>';
  admsSelCount();
}
function admsChecked() { return [...document.querySelectorAll('.adms-check:checked')].map(c => c.dataset.sn); }
function admsSelCount() { document.getElementById('admsSel').textContent = admsChecked().length; }
function admsCheckAll(on) { document.querySelectorAll('.adms-check').forEach(c => { c.checked = on; }); admsSelCount(); }
async function admsBulk(action) {
  const sns = admsChecked();
  if (!sns.length) { toast('حدّد جهازاً واحداً على الأقل', true); return; }
  if (action === 'delete' && !confirm(`حذف ${sns.length} جهاز من القائمة؟ (إن اتصل مجدداً يظهر بانتظار الموافقة)`)) return;
  await api('/api/adms/devices/bulk', { method: 'POST', body: JSON.stringify({ sns, action }) });
  toast('تم'); loadAdms();
}
async function admsRename(sn, cur) {
  const name = prompt('اسم الجهاز:', cur || '');
  if (!name) return;
  await api('/api/adms/devices/bulk', { method: 'POST', body: JSON.stringify({ sns: [sn], action: 'rename', name }) });
  loadAdms();
}

async function loadDevices() {
  loadAdms();
  const data = await api('/api/devices');
  if (!data) return;
  devicesCache = data.rows;

  const tbody = document.getElementById('devicesTable');
  tbody.innerHTML = devicesCache.map(d => `
    <tr>
      <td><input type="checkbox" class="row-check" data-id="${d.id}"></td>
      <td>${escapeHtml(d.name)}</td><td dir="ltr" style="text-align:right">${escapeHtml(d.ip)}</td><td>${d.port}</td>
      <td>${escapeHtml(d.location || '')}</td>
      <td><span class="badge ${d.active ? 'badge-ontime' : 'badge-none'}">${d.active ? 'مفعَّل' : 'معطَّل'}</span></td>
      <td><button class="btn btn-outline btn-sm" onclick="testDevice(${d.id}, this)"><i class="fas fa-plug" aria-hidden="true"></i> اختبار</button></td>
      <td><button class="btn btn-red btn-sm" onclick="deleteDevice(${d.id})" aria-label="حذف" title="حذف"><i class="fas fa-trash" aria-hidden="true"></i></button></td>
    </tr>`).join('') || '<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:16px">لا توجد أجهزة مسجَّلة بعد</td></tr>';

  const selects = ['fingerSourceDevice', 'doorDevice', 'clearAttDevice', 'deleteUsersDevice', 'faceSourceDevice'];
  const optsHtml = devicesCache.map(d => `<option value="${d.id}">${escapeHtml(d.name)}</option>`).join('');
  selects.forEach(id => { const el = document.getElementById(id); if (el) el.innerHTML = optsHtml; });

  const checklists = ['liveDeviceList', 'pullDeviceList', 'pushDeviceList', 'fingerTargetList', 'faceTargetList'];
  const checksHtml = devicesCache.map(d => `
    <label><input type="checkbox" value="${d.id}"> ${escapeHtml(d.name)} <span style="color:var(--muted);font-size:.78rem" dir="ltr">(${escapeHtml(d.ip)})</span></label>
  `).join('') || '<span style="color:var(--muted);font-size:.85rem">لا توجد أجهزة - أضف جهازاً من تبويب "الأجهزة المسجَّلة" أولاً</span>';
  checklists.forEach(id => { const el = document.getElementById(id); if (el) el.innerHTML = checksHtml; });
}

function getCheckedDeviceIds(containerId) {
  return Array.from(document.querySelectorAll(`#${containerId} input[type=checkbox]:checked`)).map(el => parseInt(el.value));
}

async function addDevice() {
  const payload = {
    name: document.getElementById('devName').value.trim(),
    ip: document.getElementById('devIp').value.trim(),
    port: document.getElementById('devPort').value || 4370,
    password: document.getElementById('devPassword').value.trim() || '0',
    location: document.getElementById('devLocation').value.trim(),
  };
  if (!payload.name || !payload.ip) { toast('اسم الجهاز وعنوان IP حقلان إجباريان', true); return; }
  try {
    await api('/api/devices', { method: 'POST', body: JSON.stringify(payload) });
    toast('تمت إضافة الجهاز');
    ['devName', 'devIp', 'devLocation'].forEach(id => document.getElementById(id).value = '');
    document.getElementById('devPort').value = 4370;
    document.getElementById('devPassword').value = '0';
    loadDevices();
  } catch (e) {}
}

async function deleteDevice(id) {
  if (!confirm('حذف هذا الجهاز من النظام؟ (لا يحذف أي شيء من الجهاز الفعلي)')) return;
  await api('/api/devices/' + id, { method: 'DELETE' });
  toast('تم الحذف');
  loadDevices();
}

async function testDevice(id, btn) {
  const original = btn.innerHTML;
  btn.innerHTML = '<span class="spinner"></span>';
  btn.disabled = true;
  try {
    const data = await api('/api/devices/' + id + '/test', { method: 'POST' });
    if (data.ok) {
      toast(`متصل ✓ — ${data.device_name || ''} (${data.user_count} مستخدم مسجَّل)`);
    } else {
      toast(data.error || 'تعذّر الاتصال', true);
    }
  } catch (e) {} finally {
    btn.innerHTML = original;
    btn.disabled = false;
  }
}

async function importMdb() {
  const f = document.getElementById('mdbFile').files[0];
  const url = document.getElementById('mdbUrl').value.trim();
  const localPath = document.getElementById('mdbLocalPath').value.trim();
  if (!f && !url && !localPath) { toast('يرجى اختيار ملف att.mdb أو إدخال رابط الملف أو مسار محلي', true); return; }
  const fd = new FormData();
  if (f) fd.append('file', f); else if (url) fd.append('cloud_url', url); else fd.append('local_path', localPath);
  fd.append('date_from', document.getElementById('mdbFrom').value);
  fd.append('date_to', document.getElementById('mdbTo').value);
  const box = document.getElementById('mdbResult');
  box.innerHTML = '<span class="spinner"></span> جارٍ الاستيراد...';
  try {
    const res = await fetch('/api/devices/import-mdb', { method: 'POST', body: fd });
    const data = await res.json();
    if (!data.ok) { box.innerHTML = `<div class="alert alert-error">${escapeHtml(data.error || 'فشل الاستيراد')}</div>`; return; }
    let html = `<div class="alert alert-success">تم استيراد ${data.imported} سجلاً بنجاح - اذهب لتبويب "رفع البيانات" واضغط "تحليل البيانات".</div>`;
    if (data.detected_as_sqlite) {
      html += `<p style="font-size:.85rem;color:var(--muted);margin-top:8px">تم اكتشاف أن الملف فعلياً بصيغة SQLite (وليس att.mdb) واستُورد على هذا الأساس تلقائياً` +
        (data.employees_added || data.employees_updated ? ` - ${data.employees_added || 0} موظف جديد، ${data.employees_updated || 0} تحديث.` : '.') + `</p>`;
    }
    if (data.unmatched_uids && data.unmatched_uids.length) {
      html += `<p style="font-size:.85rem;color:var(--muted);margin-top:8px">أرقام بصمة غير مطابقة لأي موظف: ${data.unmatched_uids.join(', ')}</p>`;
    }
    if (data.imported === 0) {
      html += `<p style="font-size:.85rem;color:var(--muted);margin-top:8px">تم العثور على ${data.raw_count || 0} سجل خام بالملف ضمن الفترة المحددة.` +
        (data.raw_count > 0
          ? ' البيانات موجودة لكن لم تُطابَق أي منها لموظف - تأكد من تعبئة "رقم البصمة" لموظفيك في تبويب الموظفين.'
          : ' لا توجد بيانات بالملف ضمن هذه الفترة الزمنية - جرّب توسيع الفترة أو تركها فارغة لاستيراد كل البيانات.') +
        `</p>`;
    }
    box.innerHTML = html;
  } catch (e) {
    box.innerHTML = '<div class="alert alert-error">تعذّر الاستيراد.</div>';
  }
}

async function importSqlite() {
  const f = document.getElementById('sqliteFile').files[0];
  const url = document.getElementById('sqliteUrl').value.trim();
  const localPath = document.getElementById('sqliteLocalPath').value.trim();
  if (!f && !url && !localPath) { toast('يرجى اختيار ملف SQLite أو إدخال رابط الملف أو مسار محلي', true); return; }
  const fd = new FormData();
  if (f) fd.append('file', f); else if (url) fd.append('cloud_url', url); else fd.append('local_path', localPath);
  fd.append('date_from', document.getElementById('sqliteFrom').value);
  fd.append('date_to', document.getElementById('sqliteTo').value);
  fd.append('create_employees', document.getElementById('sqliteCreateEmployees').checked ? '1' : '0');
  fd.append('update_existing_employees', document.getElementById('sqliteUpdateExistingEmployees').checked ? '1' : '0');
  const box = document.getElementById('sqliteResult');
  box.innerHTML = '<span class="spinner"></span> جارٍ الاستيراد...';
  try {
    const res = await fetch('/api/devices/import-sqlite', { method: 'POST', body: fd });
    const data = await res.json();
    if (!data.ok) { box.innerHTML = `<div class="alert alert-error">${escapeHtml(data.error || 'فشل الاستيراد')}</div>`; return; }
    let html = `<div class="alert alert-success">تم استيراد ${data.imported} سجلاً بنجاح - اذهب لتبويب "رفع البيانات" واضغط "تحليل البيانات".</div>`;
    if (data.employees_added || data.employees_updated) {
      html += `<p style="font-size:.85rem;color:var(--muted);margin-top:8px">من الملف: ${data.employees_added || 0} موظف جديد، ${data.employees_updated || 0} تحديث بيانات موظف.</p>`;
    }
    if (data.unmatched_uids && data.unmatched_uids.length) {
      html += `<p style="font-size:.85rem;color:var(--muted);margin-top:8px">أرقام بصمة غير مطابقة لأي موظف: ${data.unmatched_uids.join(', ')}</p>`;
    }
    if (data.skipped_bad_time) {
      html += `<p style="font-size:.85rem;color:var(--muted);margin-top:8px">${data.skipped_bad_time} سجل تُجوهل لتعذّر تفسير وقت البصمة به.</p>`;
    }
    if (data.imported === 0) {
      html += `<p style="font-size:.85rem;color:var(--muted);margin-top:8px">تم العثور على ${data.raw_count || 0} سجل خام بالملف ضمن الفترة المحددة.` +
        (data.raw_count > 0
          ? ' البيانات موجودة لكن لم تُطابَق أي منها لموظف - تأكد من تعبئة "رقم البصمة" لموظفيك في تبويب الموظفين.'
          : ' لا توجد بيانات بالملف ضمن هذه الفترة الزمنية - جرّب توسيع الفترة أو تركها فارغة لاستيراد كل البيانات.') +
        `</p>`;
    }
    box.innerHTML = html;
  } catch (e) {
    box.innerHTML = '<div class="alert alert-error">تعذّر الاستيراد.</div>';
  }
}

async function pullFromDevices() {
  const device_ids = getCheckedDeviceIds('pullDeviceList');
  if (!device_ids.length) { toast('يرجى اختيار جهاز واحد على الأقل', true); return; }
  const payload = { device_ids, date_from: document.getElementById('pullFrom').value, date_to: document.getElementById('pullTo').value };
  const box = document.getElementById('pullResult');
  box.innerHTML = '<span class="spinner"></span> جارٍ السحب من الأجهزة...';
  try {
    const data = await api('/api/devices/pull', { method: 'POST', body: JSON.stringify(payload) });
    let html = `<div class="alert alert-success">تم استيراد ${data.imported} سجلاً - اذهب لتبويب "رفع البيانات" واضغط "تحليل البيانات".</div>`;
    html += '<div class="log-box" style="margin-top:8px">' + data.per_device.map(d =>
      d.ok ? `✓ ${escapeHtml(d.device)}: ${d.count} سجل` : `✗ ${escapeHtml(d.device)}: ${escapeHtml(d.error)}`
    ).join('\n') + '</div>';
    if (data.unmatched_uids && data.unmatched_uids.length) {
      html += `<p style="font-size:.85rem;color:var(--muted);margin-top:8px">أرقام بصمة غير مطابقة لأي موظف: ${data.unmatched_uids.join(', ')}</p>`;
    }
    box.innerHTML = html;
  } catch (e) {
    box.innerHTML = '<div class="alert alert-error">فشلت عملية السحب.</div>';
  }
}

async function pushToDevices() {
  const device_ids = getCheckedDeviceIds('pushDeviceList');
  if (!device_ids.length) { toast('يرجى اختيار جهاز واحد على الأقل', true); return; }
  const box = document.getElementById('pushResult');
  box.innerHTML = '<span class="spinner"></span> جارٍ الرفع...';
  try {
    const data = await api('/api/devices/push', { method: 'POST', body: JSON.stringify({ device_ids }) });
    box.innerHTML = '<div class="log-box">' + data.per_device.map(d => {
      if (!d.ok) return `✗ ${escapeHtml(d.device)}: ${escapeHtml(d.error)}`;
      const okCount = d.results.filter(r => r.ok).length;
      const failed = d.results.filter(r => !r.ok);
      let line = `✓ ${escapeHtml(d.device)}: نجح رفع ${okCount} من ${d.results.length}`;
      if (failed.length) line += '\n  فشل: ' + failed.map(f => `${f.name} (${f.error})`).join('، ');
      return line;
    }).join('\n\n') + '</div>';
  } catch (e) {
    box.innerHTML = '<div class="alert alert-error">فشلت عملية الرفع.</div>';
  }
}

async function copyFingerprint() {
  const source_id = parseInt(document.getElementById('fingerSourceDevice').value);
  const target_ids = getCheckedDeviceIds('fingerTargetList').filter(id => id !== source_id);
  const uidsRaw = document.getElementById('fingerUids').value.trim();
  const device_uids = uidsRaw ? uidsRaw.split(',').map(s => s.trim()).filter(Boolean) : null;
  if (!source_id || !target_ids.length) { toast('يرجى اختيار جهاز مصدر وجهاز هدف واحد على الأقل (غير المصدر)', true); return; }
  if (!confirm('نسخ بصمة الإصبع ميزة تجريبية - هل تريد المتابعة؟')) return;
  const box = document.getElementById('fingerResult');
  box.innerHTML = '<span class="spinner"></span> جارٍ النسخ...';
  try {
    const data = await api('/api/devices/copy-fingerprint', { method: 'POST', body: JSON.stringify({ source_id, target_ids, device_uids }) });
    if (!data.ok) { box.innerHTML = `<div class="alert alert-error">${escapeHtml(data.error)}</div>`; return; }
    box.innerHTML = '<div class="log-box">' + data.results.map(r =>
      r.ok ? `✓ ${escapeHtml(r.device)} — رقم ${escapeHtml(r.uid || '')}` : `✗ ${escapeHtml(r.device)} — ${escapeHtml(r.uid || '')}: ${escapeHtml(r.error || '')}`
    ).join('\n') + '</div>';
  } catch (e) {
    box.innerHTML = '<div class="alert alert-error">فشلت عملية النسخ.</div>';
  }
}

async function unlockDoor() {
  const id = parseInt(document.getElementById('doorDevice').value);
  const seconds = parseInt(document.getElementById('doorSeconds').value) || 3;
  if (!id) { toast('يرجى اختيار جهاز', true); return; }
  const box = document.getElementById('doorResult');
  try {
    const data = await api(`/api/devices/${id}/unlock`, { method: 'POST', body: JSON.stringify({ seconds }) });
    box.innerHTML = data.ok ? '<div class="alert alert-success">تم إرسال أمر فتح الباب.</div>' : `<div class="alert alert-error">${escapeHtml(data.error)}</div>`;
  } catch (e) {
    box.innerHTML = '<div class="alert alert-error">تعذّر تنفيذ الأمر.</div>';
  }
}

async function copyFace() {
  const source_id = parseInt(document.getElementById('faceSourceDevice').value);
  const target_ids = getCheckedDeviceIds('faceTargetList').filter(id => id !== source_id);
  const uidsRaw = document.getElementById('faceUids').value.trim();
  const device_uids = uidsRaw ? uidsRaw.split(',').map(s => s.trim()).filter(Boolean) : null;
  const manual_password = document.getElementById('faceManualPassword').value.trim();
  if (!source_id || !target_ids.length) { toast('يرجى اختيار جهاز مصدر وجهاز هدف واحد على الأقل (غير المصدر)', true); return; }
  const box = document.getElementById('faceResult');
  box.innerHTML = '<span class="spinner"></span> جارٍ النسخ...';
  try {
    const data = await api('/api/devices/copy-face', { method: 'POST', body: JSON.stringify({ source_id, target_ids, device_uids, manual_password }) });
    if (!data.ok) { box.innerHTML = `<div class="alert alert-error">${escapeHtml(data.error)}</div>`; return; }
    let html = '<div class="log-box">' + (data.log || []).map(escapeHtml).join('\n') + '</div>';
    box.innerHTML = html;
  } catch (e) {
    box.innerHTML = '<div class="alert alert-error">فشلت عملية النسخ.</div>';
  }
}

async function clearDeviceAttendance() {
  const id = parseInt(document.getElementById('clearAttDevice').value);
  if (!id) { toast('يرجى اختيار جهاز', true); return; }
  if (!confirm('سيتم مسح كل بيانات الحضور المخزَّنة على نفس الجهاز نهائياً. متابعة؟')) return;
  const box = document.getElementById('clearAttResult');
  try {
    const data = await api(`/api/devices/${id}/clear-attendance`, { method: 'POST' });
    box.innerHTML = data.ok ? '<div class="alert alert-success">تم مسح بيانات الحضور من الجهاز.</div>' : `<div class="alert alert-error">${escapeHtml(data.error)}</div>`;
  } catch (e) {
    box.innerHTML = '<div class="alert alert-error">تعذّر تنفيذ الأمر.</div>';
  }
}

async function deleteDeviceUsers() {
  const id = parseInt(document.getElementById('deleteUsersDevice').value);
  const uidsRaw = document.getElementById('deleteUsersUids').value.trim();
  const device_uids = uidsRaw ? uidsRaw.split(',').map(s => s.trim()).filter(Boolean) : null;
  if (!id) { toast('يرجى اختيار جهاز', true); return; }
  const msg = device_uids ? `سيتم حذف ${device_uids.length} مستخدم من الجهاز نهائياً. متابعة؟` : 'سيتم حذف كل المستخدمين من الجهاز نهائياً. متابعة؟';
  if (!confirm(msg)) return;
  const box = document.getElementById('deleteUsersResult');
  try {
    const data = await api(`/api/devices/${id}/delete-users`, { method: 'POST', body: JSON.stringify({ device_uids }) });
    if (!data.ok) { box.innerHTML = `<div class="alert alert-error">${escapeHtml(data.error)}</div>`; return; }
    const okCount = data.results.filter(r => r.ok).length;
    box.innerHTML = `<div class="alert alert-success">تم حذف ${okCount} من ${data.results.length}.</div>`;
  } catch (e) {
    box.innerHTML = '<div class="alert alert-error">تعذّر تنفيذ الأمر.</div>';
  }
}

async function queryDeviceUsers() {
  const id = parseInt(document.getElementById('deleteUsersDevice').value);
  if (!id) { toast('يرجى اختيار جهاز', true); return; }
  const box = document.getElementById('deleteUsersResult');
  box.innerHTML = '<div class="alert">جارِ الاستعلام من الجهاز...</div>';
  const wrap = document.getElementById('deviceUsersQueryWrap');
  const data = await api(`/api/devices/${id}/users`);
  if (!data || !data.ok) {
    box.innerHTML = `<div class="alert alert-error">${escapeHtml((data && data.error) || 'تعذّر الاستعلام')}</div>`;
    wrap.style.display = 'none';
    return;
  }
  box.innerHTML = `<div class="alert alert-success">تم العثور على ${data.rows.length} مستخدم على الجهاز.</div>`;
  const tbody = document.getElementById('deviceUsersTable');
  tbody.innerHTML = data.rows.map(r => `
    <tr>
      <td><input type="checkbox" class="row-check" data-id="${escapeHtml(r.user_id)}"></td>
      <td dir="ltr" style="text-align:right">${r.uid}</td>
      <td dir="ltr" style="text-align:right">${escapeHtml(r.user_id)}</td>
      <td>${escapeHtml(r.name || '—')}</td>
      <td>${r.privilege === 14 ? 'مدير الجهاز' : 'عادي'}</td>
    </tr>`).join('') || '<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:16px">لا يوجد مستخدمون على هذا الجهاز</td></tr>';
  wrap.style.display = '';
  applyAllTableFilters();
}

async function deleteSelectedDeviceUsers() {
  const id = parseInt(document.getElementById('deleteUsersDevice').value);
  if (!id) { toast('يرجى اختيار جهاز', true); return; }
  const boxes = Array.from(document.querySelectorAll('#deviceUsersTable .row-check:checked'))
    .filter(cb => cb.closest('tr').style.display !== 'none');
  if (!boxes.length) { toast('حدّد مستخدماً واحداً على الأقل من الجدول', true); return; }
  const device_uids = boxes.map(cb => cb.dataset.id);
  if (!confirm(`سيتم حذف ${device_uids.length} مستخدم من الجهاز نهائياً. متابعة؟`)) return;
  const box = document.getElementById('deleteUsersResult');
  try {
    const data = await api(`/api/devices/${id}/delete-users`, { method: 'POST', body: JSON.stringify({ device_uids }) });
    if (!data.ok) { box.innerHTML = `<div class="alert alert-error">${escapeHtml(data.error)}</div>`; return; }
    const okCount = data.results.filter(r => r.ok).length;
    box.innerHTML = `<div class="alert alert-success">تم حذف ${okCount} من ${data.results.length}.</div>`;
    queryDeviceUsers(); // تحديث الجدول ليعكس الحذف
  } catch (e) {
    box.innerHTML = '<div class="alert alert-error">تعذّر تنفيذ الأمر.</div>';
  }
}

async function startLiveCapture() {
  const device_ids = getCheckedDeviceIds('liveDeviceList');
  if (!device_ids.length) { toast('يرجى اختيار جهاز واحد على الأقل', true); return; }
  const data = await api('/api/devices/live/start', { method: 'POST', body: JSON.stringify({ device_ids }) });
  if (!data.ok) { toast(data.error || 'تعذّر بدء المراقبة', true); return; }
  liveSinceId = 0;
  document.getElementById('liveLog').textContent = 'بدأت المراقبة - بانتظار أي بصمة...';
  document.getElementById('liveStartBtn').disabled = true;
  document.getElementById('liveStopBtn').disabled = false;
  livePollTimer = setInterval(pollLiveEvents, 2000);
}

async function stopLiveCapture() {
  await api('/api/devices/live/stop', { method: 'POST' });
  clearInterval(livePollTimer);
  document.getElementById('liveStartBtn').disabled = false;
  document.getElementById('liveStopBtn').disabled = true;
}

async function pollLiveEvents() {
  const data = await api('/api/devices/live/events?since=' + liveSinceId);
  if (!data || !data.events.length) return;
  const box = document.getElementById('liveLog');
  data.events.forEach(e => {
    liveSinceId = Math.max(liveSinceId, e.id);
    let line;
    if (e.error) {
      line = `⚠️ [${escapeHtml(e.device)}] ${escapeHtml(e.error)}`;
    } else {
      const analyzedTag = e.analyzed === true ? ' ✔ تحليل فوري' : (e.analyzed === false ? ` ⚠ تعذّر التحليل الفوري: ${escapeHtml(e.analyze_error || '')}` : '');
      line = `🟢 ${e.time} — ${escapeHtml(e.name)} [${escapeHtml(e.device)}]${analyzedTag}`;
    }
    box.textContent = line + '\n' + box.textContent;
  });
  loadStats(); // تحديث بطاقات لوحة التحكم فوراً لتعكس التحليل الفوري
}

/* ============ DEPT TIMES ============ */
async function saveDeptTime() {
  const dept = document.getElementById('dtDept').value.trim();
  const att = document.getElementById('dtAtt').value;
  const dep = document.getElementById('dtDep').value;
  if (!dept) { toast('اسم القسم إجباري', true); return; }
  try {
    await api('/api/dept-times', { method: 'POST', body: JSON.stringify({ dept, attendance_time: att, departure_time: dep }) });
    toast('تم الحفظ');
    document.getElementById('dtDept').value = '';
    document.getElementById('dtAtt').value = '';
    document.getElementById('dtDep').value = '';
    loadDeptTimes();
  } catch (e) {}
}

async function loadDeptTimes() {
  const data = await api('/api/dept-times');
  if (!data) return;
  const tbody = document.getElementById('deptTimesTable');
  tbody.innerHTML = data.rows.map(r => `
    <tr><td><input type="checkbox" class="row-check" data-id="${encodeURIComponent(r.dept)}"></td><td>${escapeHtml(r.dept)}</td><td>${escapeHtml(r.attendance_time || '—')}</td><td>${escapeHtml(r.departure_time || '—')}</td>
    <td><button class="btn btn-red btn-sm" onclick="deleteDeptTime('${encodeURIComponent(r.dept)}')" aria-label="حذف" title="حذف"><i class="fas fa-trash" aria-hidden="true"></i></button></td></tr>
  `).join('') || '<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:16px">لا توجد أقسام مخصَّصة</td></tr>';
}

async function deleteDeptTime(deptEncoded) {
  if (!confirm('حذف هذا التخصيص؟')) return;
  await api('/api/dept-times/' + deptEncoded, { method: 'DELETE' });
  toast('تم الحذف');
  loadDeptTimes();
}

/* ============ SETTINGS ============ */
async function loadSettings() {
  const data = await api('/api/settings');
  if (!data) return;
  const s = data.settings;
  document.getElementById('setOrgName').value = s.org_name;
  document.getElementById('setOrgNameEn').value = s.org_name_en || '';
  document.getElementById('setAttTime').value = s.attendance_time;
  document.getElementById('setDepTime').value = s.departure_time;
  document.getElementById('setLateTh').value = s.late_threshold;
  document.getElementById('setExcludedDepts').value = s.excluded_depts;
  document.getElementById('setShiftEnabled').checked = s.shift_enabled === '1';
  document.getElementById('setShift1Start').value = s.shift1_start;
  document.getElementById('setShift1End').value = s.shift1_end;
  document.getElementById('setShift2Start').value = s.shift2_start;
  document.getElementById('setShift2End').value = s.shift2_end;
  document.getElementById('setSatEnabled').checked = s.sat_time_enabled === '1';
  document.getElementById('setSatAtt').value = s.sat_attendance_time;
  document.getElementById('setSatDep').value = s.sat_departure_time;
  renderLogoPreview(s.org_logo_filename);
  document.getElementById('setSyncUrl').value = s.sync_central_url || '';
  document.getElementById('setSyncKey').value = s.sync_api_key || '';
  const syncStatus = document.getElementById('syncStatusBox');
  if (s.sync_last_push_at) {
    syncStatus.textContent = `آخر عملية نشر: ${s.sync_last_push_at} - ${s.sync_last_push_status || ''}`;
  } else {
    syncStatus.textContent = '';
  }
  document.getElementById('syncPushCard').style.display = s.sync_central_url ? 'block' : 'none';
  const role = s.sync_central_url ? 'branch' : (s.sync_api_key ? 'central' : 'none');
  const rr = document.querySelector(`input[name=syncRole][value=${role}]`); if (rr) rr.checked = true;
  syncRoleUi();

  const sn = await api('/api/shift-names');
  if (sn) {
    document.getElementById('setShift1Names').value = sn.shift1.join(', ');
    document.getElementById('setShift2Names').value = sn.shift2.join(', ');
  }
}

async function saveSettings() {
  const payload = {
    org_name: document.getElementById('setOrgName').value.trim(),
    org_name_en: document.getElementById('setOrgNameEn').value.trim(),
    attendance_time: document.getElementById('setAttTime').value,
    departure_time: document.getElementById('setDepTime').value,
    late_threshold: document.getElementById('setLateTh').value || '5',
    excluded_depts: document.getElementById('setExcludedDepts').value.trim(),
    shift_enabled: document.getElementById('setShiftEnabled').checked ? '1' : '0',
    shift1_start: document.getElementById('setShift1Start').value,
    shift1_end: document.getElementById('setShift1End').value,
    shift2_start: document.getElementById('setShift2Start').value,
    shift2_end: document.getElementById('setShift2End').value,
    sat_time_enabled: document.getElementById('setSatEnabled').checked ? '1' : '0',
    sat_attendance_time: document.getElementById('setSatAtt').value,
    sat_departure_time: document.getElementById('setSatDep').value,
    sync_central_url: syncRole() === 'branch' ? document.getElementById('setSyncUrl').value.trim() : '',
    sync_api_key: syncRole() === 'none' ? '' : document.getElementById('setSyncKey').value.trim(),
  };
  const box = document.getElementById('settingsResult');
  try {
    await api('/api/settings', { method: 'POST', body: JSON.stringify(payload) });
    const shift1 = document.getElementById('setShift1Names').value.split(',').map(s => s.trim()).filter(Boolean);
    const shift2 = document.getElementById('setShift2Names').value.split(',').map(s => s.trim()).filter(Boolean);
    await api('/api/shift-names', { method: 'POST', body: JSON.stringify({ shift1, shift2 }) });
    box.innerHTML = '<div class="alert alert-success">تم حفظ الإعدادات - اضغط "تحليل البيانات" في تبويب رفع البيانات لتطبيقها.</div>';
    toast('تم حفظ الإعدادات');
    document.getElementById('syncPushCard').style.display = payload.sync_central_url ? 'block' : 'none';
  } catch (e) {
    box.innerHTML = '<div class="alert alert-error">فشل حفظ الإعدادات.</div>';
  }
}

async function syncPush() {
  const box = document.getElementById('syncPushResult');
  box.innerHTML = '<span class="spinner"></span> جارٍ الرفع...';
  try {
    const res = await fetch('/api/sync/push', { method: 'POST' });
    const data = await res.json();
    if (!data.ok) { box.innerHTML = `<div class="alert alert-error">${escapeHtml(data.error || 'فشل النشر')}</div>`; return; }
    if (data.nothing_to_sync) {
      box.innerHTML = '<div class="alert alert-success">لا توجد تعديلات جديدة بانتظار الرفع - كل شيء مُزامَن.</div>';
      return;
    }
    box.innerHTML = `<div class="alert alert-success">تم رفع ${data.pushed_employees} موظف و${data.pushed_punches} سجل بصمة للقاعدة الرئيسية بنجاح.</div>`;
    toast('تمت المزامنة بنجاح');
  } catch (e) {
    box.innerHTML = '<div class="alert alert-error">تعذّر الاتصال بالقاعدة الرئيسية.</div>';
  }
}

/* ============ شعار المؤسسة ============ */
function renderLogoPreview(filename) {
  const box = document.getElementById('logoPreviewBox');
  if (!box) return;
  box.innerHTML = filename
    ? `<img src="/static/uploads/${encodeURIComponent(filename)}?v=${Date.now()}" alt="الشعار الحالي" style="max-height:70px;max-width:220px;border:1px solid var(--border,#ddd);border-radius:6px;padding:4px">`
    : '<p style="color:var(--muted);font-size:.85rem">لا يوجد شعار محفوظ حالياً</p>';
}

/* تحديث الشعار في الشريط الجانبي والشريط العلوي فوراً دون إعادة تحميل الصفحة */
function applyLogoEverywhere(url) {
  const chip = document.querySelector('.sidebar-logo-chip');
  if (chip) {
    if (url) {
      chip.innerHTML = '';
      const img = document.createElement('img');
      img.src = url; img.alt = 'شعار المؤسسة';
      img.style.cssText = 'max-height:32px;max-width:150px;vertical-align:middle';
      chip.appendChild(img);
    } else {
      chip.innerHTML = '<i class="fas fa-fingerprint" aria-hidden="true"></i>&nbsp;<span class="sidebar-logo-title">نظام الحضور</span>';
    }
  }
  let top = document.querySelector('.topbar-logo');
  if (url) {
    if (!top) {
      const h = document.getElementById('pageTitle');
      if (h) { top = document.createElement('img'); top.className = 'topbar-logo'; top.alt = 'شعار المؤسسة'; h.before(top); }
    }
    if (top) top.src = url;
  } else if (top) top.remove();
}

async function uploadLogo() {
  const input = document.getElementById('logoFileInput');
  const file = input.files[0];
  if (!file) { toast('اختر ملف الشعار أولاً', true); return; }
  const fd = new FormData();
  fd.append('logo', file);
  try {
    const res = await fetch('/api/settings/logo', { method: 'POST', body: fd });
    const data = await res.json();
    if (!data.ok) { toast(data.error || 'فشل رفع الشعار', true); return; }
    toast('تم رفع الشعار');
    input.value = '';
    applyLogoEverywhere(data.logo_url);
    loadSettings();
  } catch (e) {
    toast('فشل رفع الشعار', true);
  }
}

async function removeLogo() {
  if (!confirm('إزالة شعار المؤسسة الحالي؟')) return;
  try {
    await api('/api/settings/logo', { method: 'DELETE' });
    toast('تمت إزالة الشعار');
    applyLogoEverywhere('');
    loadSettings();
  } catch (e) {}
}

/* ============ SCHEDULING ============ */
/* مزوّدو البريد: قوالب جاهزة لإعدادات الإرسال مع إرشادات مختصرة */
const EMAIL_PROVIDERS = {
  microsoft: { host: 'smtp.office365.com', port: 587, security: 'starttls', pw: 'كلمة مرور الحساب (أو كلمة مرور تطبيق إن كانت المصادقة الثنائية مفعّلة)',
    help: '<b>Microsoft 365 / Outlook:</b> الخادم smtp.office365.com والمنفذ 587 مع STARTTLS. يجب أن يكون «Authenticated SMTP» مفعّلاً لصندوق المرسل من مركز إدارة Microsoft 365 (المستخدمون ← البريد ← إدارة تطبيقات البريد). إن عطّلت مؤسستك SMTP AUTH فاختر «Microsoft Graph API».' },
  google: { host: 'smtp.gmail.com', port: 587, security: 'starttls', pw: 'كلمة مرور التطبيق (16 حرفاً) — لا كلمة مرور Gmail العادية',
    help: '<b>Google (Gmail / Workspace):</b> الخادم smtp.gmail.com والمنفذ 587 مع STARTTLS (أو 465 مع SSL). يشترط Google تفعيل التحقق بخطوتين ثم إنشاء «كلمة مرور تطبيق» من حساب Google ← الأمان ← كلمات مرور التطبيقات، واستخدامها هنا.' },
  custom: { host: '', port: 587, security: 'starttls', pw: 'كلمة المرور',
    help: '<b>خادم SMTP آخر:</b> أدخل بيانات الخادم كما يزوّدك بها مزوّد البريد. المنفذ 587 يعني غالباً STARTTLS، و465 يعني SSL.' },
};
function toggleEmailMethodBoxes() {
  const graph = document.getElementById('schProvider').value === 'graph';
  document.getElementById('schEmailMethod').value = graph ? 'graph' : 'smtp';
  document.getElementById('schSmtpBox').style.display = graph ? 'none' : '';
  document.getElementById('schGraphBox').style.display = graph ? '' : 'none';
}
function applyEmailProvider(fill) {
  const prov = document.getElementById('schProvider').value, p = EMAIL_PROVIDERS[prov];
  toggleEmailMethodBoxes();
  if (!p) return;
  document.getElementById('schProviderHelp').innerHTML = p.help;
  document.getElementById('schPwLabel').textContent = p.pw;
  if (fill && p.host) {
    document.getElementById('schSmtpHost').value = p.host;
    document.getElementById('schSmtpPort').value = p.port;
    document.getElementById('schSmtpSecurity').value = p.security;
  }
}
document.addEventListener('change', e => {
  if (e.target && e.target.id === 'schSmtpPort') {
    const v = e.target.value;
    if (v === '465') document.getElementById('schSmtpSecurity').value = 'ssl';
    else if (v === '587') document.getElementById('schSmtpSecurity').value = 'starttls';
  }
});

async function loadScheduleSettings() {
  const data = await api('/api/schedule');
  if (!data) return;
  const s = data.settings;
  document.getElementById('schProvider').value = (s.email_method === 'graph') ? 'graph' : (s.smtp_provider || 'microsoft');
  applyEmailProvider(false);
  document.getElementById('schSmtpSecurity').value = s.smtp_security || 'starttls';
  document.getElementById('schSmtpUsername').value = s.smtp_username || '';
  document.getElementById('schSmtpSenderName').value = s.smtp_sender_name || '';
  document.getElementById('schSmtpHost').value = s.smtp_host || '';
  document.getElementById('schSmtpPort').value = s.smtp_port || '587';
  document.getElementById('schSmtpSender').value = s.smtp_sender_email || '';
  document.getElementById('schSmtpPassword').value = s.smtp_sender_password || '';
  document.getElementById('schGraphTenant').value = s.graph_tenant_id || '';
  document.getElementById('schGraphClientId').value = s.graph_client_id || '';
  document.getElementById('schGraphClientSecret').value = s.graph_client_secret || '';
  document.getElementById('schGraphSenderUpn').value = s.graph_sender_upn || '';
  document.getElementById('schSmtpRecipients').value = s.smtp_recipients || '';
  document.getElementById('schEnabled').checked = s.schedule_enabled === '1';
  document.getElementById('schTime').value = s.schedule_time || '07:00';
  document.getElementById('schPullBefore').checked = s.schedule_pull_before === '1';

  const sel = document.getElementById('schStatusFilter');
  sel.innerHTML = Object.entries(s.status_filters || {}).map(([k, v]) => `<option value="${k}">${escapeHtml(v)}</option>`).join('');
  sel.value = s.schedule_status_filter || 'absent_or_late';

  const days = new Set((s.schedule_days || []).map(String));
  document.querySelectorAll('.schDay').forEach(cb => { cb.checked = days.has(cb.value); });

  renderScheduleLastRun(s);
  loadOneDriveBackupSettings();
  loadGDriveBackupSettings();
}

async function loadOneDriveBackupSettings() {
  const data = await api('/api/backup/onedrive');
  if (!data) return;
  const s = data.settings;
  document.getElementById('odBackupUpn').value = s.onedrive_backup_upn || '';
  document.getElementById('odBackupFolder').value = s.onedrive_backup_folder || 'AttendanceBackups';
  const el = document.getElementById('odBackupLast');
  if (!s.onedrive_last_backup_at) { el.textContent = 'لم تُنسَخ نسخة احتياطية بعد'; return; }
  el.innerHTML = `آخر نسخة احتياطية: <b>${escapeHtml(s.onedrive_last_backup_at)}</b> - ${escapeHtml(s.onedrive_last_backup_status || '')}`;
}

async function saveOneDriveBackupSettings() {
  const payload = {
    onedrive_backup_upn: document.getElementById('odBackupUpn').value.trim(),
    onedrive_backup_folder: document.getElementById('odBackupFolder').value.trim() || 'AttendanceBackups',
  };
  try {
    await api('/api/backup/onedrive', { method: 'POST', body: JSON.stringify(payload) });
    toast('تم حفظ إعدادات النسخ الاحتياطي');
  } catch (e) {
    toast('فشل الحفظ', true);
  }
}

async function runOneDriveBackup() {
  await saveOneDriveBackupSettings();
  const box = document.getElementById('odBackupResult');
  box.innerHTML = '<span class="spinner"></span> جارٍ رفع النسخة الاحتياطية...';
  try {
    const res = await fetch('/api/backup/onedrive/run', { method: 'POST' });
    const data = await res.json();
    if (!data.ok) { box.innerHTML = `<div class="alert alert-error">${escapeHtml(data.error || 'فشل النسخ الاحتياطي')}</div>`; return; }
    box.innerHTML = `<div class="alert alert-success">تم رفع نسخة احتياطية بنجاح (${escapeHtml(data.filename)}).` +
      (data.webUrl ? ` <a href="${escapeHtml(data.webUrl)}" target="_blank" rel="noopener">فتح على OneDrive</a>` : '') + `</div>`;
    loadOneDriveBackupSettings();
  } catch (e) {
    box.innerHTML = '<div class="alert alert-error">تعذّر الاتصال بالخادم أثناء النسخ الاحتياطي.</div>';
  }
}

async function loadGDriveBackupSettings() {
  const data = await api('/api/backup/gdrive');
  if (!data) return;
  const s = data.settings;
  document.getElementById('gdBackupJsonPath').value = s.gdrive_service_account_json_path || '';
  document.getElementById('gdBackupFolderId').value = s.gdrive_backup_folder_id || '';
  const el = document.getElementById('gdBackupLast');
  if (!s.gdrive_last_backup_at) { el.textContent = 'لم تُنسَخ نسخة احتياطية بعد'; return; }
  el.innerHTML = `آخر نسخة احتياطية: <b>${escapeHtml(s.gdrive_last_backup_at)}</b> - ${escapeHtml(s.gdrive_last_backup_status || '')}`;
}

async function saveGDriveBackupSettings() {
  const payload = {
    gdrive_service_account_json_path: document.getElementById('gdBackupJsonPath').value.trim(),
    gdrive_backup_folder_id: document.getElementById('gdBackupFolderId').value.trim(),
  };
  try {
    await api('/api/backup/gdrive', { method: 'POST', body: JSON.stringify(payload) });
    toast('تم حفظ إعدادات النسخ الاحتياطي');
  } catch (e) {
    toast('فشل الحفظ', true);
  }
}

async function runGDriveBackup() {
  await saveGDriveBackupSettings();
  const box = document.getElementById('gdBackupResult');
  box.innerHTML = '<span class="spinner"></span> جارٍ رفع النسخة الاحتياطية...';
  try {
    const res = await fetch('/api/backup/gdrive/run', { method: 'POST' });
    const data = await res.json();
    if (!data.ok) { box.innerHTML = `<div class="alert alert-error">${escapeHtml(data.error || 'فشل النسخ الاحتياطي')}</div>`; return; }
    box.innerHTML = `<div class="alert alert-success">تم رفع نسخة احتياطية بنجاح (${escapeHtml(data.filename)}).` +
      (data.webViewLink ? ` <a href="${escapeHtml(data.webViewLink)}" target="_blank" rel="noopener">فتح على Google Drive</a>` : '') + `</div>`;
    loadGDriveBackupSettings();
  } catch (e) {
    box.innerHTML = '<div class="alert alert-error">تعذّر الاتصال بالخادم أثناء النسخ الاحتياطي.</div>';
  }
}

function renderScheduleLastRun(s) {
  const el = document.getElementById('scheduleLastRun');
  if (!s.schedule_last_run_at) { el.textContent = 'لم تُشغَّل بعد'; return; }
  const okBadge = s.schedule_last_run_status === 'success'
    ? '<span class="badge badge-ontime">نجاح</span>' : '<span class="badge badge-absent">فشل</span>';
  el.innerHTML = `${okBadge} &nbsp; <b>${escapeHtml(s.schedule_last_run_at)}</b><br>${escapeHtml(s.schedule_last_run_message || '')}`;
}

async function saveScheduleSettings() {
  const days = Array.from(document.querySelectorAll('.schDay:checked')).map(cb => parseInt(cb.value, 10));
  const payload = {
    email_method: document.getElementById('schProvider').value === 'graph' ? 'graph' : 'smtp',
    smtp_provider: document.getElementById('schProvider').value === 'graph' ? 'microsoft' : document.getElementById('schProvider').value,
    smtp_security: document.getElementById('schSmtpSecurity').value,
    smtp_username: document.getElementById('schSmtpUsername').value.trim(),
    smtp_sender_name: document.getElementById('schSmtpSenderName').value.trim(),
    smtp_host: document.getElementById('schSmtpHost').value.trim(),
    smtp_port: document.getElementById('schSmtpPort').value.trim() || '587',
    smtp_sender_email: document.getElementById('schSmtpSender').value.trim(),
    smtp_sender_password: document.getElementById('schSmtpPassword').value,
    graph_tenant_id: document.getElementById('schGraphTenant').value.trim(),
    graph_client_id: document.getElementById('schGraphClientId').value.trim(),
    graph_client_secret: document.getElementById('schGraphClientSecret').value,
    graph_sender_upn: document.getElementById('schGraphSenderUpn').value.trim(),
    smtp_recipients: document.getElementById('schSmtpRecipients').value.trim(),
    schedule_enabled: document.getElementById('schEnabled').checked,
    schedule_time: document.getElementById('schTime').value || '07:00',
    schedule_pull_before: document.getElementById('schPullBefore').checked,
    schedule_status_filter: document.getElementById('schStatusFilter').value,
    schedule_days: days,
  };
  const box = document.getElementById('scheduleResult');
  try {
    await api('/api/schedule', { method: 'POST', body: JSON.stringify(payload) });
    box.innerHTML = '<div class="alert alert-success">تم حفظ إعدادات الجدولة والبريد.</div>';
    toast('تم الحفظ');
  } catch (e) {
    box.innerHTML = '<div class="alert alert-error">فشل الحفظ.</div>';
  }
}

async function testScheduleEmail() {
  await saveScheduleSettings();
  const box = document.getElementById('scheduleResult');
  box.innerHTML = '<div class="alert">جارٍ إرسال رسالة الاختبار...</div>';
  try {
    const data = await api('/api/schedule/test-email', { method: 'POST', body: '{}' });
    box.innerHTML = `<div class="alert alert-success">${escapeHtml(data.message)}</div>`;
  } catch (e) {
    box.innerHTML = '<div class="alert alert-error">فشل إرسال رسالة الاختبار - تحقق من إعدادات SMTP.</div>';
  }
}

async function runScheduleNow() {
  const box = document.getElementById('scheduleResult');
  box.innerHTML = '<div class="alert">جارٍ التشغيل (سحب/تحليل/إرسال)... قد يستغرق هذا بعض الوقت</div>';
  try {
    const res = await fetch('/api/schedule/run-now', { method: 'POST' });
    const data = await res.json();
    box.innerHTML = `<div class="alert ${data.ok ? 'alert-success' : 'alert-error'}">${escapeHtml(data.message || '')}</div>`;
    loadScheduleSettings();
  } catch (e) {
    box.innerHTML = '<div class="alert alert-error">تعذّر تشغيل الجدولة الآن.</div>';
  }
}

/* ============ USERS ============ */
/* ===== نفس افتراضات home.py (_apply_role_defaults) - تُعبَّأ تلقائياً
   عند اختيار الدور، وتبقى قابلة للتعديل اليدوي بعدها ===== */
const ROLE_PERMISSION_DEFAULTS = {
  admin: { PermEmployees: true, PermDepartments: true, PermDevices: true, PermSettings: true },
  dept_manager: { PermEmployees: true, PermDepartments: false, PermDevices: false, PermSettings: false },
  viewer: { PermEmployees: false, PermDepartments: false, PermDevices: false, PermSettings: false },
};
let DEPTS_CACHE = [];

function applyRoleDefaults(prefix) {
  const role = document.getElementById(prefix + 'Role').value;
  const defaults = ROLE_PERMISSION_DEFAULTS[role] || ROLE_PERMISSION_DEFAULTS.viewer;
  Object.keys(defaults).forEach(key => {
    const el = document.getElementById(prefix + key);
    if (el) el.checked = defaults[key];
  });
}

function _fillDeptMultiSelect(selectEl, selected) {
  if (!selectEl) return;
  const sel = new Set(selected || []);
  selectEl.innerHTML = DEPTS_CACHE.map(d =>
    `<option value="${escapeHtml(d)}" ${sel.has(d) ? 'selected' : ''}>${escapeHtml(d)}</option>`).join('');
}

function _readSelectedDepts(selectEl) {
  return Array.from(selectEl ? selectEl.selectedOptions : []).map(o => o.value);
}

function _readPermFields(prefix) {
  return {
    can_manage_employees: !!document.getElementById(prefix + 'PermEmployees')?.checked,
    can_manage_departments: !!document.getElementById(prefix + 'PermDepartments')?.checked,
    can_push_devices: !!document.getElementById(prefix + 'PermDevices')?.checked,
    can_edit_org_settings: !!document.getElementById(prefix + 'PermSettings')?.checked,
  };
}

async function addUser() {
  const payload = Object.assign({
    username: document.getElementById('usrUsername').value.trim(),
    full_name: document.getElementById('usrFullName').value.trim(),
    email: document.getElementById('usrEmail').value.trim(),
    password: document.getElementById('usrPassword').value,
    role: document.getElementById('usrRole').value,
    allowed_departments: _readSelectedDepts(document.getElementById('usrDepts')),
  }, _readPermFields('usr'));
  try {
    await api('/api/users', { method: 'POST', body: JSON.stringify(payload) });
    toast('تمت إضافة المستخدم');
    document.getElementById('usrUsername').value = '';
    document.getElementById('usrFullName').value = '';
    document.getElementById('usrPassword').value = '';
    loadUsers();
  } catch (e) {}
}

async function saveUserPerms(id) {
  const prefix = 'u' + id;
  const payload = Object.assign({
    role: document.getElementById(prefix + 'Role').value,
    allowed_departments: _readSelectedDepts(document.getElementById(prefix + 'Depts')),
  }, _readPermFields(prefix));
  try {
    await api('/api/users/' + id, { method: 'PUT', body: JSON.stringify(payload) });
    toast('تم تحديث الصلاحيات');
  } catch (e) {
    loadUsers(); // إعادة تحميل لإرجاع القيم لحالتها الفعلية عند الفشل
  }
}

async function changePassword() {
  const payload = {
    current_password: document.getElementById('curPassword').value,
    new_password: document.getElementById('newPassword').value,
  };
  try {
    await api('/api/change-password', { method: 'POST', body: JSON.stringify(payload) });
    toast('تم تحديث كلمة المرور');
    document.getElementById('curPassword').value = '';
    document.getElementById('newPassword').value = '';
  } catch (e) {}
}

async function loadUsers() {
  const data = await api('/api/users');
  if (!data) return;
  const tbody = document.getElementById('usersTable');
  tbody.innerHTML = data.rows.map(r => {
    const p = 'u' + r.id;
    return `
    <tr><td><input type="checkbox" class="row-check" data-id="${r.id}"></td><td dir="ltr" style="text-align:right">${escapeHtml(r.username)}</td><td>${escapeHtml(r.full_name || '')}
      <input type="email" dir="ltr" value="${escapeHtml(r.email || '')}" placeholder="البريد الإلكتروني" aria-label="البريد الإلكتروني" style="margin-top:6px;font-size:.8rem" onchange="saveUserEmail(${r.id}, this.value)"></td>
    <td>
      <select id="${p}Role" class="search-input" style="min-width:150px" onchange="applyRoleDefaults('${p}')">
        <option value="viewer" ${r.role === 'viewer' ? 'selected' : ''}>مشاهد (viewer)</option>
        <option value="dept_manager" ${r.role === 'dept_manager' ? 'selected' : ''}>مدير قسم (dept_manager)</option>
        <option value="admin" ${r.role === 'admin' ? 'selected' : ''}>مدير النظام (admin)</option>
      </select>
      <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:6px;font-size:.75rem;white-space:nowrap">
        <label style="display:flex;align-items:center;gap:4px;font-weight:normal"><input type="checkbox" id="${p}PermEmployees" ${r.can_manage_employees ? 'checked' : ''}> موظفين</label>
        <label style="display:flex;align-items:center;gap:4px;font-weight:normal"><input type="checkbox" id="${p}PermDepartments" ${r.can_manage_departments ? 'checked' : ''}> أقسام</label>
        <label style="display:flex;align-items:center;gap:4px;font-weight:normal"><input type="checkbox" id="${p}PermDevices" ${r.can_push_devices ? 'checked' : ''}> أجهزة</label>
        <label style="display:flex;align-items:center;gap:4px;font-weight:normal"><input type="checkbox" id="${p}PermSettings" ${r.can_edit_org_settings ? 'checked' : ''}> إعدادات</label>
      </div>
      <select id="${p}Depts" class="search-input" multiple size="3" style="margin-top:6px;height:auto;min-width:150px"></select>
      <button class="btn btn-primary btn-sm" onclick="saveUserPerms(${r.id})" style="margin-top:6px"><i class="fas fa-save" aria-hidden="true"></i> حفظ</button>
    </td>
    <td>${escapeHtml(r.created_at)}</td>
    <td style="white-space:nowrap"><button class="btn btn-outline btn-sm" title="كلمة مرور جديدة" aria-label="كلمة مرور جديدة" onclick="setUserPassword(${r.id}, '${escapeHtml(r.username)}')"><i class="fas fa-key" aria-hidden="true"></i></button>
      <button class="btn btn-red btn-sm" title="حذف" aria-label="حذف" onclick="deleteUser(${r.id})"><i class="fas fa-trash" aria-hidden="true"></i></button></td></tr>
  `;
  }).join('');
  data.rows.forEach(r => _fillDeptMultiSelect(document.getElementById('u' + r.id + 'Depts'), r.allowed_departments));
}

async function saveUserEmail(id, email) {
  const d = await api('/api/users/' + id, { method: 'PUT', body: JSON.stringify({ email }) });
  if (d) toast('حُفظ البريد');
}

async function setUserPassword(id, username) {
  const pw = prompt(`كلمة المرور الجديدة للمستخدم «${username}» (8 أحرف على الأقل):`);
  if (pw === null) return;
  if (pw.length < 8) { toast('كلمة المرور 8 أحرف على الأقل', true); return; }
  const d = await api('/api/users/' + id, { method: 'PUT', body: JSON.stringify({ new_password: pw }) });
  if (d) toast('تم تغيير كلمة المرور — سلّمها للمستخدم');
}

async function deleteUser(id) {
  if (!confirm('حذف هذا المستخدم؟')) return;
  try {
    await api('/api/users/' + id, { method: 'DELETE' });
    toast('تم الحذف');
    loadUsers();
  } catch (e) {}
}

/* ===== بدء التشغيل ===== */
document.addEventListener('DOMContentLoaded', () => {
  initTableFilters();
  initTableSorting();
  applyRolePermissions();
  loadMetaInto();
  loadStats();
  loadLastImportNotice();
  // نجلب الإعدادات فوراً (وليس فقط عند فتح تبويب "الإعدادات") حتى يظهر
  // زر "نشر ومزامنة" في تبويب "رفع البيانات" مباشرة لو هذه نسخة فرع مُعدَّة
  loadSettings();

  // ===== نستعيد التبويب المفتوح من عنوان الصفحة (#tab) لو موجود - يحصل
  // بعد إعادة تحميل الصفحة (F5) أو رجوع من فتح رابط مباشر بهذا التبويب.
  // replaceState (وليس push) حتى لا نضيف خطوة زائدة بتاريخ التصفّح =====
  applyRolePermissions();
  initNavGroups();
  if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
  let initialTab = decodeURIComponent((window.location.hash || '').replace('#', '')) || '';
  if (!initialTab) { try { initialTab = sessionStorage.getItem('att_last_tab') || 'dashboard'; } catch (e) { initialTab = 'dashboard'; } }
  history.replaceState({ tab: initialTab }, '', '#' + initialTab);
  showTab(initialTab, { skipHistory: true });

  // ===== تسجيل Service Worker لتفعيل "تثبيت التطبيق" (PWA) على أندرويد/
  // ويندوز - راجع static/sw.js لتفاصيل نطاق التخزين المؤقت المحدود عمداً =====
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {});
  }
});

// ===== نفس معالجة bfcache بصفحة تسجيل الدخول، لكن بالاتجاه المعاكس:
// لو صفحة لوحة التحكم نفسها ظهرت من ذاكرة المتصفح (bfcache) - مثلاً
// المستخدم سجَّل خروج في تبويب آخر ثم رجع بزر "رجوع" - نعيد تحميلها من
// السيرفر لضمان تحويلها لصفحة الدخول فوراً لو الجلسة لم تعد صالحة،
// بدل عرض لوحة تحكم قديمة مخزَّنة كأن المستخدم ما زال داخلاً =====
window.addEventListener('pageshow', (event) => {
  if (event.persisted) {
    window.location.reload();
  }
});

/* ===== قفل تمرير الخلفية عند فتح أي نافذة منبثقة (يشمل النوافذ التي تُضاف لاحقاً) ===== */
(function () {
  const SEL = '.modal-overlay.open, .sidebar-overlay.open';
  let y = 0;
  function update() {
    const lock = !!document.querySelector(SEL), h = document.documentElement;
    if (lock === h.classList.contains('modal-lock')) return;
    if (lock) { y = window.scrollY; h.classList.add('modal-lock'); }
    else { h.classList.remove('modal-lock'); window.scrollTo(0, y); }
  }
  new MutationObserver(update).observe(document.body, { subtree: true, attributes: true, attributeFilter: ['class'], childList: true });
  update();
})();


/* ===== أزرار المفضلة: الشريط السفلي (الهاتف) وأعلى القائمة الجانبية (الكمبيوتر) ===== */
const FAV_DEFAULT = ['dashboard', 'mobile-moves', 'reports', 'employees'];
let FAV = FAV_DEFAULT.slice(), FAV_DRAFT = [];
(function () {
  try { const raw = document.getElementById('mobileNav').dataset.fav; if (raw) FAV = JSON.parse(raw); } catch (e) {}
})();
function favSource(tab) {   // الزر الأصلي في القائمة — يحترم الصلاحيات (المخفي لا يُعرض)
  const b = document.querySelector(`.nav-item:not(.nav-fav)[data-tab="${tab}"]`);
  return b && b.style.display !== 'none' && !b.closest('[style*="display:none"]') ? b : null;
}
function favLabel(b) { return (b.textContent || '').trim(); }
function favIcon(b) { const i = b.querySelector('i'); return i ? i.className : 'fas fa-star'; }
function favRender() {
  const bar = document.getElementById('mobileNavItems'), side = document.getElementById('sideFavItems');
  if (!bar || !side) return;
  const menuBtn = bar.lastElementChild;
  bar.querySelectorAll('.mobile-nav-item[data-tab], .mobile-nav-fav-edit').forEach(e => e.remove());
  side.innerHTML = '';
  const tabs = FAV.filter(favSource);
  tabs.forEach(tab => {
    const src = favSource(tab), label = favLabel(src), icon = favIcon(src);
    const m = document.createElement('button');
    m.className = 'mobile-nav-item' + (tab === currentTab ? ' active' : ''); m.dataset.tab = tab; m.type = 'button';
    m.innerHTML = `<i class="${icon}" aria-hidden="true"></i><span>${escapeHtml(label)}</span>`;
    m.onclick = () => showTab(tab);
    bar.insertBefore(m, menuBtn);
    const sb = document.createElement('button');
    sb.className = 'nav-item nav-fav' + (tab === currentTab ? ' active' : ''); sb.dataset.tab = tab; sb.type = 'button';
    sb.innerHTML = `<i class="${icon}" aria-hidden="true"></i> ${escapeHtml(label)}`;
    sb.onclick = () => showTab(tab);
    side.appendChild(sb);
  });
  if (!tabs.length) side.innerHTML = '<div class="fav-empty">اضغط ✎ لإضافة صفحاتك المفضلة</div>';
  if (tabs.length) return;   // التخصيص متاح من أعلى القائمة (✎) — زر النجمة يظهر فقط عندما تكون المفضلة فارغة
  const ed = document.createElement('button');
  ed.className = 'mobile-nav-item mobile-nav-fav-edit'; ed.type = 'button'; ed.title = 'تخصيص المفضلة';
  ed.innerHTML = '<i class="fas fa-star" aria-hidden="true"></i><span>المفضلة</span>';
  ed.onclick = favOpen;
  bar.insertBefore(ed, menuBtn);
}
function favOpen() {
  FAV_DRAFT = FAV.filter(favSource);
  document.getElementById('favSearch').value = '';
  favRenderAll();
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('sidebarOverlay').classList.remove('open');
  document.getElementById('favModal').classList.add('open');
}
function favClose() { document.getElementById('favModal').classList.remove('open'); }
function favRenderAll() {
  const q = (document.getElementById('favSearch').value || '').trim().toLowerCase();
  const all = [...document.querySelectorAll('.nav-item:not(.nav-fav)[data-tab]')].filter(b => favSource(b.dataset.tab));
  document.getElementById('favCount').textContent = FAV_DRAFT.length;
  document.getElementById('favSel').innerHTML = FAV_DRAFT.map((tab, i) => {
    const b = favSource(tab);
    return `<div class="fav-row"><i class="${favIcon(b)}" aria-hidden="true"></i><span>${escapeHtml(favLabel(b))}</span>
      <button class="btn btn-outline btn-sm" onclick="favMove(${i},-1)" ${i === 0 ? 'disabled' : ''} aria-label="أعلى">▲</button>
      <button class="btn btn-outline btn-sm" onclick="favMove(${i},1)" ${i === FAV_DRAFT.length - 1 ? 'disabled' : ''} aria-label="أسفل">▼</button>
      <button class="btn btn-red btn-sm" onclick="favToggle('${tab}',false)" aria-label="إزالة">✕</button></div>`;
  }).join('') || '<div class="fav-empty">لا توجد صفحات مفضلة</div>';
  const shown = all.filter(b => !q || favLabel(b).toLowerCase().includes(q));
  document.getElementById('favAllCount').textContent = shown.length;
  document.getElementById('favAll').innerHTML = shown.map(b => {
    const tab = b.dataset.tab, on = FAV_DRAFT.includes(tab), full = !on && FAV_DRAFT.length >= 5;
    return `<label class="fav-row${full ? ' fav-off' : ''}"><input type="checkbox" ${on ? 'checked' : ''} ${full ? 'disabled' : ''} onchange="favToggle('${tab}',this.checked)">
      <i class="${favIcon(b)}" aria-hidden="true"></i><span>${escapeHtml(favLabel(b))}</span></label>`;
  }).join('');
}
function favToggle(tab, on) {
  FAV_DRAFT = FAV_DRAFT.filter(t => t !== tab);
  if (on && FAV_DRAFT.length < 5) FAV_DRAFT.push(tab);
  favRenderAll();
}
function favMove(i, d) {
  const j = i + d; if (j < 0 || j >= FAV_DRAFT.length) return;
  [FAV_DRAFT[i], FAV_DRAFT[j]] = [FAV_DRAFT[j], FAV_DRAFT[i]];
  favRenderAll();
}
function favReset() { FAV_DRAFT = FAV_DEFAULT.filter(favSource); favRenderAll(); }
async function favSave() {
  try {
    const d = await api('/api/my/favorites', { method: 'POST', body: JSON.stringify({ tabs: FAV_DRAFT }) });
    FAV = d.tabs || FAV_DRAFT;
    favRender(); favClose(); toast('تم حفظ المفضلة');
  } catch (e) { toast('تعذّر حفظ المفضلة', true); }
}
document.addEventListener('DOMContentLoaded', favRender);
if (document.readyState !== 'loading') favRender();


/* ===== الربط بين نسختين: دور النسخة يحدد الحقول الظاهرة ===== */
function syncRole() { const r = document.querySelector('input[name=syncRole]:checked'); return r ? r.value : 'none'; }
function syncRoleUi() {
  const role = syncRole();
  document.getElementById('syncFields').style.display = role === 'none' ? 'none' : '';
  document.getElementById('syncUrlBox').style.display = role === 'branch' ? '' : 'none';
  document.getElementById('syncKeyHint').textContent = role === 'central'
    ? 'أنشئ كلمة سر (زر التوليد) واحفظها، ثم اكتبها بنفس القيمة في إعدادات كل فرع.'
    : 'اكتب نفس كلمة السر المحفوظة في النسخة الرئيسية.';
  document.querySelectorAll('.sync-roles label').forEach(l => l.classList.toggle('on', l.querySelector('input').checked));
}
function syncKeyShow() { const k = document.getElementById('setSyncKey'); k.type = k.type === 'password' ? 'text' : 'password'; }
function syncKeyGen() {
  const a = new Uint8Array(24); crypto.getRandomValues(a);
  const k = document.getElementById('setSyncKey');
  k.value = Array.from(a, b => b.toString(16).padStart(2, '0')).join(''); k.type = 'text'; k.select();
  toast('تم توليد كلمة سر — احفظ الإعدادات ثم انسخها إلى النسخة الأخرى');
}


/* ===== تطبيق الإدارة على أندرويد: إشعارات في شريط الهاتف (تنبيهات التواجد، طلبات الخروج، …) ===== */
(function () {
  const N = window.AttNative;
  if (!N || typeof N.setNotifyToken !== 'function') return;
  try {
    if (!N.hasNotifyToken()) {
      fetch('/api/my/notify-token', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' } })
        .then(r => r.json()).then(d => { if (d && d.ok && d.token) N.setNotifyToken(d.token); }).catch(() => {});
    }
  } catch (e) {}
  document.addEventListener('click', e => {
    const a = e.target.closest && e.target.closest('a[href$="/logout"]');
    if (a && typeof N.clearNotifyToken === 'function') { try { N.clearNotifyToken(); } catch (x) {} }
  }, true);
})();
