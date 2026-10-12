"""تشغيل نظام الحضور والانصراف على الكمبيوتر أو الهاتف بخادم Waitress (يعمل على Windows وTermux).

    python serve.py

• العنوان المحلي: http://localhost:8003  (PORT في .env) — والعام عبر Cloudflare: https://3.iajaward.org
• البيانات: مجلد data (القاعدة attendance_web.db) — DATA_DIR في .env لتغييره. الشعار: static/uploads
• الجدولة التلقائية (سحب + تحليل + بريد) تعمل من داخل التطبيق (APScheduler) — DISABLE_SCHEDULER=1 لإيقافها
• السجل: logs/server.log
"""
import logging
import logging.handlers
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'ops'))
from common import load_env  # noqa: E402

load_env()
os.makedirs(os.path.join(BASE, 'logs'), exist_ok=True)
handler = logging.handlers.RotatingFileHandler(os.path.join(BASE, 'logs', 'server.log'),
                                               maxBytes=5 * 1024 * 1024, backupCount=5, encoding='utf-8')
handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
logging.basicConfig(level=logging.INFO, handlers=[handler, logging.StreamHandler()])
log = logging.getLogger('attendance')


def main():
    import db
    db.init_db()
    from app import app
    if os.environ.get('DISABLE_SCHEDULER') != '1':
        import scheduler
        scheduler.start_scheduler()
    from waitress import serve
    port = int(os.environ.get('PORT') or 8003)
    log.info('ATTENDANCE running on http://localhost:%s  (site: %s, db: %s)', port,
             os.environ.get('BASE_URL') or '-', db.DB_PATH)
    serve(
        app,
        host=os.environ.get('HOST', '0.0.0.0'),
        port=port,
        threads=int(os.environ.get('THREADS') or 8),
        trusted_proxy='127.0.0.1',            # Cloudflare Tunnel يتصل من نفس الجهاز ويمرّر https
        trusted_proxy_count=1,
        trusted_proxy_headers={'x-forwarded-proto', 'x-forwarded-host', 'x-forwarded-for'},
        clear_untrusted_proxy_headers=True,
        max_request_body_size=2 * 1024 ** 3,   # استيراد ملفات أجهزة كبيرة
        channel_timeout=600,
        ident='ATTENDANCE',
    )


if __name__ == '__main__':
    try:
        main()
    except Exception:
        log.exception('Server failed to start')
        raise
