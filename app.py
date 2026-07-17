from flask import Flask, jsonify
from flask_cors import CORS
import requests
import time

app = Flask(__name__)
CORS(app)

# ה-Cache שלנו
cache = {
    "url": None,
    "last_updated": 0
}

def get_fresh_link_from_source():
    try:
        # כאן הלוגיקה שלך. 
        # אם יש לך לינק ספציפי או בקשה, שים אותה כאן:
        # דוגמה (תחליף את ה-URL ללינק האמיתי שאתה מנסה למשוך):
        
        # response = requests.get("URL_של_האתר_שלך")
        # data = response.json() # או טיפול ב-HTML אם צריך
        # link = data['url']
        
        # זמני: לינק דוגמה (תחליף בשלך)
        link = "https://d2249b6f08tjt0.cloudfront.net/placeholder.m3u8" 
        return link
    except Exception as e:
        print(f"Error fetching link: {e}")
        return None

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
