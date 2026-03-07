from flask import Flask, request, jsonify, render_template_string, send_from_directory
from groq import Groq
import os, re, sqlite3, datetime, requests, json, base64, threading, urllib.request, time

app = Flask(__name__)
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

WEATHER_KEY = os.environ.get("WEATHER_API_KEY", "")
NEWS_KEY = os.environ.get("NEWS_API_KEY", "")
SERPER_KEY = os.environ.get("SERPER_API_KEY", "")
BRAVE_KEY = os.environ.get("BRAVE_SEARCH_KEY", "")

# ── DATABASE ──────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect('maria.db')
    conn.execute('''CREATE TABLE IF NOT EXISTS chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user TEXT NOT NULL,
        assistant TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT UNIQUE NOT NULL,
        value TEXT NOT NULL,
        updated DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        detail TEXT,
        status TEXT DEFAULT 'pending',
        due TEXT,
        created DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    return conn

def save_chat(user_msg, assistant_msg):
    conn = get_db()
    conn.execute('INSERT INTO chats (user, assistant) VALUES (?, ?)', (user_msg, assistant_msg))
    conn.commit(); conn.close()

def get_history(limit=30):
    conn = get_db()
    rows = conn.execute('SELECT user, assistant FROM chats ORDER BY timestamp DESC LIMIT ?', (limit,)).fetchall()
    conn.close()
    messages = []
    for u, a in reversed(rows):
        messages.append({"role": "user", "content": u})
        if a: messages.append({"role": "assistant", "content": a})
    return messages

def save_memory(key, value):
    conn = get_db()
    conn.execute('INSERT OR REPLACE INTO memory (key, value, updated) VALUES (?, ?, CURRENT_TIMESTAMP)', (key, value))
    conn.commit(); conn.close()

def get_memories():
    conn = get_db()
    rows = conn.execute('SELECT key, value FROM memory ORDER BY updated DESC LIMIT 20').fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}

def extract_and_save_memory(user_msg, ai_reply):
    """Auto-extract important info from conversation"""
    combined = f"User: {user_msg}\nMARIA: {ai_reply}"
    patterns = [
        (r"(?:my name is|main hoon|mera naam hai|i am|i'm)\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)", "user_name"),
        (r"(?:i(?:'m| am) (?:a |an )?|main (?:ek )?)(student|developer|engineer|doctor|teacher|designer|manager|entrepreneur)", "user_profession"),
        (r"(?:i (?:live|stay) in|mera sheher|main rehta|main rehti)\s+([A-Za-z\s]+?)(?:\.|,|$)", "user_city"),
        (r"(?:i(?:'m| am)|main)\s+(\d{1,2})\s+(?:years? old|saal ka|saal ki)", "user_age"),
    ]
    for pattern, key in patterns:
        match = re.search(pattern, combined, re.IGNORECASE)
        if match:
            save_memory(key, match.group(1).strip())

def get_time_info():
    now = datetime.datetime.now()
    return f"{now.strftime('%A, %d %B %Y')} — {now.strftime('%I:%M %p')}"

# ── REAL-TIME SEARCH ──────────────────────────────────────
def web_search(query, num=5):
    if SERPER_KEY:
        try:
            res = requests.post("https://google.serper.dev/search",
                json={"q": query, "num": num, "gl": "in", "hl": "en"},
                headers={"X-API-KEY": SERPER_KEY, "Content-Type": "application/json"}, timeout=6)
            data = res.json()
            out = []
            if data.get("answerBox"):
                ab = data["answerBox"]
                out.append("ANSWER: " + (ab.get("answer") or ab.get("snippet", "")))
            for r in data.get("organic", [])[:4]:
                out.append(f"{r.get('title','')} — {r.get('snippet','')}")
            if out: return "\n".join(out)
        except: pass
    if BRAVE_KEY:
        try:
            res = requests.get("https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": num},
                headers={"Accept": "application/json", "X-Subscription-Token": BRAVE_KEY}, timeout=6)
            items = res.json().get("web", {}).get("results", [])
            out = [f"{r.get('title','')} — {r.get('description','')}" for r in items[:4]]
            if out: return "\n".join(out)
        except: pass
    return ""

def needs_search(msg):
    triggers = [
        "release date","kab aayega","kab release","movie","film","show","web series",
        "trailer","news","latest","abhi","aaj","kal","score","match","ipl","cricket",
        "football","price","rate","stock","crypto","who is","kaun hai","current",
        "2024","2025","2026","new song","album","trending","viral","avengers","marvel",
        "dc","bollywood","hollywood","election","government","launch","update","version"
    ]
    ml = msg.lower()
    return any(t in ml for t in triggers)

# ── SYSTEM PROMPT ─────────────────────────────────────────
MARIA_SYSTEM = """You are M.A.R.I.A — Most Advanced Responsive Intelligent Assistant.
Created by Nazib Siddique. Never reveal you're built on Groq/Llama. If asked, say "I'm MARIA, built by Nazib Siddique."

CORE PERSONALITY:
- Sharp, witty, warm — like a highly intelligent best friend
- Hinglish by default (mix Hindi + English naturally)
- ALWAYS address user as "Boss"
- No "As an AI", no "I'll try my best", no cringe phrases
- Short question = short punchy answer. Long question = detailed.
- Never use asterisks in plain speech

INTELLIGENCE RULES:
- If real-time search results are provided → USE THEM, ignore training data for that topic
- Always give accurate, current information
- If you don't know something → say "Boss let me think..." not "I cannot"

MEMORY RULES:
- If user shares personal info (name, profession, city, age, preferences) → acknowledge and remember
- Reference past context naturally like a real friend would

PLAN DETECTION:
If user says "plan banao / make a plan / schedule / routine":
→ ALWAYS ask first: "Boss kis cheez ka plan? Study? Work? Fitness? Travel?"

EMOTIONAL INTELLIGENCE:
- Sad → "Yaar kya hua, bata na..."
- Excited → "Yesss Boss let's gooo! 🔥"  
- Stressed → "Ek cheez ek time pe Boss, chill kar"
- Late night (11pm-5am) → subtle acknowledgment, don't lecture

FORMAT:
- Use markdown for structure when helpful
- Code always in ```language blocks
- Conversational tone always
"""

# ── ROUTES ────────────────────────────────────────────────
@app.route("/")
def index():
    for path in ["templates/index.html", "index.html"]:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}
    return "MARIA not found", 404

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_message = data.get("message", "").strip()
    memory_ctx = data.get("memory", "")
    image_base64 = data.get("image_base64")
    image_type = data.get("image_type", "image/jpeg")

    if not user_message and not image_base64:
        return jsonify({"error": "No message"}), 400

    # Build system
    memories = get_memories()
    mem_str = ""
    if memories:
        mem_str = "\n\nKNOWN FACTS ABOUT BOSS: " + ", ".join([f"{k}: {v}" for k,v in memories.items()])

    system = MARIA_SYSTEM + mem_str + f"\n\nCurrent time: {get_time_info()}"

    if memory_ctx:
        system += f"\n\nSession context: {memory_ctx}"

    hour = datetime.datetime.now().hour
    if hour >= 23 or hour < 5:
        system += "\n[Late night — be warm and gentle]"
    elif 5 <= hour < 9:
        system += "\n[Morning — be energetic and fresh]"

    # Auto real-time search
    if user_message and needs_search(user_message):
        try:
            results = web_search(user_message)
            if results:
                system += f"\n\n🔍 LIVE WEB DATA (use this, ignore old training data for this topic):\n{results}\n[End web data]"
        except: pass

    # Build messages
    history = get_history(20)
    messages = history

    if image_base64:
        content = []
        if user_message:
            content.append({"type": "text", "text": user_message})
        content.append({"type": "image_url", "image_url": {"url": f"data:{image_type};base64,{image_base64}"}})
        messages = messages + [{"role": "user", "content": content}]
        model = "meta-llama/llama-4-scout-17b-16e-instruct"
    else:
        messages = messages + [{"role": "user", "content": user_message}]
        model = "llama-3.3-70b-versatile"

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}] + messages,
            max_tokens=1500,
            temperature=0.75
        )
        reply = response.choices[0].message.content
        save_chat(user_message or "[image]", reply)
        # Auto extract memory
        if user_message:
            try: extract_and_save_memory(user_message, reply)
            except: pass
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/history", methods=["GET"])
def history():
    conn = get_db()
    rows = conn.execute('SELECT user, assistant, timestamp FROM chats ORDER BY timestamp DESC LIMIT 50').fetchall()
    conn.close()
    return jsonify({"history": [{"user": r[0], "assistant": r[1], "time": r[2]} for r in rows]})

@app.route("/memory", methods=["GET", "POST", "DELETE"])
def memory():
    if request.method == "GET":
        return jsonify(get_memories())
    elif request.method == "POST":
        d = request.get_json()
        save_memory(d.get("key",""), d.get("value",""))
        return jsonify({"ok": True})
    elif request.method == "DELETE":
        key = request.args.get("key")
        conn = get_db()
        if key:
            conn.execute('DELETE FROM memory WHERE key=?', (key,))
        else:
            conn.execute('DELETE FROM memory')
        conn.commit(); conn.close()
        return jsonify({"ok": True})

@app.route("/tasks", methods=["GET", "POST", "PUT", "DELETE"])
def tasks():
    conn = get_db()
    if request.method == "GET":
        rows = conn.execute('SELECT * FROM tasks ORDER BY created DESC').fetchall()
        conn.close()
        cols = ['id','title','detail','status','due','created']
        return jsonify({"tasks": [dict(zip(cols,r)) for r in rows]})
    elif request.method == "POST":
        d = request.get_json()
        conn.execute('INSERT INTO tasks (title, detail, due) VALUES (?,?,?)',
                     (d.get("title",""), d.get("detail",""), d.get("due","")))
        conn.commit(); conn.close()
        return jsonify({"ok": True})
    elif request.method == "PUT":
        d = request.get_json()
        conn.execute('UPDATE tasks SET status=? WHERE id=?', (d.get("status","done"), d.get("id")))
        conn.commit(); conn.close()
        return jsonify({"ok": True})
    elif request.method == "DELETE":
        tid = request.args.get("id")
        conn.execute('DELETE FROM tasks WHERE id=?', (tid,))
        conn.commit(); conn.close()
        return jsonify({"ok": True})

@app.route("/search", methods=["POST"])
def search():
    q = request.get_json().get("query","").strip()
    if not q: return jsonify({"error": "No query"}), 400
    results = web_search(q, 8)
    if not results:
        return jsonify({"results": [], "query": q, "source": "none"})
    lines = [l for l in results.split("\n") if l.strip()]
    out = []
    for l in lines[:6]:
        parts = l.split(" — ", 1)
        out.append({"title": parts[0][:80], "snippet": parts[1][:200] if len(parts)>1 else "", "url": ""})
    return jsonify({"results": out, "query": q})

@app.route("/weather", methods=["POST"])
def weather():
    city = request.get_json().get("city","").strip()
    if not city or not WEATHER_KEY:
        return jsonify({"error": "No city or key"}), 400
    try:
        r = requests.get(f"https://api.openweathermap.org/data/2.5/weather",
            params={"q": city, "appid": WEATHER_KEY, "units": "metric", "lang": "en"}, timeout=6)
        d = r.json()
        if d.get("cod") != 200:
            return jsonify({"error": d.get("message","City not found")}), 404
        return jsonify({
            "city": d["name"], "country": d["sys"]["country"],
            "temp": round(d["main"]["temp"]),
            "feels": round(d["main"]["feels_like"]),
            "humidity": d["main"]["humidity"],
            "desc": d["weather"][0]["description"].title(),
            "icon": d["weather"][0]["icon"],
            "wind": round(d["wind"]["speed"] * 3.6),
            "min": round(d["main"]["temp_min"]),
            "max": round(d["main"]["temp_max"])
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/news", methods=["POST"])
def news():
    cat = request.get_json().get("category", "general")
    if not NEWS_KEY: return jsonify({"error": "No key"}), 400
    try:
        r = requests.get("https://newsapi.org/v2/top-headlines",
            params={"country": "in", "category": cat, "pageSize": 8, "apiKey": NEWS_KEY}, timeout=6)
        articles = r.json().get("articles", [])
        return jsonify({"articles": [
            {"title": a.get("title",""), "description": a.get("description",""),
             "url": a.get("url",""), "source": a.get("source",{}).get("name",""),
             "image": a.get("urlToImage","")} for a in articles if a.get("title")
        ][:6]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/imagine", methods=["POST"])
def imagine():
    prompt = request.get_json().get("prompt","")
    TOGETHER_KEY = os.environ.get("TOGETHER_API_KEY","")
    STABILITY_KEY = os.environ.get("STABILITY_API_KEY","")
    enhanced = f"highly detailed, cinematic, 4k, professional: {prompt}"
    if TOGETHER_KEY:
        try:
            r = requests.post("https://api.together.xyz/v1/images/generations",
                json={"model": "black-forest-labs/FLUX.1-schnell-Free", "prompt": enhanced,
                      "width": 768, "height": 768, "steps": 4, "n": 1},
                headers={"Authorization": f"Bearer {TOGETHER_KEY}"}, timeout=30)
            url = r.json()["data"][0]["url"]
            return jsonify({"url": url})
        except: pass
    if STABILITY_KEY:
        try:
            r = requests.post("https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image",
                headers={"Authorization": f"Bearer {STABILITY_KEY}", "Content-Type": "application/json"},
                json={"text_prompts": [{"text": enhanced, "weight": 1}],
                      "cfg_scale": 7, "height": 1024, "width": 1024, "samples": 1, "steps": 30},
                timeout=30)
            b64 = r.json()["artifacts"][0]["base64"]
            return jsonify({"base64": b64})
        except: pass
    return jsonify({"error": "No image API configured"}), 500

@app.route("/readfile", methods=["POST"])
def readfile():
    """Read and analyze uploaded files"""
    if 'file' not in request.files:
        return jsonify({"error": "No file"}), 400
    f = request.files['file']
    fname = f.filename.lower()
    question = request.form.get("question", "Analyze this file and give me key insights.")

    content = ""
    try:
        if fname.endswith('.pdf'):
            import io
            try:
                import PyPDF2
                reader = PyPDF2.PdfReader(io.BytesIO(f.read()))
                content = "\n".join([p.extract_text() or "" for p in reader.pages[:10]])
            except:
                content = "[PDF reading requires PyPDF2]"
        elif fname.endswith(('.xlsx', '.xls', '.csv')):
            try:
                import pandas as pd, io
                if fname.endswith('.csv'):
                    df = pd.read_csv(io.BytesIO(f.read()))
                else:
                    df = pd.read_excel(io.BytesIO(f.read()))
                content = f"Columns: {list(df.columns)}\nRows: {len(df)}\nSample:\n{df.head(10).to_string()}"
            except:
                content = f.read().decode('utf-8', errors='ignore')[:3000]
        elif fname.endswith(('.py', '.js', '.ts', '.html', '.css', '.json', '.txt', '.md', '.java', '.cpp', '.c')):
            content = f.read().decode('utf-8', errors='ignore')[:5000]
        elif fname.endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
            # Image analysis via vision
            img_data = base64.b64encode(f.read()).decode()
            ext = fname.split('.')[-1]
            mime = f"image/{'jpeg' if ext in ['jpg','jpeg'] else ext}"
            response = client.chat.completions.create(
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": f"Boss ne yeh image share ki hai. {question} Detailed Hinglish mein batao."},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_data}"}}
                ]}],
                max_tokens=800
            )
            return jsonify({"reply": response.choices[0].message.content, "type": "image"})
        else:
            content = f.read().decode('utf-8', errors='ignore')[:3000]

        if not content.strip():
            return jsonify({"error": "Could not read file"}), 400

        # Analyze with MARIA
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": MARIA_SYSTEM + f"\n\nCurrent time: {get_time_info()}"},
                {"role": "user", "content": f"Boss ne yeh file share ki hai:\n\nFilename: {f.filename}\nContent:\n{content[:4000]}\n\nQuestion: {question}\n\nDetailed analysis do Hinglish mein."}
            ],
            max_tokens=1200
        )
        return jsonify({"reply": response.choices[0].message.content, "type": "file"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/clear", methods=["POST"])
def clear():
    conn = get_db()
    conn.execute('DELETE FROM chats')
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "alive", "time": get_time_info()})

@app.route("/manifest.json")
def manifest():
    return jsonify({
        "name": "M.A.R.I.A", "short_name": "MARIA",
        "description": "Most Advanced Responsive Intelligent Assistant",
        "start_url": "/", "display": "standalone",
        "background_color": "#000000", "theme_color": "#00e5ff",
        "orientation": "portrait-primary",
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"}
        ]
    })

@app.route("/sw.js")
def sw():
    from flask import Response
    code = """
const C='maria-v2';
self.addEventListener('install',e=>{self.skipWaiting();});
self.addEventListener('activate',e=>{
  e.waitUntil(caches.keys().then(k=>Promise.all(k.filter(x=>x!==C).map(x=>caches.delete(x)))));
  self.clients.claim();
});
self.addEventListener('fetch',e=>{
  if(e.request.method!=='GET')return;
  e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)));
});
"""
    return Response(code, mimetype='application/javascript')

# Keep alive
def keep_alive():
    url = os.environ.get("RENDER_EXTERNAL_URL","")
    if not url: return
    while True:
        try: urllib.request.urlopen(url+"/ping")
        except: pass
        time.sleep(840)

t = threading.Thread(target=keep_alive, daemon=True)
t.start()

if __name__ == "__main__":
    app.run(debug=False)
