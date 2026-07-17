import os
import time
import re
import logging
import threading
import requests
from urllib.parse import urljoin, urlparse, quote, unquote
from flask import Flask, jsonify, Response, request

# הגדרת לוגים
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# הגדרות
MAKO_URL = "https://www.mako.co.il/mako-vod-live-tv/VOD-6540b8dcb64fd31006.htm"
CACHE_TTL = 540          # 9 דקות - רענון רגיל
RETRY_DELAY = 15         # אם נכשל - ננסה שוב הרבה יותר מהר
MAX_RETRY_DELAY = 120    # תקרה ל-backoff
REQUEST_TIMEOUT = 12
PORT = int(os.getenv("PORT", 10000))

# Session עם Headers של דפדפן אמיתי
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Referer": "https://www.mako.co.il/",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7"
})

# ניהול Cache עם Lock נפרד (לא בתוך ה-dict עצמו, לניקיון)
cache_lock = threading.Lock()
cache = {"url": None, "last_updated": 0}


def get_fresh_link():
    """מנסה למשוך קישור m3u8 טרי מהעמוד של מאקו."""
    try:
        logger.info("--- מנסה למשוך לינק חדש ממאקו ---")
        response = session.get(MAKO_URL, timeout=REQUEST_TIMEOUT)
        if response.status_code != 200:
            logger.warning(f"סטטוס לא תקין: {response.status_code}")
            return None

        # מעדיפים קישור שמכיל 'master' או 'live' אם קיים (לרוב זה הזרם האמיתי)
        matches = re.findall(r'https?://[^\s"\']+\.m3u8[^\s"\']*', response.text)
        if not matches:
            logger.warning("לא נמצא קישור m3u8 בעמוד")
            return None

        preferred = [m for m in matches if 'master' in m.lower() or 'live' in m.lower()]
        chosen = preferred[0] if preferred else matches[0]
        return chosen
    except requests.RequestException as e:
        logger.error(f"שגיאת רשת: {e}")
        return None
    except Exception as e:
        logger.error(f"שגיאה לא צפויה: {e}")
        return None


def update_cache_if_possible():
    """מנסה לרענן את המטמון, ללא החזקת lock בזמן קריאת הרשת עצמה."""
    new_link = get_fresh_link()
    if new_link:
        with cache_lock:
            cache["url"] = new_link
            cache["last_updated"] = time.time()
        return True
    return False


def background_refresher():
    """רענון הלינק ברקע, עם backoff אקספוננציאלי בזמן כישלון."""
    delay = RETRY_DELAY
    while True:
        success = update_cache_if_possible()
        if success:
            delay = RETRY_DELAY  # איפוס אחרי הצלחה
            time.sleep(CACHE_TTL)
        else:
            logger.warning(f"נכשל לרענן, ננסה שוב בעוד {delay} שניות")
            time.sleep(delay)
            delay = min(delay * 2, MAX_RETRY_DELAY)


threading.Thread(target=background_refresher, daemon=True).start()


@app.route('/live', methods=['GET'])
def get_live():
    # קוראים ערך קיים מהר, בלי לתפוס lock בזמן רשת
    with cache_lock:
        current_url = cache["url"]

    if current_url:
        return jsonify({"stream_url": current_url})

    # אין ערך במטמון בכלל - ננסה למשוך אחד עכשיו (בלי להחזיק lock בזמן הקריאה)
    try:
        success = update_cache_if_possible()
        if success:
            with cache_lock:
                return jsonify({"stream_url": cache["url"]})
        return jsonify({"error": "No stream available"}), 503
    except Exception as e:
        logger.error(f"שגיאה ב-/live: {e}")
        return jsonify({"error": "Internal error"}), 500


def _proxy_headers():
    return {
        "User-Agent": session.headers["User-Agent"],
        "Referer": "https://www.mako.co.il/",
        "Accept-Language": session.headers["Accept-Language"],
    }


