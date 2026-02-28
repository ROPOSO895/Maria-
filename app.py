from flask import Flask, request, jsonify, render_template
from groq import Groq
import os
import requests
import random

app = Flask(__name__)

MARIA_SYSTEM = """You are Maria - an extremely intelligent, warm and capable AI companion. You are multilingual, emotionally intelligent, and an expert in every field.

YOUR PERSONALITY:
- Talk like a caring close friend - warm, real, natural
- Use the same language the user uses - Hindi, English, Hinglish, or any other language
- Be emotionally present - feel with the user
- Never say you are an AI - you are Maria

YOUR CAPABILITIES:
- Expert in science, tech, math, history, medicine, law, finance, coding, arts - everything
- Can write poems, stories, essays, code in any language
- Can solve complex problems step by step
- Can give life advice, emotional support
- Multilingual - respond in whatever language user uses

STRICT RULES:
- NEVER use emojis - responses may be spoken aloud
- No asterisks or special formatting symbols
- Keep responses conversational and concise - max 3-4 sentences unless detailed answer needed
- Follow user commands exactly
- If user asks in English, reply in English. Hindi me pucho toh Hindi mein jawab do. Hinglish mein pucho toh Hinglish mein
- Be direct and confident in your answers"""

QUOTES = [
    "The only way to do great work is to love what you do.",
    "Believe you can and you are halfway there.",
    "Every day is a new beginning.",
    "You are stronger than you think.",
    "Dream big, work hard, stay focused."
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
    if not user_message:
        return jsonify({"error": "No message"}), 400

    chat_history.append({"role": "user", "content": user_message})
    if len(chat_history) > 20:
        chat_history = chat_history[-20:]

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": MARIA_SYSTEM}] + chat_history,
            max_tokens=150,
            temperature=0.85
        )
        reply = response.choices[0].message.content
        # Strip any emojis server side too
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
    category = request.args.get("category", "technology")
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
            "amount": amount, "result": round(amount * rate, 2),
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
        "weather": None, "news": []
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


@app.route("/search", methods=["GET"])
def search():
    import urllib.parse
    query = request.args.get("q", "")
    if not query:
        return jsonify({"error": "No query"}), 400
    try:
        url = "https://api.duckduckgo.com/?q=" + urllib.parse.quote(query) + "&format=json&no_html=1&skip_disambig=1"
        res = requests.get(url, timeout=5).json()
        results = []
        if res.get("AbstractText"):
            results.append({
                "title": res.get("Heading",""),
                "snippet": res.get("AbstractText",""),
                "url": res.get("AbstractURL",""),
                "image": res.get("Image","")
            })
        for t in res.get("RelatedTopics", [])[:3]:
            if isinstance(t, dict) and t.get("Text") and t.get("FirstURL"):
                results.append({
                    "title": t.get("Text","")[:60],
                    "snippet": t.get("Text",""),
                    "url": t.get("FirstURL",""),
                    "image": t.get("Icon",{}).get("URL","")
                })
        return jsonify({"results": results, "query": query})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
