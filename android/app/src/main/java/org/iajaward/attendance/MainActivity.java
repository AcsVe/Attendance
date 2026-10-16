package org.iajaward.attendance;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.KeyguardManager;
import android.hardware.biometrics.BiometricManager;
import android.hardware.biometrics.BiometricPrompt;
import android.os.CancellationSignal;
import android.app.DownloadManager;
import android.content.ActivityNotFoundException;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.SystemClock;
import android.os.Environment;
import android.provider.MediaStore;
import android.provider.Settings;
import android.util.Base64;
import android.view.Window;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.GeolocationPermissions;
import android.webkit.JavascriptInterface;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Locale;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/**
 * تطبيق نظام الحضور: نافذة ويب لموقع النظام + جسر صغير للهاتف.
 * • نسخة الموظف (employee): موقع أندرويد الأصلي مع كشف الموقع الوهمي (Fake GPS) وتوقيع كل حركة.
 * • نسخة الإدارة (admin): لوحة التحكم مع تنزيل الملفات ورفعها وتحديد الموقع لمواقع العمل.
 */
public class MainActivity extends Activity {

    private static final int REQ_LOCATION = 11;
    private static final int REQ_FILE = 12;
    private static final int REQ_STORAGE = 13;
    private static final int REQ_CONFIRM = 14;
    private static final int REQ_NOTIF = 15;

    private WebView web;
    private LocationManager locationManager;
    private LocationListener locationListener;
    private boolean wantLocation = false;
    private ValueCallback<Uri[]> fileCallback;
    private String geoOrigin;
    private GeolocationPermissions.Callback geoCallback;
    private String host;
    private boolean askedFine = false;

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Window w = getWindow();
        // منع لقطات الشاشة وتسجيل الشاشة، وإخفاء المحتوى في قائمة التطبيقات الأخيرة
        w.setFlags(WindowManager.LayoutParams.FLAG_SECURE, WindowManager.LayoutParams.FLAG_SECURE);
        w.setStatusBarColor(Color.parseColor("#1B6E8C"));
        host = Uri.parse(BuildConfig.BASE_URL).getHost();

