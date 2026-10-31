/* أجهزة Dahua — لوحة التحكم ← أجهزة البصمة ← أجهزة Dahua (الخادم: dahua.py) */
let dhCache = { devices: [], senders: [] };
let dhEditId = null;

function dhStatus(d) {
  if (!d.active) return '<span style="color:var(--muted);font-weight:700">معطّل</span>';
  if (d.last_error) return `<span style="color:#c0392b;font-weight:700" title="${escapeHtml(d.last_error)}">خطأ</span>`;
  return d.last_pull ? '<span style="color:#1e8e5a;font-weight:700">يعمل</span>' : '<span style="color:#b45309;font-weight:700">لم يُسحب بعد</span>';
}
function dhUnmatched(list) {
  if (!list || !list.length) return '0';
  return `<span style="color:#c0392b" title="أرقام في الجهاز لا تطابق «رقم البصمة» لأي موظف">${list.length}: <span dir="ltr">${escapeHtml(list.slice(0, 8).join(', '))}${list.length > 8 ? '…' : ''}</span></span>`;
}

async function dhLoad() {
  const d = await api('/api/dahua/overview').catch(() => null);
  if (!d) return;
  const keepDev = new Set(dhChecked('dh-dev', 'id')), keepSend = new Set(dhChecked('dh-send', 'key'));
  dhCache = d;
  document.getElementById('dhCount').textContent = d.devices.length;
  document.getElementById('dhSendCount').textContent = d.senders.length;
  document.getElementById('dhAutoAll').checked = !!d.auto_pull;
  document.getElementById('dhEvery').value = String(d.pull_every || 5);
  if (d.push_url) {
    document.getElementById('dhPushUrl').textContent = d.push_url;
    document.getElementById('dhPushHost').textContent = d.push_host;
    document.getElementById('dhPushPath').textContent = new URL(d.push_url).pathname;
  }
  document.getElementById('dhDevices').innerHTML = d.devices.map(x => `<tr>
    <td><input type="checkbox" class="dh-dev" data-id="${x.id}" ${keepDev.has(String(x.id)) ? 'checked' : ''} onchange="dhCount()"></td>
    <td>${escapeHtml(x.name)}${x.location ? `<br><small style="color:var(--muted)">${escapeHtml(x.location)}</small>` : ''}</td>
    <td dir="ltr" data-notr>${x.use_https ? 'https://' : ''}${escapeHtml(x.host)}:${x.port}</td>
    <td dir="ltr" data-notr>${escapeHtml(x.model || '—')}</td>
    <td>${dhStatus(x)}${x.auto_pull ? '' : ' <small style="color:var(--muted)">(يدوي)</small>'}</td>
    <td>${dhLiveCell(x, d.live || {})}</td>
    <td dir="ltr">${escapeHtml(x.last_pull || '—')}</td><td dir="ltr">${escapeHtml(x.last_rec_ts || '—')}</td>
    <td>${x.today}</td><td>${x.total}</td><td>${dhUnmatched(x.unmatched)}</td>
    <td><button class="btn btn-outline btn-sm" onclick="dhEdit(${x.id})" aria-label="تعديل"><i class="fas fa-pen" aria-hidden="true"></i></button></td></tr>`).join('')
    || '<tr><td colspan="12" style="color:var(--muted)">لا توجد أجهزة Dahua مضافة بعد</td></tr>';
  dhFillDeviceLists(d.devices);
  if (d.push_url) dhLivePoll();          // المدير فقط
  document.getElementById('dhSenders').innerHTML = d.senders.map(x => `<tr>
    <td><input type="checkbox" class="dh-send" data-key="${escapeHtml(x.key)}" ${keepSend.has(x.key) ? 'checked' : ''} onchange="dhCount()"></td>
    <td><a href="#" onclick="dhRename('${escapeHtml(x.key)}');return false" title="تعديل الاسم">${escapeHtml(x.name || x.key)}</a></td>
    <td dir="ltr" data-notr>${escapeHtml(x.key.slice(3))}</td>
    <td>${x.approved ? '<span style="color:#1e8e5a;font-weight:700">مقبول</span>' : '<span style="color:#b45309;font-weight:700">بانتظار الموافقة</span>'}</td>
    <td dir="ltr">${escapeHtml(x.last_seen || '—')}</td><td>${x.messages}</td><td>${x.today}</td>
    <td>${x.held || 0}</td><td>${dhUnmatched(x.unmatched)}</td>
    <td>${x.last_raw !== undefined ? `<a href="#" onclick="dhShowRaw('${escapeHtml(x.key)}');return false">${escapeHtml(x.last_note || 'عرض')}</a>` : escapeHtml(x.last_note || '')}</td></tr>`).join('')
    || '<tr><td colspan="10" style="color:var(--muted)">لم يرسل أي جهاز بعد</td></tr>';
  dhCount();
  if (typeof initTableFilters === 'function') initTableFilters();
  if (typeof initTableSorting === 'function') initTableSorting(document.getElementById('devsub-dev-dahua'));
  if (typeof applyAllTableFilters === 'function') applyAllTableFilters();
}

