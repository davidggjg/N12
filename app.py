import os
import time
import re
import logging
import threading
import requests
from flask import Flask, jsonify, Response

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
                    fetch('/live').then(r => r.json()).then(d => {
                        if (!d.stream_url) {
                            overlay.innerText = "השידור לא זמין כרגע - נסי לרענן בעוד רגע";
                            return;
                        }
                        var h = new Hls({
                            xhrSetup: function(xhr) {
                                xhr.setRequestHeader('Referer', 'https://www.mako.co.il/');
                            }
                        });
                        h.loadSource(d.stream_url);
                        h.attachMedia(v);
                        h.on(Hls.Events.MANIFEST_PARSED, function() {
                            v.play().catch(() => console.log("ממתין לאינטראקציה של המשתמש"));
                        });
                        h.on(Hls.Events.ERROR, function(event, data) {
                            if (data.fatal) {
                                console.error("שגיאת HLS קריטית, מנסה לטעון מחדש בעוד 5 שניות", data);
                                setTimeout(loadStream, 5000);
                            }
                        });
                    }).catch(() => {
                        overlay.innerText = "שגיאה בטעינת השידור";
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
