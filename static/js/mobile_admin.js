/* =====================================================================
   تطبيق الموظفين على الهاتف — صفحات الإدارة (الحسابات، مواقع العمل، الحركات والمتابعة)
   يعتمد على: api() و toast() و escapeHtml() و toggleSelectAll() من app.js، و Leaflet للخرائط
   ===================================================================== */
Object.assign(PAGE_TITLES, {
  'mobile-accounts': 'حسابات تطبيق الهاتف', 'mobile-sites': 'مواقع العمل (النطاق الجغرافي)', 'mobile-moves': 'المتابعة المباشرة وحركات الهاتف',
});
window.EXTRA_LOADERS = Object.assign(window.EXTRA_LOADERS || {}, {
  'mobile-accounts': () => { loadAccounts(); loadMobileSettings(); },
  'mobile-sites': () => { loadSites(); loadKiosks(); },
  'mobile-moves': () => { loadLive(); loadMoves(); },
});

const OSM = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
const OSM_ATTR = '&copy; OpenStreetMap';
const mEsc = s => escapeHtml(s == null ? '' : String(s));

/* ================= الحسابات ================= */
const MODE_LABEL = { both: 'الجهاز + الهاتف', mobile: 'الهاتف (سحابي)', device: 'جهاز البصمة' };

let maRows = [], maDept = null, maState = '';   // maDept: null = كل الأقسام، '' = بدون قسم

async function loadAccounts() {
  document.getElementById('meLink').textContent = location.origin + '/me';
  const d = await api('/api/mobile/accounts');
  if (!d) return;
  maRows = d.rows;
  const depts = [...new Set(maRows.map(r => r.dept || ''))].sort();
  document.getElementById('maDeptList').innerHTML = depts.filter(Boolean).map(x => `<option value="${mEsc(x)}">`).join('');
  maRender();
}

function maMatches(r) {
  const q = (document.getElementById('maSearch').value || '').trim().toLowerCase();
  if (maDept !== null && (r.dept || '') !== maDept) return false;
  if (maState === 'none' && r.has_account) return false;
  if (maState === 'acc' && !r.has_account) return false;
  if (maState === 'unbound' && !(r.has_account && !r.device_label)) return false;
  if (maState === 'off' && !(r.has_account && !r.acc_active)) return false;
  if (q && ![r.name, r.dept, r.username, r.device_label, r.device_uid].some(v => (v || '').toLowerCase().includes(q))) return false;
  return true;
}

function maRender() {
  const byDept = {};
  maRows.forEach(r => { byDept[r.dept || ''] = (byDept[r.dept || ''] || 0) + 1; });
  document.getElementById('maDeptChips').innerHTML =
    `<button class="${maDept === null ? 'on' : ''}" onclick="maDept=null;maRender()">كل الأقسام <b>${maRows.length}</b></button>` +
    Object.keys(byDept).sort().map(k => `<button class="${maDept === k ? 'on' : ''}" data-dept="${mEsc(k)}" onclick="maDept=this.dataset.dept;maRender()">${mEsc(k || 'بدون قسم')} <b>${byDept[k]}</b></button>`).join('');
  const base = maRows.filter(r => maDept === null || (r.dept || '') === maDept);
  const st = {
    all: base.length, acc: base.filter(r => r.has_account).length, none: base.filter(r => !r.has_account).length,
    unbound: base.filter(r => r.has_account && !r.device_label).length, off: base.filter(r => r.has_account && !r.acc_active).length,
  };
  const chip = (k, label) => `<button class="${maState === k ? 'on' : ''}" onclick="maState='${k}';maRender()">${label} <b>${st[k === '' ? 'all' : k]}</b></button>`;
  document.getElementById('maStateChips').innerHTML = chip('', 'الكل') + chip('acc', 'لهم حساب') + chip('none', 'بدون حساب') + chip('unbound', 'لم يربطوا هاتفاً') + chip('off', 'موقوفة');
  const rows = maRows.filter(maMatches);
  document.getElementById('maShown').textContent = rows.length;
  document.getElementById('maTotal').textContent = maRows.length;
  document.getElementById('maTable').innerHTML = rows.map(r => `
    <tr><td><input type="checkbox" class="row-check" data-id="${r.id}" onchange="maCount()"></td>
      <td><a href="#" onclick="openEmployeeCard(${r.id});return false" style="font-weight:800;color:var(--primary-dark)">${mEsc(r.name)}</a>${r.active ? '' : ' <span class="badge badge-absent">معلّق</span>'}${r.device_uid ? `<br><small style="color:var(--muted)">بصمة ${mEsc(r.device_uid)}</small>` : ''}</td>
      <td>${mEsc(r.dept || '—')}</td><td><small>${MODE_LABEL[r.attendance_mode || 'both']}</small></td>
      <td dir="ltr" style="text-align:right">${r.has_account ? mEsc(r.username) : '<span style="color:var(--muted)">—</span>'}</td>
      <td>${r.device_label ? `${mEsc(r.device_label)}<br><small style="color:var(--muted)">${mEsc(r.bound_at || '')}</small>` : (r.has_account ? '<span class="badge badge-late">لم يُربط بعد</span>' : '—')}</td>
      <td><small>${mEsc(r.last_move || '—')}</small></td>
      <td>${!r.has_account ? '<span class="badge badge-none">بدون حساب</span>' : (r.acc_active ? '<span class="badge badge-ontime">مفعّل</span>' : '<span class="badge badge-absent">موقوف</span>')}${r.anywhere ? ' <span class="badge badge-holiday" title="يسجّل من أي مكان">أي مكان</span>' : ''}</td>
      <td><button class="btn btn-outline btn-sm" onclick="maEdit(${r.id})" title="تعديل اسم المستخدم/كلمة المرور" aria-label="تعديل اسم المستخدم/كلمة المرور"><i class="fas fa-pen" aria-hidden="true"></i></button></td></tr>`).join('')
    || '<tr><td colspan="9" style="text-align:center;color:var(--muted);padding:16px">لا يوجد موظفون مطابقون</td></tr>';
  document.getElementById('maAll').checked = false;
  maCount();
}

function maChecked() { return [...document.querySelectorAll('#maTable .row-check:checked')].map(c => +c.dataset.id); }
function maCount() { document.getElementById('maSel').textContent = `${maChecked().length} / ${document.querySelectorAll('#maTable .row-check').length}`; }
function maCheckAll(on) { document.querySelectorAll('#maTable .row-check').forEach(c => { c.checked = on; }); maCount(); }

const MA_LABELS = {
  create: 'إنشاء حسابات للمحددين الذين ليس لهم حساب', reset_password: 'كلمات مرور جديدة للمحددين', unbind: 'فكّ ربط الهاتف (يرتبط الهاتف التالي عند الدخول)',
  enable: 'تفعيل الحسابات', disable: 'إيقاف الحسابات', anywhere_on: 'السماح بالتسجيل من أي مكان (بدون Geofence)', anywhere_off: 'إلغاء «من أي مكان»', delete: 'حذف الحسابات (يبقى الموظف وسجلاته)',
};