function dhChecked(cls, attr) { return [...document.querySelectorAll('.' + cls + ':checked')].map(c => c.dataset[attr]); }
function dhCount() {
  document.getElementById('dhSel').textContent = dhChecked('dh-dev', 'id').length;
  document.getElementById('dhTotal').textContent = document.querySelectorAll('.dh-dev').length;
  const us = document.getElementById('dhuSel');
  if (us) { us.textContent = dhChecked('dh-user', 'uid').length; document.getElementById('dhuTotal').textContent = document.querySelectorAll('.dh-user').length; }
  document.getElementById('dhSendSel').textContent = dhChecked('dh-send', 'key').length;
}
function dhCheckAll(cls, on) {
  document.querySelectorAll('.' + cls).forEach(c => { if (c.closest('tr').style.display !== 'none') c.checked = on; });
  dhCount();
}

function dhForm() {
  return {
    name: document.getElementById('dhName').value.trim(),
    host: document.getElementById('dhHost').value.trim(),
    port: +document.getElementById('dhPort').value || 80,
    location: document.getElementById('dhLocation').value.trim(),
    username: document.getElementById('dhUser').value.trim() || 'admin',
    password: document.getElementById('dhPass').value,
    time_mode: document.getElementById('dhTime').value,
    use_https: document.getElementById('dhHttps').checked,
    auto_pull: document.getElementById('dhAuto').checked,
  };
}
function dhReset() {
  dhEditId = null;
  ['dhName', 'dhHost', 'dhLocation', 'dhPass'].forEach(i => { document.getElementById(i).value = ''; });
  document.getElementById('dhPort').value = 80;
  document.getElementById('dhUser').value = 'admin';
  document.getElementById('dhTime').value = 'utc';
  document.getElementById('dhHttps').checked = false;
  document.getElementById('dhAuto').checked = true;
  document.getElementById('dhFormTitle').textContent = 'إضافة جهاز Dahua على شبكة المدرسة';
  document.getElementById('dhSaveLbl').textContent = 'حفظ';
  document.getElementById('dhPass').placeholder = '••••••';
  document.getElementById('dhPwStar').style.display = '';
  document.getElementById('dhCancel').style.display = 'none';
}
function dhEdit(id) {
  const x = dhCache.devices.find(d => d.id === id);
  if (!x) return;
  dhEditId = id;
  document.getElementById('dhName').value = x.name;
  document.getElementById('dhHost').value = x.host;
  document.getElementById('dhPort').value = x.port;
  document.getElementById('dhLocation').value = x.location || '';
  document.getElementById('dhUser').value = x.username || 'admin';
  document.getElementById('dhPass').value = '';
  document.getElementById('dhPass').placeholder = 'اتركها فارغة لإبقاء الحالية';
  document.getElementById('dhPwStar').style.display = 'none';
  document.getElementById('dhTime').value = x.time_mode || 'utc';
  document.getElementById('dhHttps').checked = !!x.use_https;
  document.getElementById('dhAuto').checked = !!x.auto_pull;
  document.getElementById('dhFormTitle').textContent = 'تعديل الجهاز: ' + x.name;
  document.getElementById('dhSaveLbl').textContent = 'حفظ التعديل';
  document.getElementById('dhCancel').style.display = '';
  document.getElementById('dhName').scrollIntoView({ behavior: 'smooth', block: 'center' });
}
async function dhSave() {
  const f = dhForm();
  if (!f.name || !f.host) { toast('اسم الجهاز وعنوان IP مطلوبان', true); return; }
  if (dhEditId) {
    if (!f.password) delete f.password;
    await api('/api/dahua/devices/' + dhEditId, { method: 'POST', body: JSON.stringify(f) });
  } else {
    if (!f.password) { toast('كلمة مرور الجهاز مطلوبة', true); return; }
    await api('/api/dahua/devices', { method: 'POST', body: JSON.stringify(f) });
  }
  toast('تم الحفظ — جرّب «اختبار الاتصال»');
  dhReset(); dhLoad();
}

