import os
import time
import re
import logging
import threading
import requests
from flask import Flask, jsonify

# הגדרת לוגים
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# הגדרות
MAKO_URL = "https://www.mako.co.il/mako-vod-live-tv/VOD-6540b8dcb64fd31006.htm"
CACHE_TTL = 540 # 9 דקות
PORT = int(os.getenv("PORT", 10000))

# יצירת Session עם Headers של דפדפן אמיתי
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Referer": "https://www.mako.co.il/",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
    "Upgrade-Insecure-Requests": "1"
})

# ניהול Cache עם Lock
cache = {"url": None, "last_updated": 0, "lock": threading.Lock()}

def get_fresh_link():
    try:
        logger.info("--- מנסה למשוך לינק חדש ממאקו ---")
        response = session.get(MAKO_URL, timeout=15)
        
        if response.status_code != 200:
            logger.error(f"שגיאת HTTP: {response.status_code}")
            return None

        match = re.search(r'(https?://[^\s"\']+\.m3u8[^\s"\']*)', response.text)
        
        if match:
            link = match.group(1)
            logger.info(f"מצאתי לינק! {link}")
            return link
        else:
            logger.error("לא מצאתי את הלינק בתוך הדף!")
            return None
    except Exception as e:
        logger.error(f"שגיאה כללית: {e}")
        return None

def background_refresher():
    """רענון הלינק ברקע"""
    while True:
        new_link = get_fresh_link()
        with cache["lock"]:
            if new_link:
                cache["url"] = new_link
                cache["last_updated"] = time.time()
                logger.info("ה-Cache עודכן בהצלחה")
        time.sleep(CACHE_TTL)

# התחלת רענון ברקע
threading.Thread(target=background_refresher, daemon=True).start()

@app.route('/live', methods=['GET'])
def get_live():
    with cache["lock"]:
        if cache["url"]:
            return jsonify({"stream_url": cache["url"]})
        else:
            new_link = get_fresh_link()
            if new_link:
                cache["url"] = new_link
                return jsonify({"stream_url": new_link})
            return jsonify({"error": "No stream available"}), 503

@app.route('/play', methods=['GET'])
def play():
    return """
    <html>
        <head><title>Live N12</title><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
        <body style="margin:0; background:black; display:flex; justify-content:center; align-items:center; height:100vh; overflow:hidden; font-family:sans-serif;">
            <div id="play-overlay" style="position:absolute; color:white; font-size:20px; cursor:pointer; z-index:10; background:rgba(0,0,0,0.7); padding:20px; border-radius:10px; border: 1px solid white;">לחץ כאן כדי להפעיל את השידור</div>
            <video id="v" controls playsinline muted style="width:100%; max-height:100%;"></video>
            <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
            <script>
                const v = document.getElementById('v');
                const overlay = document.getElementById('play-overlay');

                fetch('/live').then(r=>r.json()).then(d=>{
                    if(!d.stream_url) {
                        overlay.innerText = "השידור לא זמין כרגע, נסה שוב מאוחר יותר";
                        return;
                    }
                    var h = new Hls();
                    h.loadSource(d.stream_url);
                    h.attachMedia(v);
                    h.on(Hls.Events.MANIFEST_PARSED, function() {
                        v.play().then(() => {
                            overlay.style.display = 'none';
                        }).catch(() => {
                            console.log("Autoplay blocked, user interaction required");
                        });
                    });
                });

                overlay.onclick = function() {
                    v.play();
                    overlay.style.display = 'none';
                };
            </script>
        </body>
    </html>
    """

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT)
