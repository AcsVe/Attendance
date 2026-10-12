/* =====================================================================
   تطبيق الموظفين على الهاتف — صفحات الإدارة (الحسابات، مواقع العمل، الحركات والمتابعة)
   يعتمد على: api() و toast() و escapeHtml() و toggleSelectAll() من app.js، و Leaflet للخرائط
   ===================================================================== */
Object.assign(PAGE_TITLES, {
  'mobile-accounts': 'حسابات تطبيق الهاتف', 'mobile-sites': 'مواقع العمل (Geofence)', 'mobile-moves': 'حركات الهاتف والمتابعة',
});
window.EXTRA_LOADERS = Object.assign(window.EXTRA_LOADERS || {}, {
  'mobile-accounts': () => { loadAccounts(); loadMobileSettings(); },
  'mobile-sites': loadSites,
  'mobile-moves': () => { loadLive(); loadMoves(); },
});

const OSM = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
const OSM_ATTR = '&copy; OpenStreetMap';
const mEsc = s => escapeHtml(s == null ? '' : String(s));

/* ================= الحسابات ================= */
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
      <td><b>${mEsc(r.name)}</b>${r.device_uid ? `<br><small style="color:var(--muted)">بصمة ${mEsc(r.device_uid)}</small>` : ''}</td>
      <td>${mEsc(r.dept || '—')}</td>
      <td dir="ltr" style="text-align:right">${r.has_account ? mEsc(r.username) : '<span style="color:var(--muted)">—</span>'}</td>
      <td>${r.device_label ? `${mEsc(r.device_label)}<br><small style="color:var(--muted)">${mEsc(r.bound_at || '')}</small>` : (r.has_account ? '<span class="badge badge-late">لم يُربط بعد</span>' : '—')}</td>
      <td><small>${mEsc(r.last_move || '—')}</small></td>
      <td>${!r.has_account ? '<span class="badge badge-none">بدون حساب</span>' : (r.acc_active ? '<span class="badge badge-ontime">مفعّل</span>' : '<span class="badge badge-absent">موقوف</span>')}${r.anywhere ? ' <span class="badge badge-holiday" title="يسجّل من أي مكان">أي مكان</span>' : ''}</td>
      <td><button class="btn btn-outline btn-sm" onclick="maEdit(${r.id})" title="تعديل اسم المستخدم/كلمة المرور"><i class="fas fa-pen"></i></button></td></tr>`).join('')
    || '<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:16px">لا يوجد موظفون مطابقون</td></tr>';
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
    const csv = '﻿' + rows.map(r => r.map(v => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\r\n');
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
  if (!PERMS.can_edit_org_settings) document.querySelectorAll('#mobileSettingsCard input, #mobileSettingsCard button').forEach(e => { e.disabled = true; });
}

async function msSave() {
  await api('/api/mobile/settings', { method: 'POST', body: JSON.stringify({
    mobile_enabled: document.getElementById('msEnabled').checked, mobile_bind_device: document.getElementById('msBind').checked,
    mobile_require_geofence: document.getElementById('msGeo').checked, mobile_leave_deduct: document.getElementById('msLeave').checked,
    mobile_max_accuracy: document.getElementById('msAcc').value,
    mobile_require_app: document.getElementById('msApp').checked, mobile_suspicious: document.getElementById('msSusp').value,
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
      <td style="white-space:nowrap"><button class="btn btn-outline btn-sm" onclick="siteEdit(${s.id})"><i class="fas fa-pen"></i></button>
        <a class="btn btn-outline btn-sm" target="_blank" href="https://www.google.com/maps?q=${s.lat},${s.lng}"><i class="fas fa-map-location-dot"></i></a></td></tr>`).join('')
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
  document.getElementById('liveTable').innerHTML = d.rows.map(r => `<tr><td><b>${mEsc(r.name)}</b></td><td>${mEsc(r.dept || '')}</td>
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
    <td>${mEsc(r.date)}</td><td dir="ltr" style="text-align:right">${mEsc(r.time.slice(0, 5))}</td><td><b>${mEsc(r.name)}</b></td><td>${mEsc(r.dept || '')}</td>
    <td>${mEsc(r.kind_label)}</td><td>${mEsc(r.site_name || '—')}${r.distance_m != null ? ` <small style="color:var(--muted)">(${Math.round(r.distance_m)} م)</small>` : ''}</td>
    <td>${r.accuracy != null ? Math.round(r.accuracy) + ' م' : '—'}<br><small style="color:var(--muted)">${r.source === 'app' ? '<i class="fas fa-mobile-screen"></i> التطبيق' : '<i class="fas fa-globe"></i> المتصفح'}</small></td>
    <td>${r.status === 'accepted' ? '<span class="badge badge-ontime">مقبولة</span>' : `<span class="badge badge-absent" title="${mEsc(r.reason || '')}">مرفوضة</span><br><small style="color:#842029">${mEsc(r.reason || '')}</small>`}${r.flags ? `<br><small style="color:#b45309">⚠ ${mEsc(r.flags)}</small>` : ''}</td>
    <td>${r.lat != null ? `<a target="_blank" href="https://www.google.com/maps?q=${r.lat},${r.lng}"><i class="fas fa-map-location-dot"></i></a>` : ''}</td></tr>`).join('')
    || '<tr><td colspan="9" style="text-align:center;color:var(--muted);padding:16px">لا توجد حركات في هذه الفترة</td></tr>';
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
