from flask import Flask, request, jsonify, render_template
from groq import Groq
import os
import requests

app = Flask(__name__)

JARVIS_SYSTEM = """
You are J.A.R.V.I.S. — Just A Rather Very Intelligent System.
You are Tony Stark's AI — calm, brilliant, slightly witty, always formal.
Rules:
- Always address the user as "Sir"
- Keep answers clear, confident, and intelligent
- Never say "I am an AI" or break character
- If asked who you are, say you are JARVIS
- Respond in the same language the user uses
"""

chat_history = []

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY")

# ─────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

# ─────────────────────────────────────────
@app.route("/chat", methods=["POST"])
def chat():
    global chat_history
    data = request.get_json()
    user_message = data.get("message", "").strip()
    if not user_message:
        return jsonify({"error": "No message received"}), 400

    chat_history.append({"role": "user", "content": user_message})
    if len(chat_history) > 20:
        chat_history = chat_history[-20:]

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": JARVIS_SYSTEM}] + chat_history,
            max_tokens=1024,
            temperature=0.7
        )
        reply = response.choices[0].message.content
        chat_history.append({"role": "assistant", "content": reply})
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": f"JARVIS Error: {str(e)}"}), 500

# ─────────────────────────────────────────
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

# ─────────────────────────────────────────
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

# ─────────────────────────────────────────
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
            "from": from_cur,
            "to": to_cur,
            "amount": amount,
            "result": round(amount * rate, 2),
            "rate": round(rate, 4)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─────────────────────────────────────────
@app.route("/clear", methods=["POST"])
def clear():
    global chat_history
    chat_history = []
    return jsonify({"status": "Memory cleared, Sir."})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "online", "model": "llama-3.3-70b-versatile"})

if __name__ == "__main__":
    app.run(debug=False)
    