async function dhBulk(action) {
  const ids = dhChecked('dh-dev', 'id');
  if (!ids.length) { toast('حدّد جهازاً واحداً على الأقل', true); return; }
  if (action === 'delete' && !confirm(`حذف ${ids.length} جهاز من القائمة؟ البصمات التي سُحبت منه تبقى في الحضور.`)) return;
  const body = { ids, action };
  if (action === 'pull') {
    body.date_from = document.getElementById('dhFrom').value || null;
    body.date_to = document.getElementById('dhTo').value || null;
  }
  const box = document.getElementById('dhResult');
  if (action === 'pull' || action === 'test') box.textContent = 'جارٍ الاتصال بالأجهزة…';
  const d = await api('/api/dahua/devices/bulk', { method: 'POST', body: JSON.stringify(body) }).catch(() => null);
  if (!d) { box.textContent = ''; return; }
  if (d.results) {
    box.innerHTML = d.results.map(r => {
      if (!r.ok) return `<div style="color:#c0392b"><b>${escapeHtml(r.device)}:</b> ${escapeHtml(r.error)}</div>`;
      if (action === 'test') {
        const last = r.last_record ? ` — آخر بصمة في الجهاز: رقم ${escapeHtml(r.last_record.user_id)} الساعة <b dir="ltr">${escapeHtml(r.last_record.time)}</b> (إن كانت مزاحة بساعات فغيّر «توقيت السجلات»)` : '';
        return `<div style="color:#1e8e5a"><b>${escapeHtml(r.device)}:</b> متصل ✓ <span dir="ltr">${escapeHtml(r.model || '')} ${escapeHtml(r.serial || '')}</span> — وقت الجهاز <span dir="ltr">${escapeHtml(r.device_time || '؟')}</span> ووقت الخادم <span dir="ltr">${escapeHtml(r.server_time)}</span>${last}${r.records_error ? ` <span style="color:#c0392b">(${escapeHtml(r.records_error)})</span>` : ''}</div>`;
      }
      return `<div><b>${escapeHtml(r.device)}:</b> ${r.received} سجل مقروء، ${r.new} جديد${r.unmatched && r.unmatched.length ? ` — <span style="color:#c0392b">${r.unmatched.length} رقم غير مطابق</span>` : ''}</div>`;
    }).join('');
  } else toast('تم');
  dhLoad();
}

async function dhSettings(body) {
  await api('/api/dahua/settings', { method: 'POST', body: JSON.stringify(body) }).catch(() => null);
  toast('تم الحفظ');
}
async function dhNewToken() {
  if (!confirm('إنشاء رمز جديد يبطل الرابط الحالي — يجب تحديثه في كل جهاز يستخدمه. متابعة؟')) return;
  await api('/api/dahua/settings', { method: 'POST', body: JSON.stringify({ new_token: true }) });
  dhLoad();
}
function dhCopy() {
  const t = document.getElementById('dhPushUrl').textContent;
  (navigator.clipboard ? navigator.clipboard.writeText(t) : Promise.reject()).then(() => toast('نُسخ الرابط'), () => toast(t));
}

