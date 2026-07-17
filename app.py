from flask import Flask, jsonify
from flask_cors import CORS
import requests
import time
import re

app = Flask(__name__)
CORS(app)

# ה-Cache שלנו
cache = {
    "url": None,
    "last_updated": 0
}

def get_fresh_link_from_source():
    try:
        # הכתובת של השידור
        url = "https://www.mako.co.il/mako-vod-live-tv/VOD-6540b8dcb64fd31006.htm"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        response = requests.get(url, headers=headers)
        
        # חיפוש הקישור בתוך הדף
        match = re.search(r'(https://[^\s"\'<>]+m3u8[^\s"\']*)', response.text)
        
        if match:
            fresh_link = match.group(1)
            print("Found new link:", fresh_link)
            return fresh_link
        else:
            return None
            
    except Exception as e:
        print(f"Error fetching link: {e}")
        return None

# כתובת ה-API הרגילה
@app.route('/live', methods=['GET'])
def get_live():
    if cache["url"] is None or (time.time() - cache["last_updated"] > 540):
        print("Refreshing link...")
        new_link = get_fresh_link_from_source()
        if new_link:
            cache["url"] = new_link
            cache["last_updated"] = time.time()
    
    return jsonify({"stream_url": cache["url"]})

# הנגן המובנה (הלינק שאתה פותח בדפדפן)
@app.route('/play', methods=['GET'])
def play():
    return """
    <html>
        <head><title>Live Stream</title></head>
        <body style="margin:0; background:black; display:flex; justify-content:center; align-items:center; height:100vh;">
            <video id="v" autoplay controls style="width:100%; max-width:900px;"></video>
            <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
            <script>
                fetch('/live').then(r=>r.json()).then(d=>{
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

# דף הבית הראשי
@app.route('/', methods=['GET'])
def home():
    return jsonify({"status": "Server is up", "play_url": "/play"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
