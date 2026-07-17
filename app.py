from flask import Flask, jsonify
from flask_cors import CORS
import time

app = Flask(__name__)
CORS(app) # מאפשר לאתר שלך בגיטהאב לדבר עם השרת הזה

# ה-Cache שלנו
cache = {
    "url": None,
    "last_updated": 0
}

def get_fresh_link_from_source():
    # --- כאן תבוא הלוגיקה שלך ---
    # כאן אתה תשים את הסקריפט שמושך את הלינק מ-12+
    # זמנית, בוא נשים פה לינק דמה:
    new_link = "https://d2249b6f08tjt0.cloudfront.net/..." 
    return new_link

@app.route('/live', methods=['GET'])
def get_live():
    # בדיקה: אם אין לינק או שעברו יותר מ-9 דקות (540 שניות) - תרענן
    if cache["url"] is None or (time.time() - cache["last_updated"] > 540):
        print("Refreshing link...")
        cache["url"] = get_fresh_link_from_source()
        cache["last_updated"] = time.time()
    
    return jsonify({"stream_url": cache["url"]})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)

