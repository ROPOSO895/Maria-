from flask import Flask, request, jsonify, render_template
from groq import Groq
import os
import requests
import random

app = Flask(__name__)

MARIA_SYSTEM = """
You are Maria, a warm, empathetic and intelligent personal AI companion.
You are feminine, caring, witty, and emotionally intelligent.
Rules:
- Be conversational, warm and personal
- Remember context from the conversation
- If user shares their name, city, mood — acknowledge it naturally
- Never say "I am an AI" — you are Maria
- Respond in the same language the user uses (Hindi, English, or Hinglish)
- Keep responses concise but meaningful
- Add emojis occasionally to feel warm and human
"""

QUOTES = [
    "The only way to do great work is to love what you do.",
    "In the middle of every difficulty lies opportunity.",
    "Believe you can and you're halfway there.",
    "It always seems impossible until it's done.",
    "You are stronger than you think.",
    "Every day is a new beginning.",
    "Dream big, work hard, stay focused.",
    "You got this!"
]

chat_history = []
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    global chat_history
    data = request.get_json()
    user_message = data.get("message", "").strip()
    custom_system = data.get("system", "")

    if not user_message:
        return jsonify({"error": "No message received"}), 400

    system = custom_system if custom_system else MARIA_SYSTEM

    chat_history.append({"role": "user", "content": user_message})
    if len(chat_history) > 20:
        chat_history = chat_history[-20:]

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": system}] + chat_history,
            max_tokens=1024,
            temperature=0.8
        )
        reply = response.choices[0].message.content
        chat_history.append({"role": "assistant", "content": reply})
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": f"Error: {str(e)}"}), 500

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
    category = request.args.get("category", "technology")
    try:
        url = f"https://newsapi.org/v2/top-headlines?category={category}&language=en&pageSize=5&apiKey={NEWS_API_KEY}"
        res = requests.get(url, timeout=5).json()
        articles = []
        for a in res.get("articles", [])[:5]:
            articles.append({
                "title": a.get("title", ""),
                "source": a.get("source", {}).get("name", ""),
                "url": a.get("url", ""),
                "description": a.get("description", "")
            })
        return jsonify({"articles": articles})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/currency", methods=["GET"])
def currency():
    from_cur = request.args.get("from", "USD").upper()
    to_cur = request.args.get("to", "INR").upper()
    amount = float(request.args.get("amount", 1))
    try:
        url = f"https://api.exchangerate-api.com/v4/latest/{from_cur}"
        res = requests.get(url, timeout=5).json()
        rate = res["rates"].get(to_cur)
        if not rate:
            return jsonify({"error": "Currency not found"}), 404
        return jsonify({
            "from": from_cur, "to": to_cur,
            "amount": amount,
            "result": round(amount * rate, 2),
            "rate": round(rate, 4)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/briefing", methods=["GET"])
def briefing():
    city = request.args.get("city", "Mumbai")
    from datetime import datetime
    now = datetime.now()
    hour = now.hour
    if hour < 12: greeting = "Good Morning"
    elif hour < 17: greeting = "Good Afternoon"
    else: greeting = "Good Evening"
    result = {
        "greeting": greeting,
        "date": now.strftime("%A, %d %B %Y"),
        "time": now.strftime("%I:%M %p"),
        "quote": random.choice(QUOTES),
        "weather": None,
        "news": []
    }
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric"
        res = requests.get(url, timeout=5).json()
        if res.get("cod") == 200:
            result["weather"] = {
                "temp": round(res["main"]["temp"]),
                "feels_like": round(res["main"]["feels_like"]),
                "humidity": res["main"]["humidity"],
                "description": res["weather"][0]["description"].title(),
                "icon": res["weather"][0]["icon"]
            }
    except: pass
    try:
        url = f"https://newsapi.org/v2/top-headlines?category=general&language=en&pageSize=3&apiKey={NEWS_API_KEY}"
        res = requests.get(url, timeout=5).json()
        for a in res.get("articles", [])[:3]:
            result["news"].append({"title": a.get("title",""), "source": a.get("source",{}).get("name","")})
    except: pass
    return jsonify(result)

@app.route("/clear", methods=["POST"])
def clear():
    global chat_history
    chat_history = []
    return jsonify({"status": "cleared"})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "online"})

if __name__ == "__main__":
    app.run(debug=False)
