# تشغيل نظام الحضور والانصراف على الكمبيوتر (3.iajaward.org) + الهاتف احتياطاً

نفس طريقة موقع الجائزة ونظامي التذاكر والحجوزات: الكمبيوتر يشغّل النظام، Cloudflare ينشره على `https://3.iajaward.org`،
نسخة احتياطية كل ساعة إلى Google Drive (ونسخة ثانية في Neon إن رُبط)، والهاتف يتولّى عند انقطاع الكمبيوتر.

| | |
|---|---|
| المنفذ المحلي | `8003` (الجائزة 8000، التذاكر 8001، الحجوزات 8002) |
| القاعدة | `data\attendance_web.db` (+ الشعار في `static\uploads`) |
| النسخ | `BACKUP_DIR\db` (داخل مجلد Drive للجائزة: `IAJ-backups\attendance`) |
| نفق الكمبيوتر | نفس نفق الجائزة `iajaward` |
| نفق الهاتف | `attendance-standby` (يُنشأ تلقائياً) |
| أجهزة البصمة | يجب أن يكون الكمبيوتر على شبكة المدرسة نفسها (السحب من الهاتف يعمل فقط على شبكة المدرسة) |

## الكمبيوتر (مرة واحدة)

```bat
git clone https://github.com/AcsVe/attendance.git C:\attendance
cd C:\attendance
1_setup.bat            :: الإعدادات + كلمة مرور admin + نقل قاعدة قديمة (اختياري) + ربط 3.iajaward.org
3_autostart.bat        :: كمسؤول: تشغيل مع Windows + نسخ كل ساعة + الحارس
```

| الملف | العمل |
|---|---|
| `update.bat` | تحديث الكود من GitHub وإعادة التشغيل |
| `att_on.bat` / `att_off.bat` | تشغيل / إيقاف 3.iajaward.org فقط (المواقع الأخرى تبقى) |
| `site_where.bat` | أين يعمل 3.iajaward.org + تشخيص + حالة الحارس |
| `switch_to_server.bat` | إرجاع 3.iajaward.org للكمبيوتر فوراً |
| `back_to_server.bat` | بعد الطوارئ: أخذ بيانات الهاتف + إرجاع الموقع |
| `backup_now.bat` / `restore_backup.bat` | نسخ / استرجاع يدوي |
| `neon_link.bat` | ربط نسخة ثانية في Neon |
| `protection_on.bat` / `protection_off.bat` | حماية مصدر الصفحات |

## الهاتف (Termux — بجانب موقع الجائزة)

```bash
cd ~ && curl -sL -H "Authorization: Bearer $(cat ~/.iaj_github_token)" \
  https://api.github.com/repos/AcsVe/attendance/zipball/main -o r.zip && \
  unzip -q r.zip -d rtmp && mv rtmp/* attendance && rm -rf rtmp r.zip && \
  bash ~/attendance/standby/phone.sh setup && bash ~/attendance/standby/phone.sh configure
```

رمز GitHub يجب أن يشمل مستودع Attendance. الأزرار: `ATT 1` تشغيل/إنهاء الطوارئ، `ATT 2` إرجاع للكمبيوتر،
`ATT 3` الحالة، `ATT 4` تحديث الكود، `ATT 5` رفع بيانات الهاتف، `ATT 6` استرجاع من Neon. القفل واللغة من أزرار `IAJ 0` و`IAJ 9`.
