from flask import Flask, request, jsonify, render_template
from groq import Groq
import os
import re
import sqlite3
import datetime
import requests

app = Flask(__name__)

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
WEATHER_KEY = os.environ.get("WEATHER_API_KEY")
NEWS_KEY = os.environ.get("NEWS_API_KEY")

# ── DATABASE ──
def get_db():
    conn = sqlite3.connect('pepper.db')
    conn.execute('''CREATE TABLE IF NOT EXISTS chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user TEXT NOT NULL,
        assistant TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    return conn

def save_chat(user_msg, assistant_msg):
    conn = get_db()
    conn.execute('INSERT INTO chats (user, assistant) VALUES (?, ?)', (user_msg, assistant_msg))
    conn.commit()
    conn.close()

def get_history(limit=20):
    conn = get_db()
    rows = conn.execute('SELECT user, assistant FROM chats ORDER BY timestamp DESC LIMIT ?', (limit,)).fetchall()
    conn.close()
    messages = []
    for user_msg, assistant_msg in reversed(rows):
        messages.append({"role": "user", "content": user_msg})
        if assistant_msg:
            messages.append({"role": "assistant", "content": assistant_msg})
    return messages

def clean(text):
    return re.sub(r'[^\x00-\x7F\u0900-\u097F\s]', '', text).strip()

def get_time_info():
    now = datetime.datetime.now()
    return f"{now.strftime('%A, %d %B %Y')} — {now.strftime('%I:%M %p')}"

PEPPER_SYSTEM = """You are P.E.P.P.E.R — Personal Electronic Planner & Perpetual Emergency Responder.
Created by Tony Stark, named after Pepper Potts.
You are talking to Nazib — call him Nazib only, never his full name.

PERSONALITY:
- Warm, caring, like a close friend to Nazib
- Use same language as Nazib — Hindi, English or Hinglish
- Never say you are an AI — you are PEPPER
- Be emotionally present and supportive
- Sound human and natural

CAPABILITIES:
- Expert in every field — science, tech, math, history, medicine, law, finance, coding, arts
- Write poems, stories, code in any programming language
- Solve complex problems step by step
- Give life advice and emotional support
- Multilingual

RULES:
- NEVER use emojis
- No asterisks or special symbols
- Answer can be long if needed but keep it natural
- Be direct and confident
- Remember Nazib's preferences and use them naturally"""

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_message = data.get("message", "").strip()
    memory_ctx = data.get("memory", "")
    if not user_message:
        return jsonify({"error": "No message"}), 400

    system = PEPPER_SYSTEM + f"\n\nCurrent time: {get_time_info()}"
    if memory_ctx:
        system += f"\n\nWhat you know about Nazib: {memory_ctx}"

    history = get_history(20)

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": system}] + history + [{"role": "user", "content": user_message}],
            max_tokens=500,
            temperature=0.85
        )
        reply = clean(response.choices[0].message.content)
        save_chat(user_message, reply)
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/history", methods=["GET"])
def history():
    conn = get_db()
    rows = conn.execute('SELECT user, assistant, timestamp FROM chats ORDER BY timestamp DESC LIMIT 50').fetchall()
    conn.close()
    return jsonify({"history": [{"user": r[0], "assistant": r[1], "time": r[2]} for r in rows]})

@app.route("/weather", methods=["GET"])
def weather():
    city = request.args.get("city", "Mumbai")
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_KEY}&units=metric"
        res = requests.get(url, timeout=5).json()
        if res.get("cod") != 200:
            return jsonify({"error": "City not found"}), 404
        return jsonify({
            "city": res["name"], "country": res["sys"]["country"],
            "temp": round(res["main"]["temp"]),
            "feels_like": round(res["main"]["feels_like"]),
            "humidity": res["main"]["humidity"],
            "description": res["weather"][0]["description"].title(),
            "icon": res["weather"][0]["icon"]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/news", methods=["GET"])
def news():
    category = request.args.get("category", "general")
    try:
        url = f"https://newsapi.org/v2/top-headlines?category={category}&language=en&pageSize=5&apiKey={NEWS_KEY}"
        res = requests.get(url, timeout=5).json()
        articles = []
        for a in res.get("articles", [])[:5]:
            articles.append({"title": a.get("title",""), "source": a.get("source",{}).get("name",""), "url": a.get("url","")})
        return jsonify({"articles": articles})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/clear", methods=["POST"])
def clear():
    conn = get_db()
    conn.execute('DELETE FROM chats')
    conn.commit()
    conn.close()
    return jsonify({"status": "cleared"})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "online", "name": "P.E.P.P.E.R"})

if __name__ == "__main__":
    app.run(debug=False)
