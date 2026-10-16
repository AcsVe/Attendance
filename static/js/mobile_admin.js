/* =====================================================================
   تطبيق الموظفين على الهاتف — صفحات الإدارة (الحسابات، مواقع العمل، الحركات والمتابعة)
   يعتمد على: api() و toast() و escapeHtml() و toggleSelectAll() من app.js، و Leaflet للخرائط
   ===================================================================== */
Object.assign(PAGE_TITLES, {
  leaves: 'الخروج المؤقت والمغادرات',
  presence: 'التحقق من التواجد أثناء الدوام', shares: 'المواقع المشاركة من الموظفين',
  'mobile-accounts': 'حسابات تطبيق الهاتف', 'mobile-sites': 'مواقع العمل (النطاق الجغرافي)', 'mobile-moves': 'المتابعة المباشرة وحركات الهاتف',
});
window.EXTRA_LOADERS = Object.assign(window.EXTRA_LOADERS || {}, {
  'mobile-accounts': () => { loadAccounts(); loadMobileSettings(); },
  'mobile-sites': () => { loadSites(); loadKiosks(); },
  'mobile-moves': () => { loadLive(); loadMoves(); },
  presence: prLoad,
  shares: () => { trLoad(); shLoad(); },
  leaves: () => { lvSettings(); lvLoad(); lvReport(); },
});

const OSM = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
const OSM_ATTR = '&copy; OpenStreetMap';
const mEsc = s => escapeHtml(s == null ? '' : String(s));

/* ================= الحسابات ================= */
const MODE_LABEL = { both: 'البصمة + الهاتف + QR', device: 'جهاز البصمة فقط', mobile: 'الهاتف فقط', qr: 'رمز QR فقط', device_qr: 'البصمة + QR', mobile_qr: 'الهاتف + QR' };
const MODE_PHONE = { both: 1, mobile: 1, mobile_qr: 1 };   // الطرق التي تشمل التسجيل من الهاتف بالموقع

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
  if (action.startsWith('emp:') || action.startsWith('mode:') || action.startsWith('presence:')) {
    const [kind, value] = action.split(':');
    const label = document.querySelector(`#maMore option[value="${action}"]`).textContent;
    if (!confirm(`${label}؟\n(${ids.length} موظف)`)) return;
    const d = await api('/api/mobile/employees/bulk', { method: 'POST', body: JSON.stringify({ ids, action: kind === 'emp' ? value : kind, value }) });
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
  document.getElementById('msApp').value = ['0', 'android', '1'].includes(s.mobile_require_app) ? s.mobile_require_app : '0';
  document.getElementById('msSusp').value = s.mobile_suspicious || 'flag';
  document.getElementById('msBio').value = s.mobile_biometric || 'off';
  if (!PERMS.can_edit_org_settings) document.querySelectorAll('#mobileSettingsCard input, #mobileSettingsCard button').forEach(e => { e.disabled = true; });
}

