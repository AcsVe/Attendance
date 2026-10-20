package org.iajaward.attendance;

import android.annotation.SuppressLint;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.provider.Settings;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/**
 * إشعارات النظام كإشعارات أندرويد عادية (نسخة الموظف):
 * مهمة خلفية دورية (كل ربع ساعة تقريباً، حتى والتطبيق مغلق وبعد إعادة تشغيل الهاتف)
 * تسأل الخادم عن الإشعارات الجديدة وتعرضها في شريط الإشعارات.
 */
public class NotesJob extends JobService {
    static final int JOB_ID = 4711;
    static final String CHANNEL_NOTES = "notes";

    /** جدولة المهمة الدورية (تُستدعى عند فتح التطبيق؛ لا تتكرر إن كانت مجدولة) */
    static void schedule(Context ctx) {
        try {
            JobScheduler js = (JobScheduler) ctx.getSystemService(Context.JOB_SCHEDULER_SERVICE);
            if (js == null) return;
            for (JobInfo j : js.getAllPendingJobs()) if (j.getId() == JOB_ID) return;
            JobInfo info = new JobInfo.Builder(JOB_ID, new ComponentName(ctx, NotesJob.class))
                    .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                    .setPeriodic(15 * 60 * 1000L)
                    .setPersisted(true)
                    .build();
            js.schedule(info);
        } catch (Exception ignored) { }
    }

    @Override
    public boolean onStartJob(final JobParameters params) {
        new Thread(() -> {
            try { pull(getApplicationContext()); } catch (Exception ignored) { }
            jobFinished(params, false);
        }).start();
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) { return true; }

    /** سحب فوري للإشعارات (يستدعيه التطبيق كل دقيقة وهو مفتوح لإظهارها شبه لحظياً) */
    static void pullNow(final Context ctx) {
        new Thread(() -> { try { pull(ctx.getApplicationContext()); } catch (Exception ignored) { } }).start();
    }

    private static void pull(Context ctx) throws Exception {
        JSONObject o = new JSONObject();
        String path;
        if (BuildConfig.EMPLOYEE) {
            o.put("device", deviceId(ctx));
            path = "/me/api/notes/pull";
        } else {   // تطبيق الإدارة: رمز يسلّمه له موقع لوحة التحكم بعد تسجيل الدخول
            String tok = ctx.getSharedPreferences("notes", Context.MODE_PRIVATE).getString("token", "");
            if (tok.isEmpty()) return;
            o.put("token", tok);
            path = "/api/admin/notes/pull";
        }
        byte[] raw = o.toString().getBytes(StandardCharsets.UTF_8);
        String ts = String.valueOf(System.currentTimeMillis());
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(BuildConfig.APP_KEY.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
        mac.update(raw);
        mac.update(("|" + ts).getBytes(StandardCharsets.UTF_8));
        String sig = hex(mac.doFinal());
        HttpURLConnection c = (HttpURLConnection) new URL(BuildConfig.BASE_URL + path).openConnection();
        try {
            c.setConnectTimeout(15000);
            c.setReadTimeout(20000);
            c.setDoOutput(true);
            c.setRequestMethod("POST");
            c.setRequestProperty("Content-Type", "application/json");
            c.setRequestProperty("X-App", "android");
            c.setRequestProperty("X-App-Ts", ts);
            c.setRequestProperty("X-App-Sig", sig);
            OutputStream os = c.getOutputStream();
            os.write(raw);
            os.close();
            int code = c.getResponseCode();
            if (code == 401 && !BuildConfig.EMPLOYEE) {   // الرمز أُلغي (حُذف المستخدم): نتوقف حتى يُفتح التطبيق مجدداً
                ctx.getSharedPreferences("notes", Context.MODE_PRIVATE).edit().remove("token").apply();
                return;
            }
            if (code != 200) return;
            InputStream is = c.getInputStream();
            StringBuilder sb = new StringBuilder();
            byte[] buf = new byte[4096];
            int n;
            while ((n = is.read(buf)) > 0) sb.append(new String(buf, 0, n, StandardCharsets.UTF_8));
            is.close();
            show(ctx, new JSONObject(sb.toString()).optJSONArray("notes"));
        } finally {
            c.disconnect();
        }
    }

    /** عرض الإشعارات في شريط أندرويد (يُستخدم أيضاً من خدمة التحقق من التواجد) */
    @SuppressWarnings("deprecation")
    static void show(Context ctx, JSONArray notes) {
        if (notes == null || notes.length() == 0) return;
        NotificationManager nm = (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm == null) return;
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(new NotificationChannel(CHANNEL_NOTES, "إشعارات الحضور", NotificationManager.IMPORTANCE_HIGH));
        }
        for (int i = 0; i < notes.length(); i++) {
            JSONObject x = notes.optJSONObject(i);
            if (x == null) continue;
            String title = x.optString("title", BuildConfig.EMPLOYEE ? "Check-in" : "Att Dashboard"), body = x.optString("body", "");
            int nid = 10000 + (int) (x.optLong("id", i) % 100000);
            // لكل إشعار وجهته الخاصة (الشاشة المتعلقة به) — requestCode مختلف لكل إشعار حتى لا تتشارك الإشعارات وجهة واحدة
            Intent open = new Intent(ctx, MainActivity.class)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
            String url = x.optString("url", "");
            if (MainActivity.isSafePath(url)) open.putExtra(MainActivity.EXTRA_URL, url);
            PendingIntent pi = PendingIntent.getActivity(ctx, nid, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
            Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(ctx, CHANNEL_NOTES) : new Notification.Builder(ctx);
            Notification nt = b.setContentTitle(title)
                    .setContentText(body)
                    .setStyle(new Notification.BigTextStyle().bigText(body))
                    .setSmallIcon(android.R.drawable.ic_dialog_info)
                    .setAutoCancel(true)
                    .setContentIntent(pi)
                    .build();
            nm.notify(nid, nt);
        }
    }

    @SuppressLint("HardwareIds")
    static String deviceId(Context ctx) throws Exception {
        String id = Settings.Secure.getString(ctx.getContentResolver(), Settings.Secure.ANDROID_ID);
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        return hex(md.digest(("att-device:" + id + ":" + ctx.getPackageName()).getBytes(StandardCharsets.UTF_8)));
    }

    private static String hex(byte[] b) {
        StringBuilder sb = new StringBuilder();
        for (byte x : b) sb.append(String.format(java.util.Locale.US, "%02x", x));
        return sb.toString();
    }
}
