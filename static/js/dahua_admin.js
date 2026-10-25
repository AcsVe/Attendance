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
    <td dir="ltr">${escapeHtml(x.last_pull || '—')}</td><td dir="ltr">${escapeHtml(x.last_rec_ts || '—')}</td>
    <td>${x.today}</td><td>${x.total}</td><td>${dhUnmatched(x.unmatched)}</td>
    <td><button class="btn btn-outline btn-sm" onclick="dhEdit(${x.id})" aria-label="تعديل"><i class="fas fa-pen" aria-hidden="true"></i></button></td></tr>`).join('')
    || '<tr><td colspan="11" style="color:var(--muted)">لا توجد أجهزة Dahua مضافة بعد</td></tr>';
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