async function msSave() {
  await api('/api/mobile/settings', { method: 'POST', body: JSON.stringify({
    mobile_enabled: document.getElementById('msEnabled').checked, mobile_bind_device: document.getElementById('msBind').checked,
    mobile_require_geofence: document.getElementById('msGeo').checked, mobile_leave_deduct: document.getElementById('msLeave').checked,
    mobile_max_accuracy: document.getElementById('msAcc').value,
    mobile_require_app: document.getElementById('msApp').value, mobile_suspicious: document.getElementById('msSusp').value,
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
  // نجمع القراءات 15 ثانية ونأخذ الأدق — قراءة واحدة (خاصة من الكمبيوتر) قد تبعد مئات الأمتار
  toast('جارٍ تحديد موقعك بدقة… (15 ثانية)');
  let best = null;
  const id = navigator.geolocation.watchPosition(p => {
    if (!best || p.coords.accuracy < best.coords.accuracy) best = p;
  }, () => {}, { enableHighAccuracy: true, maximumAge: 0, timeout: 15000 });
  setTimeout(() => {
    navigator.geolocation.clearWatch(id);
    if (!best) { toast('تعذّر تحديد الموقع — اسمح للمتصفح باستخدامه', true); return; }
    const acc = Math.round(best.coords.accuracy);
    document.getElementById('siteLat').value = best.coords.latitude.toFixed(6);
    document.getElementById('siteLng').value = best.coords.longitude.toFixed(6);
    siteDraw();
    if (siteMap) siteMap.setView([best.coords.latitude, best.coords.longitude], 18);
    if (acc > 30) alert(`دقة الموقع ${acc} م — غير كافية لتحديد موقع العمل.\n\nالكمبيوتر يقدّر موقعه من الشبكة وقد يبعد مئات الأمتار. الأفضل:\n• انقر على مكان المبنى مباشرة في الخريطة، أو\n• افتح هذه الصفحة من الهاتف وأنت داخل المبنى (GPS مفعّل) ثم اضغط «موقعي الحالي».`);
    else toast(`تم — دقة ${acc} م`);
  }, 15000);
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
  toast('حُفظ الموقع — يُطبَّق فوراً على حالة الموظفين، ويتحدّث في هواتفهم خلال دقيقة' + (d.recomputed ? ` (أُعيد حساب ${d.recomputed} قراءة)` : ''));
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
        <option value="both">الكل: جهاز البصمة + الهاتف + رمز QR (الأبكر حضوراً والأخير انصرافاً)</option>
        <option value="device">جهاز البصمة فقط</option>
        <option value="mobile">الهاتف فقط (بالموقع الجغرافي)</option>
        <option value="qr">رمز QR على جهاز المدخل فقط</option>
        <option value="device_qr">جهاز البصمة + رمز QR</option>
        <option value="mobile_qr">الهاتف + رمز QR</option></select></div>
      <div class="form-group"><label>الحالة</label><select id="ecActive" class="search-input" ${can}><option value="1">فعّال</option><option value="0">معلّق (لا يدخل التطبيق ولا يظهر في المتابعة)</option></select></div>
      <div class="form-group"><label>ملاحظات</label><input type="text" id="ecNotes" value="${mEsc(e.notes || '')}" ${can}></div>
      <div class="form-group"><label>التحقق من التواجد أثناء الدوام</label>
        <label style="display:flex;gap:8px;align-items:center;font-weight:600"><input type="checkbox" id="ecPresence" ${e.presence_monitor ? 'checked' : ''} ${can}> مشمول بالاسم</label>
        <small style="color:var(--muted)">${d.presence && d.presence.monitored ? '✓ مشمول حالياً' : (d.presence && !d.presence.enabled ? 'التحقق متوقف عموماً' : 'غير مشمول حالياً')}${d.presence && d.presence.scope === 'all' ? ' (الإعداد: كل الموظفين)' : ''}</small></div>
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
    <p style="font-size:.85rem;color:var(--muted)">مصادر البصمات هذا الشهر: جهاز البصمة ${d.sources.device || 0} يوم · الهاتف ${d.sources.mobile || 0} يوم · رمز QR ${d.sources.kiosk || 0} يوم · طريقة التوثيق: <b>${MODE_LABEL[e.attendance_mode || 'both']}</b></p>
    <div class="table-wrap" style="max-height:260px;overflow:auto"><table><thead><tr><th>التاريخ</th><th>حضور</th><th>انصراف</th><th>الحالة</th><th>تأخير</th><th>ساعات</th></tr></thead><tbody>
      ${d.days.map(x => `<tr><td>${mEsc(x.date)}</td><td dir="ltr">${mEsc(x.time_in || '—')}</td><td dir="ltr">${mEsc(x.time_out || '—')}</td><td>${mEsc(x.status || '')}</td><td>${x.late_minutes || 0}</td><td>${x.working_hours || 0}</td></tr>`).join('') || '<tr><td colspan="6" style="color:var(--muted)">لا توجد بيانات محلّلة لهذا الشهر</td></tr>'}
    </tbody></table></div>
    ${d.presence && d.presence.events && d.presence.events.length ? `<h4 style="margin:12px 0 6px;color:var(--primary-dark)">تنبيهات التواجد أثناء الدوام</h4>
    <div class="table-wrap" style="max-height:220px;overflow:auto"><table><thead><tr><th>التاريخ</th><th>التنبيه</th><th>من</th><th>إلى</th><th>المدة</th></tr></thead><tbody>
      ${d.presence.events.map(v => `<tr><td>${mEsc(v.date)}</td><td>${mEsc(v.kind_label)}</td><td dir="ltr">${mEsc((v.start_ts || '').slice(11, 16))}</td><td dir="ltr">${mEsc((v.end_ts || '').slice(11, 16))}</td><td>${v.minutes ? v.minutes + ' د' : '—'}</td></tr>`).join('')}
    </tbody></table></div>` : ''}
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
    phone: ec$('ecPhone').value, email: ec$('ecEmail').value, notes: ec$('ecNotes').value, attendance_mode: ec$('ecMode').value, active: ec$('ecActive').value === '1',
    presence_monitor: ec$('ecPresence').checked };
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
  const d = await api('/api/mobile/employees/bulk', { method: 'POST', body: JSON.stringify({ ids, action: kind === 'emp' ? value : kind, value }) });
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


/* ================= التحقق من التواجد أثناء الدوام ================= */
let prCfg = {}, prEmps = [], prDeptSet = new Set(), prEvRows = [], prKind = '';
const PR_KIND_COLOR = { outside: '#c0392b', no_location: '#b45309', no_signal: '#6b7c7e', missed_check: '#8e44ad', failed_check: '#c0392b' };

async function prLoad() {
  const [st, acc] = await Promise.all([api('/api/mobile/settings'), api('/api/mobile/accounts')]);
  if (!st || !acc) return;
  prCfg = st.settings || {};
  prEmps = acc.rows.filter(r => r.has_account);
  try { prDeptSet = new Set(JSON.parse(prCfg.presence_depts_json || '[]')); } catch (e) { prDeptSet = new Set(); }
  document.getElementById('prOn').checked = prCfg.presence_enabled === '1';
  document.getElementById('prInterval').value = prCfg.presence_interval_min || 10;
  document.getElementById('prGrace').value = prCfg.presence_grace_min || 20;
  document.getElementById('prChecks').value = prCfg.presence_checks_per_day || '0';
  document.getElementById('prWindow').value = prCfg.presence_check_window_min || 10;
  document.querySelectorAll('input[name=prScope]').forEach(r => { r.checked = r.value === (prCfg.presence_scope || 'selected'); });
  const f = document.getElementById('prFrom');
  if (!f.value) { const t = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10); f.value = t; document.getElementById('prTo').value = t; }
  prScopeUi(); prDeptsRender(); prRender(); prLive(); prEvents();
}

function prScope() { const r = document.querySelector('input[name=prScope]:checked'); return r ? r.value : 'selected'; }
function prScopeUi() { document.getElementById('prSelBox').style.display = prScope() === 'all' ? 'none' : ''; prRender(); prStateText(); }

function prCovered(e) {
  if (!document.getElementById('prOn').checked) return [false, 'التحقق متوقف'];
  if (!MODE_PHONE[e.attendance_mode || 'both']) return [false, 'طريقة توثيقه لا تشمل الهاتف: ' + (MODE_LABEL[e.attendance_mode] || '')];
  if (!e.active || !e.acc_active) return [false, 'الحساب موقوف'];
  if (prScope() === 'all') return [true, 'كل الموظفين'];
  if (e.presence_monitor) return [true, 'محدد بالاسم'];
  if (prDeptSet.has(e.dept || '')) return [true, 'ضمن قسم محدد'];
  return [false, ''];
}

function prStateText() {
  const n = prEmps.filter(e => prCovered(e)[0]).length;
  document.getElementById('prState').textContent = document.getElementById('prOn').checked
    ? `مفعّل — يشمل ${n} من ${prEmps.length} موظفاً لديهم حساب تطبيق` : 'متوقف — لا يُتحقَّق من أي موظف';
}

function prDeptsRender() {
  const counts = {};
  prEmps.forEach(e => { const d = e.dept || ''; counts[d] = (counts[d] || 0) + 1; });
  document.getElementById('prDepts').innerHTML = Object.keys(counts).sort().map(d => `<label style="display:flex;gap:6px;align-items:center;border:1px solid var(--border);border-radius:20px;padding:5px 12px;font-weight:600;font-size:.85rem">
    <input type="checkbox" class="pr-dept" value="${mEsc(d)}" ${prDeptSet.has(d) ? 'checked' : ''} onchange="prDeptToggle(this)"> ${mEsc(d || 'بدون قسم')} <b style="color:var(--muted)">${counts[d]}</b></label>`).join('')
    || '<span style="color:var(--muted)">لا توجد أقسام</span>';
}
function prDeptToggle(cb) { cb.checked ? prDeptSet.add(cb.value) : prDeptSet.delete(cb.value); prRender(); prStateText(); }
function prDeptAll(on) { document.querySelectorAll('.pr-dept').forEach(c => { c.checked = on; on ? prDeptSet.add(c.value) : prDeptSet.delete(c.value); }); prRender(); prStateText(); }

function prRender() {
  const q = (document.getElementById('prSearch').value || '').trim().toLowerCase(), flt = document.getElementById('prFilter').value;
  const rows = prEmps.filter(e => {
    const [on] = prCovered(e);
    if (flt === 'on' && !on) return false;
    if (flt === 'off' && on) return false;
    return !q || (e.name + ' ' + (e.dept || '')).toLowerCase().includes(q);
  });
  document.getElementById('prTable').innerHTML = rows.map(e => { const [on, why] = prCovered(e); return `<tr>
    <td><input type="checkbox" class="row-check" data-id="${e.id}" aria-label="تحديد"></td>
    <td><a href="#" onclick="openEmployeeCard(${e.id});return false"><b>${mEsc(e.name)}</b></a></td><td>${mEsc(e.dept || '—')}</td>
    <td>${on ? '<span class="badge badge-ontime">نعم</span>' : '<span class="badge badge-none">لا</span>'}</td><td><small>${mEsc(why)}</small></td></tr>`; }).join('')
    || '<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:14px">لا يوجد موظفون مطابقون</td></tr>';
  document.getElementById('prAll').checked = false;
  document.getElementById('prSelCount').textContent = `${prEmps.filter(e => e.presence_monitor).length} محدد بالاسم · المعروض ${rows.length} من ${prEmps.length}`;
}

async function prBulk(v) {
  const ids = Array.from(document.querySelectorAll('#prTable .row-check:checked')).map(c => +c.dataset.id);
  if (!ids.length) { toast('حدّد موظفاً واحداً على الأقل', true); return; }
  const d = await api('/api/mobile/employees/bulk', { method: 'POST', body: JSON.stringify({ ids, action: 'presence', value: v }) });
  if (d) { toast(`تم: ${d.count} موظف`); prLoad(); }
}

async function prSave(quiet) {
  const body = {
    presence_enabled: document.getElementById('prOn').checked, presence_scope: prScope(),
    presence_interval_min: document.getElementById('prInterval').value, presence_grace_min: document.getElementById('prGrace').value,
    presence_checks_per_day: document.getElementById('prChecks').value, presence_check_window_min: document.getElementById('prWindow').value,
    presence_depts_json: Array.from(prDeptSet),
  };
  if (body.presence_enabled && !quiet && !confirm('تفعيل التحقق من التواجد أثناء الدوام للموظفين المشمولين؟\nتأكّد من إعلامهم بالسياسة.')) return;
  const d = await api('/api/mobile/settings', { method: 'POST', body: JSON.stringify(body) });
  if (d) { toast(body.presence_enabled ? 'حُفظ — التحقق مفعّل' : 'حُفظ — التحقق متوقف'); prStateText(); prRender(); }
}

async function prLive() {
  const d = await api('/api/mobile/presence/live');
  if (!d) return;
  const byId = Object.fromEntries(prEmps.map(e => [e.id, e]));
  const ids = Object.keys(d.rows).map(Number).filter(id => byId[id]);
  const label = r => {
    if (r.open && r.open.includes('outside')) return ['#c0392b', 'خارج النطاق الآن'];
    if (r.open && r.open.includes('no_location')) return ['#b45309', 'الموقع مطفأ/وهمي'];
    if (r.stale || (r.open && r.open.includes('no_signal'))) return ['#6b7c7e', 'انقطعت الإشارة'];
    if (r.status === 'exempt') return ['#1B6E8C', 'مستثنى (خروج مؤقت/استثناء)'];
    if (r.inside === 1) return ['#1e8e5a', 'داخل النطاق'];
    if (r.inside === 0) return ['#e67e22', 'خارج النطاق (ضمن المهلة)'];
    return ['#9aa', '—'];
  };
  document.getElementById('prLiveTable').innerHTML = ids.map(id => { const r = d.rows[id], e = byId[id], [c, t] = label(r); return `<tr>
    <td><a href="#" onclick="openEmployeeCard(${id});return false"><b>${mEsc(e.name)}</b></a></td><td>${mEsc(e.dept || '')}</td>
    <td><span class="pr-dot" style="background:${c}"></span>${t}${r.distance != null && r.inside === 0 ? ` <small>(${Math.round(r.distance)} م)</small>` : ''}</td>
    <td dir="ltr" style="text-align:right">${mEsc(r.last_ping || '—')}</td><td>${r.events || 0}</td></tr>`; }).join('')
    || `<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:14px">${d.enabled ? 'لا توجد قراءات اليوم بعد' : 'التحقق متوقف'}</td></tr>`;
}

function prParams() {
  const p = new URLSearchParams({ from: document.getElementById('prFrom').value, to: document.getElementById('prTo').value });
  if (prKind) p.set('kind', prKind);
  return p;
}
async function prEvents() {
  const d = await api('/api/mobile/presence/events?' + prParams());
  if (!d) return;
  prEvRows = d.rows;
  const chip = (k, l, n) => `<button class="${prKind === k ? 'on' : ''}" onclick="prKind='${k}';prEvents()">${l} <b>${n}</b></button>`;
  document.getElementById('prChips').innerHTML = chip('', 'الكل', d.total) + Object.entries(d.kinds).map(([k, l]) => chip(k, l, d.counts[k] || 0)).join('');
  prEvRender();
}
function prEvRender() {
  const q = (document.getElementById('prEvSearch').value || '').trim().toLowerCase();
  const rows = prEvRows.filter(r => !q || [r.name, r.dept, r.kind_label, r.details].some(v => (v || '').toLowerCase().includes(q)));
  document.getElementById('prEvTable').innerHTML = rows.map(r => `<tr>
    <td><input type="checkbox" class="row-check" data-id="${r.id}" onchange="prEvCount()" aria-label="تحديد"></td>
    <td>${mEsc(r.date)}</td><td><b>${mEsc(r.name || '')}</b></td><td>${mEsc(r.dept || '')}</td>
    <td><span class="pr-dot" style="background:${PR_KIND_COLOR[r.kind] || '#999'}"></span>${mEsc(r.kind_label)}${r.open ? ' <span class="badge badge-late">جارٍ</span>' : ''}</td>
    <td dir="ltr" style="text-align:right">${mEsc((r.start_ts || '').slice(11, 16))}</td><td dir="ltr" style="text-align:right">${mEsc((r.end_ts || '').slice(11, 16))}</td>
    <td>${r.minutes ? r.minutes + ' د' : '—'}</td><td><small>${mEsc(r.details || '')}</small></td></tr>`).join('')
    || '<tr><td colspan="9" style="text-align:center;color:var(--muted);padding:14px">لا توجد تنبيهات في هذه الفترة</td></tr>';
  prEvCount();
}
function prEvCount() {
  const n = document.querySelectorAll('#prEvTable .row-check:checked').length, all = document.querySelectorAll('#prEvTable .row-check').length;
  document.getElementById('prEvSel').textContent = n ? `(${n} من ${all})` : '';
}
function prEvExport() { const p = prParams(); p.set('format', 'csv'); window.location.href = '/api/mobile/presence/events?' + p; }
async function prEvDelete() {
  const ids = Array.from(document.querySelectorAll('#prEvTable .row-check:checked')).filter(c => c.closest('tr').style.display !== 'none').map(c => +c.dataset.id);
  if (!ids.length) { toast('حدّد تنبيهاً واحداً على الأقل', true); return; }
  if (!confirm(`حذف ${ids.length} تنبيه؟`)) return;
  const d = await api('/api/mobile/presence/events/delete', { method: 'POST', body: JSON.stringify({ ids }) });
  if (d) { toast(`حُذف ${d.count}`); prEvents(); }
}


/* ================= الخروج المؤقت ================= */
let lvRows = [], lvStatus = '', lvStatuses = {};
const LV_COLOR = { pending: '#b45309', approved: '#1B6E8C', rejected: '#842029', cancelled: '#6b7c7e', expired: '#6b7c7e', active: '#1B6E8C',
  overdue: '#c0392b', returned: '#1e8e5a', returned_late: '#e67e22', not_returned: '#c0392b' };
const lvToday = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);

async function lvSettings() {
  const d = await api('/api/mobile/settings');
  if (!d) return;
  const s = d.settings || {};
  document.getElementById('lvApproval').checked = s.leave_approval === '1';
  document.getElementById('lvEarly').checked = s.leave_unreturned_early !== '0';
  document.getElementById('lvMax').value = s.leave_max_minutes || 60;
  document.getElementById('lvGrace').value = s.leave_grace_min || 10;
}
async function lvSave() {
  const d = await api('/api/mobile/settings', { method: 'POST', body: JSON.stringify({
    leave_approval: document.getElementById('lvApproval').checked, leave_unreturned_early: document.getElementById('lvEarly').checked,
    leave_max_minutes: document.getElementById('lvMax').value, leave_grace_min: document.getElementById('lvGrace').value }) });
  if (d) toast('حُفظت إعدادات الخروج المؤقت');
}
function lvParams() {
  const p = new URLSearchParams({ from: document.getElementById('lvFrom').value, to: document.getElementById('lvTo').value });
  if (lvStatus) p.set('status', lvStatus);
  return p;
}
async function lvLoad() {
  const f = document.getElementById('lvFrom');
  if (!f.value) { f.value = lvToday(); document.getElementById('lvTo').value = lvToday(); }
  const d = await api('/api/leaves?' + lvParams());
  if (!d) return;
  lvRows = d.rows; lvStatuses = d.statuses;
  const chip = (k, l, n) => `<button class="${lvStatus === k ? 'on' : ''}" onclick="lvStatus='${k}';lvLoad()">${l} <b>${n}</b></button>`;
  document.getElementById('lvChips').innerHTML = chip('', 'الكل', d.total) + Object.entries(d.statuses).map(([k, l]) => chip(k, l, d.counts[k] || 0)).join('');
  lvRender();
  lvPendRender(d.pending);
}
function lvRender() {
  const q = (document.getElementById('lvSearch').value || '').trim().toLowerCase();
  const rows = lvRows.filter(r => !q || [r.name, r.dept, r.reason, r.status_label].some(v => (v || '').toLowerCase().includes(q)));
  document.getElementById('lvTable').innerHTML = rows.map(r => `<tr>
    <td><input type="checkbox" class="row-check" data-id="${r.id}" onchange="lvCount()" aria-label="تحديد"></td>
    <td>${mEsc(r.date)}</td><td><a href="#" onclick="openEmployeeCard(${r.employee_id});return false"><b>${mEsc(r.name || '')}</b></a></td><td>${mEsc(r.dept || '')}</td>
    <td dir="ltr" style="text-align:right">${mEsc(r.from_time)}</td><td dir="ltr" style="text-align:right">${mEsc(r.to_time)}</td>
    <td dir="ltr" style="text-align:right">${mEsc(r.out_time || '—')}</td><td dir="ltr" style="text-align:right">${mEsc(r.back_time || '—')}</td>
    <td>${r.minutes != null ? r.minutes + ' د' : '—'}</td><td>${r.late_min ? '<b style="color:#c0392b">' + r.late_min + ' د</b>' : '—'}</td>
    <td><span class="pr-dot" style="background:${LV_COLOR[r.status] || '#999'}"></span>${mEsc(r.status_label)}${r.source === 'direct' ? ' <small style="color:var(--muted)">(مباشر)</small>' : ''}</td>
    <td><small>${mEsc(r.reason || '')}${r.decision_note ? ' — ' + mEsc(r.decision_note) : ''}</small></td></tr>`).join('')
    || '<tr><td colspan="12" style="text-align:center;color:var(--muted);padding:14px">لا توجد سجلات في هذه الفترة</td></tr>';
  lvCount();
}
function lvCount() {
  const n = document.querySelectorAll('#lvTable .row-check:checked').length, all = document.querySelectorAll('#lvTable .row-check').length;
  document.getElementById('lvSel').textContent = n ? `(${n} من ${all})` : '';
}
function lvPendRender(rows) {
  const card = document.getElementById('lvPendingCard');
  card.style.display = rows.length ? '' : 'none';
  document.getElementById('lvPendingN').textContent = rows.length;
  const dur = r => { const [a, b] = [r.from_time, r.to_time].map(x => +x.slice(0, 2) * 60 + +x.slice(3, 5)); return b - a; };
  document.getElementById('lvPendTable').innerHTML = rows.map(r => `<tr>
    <td><input type="checkbox" class="row-check" data-id="${r.id}" onchange="lvPendCount()" aria-label="تحديد"></td>
    <td><b>${mEsc(r.name || '')}</b></td><td>${mEsc(r.dept || '')}</td><td>${mEsc(r.date)}</td>
    <td dir="ltr" style="text-align:right">${mEsc(r.from_time)}</td><td dir="ltr" style="text-align:right">${mEsc(r.to_time)}</td><td>${dur(r)} د</td>
    <td>${mEsc(r.reason || '')}</td><td><small>${mEsc((r.requested_at || '').slice(0, 16))}</small></td></tr>`).join('');
  lvPendCount();
  lvBannerUpdate(rows.length);
}
function lvPendCount() {
  const n = document.querySelectorAll('#lvPendTable .row-check:checked').length, all = document.querySelectorAll('#lvPendTable .row-check').length;
  document.getElementById('lvPendSel').textContent = `المحدد ${n} من ${all}`;
}
async function lvDecide(action) {
  const ids = Array.from(document.querySelectorAll('#lvPendTable .row-check:checked')).map(c => +c.dataset.id);
  if (!ids.length) { toast('حدّد طلباً واحداً على الأقل', true); return; }
  if (action === 'reject' && !confirm(`رفض ${ids.length} طلب؟`)) return;
  const d = await api('/api/leaves/decide', { method: 'POST', body: JSON.stringify({ ids, action, note: document.getElementById('lvNote').value }) });
  if (d) { toast(action === 'approve' ? `تمت الموافقة على ${d.count} طلب — أُبلغ الموظفون` : `رُفض ${d.count} طلب — أُبلغ الموظفون`); document.getElementById('lvNote').value = ''; lvLoad(); }
}
async function lvDelete() {
  const ids = Array.from(document.querySelectorAll('#lvTable .row-check:checked')).filter(c => c.closest('tr').style.display !== 'none').map(c => +c.dataset.id);
  if (!ids.length) { toast('حدّد سجلاً واحداً على الأقل', true); return; }
  if (!confirm(`حذف ${ids.length} سجل؟`)) return;
  const d = await api('/api/leaves/delete', { method: 'POST', body: JSON.stringify({ ids }) });
  if (d) { toast(`حُذف ${d.count}`); lvLoad(); }
}
function lvExport() { const p = lvParams(); p.set('format', 'csv'); window.location.href = '/api/leaves?' + p; }
async function lvReport() {
  const m = document.getElementById('lvMonth');
  if (!m.value) m.value = lvToday().slice(0, 7);
  const d = await api('/api/leaves/report?month=' + m.value);
  if (!d) return;
  const t = d.totals;
  document.getElementById('lvTotals').textContent = `${d.rows.length} موظف · ${t.times} مرة خروج · ${t.minutes} دقيقة · تأخر ${t.late} · لم يعد ${t.not_returned} · طلبات ${t.requested} (مرفوضة ${t.rejected})`;
  document.getElementById('lvRepTable').innerHTML = d.rows.map(a => `<tr>
    <td><a href="#" onclick="openEmployeeCard(${a.employee_id});return false"><b>${mEsc(a.name || '')}</b></a></td><td>${mEsc(a.dept || '')}</td>
    <td>${a.times}</td><td>${a.minutes}</td><td>${a.late ? '<b style="color:#e67e22">' + a.late + '</b>' : 0}</td><td>${a.late_minutes}</td>
    <td>${a.not_returned ? '<b style="color:#c0392b">' + a.not_returned + '</b>' : 0}</td><td>${a.requested}</td><td>${a.rejected}</td></tr>`).join('')
    || '<tr><td colspan="9" style="text-align:center;color:var(--muted);padding:14px">لا توجد مغادرات في هذا الشهر</td></tr>';
}
function lvReportExport() { window.location.href = '/api/leaves/report?format=csv&month=' + document.getElementById('lvMonth').value; }
function lvBannerUpdate(n) {
  const b = document.getElementById('lvBanner'), nb = document.getElementById('lvNavBadge');
  b.classList.toggle('hide', !n); b.style.display = n ? 'flex' : 'none';
  document.getElementById('lvBannerText').textContent = `طلبات إذن خروج بانتظار الموافقة: ${n}`;
  nb.classList.toggle('hide', !n); nb.textContent = n;
}
async function lvPoll() {
  if (typeof PERMS !== 'undefined' && !PERMS.can_manage_employees && CURRENT_ROLE !== 'admin') return;
  try {
    const r = await fetch('/api/leaves?status=pending', { credentials: 'same-origin' });
    const d = await r.json();
    if (d && d.ok) lvBannerUpdate(d.pending.length);
  } catch (e) {}
}
document.addEventListener('DOMContentLoaded', () => { lvPoll(); setInterval(lvPoll, 120000); });


/* ===== شريط تنبيهات التواجد: من هو خارج موقع العمل أو انقطع هاتفه الآن (يتحدّث كل دقيقة) ===== */
const PR_KIND_TEXT = { outside: 'خارج الموقع', no_location: 'الموقع متوقف', no_signal: 'انقطاع الهاتف', missed_check: 'لم يردّ على الفحص', failed_check: 'فحص فاشل', leave_overdue: 'تجاوز وقت العودة' };
async function prAlertPoll() {
  if (typeof CURRENT_ROLE !== 'undefined' && CURRENT_ROLE !== 'admin') return;
  try {
    const r = await fetch('/api/mobile/presence/alerts', { credentials: 'same-origin' });
    if (!r.ok) return;
    const d = await r.json();
    if (!d || !d.ok) return;
    const b = document.getElementById('prBanner'), nb = document.getElementById('prNavBadge');
    if (!b) return;
    b.classList.toggle('hide', !d.count); b.style.display = d.count ? 'flex' : 'none';
    const parts = Object.entries(d.by_kind).map(([k, n]) => `${PR_KIND_TEXT[k] || k}: ${n}`).join(' · ');
    document.getElementById('prBannerText').textContent = `تنبيهات التواجد الآن — ${d.count} موظف (${parts})`;
    if (nb) { nb.classList.toggle('hide', !d.count); nb.textContent = d.count; }
  } catch (e) {}
}
document.addEventListener('DOMContentLoaded', () => { prAlertPoll(); setInterval(prAlertPoll, 60000); });


/* ================= المواقع المشاركة من الموظفين ================= */
function connLabel(age, live) {
  if (age == null) return '<span style="color:var(--muted)">—</span>';
  if (live && age <= 120) return '<span style="color:#0a6640;font-weight:700">🟢 متصل الآن</span>';
  const t = age < 3600 ? Math.round(age / 60) + ' د' : age < 86400 ? Math.round(age / 3600) + ' س' : Math.round(age / 86400) + ' يوم';
  return `<span style="color:var(--muted)">⚪ آخر اتصال قبل ${t}</span>`;
}
let shRows = [], shMap = null, shLayer = null, shFilter = 'all', shTimer = null;
async function shLoad() {
  const d = await api('/api/shares?days=' + document.getElementById('shDays').value).catch(() => null);
  if (!d) return;
  shRows = d.rows;
  document.getElementById('shLiveCount').textContent = d.live;
  const nb = document.getElementById('shNavBadge'); if (nb) { nb.classList.toggle('hide', !d.live); nb.textContent = d.live; }
  shRender();
  clearInterval(shTimer);
  shTimer = setInterval(() => { if (typeof currentTab !== 'undefined' && currentTab === 'shares') shLoad(); else clearInterval(shTimer); }, 30000);
}
function shVisible() {
  const q = (document.getElementById('shSearch').value || '').trim().toLowerCase();
  return shRows.filter(r => (shFilter === 'all' || (shFilter === 'live' ? r.live_now : shFilter === 'flag' ? !!r.flags : r.kind === shFilter))
    && (!q || (r.name || '').toLowerCase().includes(q) || (r.dept || '').toLowerCase().includes(q)));
}
function shRender() {
  const cnt = { all: shRows.length, live: shRows.filter(r => r.live_now).length, once: shRows.filter(r => r.kind === 'once').length, liveAll: shRows.filter(r => r.kind === 'live').length };
  cnt.flag = shRows.filter(r => r.flags).length;
  document.getElementById('shChips').innerHTML = [['all', 'الكل', cnt.all], ['live', 'مباشر الآن', cnt.live], ['once', 'موقع حالي', cnt.once], ['flag', 'مشبوه', cnt.flag]]
    .map(([k, l, n]) => `<button class="${shFilter === k ? 'on' : ''}" onclick="shFilter='${k}';shRender()">${l} <b>${n}</b></button>`).join('');
  const rows = shVisible();
  document.getElementById('shTotal').textContent = rows.length;
  document.getElementById('shAll').checked = false;
  document.getElementById('shTable').innerHTML = rows.map(r => `<tr style="cursor:pointer" onclick="if(event.target.type!=='checkbox')shTrack(${r.id})">
    <td><input type="checkbox" class="sh-check" data-id="${r.id}" onchange="shSelCount()"></td>
    <td><b>${mEsc(r.name)}</b>${r.flags ? ` <span title="${mEsc(r.flags)}" style="color:#c0392b;font-weight:700">⚠ مشبوه</span><div style="font-size:.75rem;color:#c0392b">${mEsc(r.flags)}</div>` : ''}${r.source === 'admin' ? ' <small style="color:var(--primary)">(تتبع مستمر)</small>' : r.source === 'app' ? ' <small style="color:var(--muted)">(التطبيق)</small>' : r.source ? ' <small style="color:var(--muted)">(المتصفح)</small>' : ''}</td><td>${mEsc(r.dept || '—')}</td>
    <td>${r.kind === 'live' ? (r.live_now ? '<span style="color:#0a6640;font-weight:700">مباشر الآن</span>' : 'مباشر (انتهى)') : 'موقع حالي'}</td>
    <td dir="ltr">${mEsc((r.started_at || '').slice(5, 16))}</td><td dir="ltr">${r.kind === 'live' ? (r.stopped_at ? mEsc(r.stopped_at.slice(11, 16)) : (r.ends_at || '').startsWith('9999') ? '<span dir="rtl">بلا مدة</span>' : mEsc((r.ends_at || '').slice(11, 16))) : '—'}</td>
    <td><span dir="ltr">${mEsc((r.updated_at || '').slice(11, 19) || '—')}</span>${r.kind === 'live' ? '<br><small>' + connLabel(r.age_s, r.live_now) + '</small>' : ''}
      ${r.live_now ? `<br><button class="btn btn-primary btn-sm" style="margin-top:4px" onclick="event.stopPropagation();shFollow(${r.id})"><i class="fas fa-crosshairs" aria-hidden="true"></i> تتبع</button>` : ''}</td>
    <td>${r.site_dist == null ? '—' : (r.site_dist === 0 ? '<span style="color:#0a6640">داخل «' + mEsc(r.site_name) + '»</span>' : r.site_dist + ' م عن «' + mEsc(r.site_name) + '»')}</td>
    <td>${mEsc(r.note || '')}</td></tr>`).join('') || '<tr><td colspan="9" style="color:var(--muted)">لا توجد مواقع مشاركة</td></tr>';
  shSelCount();
  shDrawMarkers(rows);
}
function shEnsureMap() {
  if (shMap || typeof L === 'undefined') return;
  shMap = L.map('shMap').setView([31.95, 35.91], 12);
  L.tileLayer(OSM, { maxZoom: 19, attribution: OSM_ATTR }).addTo(shMap);
  shLayer = L.layerGroup().addTo(shMap);
}
function shDrawMarkers(rows) {
  if (shFollowId) return;   // أثناء «تتبع هذا الجهاز» لا نغيّر الخريطة
  setTimeout(() => {
    shEnsureMap(); if (!shMap) return;
    shMap.invalidateSize(); shLayer.clearLayers();
    const b = [];
    rows.filter(r => r.lat != null).forEach(r => {
      const live = r.live_now;
      L.circleMarker([r.lat, r.lng], { radius: live ? 9 : 6, color: r.flags ? '#c0392b' : (live ? '#0a6640' : '#1B6E8C'), fillOpacity: .8 })
        .bindPopup(`<b>${mEsc(r.name)}</b><br>${live ? 'مباشر الآن' : (r.kind === 'live' ? 'مباشر (انتهى)' : 'موقع حالي')}<br>${mEsc((r.updated_at || r.started_at || '').slice(0, 16))}${r.note ? '<br>' + mEsc(r.note) : ''}`)
        .addTo(shLayer);
      b.push([r.lat, r.lng]);
    });
    if (b.length) shMap.fitBounds(b, { padding: [30, 30], maxZoom: 16 });
  }, 50);
}
async function shTrack(id) {
  const d = await api('/api/shares/' + id + '/track').catch(() => null);
  if (!d || !shMap) return;
  shLayer.clearLayers();
  const pts = d.points.map(p => [p[0], p[1]]);
  if (pts.length > 1) L.polyline(pts, { color: '#d9822b', weight: 4 }).addTo(shLayer);
  d.points.forEach((p, i) => L.circleMarker([p[0], p[1]], { radius: i === d.points.length - 1 ? 9 : 4, color: i === d.points.length - 1 ? '#0a6640' : '#d9822b', fillOpacity: .9 })
    .bindPopup(`${mEsc(d.share.name)}<br>${p[2]}${p[3] ? ' · دقة ' + Math.round(p[3]) + ' م' : ''}`).addTo(shLayer));
  if (pts.length) shMap.fitBounds(pts, { padding: [30, 30], maxZoom: 17 });
  document.getElementById('shMap').scrollIntoView({ behavior: 'smooth', block: 'center' });
}
function shChecked() { return [...document.querySelectorAll('.sh-check:checked')].map(c => +c.dataset.id); }
function shSelCount() { document.getElementById('shSel').textContent = shChecked().length; }
function shCheckAll(on) { document.querySelectorAll('.sh-check').forEach(c => { c.checked = on; }); shSelCount(); }
async function shDelete() {
  const ids = shChecked();
  if (!ids.length) { toast('حدّد سجلاً واحداً على الأقل', true); return; }
  if (!confirm(`حذف ${ids.length} سجل مشاركة مع مساراتها؟`)) return;
  await api('/api/shares/delete', { method: 'POST', body: JSON.stringify({ ids }) });
  toast('تم الحذف'); shLoad();
}


/* ===== التتبع المستمر بلا مدة (الأجهزة المتنقلة) ===== */
let trRows = [], trFilter = 'all';
async function trLoad() {
  const d = await api('/api/shares/tracking').catch(() => null);
  if (!d) return;
  trRows = d.rows; trRender();
}
function trRender() {
  const q = (document.getElementById('trSearch').value || '').trim().toLowerCase();
  const on = trRows.filter(r => r.always_track).length;
  document.getElementById('trOnCount').textContent = on;
  document.getElementById('trChips').innerHTML = [['all', 'الكل', trRows.length], ['on', 'مفعّل', on], ['off', 'غير مفعّل', trRows.length - on]]
    .map(([k, l, n]) => `<button class="${trFilter === k ? 'on' : ''}" onclick="trFilter='${k}';trRender()">${l} <b>${n}</b></button>`).join('');
  const rows = trRows.filter(r => (trFilter === 'all' || (trFilter === 'on') === !!r.always_track)
    && (!q || (r.name || '').toLowerCase().includes(q) || (r.dept || '').toLowerCase().includes(q)));
  document.getElementById('trTotal').textContent = rows.length;
  document.getElementById('trAll').checked = false;
  document.getElementById('trTable').innerHTML = rows.map(r => `<tr>
    <td><input type="checkbox" class="tr-check" data-id="${r.id}" onchange="trSelCount()"></td>
    <td><b>${mEsc(r.name)}</b></td><td>${mEsc(r.dept || '—')}</td>
    <td>${r.always_track ? '<span style="color:#0a6640;font-weight:700">مفعّل</span>' : '<span style="color:var(--muted)">غير مفعّل</span>'}</td>
    <td>${r.track_interval == 15 ? 'كل 15 ثانية' : r.track_interval == 30 ? 'كل 30 ثانية' : 'كل دقيقة'}</td>
    <td>${r.always_track ? connLabel(r.age_s, !!r.last_update) : '—'}</td></tr>`).join('') || '<tr><td colspan="6" style="color:var(--muted)">لا يوجد موظفون بحسابات تطبيق</td></tr>';
  trSelCount();
}
function trChecked() { return [...document.querySelectorAll('.tr-check:checked')].map(c => +c.dataset.id); }
function trSelCount() { document.getElementById('trSel').textContent = trChecked().length; }
function trCheckAll(on) { document.querySelectorAll('.tr-check').forEach(c => { c.checked = on; }); trSelCount(); }
async function trSet(on) {
  const ids = trChecked();
  if (!ids.length) { toast('حدّد موظفاً أو جهازاً واحداً على الأقل', true); return; }
  if (on && !confirm(`تشغيل التتبع المستمر بلا مدة لـ ${ids.length}؟ سيُرسل موقعهم كل دقيقة ولن يستطيعوا إيقافه من الهاتف.`)) return;
  await api('/api/shares/tracking', { method: 'POST', body: JSON.stringify({ ids, on, interval: on ? +document.getElementById('trInterval').value : 0 }) });
  toast(on ? 'تم تشغيل التتبع المستمر' : 'تم إيقاف التتبع المستمر'); trLoad(); shLoad();
}
async function shStop() {
  const ids = shChecked();
  if (!ids.length) { toast('حدّد سجلاً واحداً على الأقل', true); return; }
  if (!confirm(`إيقاف ${ids.length} مشاركة جارية؟`)) return;
  const d = await api('/api/shares/stop', { method: 'POST', body: JSON.stringify({ ids }) });
  toast(`أُوقفت ${d.stopped} مشاركة`); trLoad(); shLoad();
}


/* ===== وضع «تتبع هذا الجهاز»: الخريطة تتحرك معه وتتحدّث كل 10 ثوانٍ ===== */
let shFollowId = null, shFollowTimer = null, shFollowLayer = null;
async function shFollow(id) {
  shFollowStop(true);
  shFollowId = id;
  shEnsureMap(); if (!shMap) return;
  shLayer.clearLayers();
  shFollowLayer = L.layerGroup().addTo(shMap);
  document.getElementById('shFollowBar').classList.remove('hide');
  document.getElementById('shFollowBar').style.display = 'flex';
  document.getElementById('shMap').scrollIntoView({ behavior: 'smooth', block: 'center' });
  await shFollowTick(true);
  shFollowTimer = setInterval(() => {
    if (typeof currentTab !== 'undefined' && currentTab !== 'shares') { shFollowStop(); return; }
    shFollowTick(false);
  }, 10000);
}
async function shFollowTick(first) {
  if (!shFollowId) return;
  const d = await api('/api/shares/' + shFollowId + '/latest').catch(() => null);
  if (!d || d.lat == null || !shFollowLayer) return;
  shFollowLayer.clearLayers();
  if (d.tail.length > 1) L.polyline(d.tail, { color: '#d9822b', weight: 4, opacity: .8 }).addTo(shFollowLayer);
  if (d.accuracy) L.circle([d.lat, d.lng], { radius: d.accuracy, color: '#0a6640', weight: 1, fillOpacity: .1 }).addTo(shFollowLayer);
  L.circleMarker([d.lat, d.lng], { radius: 10, color: '#0a6640', fillColor: '#2ecc71', fillOpacity: .95, weight: 3 })
    .bindTooltip(mEsc(d.name), { permanent: true, direction: 'top', offset: [0, -10] }).addTo(shFollowLayer);
  if (first) shMap.setView([d.lat, d.lng], 17); else shMap.panTo([d.lat, d.lng]);
  const ago = d.age_s == null ? '—' : d.age_s < 60 ? d.age_s + ' ثانية' : Math.round(d.age_s / 60) + ' دقيقة';
  document.getElementById('shFollowText').innerHTML = `تتبع: ${mEsc(d.name)} — آخر موقع قبل ${ago} (${mEsc((d.updated_at || '').slice(11, 19))})`
    + (d.live ? (d.age_s != null && d.age_s <= 120 ? ' · <span style="color:#0a6640">🟢 متصل الآن</span>' : ' · <span style="color:#b45309">⚪ لا تصل تحديثات حالياً</span>') : ' · <span style="color:#c0392b">انتهت المشاركة</span>');
}
function shFollowStop(keep) {
  clearInterval(shFollowTimer); shFollowTimer = null; shFollowId = null;
  if (shFollowLayer && shMap) { shMap.removeLayer(shFollowLayer); }
  shFollowLayer = null;
  const b = document.getElementById('shFollowBar'); if (b) { b.classList.add('hide'); b.style.display = 'none'; }
  if (!keep) shRender();
}
