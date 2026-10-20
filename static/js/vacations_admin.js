/* =====================================================================
   الإجازات وأرصدتها — صفحة الإدارة (لا احتساب مالي)
   يعتمد على: api() و toast() و escapeHtml() من app.js
   ===================================================================== */
let vaTypesCache = [], vaBalData = null;
const vaEsc = s => escapeHtml(s == null ? '' : String(s));

async function vaLoad() {
  const p = new URLSearchParams({ status: document.getElementById('vaStatus').value, type_id: document.getElementById('vaType').value,
    from: document.getElementById('vaFrom').value, to: document.getElementById('vaTo').value });
  let d;
  try { d = await (await fetch('/api/vacations?' + p, { credentials: 'same-origin' })).json(); } catch (e) { return; }
  if (!d || !d.ok) return;
  vaTypesCache = d.types;
  const nb = document.getElementById('vaNavBadge'); if (nb) { nb.classList.toggle('hide', !d.pending); nb.textContent = d.pending; }
  const pc = document.getElementById('vaPending'); if (!pc) return;
  pc.textContent = d.pending;
  const ts = document.getElementById('vaType'), keep = ts.value;
  ts.innerHTML = '<option value="">كل الأنواع</option>' + d.types.map(t => `<option value="${t.id}">${vaEsc(t.name)}</option>`).join('');
  ts.value = keep;
  const at = document.getElementById('vaAddType'), keep2 = at.value;
  at.innerHTML = d.types.filter(t => t.active).map(t => `<option value="${t.id}">${vaEsc(t.name)}</option>`).join('');
  if (keep2) at.value = keep2;
  document.getElementById('vaTable').innerHTML = d.rows.map(r => `<tr>
    <td>${['pending', 'approved'].includes(r.status) ? `<input type="checkbox" class="va-check" data-id="${r.id}" aria-label="تحديد">` : ''}</td>
    <td><b>${vaEsc(r.name)}</b><br><small style="color:var(--muted)">${vaEsc(r.dept)}</small></td>
    <td>${vaEsc(r.type_name)}</td><td dir="ltr">${vaEsc(r.date_from)}</td><td dir="ltr">${vaEsc(r.date_to)}</td><td><b>${r.days}</b></td>
    <td>${vaEsc(r.reason)}${r.decision_note ? `<br><small style="color:var(--muted)">ملاحظة: ${vaEsc(r.decision_note)}</small>` : ''}</td>
    <td>${vaEsc(r.status_label)}${r.decided_by ? `<br><small style="color:var(--muted)">${vaEsc(r.decided_by)}</small>` : ''}</td>
    <td>${r.source === 'admin' ? 'الإدارة' : 'التطبيق'}</td></tr>`).join('')
    || '<tr><td colspan="9" style="text-align:center;color:var(--muted);padding:14px">لا توجد إجازات مطابقة</td></tr>';
  vaTypesRender();
}

async function vaDecide(action, force) {
  const ids = [...document.querySelectorAll('.va-check:checked')].map(c => +c.dataset.id);
  if (!ids.length) { toast('حدّد طلباً واحداً على الأقل', true); return; }
  const label = { approve: 'موافقة على', reject: 'رفض', cancel: 'إلغاء' }[action];
  if (!force && !confirm(`${label} ${ids.length} إجازة؟`)) return;
  const d = await api('/api/vacations/decide', { method: 'POST', body: JSON.stringify({ ids, action, force: !!force, note: document.getElementById('vaNote').value }) });
  if (!d) return;
  if (d.errors && d.errors.length) {
    if (confirm('لم تُعتمد هذه الطلبات:\n' + d.errors.join('\n') + '\n\nاعتمادها رغم ذلك (تجاوز الرصيد)؟')) return vaDecide(action, true);
  }
  toast(`تم: ${d.count}`);
  document.getElementById('vaNote').value = '';
  vaLoad(); vaBalances();
}

