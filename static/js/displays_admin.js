/* =====================================================================
   شاشات العرض (مشاهدة فقط برابط سري) — صفحة الإدارة (لمدير النظام)
   ===================================================================== */
let dsData = null, dsDeptSel = new Set(), dsEmpSel = new Set();
const dsEsc = s => escapeHtml(s == null ? '' : String(s));

async function dsLoad() {
  if (document.body.dataset.role !== 'admin') return;
  const d = await api('/api/displays');
  if (!d) return;
  dsData = d;
  dsDeptRender(); dsEmpRender();
  document.getElementById('dsTable').innerHTML = d.rows.map(r => {
    const what = r.kind === 'attendance'
      ? ((r.config.depts || []).length ? r.config.depts.map(dsEsc).join('، ') : 'كل الأقسام') + (r.config.show_names === false ? ' — أرقام فقط' : '')
      : r.employee_names.map(dsEsc).join('، ');
    return `<tr>
      <td><b>${dsEsc(r.name)}</b><br><small style="color:var(--muted)">كل ${r.config.refresh || 30} ث</small></td>
      <td>${dsEsc(r.kind_label)}</td><td style="max-width:280px">${what}</td>
      <td><small>${r.last_view_at ? dsEsc(r.last_view_at.slice(5, 16)) + '<br><span dir="ltr" style="color:var(--muted)">' + dsEsc(r.last_view_ip || '') + '</span>' : '<span style="color:var(--muted)">لم تُفتح بعد</span>'}</small></td>
      <td>${r.active ? '<span style="color:#0a6640;font-weight:700">مفعّلة</span>' : '<span style="color:#c0392b;font-weight:700">متوقفة</span>'}</td>
      <td style="white-space:nowrap">
        <button class="btn btn-primary btn-sm" onclick="dsCopy(${r.id})" title="نسخ الرابط"><i class="fas fa-copy" aria-hidden="true"></i> نسخ الرابط</button>
        <a class="btn btn-outline btn-sm" href="${dsEsc(r.url)}" target="_blank" rel="noopener" title="فتح"><i class="fas fa-up-right-from-square" aria-hidden="true"></i></a>
        <button class="btn btn-outline btn-sm" onclick="dsEdit(${r.id})" title="تعديل" aria-label="تعديل"><i class="fas fa-pen" aria-hidden="true"></i></button>
        <button class="btn btn-outline btn-sm" onclick="dsAct(${r.id}, '${r.active ? 'disable' : 'enable'}')">${r.active ? 'إيقاف' : 'تفعيل'}</button>
        <button class="btn btn-outline btn-sm" onclick="dsAct(${r.id}, 'regen')" title="رابط جديد — يتوقف القديم فوراً"><i class="fas fa-rotate" aria-hidden="true"></i></button>
        <button class="btn btn-red btn-sm" onclick="dsAct(${r.id}, 'delete')" title="حذف" aria-label="حذف"><i class="fas fa-trash" aria-hidden="true"></i></button>
      </td></tr>`;
  }).join('') || '<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:16px">لا توجد شاشات بعد</td></tr>';
}