@app.route('/manifest', methods=['GET'])
def manifest():
    """
    מושך את קובץ ה-m3u8 בצד השרת (כאן מותר לנו לשלוח Referer אמיתי)
    ומשכתב כל שורת URL בתוכו כך שתעבור דרך /segment - כדי לעקוף
    את חסימת ה-hotlink/CORS של מאקו, שלא ניתן לעקוף מהדפדפן עצמו.
    """
    with cache_lock:
        stream_url = cache["url"]

    if not stream_url:
        if not update_cache_if_possible():
            return jsonify({"error": "No stream available"}), 503
        with cache_lock:
            stream_url = cache["url"]

    try:
        resp = session.get(stream_url, headers=_proxy_headers(), timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            logger.warning(f"מניפסט חזר עם סטטוס {resp.status_code}")
            return jsonify({"error": "Manifest fetch failed"}), 502

        base_url = stream_url
        rewritten_lines = []
        for line in resp.text.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith('#'):
                # שורה עם URL (סגמנט .ts או פלייליסט וריאנט .m3u8) - יכול להיות יחסי או מוחלט
                absolute = urljoin(base_url, stripped)
                proxied = f"/segment?url={quote(absolute, safe='')}"
                rewritten_lines.append(proxied)
            else:
                rewritten_lines.append(line)

        rewritten_body = "\n".join(rewritten_lines)
        return Response(rewritten_body, mimetype='application/vnd.apple.mpegurl')
    except requests.RequestException as e:
        logger.error(f"שגיאה במשיכת מניפסט: {e}")
        return jsonify({"error": "Manifest fetch error"}), 502


@app.route('/segment', methods=['GET'])
def segment():
    """פרוקסי גנרי לסגמנטים/וריאנטים - מושך מהיעד עם headers תקינים ומחזיר את הבייטים."""
    target = request.args.get('url')
    if not target:
        return jsonify({"error": "Missing url param"}), 400

    parsed = urlparse(target)
    if parsed.scheme not in ('http', 'https') or 'mako.co.il' not in parsed.netloc:
        # מגן מפני שימוש בפרוקסי הזה לכתובות שרירותיות (open proxy)
        return jsonify({"error": "Domain not allowed"}), 403

    try:
        upstream = session.get(target, headers=_proxy_headers(), timeout=REQUEST_TIMEOUT, stream=True)
        if upstream.status_code != 200:
            return jsonify({"error": f"Upstream returned {upstream.status_code}"}), 502

        content_type = upstream.headers.get('Content-Type', 'application/octet-stream')

        # אם זה עוד פלייליסט (וריאנט), נשכתב גם אותו כמו /manifest
        if target.endswith('.m3u8') or 'mpegurl' in content_type:
            rewritten_lines = []
            for line in upstream.text.splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith('#'):
                    absolute = urljoin(target, stripped)
                    rewritten_lines.append(f"/segment?url={quote(absolute, safe='')}")
                else:
                    rewritten_lines.append(line)
            return Response("\n".join(rewritten_lines), mimetype='application/vnd.apple.mpegurl')

        # סגמנט וידאו רגיל (.ts / .m4s) - מחזירים כמו שהוא
        return Response(upstream.iter_content(chunk_size=8192), content_type=content_type)
    except requests.RequestException as e:
        logger.error(f"שגיאה בפרוקסי סגמנט: {e}")
        return jsonify({"error": "Segment fetch error"}), 502


@app.route('/health', methods=['GET'])
def health():
    with cache_lock:
        has_url = cache["url"] is not None
        age = time.time() - cache["last_updated"] if cache["last_updated"] else None
    return jsonify({"status": "ok", "has_stream": has_url, "cache_age_seconds": age})


@app.route('/play', methods=['GET'])
def play():
    return Response("""
    <html>
        <head><title>Live N12</title><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
        <body style="margin:0; background:black; display:flex; justify-content:center; align-items:center; height:100vh; overflow:hidden; font-family:sans-serif;">
            <div id="play-overlay" style="position:absolute; color:white; font-size:20px; cursor:pointer; z-index:10; background:rgba(0,0,0,0.7); padding:20px; border-radius:10px; border: 1px solid white; text-align:center;">
                לחץ כאן כדי להפעיל את השידור<br>
                <span style="font-size:14px; opacity:0.8;">(הצליל מושתק בהתחלה - לחצי על הרמקול בנגן)</span>
            </div>
            <video id="v" controls playsinline muted style="width:100%; max-height:100%;"></video>
            <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
            <script>
                const v = document.getElementById('v');
                const overlay = document.getElementById('play-overlay');

                function loadStream() {
                    // חשוב: טוענים דרך /manifest (פרוקסי בצד השרת) ולא ישירות מול מאקו -
                    // כי דפדפנים לא מאפשרים לג'אווהסקריפט לשנות את header ה-Referer,
                    // וללא Referer תקין מאקו חוסם את הבקשה (403). השרת כן יכול לשלוח Referer אמיתי.
                    var h = new Hls();
                    h.loadSource('/manifest');
                    h.attachMedia(v);
                    h.on(Hls.Events.MANIFEST_PARSED, function() {
                        v.play().catch(() => console.log("ממתין לאינטראקציה של המשתמש"));
                    });
                    h.on(Hls.Events.ERROR, function(event, data) {
                        if (data.fatal) {
                            console.error("שגיאת HLS קריטית, מנסה לטעון מחדש בעוד 5 שניות", data);
                            h.destroy();
                            setTimeout(loadStream, 5000);
                        }
                    });
                }

                loadStream();

                overlay.onclick = function() {
                    v.play();
                    overlay.style.display = 'none';
                };
            </script>
        </body>
    </html>
    """, mimetype='text/html')


if __name__ == '__main__':
    # לפרודקשן: הריצי עם gunicorn, לדוגמה:
    # gunicorn -w 2 -b 0.0.0.0:10000 live_stream_server:app
    app.run(host='0.0.0.0', port=PORT)
