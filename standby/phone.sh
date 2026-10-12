#!/data/data/com.termux/files/usr/bin/bash
# ================================================================
#  نظام الحضور (3.iajaward.org) من الهاتف (Termux) — احتياط عند انقطاع الكمبيوتر
#  يعمل بجانب موقع الجائزة (~/iaj) دون تعارض: منفذ 8003 ونفق مستقل «attendance-standby»
#
#   bash ~/attendance/standby/phone.sh setup        # مرة واحدة: المتطلبات
#   bash ~/attendance/standby/phone.sh configure    # مرة واحدة: الرموز (من إعدادات IAJ تلقائياً) + الأزرار ATT
#   bash ~/attendance/standby/phone.sh update-code  # آخر نسخة من GitHub (أو من Drive)
#   bash ~/attendance/standby/phone.sh takeover     # ★ الطوارئ: أحدث بيانات + تشغيل + تحويل 3.iajaward.org للهاتف
#   bash ~/attendance/standby/phone.sh stop         # إنهاء الطوارئ: إرجاع للكمبيوتر أو رفع بيانات الهاتف
#   bash ~/attendance/standby/phone.sh server       # إرجاع 3.iajaward.org للكمبيوتر فوراً (بدون نقل بيانات)
#   bash ~/attendance/standby/phone.sh status       # أين يعمل الآن
#   bash ~/attendance/standby/phone.sh backup       # رفع بيانات الهاتف إلى Drive
#   bash ~/attendance/standby/phone.sh try          # تجربة على الهاتف فقط: http://127.0.0.1:8003
#
#  القفل واللغة مشتركان مع أزرار IAJ (IAJ 0 / IAJ 9).
# ================================================================
set -e
SITE="$HOME/attendance"
LOCAL_BK="$HOME/attendance-backups"
REMOTE="gdrive:IAJ-backups"
[ -f "$HOME/.iaj_standby" ] && . "$HOME/.iaj_standby"
RT_REMOTE="${RT_REMOTE:-$REMOTE/attendance}"
[ -f "$HOME/.attendance_standby" ] && . "$HOME/.attendance_standby"
TOKEN_FILE="$HOME/.attendance_tunnel_token"
export PYTHONUTF8=1
LANG_UI="${LANG_UI:-ar}"
export IAJ_LANG="$LANG_UI"
T() { if [ "$LANG_UI" = "en" ]; then printf '%s' "$2"; else printf '%s' "$1"; fi; }
say() { printf '\n\033[1;36m» %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m✖ %s\033[0m\n' "$*"; exit 1; }
guard() {
  if [ -f "$HOME/.iaj_lock" ] && [ -z "$IAJ_NOGUARD" ]; then
    die "$(T "🔒 الأزرار الحساسة مقفلة — اضغط «IAJ 0 - قفل أو فتح الأزرار» لفتحها" "🔒 Sensitive buttons are locked - press IAJ 0 to unlock")"
  fi
}
need_code() { [ -f "$SITE/serve.py" ] || die "$(T "الكود غير موجود — شغّل: bash phone.sh update-code" "Code not found - run: bash phone.sh update-code")"; }
# إيقاف نفق هذا النظام فقط (لا يلمس نفق موقع الجائزة)
kill_my_tunnel() {
  [ -s "$TOKEN_FILE" ] || return 0
  local key; key=$(head -c 40 "$TOKEN_FILE")
  for p in $(pgrep -x cloudflared 2>/dev/null); do
    tr '\0' ' ' < "/proc/$p/cmdline" 2>/dev/null | grep -qF "$key" && kill "$p" 2>/dev/null || true
  done
}
neon_on() { grep -q '^NEON_BACKUP_URL=.' "$SITE/.env" 2>/dev/null; }
ensure_pg8000() { python -c "import pg8000" 2>/dev/null || pip install -q pg8000 >/dev/null 2>&1 || true; }
other_takeover() { pgrep -f "(iaj|rastkt|venues)/standby/phone.sh takeover" >/dev/null 2>&1; }

