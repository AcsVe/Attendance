/* =====================================================================
   الرواتب (بديل MenaPAY) والربط مع MenaPAY / MenaITech — صفحة الإدارة
   الخادم: payroll.py. يعتمد على: api() و toast() و escapeHtml() و initTableSorting() من app.js
   ===================================================================== */
let prState = { rules: null, menapay: null, items: [], runs: [], run: null, profiles: [], editId: null, users: [] };
const prEsc = s => escapeHtml(s == null ? '' : String(s));
const prMoney = v => (Number(v) || 0).toLocaleString('en-US', { minimumFractionDigits: 3, maximumFractionDigits: 3 });
const prNum = v => { const n = parseFloat(v); return isNaN(n) ? 0 : n; };

function prSub(name) {
  document.querySelectorAll('#tab-payroll .pr-sub').forEach(p => p.classList.toggle('active', p.id === 'prsub-' + name));
  document.querySelectorAll('#tab-payroll .subtab-btn').forEach(b => b.classList.toggle('active', b.dataset.subtab === name));
  if (name === 'profiles') prProfilesLoad();
}

async function prLoad() {
  let d;
  try { d = await api('/api/payroll/overview'); } catch (e) { return; }
  if (!d) return;
  prState.rules = d.rules; prState.menapay = d.menapay; prState.items = d.items; prState.runs = d.runs; prState.users = d.users || [];
  const now = new Date(), def = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
  ['prMonth', 'prMpMonth'].forEach(id => { const el = document.getElementById(id); if (!el.value) el.value = def; });
  document.getElementById('prAccessBtn').classList.toggle('hide', !d.is_admin);
  prRunsRender(); prRulesRender(); prMenapayRender(); prAccessRender();
}

/* ---------------- المسيرات ---------------- */
function prRunsRender() {
  document.getElementById('prRuns').innerHTML = prState.runs.map(r => `<tr style="cursor:pointer" onclick="prOpenRun(${r.id})">
    <td dir="ltr"><b>${prEsc(r.month)}</b></td>
    <td><span class="badge ${r.status === 'approved' ? 'badge-ontime' : 'badge-late'}">${prEsc(r.status_label)}</span></td>
    <td>${r.count}</td><td dir="ltr">${prMoney(r.net)}</td>
    <td>${prEsc(r.created_at || '')}<br><small style="color:var(--muted)">${prEsc(r.created_by || '')}</small></td>
    <td>${prEsc(r.approved_at || '')}<br><small style="color:var(--muted)">${prEsc(r.approved_by || '')}</small></td></tr>`).join('')
    || '<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:14px">لا توجد مسيرات بعد — اختر الشهر واضغط «احتساب»</td></tr>';
}

async function prCompute() {
  const month = document.getElementById('prMonth').value;
  if (!month) { toast('اختر الشهر', true); return; }
  let d;
  try { d = await api('/api/payroll/runs', { method: 'POST', body: JSON.stringify({ month }) }); } catch (e) { return; }
  if (!d) return;
  if (d.warning) toast(d.warning, true); else toast(`احتُسبت المسودة: ${d.count} موظف`);
  await prLoad();
  prOpenRun(d.id);
}

async function prOpenRun(id) {
  let d;
  try { d = await api('/api/payroll/runs/' + id); } catch (e) { return; }
  if (!d) return;
  prState.run = d;
  const r = d.run, approved = r.status === 'approved';
  document.getElementById('prRunCard').classList.remove('hide');
  document.getElementById('prRunMonth').textContent = r.month;
  document.getElementById('prRunStatus').textContent = r.status_label + (r.reopen_note ? ` (فُتحت: ${r.reopen_note})` : '');
  document.getElementById('prApproveBtn').classList.toggle('hide', approved);
  document.getElementById('prDeleteBtn').classList.toggle('hide', approved);
  document.getElementById('prReopenBtn').classList.toggle('hide', !approved);
  document.getElementById('prAdjBar').classList.toggle('hide', approved);
  document.getElementById('prRegLink').href = `/api/payroll/runs/${id}/register.xlsx`;
  document.getElementById('prBankX').href = `/api/payroll/runs/${id}/bank.xlsx`;
  document.getElementById('prBankC').href = `/api/payroll/runs/${id}/bank.csv`;
  const t = d.totals, cur = prEsc(d.currency);
  document.getElementById('prRunStats').innerHTML = [
    ['', d.lines.length, 'عدد الموظفين', ''], ['green', prMoney(t.gross), 'إجمالي الاستحقاقات ' + cur, ''],
    ['red', prMoney(t.deductions), 'مجموع الاستقطاعات ' + cur, 'ded'], ['', prMoney(t.net), 'صافي الرواتب ' + cur, ''],
    ['orange', prMoney(t.employer_ss), 'ضمان المؤسسة ' + cur, ''],
  ].map(([c, v, l, f]) => `<div class="stat-card ${c}" onclick="prStatFilter('${f}')"><div class="stat-val" dir="ltr">${v}</div><div class="stat-label">${l}</div></div>`).join('');
  prLinesRender();
  document.getElementById('prLineDetail').classList.add('hide');
}

