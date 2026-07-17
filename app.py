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
        # הכתובת של עמוד השידור החי 
        # (אפשר לשנות את זה ל-API ספציפי אם יש לך אחד אחר)
        url = "https://www.mako.co.il/mako-vod-live-tv/VOD-6540b8dcb64fd31006.htm"
        
        # מתחזים לדפדפן רגיל כדי שלא יחסמו את השרת
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        response = requests.get(url, headers=headers)
        
        # מחפשים בתוך קוד האתר קישור שמכיל m3u8
        match = re.search(r'(https://[^\s"\'<>]+m3u8[^\s"\']*)', response.text)
        
        if match:
            fresh_link = match.group(1)
            print("Found new link:", fresh_link)
            return fresh_link
        else:
            print("Could not find m3u8 link in the page.")
            return None
            
    except Exception as e:
        print(f"Error fetching link: {e}")
        return None

# דף הבית - כדי שנדע שהשרת עובד
@app.route('/', methods=['GET'])
def home():
    return jsonify({"status": "Server is running!", "endpoint": "/live"})

# הכתובת שמחזירה את השידור
@app.route('/live', methods=['GET'])
def get_live():
    # בדיקה: אם אין לינק או שעברו יותר מ-9 דקות (540 שניות) - תרענן
    if cache["url"] is None or (time.time() - cache["last_updated"] > 540):
        print("Refreshing link...")
        new_link = get_fresh_link_from_source()
        if new_link:
            cache["url"] = new_link
            cache["last_updated"] = time.time()
    
    return jsonify({"stream_url": cache["url"]})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
