/* المناوبات المسمّاة وإسنادها للموظفين (shifts.py) */
let NSH = { shifts: [], assignments: [], employees: [], weekdays: [], editId: null, statFilter: '', nsaFilter: '', picked: new Set() };
const nsT = x => (window.T && window.UI_LANG === 'en' ? window.T(x) : x);
const nsEsc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

async function nsLoad() {
  let d;
  try { d = await api('/api/shifts'); } catch (e) { return; }
  if (d) nsApply(d);
}

function nsApply(d) {
  NSH.shifts = d.shifts; NSH.assignments = d.assignments; NSH.employees = d.employees; NSH.weekdays = d.weekdays;
  const days = document.getElementById('nsDays');
  if (!days.querySelector('input')) {
    days.innerHTML = d.weekdays.map(w => `<label class="ns-day"><input type="checkbox" value="${w.d}"> <span>${nsEsc(nsT(w.name))}</span></label>`).join('');
  }
  const from = document.getElementById('nsaFrom');
  if (!from.value) from.value = d.today;
  const sel = document.getElementById('nsaShift'), keep = sel.value;
  sel.innerHTML = '<option value="">— اختر المناوبة —</option>' + d.shifts.filter(s => s.active).map(s =>
    `<option value="${s.id}">${nsEsc(s.name)} (\u2066${s.start}–${s.end}\u2069)</option>`).join('');
  sel.value = keep;
  const dept = document.getElementById('nsaDept'), dk = dept.value;
  const depts = [...new Set(d.employees.map(e => e.dept).filter(Boolean))].sort();
  dept.innerHTML = '<option value="">كل الأقسام</option>' + depts.map(x => `<option>${nsEsc(x)}</option>`).join('');
  dept.value = dk;
  nsRender(); nsaRenderEmps(); nsaRender();
}

/* ---------- المناوبات ---------- */
function nsRender() {
  const rows = NSH.shifts;
  document.getElementById('nsCount').textContent = rows.length;
  const n = f => rows.filter(f).length;
  document.getElementById('nsStats').innerHTML = [
    ['', rows.length, 'كل المناوبات', ''], ['green', n(s => s.active), 'مفعّلة', 'active'],
    ['orange', n(s => !s.active), 'معطّلة', 'inactive'], ['', n(s => s.overnight), 'ليلية', 'overnight'],
  ].map(([c, v, l, f]) => `<div class="stat-card ${c}${NSH.statFilter === f ? ' active' : ''}" style="cursor:pointer" onclick="nsStat('${f}')">
      <div class="stat-val" dir="ltr">${v}</div><div class="stat-label">${l}</div></div>`).join('');
  const show = s => !NSH.statFilter || (NSH.statFilter === 'active' ? s.active : NSH.statFilter === 'inactive' ? !s.active : s.overnight);
  document.getElementById('nsRows').innerHTML = rows.map(s => `<tr${show(s) ? '' : ' data-hidden-status="1" style="display:none"'}>
      <td><input type="checkbox" class="ns-cb" data-id="${s.id}" aria-label="تحديد" onchange="nsSel()"></td>
      <td><b>${nsEsc(s.name)}</b>${s.overnight ? ' <span class="badge badge-late">ليلية</span>' : ''}</td>
      <td dir="ltr">${s.start}</td><td dir="ltr">${s.end}</td><td>${nsEsc(s.days.length ? NSH.weekdays.filter(w => s.days.includes(w.d)).map(w => nsT(w.name)).join(window.UI_LANG === 'en' ? ', ' : '، ') : nsT(s.days_label))}</td>
      <td><a href="#" onclick="nsaShowShift(${s.id});return false">${s.current}</a></td>
      <td><span class="badge ${s.active ? 'badge-ontime' : 'badge-absent'}">${s.active ? 'مفعّلة' : 'معطّلة'}</span></td>
      <td><button class="btn btn-outline btn-sm" onclick="nsEdit(${s.id})" aria-label="تعديل"><i class="fas fa-pen" aria-hidden="true"></i></button></td></tr>`).join('')
    || '<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:14px">لا توجد مناوبات — أضف مناوبة من النموذج أعلاه</td></tr>';
  nsSel();
  if (typeof applyAllTableFilters === 'function') applyAllTableFilters();
  document.querySelectorAll('#nsRows tr[data-hidden-status]').forEach(tr => { tr.style.display = 'none'; });
}
function nsStat(f) { NSH.statFilter = NSH.statFilter === f ? '' : f; nsRender(); }
function nsSel() { document.getElementById('nsSel').textContent = document.querySelectorAll('.ns-cb:checked').length; }
function nsCheckAll(on) { document.querySelectorAll('.ns-cb').forEach(c => { if (c.closest('tr').style.display !== 'none') c.checked = on; }); nsSel(); }

