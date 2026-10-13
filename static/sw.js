/*
 * Service Worker لتثبيت النظام كتطبيق (PWA) على أندرويد/ويندوز (وحتى
 * آيفون جزئياً عبر "إضافة للشاشة الرئيسية" بدون Service Worker أصلاً،
 * لكن وجوده هنا لا يضرّ ولا يُستخدَم هناك).
 *
 * ===== نطاق التخزين المؤقت مقصود يكون محدوداً جداً وآمناً: فقط ملفات
 * ثابتة تحت /static/ (CSS/JS/الأيقونات) - بدون أي صفحة HTML وبدون أي
 * /api/. السبب: صفحة /dashboard تُبنى بالخادم حسب صلاحيات كل مستخدم
 * (Jinja + session)، فتخزينها مؤقتاً قد يُظهر واجهة قديمة أو صلاحيات
 * خاطئة لمستخدم آخر على نفس الجهاز. و/api/ تحتوي بيانات حسّاسة (حضور/
 * موظفين) لا يصح تخزينها بذاكرة الجهاز بدون تحكّم دقيق. لذلك الهدف من
 * هذا الـService Worker هو فقط تحقيق شرط "قابل للتثبيت" (installability)
 * بمتصفحات كروم/إيدج، وتسريع تحميل الملفات الثابتة قليلاً - وليس تشغيل
 * النظام بدون إنترنت بالكامل (يحتاج اتصال فعلي بالخادم دائماً لأي بيانات).
 */
const CACHE_NAME = 'attendance-static-v4';   // يُخدم من /sw.js (نطاق الموقع كله) لتثبيت النظام كتطبيق
const STATIC_PREFIX = '/static/';

/* ===== استثناء مقصود: صفحتان تعملان دون إنترنت ولا تحويان بيانات شخصية في HTML:
   /me/qr  (رمز الموظف — السرّ محفوظ في الهاتف لا في الصفحة)  و  /kiosk  (جهاز المدخل).
   تُجلب من الشبكة أولاً وتُحدَّث نسختها، وعند انقطاع الإنترنت تُعرض النسخة المحفوظة.
   وأي فتح لصفحات /me دون اتصال يُحوَّل إلى رمز المدخل. ===== */
const OFFLINE_PAGES = ['/me/qr', '/kiosk'];
const OFFLINE_ASSETS = ['/static/vendor/qrcode.js', '/static/vendor/jsQR.js'];
const PAGE_CACHE = 'attendance-offline-v1';

self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(caches.open(PAGE_CACHE).then((c) => Promise.all(OFFLINE_ASSETS.concat(['/me/qr']).map((u) => c.add(u).catch(() => {})))));
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  const page = OFFLINE_PAGES.includes(url.pathname);
  const asset = OFFLINE_ASSETS.includes(url.pathname);
  const meNav = req.mode === 'navigate' && (url.pathname === '/me' || url.pathname.startsWith('/me/'));
  if (!page && !asset && !meNav) return;
  event.respondWith(
    fetch(req).then((resp) => {
      if (resp && resp.ok && (page || asset)) { const copy = resp.clone(); caches.open(PAGE_CACHE).then((c) => c.put(url.pathname, copy)); }
      return resp;
    }).catch(() => caches.open(PAGE_CACHE).then((c) =>
      c.match(url.pathname).then((hit) => hit || (meNav ? c.match('/me/qr') : undefined)).then((hit) => hit || Response.error())
    ))
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(names.filter((n) => n !== CACHE_NAME && n !== PAGE_CACHE).map((n) => caches.delete(n)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (!url.pathname.startsWith(STATIC_PREFIX)) return; // لا نلمس /api أو صفحات HTML
  if (OFFLINE_ASSETS.includes(url.pathname)) return;    // تخدمها معالجة الصفحات دون اتصال أعلاه

  event.respondWith(
    caches.open(CACHE_NAME).then((cache) =>
      cache.match(req).then((cached) => {
        const fetchPromise = fetch(req).then((networkResp) => {
          if (networkResp && networkResp.ok) cache.put(req, networkResp.clone());
          return networkResp;
        }).catch(() => cached);
        // stale-while-revalidate: نعرض النسخة المخزَّنة فوراً لو موجودة
        // (أسرع)، وبنفس الوقت نحدّثها بالخلفية من الشبكة
        return cached || fetchPromise;
      })
    )
  );
});
