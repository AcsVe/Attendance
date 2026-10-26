/* =====================================================================
   تثبيت النظام كتطبيق (PWA على Windows/أندرويد) + مراجعة صلاحيات المستخدمين
   ===================================================================== */
let pwaDeferred = null;
window.addEventListener('beforeinstallprompt', e => {
  e.preventDefault();
  pwaDeferred = e;
  const b = document.getElementById('pwaInstallBtn');
  if (b) b.style.display = '';
});
window.addEventListener('appinstalled', () => {
  const b = document.getElementById('pwaInstallBtn');
  if (b) b.style.display = 'none';
  toast('ثُبّت النظام كتطبيق — تجده في قائمة ابدأ وشريط المهام');
});
function pwaInstall() {
  if (!pwaDeferred) { toast('من قائمة المتصفح (⋮) اختر «تثبيت التطبيق» أو «Apps ← Install»', true); return; }
  pwaDeferred.prompt();
  pwaDeferred = null;
}

/* ================= مراجعة الصلاحيات ================= */
let urRows = [], urRole = '';
const UR_ROLE = { admin: 'مدير النظام', dept_manager: 'مدير قسم', viewer: 'اطّلاع فقط' };

async function loadUsersReview() {
  if (document.body.dataset.role !== 'admin') return;
  const d = await api('/api/users/review');
  if (!d) return;
  urRows = d.rows;
  urRender();
}

function urRender() {
  const q = (document.getElementById('urSearch').value || '').trim().toLowerCase();
  const counts = { '': urRows.length, admin: 0, dept_manager: 0, viewer: 0, restricted: 0, never: 0 };
  urRows.forEach(r => { counts[r.role] = (counts[r.role] || 0) + 1; if (r.allowed_departments.length) counts.restricted++; if (!r.last_login_at) counts.never++; });
  const chip = (k, label) => `<button class="${urRole === k ? 'on' : ''}" onclick="urRole='${k}';urRender()">${label} <b>${counts[k]}</b></button>`;
  document.getElementById('urChips').innerHTML = chip('', 'الكل') + chip('admin', UR_ROLE.admin) + chip('dept_manager', UR_ROLE.dept_manager) +
    chip('viewer', UR_ROLE.viewer) + chip('restricted', 'مقيّدون بأقسام') + chip('never', 'لم يدخلوا أبداً');
  const rows = urRows.filter(r => {
    if (urRole === 'restricted' && !r.allowed_departments.length) return false;
    if (urRole === 'never' && r.last_login_at) return false;
    if (['admin', 'dept_manager', 'viewer'].includes(urRole) && r.role !== urRole) return false;
    return !q || [r.username, r.full_name, r.role, r.allowed_departments.join(' ')].some(v => (v || '').toLowerCase().includes(q));
  });
  const mark = (r, k) => r.effective[k] ? `<b style="color:${r[k] ? '#0a6640' : '#9aa'};font-size:1.1rem">✓</b>` : '<b style="color:#c0392b;font-size:1.1rem">✗</b>';
  document.getElementById('urShown').textContent = `${rows.length} من ${urRows.length}`;
  document.getElementById('urTable').innerHTML = rows.map(r => `<tr>
    <td><input type="checkbox" class="row-check" data-id="${r.id}" ${r.is_me ? 'disabled title="حسابك الحالي"' : ''} onchange="urCount()"></td>
    <td><b dir="ltr">${escapeHtml(r.username)}</b>${r.is_me ? ' <span class="badge badge-holiday">أنت</span>' : ''}<br><small style="color:var(--muted)">${escapeHtml(r.full_name || '')}</small></td>
    <td><span class="badge ${r.role === 'admin' ? 'badge-absent' : r.role === 'viewer' ? 'badge-none' : 'badge-late'}">${UR_ROLE[r.role] || r.role}</span></td>
    <td>${mark(r, 'can_manage_employees')}</td><td>${mark(r, 'can_push_devices')}</td><td>${mark(r, 'can_edit_org_settings')}</td><td>${mark(r, 'can_manage_departments')}</td>
    <td><small>${r.allowed_departments.length ? r.allowed_departments.map(escapeHtml).join('، ') : 'كل الأقسام'}</small></td>
    <td><small>${r.last_login_at ? escapeHtml(r.last_login_at) + '<br><span dir="ltr" style="color:var(--muted)">' + escapeHtml(r.last_login_ip || '') + '</span>' : '<span style="color:#c0392b">لم يدخل</span>'}</small></td></tr>`).join('')
    || '<tr><td colspan="9" style="text-align:center;color:var(--muted);padding:16px">لا يوجد مستخدمون مطابقون</td></tr>';
  document.getElementById('urAll').checked = false;
  urCount();
}