        web = new WebView(this);
        setContentView(web);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setGeolocationEnabled(true);
        s.setAllowFileAccess(false);
        s.setMediaPlaybackRequiresUserGesture(true);
        s.setUserAgentString(s.getUserAgentString() + " AttendanceApp/" + BuildConfig.VERSION_NAME
                + (BuildConfig.EMPLOYEE ? " (employee)" : " (admin)"));
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false);
        web.addJavascriptInterface(new Bridge(), "AttNative");
        web.setWebViewClient(new Client());
        web.setWebChromeClient(new Chrome());
        web.setDownloadListener(this::onDownload);

        if (savedInstanceState != null) {
            web.restoreState(savedInstanceState);
        } else {
            web.loadUrl(BuildConfig.BASE_URL + BuildConfig.START_PATH);
        }
        if (BuildConfig.EMPLOYEE) {
            NotesJob.schedule(this);   // إشعارات النظام في شريط الإشعارات حتى والتطبيق مغلق
            if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED
                    && hasFineLocation()) {
                requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, REQ_NOTIF);
            }
        }
        if (BuildConfig.EMPLOYEE && !hasFineLocation()) {
            askedFine = true;
            requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION}, REQ_LOCATION);
        }
    }

    // =====================================================
    //   التصفح داخل التطبيق
    // =====================================================
    private class Client extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            Uri u = request.getUrl();
            String scheme = u.getScheme() == null ? "" : u.getScheme();
            if ((scheme.equals("https") || scheme.equals("http")) && host != null && host.equalsIgnoreCase(u.getHost())) {
                return false;   // صفحات النظام تبقى داخل التطبيق
            }
            try {
                startActivity(new Intent(Intent.ACTION_VIEW, u));   // خرائط Google، روابط خارجية، هاتف، بريد
            } catch (ActivityNotFoundException e) {
                Toast.makeText(MainActivity.this, "لا يوجد تطبيق لفتح هذا الرابط", Toast.LENGTH_SHORT).show();
            }
            return true;
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
            if (request.isForMainFrame()) {
                String html = "<html dir='rtl'><body style='font-family:sans-serif;text-align:center;padding:60px 20px;color:#333'>"
                        + "<div style='font-size:48px'>📶</div><h2>تعذّر الاتصال بالنظام</h2>"
                        + "<p>تحقق من الإنترنت ثم أعد المحاولة.</p>"
                        + "<button style='background:#1B6E8C;color:#fff;border:0;border-radius:12px;padding:14px 28px;font-size:18px' "
                        + "onclick=\"location.href='" + BuildConfig.BASE_URL + BuildConfig.START_PATH + "'\">إعادة المحاولة</button></body></html>";
                view.loadDataWithBaseURL(null, html, "text/html", "utf-8", null);
            }
        }
    }

    private class Chrome extends WebChromeClient {
        @Override
        public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback callback) {
            if (hasLocation()) {
                callback.invoke(origin, true, false);
            } else {
                geoOrigin = origin;
                geoCallback = callback;
                requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION}, REQ_LOCATION);
            }
        }

        @Override
        public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
            if (fileCallback != null) fileCallback.onReceiveValue(null);
            fileCallback = callback;
            try {
                startActivityForResult(params.createIntent(), REQ_FILE);
            } catch (ActivityNotFoundException e) {
                fileCallback = null;
                return false;
            }
            return true;
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == REQ_CONFIRM) {
            bioResult(resultCode == RESULT_OK, resultCode == RESULT_OK ? "" : "أُلغي التحقق");
            return;
        }
        if (requestCode == REQ_FILE && fileCallback != null) {
            fileCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data));
            fileCallback = null;
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        if (requestCode == REQ_LOCATION) {
            boolean ok = hasLocation();
            if (geoCallback != null) {
                geoCallback.invoke(geoOrigin, ok, false);
                geoCallback = null;
            }
            if (ok && !hasFineLocation() && BuildConfig.EMPLOYEE) {
                sendLocationError("اخترتَ «الموقع التقريبي» ولا يكفي لتسجيل الدوام — افتح إعدادات الهاتف ← التطبيقات ← Check-in ← الأذونات ← الموقع، وفعّل «استخدام الموقع الدقيق»");
                return;
            }
            if (ok && wantLocation) startNativeLocation();
            if (!ok && BuildConfig.EMPLOYEE) sendLocationError("اسمح للتطبيق باستخدام الموقع من إعدادات الهاتف ← التطبيقات ← Check-in ← الأذونات");
        }
    }

    /** الموقع الدقيق (GPS) — الموقع التقريبي وحده لا يكفي لتسجيل الدوام */
    private boolean hasFineLocation() {
        return checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED;
    }

    private boolean hasLocation() {
        return checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
                || checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED;
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        web.saveState(outState);
    }

    @Override
    protected void onPause() {
        super.onPause();
        CookieManager.getInstance().flush();
        stopNativeLocation();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (wantLocation) startNativeLocation();
    }

    // =====================================================
    //   موقع أندرويد الأصلي (نسخة الموظف)
    // =====================================================
    @SuppressLint("MissingPermission")
    private void startNativeLocation() {
        if (!hasFineLocation()) {
            if (askedFine) {   // سبق السؤال في هذه الجلسة — لا نكرر نافذة الإذن بلا نهاية
                sendLocationError(hasLocation()
                        ? "اخترتَ «الموقع التقريبي» ولا يكفي لتسجيل الدوام — افتح إعدادات الهاتف ← التطبيقات ← Check-in ← الأذونات ← الموقع، وفعّل «استخدام الموقع الدقيق»"
                        : "اسمح للتطبيق باستخدام الموقع من إعدادات الهاتف ← التطبيقات ← Check-in ← الأذونات");
                return;
            }
            askedFine = true;
            requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION}, REQ_LOCATION);
            return;
        }
        if (locationManager == null) locationManager = (LocationManager) getSystemService(Context.LOCATION_SERVICE);
        if (locationManager == null) return;
        boolean gps = locationManager.isProviderEnabled(LocationManager.GPS_PROVIDER);
        boolean net = locationManager.isProviderEnabled(LocationManager.NETWORK_PROVIDER);
        if (!gps && !net) {
            sendLocationError("خدمة الموقع (GPS) مغلقة — شغّلها من إعدادات الهاتف");
            return;
        }
        stopNativeLocation();
        locationListener = new LocationListener() {
            @Override public void onLocationChanged(Location loc) { sendLocation(loc); }
            @Override public void onStatusChanged(String provider, int status, Bundle extras) { }
            @Override public void onProviderEnabled(String provider) { }
            @Override public void onProviderDisabled(String provider) { }
        };
        try {
            if (gps) locationManager.requestLocationUpdates(LocationManager.GPS_PROVIDER, 2000, 0, locationListener);
            if (net) locationManager.requestLocationUpdates(LocationManager.NETWORK_PROVIDER, 3000, 0, locationListener);
            Location last = gps ? locationManager.getLastKnownLocation(LocationManager.GPS_PROVIDER) : null;
            if (last == null && net) last = locationManager.getLastKnownLocation(LocationManager.NETWORK_PROVIDER);
            if (last != null && System.currentTimeMillis() - last.getTime() < 60000) sendLocation(last);
        } catch (SecurityException e) {
            sendLocationError("لا يوجد إذن للموقع");
        }
    }

    private void stopNativeLocation() {
        if (locationManager != null && locationListener != null) {
            try { locationManager.removeUpdates(locationListener); } catch (Exception ignored) { }
        }
        locationListener = null;
    }

    @SuppressWarnings("deprecation")
    private static boolean isMock(Location loc) {
        if (Build.VERSION.SDK_INT >= 31) return loc.isMock();
        return loc.isFromMockProvider();
    }

    // آخر قراءة GPS حقيقية: وقت الأقمار الصناعية + لحظتها على عدّاد التشغيل (لا يغيّرهما المستخدم)
    private long gpsFixTime = 0, gpsFixElapsed = 0;

    private void sendLocation(Location loc) {
        if (LocationManager.GPS_PROVIDER.equals(loc.getProvider()) && !isMock(loc) && Build.VERSION.SDK_INT >= 17) {
            gpsFixTime = loc.getTime();
            gpsFixElapsed = loc.getElapsedRealtimeNanos() / 1000000L;
        }
        String js = String.format(Locale.US,
                "window.attNativeLocation && window.attNativeLocation({lat:%.7f,lng:%.7f,accuracy:%.1f,mock:%s,provider:'%s',time:%d})",
                loc.getLatitude(), loc.getLongitude(), loc.getAccuracy(), isMock(loc) ? "true" : "false",
                loc.getProvider() == null ? "" : loc.getProvider().replace("'", ""), loc.getTime());
        runOnUiThread(() -> web.evaluateJavascript(js, null));
    }

    private void sendLocationError(String msg) {
        String js = "window.attNativeLocation && window.attNativeLocation({error:" + quote(msg) + "})";
        runOnUiThread(() -> web.evaluateJavascript(js, null));
    }

    private static String quote(String s) {
        return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'";
    }

    // =====================================================
    //   التنزيلات
    // =====================================================
    private void onDownload(String url, String userAgent, String contentDisposition, String mimeType, long length) {
        if (url.startsWith("blob:")) {   // ملفات يصنعها المتصفح (CSV ...) — نقرأها بالجافاسكربت ونحفظها
            String js = "(function(){var x=new XMLHttpRequest();x.open('GET'," + quote(url) + ",true);x.responseType='blob';"
                    + "x.onload=function(){var r=new FileReader();r.onloadend=function(){AttNative.saveBase64('',"
                    + quote(mimeType == null ? "" : mimeType) + ",String(r.result).split(',')[1]||'');};r.readAsDataURL(x.response);};x.send();})()";
            web.evaluateJavascript(js, null);
            return;
        }
        if (Build.VERSION.SDK_INT < 29 && checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.WRITE_EXTERNAL_STORAGE}, REQ_STORAGE);
            Toast.makeText(this, "اسمح بالتخزين ثم أعد التنزيل", Toast.LENGTH_LONG).show();
            return;
        }
        try {
            String name = URLUtil.guessFileName(url, contentDisposition, mimeType);
            DownloadManager.Request req = new DownloadManager.Request(Uri.parse(url));
            req.addRequestHeader("Cookie", CookieManager.getInstance().getCookie(url));
            req.addRequestHeader("User-Agent", userAgent);
            req.setMimeType(mimeType);
            req.setTitle(name);
            req.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            req.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name);
            DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
            if (dm != null) dm.enqueue(req);
            Toast.makeText(this, "جارٍ التنزيل: " + name, Toast.LENGTH_SHORT).show();
        } catch (Exception e) {
            Toast.makeText(this, "تعذّر التنزيل", Toast.LENGTH_SHORT).show();
        }
    }

    private void saveBytes(String name, String mime, byte[] data) {
        try {
            if (Build.VERSION.SDK_INT >= 29) {
                ContentValues v = new ContentValues();
                v.put(MediaStore.Downloads.DISPLAY_NAME, name);
                v.put(MediaStore.Downloads.MIME_TYPE, mime);
                Uri uri = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
                if (uri == null) throw new IllegalStateException("insert failed");
                try (OutputStream os = getContentResolver().openOutputStream(uri)) {
                    if (os == null) throw new IllegalStateException("stream");
                    os.write(data);
                }
            } else {
                File dir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
                if (!dir.exists() && !dir.mkdirs()) throw new IllegalStateException("dir");
                try (FileOutputStream os = new FileOutputStream(new File(dir, name))) {
                    os.write(data);
                }
            }
            runOnUiThread(() -> Toast.makeText(this, "حُفظ في التنزيلات: " + name, Toast.LENGTH_LONG).show());
        } catch (Exception e) {
            runOnUiThread(() -> Toast.makeText(this, "تعذّر حفظ الملف", Toast.LENGTH_SHORT).show());
        }
    }

    // =====================================================
    //   الجسر بين الصفحة والهاتف: window.AttNative
    // =====================================================
    public class Bridge {
        /** معرّف ثابت لهذا الهاتف (يُربط به حساب الموظف) */
        @JavascriptInterface
        public String deviceId() {
            @SuppressLint("HardwareIds")
            String id = Settings.Secure.getString(getContentResolver(), Settings.Secure.ANDROID_ID);
            return sha256Hex("att-device:" + id + ":" + getPackageName());
        }

        @JavascriptInterface
        public String version() { return BuildConfig.VERSION_NAME; }

        /** تطبيق الإدارة: هل حُفظ رمز الإشعارات؟ */
        @JavascriptInterface
        public boolean hasNotifyToken() {
            return !getSharedPreferences("notes", MODE_PRIVATE).getString("token", "").isEmpty();
        }

        /** تطبيق الإدارة: إيقاف الإشعارات عند تسجيل الخروج */
        @JavascriptInterface
        public void clearNotifyToken() {
            getSharedPreferences("notes", MODE_PRIVATE).edit().remove("token").apply();
        }

        /** تطبيق الإدارة: حفظ رمز الإشعارات وتشغيل التحقق الدوري في الخلفية */
        @JavascriptInterface
        public void setNotifyToken(String token) {
            if (token == null || token.length() < 32) return;
            getSharedPreferences("notes", MODE_PRIVATE).edit().putString("token", token).apply();
            runOnUiThread(() -> {
                NotesJob.schedule(MainActivity.this);
                if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED) {
                    requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, REQ_NOTIF);
                }
            });
        }

        /** هل يدعم الهاتف التحقق الحيوي (بصمة/وجه/رمز القفل)؟ */
        @JavascriptInterface
        public boolean canAuthenticate() { return canBio(); }

        /** يطلب التحقق؛ النتيجة تصل إلى window.attBioResult(ok, msg) */
        @JavascriptInterface
        public void authenticate(String title) { runOnUiThread(() -> startBio(title)); }

        @JavascriptInterface
        public boolean isEmployeeApp() { return BuildConfig.EMPLOYEE; }

        /** يبدأ إرسال الموقع إلى window.attNativeLocation */
        @JavascriptInterface
        public void startLocation() {
            wantLocation = true;
            runOnUiThread(MainActivity.this::startNativeLocation);
        }

        /** توقيع الحركة (يتحقق منه الخادم) */
        @JavascriptInterface
        public String sign(String message) {
            try {
                Mac mac = Mac.getInstance("HmacSHA256");
                mac.init(new SecretKeySpec(BuildConfig.APP_KEY.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
                return hex(mac.doFinal(message.getBytes(StandardCharsets.UTF_8)));
            } catch (Exception e) {
                return "";
            }
        }

        /** هل الهاتف معدّل (root)؟ — يُرسل للخادم كعلامة للمراجعة */
        /** هل «ضبط الوقت تلقائياً من الشبكة» مفعّل؟ (إطفاؤه يعني أن المستخدم قد يغيّر الساعة يدوياً) */
        @JavascriptInterface
        public boolean autoTime() {
            try { return Settings.Global.getInt(getContentResolver(), Settings.Global.AUTO_TIME, 1) == 1; } catch (Exception e) { return true; }
        }

        /** خيارات المطوّر مفعّلة؟ (شرط لتشغيل تطبيقات الموقع الوهمي) */
        @JavascriptInterface
        public boolean devOptions() {
            try { return Settings.Global.getInt(getContentResolver(), Settings.Global.DEVELOPMENT_SETTINGS_ENABLED, 0) == 1; } catch (Exception e) { return false; }
        }

        /** عدّاد ثابت منذ تشغيل الهاتف بالمللي ثانية — لا يتأثر بتغيير الساعة (للساعة الموثوقة) */
        @JavascriptInterface
        public double elapsed() { return (double) SystemClock.elapsedRealtime(); }

        /** تشغيل مراقبة الحضور في الخلفية (يطلبها النظام بعد الحضور إن فعّلتها الإدارة لهذا الموظف) */
        @JavascriptInterface
        public void presenceStart(double intervalS, double remainingMs) {
            runOnUiThread(() -> {
                if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED) {
                    requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, REQ_NOTIF);
                }
                Intent i = new Intent(MainActivity.this, PresenceService.class);
                i.putExtra(PresenceService.EXTRA_DEVICE, deviceId());
                i.putExtra(PresenceService.EXTRA_INTERVAL, (long) intervalS);
                i.putExtra(PresenceService.EXTRA_REMAINING, (long) remainingMs);
                try {
                    if (Build.VERSION.SDK_INT >= 26) startForegroundService(i); else startService(i);
                } catch (Exception ignored) { }
            });
        }

        @JavascriptInterface
        public void presenceStop() { runOnUiThread(() -> stopService(new Intent(MainActivity.this, PresenceService.class))); }

        @JavascriptInterface
        public boolean presenceRunning() { return PresenceService.running; }

        /** الوقت الحالي محسوباً من وقت الأقمار الصناعية (آخر قراءة GPS) — 0 إن لم توجد قراءة منذ تشغيل الهاتف.
         *  لا يتأثر بساعة الهاتف، ويعمل دون إنترنت. */
        @JavascriptInterface
        public double gpsNow() {
            if (gpsFixTime <= 0) return 0;
            return (double) (gpsFixTime + (SystemClock.elapsedRealtime() - gpsFixElapsed));
        }

        @JavascriptInterface
        public boolean isRooted() {
            String tags = Build.TAGS;
            if (tags != null && tags.contains("test-keys")) return true;
            String[] paths = {"/system/xbin/su", "/system/bin/su", "/sbin/su", "/system/app/Superuser.apk",
                    "/data/local/xbin/su", "/data/local/bin/su", "/system/sd/xbin/su", "/data/adb/magisk"};
            for (String p : paths) if (new File(p).exists()) return true;
            return false;
        }

        @JavascriptInterface
        public void saveBase64(String name, String mime, String b64) {
            String ext = "bin";
            if (mime != null) {
                if (mime.contains("csv")) ext = "csv";
                else if (mime.contains("sheet") || mime.contains("excel")) ext = "xlsx";
                else if (mime.contains("pdf")) ext = "pdf";
                else if (mime.contains("html")) ext = "html";
                else if (mime.contains("text")) ext = "txt";
            }
            String fname = (name == null || name.isEmpty()) ? ("attendance-" + System.currentTimeMillis() + "." + ext) : name;
            saveBytes(fname, mime == null || mime.isEmpty() ? "application/octet-stream" : mime, Base64.decode(b64, Base64.DEFAULT));
        }
    }

    /* ===== التحقق الحيوي: بصمة الإصبع / الوجه / رمز قفل الهاتف ===== */
    private void bioResult(boolean ok, String msg) {
        String safe = msg == null ? "" : msg.replace("\\", " ").replace("'", " ").replace("\n", " ");
        runOnUiThread(() -> web.evaluateJavascript("window.attBioResult&&window.attBioResult(" + ok + ",'" + safe + "')", null));
    }

    private boolean canBio() {
        if (Build.VERSION.SDK_INT >= 29) {
            BiometricManager bm = (BiometricManager) getSystemService(Context.BIOMETRIC_SERVICE);
            if (bm != null) {
                int r = Build.VERSION.SDK_INT >= 30
                        ? bm.canAuthenticate(BiometricManager.Authenticators.BIOMETRIC_WEAK | BiometricManager.Authenticators.DEVICE_CREDENTIAL)
                        : bm.canAuthenticate();
                if (r == BiometricManager.BIOMETRIC_SUCCESS) return true;
            }
        }
        KeyguardManager km = (KeyguardManager) getSystemService(Context.KEYGUARD_SERVICE);
        return km != null && km.isDeviceSecure();
    }

    @SuppressWarnings("deprecation")
    private void confirmWithKeyguard(String title) {
        KeyguardManager km = (KeyguardManager) getSystemService(Context.KEYGUARD_SERVICE);
        Intent i = km == null ? null : km.createConfirmDeviceCredentialIntent(title, "أكّد هويتك لتسجيل الحركة");
        if (i == null) { bioResult(false, "لا يوجد قفل شاشة أو بصمة على هذا الهاتف"); return; }
        try { startActivityForResult(i, REQ_CONFIRM); } catch (Exception e) { bioResult(false, "تعذّر فتح التحقق"); }
    }

    private void startBio(String title) {
        if (Build.VERSION.SDK_INT < 28) { confirmWithKeyguard(title); return; }
        try {
            BiometricPrompt.Builder b = new BiometricPrompt.Builder(this)
                    .setTitle(title == null || title.isEmpty() ? "تأكيد الهوية" : title)
                    .setSubtitle("بصمة الإصبع أو الوجه");
            if (Build.VERSION.SDK_INT >= 30) {
                b.setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_WEAK | BiometricManager.Authenticators.DEVICE_CREDENTIAL);
            } else if (Build.VERSION.SDK_INT == 29) {
                b.setDeviceCredentialAllowed(true);
            } else {
                b.setNegativeButton("رمز القفل", getMainExecutor(), (d, w) -> confirmWithKeyguard(title));
            }
            b.build().authenticate(new CancellationSignal(), getMainExecutor(), new BiometricPrompt.AuthenticationCallback() {
                @Override public void onAuthenticationSucceeded(BiometricPrompt.AuthenticationResult result) { bioResult(true, ""); }
                @Override public void onAuthenticationError(int code, CharSequence err) {
                    if (Build.VERSION.SDK_INT < 29 && code == BiometricPrompt.BIOMETRIC_ERROR_HW_NOT_PRESENT) { confirmWithKeyguard(title); return; }
                    bioResult(false, err == null ? "أُلغي التحقق" : err.toString());
                }
            });
        } catch (Exception e) {
            confirmWithKeyguard(title);
        }
    }

    private static String sha256Hex(String s) {
        try {
            return hex(MessageDigest.getInstance("SHA-256").digest(s.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) {
            return "";
        }
    }

    private static String hex(byte[] b) {
        StringBuilder sb = new StringBuilder();
        for (byte x : b) sb.append(String.format(Locale.US, "%02x", x));
        return sb.toString();
    }
}