async function dhSendBulk(action) {
  const keys = dhChecked('dh-send', 'key');
  if (!keys.length) { toast('حدّد مرسِلاً واحداً على الأقل', true); return; }
  if (action === 'delete' && !confirm(`حذف ${keys.length} مرسِل؟ تُحذف بصماته المعلّقة فقط، وما طُبِّق يبقى في الحضور.`)) return;
  const d = await api('/api/dahua/senders/bulk', { method: 'POST', body: JSON.stringify({ keys, action }) }).catch(() => null);
  if (d) toast(action === 'approve' && d.applied ? `تمت الموافقة وطُبِّقت ${d.applied} بصمة معلّقة` : 'تم');
  dhLoad();
}
async function dhRename(key) {
  const x = dhCache.senders.find(s => s.key === key);
  const name = prompt('اسم الجهاز:', x ? x.name : '');
  if (!name) return;
  await api('/api/dahua/senders/bulk', { method: 'POST', body: JSON.stringify({ keys: [key], action: 'rename', name }) });
  dhLoad();
}
function dhShowRaw(key) {
  const x = dhCache.senders.find(s => s.key === key);
  const pre = document.getElementById('dhRaw');
  pre.textContent = (x && x.last_raw) || '(فارغة)';
  pre.style.display = '';
  pre.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

async function dhImport() {
  const f = document.getElementById('dhFile').files[0];
  if (!f) { toast('اختر الملف أولاً', true); return; }
  const fd = new FormData(); fd.append('file', f);
  const box = document.getElementById('dhImportResult');
  box.textContent = 'جارٍ القراءة…';
  const res = await fetch('/api/dahua/import', { method: 'POST', body: fd });
  const d = await res.json().catch(() => ({ ok: false, error: 'رد غير متوقع من الخادم' }));
  if (!d.ok) { box.innerHTML = `<span style="color:#c0392b">${escapeHtml(d.error)}</span>`; return; }
  const c = d.columns || {};
  box.innerHTML = `<div style="color:#1e8e5a"><b>تم:</b> ${d.received} بصمة في الملف (${escapeHtml(d.date_from)} — ${escapeHtml(d.date_to)})، منها ${d.new} جديدة و${d.received - d.new} موجودة سابقاً.</div>
    <div style="color:var(--muted)">الأعمدة المستخدمة: الرقم «${escapeHtml(c.id || '—')}»، الاسم «${escapeHtml(c.name || '—')}»، الوقت «${escapeHtml(c.time || c.date || '—')}»</div>
    ${d.unmatched.length ? `<div style="color:#c0392b">${d.unmatched.length} رقم غير مطابق لأي موظف: <span dir="ltr">${escapeHtml(d.unmatched.slice(0, 20).join(', '))}</span> — أضفها «رقم بصمة» للموظفين ثم اضغط «إعادة مطابقة».</div>` : ''}`;
  dhLoad();
}
async function dhRematch() {
  const d = await api('/api/dahua/rematch', { method: 'POST', body: '{}' }).catch(() => null);
  if (d) toast(`طوبق ${d.matched} سجل`);
  dhLoad();
}

/* ===== إدارة الأجهزة: المعلومات، الوقت، الموظفون، الباب، المراقبة الحية، الصيانة (dahua_ops.py) ===== */
function dhLiveCell(x, live) {
  if (!x.live) return '<span style="color:var(--muted)">متوقفة</span>';
  const st = live[String(x.id)];
  if (st && st.state === 'connected') return `<span style="color:#1e8e5a;font-weight:700" title="منذ ${escapeHtml(st.since)}">متصلة</span>`;
  return `<span style="color:#b45309;font-weight:700" title="${escapeHtml(st ? st.state : '')}">جارٍ الاتصال</span>`;
}
function dhFillDeviceLists(devs) {
  const opts = devs.map(x => `<option value="${x.id}">${escapeHtml(x.name)}</option>`).join('');
  for (const id of ['dhuDevice', 'dhcSource']) {
    const el = document.getElementById(id);
    if (!el) continue;
    const keep = el.value;
    el.innerHTML = opts || '<option value="">لا توجد أجهزة</option>';
    if (keep && devs.some(x => String(x.id) === keep)) el.value = keep;
  }
  const t = document.getElementById('dhcTargets');
  if (t) {
    const keep = new Set([...t.querySelectorAll('input:checked')].map(c => c.value));
    t.innerHTML = devs.map(x => `<label style="display:flex;gap:6px;align-items:center"><input type="checkbox" value="${x.id}" ${keep.has(String(x.id)) ? 'checked' : ''}> ${escapeHtml(x.name)}</label>`).join('')
      || '<span style="color:var(--muted)">أضف جهازين على الأقل</span>';
  }
  dhLoadNames();
}
async function dhLoadNames() {
  const dl = document.getElementById('dhfNames');
  if (!dl || dl.dataset.loaded) return;
  const d = await api('/api/employees').catch(() => null);
  if (!d) return;
  dl.innerHTML = d.rows.filter(e => e.active && e.device_uid).map(e => `<option value="${escapeHtml(e.name)}">${escapeHtml(e.device_uid)}</option>`).join('');
  dl.dataset.loaded = '1';
}

function dhResults(results, okText) {
  const box = document.getElementById('dhResult');
  box.innerHTML = results.map(r => r.ok
    ? `<div style="color:#1e8e5a"><b>${escapeHtml(r.device)}:</b> ${okText(r)}</div>`
    : `<div style="color:#c0392b"><b>${escapeHtml(r.device)}:</b> ${escapeHtml(r.error)}</div>`).join('');
  box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
const DH_COUNT = v => (v === null || v === undefined) ? '—' : v;

async function dhManage(action) {
  const ids = dhChecked('dh-dev', 'id');
  if (!ids.length) { toast('حدّد جهازاً واحداً على الأقل', true); return; }
  const body = { ids, action };
  if (action === 'reboot' && !confirm(`إعادة تشغيل ${ids.length} جهاز؟ يتوقف الجهاز نحو دقيقة.`)) return;
  if (action === 'open_door' && !confirm('فتح الباب الآن من الأجهزة المحددة؟')) return;
  if (action === 'clear_records') {
    const w = prompt(`مسح كل سجلات الحضور المخزنة في ${ids.length} جهاز. تُسحب سجلات كل جهاز أولاً، ولا يُمسح جهاز تعذّر سحب سجلاته.\nاكتب «مسح» للتأكيد:`);
    if (w !== 'مسح') return;
    body.confirm = w;
  }
  document.getElementById('dhResult').textContent = 'جارٍ الاتصال بالأجهزة…';
  const d = await api('/api/dahua/manage', { method: 'POST', body: JSON.stringify(body) }).catch(() => null);
  if (!d) { document.getElementById('dhResult').textContent = ''; return; }
  if (d.results) {
    dhResults(d.results, r => ({
      info: () => `<span dir="ltr">${escapeHtml(r.model || '')} — ${escapeHtml(r.serial || '')}</span>، الإصدار <span dir="ltr">${escapeHtml(r.version || '—')}</span>،
        وقت الجهاز <span dir="ltr">${escapeHtml(r.device_time || '—')}</span> (الخادم <span dir="ltr">${escapeHtml(r.server_time)}</span>)<br>
        المستخدمون ${DH_COUNT(r.users)}، الوجوه ${DH_COUNT(r.faces)}، البطاقات ${DH_COUNT(r.cards)}، بصمات الإصبع ${DH_COUNT(r.fingerprints)}، السجلات ${DH_COUNT(r.records)}`,
      time_sync: () => `ضُبط وقت الجهاز على <span dir="ltr">${escapeHtml(r.device_time)}</span>`,
      reboot: () => 'يُعاد تشغيله الآن',
      open_door: () => 'فُتح الباب',
      clear_records: () => 'سُحبت السجلات ثم مُسحت من الجهاز',
    }[action] || (() => 'تم'))());
  } else toast(action === 'live_on' ? 'شُغّلت المراقبة الحية' : 'أُوقفت المراقبة الحية');
  dhLoad();
}

async function dhPushEmployees() {
  const ids = dhChecked('dh-dev', 'id');
  if (!ids.length) { toast('حدّد جهازاً واحداً على الأقل', true); return; }
  if (!confirm(`رفع كل الموظفين النشطين الذين لديهم «رقم بصمة» إلى ${ids.length} جهاز؟ يُضاف الجديد ويُحدَّث الاسم المختلف، ولا يُحذف شيء.`)) return;
  document.getElementById('dhResult').textContent = 'جارٍ الرفع…';
  const d = await api('/api/dahua/push-employees', { method: 'POST', body: JSON.stringify({ ids }) }).catch(() => null);
  if (!d) { document.getElementById('dhResult').textContent = ''; return; }
  dhResults(d.results, r => `${d.employees} موظف: أُضيف ${r.added}، حُدِّث ${r.updated}${r.unchanged !== undefined ? `، دون تغيير ${r.unchanged}` : ''}${r.failed ? `، <span style="color:#c0392b">تعذّر ${r.failed}</span>` : ''}`);
  dhUsersLoad();
}

async function dhUsersLoad() {
  const id = document.getElementById('dhuDevice').value;
  const tb = document.getElementById('dhUsers'), note = document.getElementById('dhuNote');
  if (!id) return;
  note.textContent = 'جارٍ القراءة من الجهاز…';
  const res = await fetch(`/api/dahua/devices/${id}/users`);
  const d = await res.json().catch(() => ({ ok: false, error: 'رد غير متوقع' }));
  if (!d.ok) { note.innerHTML = `<span style="color:#c0392b">${escapeHtml(d.error)}</span>`; tb.innerHTML = ''; dhCount(); return; }
  const yes = v => v === null || v === undefined ? '—' : (v ? '<span style="color:#1e8e5a">✓</span>' : '');
  tb.innerHTML = d.rows.map(u => `<tr>
    <td><input type="checkbox" class="dh-user" data-uid="${escapeHtml(u.uid)}" onchange="dhCount()"></td>
    <td dir="ltr">${escapeHtml(u.uid)}</td><td>${escapeHtml(u.name)}</td>
    <td>${u.employee ? escapeHtml(u.employee) : '<span style="color:#c0392b">غير مطابق</span>'}</td>
    <td>${yes(u.has_face)}</td><td dir="ltr">${escapeHtml(u.card || '')}</td><td>${u.fingerprints === null ? '—' : (u.fingerprints || '')}</td></tr>`).join('')
    || '<tr><td colspan="7" style="color:var(--muted)">لا يوجد مستخدمون في الجهاز</td></tr>';
  document.getElementById('dhuCount').textContent = d.rows.length;
  note.textContent = d.mode === 'legacy' ? 'إصدار أقدم من برنامج الجهاز: تظهر الأسماء والبطاقات فقط.' : '';
  const miss = document.getElementById('dhuMissing');
  miss.innerHTML = d.missing.length
    ? `<span style="color:#b45309">${d.missing.length} موظف لديه «رقم بصمة» وغير مسجّل في هذا الجهاز:</span> ${d.missing.slice(0, 25).map(m => escapeHtml(m.name)).join('، ')}${d.missing.length > 25 ? '…' : ''}
       — حدّد الجهاز في جدول الأجهزة واضغط «رفع الموظفين».`
    : '';
  dhCount();
  if (typeof initTableFilters === 'function') initTableFilters();
  if (typeof initTableSorting === 'function') initTableSorting(document.getElementById('devsub-dev-dahua'));
}

async function dhUsersDelete(all) {
  const id = document.getElementById('dhuDevice').value;
  if (!id) return;
  const body = {};
  if (all) {
    const w = prompt('حذف كل المستخدمين من الجهاز مع وجوههم وبطاقاتهم وبصماتهم (السجلات السابقة تبقى في النظام).\nاكتب «حذف الكل» للتأكيد:');
    if (w !== 'حذف الكل') return;
    body.all = true; body.confirm = w;
  } else {
    body.uids = dhChecked('dh-user', 'uid');
    if (!body.uids.length) { toast('حدّد مستخدماً واحداً على الأقل', true); return; }
    if (!confirm(`حذف ${body.uids.length} مستخدم من الجهاز مع وجوههم وبصماتهم؟`)) return;
  }
  const d = await api(`/api/dahua/devices/${id}/users/delete`, { method: 'POST', body: JSON.stringify(body) }).catch(() => null);
  if (d) toast(`حُذف ${d.deleted} مستخدم من الجهاز`);
  dhUsersLoad();
}

async function dhCopyRun() {
  const source_id = document.getElementById('dhcSource').value;
  const target_ids = [...document.querySelectorAll('#dhcTargets input:checked')].map(c => c.value).filter(v => v !== source_id);
  const what = [...document.querySelectorAll('.dhc-what:checked')].map(c => c.value);
  if (!source_id || !target_ids.length) { toast('حدّد الجهاز المصدر وجهازاً هدفاً واحداً على الأقل', true); return; }
  if (!what.length) { toast('اختر ما يُنسخ', true); return; }
  const uids = document.getElementById('dhuDevice').value === source_id ? dhChecked('dh-user', 'uid') : [];
  const box = document.getElementById('dhcResult');
  box.textContent = 'جارٍ النسخ… (قد يستغرق دقائق مع عدد كبير من الوجوه)';
  const d = await api('/api/dahua/copy', { method: 'POST', body: JSON.stringify({ source_id, target_ids, what, uids }) }).catch(() => null);
  if (!d) { box.textContent = ''; return; }
  box.innerHTML = `<div>${d.users} مستخدم من الجهاز المصدر:</div>` + Object.entries(d.per_target).map(([name, r]) =>
    `<div style="color:${r.errors.length ? '#b45309' : '#1e8e5a'}"><b>${escapeHtml(name)}:</b> وجوه ${r.faces}، بطاقات ${r.cards}، بصمات إصبع ${r.fingerprints}، مستخدمون جدد ${r.users}${r.errors.length ? ` — ${escapeHtml(r.errors.join('؛ '))}` : ''}</div>`).join('');
}

function dhFacePreview() {
  const f = document.getElementById('dhfPhoto').files[0], img = document.getElementById('dhfPreview');
  if (!f) { img.style.display = 'none'; return; }
  img.src = URL.createObjectURL(f); img.style.display = '';
}
async function dhFaceUpload() {
  const name = document.getElementById('dhfName').value.trim();
  const f = document.getElementById('dhfPhoto').files[0];
  const ids = dhChecked('dh-dev', 'id');
  if (!name || !f) { toast('اختر الموظف والصورة', true); return; }
  if (!ids.length) { toast('حدّد جهازاً واحداً على الأقل في جدول الأجهزة', true); return; }
  const fd = new FormData(); fd.append('name', name); fd.append('ids', ids.join(',')); fd.append('photo', f);
  const box = document.getElementById('dhfResult');
  box.textContent = 'جارٍ الرفع…';
  const res = await fetch('/api/dahua/face-photo', { method: 'POST', body: fd });
  const d = await res.json().catch(() => ({ ok: false, error: 'رد غير متوقع' }));
  if (!d.ok) { box.innerHTML = `<span style="color:#c0392b">${escapeHtml(d.error)}</span>`; return; }
  box.innerHTML = d.results.map(r => `<div style="color:${r.ok ? '#1e8e5a' : '#c0392b'}"><b>${escapeHtml(r.device)}:</b> ${r.ok ? 'سُجّل الوجه' : escapeHtml(r.error)}</div>`).join('');
}

let dhLiveSince = 0, dhLiveTimer = null;
const dhLiveRows = [];
async function dhLivePoll() {
  clearTimeout(dhLiveTimer);
  const panel = document.getElementById('devsub-dev-dahua');
  if (!panel || !panel.classList.contains('active') || document.hidden) { dhLiveTimer = setTimeout(dhLivePoll, 5000); return; }
  const d = await fetch('/api/dahua/live?since=' + dhLiveSince).then(r => r.ok ? r.json() : null).catch(() => null);
  if (d && d.events.length) {
    dhLiveSince = d.events[d.events.length - 1].id;
    dhLiveRows.unshift(...d.events.reverse());
    dhLiveRows.length = Math.min(dhLiveRows.length, 200);
    document.getElementById('dhLive').innerHTML = dhLiveRows.map(e => `<tr>
      <td dir="ltr">${escapeHtml(e.time)}</td><td>${escapeHtml(e.device)}</td><td dir="ltr">${escapeHtml(e.uid)}</td>
      <td>${e.name ? escapeHtml(e.name) : '<span style="color:#c0392b">غير مطابق</span>'}</td>
      <td>${e.ok ? '<span style="color:#1e8e5a">مقبولة</span>' : '<span style="color:#c0392b">مرفوضة</span>'}</td></tr>`).join('');
    document.getElementById('dhlCount').textContent = dhLiveRows.length;
  }
  dhLiveTimer = setTimeout(dhLivePoll, 3000);
}