function urChecked() { return [...document.querySelectorAll('#urTable .row-check:checked')].map(c => +c.dataset.id); }
function urCount() { document.getElementById('urSel').textContent = `${urChecked().length} / ${document.querySelectorAll('#urTable .row-check').length}`; }

async function urBulk() {
  const ids = urChecked(), sel = document.getElementById('urAction');
  if (!ids.length) { toast('حدّد مستخدماً واحداً على الأقل', true); return; }
  if (!sel.value) { toast('اختر الإجراء', true); return; }
  const [action, value] = sel.value.split(':');
  if (!confirm(`${sel.options[sel.selectedIndex].text}\n(${ids.length} مستخدم)؟`)) return;
  const d = await api('/api/users/bulk', { method: 'POST', body: JSON.stringify({ ids, action, value: action === 'depts' ? [] : value }) });
  if (!d) return;
  toast(`تم: ${d.count} مستخدم`);
  loadUsersReview();
  if (typeof loadUsers === 'function') loadUsers();
}

function urExport() {
  const rows = [['المستخدم', 'الاسم', 'الدور', 'الموظفون', 'الأجهزة', 'الإعدادات', 'الأقسام', 'الأقسام المسموحة', 'آخر دخول', 'IP', 'تاريخ الإنشاء']].concat(
    urRows.map(r => [r.username, r.full_name || '', UR_ROLE[r.role] || r.role,
      ...['can_manage_employees', 'can_push_devices', 'can_edit_org_settings', 'can_manage_departments'].map(k => r.effective[k] ? 'نعم' : 'لا'),
      r.allowed_departments.join('، ') || 'كل الأقسام', r.last_login_at || 'لم يدخل', r.last_login_ip || '', r.created_at || '']));
  const csv = '﻿' + rows.map(r => r.map(v => `"${String(window.T ? T(String(v)) : v).replace(/"/g, '""')}"`).join(',')).join('\r\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  a.download = 'users-permissions.csv';
  a.click();
}

window.EXTRA_LOADERS = Object.assign(window.EXTRA_LOADERS || {}, {
  users: () => { if (typeof loadUsers === 'function') loadUsers(); loadUsersReview(); },
});


/* ================= أدوات الصيانة: حذف السجلات ================= */
function mtCount() {
  const boxes = Array.from(document.querySelectorAll('.mt-check'));
  const sel = boxes.filter(c => c.checked);
  const rows = sel.reduce((a, c) => a + (+c.dataset.count || 0), 0);
  document.getElementById('mtSel').textContent = `المحدَّد: ${sel.length} من ${boxes.length} — ${rows.toLocaleString('en')} سجل`;
  document.getElementById('mtAll').checked = sel.length && sel.length === boxes.length;
}
function _mtRender(groups) {
  const keep = new Set(Array.from(document.querySelectorAll('.mt-check:checked')).map(c => c.value));
  document.getElementById('mtTable').innerHTML = groups.map(g => `<tr>
    <td><input type="checkbox" class="mt-check" value="${g.key}" data-count="${g.count}" ${keep.has(g.key) ? 'checked' : ''} onchange="mtCount()" aria-label="${escapeHtml(g.label)}"></td>
    <td>${escapeHtml(g.label)}${g.dated ? '' : ' <small style="color:#c0392b">(كل الفترات — لا يتأثر بالتاريخ)</small>'}</td>
    <td><b>${g.count.toLocaleString('en')}</b></td></tr>`).join('');
  mtCount();
}
async function loadMaintenance() {
  const p = new URLSearchParams({ from: document.getElementById('mtFrom').value, to: document.getElementById('mtTo').value });
  const d = await api('/api/maintenance/counts?' + p);
  if (d) _mtRender(d.groups);
}
async function runPurge() {
  const groups = Array.from(document.querySelectorAll('.mt-check:checked')).map(c => c.value);
  if (!groups.length) { toast('اختر نوعاً واحداً على الأقل', true); return; }
  const confirmWord = document.getElementById('mtConfirm').value.trim();
  if (confirmWord !== 'حذف' && confirmWord.toUpperCase() !== 'DELETE') { toast('اكتب كلمة «حذف» في خانة التأكيد', true); return; }
  const from = document.getElementById('mtFrom').value, to = document.getElementById('mtTo').value;
  if (!confirm(`سيُحذف ${groups.length} نوع من السجلات ${from || to ? `للفترة ${from || 'البداية'} — ${to || 'اليوم'}` : 'لكل الفترات'}.\nتُحفظ نسخة احتياطية قبل الحذف. متابعة؟`)) return;
  const d = await api('/api/maintenance/purge', { method: 'POST', body: JSON.stringify({ groups, from, to, confirm: confirmWord }) });
  if (!d) return;
  document.getElementById('mtConfirm').value = '';
  document.querySelectorAll('.mt-check').forEach(c => { c.checked = false; });
  document.getElementById('mtResult').innerHTML = `<div style="background:#eef7f1;border-radius:10px;padding:10px 12px;line-height:1.9">✓ تم الحذف:<br>${d.done.map(escapeHtml).join('<br>')}<br><small style="color:var(--muted)">النسخة الاحتياطية: ${escapeHtml(d.backup)}</small></div>`;
  _mtRender(d.groups);
  toast('تم الحذف وإعادة التحليل');
}
window.EXTRA_LOADERS = Object.assign(window.EXTRA_LOADERS || {}, { maintenance: loadMaintenance });


/* ================= طلبات نسيان كلمة المرور (للمدير) ================= */
let rrRows = [];
async function rrLoad() {
  if (typeof CURRENT_ROLE === 'undefined' || CURRENT_ROLE !== 'admin') return;
  let d;
  try { d = await (await fetch('/api/reset-requests', { credentials: 'same-origin' })).json(); } catch (e) { return; }
  if (!d || !d.ok) return;
  rrRows = d.rows;
  const b = document.getElementById('rrBanner');
  b.classList.toggle('hide', !rrRows.length);
  b.style.display = rrRows.length ? 'flex' : 'none';
  document.getElementById('rrText').textContent = `طلبات نسيان كلمة المرور بانتظارك: ${rrRows.length}`;
  if (document.getElementById('rrModal').classList.contains('open')) rrRender();
}
function rrRender() {
  document.getElementById('rrTable').innerHTML = rrRows.map(r => `<tr>
    <td><b>${escapeHtml(r.name || '')}</b></td><td>${r.kind === 'emp' ? 'موظف' : ''} ${escapeHtml(r.dept || '')}</td>
    <td dir="ltr" style="text-align:right">${escapeHtml(r.label || '')}</td><td>${escapeHtml(r.created_at || '')}</td>
    <td style="white-space:nowrap"><button class="btn btn-primary btn-sm" onclick="rrAct(${r.id}, 'reset')"><i class="fas fa-key" aria-hidden="true"></i> كلمة مرور جديدة</button>
      <button class="btn btn-outline btn-sm" onclick="rrAct(${r.id}, 'dismiss')">تجاهل</button></td></tr>`).join('')
    || '<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:14px">لا توجد طلبات</td></tr>';
}
function rrOpen() { rrRender(); document.getElementById('rrModal').classList.add('open'); }
async function rrAct(id, action) {
  if (action === 'dismiss' && !confirm('تجاهل هذا الطلب؟')) return;
  const d = await api('/api/reset-requests/' + id, { method: 'POST', body: JSON.stringify({ action }) });
  if (!d) return;
  await rrLoad();
  if (d.credentials && d.credentials.length && typeof maShowCreds === 'function') {
    document.getElementById('rrModal').classList.remove('open');
    maShowCreds(d.credentials);
  } else toast('تم');
}
document.addEventListener('DOMContentLoaded', () => { rrLoad(); setInterval(rrLoad, 120000); });


/* ================= الكشف الشهري (للرواتب) ================= */
let moData = null;
function moParams(extra) {
  const p = new URLSearchParams({ month: document.getElementById('moMonth').value, dept: document.getElementById('moDept').value,
    grace: document.getElementById('moGrace').value || '0' });
  Object.entries(extra || {}).forEach(([k, v]) => p.set(k, v));
  return p;
}
async function loadMonthly() {
  const m = document.getElementById('moMonth');
  if (!m.value) { const t = new Date(); m.value = t.getFullYear() + '-' + String(t.getMonth() + 1).padStart(2, '0'); }
  const ds = document.getElementById('moDept');
  if (ds.options.length <= 1) {   // نفس قائمة أقسام التقارير
    const src = document.getElementById('repDept');
    if (src) [...src.options].slice(1).forEach(o => ds.add(new Option(o.text, o.value)));
  }
  const d = await api('/api/reports/monthly?' + moParams());
  if (!d) return;
  moData = d;
  renderMonthly();
}
function renderMonthly() {
  if (!moData) return;
  const q = (document.getElementById('moSearch').value || '').trim().toLowerCase();
  const cols = moData.cols;
  const warn = { absent: 1, late_minutes: 1, early_minutes: 1, no_out: 1 };
  document.getElementById('moHead').innerHTML = '<tr>' + cols.map(c => `<th>${escapeHtml(c.label)}</th>`).join('') + '</tr>';
  const rows = moData.rows.filter(r => !q || (r.name || '').toLowerCase().includes(q) || (r.dept || '').toLowerCase().includes(q));
  document.getElementById('moBody').innerHTML = rows.map(r => '<tr>' + cols.map(c => {
    const v = r[c.key];
    if (c.key === 'name') return `<td><a href="#" onclick="moOpenEmployee(${JSON.stringify(r.name).replace(/"/g, '&quot;')});return false"><b>${escapeHtml(v)}</b></a></td>`;
    const bad = warn[c.key] && v > 0;
    return `<td${bad ? ' style="color:#c0392b;font-weight:700"' : ''}>${escapeHtml(String(v ?? ''))}</td>`;
  }).join('') + '</tr>').join('') || `<tr><td colspan="${cols.length}" style="text-align:center;color:var(--muted);padding:16px">لا توجد بيانات محلّلة لهذا الشهر</td></tr>`;
  document.getElementById('moFoot').innerHTML = rows.length ? '<tr>' + cols.map((c, i) => `<td>${i === 0 ? 'المجموع (' + moData.rows.length + ')' : escapeHtml(String(moData.totals[c.key] ?? ''))}</td>`).join('') + '</tr>' : '';
}
function exportMonthly(fmt) { window.location.href = '/api/reports/monthly?' + moParams({ format: fmt }); }
/* من الكشف إلى تقرير الموظف التفصيلي لنفس الشهر */
function moOpenEmployee(name) {
  const m = document.getElementById('moMonth').value;
  const [y, mo] = m.split('-').map(Number);
  const last = new Date(y, mo, 0).getDate();
  showTab('reports');
  setTimeout(() => {
    const f = document.getElementById('repFrom'), t = document.getElementById('repTo'), s = document.getElementById('repSearch');
    if (f) f.value = m + '-01';
    if (t) t.value = m + '-' + String(last).padStart(2, '0');
    if (s) s.value = name;
    if (typeof loadReports === 'function') loadReports(1);
  }, 50);
}
if (typeof PAGE_TITLES !== 'undefined') PAGE_TITLES.monthly = 'الكشف الشهري لكل موظف';
window.EXTRA_LOADERS = Object.assign(window.EXTRA_LOADERS || {}, { monthly: loadMonthly });