function nsNew() {
  NSH.editId = null;
  ['nsName', 'nsStart', 'nsEnd'].forEach(id => { document.getElementById(id).value = ''; });
  document.querySelectorAll('#nsDays input').forEach(c => { c.checked = false; });
  document.getElementById('nsSaveLbl').textContent = 'إضافة مناوبة';
  document.getElementById('nsNewBtn').classList.add('hide');
}

function nsEdit(id) {
  const s = NSH.shifts.find(x => x.id === id);
  if (!s) return;
  NSH.editId = id;
  document.getElementById('nsName').value = s.name;
  document.getElementById('nsStart').value = s.start;
  document.getElementById('nsEnd').value = s.end;
  document.querySelectorAll('#nsDays input').forEach(c => { c.checked = s.days.includes(+c.value); });
  document.getElementById('nsSaveLbl').textContent = 'حفظ التعديل';
  document.getElementById('nsNewBtn').classList.remove('hide');
  document.getElementById('nsName').scrollIntoView({ block: 'center', behavior: 'smooth' });
}

async function nsSave() {
  const cur = NSH.shifts.find(x => x.id === NSH.editId);
  const body = {
    id: NSH.editId, name: document.getElementById('nsName').value, start: document.getElementById('nsStart').value,
    end: document.getElementById('nsEnd').value, active: cur ? cur.active : true,
    days: [...document.querySelectorAll('#nsDays input:checked')].map(c => +c.value),
  };
  let d;
  try { d = await api('/api/shifts', { method: 'POST', body: JSON.stringify(body) }); } catch (e) { return; }
  if (!d) return;
  toast(NSH.editId ? 'حُفظ التعديل وأُعيد بناء التقارير' : 'أُضيفت المناوبة — أسندها للموظفين من الأسفل');
  nsNew();
  nsApply(d);
}

async function nsBulk() {
  const action = document.getElementById('nsAction').value;
  const ids = [...document.querySelectorAll('.ns-cb:checked')].filter(c => c.closest('tr').style.display !== 'none').map(c => +c.dataset.id);
  if (!action) { toast('اختر الإجراء', true); return; }
  if (!ids.length) { toast('حدّد مناوبة واحدة على الأقل', true); return; }
  const verb = { activate: 'تفعيل', deactivate: 'تعطيل', delete: 'حذف' }[action];
  if (!confirm(`${verb} ${ids.length} من المناوبات؟`)) return;
  let d;
  try { d = await api('/api/shifts/bulk', { method: 'POST', body: JSON.stringify({ action, ids }) }); } catch (e) { return; }
  if (!d) return;
  if (d.warning) toast(d.warning, true); else toast(`تم: ${d.done}`);
  document.getElementById('nsAction').value = '';
  nsApply(d);
}

/* ---------- الإسناد ---------- */
function nsaRenderEmps() {
  document.getElementById('nsaEmps').innerHTML = NSH.employees.map(e =>
    `<label class="nsa-emp" data-q="${nsEsc((e.name + ' ' + e.dept).toLowerCase())}" data-dept="${nsEsc(e.dept)}">
      <input type="checkbox" value="${nsEsc(e.name)}"${NSH.picked.has(e.name) ? ' checked' : ''} onchange="nsaPick(this)"> ${nsEsc(e.name)}
      ${e.dept ? `<small>${nsEsc(e.dept)}</small>` : ''}</label>`).join('') || '<p style="color:var(--muted)">لا يوجد موظفون فعّالون</p>';
  nsaFilterEmps();
}
function nsaPick(cb) { if (cb.checked) NSH.picked.add(cb.value); else NSH.picked.delete(cb.value); document.getElementById('nsaPicked').textContent = NSH.picked.size; }
function nsaFilterEmps() {
  const q = document.getElementById('nsaSearch').value.trim().toLowerCase(), dept = document.getElementById('nsaDept').value;
  document.querySelectorAll('#nsaEmps .nsa-emp').forEach(l => {
    l.style.display = (!q || l.dataset.q.includes(q)) && (!dept || l.dataset.dept === dept) ? '' : 'none';
  });
  document.getElementById('nsaPicked').textContent = NSH.picked.size;
}
function nsaPickAll(on) {
  document.querySelectorAll('#nsaEmps .nsa-emp').forEach(l => {
    if (l.style.display === 'none') return;
    const cb = l.querySelector('input'); cb.checked = on; nsaPick(cb);
  });
}

