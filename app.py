import os
import time
import re
import logging
import threading
import requests
from flask import Flask, jsonify

# הגדרות לוגים
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# הגדרות סביבה
MAKO_URL = os.getenv("MAKO_URL", "https://www.mako.co.il/mako-vod-live-tv/VOD-6540b8dcb64fd31006.htm")
CACHE_TTL = 540 # 9 דקות
PORT = int(os.getenv("PORT", 10000))

# יצירת Session קבוע לביצועים מהירים
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})

# ניהול Cache עם Lock למניעת התנגשויות
cache = {"url": None, "last_updated": 0, "lock": threading.Lock()}

def get_fresh_link():
    try:
        logger.info("Fetching link from Mako...")
        response = session.get(MAKO_URL, timeout=15)
        response.raise_for_status()
        match = re.search(r'(https?://[^\s"\']+\.m3u8[^\s"\']*)', response.text)
        return match.group(1) if match else None
    except Exception as e:
        logger.error(f"Failed to fetch link: {e}")
        return None

def background_refresher():
    """פונקציה שרצה ברקע ומרעננת את הלינק"""
    while True:
        new_link = get_fresh_link()
        with cache["lock"]:
            if new_link:
                cache["url"] = new_link
                cache["last_updated"] = time.time()
                logger.info("Cache updated successfully in background")
        time.sleep(CACHE_TTL)

# התחלת רענון ברקע מיד עם הפעלת השרת
threading.Thread(target=background_refresher, daemon=True).start()

@app.route('/live', methods=['GET'])
def get_live():
    with cache["lock"]:
        if cache["url"]:
            return jsonify({"stream_url": cache["url"]})
        else:
            return jsonify({"error": "No stream available"}), 503

@app.route('/play', methods=['GET'])
def play():
    return """
    <html>
        <head><title>Live N12</title><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
        <body style="margin:0; background:black; display:flex; justify-content:center; align-items:center; height:100vh;">
            <video id="v" controls playsinline muted autoplay style="width:100%; max-width:900px;"></video>
            <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
            <script>
                fetch('/live').then(r=>r.json()).then(d=>{
                    if(!d.stream_url) return alert("השידור לא זמין כרגע");
                    var v = document.getElementById('v');
                    var h = new Hls();
                    h.loadSource(d.stream_url);
                    h.attachMedia(v);
                    v.play();
                });
            </script>
        </body>
    </html>
    """

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT)