async function vaAdd(force) {
  const body = { name: document.getElementById('vaEmp').value.trim(), type_id: document.getElementById('vaAddType').value,
    date_from: document.getElementById('vaAddFrom').value, date_to: document.getElementById('vaAddTo').value || document.getElementById('vaAddFrom').value,
    reason: document.getElementById('vaAddReason').value, force: !!force };
  const res = await fetch('/api/vacations', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const d = await res.json().catch(() => null);
  if (!d) return;
  if (!d.ok) {
    if (d.can_force && confirm(d.error + '\n\nتسجيلها رغم تجاوز الرصيد؟')) return vaAdd(true);
    if (!d.can_force) toast(d.error, true);
    return;
  }
  toast(`سُجّلت الإجازة (${d.days} يوم عمل)`);
  ['vaEmp', 'vaAddFrom', 'vaAddTo', 'vaAddReason'].forEach(id => { document.getElementById(id).value = ''; });
  vaLoad(); vaBalances();
}

async function vaBalances() {
  const y = document.getElementById('vaYear');
  if (!y.value) y.value = new Date().getFullYear();
  const d = await api('/api/vacations/balances?year=' + y.value);
  if (!d) return;
  vaBalData = d;
  document.getElementById('vaEmpList').innerHTML = d.rows.map(r => `<option value="${vaEsc(r.name)}">${vaEsc(r.dept)}</option>`).join('');
  vaBalRender();
}
function vaBalRender() {
  if (!vaBalData) return;
  const q = (document.getElementById('vaBalSearch').value || '').trim().toLowerCase();
  document.getElementById('vaBalHead').innerHTML = '<tr><th>الموظف</th><th>القسم</th>' + vaBalData.types.map(t => `<th>${vaEsc(t.name)}</th>`).join('') + '</tr>';
  const admin = document.body.dataset.role === 'admin';
  document.getElementById('vaBalBody').innerHTML = vaBalData.rows.filter(r => !q || r.name.toLowerCase().includes(q) || r.dept.toLowerCase().includes(q))
    .map(r => `<tr><td><b>${vaEsc(r.name)}</b></td><td>${vaEsc(r.dept)}</td>` + r.b.map(b => {
      const over = !b.unlimited && b.used > b.quota;
      const txt = `${b.used} / ${b.unlimited ? '∞' : b.quota}` + (b.pending ? ` <small style="color:var(--muted)">(${b.pending})</small>` : '');
      return `<td${admin ? ` style="cursor:pointer" title="تحديد رصيد خاص" onclick="vaQuota(${r.id}, ${b.type_id}, ${JSON.stringify(r.name).replace(/"/g, '&quot;')}, ${JSON.stringify(b.name).replace(/"/g, '&quot;')}, ${b.quota})"` : ''}${over ? ' class="va-over"' : ''}>${over ? `<b style="color:#c0392b">${txt}</b>` : txt}</td>`;
    }).join('') + '</tr>').join('') || `<tr><td colspan="${vaBalData.types.length + 2}" style="color:var(--muted)">لا يوجد موظفون</td></tr>`;
}
async function vaQuota(empId, typeId, name, typeName, cur) {
  const v = prompt(`رصيد «${typeName}» لـ ${name} لسنة ${vaBalData.year} (اتركه فارغاً للعودة لرصيد النوع):`, cur);
  if (v === null) return;
  if (v.trim() !== '' && (isNaN(+v) || +v < 0)) { toast('اكتب رقماً صحيحاً', true); return; }
  const d = await api('/api/vacations/quota', { method: 'POST', body: JSON.stringify({ employee_id: empId, type_id: typeId, year: vaBalData.year, days: v.trim() }) });
  if (d) { toast('تم'); vaBalances(); }
}

function vaTypesRender() {
  const admin = document.body.dataset.role === 'admin';
  const dis = admin ? '' : 'disabled';
  const row = t => `<tr data-id="${t.id || ''}">
    <td><input type="text" class="search-input va-t-name" value="${vaEsc(t.name || '')}" ${dis} placeholder="اسم نوع جديد" style="min-width:120px"></td>
    <td><input type="number" class="search-input va-t-quota" value="${t.quota_days ?? 0}" min="0" step="0.5" ${dis} style="width:90px;min-width:0"></td>
    <td><input type="checkbox" class="va-t-paid" ${t.paid ? 'checked' : ''} ${dis}></td>
    <td><input type="checkbox" class="va-t-appr" ${t.requires_approval ?? 1 ? 'checked' : ''} ${dis}></td>
    <td><input type="checkbox" class="va-t-emp" ${t.employee_request ?? 1 ? 'checked' : ''} ${dis}></td>
    <td><input type="checkbox" class="va-t-active" ${t.active ?? 1 ? 'checked' : ''} ${dis}></td>
    <td>${admin ? `<button class="btn btn-primary btn-sm" onclick="vaTypeSave(this)"><i class="fas fa-save" aria-hidden="true"></i></button>` : ''}</td></tr>`;
  document.getElementById('vaTypes').innerHTML = vaTypesCache.map(row).join('') + (admin ? row({ paid: 1 }) : '');
}
async function vaTypeSave(btn) {
  const tr = btn.closest('tr'), g = c => tr.querySelector(c);
  const body = { id: tr.dataset.id ? +tr.dataset.id : null, name: g('.va-t-name').value.trim(), quota_days: g('.va-t-quota').value,
    paid: g('.va-t-paid').checked, requires_approval: g('.va-t-appr').checked, employee_request: g('.va-t-emp').checked, active: g('.va-t-active').checked };
  const d = await api('/api/vacation-types', { method: 'POST', body: JSON.stringify(body) });
  if (d) { toast('تم الحفظ'); vaLoad(); vaBalances(); }
}

async function vaSetting(key, on) {
  const d = await api('/api/settings', { method: 'POST', body: JSON.stringify({ [key]: on ? '1' : '0' }) });
  if (d) toast(on ? 'تم التفعيل' : 'تم الإيقاف');
}
async function vaSettingsLoad() {
  const d = await api('/api/settings');
  if (!d) return;
  document.getElementById('vaEnabled').checked = d.settings.vacations_enabled !== '0';
  document.getElementById('vaEmpReq').checked = d.settings.vacations_employee_request !== '0';
}

if (typeof PAGE_TITLES !== 'undefined') PAGE_TITLES.vacations = 'الإجازات وأرصدتها';
window.EXTRA_LOADERS = Object.assign(window.EXTRA_LOADERS || {}, { vacations: () => { vaSettingsLoad(); vaLoad(); vaBalances(); } });
document.addEventListener('DOMContentLoaded', () => { vaLoad(); setInterval(vaLoad, 120000); });