async function nsaAssign() {
  const body = {
    shift_id: +document.getElementById('nsaShift').value, names: [...NSH.picked],
    date_from: document.getElementById('nsaFrom').value, date_to: document.getElementById('nsaTo').value,
  };
  if (!body.shift_id) { toast('اختر المناوبة', true); return; }
  if (!body.names.length) { toast('اختر موظفاً واحداً على الأقل', true); return; }
  let d;
  try { d = await api('/api/shifts/assign', { method: 'POST', body: JSON.stringify(body) }); } catch (e) { return; }
  if (!d) return;
  toast(`أُسندت المناوبة إلى ${d.done} وأُعيد بناء التقارير`);
  NSH.picked.clear();
  document.getElementById('nsaTo').value = '';
  nsApply(d);
}

function nsaRender() {
  const rows = NSH.assignments, n = st => rows.filter(r => r.status === st).length;
  document.getElementById('nsaCount').textContent = rows.length;
  document.getElementById('nsaStats').innerHTML = [
    ['', rows.length, 'كل الإسنادات', ''], ['green', n('current'), 'سارية', 'current'],
    ['', n('upcoming'), 'قادمة', 'upcoming'], ['orange', n('ended'), 'منتهية', 'ended'],
  ].map(([c, v, l, f]) => `<div class="stat-card ${c}${NSH.nsaFilter === f ? ' active' : ''}" style="cursor:pointer" onclick="nsaStat('${f}')">
      <div class="stat-val" dir="ltr">${v}</div><div class="stat-label">${l}</div></div>`).join('');
  const show = r => (!NSH.nsaFilter || (NSH.nsaFilter.startsWith('s:') ? r.shift_id === +NSH.nsaFilter.slice(2) && r.status === 'current' : r.status === NSH.nsaFilter));
  document.getElementById('nsaRows').innerHTML = rows.map(r => {
    const badge = r.status === 'current' ? 'badge-ontime' : (r.status === 'upcoming' ? 'badge-late' : 'badge-absent');
    return `<tr${show(r) ? '' : ' data-hidden-status="1" style="display:none"'}>
      <td><input type="checkbox" class="nsa-cb" data-id="${r.id}" aria-label="تحديد" onchange="nsaSel()"></td>
      <td><b>${nsEsc(r.name)}</b></td><td>${nsEsc(r.dept)}</td>
      <td>${nsEsc(r.shift)}${r.shift_active ? '' : ' <span class="badge badge-absent">معطّلة</span>'}</td>
      <td dir="ltr">${r.time}</td><td dir="ltr">${r.date_from}</td><td dir="ltr">${r.date_to || '—'}</td>
      <td><span class="badge ${badge}">${r.status_label}</span></td><td>${nsEsc(r.created_by) || '—'}</td></tr>`;
  }).join('') || '<tr><td colspan="9" style="text-align:center;color:var(--muted);padding:14px">لا توجد إسنادات بعد</td></tr>';
  nsaSel();
  if (typeof applyAllTableFilters === 'function') applyAllTableFilters();
  document.querySelectorAll('#nsaRows tr[data-hidden-status]').forEach(tr => { tr.style.display = 'none'; });
}
function nsaStat(f) { NSH.nsaFilter = NSH.nsaFilter === f ? '' : f; nsaRender(); }
function nsaShowShift(id) { NSH.nsaFilter = 's:' + id; nsaRender(); document.getElementById('nsaTable').scrollIntoView({ behavior: 'smooth' }); }
function nsaSel() { document.getElementById('nsaSel').textContent = document.querySelectorAll('.nsa-cb:checked').length; }
function nsaCheckAll(on) { document.querySelectorAll('.nsa-cb').forEach(c => { if (c.closest('tr').style.display !== 'none') c.checked = on; }); nsaSel(); }

async function nsaBulk() {
  const action = document.getElementById('nsaAction').value;
  const ids = [...document.querySelectorAll('.nsa-cb:checked')].filter(c => c.closest('tr').style.display !== 'none').map(c => +c.dataset.id);
  if (!action) { toast('اختر الإجراء', true); return; }
  if (!ids.length) { toast('حدّد إسناداً واحداً على الأقل', true); return; }
  const verb = { end: 'إنهاء', delete: 'حذف' }[action];
  if (!confirm(`${verb} ${ids.length} من الإسنادات؟`)) return;
  let d;
  try { d = await api('/api/shifts/assignments/bulk', { method: 'POST', body: JSON.stringify({ action, ids }) }); } catch (e) { return; }
  if (!d) return;
  toast(`تم: ${d.done} — وأُعيد بناء التقارير`);
  document.getElementById('nsaAction').value = '';
  nsApply(d);
}

window.EXTRA_LOADERS = Object.assign(window.EXTRA_LOADERS || {}, { shifts: nsLoad });
