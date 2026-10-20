package org.iajaward.attendance;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.SystemClock;

import org.json.JSONObject;

import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/**
 * مراقبة الحضور أثناء الدوام: بعد تسجيل الحضور يرسل موقع الهاتف للنظام كل بضع دقائق
 * حتى الانصراف أو نهاية الدوام (يحدّدهما الخادم). يظهر إشعار دائم طوال المدة كما يشترط أندرويد.
 * لا يعمل إلا إذا فعّلت الإدارة المراقبة لهذا الموظف، ويتوقف تلقائياً خارج الدوام.
 */
public class PresenceService extends Service implements LocationListener {
    static final String EXTRA_DEVICE = "device", EXTRA_INTERVAL = "interval_s", EXTRA_REMAINING = "remaining_ms";
    private static final String CHANNEL = "presence", CHANNEL_ALERT = "presence_alert";
    private static final int NOTIF_ID = 4101, NOTIF_CHECK = 4102;
    static volatile boolean running = false;

    private Handler handler;
    private LocationManager lm;
    private Location last;
    private String device = "";
    private long intervalMs = 10 * 60000L;
    private long stopAtElapsed = 0;
    // في التتبع كل ثانية قد يتأخر الإرسال إن كانت الشبكة بطيئة: لا نرسل طلباً جديداً قبل انتهاء السابق
    private final java.util.concurrent.atomic.AtomicBoolean posting = new java.util.concurrent.atomic.AtomicBoolean(false);
    private long lastCheckNotified = -1;

