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
const CACHE_NAME = 'attendance-static-v2';   // يُخدم من /sw.js (نطاق الموقع كله) لتثبيت النظام كتطبيق
const STATIC_PREFIX = '/static/';

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (!url.pathname.startsWith(STATIC_PREFIX)) return; // لا نلمس /api أو صفحات HTML

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
