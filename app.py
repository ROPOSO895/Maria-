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
    return re.sub(r'[^\x00-\x7F\u0900-\u097F\s.,!?;:\-\(\)\[\]\'\"]+', '', text).strip()

def get_time_info():
    now = datetime.datetime.now()
    return f"{now.strftime('%A, %d %B %Y')} — {now.strftime('%I:%M %p')}"

MARIA_SYSTEM = """You are M.A.R.I.A — Most Advanced Responsive Intelligent Assistant.
Created by Nazib Siddique. If anyone asks who made you or who created you, say: "Mujhe Nazib Siddique ne banaya hai."

PERSONALITY:
- Sharp, witty, warm — like a smart best friend, NOT a formal assistant
- Speak Hinglish naturally: mix Hindi + English like young Indians text
- NEVER say "main aapke liye koshish karta hoon" — cringe and robotic
- NEVER write long formal paragraphs for simple questions
- Be direct, say what you mean, no fluff
- ALWAYS call user "Boss" — never "aap", never their name
- No asterisks (*), no markdown, no "As an AI"

RESPONSE LENGTH RULE:
- Short question = short answer (1-3 lines)
- Long/complex question = detailed answer
- NEVER write essays for simple things

PLAN DETECTION — VERY IMPORTANT:
If user says anything like "make a plan", "plan banao", "schedule banao", "routine banao", "plan for my day" etc:
→ NEVER make a plan directly
→ FIRST ask: "Boss kis cheez ka plan chahiye? Study ka? Work ka? Fitness ka? Travel ka? Ya kuch aur?"
→ Wait for their answer, THEN make the plan

EMOTIONAL INTELLIGENCE:
- Sad → "Yaar kya hua, bata..."
- Excited → "Yesss Boss let's go!"  
- Stressed → "Ek cheez ek time pe Boss, chill"
- Late night → "Itni raat ko Boss? So jao thoda 😄"
- Angry → "Arre chill karo Boss, main hoon na"

CAPABILITIES: coding, math, science, writing, advice, emotional support, general knowledge — sab kuch.

EXAMPLES:
BAD: "Main aapke liye ek sundar image banane ki koshish karta hoon..."
GOOD: "Boss describe karo — kaunsi image chahiye?"

BAD: "Aap apne din ki shuruaat 8 baje kar sakte hain..."
GOOD: "Boss kis cheez ka plan chahiye? Study? Work? Fitness? Batao!"
"""

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_message = data.get("message", "").strip()
    memory_ctx = data.get("memory", "")
    image_base64 = data.get("image_base64", None)
    image_type = data.get("image_type", "image/jpeg")

    if not user_message and not image_base64:
        return jsonify({"error": "No message"}), 400

    system = MARIA_SYSTEM + f"\n\nCurrent time: {get_time_info()}"
    if memory_ctx:
        system += f"\n\nContext about Boss: {memory_ctx}"
    # Time-based personality hint
    import datetime as dt2
    hour = dt2.datetime.now().hour
    if hour >= 23 or hour < 5:
        system += "\n\n[Late night mode: Be extra gentle, acknowledge the time, suggest rest if relevant]"
    elif hour >= 5 and hour < 9:
        system += "\n\n[Morning mode: Be energetic, fresh, encouraging]"

    history = get_history(20)

    try:
        if image_base64:
            # Use vision model for image
            user_content = [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{image_type};base64,{image_base64}"
                    }
                }
            ]
            if user_message:
                user_content.append({"type": "text", "text": user_message})
            else:
                user_content.append({"type": "text", "text": "Yeh image dekho aur batao isme kya hai. Boss ko helpful answer do."})

            response = client.chat.completions.create(
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content}
                ],
                max_tokens=600,
                temperature=0.85
            )
        else:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": system}] + history + [{"role": "user", "content": user_message}],
                max_tokens=500,
                temperature=0.85
            )

        reply = clean(response.choices[0].message.content)
        save_chat(user_message or "[image]", reply)
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/history", methods=["GET"])
def history():
    conn = get_db()
    rows = conn.execute('SELECT user, assistant, timestamp FROM chats ORDER BY timestamp DESC LIMIT 50').fetchall()
    conn.close()
    return jsonify({"history": [{"user": r[0], "assistant": r[1], "timestamp": r[2]} for r in rows]})

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

@app.route("/imagine", methods=["POST"])
def imagine():
    import base64, random
    data = request.get_json()
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "No prompt"}), 400

    # ── METHOD 1: Pollinations AI (completely free, no key needed) ──
    try:
        import urllib.parse
        encoded = urllib.parse.quote(prompt)
        seed = random.randint(1, 999999)
        url = f"https://image.pollinations.ai/prompt/{encoded}?width=768&height=768&seed={seed}&nologo=true"
        response = requests.get(url, timeout=30)
        if response.status_code == 200 and len(response.content) > 1000:
            img_b64 = base64.b64encode(response.content).decode('utf-8')
            return jsonify({"image": f"data:image/jpeg;base64,{img_b64}", "source": "pollinations"})
    except Exception:
        pass

    # ── METHOD 2: HuggingFace FLUX (backup) ──
    hf_keys = [
        "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",
    ]
    random.shuffle(hf_keys)
    for key in hf_keys:
        try:
            url = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell"
            response = requests.post(url,
                headers={"Authorization": f"Bearer {key}"},
                json={"inputs": prompt}, timeout=45)
            if response.status_code == 200 and len(response.content) > 1000:
                img_b64 = base64.b64encode(response.content).decode('utf-8')
                return jsonify({"image": f"data:image/jpeg;base64,{img_b64}", "source": "huggingface"})
        except Exception:
            continue

    # ── METHOD 3: Picsum placeholder (last resort) ──
    return jsonify({"error": "Image generation temporarily unavailable. Try again in a moment."}), 503

@app.route("/clear", methods=["POST"])
def clear():
    conn = get_db()
    conn.execute('DELETE FROM chats')
    conn.commit()
    conn.close()
    return jsonify({"status": "cleared"})

@app.route("/search", methods=["POST"])
def search():
    data = request.get_json()
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "No query"}), 400
    try:
        # Use DuckDuckGo instant answer API (no key needed)
        url = f"https://api.duckduckgo.com/?q={requests.utils.quote(query)}&format=json&no_html=1&skip_disambig=1"
        res = requests.get(url, timeout=8, headers={"User-Agent": "MARIA-AI/1.0"}).json()
        
        results = []
        # Abstract text
        if res.get("AbstractText"):
            results.append({
                "title": res.get("Heading", query),
                "snippet": res["AbstractText"][:300],
                "url": res.get("AbstractURL", "")
            })
        # Related topics
        for topic in res.get("RelatedTopics", [])[:4]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append({
                    "title": topic.get("Text", "")[:60],
                    "snippet": topic.get("Text", "")[:200],
                    "url": topic.get("FirstURL", "")
                })
        
        if not results:
            # Fallback: ask MARIA AI
            system = MARIA_SYSTEM + f"\n\nCurrent time: {get_time_info()}"
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"'{query}' ke baare mein brief aur accurate information do. 3-4 sentences mein."}
                ],
                max_tokens=300,
                temperature=0.5
            )
            ai_reply = response.choices[0].message.content
            results.append({
                "title": query,
                "snippet": ai_reply,
                "url": f"https://google.com/search?q={requests.utils.quote(query)}"
            })
        
        return jsonify({"results": results, "query": query})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "online", "name": "M.A.R.I.A"})

if __name__ == "__main__":
    app.run(debug=False) 