function dsKindUi() {
  const k = document.getElementById('dsKind').value;
  document.getElementById('dsAttBox').style.display = k === 'attendance' ? '' : 'none';
  document.getElementById('dsTrkBox').style.display = k === 'tracking' ? '' : 'none';
  const r = document.getElementById('dsRefresh');
  if (!document.getElementById('dsId').value) r.value = k === 'attendance' ? 30 : 5;
}
function dsDeptRender() {
  if (!dsData) return;
  document.getElementById('dsDepts').innerHTML = dsData.depts.map(d =>
    `<button type="button" class="${dsDeptSel.has(d) ? 'on' : ''}" onclick="dsDeptToggle(${JSON.stringify(d).replace(/"/g, '&quot;')})">${dsEsc(d)}</button>`).join('')
    || '<span style="color:var(--muted)">لا توجد أقسام</span>';
}
function dsDeptToggle(d) { dsDeptSel.has(d) ? dsDeptSel.delete(d) : dsDeptSel.add(d); dsDeptRender(); }
function dsEmpRender() {
  if (!dsData) return;
  const q = (document.getElementById('dsEmpSearch').value || '').trim().toLowerCase();
  document.getElementById('dsEmps').innerHTML = dsData.trackable.filter(e => !q || e.name.toLowerCase().includes(q) || (e.dept || '').toLowerCase().includes(q))
    .map(e => `<label style="display:flex;gap:8px;align-items:center;padding:4px 0"><input type="checkbox" ${dsEmpSel.has(e.id) ? 'checked' : ''} onchange="this.checked ? dsEmpSel.add(${e.id}) : dsEmpSel.delete(${e.id})">
      <b>${dsEsc(e.name)}</b> <small style="color:var(--muted)">${dsEsc(e.dept || '')}</small>${e.always_track ? ' <small style="color:var(--primary)">(تتبع مستمر)</small>' : ''}</label>`).join('')
    || '<span style="color:var(--muted)">لا يوجد موظفون بحسابات تطبيق</span>';
}
function dsReset() {
  document.getElementById('dsId').value = ''; document.getElementById('dsName').value = '';
  dsDeptSel = new Set(); dsEmpSel = new Set();
  document.getElementById('dsNames').checked = true; document.getElementById('dsTrail').checked = true;
  document.getElementById('dsSaveLbl').textContent = 'إنشاء الشاشة'; document.getElementById('dsCancel').style.display = 'none';
  dsKindUi(); dsDeptRender(); dsEmpRender();
}
function dsEdit(id) {
  const r = dsData.rows.find(x => x.id === id); if (!r) return;
  document.getElementById('dsId').value = r.id; document.getElementById('dsName').value = r.name;
  document.getElementById('dsKind').value = r.kind; document.getElementById('dsRefresh').value = r.config.refresh || 30;
  dsDeptSel = new Set(r.config.depts || []); dsEmpSel = new Set(r.config.employees || []);
  document.getElementById('dsNames').checked = r.config.show_names !== false; document.getElementById('dsTrail').checked = r.config.trail !== false;
  document.getElementById('dsSaveLbl').textContent = 'حفظ التعديل'; document.getElementById('dsCancel').style.display = '';
  dsKindUi(); dsDeptRender(); dsEmpRender();
  document.getElementById('dsName').scrollIntoView({ behavior: 'smooth', block: 'center' });
}
async function dsSave() {
  const kind = document.getElementById('dsKind').value;
  const body = { id: document.getElementById('dsId').value || null, name: document.getElementById('dsName').value.trim(), kind,
    refresh: +document.getElementById('dsRefresh').value || (kind === 'attendance' ? 30 : 5),
    depts: [...dsDeptSel], show_names: document.getElementById('dsNames').checked,
    employees: [...dsEmpSel], trail: document.getElementById('dsTrail').checked };
  const d = await api('/api/displays', { method: 'POST', body: JSON.stringify(body) });
  if (!d) return;
  toast(body.id ? 'حُفظت الشاشة' : 'أُنشئت الشاشة — انسخ رابطها من الجدول');
  dsReset(); dsLoad();
}
async function dsAct(id, action) {
  const msg = { delete: 'حذف هذه الشاشة نهائياً؟ يتوقف رابطها.', regen: 'إنشاء رابط جديد؟ يتوقف الرابط الحالي فوراً على كل الشاشات المفتوحة.', disable: 'إيقاف الشاشة؟' }[action];
  if (msg && !confirm(msg)) return;
  const d = await api(`/api/displays/${id}/${action}`, { method: 'POST' });
  if (d) { toast('تم'); dsLoad(); }
}
function dsCopy(id) {
  const r = dsData.rows.find(x => x.id === id); if (!r) return;
  const done = () => toast('نُسخ الرابط — افتحه على الشاشة');
  if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(r.url).then(done).catch(() => prompt('انسخ الرابط:', r.url));
  else prompt('انسخ الرابط:', r.url);
}

if (typeof PAGE_TITLES !== 'undefined') PAGE_TITLES.displays = 'شاشات العرض (مشاهدة فقط)';
window.EXTRA_LOADERS = Object.assign(window.EXTRA_LOADERS || {}, { displays: () => { dsLoad(); dsKindUi(); } });