async function maBulk(action) {
  const ids = maChecked();
  if (!ids.length) { toast('حدّد موظفاً واحداً على الأقل', true); return; }
  if (action === 'notify') { ecNotifyDialog(ids); return; }
  if (action.startsWith('emp:') || action.startsWith('mode:')) {
    const [kind, value] = action.split(':');
    const label = document.querySelector(`#maMore option[value="${action}"]`).textContent;
    if (!confirm(`${label}؟\n(${ids.length} موظف)`)) return;
    const d = await api('/api/mobile/employees/bulk', { method: 'POST', body: JSON.stringify({ ids, action: kind === 'emp' ? value : 'mode', value }) });
    if (!d) return;
    toast(`تم: ${d.count} موظف`);
    loadAccounts();
    return;
  }
  if (!confirm(`${MA_LABELS[action]}؟\n(${ids.length} موظف)`)) return;
  const d = await api('/api/mobile/accounts/bulk', { method: 'POST', body: JSON.stringify({ ids, action }) });
  if (!d) return;
  toast(`تم: ${d.count} موظف`);
  if (d.credentials && d.credentials.length) maShowCreds(d.credentials);
  loadAccounts();
}

let maCredsCache = [];
function maShowCreds(list) {
  maCredsCache = list;
  document.getElementById('maModalTitle').textContent = `بيانات الدخول (${list.length}) — احفظها الآن، لن تظهر كلمات المرور مرة أخرى`;
  document.getElementById('maModalBody').innerHTML = `<p style="font-size:.85rem;color:var(--muted)">رابط التطبيق: <b dir="ltr">${location.origin}/me</b></p>
    <div class="table-wrap"><table id="maCredTable"><thead><tr><th>الموظف</th><th>القسم</th><th>اسم المستخدم</th><th>كلمة المرور</th></tr></thead><tbody>
    ${list.map(c => `<tr><td>${mEsc(c.name)}</td><td>${mEsc(c.dept)}</td><td class="m-cred">${mEsc(c.username)}</td><td class="m-cred"><b>${mEsc(c.password)}</b></td></tr>`).join('')}</tbody></table></div>`;
  ['maModalCsv', 'maModalPrint'].forEach(id => { document.getElementById(id).style.display = ''; });
  document.getElementById('maModalSave').style.display = 'none';
  document.getElementById('maModalCsv').onclick = () => {
    const rows = [['الموظف', 'القسم', 'اسم المستخدم', 'كلمة المرور', 'الرابط']].concat(maCredsCache.map(c => [c.name, c.dept, c.username, c.password, location.origin + '/me']));
    const csv = '﻿' + rows.map((r, i) => r.map(v => `"${String(i === 0 && window.T ? T(String(v)) : v).replace(/"/g, '""')}"`).join(',')).join('\r\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    a.download = 'employee-app-logins.csv';
    a.click();
  };
  document.getElementById('maModal').classList.add('open');
}

function maPrint() {
  const w = window.open('', '_blank');
  w.document.write(`<html dir="rtl"><head><meta charset="utf-8"><title>بيانات دخول تطبيق الموظف</title><style>body{font-family:Tahoma,Arial;padding:20px}
    .c{display:inline-block;width:46%;margin:1%;border:1px dashed #999;border-radius:10px;padding:12px;vertical-align:top;page-break-inside:avoid}
    .c b{font-size:1.05rem}.m{font-family:Consolas,monospace;direction:ltr;font-size:1.1rem}</style></head><body>
    ${maCredsCache.map(c => `<div class="c"><b>${mEsc(c.name)}</b><br><small>${mEsc(c.dept)}</small><br>الرابط: <span class="m">${location.origin}/me</span><br>
    المستخدم: <span class="m">${mEsc(c.username)}</span><br>كلمة المرور: <span class="m">${mEsc(c.password)}</span></div>`).join('')}
    <script>print()<\/script></body></html>`);
  w.document.close();
}

function maEdit(id) {
  const r = maRows.find(x => x.id === id);
  if (!r) return;
  document.getElementById('maModalTitle').textContent = `حساب التطبيق — ${r.name}`;
  document.getElementById('maModalBody').innerHTML = `
    <div class="form-group"><label>اسم المستخدم</label><input type="text" id="maU" dir="ltr" value="${mEsc(r.username || '')}" placeholder="مثال: ahmad"></div>
    <div class="form-group"><label>كلمة المرور ${r.has_account ? '(اتركها فارغة دون تغيير)' : '*'}</label><input type="text" id="maP" dir="ltr" placeholder="6 أحرف على الأقل"></div>
    <label style="display:flex;gap:8px;align-items:center;font-weight:600"><input type="checkbox" id="maAny" ${r.anywhere ? 'checked' : ''}> يسجّل من أي مكان (موظف ميداني — بدون Geofence)</label>`;
  ['maModalCsv', 'maModalPrint'].forEach(x => { document.getElementById(x).style.display = 'none'; });
  const save = document.getElementById('maModalSave');
  save.style.display = '';
  save.onclick = async () => {
    const body = { employee_id: id, username: document.getElementById('maU').value.trim(), password: document.getElementById('maP').value, anywhere: document.getElementById('maAny').checked };
    const d = await api('/api/mobile/accounts', { method: 'POST', body: JSON.stringify(body) });
    if (!d) return;
    toast('تم الحفظ');
    document.getElementById('maModal').classList.remove('open');
    loadAccounts();
  };
  document.getElementById('maModal').classList.add('open');
}

async function maMoveDept() {
  const ids = maChecked();
  const dept = document.getElementById('maMoveDept').value.trim();
  if (!ids.length) { toast('حدّد موظفاً واحداً على الأقل', true); return; }
  if (!confirm(`نقل ${ids.length} موظف إلى القسم «${dept || 'بدون قسم'}»؟\nتُحدَّث سجلاتهم السابقة أيضاً ويُعاد التحليل.`)) return;
  const d = await api('/api/employees/bulk-dept', { method: 'POST', body: JSON.stringify({ ids, dept, history: true }) });
  if (!d) return;
  toast(`نُقل ${d.count} موظف`);
  loadAccounts();
  loadMetaInto();
}

async function loadMobileSettings() {
  const d = await api('/api/mobile/settings');
  if (!d) return;
  const s = d.settings;
  document.getElementById('msEnabled').checked = s.mobile_enabled === '1';
  document.getElementById('msBind').checked = s.mobile_bind_device === '1';
  document.getElementById('msGeo').checked = s.mobile_require_geofence === '1';
  document.getElementById('msLeave').checked = s.mobile_leave_deduct === '1';
  document.getElementById('msAcc').value = s.mobile_max_accuracy;
  document.getElementById('msApp').checked = s.mobile_require_app === '1';
  document.getElementById('msSusp').value = s.mobile_suspicious || 'flag';
  document.getElementById('msBio').value = s.mobile_biometric || 'off';
  if (!PERMS.can_edit_org_settings) document.querySelectorAll('#mobileSettingsCard input, #mobileSettingsCard button').forEach(e => { e.disabled = true; });
}

async function msSave() {
  await api('/api/mobile/settings', { method: 'POST', body: JSON.stringify({
    mobile_enabled: document.getElementById('msEnabled').checked, mobile_bind_device: document.getElementById('msBind').checked,
    mobile_require_geofence: document.getElementById('msGeo').checked, mobile_leave_deduct: document.getElementById('msLeave').checked,
    mobile_max_accuracy: document.getElementById('msAcc').value,
    mobile_require_app: document.getElementById('msApp').checked, mobile_suspicious: document.getElementById('msSusp').value,
    mobile_biometric: document.getElementById('msBio').value,
  }) });
  toast('حُفظت إعدادات التطبيق');
}

/* ================= مواقع العمل ================= */
let siteMap = null, siteLayer = null, siteDraft = null, siteRowsCache = [], siteDeptsCache = [];

function siteEnsureMap() {
  if (siteMap || typeof L === 'undefined') return;
  siteMap = L.map('siteMap').setView([31.95, 35.91], 12);
  L.tileLayer(OSM, { maxZoom: 19, attribution: OSM_ATTR }).addTo(siteMap);
  siteLayer = L.layerGroup().addTo(siteMap);
  siteMap.on('click', e => {
    document.getElementById('siteLat').value = e.latlng.lat.toFixed(6);
    document.getElementById('siteLng').value = e.latlng.lng.toFixed(6);
    siteDraw();
  });
}

function siteDraw() {
  if (!siteMap) return;
  if (siteDraft) { siteMap.removeLayer(siteDraft); siteDraft = null; }
  const lat = parseFloat(document.getElementById('siteLat').value), lng = parseFloat(document.getElementById('siteLng').value);
  const r = parseInt(document.getElementById('siteRadius').value || '150', 10);
  if (isNaN(lat) || isNaN(lng)) return;
  siteDraft = L.circle([lat, lng], { radius: r, color: '#EBB37B', weight: 3, fillOpacity: .25 }).addTo(siteMap);
}

async function loadSites() {
  const d = await api('/api/mobile/sites');
  if (!d) return;
  siteRowsCache = d.rows;
  siteDeptsCache = d.depts;
  document.getElementById('siteCount').textContent = d.rows.length;
  document.getElementById('sitesTable').innerHTML = d.rows.map(s => `
    <tr><td><input type="checkbox" class="row-check" data-id="${s.id}"></td>
      <td><b>${mEsc(s.name)}</b><br><small dir="ltr" style="color:var(--muted)">${s.lat.toFixed(5)}, ${s.lng.toFixed(5)}</small></td>
      <td>${s.radius_m} م</td><td><small>${s.depts.length ? s.depts.map(mEsc).join('، ') : 'كل الأقسام'}</small></td>
      <td><small dir="ltr">${mEsc(s.ips || '—')}</small>${s.ip_required ? '<br><span class="badge badge-ontime">إلزامي</span>' : ''}</td><td>${s.moves}</td>
      <td><button class="btn btn-sm ${s.active ? 'btn-primary' : 'btn-outline'}" onclick="siteToggle(${s.id}, ${s.active ? 0 : 1})">${s.active ? 'مفعّل' : 'معطّل'}</button></td>
      <td style="white-space:nowrap"><button class="btn btn-outline btn-sm" onclick="siteEdit(${s.id})" aria-label="تعديل" title="تعديل"><i class="fas fa-pen" aria-hidden="true"></i></button>
        <a class="btn btn-outline btn-sm" target="_blank" href="https://www.google.com/maps?q=${s.lat},${s.lng}"><i class="fas fa-map-location-dot" aria-hidden="true"></i></a></td></tr>`).join('')
    || '<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:16px">لا توجد مواقع عمل بعد — أضف موقعاً حتى يستطيع الموظفون التسجيل</td></tr>';
  siteRenderDepts([]);
  setTimeout(() => {
    siteEnsureMap();
    if (!siteMap) return;
    siteMap.invalidateSize();
    siteLayer.clearLayers();
    const bounds = [];
    d.rows.forEach(s => {
      L.circle([s.lat, s.lng], { radius: s.radius_m, color: s.active ? '#1B6E8C' : '#999', fillOpacity: .15 }).bindTooltip(s.name).addTo(siteLayer);
      bounds.push([s.lat, s.lng]);
    });
    if (bounds.length) siteMap.fitBounds(L.latLngBounds(bounds).pad(0.4), { maxZoom: 17 });
  }, 60);
}

function siteRenderDepts(selected) {
  document.getElementById('siteDepts').innerHTML = siteDeptsCache.map(dp =>
    `<label style="display:flex;gap:6px;align-items:center;font-weight:600"><input type="checkbox" class="site-dept" value="${mEsc(dp)}" ${selected.includes(dp) ? 'checked' : ''}> ${mEsc(dp)}</label>`).join('')
    || '<span style="color:var(--muted)">لا توجد أقسام بعد (أضف الأقسام للموظفين)</span>';
}

function siteReset() {
  ['siteId', 'siteName', 'siteLat', 'siteLng', 'siteIps'].forEach(id => { document.getElementById(id).value = ''; });
  document.getElementById('siteIpReq').checked = false;
  document.getElementById('siteRadius').value = 150;
  document.getElementById('siteFormTitle').textContent = 'إضافة موقع عمل';
  siteRenderDepts([]);
  siteDraw();
}

function siteEdit(id) {
  const s = siteRowsCache.find(x => x.id === id);
  if (!s) return;
  document.getElementById('siteId').value = s.id;
  document.getElementById('siteName').value = s.name;
  document.getElementById('siteLat').value = s.lat;
  document.getElementById('siteLng').value = s.lng;
  document.getElementById('siteRadius').value = s.radius_m;
  document.getElementById('siteIps').value = s.ips || '';
  document.getElementById('siteIpReq').checked = !!s.ip_required;
  document.getElementById('siteFormTitle').textContent = `تعديل: ${s.name}`;
  siteRenderDepts(s.depts);
  siteDraw();
  if (siteMap) siteMap.setView([s.lat, s.lng], 17);
  document.getElementById('tab-mobile-sites').scrollIntoView({ behavior: 'smooth' });
}

function siteMyLocation() {
  if (!navigator.geolocation) { toast('المتصفح لا يدعم تحديد الموقع', true); return; }
  toast('جارٍ تحديد موقعك…');
  navigator.geolocation.getCurrentPosition(p => {
    document.getElementById('siteLat').value = p.coords.latitude.toFixed(6);
    document.getElementById('siteLng').value = p.coords.longitude.toFixed(6);
    siteDraw();
    if (siteMap) siteMap.setView([p.coords.latitude, p.coords.longitude], 17);
    toast(`تم — دقة ${Math.round(p.coords.accuracy)} م`);
  }, () => toast('تعذّر تحديد الموقع — اسمح للمتصفح باستخدامه', true), { enableHighAccuracy: true, timeout: 20000 });
}

async function siteSave() {
  const id = document.getElementById('siteId').value;
  const body = {
    name: document.getElementById('siteName').value.trim(), lat: document.getElementById('siteLat').value,
    lng: document.getElementById('siteLng').value, radius_m: document.getElementById('siteRadius').value,
    depts: [...document.querySelectorAll('.site-dept:checked')].map(c => c.value), active: true,
    ips: document.getElementById('siteIps').value, ip_required: document.getElementById('siteIpReq').checked,
  };
  const d = await api(id ? '/api/mobile/sites/' + id : '/api/mobile/sites', { method: id ? 'PUT' : 'POST', body: JSON.stringify(body) });
  if (!d) return;
  toast('حُفظ الموقع');
  siteReset();
  loadSites();
}

async function siteAddMyIp() {
  const d = await api('/api/mobile/myip');
  if (!d) return;
  const el = document.getElementById('siteIps');
  const list = el.value.split(',').map(x => x.trim()).filter(Boolean);
  if (!list.includes(d.ip)) list.push(d.ip);
  el.value = list.join(', ');
  toast(`أُضيف ${d.ip} — تأكد أنك متصل الآن بشبكة Wi-Fi العمل`);
}

async function siteToggle(id, active) {
  await api('/api/mobile/sites/' + id, { method: 'PUT', body: JSON.stringify({ active: !!active }) });
  loadSites();
}

/* ================= الحركات والمتابعة ================= */
let liveMap = null, liveLayer = null, liveTimer = null, mvKind = '', mvStatus = '', mvFlag = false, mvRowsCache = [];
const ST_LABEL = { in: 'في الدوام', out: 'انصرف', leave: 'خروج مؤقت', none: 'لم يسجّل' };

async function loadLive() {
  const d = await api('/api/mobile/live');
  if (!d) return;
  document.getElementById('liveDate').textContent = d.date;
  document.getElementById('liveChips').innerHTML = `<button>الكل <b>${d.total}</b></button>` +
    ['in', 'leave', 'out', 'none'].map(k => `<button>${ST_LABEL[k]} <b>${d.state[k]}</b></button>`).join('');
  document.getElementById('liveTable').innerHTML = d.rows.map(r => `<tr><td><a href="#" onclick="openEmployeeCard(${r.id});return false"><b>${mEsc(r.name)}</b></a></td><td>${mEsc(r.dept || '')}</td>
    <td><span class="m-state m-st-${r.state}">${ST_LABEL[r.state]}</span></td><td>${r.time ? `${mEsc(r.kind_label)} <b dir="ltr">${r.time}</b>` : '—'}</td><td>${mEsc(r.site || '')}</td></tr>`).join('')
    || '<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:16px">لا يوجد موظفون لهم حسابات تطبيق بعد</td></tr>';
  setTimeout(() => {
    if (typeof L === 'undefined') return;
    if (!liveMap) {
      liveMap = L.map('liveMap').setView([31.95, 35.91], 12);
      L.tileLayer(OSM, { maxZoom: 19, attribution: OSM_ATTR }).addTo(liveMap);
      liveLayer = L.layerGroup().addTo(liveMap);
    }
    liveMap.invalidateSize();
    liveLayer.clearLayers();
    const b = [];
    d.sites.forEach(s => { L.circle([s.lat, s.lng], { radius: s.radius, color: '#1B6E8C', fillOpacity: .08, weight: 1 }).addTo(liveLayer); b.push([s.lat, s.lng]); });
    const color = { in: '#0a6640', leave: '#d9822b', out: '#6c757d' };
    d.rows.filter(r => r.lat != null).forEach(r => {
      L.circleMarker([r.lat, r.lng], { radius: 8, color: '#fff', weight: 2, fillColor: color[r.state] || '#333', fillOpacity: 1 })
        .bindTooltip(`${r.name} — ${r.kind_label} ${r.time}`).addTo(liveLayer);
      b.push([r.lat, r.lng]);
    });
    if (b.length && !liveMap._fitted) { liveMap.fitBounds(L.latLngBounds(b).pad(0.3), { maxZoom: 17 }); liveMap._fitted = true; }
  }, 60);
  clearTimeout(liveTimer);
  liveTimer = setTimeout(() => {
    if (currentTab === 'mobile-moves' && document.getElementById('liveAuto').checked && !document.hidden) { loadLive(); loadMoves(true); }
  }, 30000);
}

function mvParams() {
  const p = new URLSearchParams();
  ['From', 'To', 'Dept', 'Name'].forEach(k => { const v = document.getElementById('mv' + k).value; if (v) p.set(k.toLowerCase(), v); });
  if (mvKind) p.set('kind', mvKind);
  if (mvStatus) p.set('status', mvStatus);
  if (mvFlag) p.set('flagged', '1');
  return p;
}

async function loadMoves(quiet) {
  const f = document.getElementById('mvFrom');
  if (!f.value) { const t = new Date(); const s = new Date(t.getTime() - t.getTimezoneOffset() * 60000).toISOString().slice(0, 10); f.value = s; document.getElementById('mvTo').value = s; }
  const d = await api('/api/mobile/punches?' + mvParams().toString());
  if (!d) return;
  mvRowsCache = d.rows;
  const deptSel = document.getElementById('mvDept'), nameSel = document.getElementById('mvName');
  if (deptSel.options.length <= 1 && typeof metaCache !== 'undefined') { /* تملؤها loadMetaInto إن وُجدت */ }
  const keepName = nameSel.value;
  nameSel.innerHTML = '<option value="">كل الموظفين</option>' + d.names.map(n => `<option ${n === keepName ? 'selected' : ''}>${mEsc(n)}</option>`).join('');
  const depts = [...new Set(maRows.map(r => r.dept).filter(Boolean).concat(d.rows.map(r => r.dept).filter(Boolean)))].sort();
  const keepDept = deptSel.value;
  deptSel.innerHTML = '<option value="">كل الأقسام</option>' + depts.map(n => `<option ${n === keepDept ? 'selected' : ''}>${mEsc(n)}</option>`).join('');
  const c = d.counts;
  const chip = (kind, status, label, n) => `<button class="${!mvFlag && mvKind === kind && mvStatus === status ? 'on' : ''}" onclick="mvFlag=false;mvKind='${kind}';mvStatus='${status}';loadMoves()">${label} <b>${n}</b></button>`;
  document.getElementById('mvChips').innerHTML = chip('', '', 'الكل', c.all) + chip('in', 'accepted', 'حضور', c.in) + chip('out', 'accepted', 'انصراف', c.out) +
    chip('leave_out', 'accepted', 'خروج مؤقت', c.leave_out) + chip('leave_back', 'accepted', 'عودة', c.leave_back) + chip('', 'rejected', 'مرفوضة', c.rejected) +
    `<button class="${mvFlag ? 'on' : ''}" onclick="mvFlag=!mvFlag;mvKind='';mvStatus='';loadMoves()">⚠ مشبوهة <b>${c.flagged}</b></button>`;
  mvFilter();
}

function mvFilter() {
  const q = (document.getElementById('mvSearch').value || '').trim().toLowerCase();
  const rows = mvRowsCache.filter(r => !q || [r.name, r.dept, r.site_name, r.reason, r.kind_label, r.device_label, r.flags].some(v => (v || '').toLowerCase().includes(q)));
  document.getElementById('mvShown').textContent = `${rows.length} من ${mvRowsCache.length}`;
  document.getElementById('mvTable').innerHTML = rows.map(r => `<tr${r.status === 'rejected' ? ' style="background:#fff5f5"' : (r.flags ? ' style="background:#fffbeb"' : '')}>
    <td><input type="checkbox" class="row-check" data-id="${r.id}" onchange="mvSelCount()" aria-label="تحديد"></td><td>${mEsc(r.date)}</td><td dir="ltr" style="text-align:right">${mEsc(r.time.slice(0, 5))}</td><td><b>${mEsc(r.name)}</b></td><td>${mEsc(r.dept || '')}</td>
    <td>${mEsc(r.kind_label)}</td><td>${mEsc(r.site_name || '—')}${r.distance_m != null ? ` <small style="color:var(--muted)">(${Math.round(r.distance_m)} م)</small>` : ''}</td>
    <td>${r.accuracy != null ? Math.round(r.accuracy) + ' م' : '—'}<br><small style="color:var(--muted)">${r.source === 'kiosk' ? '<i class="fas fa-qrcode" aria-hidden="true"></i> جهاز المدخل' : r.source === 'app' ? '<i class="fas fa-mobile-screen" aria-hidden="true"></i> التطبيق' : '<i class="fas fa-globe" aria-hidden="true"></i> المتصفح'}</small></td>
    <td>${r.status === 'accepted' ? '<span class="badge badge-ontime">مقبولة</span>' : `<span class="badge badge-absent" title="${mEsc(r.reason || '')}">مرفوضة</span><br><small style="color:#842029">${mEsc(r.reason || '')}</small>`}${r.flags ? `<br><small style="color:#b45309">⚠ ${mEsc(r.flags)}</small>` : ''}</td>
    <td>${r.lat != null ? `<a target="_blank" href="https://www.google.com/maps?q=${r.lat},${r.lng}"><i class="fas fa-map-location-dot" aria-hidden="true"></i></a>` : ''}</td></tr>`).join('')
    || '<tr><td colspan="10" style="text-align:center;color:var(--muted);padding:16px">لا توجد حركات في هذه الفترة</td></tr>';
  document.getElementById('mvAll').checked = false;
  mvSelCount();
}

function mvSelCount() {
  const all = document.querySelectorAll('#mvTable .row-check').length, n = document.querySelectorAll('#mvTable .row-check:checked').length;
  document.getElementById('mvSelN').textContent = n ? `(${n} من ${all})` : '';
}

async function mvDelete() {
  const ids = Array.from(document.querySelectorAll('#mvTable .row-check:checked')).filter(c => c.closest('tr').style.display !== 'none').map(c => +c.dataset.id);
  if (!ids.length) { toast('حدّد حركة واحدة على الأقل', true); return; }
  if (!confirm(`حذف ${ids.length} حركة نهائياً؟ يُعاد تحليل الحضور بعدها.`)) return;
  const d = await api('/api/mobile/punches/delete', { method: 'POST', body: JSON.stringify({ ids }) });
  if (d) { toast(`حُذفت ${d.count} حركة`); loadMoves(); loadLive(); }
}

function mvExport(fmt) {
  const p = mvParams();
  p.set('format', fmt);
  window.location.href = '/api/mobile/punches/export?' + p.toString();
}

/* ================= توزيع الموظفين على الأقسام (تبويب الموظفون) ================= */
async function empMoveDept() {
  const ids = [...document.querySelectorAll('#employeesTable .row-check:checked')].filter(c => c.closest('tr').style.display !== 'none').map(c => +c.dataset.id);
  const dept = document.getElementById('empMoveDept').value.trim();
  if (!ids.length) { toast('حدّد موظفاً واحداً على الأقل', true); return; }
  if (!confirm(`نقل ${ids.length} موظف إلى القسم «${dept || 'بدون قسم'}»؟\nتُحدَّث سجلاتهم السابقة أيضاً ويُعاد التحليل.`)) return;
  const d = await api('/api/employees/bulk-dept', { method: 'POST', body: JSON.stringify({ ids, dept, history: true }) });
  if (!d) return;
  toast(`نُقل ${d.count} موظف`);
  loadEmployees();
  loadMetaInto();
}

(function () {   // أعداد كل قسم + قائمة الأقسام بعد تحميل جدول الموظفين
  const orig = window.loadEmployees;
  if (!orig) return;
  window.loadEmployees = async function () {
    await orig.apply(this, arguments);
    const rows = [...document.querySelectorAll('#employeesTable tr')].filter(tr => tr.children.length > 3);
    const counts = {};
    rows.forEach(tr => { const d = tr.children[2].textContent.trim() || 'بدون قسم'; counts[d] = (counts[d] || 0) + 1; });
    document.getElementById('empDeptCounts').textContent = `الكل (${rows.length}) · ` + Object.keys(counts).sort().map(k => `${k} (${counts[k]})`).join(' · ');
    document.getElementById('empDeptList').innerHTML = Object.keys(counts).filter(k => k !== 'بدون قسم').map(k => `<option value="${mEsc(k)}">`).join('');
  };
})();


/* ================= بطاقة الموظف ================= */
let ecData = null;
const ec$ = id => document.getElementById(id);

function ecTab(t) {
  document.querySelectorAll('.ec-pane').forEach(p => { p.style.display = p.id === 'ec-' + t ? '' : 'none'; });
  document.querySelectorAll('#ecModal .subtab-btn').forEach(b => b.classList.toggle('active', b.dataset.ec === t));
}

async function openEmployeeCard(id) {
  const d = await api('/api/mobile/employee/' + id);
  if (!d) return;
  ecData = d;
  const e = d.employee, a = d.account, s = d.summary;
  ec$('ecTitle').innerHTML = `${mEsc(e.name)} <small style="color:var(--muted);font-weight:600">${mEsc(e.dept || 'بدون قسم')}${e.job_title ? ' · ' + mEsc(e.job_title) : ''}</small> ${e.active ? '<span class="badge badge-ontime">فعّال</span>' : '<span class="badge badge-absent">معلّق</span>'}`;
  const can = PERMS.can_manage_employees ? '' : 'disabled';
  ec$('ec-info').innerHTML = `
    <div class="form-grid trio">
      <div class="form-group"><label>الاسم</label><input type="text" id="ecName" value="${mEsc(e.name)}" ${can}></div>
      <div class="form-group"><label>القسم</label><input type="text" id="ecDept" list="maDeptList" value="${mEsc(e.dept || '')}" ${can}></div>
      <div class="form-group"><label>رقم البصمة على الجهاز</label><input type="text" id="ecUid" dir="ltr" value="${mEsc(e.device_uid || '')}" ${can}></div>
      <div class="form-group"><label>المسمى الوظيفي</label><input type="text" id="ecJob" value="${mEsc(e.job_title || '')}" ${can}></div>
      <div class="form-group"><label>الهاتف</label><input type="tel" id="ecPhone" dir="ltr" value="${mEsc(e.phone || '')}" ${can}></div>
      <div class="form-group"><label>البريد</label><input type="email" id="ecEmail" dir="ltr" value="${mEsc(e.email || '')}" ${can}></div>
      <div class="form-group"><label>طريقة توثيق الدوام</label><select id="ecMode" class="search-input" ${can}>
        <option value="both">جهاز البصمة + تطبيق الهاتف (الأبكر حضوراً والأخير انصرافاً)</option>
        <option value="mobile">تطبيق الهاتف فقط (سحابي) — تُتجاهل بصمات الجهاز</option>
        <option value="device">جهاز البصمة فقط — التطبيق لا يسجّل</option></select></div>
      <div class="form-group"><label>الحالة</label><select id="ecActive" class="search-input" ${can}><option value="1">فعّال</option><option value="0">معلّق (لا يدخل التطبيق ولا يظهر في المتابعة)</option></select></div>
      <div class="form-group"><label>ملاحظات</label><input type="text" id="ecNotes" value="${mEsc(e.notes || '')}" ${can}></div>
    </div>
    <button class="btn btn-primary" onclick="ecSave()" ${can}><i class="fas fa-save" aria-hidden="true"></i> حفظ</button>
    <div class="card" style="margin-top:14px;background:#f8fbfc">
      <div class="card-title"><i class="fas fa-mobile-screen" aria-hidden="true"></i> حساب التطبيق</div>
      ${a ? `<div style="line-height:2">اسم المستخدم: <b dir="ltr">${mEsc(a.username)}</b> · ${a.active ? 'مفعّل' : '<b style="color:#c0392b">موقوف</b>'}${a.anywhere ? ' · يسجّل من أي مكان' : ''}<br>
        الهاتف: ${a.device_label ? mEsc(a.device_label) + ' <small>(' + mEsc(a.bound_at || '') + ')</small>' : 'لم يُربط بعد'} · آخر دخول: ${mEsc(a.last_login_at || '—')} · البصمة الحيوية: ${d.bio ? 'مفعّلة' : '—'}</div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px">
          <button class="btn btn-outline btn-sm" onclick="ecAcc('reset_password')"><i class="fas fa-key" aria-hidden="true"></i> كلمة مرور جديدة</button>
          <button class="btn btn-outline btn-sm" onclick="ecAcc('unbind')"><i class="fas fa-link-slash" aria-hidden="true"></i> فكّ ربط الهاتف</button>
          <button class="btn btn-outline btn-sm" onclick="ecAcc('${a.active ? 'disable' : 'enable'}')">${a.active ? 'إيقاف الحساب' : 'تفعيل الحساب'}</button></div>`
      : `<p style="color:var(--muted)">لا يوجد حساب تطبيق.</p><button class="btn btn-primary btn-sm" onclick="ecAcc('create')"><i class="fas fa-user-plus" aria-hidden="true"></i> إنشاء حساب</button>`}
    </div>`;
  ec$('ecMode').value = e.attendance_mode || 'both';
  ec$('ecActive').value = e.active ? '1' : '0';
  ec$('ec-att').innerHTML = `
    <div class="stats-grid" style="margin-bottom:10px">
      <div class="stat-card green" style="cursor:default"><div class="stat-val">${s.days}</div><div class="stat-label">أيام حضور (الشهر)</div></div>
      <div class="stat-card orange" style="cursor:default"><div class="stat-val">${s.late_days}</div><div class="stat-label">أيام تأخير · ${s.late_minutes} د</div></div>
      <div class="stat-card red" style="cursor:default"><div class="stat-val">${s.absent}</div><div class="stat-label">غياب</div></div>
      <div class="stat-card" style="cursor:default"><div class="stat-val">${s.hours}</div><div class="stat-label">ساعات العمل</div></div>
    </div>
    <p style="font-size:.85rem;color:var(--muted)">مصادر البصمات هذا الشهر: جهاز البصمة ${d.sources.device || 0} يوم · الهاتف ${d.sources.mobile || 0} يوم · طريقة التوثيق: <b>${MODE_LABEL[e.attendance_mode || 'both']}</b></p>
    <div class="table-wrap" style="max-height:260px;overflow:auto"><table><thead><tr><th>التاريخ</th><th>حضور</th><th>انصراف</th><th>الحالة</th><th>تأخير</th><th>ساعات</th></tr></thead><tbody>
      ${d.days.map(x => `<tr><td>${mEsc(x.date)}</td><td dir="ltr">${mEsc(x.time_in || '—')}</td><td dir="ltr">${mEsc(x.time_out || '—')}</td><td>${mEsc(x.status || '')}</td><td>${x.late_minutes || 0}</td><td>${x.working_hours || 0}</td></tr>`).join('') || '<tr><td colspan="6" style="color:var(--muted)">لا توجد بيانات محلّلة لهذا الشهر</td></tr>'}
    </tbody></table></div>
    <h4 style="margin:12px 0 6px;color:var(--primary-dark)">آخر حركات الهاتف</h4>
    <div class="table-wrap" style="max-height:260px;overflow:auto"><table><thead><tr><th>التاريخ</th><th>الوقت</th><th>الحركة</th><th>الموقع</th><th>الحالة</th><th></th></tr></thead><tbody>
      ${d.moves.map(m => `<tr${m.status === 'rejected' ? ' style="background:#fff5f5"' : (m.flags ? ' style="background:#fffbeb"' : '')}><td>${mEsc(m.date)}</td><td dir="ltr">${mEsc(m.time.slice(0, 5))}</td><td>${mEsc(m.kind_label)}</td>
        <td>${mEsc(m.site_name || '—')}${m.distance_m != null ? ' <small>(' + Math.round(m.distance_m) + ' م)</small>' : ''}</td>
        <td>${m.status === 'accepted' ? 'مقبولة' : '<span style="color:#c0392b">' + mEsc(m.reason || 'مرفوضة') + '</span>'}${m.flags ? '<br><small style="color:#b45309">⚠ ' + mEsc(m.flags) + '</small>' : ''}</td>
        <td>${m.lat != null ? `<a target="_blank" href="https://www.google.com/maps?q=${m.lat},${m.lng}"><i class="fas fa-map-location-dot" aria-hidden="true"></i></a>` : ''}</td></tr>`).join('') || '<tr><td colspan="6" style="color:var(--muted)">لا توجد حركات</td></tr>'}
    </tbody></table></div>`;
  const nowIso = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  ec$('ec-ov').innerHTML = `
    <p style="font-size:.86rem;color:var(--muted);line-height:1.8">للحالات النادرة فقط: مهمة رسمية خارج المدرسة، عطل في GPS الهاتف، تغيير مؤقت لمكان العمل.
      خلال المدة يستطيع الموظف التسجيل من أي مكان (ويُحفظ موقعه وتُعلَّم حركاته «استثناء موقع» للمراجعة). يصله إشعار بذلك.</p>
    <div class="form-grid">
      <div class="form-group"><label>المدة</label><select id="ovPreset" class="search-input" onchange="ec$('ovCustom').style.display=this.value==='custom'?'':'none'">
        <option value="2">ساعتان</option><option value="4">4 ساعات</option><option value="today">حتى نهاية اليوم</option><option value="24">24 ساعة</option><option value="72">3 أيام</option><option value="168">أسبوع</option><option value="custom">من — إلى…</option></select></div>
      <div class="form-group"><label>السبب (يظهر للموظف وفي السجل) *</label><input type="text" id="ovReason" placeholder="مثال: مهمة رسمية في مديرية التربية"></div>
    </div>
    <div class="form-grid" id="ovCustom" style="display:none">
      <div class="form-group"><label>من</label><input type="datetime-local" id="ovFrom" value="${nowIso}"></div>
      <div class="form-group"><label>إلى</label><input type="datetime-local" id="ovTo"></div>
    </div>
    <label style="display:flex;gap:8px;align-items:center;font-weight:600;margin:6px 0"><input type="checkbox" id="ovNoLoc"> السماح حتى بدون تحديد الموقع (عطل GPS)</label>
    <button class="btn btn-primary" onclick="ecOverride()" ${can}><i class="fas fa-unlock" aria-hidden="true"></i> منح الاستثناء</button>
    <h4 style="margin:14px 0 6px;color:var(--primary-dark)">الاستثناءات</h4>
    <div class="table-wrap"><table><thead><tr><th>من</th><th>إلى</th><th>السبب</th><th>بواسطة</th><th>الحالة</th><th></th></tr></thead><tbody>
      ${d.overrides.map(o => `<tr><td>${mEsc(o.starts_at)}</td><td>${mEsc(o.ends_at)}</td><td>${mEsc(o.reason)}${o.no_location ? ' <small>(بدون موقع)</small>' : ''}</td><td>${mEsc(o.created_by || '')}</td>
        <td>${o.revoked ? '<span class="badge badge-none">أُلغي</span>' : o.active ? '<span class="badge badge-ontime">ساري</span>' : '<span class="badge badge-none">منتهٍ/لاحق</span>'}</td>
        <td>${!o.revoked ? `<button class="btn btn-red btn-sm" onclick="ecRevoke(${o.id})" ${can}>إلغاء</button>` : ''}</td></tr>`).join('') || '<tr><td colspan="6" style="color:var(--muted)">لا توجد استثناءات</td></tr>'}
    </tbody></table></div>`;
  ec$('ec-msg').innerHTML = `
    <div class="form-group"><label>العنوان *</label><input type="text" id="ecMsgTitle" placeholder="مثال: تذكير بموعد الاجتماع"></div>
    <div class="form-group"><label>النص</label><textarea id="ecMsgBody" rows="4" style="width:100%;border:1px solid var(--border);border-radius:10px;padding:10px;font-family:inherit"></textarea></div>
    <button class="btn btn-primary" onclick="ecNotify([${e.id}], ec$('ecMsgTitle').value, ec$('ecMsgBody').value)"><i class="fas fa-paper-plane" aria-hidden="true"></i> إرسال إلى تطبيق الموظف</button>
    <h4 style="margin:14px 0 6px;color:var(--primary-dark)">الإشعارات المرسلة</h4>
    <ul style="list-style:none;padding:0">${d.notifications.map(n => `<li style="border-bottom:1px dashed var(--border);padding:7px 0"><b>${mEsc(n.title)}</b> <small style="color:var(--muted)">${mEsc(n.created_at)} · ${mEsc(n.created_by || '')} · ${n.read_at ? 'قُرئ ' + mEsc(n.read_at) : 'لم يُقرأ'}</small>${n.body ? '<div style="white-space:pre-line;color:var(--muted)">' + mEsc(n.body) + '</div>' : ''}</li>`).join('') || '<li style="color:var(--muted)">لا توجد</li>'}</ul>`;
  ec$('ec-log').innerHTML = `<div class="table-wrap"><table><thead><tr><th>الوقت</th><th>المستخدم</th><th>العملية</th><th>التفاصيل</th></tr></thead><tbody>
    ${d.audit.map(x => `<tr><td>${mEsc(x.timestamp)}</td><td>${mEsc(x.username || '')}</td><td>${mEsc(AUDIT_ACTION_LABELS[x.action_type] || x.action_type)}</td><td><small>${x.old_value ? mEsc(x.old_value) + ' ← ' : ''}${mEsc(x.new_value || '')}${x.reason ? ' — ' + mEsc(x.reason) : ''}</small></td></tr>`).join('') || '<tr><td colspan="4" style="color:var(--muted)">لا توجد عمليات مسجّلة على هذا الموظف</td></tr>'}
    </tbody></table></div>`;
  ecTab('info');
  ec$('ecModal').classList.add('open');
}

async function ecSave() {
  const e = ecData.employee;
  const body = { name: ec$('ecName').value.trim(), dept: ec$('ecDept').value.trim(), device_uid: ec$('ecUid').value.trim(), job_title: ec$('ecJob').value,
    phone: ec$('ecPhone').value, email: ec$('ecEmail').value, notes: ec$('ecNotes').value, attendance_mode: ec$('ecMode').value, active: ec$('ecActive').value === '1' };
  if (body.name !== e.name && !confirm(`تغيير الاسم إلى «${body.name}»؟ ينتقل الاسم الجديد إلى كل سجلاته السابقة.`)) return;
  const d = await api('/api/mobile/employee/' + e.id, { method: 'PUT', body: JSON.stringify(body) });
  if (!d) return;
  toast(d.changed.length ? 'حُفظت التعديلات' : 'لا تغييرات');
  openEmployeeCard(e.id);
  if (currentTab === 'mobile-accounts') loadAccounts();
  if (currentTab === 'employees') loadEmployees();
}

async function ecAcc(action) {
  const id = ecData.employee.id;
  if (!confirm((MA_LABELS[action] || action) + '؟')) return;
  const d = await api('/api/mobile/accounts/bulk', { method: 'POST', body: JSON.stringify({ ids: [id], action }) });
  if (!d) return;
  if (d.credentials && d.credentials.length) { ec$('ecModal').classList.remove('open'); maShowCreds(d.credentials); }
  else { toast('تم'); openEmployeeCard(id); }
}

async function ecOverride() {
  const p = ec$('ovPreset').value, body = { reason: ec$('ovReason').value.trim(), no_location: ec$('ovNoLoc').checked };
  if (p === 'custom') { body.starts_at = ec$('ovFrom').value; body.ends_at = ec$('ovTo').value; }
  else if (p === 'today') { const t = new Date(); t.setHours(23, 59, 0, 0); body.ends_at = new Date(t.getTime() - t.getTimezoneOffset() * 60000).toISOString().slice(0, 16); }
  else body.hours = +p;
  const d = await api(`/api/mobile/employee/${ecData.employee.id}/override`, { method: 'POST', body: JSON.stringify(body) });
  if (!d) return;
  toast('مُنح الاستثناء وأُبلغ الموظف');
  openEmployeeCard(ecData.employee.id);
  setTimeout(() => ecTab('ov'), 50);
}

async function ecRevoke(id) {
  if (!confirm('إلغاء هذا الاستثناء الآن؟')) return;
  await api('/api/mobile/override/' + id, { method: 'DELETE' });
  toast('أُلغي الاستثناء');
  openEmployeeCard(ecData.employee.id);
  setTimeout(() => ecTab('ov'), 50);
}

async function ecNotify(ids, title, body) {
  if (!title || !title.trim()) { toast('اكتب عنوان الإشعار', true); return; }
  const d = await api('/api/mobile/notify', { method: 'POST', body: JSON.stringify({ ids, title, body }) });
  if (!d) return;
  toast(`أُرسل الإشعار إلى ${d.count} موظف — يظهر في تطبيقهم`);
  if (ids.length === 1 && ecData && ecData.employee.id === ids[0]) { openEmployeeCard(ids[0]); setTimeout(() => ecTab('msg'), 50); }
}

function ecNotifyDialog(ids) {
  document.getElementById('maModalTitle').textContent = `إرسال إشعار إلى ${ids.length} موظف`;
  document.getElementById('maModalBody').innerHTML = `<div class="form-group"><label>العنوان *</label><input type="text" id="bnTitle"></div>
    <div class="form-group"><label>النص</label><textarea id="bnBody" rows="4" style="width:100%;border:1px solid var(--border);border-radius:10px;padding:10px;font-family:inherit"></textarea></div>`;
  ['maModalCsv', 'maModalPrint'].forEach(x => { document.getElementById(x).style.display = 'none'; });
  const save = document.getElementById('maModalSave');
  save.style.display = '';
  save.innerHTML = '<i class="fas fa-paper-plane" aria-hidden="true"></i> إرسال';
  save.onclick = async () => { await ecNotify(ids, document.getElementById('bnTitle').value, document.getElementById('bnBody').value); document.getElementById('maModal').classList.remove('open'); save.innerHTML = '<i class="fas fa-save" aria-hidden="true"></i> حفظ'; };
  document.getElementById('maModal').classList.add('open');
}


/* إجراءات جماعية من تبويب «الموظفون» */
async function empBulkAction(action) {
  if (!action) return;
  const ids = Array.from(document.querySelectorAll('#employeesTable .row-check:checked')).map(c => +c.dataset.id);
  if (!ids.length) { toast('حدّد موظفاً واحداً على الأقل', true); return; }
  if (action === 'notify') { ecNotifyDialog(ids); return; }
  const [kind, value] = action.split(':');
  if (!confirm(`تطبيق الإجراء على ${ids.length} موظف؟`)) return;
  const d = await api('/api/mobile/employees/bulk', { method: 'POST', body: JSON.stringify({ ids, action: kind === 'emp' ? value : 'mode', value }) });
  if (d) { toast(`تم: ${d.count} موظف`); loadEmployees(); }
}


/* ================= أجهزة المداخل (QR) ================= */
let kioskRows = [];
async function loadKiosks() {
  const d = await api('/api/kiosks');
  if (!d) return;
  kioskRows = d.rows;
  document.getElementById('kioskUrl').textContent = location.origin + '/kiosk';
  document.getElementById('kioskCount').textContent = d.rows.length;
  const sel = document.getElementById('kioskSite'), keep = sel.value;
  sel.innerHTML = '<option value="">— بدون —</option>' + (siteRowsCache || []).map(x => `<option value="${x.id}">${mEsc(x.name)}</option>`).join('');
  sel.value = keep;
  const ago = t => { if (!t) return 'لم يتصل بعد'; const m = Math.round((Date.now() - new Date(t.replace(' ', 'T')).getTime()) / 60000); return m < 2 ? '<span style="color:#1e8e5a">متصل الآن</span>' : (m < 60 ? `قبل ${m} دقيقة` : t); };
  document.getElementById('kioskTable').innerHTML = d.rows.map(k => `<tr>
    <td><input type="checkbox" class="row-check" data-id="${k.id}" onchange="kioskCount()" aria-label="تحديد"></td>
    <td><b>${mEsc(k.name)}</b></td><td>${mEsc(k.site_name || '—')}</td>
    <td>${k.paired ? '<span class="badge badge-ontime">مقترن</span>' : ''}${k.pair_code ? `<div style="margin-top:4px">رمز الإقران: <b dir="ltr" style="font-size:1.1rem;letter-spacing:3px">${k.pair_code}</b><br><small style="color:var(--muted)">صالح 30 دقيقة — أو افتح: <span dir="ltr">${mEsc(location.origin)}/kiosk?pair=${k.pair_code}</span></small></div>` : (k.paired ? '' : '<small style="color:var(--muted)">غير مقترن — اطلب «رمز إقران جديد»</small>')}</td>
    <td>${ago(k.last_seen)}</td><td>${k.today}</td>
    <td>${k.active ? '<span class="badge badge-ontime">مفعّل</span>' : '<span class="badge badge-absent">معطّل</span>'}</td></tr>`).join('')
    || '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:14px">لا توجد أجهزة مداخل بعد</td></tr>';
  document.getElementById('kioskAll').checked = false;
  kioskCount();
}
function kioskCount() {
  const all = document.querySelectorAll('#kioskTable .row-check').length, n = document.querySelectorAll('#kioskTable .row-check:checked').length;
  document.getElementById('kioskSel').textContent = `المحدَّد: ${n} من ${all}`;
}
async function kioskAdd() {
  const name = document.getElementById('kioskName').value.trim();
  if (!name) { toast('اكتب اسماً للجهاز', true); return; }
  const d = await api('/api/kiosks', { method: 'POST', body: JSON.stringify({ name, site_id: document.getElementById('kioskSite').value || null }) });
  if (!d) return;
  document.getElementById('kioskName').value = '';
  toast(`أُضيف الجهاز — رمز الإقران: ${d.pair_code}`);
  loadKiosks();
}
async function kioskBulk(action) {
  const ids = Array.from(document.querySelectorAll('#kioskTable .row-check:checked')).map(c => +c.dataset.id);
  if (!ids.length) { toast('حدّد جهازاً واحداً على الأقل', true); return; }
  const labels = { pair: 'إنشاء رمز إقران جديد', disable: 'تعطيل', enable: 'تفعيل', unpair: 'إلغاء الإقران (يجب إقران الجهاز من جديد)', delete: 'حذف' };
  if (!confirm(`${labels[action]} — ${ids.length} جهاز؟`)) return;
  const d = await api('/api/kiosks/bulk', { method: 'POST', body: JSON.stringify({ ids, action }) });
  if (d) { toast('تم'); loadKiosks(); }
}