    private final Runnable tick = new Runnable() {
        @Override public void run() {
            if (stopAtElapsed > 0 && SystemClock.elapsedRealtime() > stopAtElapsed) { stopSelf(); return; }
            sendPing();
            handler.postDelayed(this, intervalMs);
        }
    };

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        android.content.SharedPreferences sp = getSharedPreferences("presence", MODE_PRIVATE);
        if (intent != null && intent.hasExtra(EXTRA_DEVICE)) {
            String d = intent.getStringExtra(EXTRA_DEVICE);
            if (d != null && !d.isEmpty()) device = d;
            long iv = intent.getLongExtra(EXTRA_INTERVAL, 600) * 1000L;
            intervalMs = Math.max(1000L, Math.min(3600000L, iv));   // ثانية واحدة = أسرع تتبع لحظي للموظف الميداني
            long rem = intent.getLongExtra(EXTRA_REMAINING, 0);
            if (rem > 0) stopAtElapsed = SystemClock.elapsedRealtime() + rem;
            sp.edit().putString("device", device).putLong("interval", intervalMs).apply();
        } else {
            // أعاد النظام تشغيل الخدمة بعد إغلاقها: نكمل بالقيم المحفوظة، والخادم يقرّر الاستمرار أو التوقف
            device = sp.getString("device", "");
            intervalMs = sp.getLong("interval", intervalMs);
            if (device.isEmpty()) { stopSelf(); return START_NOT_STICKY; }
        }
        // أندرويد 14 يرفض خدمة الموقع دون إذن الموقع: نتوقف بهدوء (يرصد الخادم غياب القراءات)
        if (!hasLocationPermission()) { stopSelf(); return START_NOT_STICKY; }
        try { startInForeground(); } catch (Exception e) { stopSelf(); return START_NOT_STICKY; }
        if (handler == null) handler = new Handler(Looper.getMainLooper());
        startLocation();
        handler.removeCallbacks(tick);
        handler.postDelayed(tick, 15000);    // أول قراءة بعد ثوانٍ (ريثما يصل الموقع)
        running = true;
        return START_STICKY;
    }

    private void startInForeground() {
        NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26 && nm != null) {
            nm.createNotificationChannel(new NotificationChannel(CHANNEL, "مراقبة الحضور أثناء الدوام", NotificationManager.IMPORTANCE_LOW));
            nm.createNotificationChannel(new NotificationChannel(CHANNEL_ALERT, "فحص الحضور", NotificationManager.IMPORTANCE_HIGH));
        }
        Notification n = builder(CHANNEL)
                .setContentTitle("Check-in")
                .setContentText("يرسل التطبيق موقعك إلى النظام الآن (التحقق من التواجد أو مشاركة الموقع)")
                .setSmallIcon(android.R.drawable.ic_menu_mylocation)
                .setOngoing(true)
                .setContentIntent(openApp())
                .build();
        if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIF_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION);
        else startForeground(NOTIF_ID, n);
    }

    @SuppressWarnings("deprecation")
    private Notification.Builder builder(String channel) {
        return Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(this, channel) : new Notification.Builder(this);
    }

    private PendingIntent openApp() {
        Intent i = new Intent(this, MainActivity.class);
        i.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        int f = PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0);
        return PendingIntent.getActivity(this, 0, i, f);
    }

    private boolean hasLocationPermission() {
        return checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
                || checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED;
    }

    @SuppressWarnings("MissingPermission")
    private void startLocation() {
        lm = (LocationManager) getSystemService(Context.LOCATION_SERVICE);
        if (lm == null || !hasLocationPermission()) return;
        try { lm.removeUpdates(this); } catch (Exception ignored) { }
        long minTime = Math.max(1000L, Math.min(60000L, intervalMs / 2));
        try { if (lm.isProviderEnabled(LocationManager.GPS_PROVIDER)) lm.requestLocationUpdates(LocationManager.GPS_PROVIDER, minTime, 0, this); } catch (Exception ignored) { }
        try { if (lm.isProviderEnabled(LocationManager.NETWORK_PROVIDER)) lm.requestLocationUpdates(LocationManager.NETWORK_PROVIDER, minTime, 0, this); } catch (Exception ignored) { }
        try {
            Location g = lm.getLastKnownLocation(LocationManager.GPS_PROVIDER);
            Location n = lm.getLastKnownLocation(LocationManager.NETWORK_PROVIDER);
            last = better(g, n);
        } catch (Exception ignored) { }
    }

    private static Location better(Location a, Location b) {
        if (a == null) return b;
        if (b == null) return a;
        return a.getTime() >= b.getTime() ? a : b;
    }

    @Override public void onLocationChanged(Location loc) {
        if (last == null || loc.getAccuracy() <= last.getAccuracy() + 20 || loc.getTime() - last.getTime() > 60000) last = loc;
    }
    @Override public void onStatusChanged(String provider, int status, Bundle extras) { }
    @Override public void onProviderEnabled(String provider) { }
    @Override public void onProviderDisabled(String provider) { }

    private static boolean isMock(Location loc) {
        if (Build.VERSION.SDK_INT >= 31) return loc.isMock();
        return loc.isFromMockProvider();
    }

    private void sendPing() {
        final String body;
        try {
            JSONObject o = new JSONObject();
            o.put("device", device);
            boolean enabled = lm != null && hasLocationPermission()
                    && (lm.isProviderEnabled(LocationManager.GPS_PROVIDER) || lm.isProviderEnabled(LocationManager.NETWORK_PROVIDER));
            Location l = last;
            // قراءة أقدم من ثلاث دورات تُعد «بلا موقع»
            if (l != null && Build.VERSION.SDK_INT >= 17
                    && (SystemClock.elapsedRealtimeNanos() - l.getElapsedRealtimeNanos()) / 1000000L > Math.max(intervalMs * 3, 15000L)) l = null;
            if (!enabled || l == null) {
                o.put("location_off", true);
            } else {
                o.put("lat", l.getLatitude());
                o.put("lng", l.getLongitude());
                o.put("accuracy", (double) l.getAccuracy());
                o.put("mock", isMock(l));
            }
            body = o.toString();
        } catch (Exception e) {
            return;
        }
        if (!posting.compareAndSet(false, true)) return;
        new Thread(() -> { try { post(body); } finally { posting.set(false); } }).start();
    }

    private void post(String body) {
        HttpURLConnection c = null;
        try {
            String ts = String.valueOf(System.currentTimeMillis());
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(BuildConfig.APP_KEY.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            byte[] raw = body.getBytes(StandardCharsets.UTF_8);
            mac.update(raw);
            mac.update(("|" + ts).getBytes(StandardCharsets.UTF_8));
            String sig = hex(mac.doFinal());
            c = (HttpURLConnection) new URL(BuildConfig.BASE_URL + "/me/api/presence/ping").openConnection();
            c.setConnectTimeout(15000);
            c.setReadTimeout(20000);
            c.setDoOutput(true);
            c.setRequestMethod("POST");
            c.setRequestProperty("Content-Type", "application/json");
            c.setRequestProperty("X-App", "android");
            c.setRequestProperty("X-App-Ts", ts);
            c.setRequestProperty("X-App-Sig", sig);
            c.setRequestProperty("X-Device", device);
            OutputStream os = c.getOutputStream();
            os.write(raw);
            os.close();
            int code = c.getResponseCode();
            InputStream is = code < 400 ? c.getInputStream() : c.getErrorStream();
            StringBuilder sb = new StringBuilder();
            if (is != null) {
                byte[] buf = new byte[4096];
                int n;
                while ((n = is.read(buf)) > 0) sb.append(new String(buf, 0, n, StandardCharsets.UTF_8));
                is.close();
            }
            JSONObject r = new JSONObject(sb.length() > 0 ? sb.toString() : "{}");
            if (!r.optBoolean("continue", true) || code == 401 || code == 403) {
                handler.post(this::stopSelf);
                return;
            }
            long iv = r.optLong("interval_s", 0) * 1000L;
            if (iv >= 1000L && iv != intervalMs) {   // تغيّر الفاصل (مثلاً تتبع مستمر كل 15 ثانية): نعيد ضبط قراءات الموقع
                intervalMs = iv;
                getSharedPreferences("presence", MODE_PRIVATE).edit().putLong("interval", intervalMs).apply();
                handler.post(() -> {
                    startLocation();
                    // الدورة التالية كانت مجدولة بالفاصل القديم (قد يكون 10 دقائق) — نعيد جدولتها بالفاصل الجديد فوراً
                    handler.removeCallbacks(tick);
                    handler.postDelayed(tick, intervalMs);
                });
            }
            long rem = r.optLong("remaining_ms", 0);
            if (rem > 0) stopAtElapsed = SystemClock.elapsedRealtime() + rem;
            JSONObject chk = r.optJSONObject("check");
            if (chk != null) notifyCheck(chk.optLong("id", 0));
            NotesJob.show(this, r.optJSONArray("notes"));
        } catch (Exception ignored) {
            // بلا إنترنت: يرصد الخادم الفجوة عند عودة الاتصال (انقطاع الإشارة)
        } finally {
            if (c != null) c.disconnect();
        }
    }

    private void notifyCheck(long id) {
        if (id <= 0 || id == lastCheckNotified) return;
        lastCheckNotified = id;
        NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm == null) return;
        Notification n = builder(CHANNEL_ALERT)
                .setContentTitle("فحص الحضور")
                .setContentText("افتح التطبيق الآن واضغط «تأكيد وجودي» خلال دقائق")
                .setSmallIcon(android.R.drawable.ic_dialog_alert)
                .setAutoCancel(true)
                .setContentIntent(openApp())
                .build();
        nm.notify(NOTIF_CHECK, n);
    }

    private static String hex(byte[] b) {
        StringBuilder sb = new StringBuilder();
        for (byte x : b) sb.append(String.format(Locale.US, "%02x", x));
        return sb.toString();
    }

    @Override
    public void onDestroy() {
        running = false;
        if (handler != null) handler.removeCallbacks(tick);
        try { if (lm != null) lm.removeUpdates(this); } catch (Exception ignored) { }
        super.onDestroy();
    }
}
