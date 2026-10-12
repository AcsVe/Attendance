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
  const csv = '﻿' + rows.map(r => r.map(v => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\r\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  a.download = 'users-permissions.csv';
  a.click();
}

window.EXTRA_LOADERS = Object.assign(window.EXTRA_LOADERS || {}, {
  users: () => { if (typeof loadUsers === 'function') loadUsers(); loadUsersReview(); },
});
