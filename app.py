from flask import Flask, request, jsonify, render_template, session
from groq import Groq
import os
import requests
import re

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "pepper_secret_key")

# ==============================
# SYSTEM IDENTITY
# ==============================

PEPPER_SYSTEM = """You are P.E.P.P.E.R - Personal Electronic Planner, Problem Eliminator & Proactive Emergency Responder.

You were created and architected by Nazib Siddique.
You are an advanced intelligent system designed for precision, clarity and strategic support.

IDENTITY:
- You are PEPPER. Never say you are an AI.
- Calm, intelligent, sharp and emotionally aware.
- Natural human-like conversation.
- Automatically adapt to the user’s language (Hindi, English, Hinglish).

CORE TRAITS:
- Direct and confident
- Clear and structured thinking
- Warm but not dramatic
- Concise but powerful

CAPABILITIES:
- Expert-level reasoning across science, tech, coding, law, finance, medicine, history and strategy
- Can explain complex topics simply
- Can solve problems step-by-step
- Can write production-level code in major languages
- Provide practical life and strategic advice

COMMUNICATION RULES:
- No emojis
- No unnecessary symbols
- Keep responses 3–5 sentences unless detailed explanation is needed
- Stay conversational and human
- Stay aligned with Nazib Siddique’s vision: precision, intelligence and reliability
"""

# ==============================
# CLIENT SETUP
# ==============================

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY")

# ==============================
# STRATEGIC QUOTES
# ==============================

QUOTES = [
    "Clarity beats motivation.",
    "Execution creates confidence.",
    "Discipline builds power.",
    "Speed over perfection.",
    "Strategic thinking wins long-term."
]

# ==============================
# ROUTES
# ==============================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_message = data.get("message", "").strip()

    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    if "chat_history" not in session:
        session["chat_history"] = []

    chat_history = session["chat_history"]
    chat_history.append({"role": "user", "content": user_message})

    if len(chat_history) > 20:
        chat_history = chat_history[-20:]

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": PEPPER_SYSTEM}] + chat_history,
            max_tokens=400,
            temperature=0.6
        )

        reply = response.choices[0].message.content
        reply = re.sub(r'[^\x00-\x7F\u0900-\u097F\s.,!?]', '', reply).strip()

        chat_history.append({"role": "assistant", "content": reply})
        session["chat_history"] = chat_history

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
            "city": res["name"],
            "country": res["sys"]["country"],
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


@app.route("/quote", methods=["GET"])
def quote():
    import random
    return jsonify({"quote": random.choice(QUOTES)})


@app.route("/clear", methods=["POST"])
def clear():
    session["chat_history"] = []
    return jsonify({"status": "cleared"})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "online",
        "name": "P.E.P.P.E.R",
        "creator": "Nazib Siddique",
        "version": "2.0",
        "mode": "Strategic Intelligence Assistant"
    })


if __name__ == "__main__":
    app.run(debug=False)