ensure_env() {
  if [ ! -f "$SITE/.env" ]; then
    KEY=$(python -c "import secrets;print(secrets.token_urlsafe(48))")
    printf 'SECRET_KEY=%s\nBASE_URL=https://3.iajaward.org\nPORT=8003\nTHREADS=4\n' "$KEY" > "$SITE/.env"
  fi
  # رمز Cloudflare: نفس رمز موقع الجائزة على هذا الهاتف
  if ! grep -q '^CF_API_TOKEN=.' "$SITE/.env" && grep -q '^CF_API_TOKEN=.' "$HOME/iaj/.env" 2>/dev/null; then
    grep '^CF_API_TOKEN=' "$HOME/iaj/.env" >> "$SITE/.env"
  fi
  chmod 600 "$SITE/.env" 2>/dev/null || true
}

case "$1" in
  setup)
    say "$(T "تثبيت المتطلبات (pandas قد يستغرق دقائق)" "Installing requirements (pandas may take a few minutes)")"
    pkg install -y python rclone cloudflared unzip python-pillow python-numpy >/dev/null || pkg install -y python rclone cloudflared unzip python-pillow
    pip install "Flask==3.0.3" "Werkzeug==3.0.3" "requests" "waitress==3.0.2" "pg8000==1.31.5" "APScheduler==3.10.4" tzdata \
                "openpyxl>=3.1.5" "xlrd==2.0.1" "reportlab==4.2.2" "arabic-reshaper==3.0.0" "python-bidi==0.4.2"
    pip install "pandas>=2.2.2,<4" || pkg install -y python-pandas || die "$(T "تعذّر تثبيت pandas" "Could not install pandas")"
    pkg install -y python-cryptography >/dev/null 2>&1 || pip install cryptography || say "$(T "تنبيه: cryptography غير مثبتة — بصمة المتصفح (WebAuthn) معطّلة" "Note: cryptography missing — browser biometrics disabled")"
    say "$(T "تم. الخطوة التالية: bash ~/attendance/standby/phone.sh configure" "Done. Next: bash ~/attendance/standby/phone.sh configure")"
    ;;

  update-code)
    if [ -s "$HOME/.iaj_github_token" ] && [ -f "$SITE/standby/gh_update.py" ]; then
      say "$(T "تنزيل الكود من GitHub" "Downloading code from GitHub")"
      if python "$SITE/standby/gh_update.py"; then
        say "$(T "تم تحديث الكود" "Code updated")"; exit 0
      fi
      say "$(T "تعذّر GitHub (تأكد أن رمز GitHub يشمل مستودع ATTENDANCE) — أحاول من Drive" "GitHub failed (make sure the GitHub token includes the ATTENDANCE repo) - trying Drive")"
    fi
    mkdir -p "$LOCAL_BK/code"
    rclone copy "$RT_REMOTE/code" "$LOCAL_BK/code" --progress
    [ -f "$LOCAL_BK/code/attendance-code.zip" ] || die "$(T "لم أجد attendance-code.zip في Drive — شغّل backup_now.bat على الكمبيوتر" "attendance-code.zip not in Drive - run backup_now.bat on the PC")"
    unzip -oq "$LOCAL_BK/code/attendance-code.zip" -d "$HOME"
    sed -i 's/\r$//' "$SITE"/standby/*.sh 2>/dev/null || true
    say "$(T "تم تحديث الكود من Drive" "Code updated from Drive")"
    ;;

  restore)
    need_code; ensure_env
    say "$(T "تنزيل أحدث بيانات الحضور من Drive" "Downloading the latest attendance data from Drive")"
    mkdir -p "$LOCAL_BK/db"
    if ! rclone lsf "$RT_REMOTE/db" --include "*.db.gz" 2>/dev/null | grep -q . && ! neon_on && ! ls "$LOCAL_BK/db"/*.db.gz >/dev/null 2>&1; then
      echo
      echo "$(T "  ✖ لا توجد أي نسخة احتياطية لنظام الحضور في Drive ($RT_REMOTE/db)." "  ✖ There is no attendance backup in Drive ($RT_REMOTE/db).")"
      echo "$(T "    الكمبيوتر لم يرفع نسخة بعد. عند تشغيله: شغّل 3_autostart.bat كمسؤول (نسخة كل ساعة) ثم backup_now.bat" "    The PC has not uploaded one yet. When it is on: run 3_autostart.bat as admin (hourly backup), then backup_now.bat")"
      echo "$(T "    وتأكد أن مجلد النسخ BACKUP_DIR في .env داخل Google Drive: ...\\IAJ-backups\\attendance" "    and that BACKUP_DIR in .env is inside Google Drive: ...\\IAJ-backups\\attendance")"
      die "$(T "لم يتغيّر شيء — الموقع لم يُحوَّل" "Nothing changed - the site was not switched")"
    fi
    rclone copy "$RT_REMOTE/db" "$LOCAL_BK/db" --include "*.db.gz" --max-age 30d --progress || true
    rclone copy "$RT_REMOTE/uploads" "$LOCAL_BK/uploads" --progress || true
    if neon_on; then
      ensure_pg8000
      say "$(T "جلب أحدث نسخة من Neon أيضاً (تُستخدم الأحدث بين Drive وNeon)" "Also fetching the latest copy from Neon (the newer of Drive/Neon is used)")"
      (cd "$SITE" && python ops/neon_store.py pull "$LOCAL_BK/db") || say "$(T "تعذّر Neon — أكمل بنسخة Drive" "Neon failed - continuing with the Drive copy")"
    fi
    cd "$SITE" && python ops/restore.py --latest "$LOCAL_BK" --uploads --yes
    ;;

  neon)
    guard; need_code; ensure_env
    neon_on || die "$(T "لا يوجد رابط Neon — شغّل configure وألصقه عند الطلب" "No Neon link - run configure and paste it when asked")"
    ensure_pg8000
    say "$(T "تنزيل أحدث نسخة من Neon وتثبيتها على الهاتف" "Downloading the latest copy from Neon onto the phone")"
    mkdir -p "$LOCAL_BK/neon"
    F=$(cd "$SITE" && python ops/neon_store.py pull "$LOCAL_BK/neon" | tail -1)
    echo "$F"
    N=$(ls -t "$LOCAL_BK/neon"/*.db.gz 2>/dev/null | head -1)
    [ -n "$N" ] || die "$(T "لم يُنزَّل شيء" "Nothing was downloaded")"
    pkill -f "$SITE/serve.py" 2>/dev/null || true
    cd "$SITE" && python ops/restore.py --file "$N" --yes
    say "$(T "تم. بيانات Neon على الهاتف الآن — للتشغيل للعامة: زر ATT 1" "Done. Neon data is on the phone - to serve it publicly: ATT 1")"
    ;;

  try)
    need_code; ensure_env
    say "$(T "النظام يعمل على الهاتف فقط: http://127.0.0.1:8003 — للإيقاف Ctrl+C" "Running on the phone only: http://127.0.0.1:8003 - Ctrl+C to stop")"
    cd "$SITE" && DISABLE_SCHEDULER=1 python "$SITE/serve.py"
    ;;

  configure)
    need_code; ensure_env
    grep -q '^CF_API_TOKEN=.' "$SITE/.env" || {
      read -r -s -p "$(T "  الصق رمز Cloudflare API ثم Enter: " "  Paste the Cloudflare API token, then Enter: ")" TK; echo
      [ -n "$TK" ] && echo "CF_API_TOKEN=$TK" >> "$SITE/.env"; }
    say "$(T "جلب رمز نفق الهاتف attendance-standby من Cloudflare (يُحفظ ولا يظهر)" "Fetching the phone tunnel token from Cloudflare (saved, not shown)")"
    (cd "$SITE" && python ops/cf.py token > "$TOKEN_FILE.tmp") && [ -s "$TOKEN_FILE.tmp" ] && mv "$TOKEN_FILE.tmp" "$TOKEN_FILE" && chmod 600 "$TOKEN_FILE" \
      || { rm -f "$TOKEN_FILE.tmp"; die "$(T "تعذّر — شغّل أولاً على الكمبيوتر 1_setup.bat (ينشئ النفق)" "Failed - run 1_setup.bat on the PC first (it creates the tunnel)")"; }
    if ! neon_on && [ ! -f "$SITE/.neon_skip" ]; then
      read -r -s -p "$(T "  (اختياري) الصق رابط Neon لهذا النظام — أو Enter للتخطي: " "  (optional) Paste this system's Neon link - or Enter to skip: ")" NU; echo
      if [ -n "$NU" ]; then echo "NEON_BACKUP_URL=$NU" >> "$SITE/.env"; ensure_pg8000; (cd "$SITE" && python ops/neon_store.py info) || true
      else touch "$SITE/.neon_skip"; fi
    fi
    mkdir -p "$HOME/.shortcuts"
    mk() { printf '#!/data/data/com.termux/files/usr/bin/bash\n%s\necho; read -r -p "Enter ↵" _\n' "$2" > "$HOME/.shortcuts/$1"; chmod +x "$HOME/.shortcuts/$1"; }
    mk "ATT 1 - تشغيل طوارئ الحضور"  "bash ~/attendance/standby/phone.sh takeover"
    mk "ATT 1 - إنهاء طوارئ الحضور"  "bash ~/attendance/standby/phone.sh stop"
    mk "ATT 2 - إرجاع الحضور للكمبيوتر" "bash ~/attendance/standby/phone.sh server"
    mk "ATT 3 - أين يعمل نظام الحضور" "bash ~/attendance/standby/phone.sh status"
    mk "ATT 4 - تحديث كود الحضور" "bash ~/attendance/standby/phone.sh update-code && bash ~/attendance/standby/phone.sh configure"
    mk "ATT 5 - نسخ بيانات الحضور إلى Drive" "bash ~/attendance/standby/phone.sh backup"
    mk "ATT 6 - استرجاع من Neon إلى الهاتف" "bash ~/attendance/standby/phone.sh neon"
    say "$(T "تم. حدّث أداة Termux:Widget لتظهر أزرار ATT" "Done. Refresh the Termux:Widget to see the ATT buttons")"
    cd "$SITE" && python ops/cf.py status || true
    ;;

  backup)
    guard; need_code
    cd "$SITE"
    say "$(T "رفع بيانات الهاتف إلى Drive" "Uploading the phone data to Drive")"
    python ops/backup.py --dir "$LOCAL_BK" --tag phone --no-code --no-uploads
    rclone copy "$LOCAL_BK/db" "$RT_REMOTE/db" --include "*-phone.db.gz" --max-age 1d --progress
    rclone copy "$SITE/static/uploads" "$RT_REMOTE/uploads" --progress || true
    say "$(T "تم. على الكمبيوتر: back_to_server.bat" "Done. On the PC: back_to_server.bat")"
    ;;

  takeover)
    guard; need_code; ensure_env
    grep -q '^CF_API_TOKEN=.' "$SITE/.env" || die "$(T "شغّل configure أولاً" "Run configure first")"
    [ -s "$TOKEN_FILE" ] || die "$(T "شغّل configure أولاً (رمز النفق)" "Run configure first (tunnel token)")"
    if (cd "$SITE" && python ops/cf.py server-up 2>/dev/null); then
      echo
      echo "$(T "  ✋ الكمبيوتر يعمل ونظام الحضور سليم — لا حاجة للطوارئ." "  ✋ The PC is up and the attendance system is fine - no need for emergency mode.")"
      read -r -p "$(T "  للتشغيل رغم ذلك اكتب FORCE، أو Enter للإلغاء: " "  To run anyway type FORCE, or Enter to cancel: ")" ANS
      [ "$ANS" = "FORCE" ] || die "$(T "تم الإلغاء" "Cancelled")"
    fi
    say "$(T "ملاحظة: إعدادات البريد محفوظة داخل البيانات وتنتقل تلقائياً. سحب البصمات من الأجهزة يعمل فقط إذا كان الهاتف على شبكة المدرسة." "Note: email settings live in the data and move automatically. Pulling from fingerprint devices works only when the phone is on the school network.")"
    pkill -f "$SITE/serve.py" 2>/dev/null || true
    kill_my_tunnel; sleep 1
    bash "$0" restore
    cd "$SITE"
    termux-wake-lock 2>/dev/null || true
    say "$(T "تشغيل نظام الحضور" "Starting the attendance system")"
    python "$SITE/serve.py" > "$HOME/attendance-serve.log" 2>&1 &
    WEB=$!
    OK=0
    for i in $(seq 1 45); do
      kill -0 $WEB 2>/dev/null || break
      python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8003/',timeout=2)" 2>/dev/null && { OK=1; break; }
      sleep 2
    done
    if [ $OK != 1 ]; then
      kill $WEB 2>/dev/null; tail -20 "$HOME/attendance-serve.log"
      die "$(T "لم يعمل على الهاتف — لم يُحوَّل شيء" "Did not start on the phone - nothing was switched")"
    fi
    say "$(T "تشغيل نفق الهاتف" "Starting the phone tunnel")"
    cloudflared tunnel --no-autoupdate run --token "$(cat "$TOKEN_FILE")" > "$HOME/attendance-cloudflared.log" 2>&1 &
    CF=$!
    FP0=$(python ops/fingerprint.py 2>/dev/null | tail -1)
    DONE=0
    finish() {
      [ $DONE = 1 ] && return; DONE=1
      kill $WEB $CF 2>/dev/null
      say "$(T "إيقاف نظام الحضور على الهاتف" "Stopping the attendance system on the phone")"
      FP1=$(python ops/fingerprint.py 2>/dev/null | tail -1)
      if [ "$FP0" = "$FP1" ]; then
        if python ops/cf.py server; then
          python -c "import sys;sys.path.insert(0,'ops');from common import stamp;print('server',stamp())" > "$LOCAL_BK/db/ACTIVE_SITE.txt"
          rclone copyto "$LOCAL_BK/db/ACTIVE_SITE.txt" "$RT_REMOTE/db/ACTIVE_SITE.txt" 2>/dev/null || true
        else
          say "$(T "الكمبيوتر غير متصل — 3.iajaward.org سيبقى متوقفاً حتى يعود" "The PC is offline - 3.iajaward.org stays down until it is back")"
        fi
      else
        IAJ_NOGUARD=1 bash "$0" backup || true
        echo
        echo "$(T "  ⚠ سُجّلت بيانات حضور على الهاتف — على الكمبيوتر شغّل: back_to_server.bat" "  ⚠ Attendance data was recorded on the phone - on the PC run: back_to_server.bat")"
      fi
      other_takeover || termux-wake-unlock 2>/dev/null || true
    }
    trap finish EXIT INT TERM
    say "$(T "تحويل 3.iajaward.org إلى الهاتف" "Switching 3.iajaward.org to the phone")"
    if python ops/cf.py phone; then
      python -c "import sys;sys.path.insert(0,'ops');from common import stamp;print('phone',stamp())" > "$LOCAL_BK/db/ACTIVE_SITE.txt"
      rclone copyto "$LOCAL_BK/db/ACTIVE_SITE.txt" "$RT_REMOTE/db/ACTIVE_SITE.txt" 2>/dev/null || true
    else
      die "$(T "لم يتم التحويل" "Switch failed")"
    fi
    say "$(T "✅ الهاتف يشغّل 3.iajaward.org — لا تغلق النافذة. للإنهاء: زر «ATT 1 - إنهاء» أو Ctrl+C" "✅ The phone serves 3.iajaward.org - keep this window. To finish: ATT 1 - Stop, or Ctrl+C")"
    while kill -0 $WEB 2>/dev/null && kill -0 $CF 2>/dev/null; do sleep 5; done
    say "$(T "توقف النظام أو النفق على الهاتف" "The system or tunnel stopped on the phone")"
    exit 0
    ;;

  stop)
    PID=$(pgrep -f "attendance/standby/phone.sh takeover" | grep -v "^$$\$" | head -1)
    if [ -z "$PID" ]; then
      say "$(T "طوارئ الحضور ليست قيد التشغيل" "Attendance emergency mode is not running")"
    else
      say "$(T "إنهاء الطوارئ… (قد يستغرق دقيقة)" "Stopping emergency mode... (may take a minute)")"
      kill -INT "$PID" 2>/dev/null || true
      for i in $(seq 1 45); do kill -0 "$PID" 2>/dev/null || break; sleep 2; done
    fi
    need_code; cd "$SITE" && python ops/cf.py status 2>/dev/null || true
    ;;

  server)
    guard; need_code
    read -r -p "$(T "  إرجاع 3.iajaward.org للكمبيوتر بدون نقل بيانات — اكتب YES: " "  Move 3.iajaward.org back to the PC without moving data - type YES: ")" OK
    [ "$OK" = "YES" ] || die "$(T "تم الإلغاء" "Cancelled")"
    cd "$SITE" && python ops/cf.py server
    ;;

  status)
    need_code; cd "$SITE" && python ops/cf.py status
    ;;

  *)
    sed -n '2,18p' "$0"
    ;;
esac