function prStatFilter(f) {
  // الضغط على رقم: «الاستقطاعات» يُظهر من عليهم خصومات حضور فقط، والباقي يُظهر الكل
  document.querySelectorAll('#prLines tr').forEach(tr => { tr.style.display = (!f || +tr.dataset.attded > 0) ? '' : 'none'; });
}

function prSum(list, pred) { return list.filter(pred).reduce((a, x) => a + (Number(x.amount) || 0), 0); }

function prLinesRender() {
  const d = prState.run;
  document.getElementById('prLines').innerHTML = d.lines.map(ln => {
    const x = ln.data, adj = x.adjustments || [];
    const allow = prSum(x.earnings, e => e.key === 'allowance'), basic = prSum(x.earnings, e => e.key === 'basic');
    const extra = prSum(x.earnings, e => e.key === 'overtime') + prSum(adj, a => a.kind === 'add');
    const attDed = prSum(x.deductions, e => e.attendance), stat = prSum(x.deductions, e => !e.attendance);
    const adjNet = prSum(adj, a => a.kind === 'add') - prSum(adj, a => a.kind === 'deduct');
    return `<tr data-attded="${attDed}">
      <td><input type="checkbox" class="pr-line" data-emp="${ln.employee_id}" aria-label="تحديد" onchange="prSelCount()"></td>
      <td dir="ltr">${prEsc(ln.employee_no)}</td>
      <td><a href="#" onclick="prLineDetail(${ln.employee_id}); return false"><b>${prEsc(ln.name)}</b></a></td><td>${prEsc(ln.dept)}</td>
      <td dir="ltr">${prMoney(basic)}</td><td dir="ltr">${prMoney(allow)}</td><td dir="ltr">${prMoney(extra)}</td>
      <td dir="ltr" style="color:${attDed ? 'var(--red, #c0392b)' : 'inherit'}">${prMoney(attDed)}</td><td dir="ltr">${prMoney(stat)}</td>
      <td dir="ltr">${adj.length ? (adjNet >= 0 ? '+' : '') + prMoney(adjNet) : '—'}</td>
      <td dir="ltr">${prMoney(ln.gross)}</td><td dir="ltr">${prMoney(ln.deductions)}</td><td dir="ltr"><b>${prMoney(ln.net)}</b></td></tr>`;
  }).join('') || '<tr><td colspan="13" style="text-align:center;color:var(--muted);padding:14px">لا يوجد موظف له راتب — أدخل الرواتب من «رواتب الموظفين»</td></tr>';
  prSelCount();
  if (typeof applyAllTableFilters === 'function') applyAllTableFilters();
}

function prCheckAll(on) { document.querySelectorAll('.pr-line').forEach(c => { if (c.closest('tr').style.display !== 'none') c.checked = on; }); prSelCount(); }
function prSelCount() { document.getElementById('prSelCount').textContent = document.querySelectorAll('.pr-line:checked').length; }
function prSelected() { return [...document.querySelectorAll('.pr-line:checked')].map(c => +c.dataset.emp); }

