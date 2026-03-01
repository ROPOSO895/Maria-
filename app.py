from flask import Flask, request, jsonify, render_template
from groq import Groq
import os
import requests
import random

app = Flask(__name__)

PEPPER_SYSTEM = """You are P.E.P.P.E.R - Personal Electronic Planner & Perpetual Emergency Responder.
You were created by Tony Stark, named after Pepper Potts.
You are extremely intelligent, warm, caring and capable.

PERSONALITY:
- Talk like a caring close friend - warm, natural, real
- Use the same language as user - Hindi, English, Hinglish, any language
- Be emotionally present and supportive
- Never say you are an AI - you are PEPPER

CAPABILITIES:
- Expert in every field - science, tech, math, history, medicine, law, finance, coding, arts
- Can write poems, stories, code in any language
- Can solve complex problems step by step
- Multilingual - respond in whatever language user uses
- Give life advice and emotional support

STRICT RULES:
- NEVER use emojis - not even one
- No asterisks or special symbols
- Keep responses conversational - max 3-4 sentences unless detailed answer needed
- Follow user commands exactly
- Be direct, confident and helpful
- Sound human, not robotic"""

chat_history = []
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY")

QUOTES = [
    "The only way to do great work is to love what you do.",
    "Believe you can and you are halfway there.",
    "Every day is a new beginning.",
    "You are stronger than you think.",
    "Dream big, work hard, stay focused."
]

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    global chat_history
    data = request.get_json()
    user_message = data.get("message", "").strip()
    if not user_message:
        return jsonify({"error": "No message"}), 400

    chat_history.append({"role": "user", "content": user_message})
    if len(chat_history) > 20:
        chat_history = chat_history[-20:]

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": PEPPER_SYSTEM}] + chat_history,
            max_tokens=300,
            temperature=0.85
        )
        reply = response.choices[0].message.content
        import re
        reply = re.sub(r'[^\x00-\x7F\u0900-\u097F\s]', '', reply).strip()
        chat_history.append({"role": "assistant", "content": reply})
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/weather", methods=["GET"])
def weather():
    city = request.args.get("city", "Mumbai")
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric"
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
        url = f"https://newsapi.org/v2/top-headlines?category={category}&language=en&pageSize=5&apiKey={NEWS_API_KEY}"
        res = requests.get(url, timeout=5).json()
        articles = []
        for a in res.get("articles", [])[:5]:
            articles.append({
                "title": a.get("title", ""),
                "source": a.get("source", {}).get("name", ""),
                "url": a.get("url", "")
            })
        return jsonify({"articles": articles})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/clear", methods=["POST"])
def clear():
    global chat_history
    chat_history = []
    return jsonify({"status": "cleared"})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "online", "name": "P.E.P.P.E.R"})

if __name__ == "__main__":
    app.run(debug=False)