function prLineDetail(empId) {
  const ln = prState.run.lines.find(l => l.employee_id === empId);
  if (!ln) return;
  const x = ln.data, a = x.attendance || {}, approved = prState.run.run.status === 'approved';
  const rows = (list, sign) => list.map(e => `<tr><td>${prEsc(e.label)}${e.qty && e.unit ? ` <small style="color:var(--muted)">(${e.qty} ${prEsc(e.unit)})</small>` : ''}</td><td dir="ltr">${sign}${prMoney(e.amount)}</td></tr>`).join('');
  const adj = (x.adjustments || []).map(j => `<tr><td>${j.kind === 'add' ? 'مكافأة' : 'خصم'}: ${prEsc(j.reason)}</td><td dir="ltr">${j.kind === 'add' ? '+' : '−'}${prMoney(j.amount)}
    ${approved ? '' : `<button class="btn btn-outline btn-sm" style="margin-inline-start:6px" onclick="prAdjDelete(${j.id})" aria-label="حذف التعديل"><i class="fas fa-trash" aria-hidden="true"></i></button>`}</td></tr>`).join('');
  const el = document.getElementById('prLineDetail');
  el.innerHTML = `<div class="card" style="margin:0;background:var(--primary-soft, #f2f6fc)">
    <div class="card-title"><i class="fas fa-user" aria-hidden="true"></i> ${prEsc(ln.name)} — أجر اليوم ${prMoney(x.day_wage)} (أيام العمل في الشهر: ${x.workdays})</div>
    <p style="font-size:.82rem;color:var(--muted);margin-bottom:8px">الحضور ${a.present || 0} يوم · الغياب ${a.absent || 0} · التأخير ${a.late_days || 0} يوم / ${a.late_minutes || 0} دقيقة ·
      المغادرة المبكرة ${a.early_minutes || 0} دقيقة · بدون انصراف ${a.no_out || 0} · الإجازات ${a.vacation_days || 0} (بلا راتب ${a.unpaid_leave || 0}) ·
      الإضافي ${Math.round((a.ot_minutes || 0) / 6) / 10} ساعة · عمل في العطلة ${a.weekend_work || 0}</p>
    <div class="form-grid" style="grid-template-columns:repeat(auto-fit,minmax(260px,1fr))">
      <div class="table-wrap"><table class="no-sort"><thead><tr><th>الاستحقاقات</th><th>المبلغ</th></tr></thead><tbody>${rows(x.earnings, '')}</tbody></table></div>
      <div class="table-wrap"><table class="no-sort"><thead><tr><th>الاستقطاعات</th><th>المبلغ</th></tr></thead><tbody>${rows(x.deductions.filter(e => e.amount || e.key === 'cap'), '−') || '<tr><td colspan="2">لا يوجد</td></tr>'}</tbody></table></div>
      <div class="table-wrap"><table class="no-sort"><thead><tr><th>التعديلات اليدوية</th><th>المبلغ</th></tr></thead><tbody>${adj || '<tr><td colspan="2">لا يوجد</td></tr>'}</tbody></table></div>
    </div>
    <div style="margin-top:8px;font-weight:700">الصافي: <span dir="ltr">${prMoney(ln.net)} ${prEsc(prState.run.currency)}</span>
      <a class="btn btn-outline btn-sm" style="margin-inline-start:8px" target="_blank" rel="noopener" href="/api/payroll/runs/${prState.run.run.id}/payslips?ids=${ln.employee_id}"><i class="fas fa-print" aria-hidden="true"></i> القسيمة</a></div></div>`;
  el.classList.remove('hide');
  el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

async function prRunAction(action) {
  const r = prState.run && prState.run.run;
  if (!r) return;
  const body = { action };
  if (action === 'approve' && !confirm(`اعتماد مسيرة ${r.month} وإقفالها؟ لن يمكن تعديلها إلا بفتحها مع ذكر السبب.`)) return;
  if (action === 'delete' && !confirm(`حذف مسودة ${r.month}؟ تُحذف معها التعديلات اليدوية.`)) return;
  if (action === 'reopen') {
    const note = prompt('سبب فتح المسيرة المعتمدة (يُسجَّل في سجل التدقيق):');
    if (!note || !note.trim()) return;
    body.note = note.trim();
  }
  try { await api(`/api/payroll/runs/${r.id}/action`, { method: 'POST', body: JSON.stringify(body) }); } catch (e) { return; }
  toast({ approve: 'اعتُمدت المسيرة وأُقفلت', reopen: 'فُتحت المسيرة — أعد احتسابها بعد التعديل', delete: 'حُذفت المسودة' }[action]);
  await prLoad();
  if (action === 'delete') document.getElementById('prRunCard').classList.add('hide'); else prOpenRun(r.id);
}

async function prAdjust() {
  const ids = prSelected();
  const body = { employee_ids: ids, kind: document.getElementById('prAdjKind').value,
    amount: prNum(document.getElementById('prAdjAmount').value), reason: document.getElementById('prAdjReason').value.trim() };
  if (!ids.length) { toast('حدّد موظفاً واحداً على الأقل', true); return; }
  if (!body.amount || !body.reason) { toast('اكتب المبلغ والسبب', true); return; }
  try { await api(`/api/payroll/runs/${prState.run.run.id}/adjust`, { method: 'POST', body: JSON.stringify(body) }); } catch (e) { return; }
  toast(`أُضيف التعديل لـ ${ids.length} موظف`);
  document.getElementById('prAdjAmount').value = ''; document.getElementById('prAdjReason').value = '';
  prOpenRun(prState.run.run.id);
}

async function prAdjDelete(id) {
  if (!confirm('حذف هذا التعديل؟')) return;
  try { await api(`/api/payroll/runs/${prState.run.run.id}/adjust`, { method: 'POST', body: JSON.stringify({ delete_id: id }) }); } catch (e) { return; }
  prOpenRun(prState.run.run.id);
}

function prPayslips() {
  if (!prState.run) return;
  const ids = prSelected();
  window.open(`/api/payroll/runs/${prState.run.run.id}/payslips` + (ids.length ? '?ids=' + ids.join(',') : ''), '_blank', 'noopener');
}

/* ---------------- رواتب الموظفين ---------------- */
async function prProfilesLoad() {
  let d;
  try { d = await api('/api/payroll/profiles'); } catch (e) { return; }
  if (!d) return;
  prState.profiles = d.rows;
  document.getElementById('prProfCount').textContent = d.rows.length;
  document.getElementById('prProfPaid').textContent = d.rows.filter(r => r.basic > 0).length;
  document.getElementById('prProfiles').innerHTML = d.rows.map(r => `<tr>
    <td><input type="checkbox" class="pr-prof" data-id="${r.id}" aria-label="تحديد" onchange="prProfSel()"></td>
    <td dir="ltr">${prEsc(r.employee_no)}</td><td><b>${prEsc(r.name)}</b></td><td>${prEsc(r.dept)}</td>
    <td dir="ltr">${r.basic ? prMoney(r.basic) : '—'}</td>
    <td>${r.allowances.map(a => `${prEsc(a.name)}: <span dir="ltr">${prMoney(a.amount)}</span>`).join('<br>') || '—'}</td>
    <td>${r.ss_subject ? 'خاضع' : 'غير خاضع'}</td><td dir="ltr">${r.tax_monthly ? prMoney(r.tax_monthly) : '—'}</td>
    <td>${r.payment === 'cash' ? 'نقداً' : 'بنك'}</td><td>${prEsc(r.bank_name)}</td><td dir="ltr" style="font-size:.78rem">${prEsc(r.iban)}</td>
    <td>${r.active ? 'نشط' : 'موقوف'}</td>
    <td><button class="btn btn-outline btn-sm" onclick="prEdit(${r.id})" aria-label="تعديل"><i class="fas fa-pen" aria-hidden="true"></i></button></td></tr>`).join('')
    || '<tr><td colspan="13" style="text-align:center;color:var(--muted);padding:14px">لا يوجد موظفون</td></tr>';
  prProfSel();
  if (typeof applyAllTableFilters === 'function') applyAllTableFilters();
}
function prProfCheckAll(on) { document.querySelectorAll('.pr-prof').forEach(c => { if (c.closest('tr').style.display !== 'none') c.checked = on; }); prProfSel(); }
function prProfSel() { document.getElementById('prProfSel').textContent = document.querySelectorAll('.pr-prof:checked').length; }
function prBulkUi() {
  const a = document.getElementById('prBulkAction').value, v = document.getElementById('prBulkValue');
  v.classList.toggle('hide', !['raise_percent', 'raise_amount', 'bank_name'].includes(a));
  v.type = a === 'bank_name' ? 'text' : 'number';
  v.placeholder = { raise_percent: 'النسبة %', raise_amount: 'المبلغ', bank_name: 'اسم البنك' }[a] || '';
}
async function prBulk() {
  const ids = [...document.querySelectorAll('.pr-prof:checked')].map(c => +c.dataset.id), action = document.getElementById('prBulkAction').value;
  if (!ids.length || !action) { toast('حدّد الموظفين واختر الإجراء', true); return; }
  const value = document.getElementById('prBulkValue').value;
  if (['raise_percent', 'raise_amount'].includes(action) && !prNum(value)) { toast('اكتب القيمة', true); return; }
  if (!confirm(`تطبيق الإجراء على ${ids.length} موظف؟`)) return;
  let d;
  try { d = await api('/api/payroll/profiles/bulk', { method: 'POST', body: JSON.stringify({ ids, action, value }) }); } catch (e) { return; }
  toast(`عُدّل ${d.updated} موظف`);
  prProfilesLoad();
}

function prAllowRow(a) {
  a = a || { name: '', amount: '' };
  const div = document.createElement('div');
  div.className = 'filter-bar pr-allow';
  div.style.marginBottom = '6px';
  div.innerHTML = `<input type="text" class="search-input pr-al-name" maxlength="60" placeholder="اسم العلاوة (مثل: علاوة نقل)" aria-label="اسم العلاوة" value="${prEsc(a.name)}">
    <input type="number" class="search-input pr-al-amt" style="width:130px;min-width:0" min="0" step="0.001" placeholder="المبلغ" aria-label="مبلغ العلاوة" value="${prEsc(a.amount)}">
    <button type="button" class="btn btn-outline btn-sm" aria-label="حذف العلاوة" onclick="this.parentElement.remove()"><i class="fas fa-trash" aria-hidden="true"></i></button>`;
  document.getElementById('prEdAllow').appendChild(div);
}
function prEdit(id) {
  const r = prState.profiles.find(x => x.id === id);
  if (!r) return;
  prState.editId = id;
  document.getElementById('prEditName').textContent = r.name;
  document.getElementById('prEdNo').value = r.employee_no;
  document.getElementById('prEdBasic').value = r.basic || '';
  document.getElementById('prEdSsSalary').value = r.ss_salary || '';
  document.getElementById('prEdTax').value = r.tax_monthly || '';
  document.getElementById('prEdPay').value = r.payment;
  document.getElementById('prEdBank').value = r.bank_name;
  document.getElementById('prEdIban').value = r.iban;
  document.getElementById('prEdSs').checked = !!r.ss_subject;
  document.getElementById('prEdNotes').value = r.notes;
  document.getElementById('prEdAllow').innerHTML = '';
  r.allowances.forEach(prAllowRow);
  const card = document.getElementById('prEditCard');
  card.classList.remove('hide');
  card.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
async function prSaveProfile() {
  const body = { employee_no: document.getElementById('prEdNo').value, basic: prNum(document.getElementById('prEdBasic').value),
    ss_salary: document.getElementById('prEdSsSalary').value, tax_monthly: prNum(document.getElementById('prEdTax').value),
    payment: document.getElementById('prEdPay').value, bank_name: document.getElementById('prEdBank').value,
    iban: document.getElementById('prEdIban').value, ss_subject: document.getElementById('prEdSs').checked,
    notes: document.getElementById('prEdNotes').value,
    allowances: [...document.querySelectorAll('#prEdAllow .pr-allow')].map(r => ({ name: r.querySelector('.pr-al-name').value, amount: r.querySelector('.pr-al-amt').value })) };
  try { await api('/api/payroll/profiles/' + prState.editId, { method: 'POST', body: JSON.stringify(body) }); } catch (e) { return; }
  toast('حُفظ الراتب');
  document.getElementById('prEditCard').classList.add('hide');
  prProfilesLoad();
}

/* ---------------- قواعد الاحتساب ---------------- */
const PR_RULES = [
  { title: 'عام', fields: [
    ['currency', 'العملة', 'text'], ['decimals', 'المنازل العشرية', 'number'],
    ['day_basis', 'أساس أجر اليوم', 'select', [['thirty', 'الأساسي ÷ 30'], ['workdays', 'الأساسي ÷ أيام العمل الفعلية في الشهر']]],
    ['hours_per_day', 'ساعات العمل اليومية (لأجر الدقيقة والساعة)', 'number'],
    ['cap_percent', 'الحد الأقصى لخصومات الحضور % من الراتب (0 = بلا حد)', 'number'],
    ['payslip_app', 'إظهار قسيمة الراتب للموظف في تطبيقه بعد الاعتماد', 'check']] },
  { title: 'التأخير', on: 'late.on', fields: [
    ['late.mode', 'طريقة الخصم', 'select', [['minutes', 'بالدقيقة (أجر الدقيقة × الدقائق)'], ['tiers', 'شرائح لكل يوم تأخير'], ['count', 'كل عدد من مرات التأخير = خصم أيام']]],
    ['late.grace_minutes', 'سماح شهري بالدقائق (طريقة الدقيقة)', 'number'], ['late.factor', 'مُعامل (طريقة الدقيقة)', 'number'],
    ['late.every_n', 'كل كم مرة تأخير (طريقة العدد)', 'number'], ['late.every_day', 'تُخصم أيام (طريقة العدد)', 'number'],
    ['late.tiers', 'الشرائح: من دقيقة – إلى دقيقة = خصم من يوم', 'tiers']] },
  { title: 'المغادرة المبكرة', on: 'early.on', fields: [['early.grace_minutes', 'سماح شهري بالدقائق', 'number'], ['early.factor', 'مُعامل', 'number']] },
  { title: 'الغياب بلا عذر', on: 'absence.on', fields: [['absence.factor', 'أيام الخصم عن كل يوم غياب', 'number']] },
  { title: 'الإجازة بلا راتب (أنواع الإجازات غير المدفوعة)', on: 'unpaid_leave.on', fields: [['unpaid_leave.factor', 'أيام الخصم عن كل يوم', 'number']] },
  { title: 'نسيان تسجيل الانصراف', on: 'no_out.on', fields: [['no_out.free', 'مرات معفاة في الشهر', 'number'], ['no_out.day', 'خصم من يوم عن كل مرة بعدها', 'number']] },
  { title: 'العمل الإضافي', on: 'overtime.on', fields: [['overtime.factor', 'مُعامل ساعة الإضافي في أيام العمل', 'number'], ['overtime.weekend_factor', 'مُعامل يوم العمل في العطلة', 'number']] },
  { title: 'الضمان الاجتماعي', on: 'ss.on', fields: [['ss.employee_rate', 'نسبة حصة الموظف %', 'number'], ['ss.employer_rate', 'نسبة حصة المؤسسة %', 'number']] },
  { title: 'ضريبة الدخل (المبلغ الشهري من ملف كل موظف)', on: 'tax.on', fields: [] },
];
const prGet = (o, path) => path.split('.').reduce((a, k) => (a == null ? a : a[k]), o);
const prSet = (o, path, v) => { const ks = path.split('.'); const last = ks.pop(); ks.reduce((a, k) => (a[k] = a[k] || {}), o)[last] = v; };

function prRulesRender() {
  const r = prState.rules;
  document.getElementById('prRulesForm').innerHTML = PR_RULES.map((g, gi) => `<fieldset style="border:1px solid var(--line, #e3e9f2);border-radius:10px;padding:10px 14px;margin-bottom:12px">
    <legend style="font-weight:700;padding:0 6px">${g.on ? `<label style="display:inline-flex;gap:6px;align-items:center"><input type="checkbox" data-rule="${g.on}" data-kind="check" ${prGet(r, g.on) ? 'checked' : ''}> ${g.title}</label>` : g.title}</legend>
    <div class="form-grid quad">${g.fields.map(([k, label, type, opts]) => {
      const v = prGet(r, k), id = `prR_${gi}_${k.replace(/\./g, '_')}`;
      if (type === 'check') return `<div class="form-group"><label style="display:flex;gap:6px;align-items:center;margin-top:24px"><input type="checkbox" id="${id}" data-rule="${k}" data-kind="check" ${v ? 'checked' : ''}> ${label}</label></div>`;
      if (type === 'select') return `<div class="form-group"><label for="${id}">${label}</label><select id="${id}" data-rule="${k}" data-kind="text">${opts.map(([ov, ol]) => `<option value="${ov}" ${v === ov ? 'selected' : ''}>${ol}</option>`).join('')}</select></div>`;
      if (type === 'tiers') return `<div class="form-group" style="grid-column:1/-1"><label>${label}</label><div id="prTiers">${(v || []).map(prTierRow).join('')}</div>
        <button type="button" class="btn btn-outline btn-sm" onclick="document.getElementById('prTiers').insertAdjacentHTML('beforeend', prTierRow({from:'',to:'',day:''}))"><i class="fas fa-plus" aria-hidden="true"></i> شريحة</button></div>`;
      return `<div class="form-group"><label for="${id}">${label}</label><input id="${id}" type="${type}" ${type === 'number' ? 'step="any" min="0"' : 'maxlength="8"'} data-rule="${k}" data-kind="${type}" value="${prEsc(v)}"></div>`;
    }).join('')}</div></fieldset>`).join('');
}
function prTierRow(t) {
  return `<div class="filter-bar pr-tier" style="margin-bottom:6px">
    <input type="number" class="search-input pr-t-from" style="width:110px;min-width:0" min="0" placeholder="من دقيقة" aria-label="من دقيقة" value="${prEsc(t.from)}">
    <input type="number" class="search-input pr-t-to" style="width:110px;min-width:0" min="0" placeholder="إلى دقيقة" aria-label="إلى دقيقة" value="${prEsc(t.to)}">
    <input type="number" class="search-input pr-t-day" style="width:110px;min-width:0" min="0" step="any" placeholder="خصم من يوم" aria-label="خصم من يوم" value="${prEsc(t.day)}">
    <button type="button" class="btn btn-outline btn-sm" aria-label="حذف الشريحة" onclick="this.parentElement.remove()"><i class="fas fa-trash" aria-hidden="true"></i></button></div>`;
}
async function prSaveRules() {
  const out = JSON.parse(JSON.stringify(prState.rules));
  document.querySelectorAll('#prRulesForm [data-rule]').forEach(el => {
    const k = el.dataset.kind;
    prSet(out, el.dataset.rule, k === 'check' ? el.checked : k === 'number' ? prNum(el.value) : el.value);
  });
  out.late.tiers = [...document.querySelectorAll('#prTiers .pr-tier')].map(r => ({ from: prNum(r.querySelector('.pr-t-from').value),
    to: prNum(r.querySelector('.pr-t-to').value), day: prNum(r.querySelector('.pr-t-day').value) })).filter(t => t.to > 0);
  let d;
  try { d = await api('/api/payroll/rules', { method: 'POST', body: JSON.stringify(out) }); } catch (e) { return; }
  prState.rules = d.rules;
  prRulesRender();
  toast('حُفظت القواعد — أعد احتساب المسودات لتطبيقها');
}

/* ---------------- الربط مع MenaPAY ---------------- */
function prMenapayRender() {
  const m = prState.menapay, lab = Object.fromEntries(prState.items.map(i => [i.key, i]));
  document.getElementById('prMpLayout').value = m.layout;
  document.getElementById('prMpCode').value = m.code_field;
  document.getElementById('prMpPeriod').value = m.period_format;
  document.getElementById('prMpItems').innerHTML = m.items.map(it => `<tr>
    <td><input type="checkbox" class="pr-mp-on" data-key="${it.key}" aria-label="تصدير" ${it.on ? 'checked' : ''}></td>
    <td>${prEsc((lab[it.key] || {}).label || it.key)}</td><td>${prEsc((lab[it.key] || {}).unit || '')}</td>
    <td><input type="text" class="search-input pr-mp-code" data-key="${it.key}" maxlength="30" dir="ltr" style="width:140px;min-width:0" aria-label="رمز البند" value="${prEsc(it.code)}"></td></tr>`).join('');
}
async function prSaveMenapay(silent) {
  const body = { layout: document.getElementById('prMpLayout').value, code_field: document.getElementById('prMpCode').value,
    period_format: document.getElementById('prMpPeriod').value,
    items: [...document.querySelectorAll('.pr-mp-on')].map(c => ({ key: c.dataset.key, on: c.checked,
      code: document.querySelector(`.pr-mp-code[data-key="${c.dataset.key}"]`).value })) };
  let d;
  try { d = await api('/api/payroll/menapay', { method: 'POST', body: JSON.stringify(body) }); } catch (e) { return false; }
  prState.menapay = d.menapay;
  if (!silent) toast('حُفظت إعدادات الربط');
  return true;
}
async function prMpExport(fmt) {
  const month = document.getElementById('prMpMonth').value;
  if (!month) { toast('اختر الشهر', true); return; }
  if (!(await prSaveMenapay(true))) return;
  const res = await fetch(`/api/payroll/menapay/export.${fmt}?month=${month}`, { credentials: 'same-origin' });
  if (!res.ok) { const d = await res.json().catch(() => ({})); toast(d.error || 'تعذّر التصدير', true); return; }
  const miss = res.headers.get('X-Missing-Codes');
  const blob = await res.blob(), a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = `menapay-${month}.${fmt}`; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  if (miss) toast(`تنبيه: ${miss} موظف بلا رمز — أدخل الرقم الوظيفي في «رواتب الموظفين»`, true);
}
async function prImport() {
  const f = document.getElementById('prImpFile').files[0];
  if (!f) { toast('اختر الملف أولاً', true); return; }
  const fd = new FormData();
  fd.append('file', f);
  fd.append('create', document.getElementById('prImpCreate').checked ? '1' : '0');
  const res = await fetch('/api/payroll/import', { method: 'POST', credentials: 'same-origin', body: fd });
  const d = await res.json().catch(() => null);
  const out = document.getElementById('prImpResult');
  if (!d || !d.ok) { toast((d && d.error) || 'تعذّر الاستيراد', true); return; }
  out.innerHTML = `<b>تم:</b> ${d.updated} محدَّث، ${d.created} جديد، ${d.skipped} غير موجود.<br>
    <span style="color:var(--muted)">الأعمدة المكتشفة: ${Object.entries(d.columns).map(([k, v]) => prEsc(v)).join('، ')}</span>
    ${d.not_found.length ? `<br><span style="color:var(--muted)">غير موجودين: ${d.not_found.map(prEsc).join('، ')}</span>` : ''}`;
  toast('اكتمل الاستيراد');
}

/* ---------------- الصلاحيات ---------------- */
function prAccessRender() {
  const tb = document.getElementById('prAccessRows');
  if (!tb) return;
  const roles = { admin: 'مدير النظام', dept_manager: 'مدير قسم', viewer: 'اطّلاع فقط' };
  tb.innerHTML = prState.users.map(u => `<tr>
    <td><input type="checkbox" class="pr-acc" data-id="${u.id}" aria-label="تحديد" ${u.role === 'admin' ? 'disabled' : ''}></td>
    <td dir="ltr">${prEsc(u.username)}</td><td>${prEsc(u.full_name)}</td><td>${prEsc(roles[u.role] || u.role)}</td>
    <td>${u.role === 'admin' ? 'دائمة (مدير)' : u.access ? '<b style="color:#16a34a">ممنوحة</b>' : 'لا'}</td></tr>`).join('')
    || '<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:14px">لا يوجد مستخدمون</td></tr>';
}
async function prAccess(grant) {
  const ids = [...document.querySelectorAll('.pr-acc:checked')].map(c => +c.dataset.id);
  if (!ids.length) { toast('حدّد مستخدماً واحداً على الأقل', true); return; }
  try { await api('/api/payroll/access', { method: 'POST', body: JSON.stringify({ ids, grant }) }); } catch (e) { return; }
  toast(grant ? 'مُنحت الصلاحية' : 'سُحبت الصلاحية');
  prLoad();
}

window.EXTRA_LOADERS = Object.assign(window.EXTRA_LOADERS || {}, { payroll: prLoad });
