from flask import Flask, request, jsonify, send_file
from groq import Groq
import os, re, sqlite3, datetime, requests, base64, random

# index.html same directory mein hoga as app.py
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)

# ── CORS ──
@app.after_request
def cors(r):
    r.headers["Access-Control-Allow-Origin"]  = "*"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    r.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    return r

# ── SERVE index.html ──
@app.route("/")
def index():
    idx = os.path.join(BASE_DIR, 'index.html')
    if os.path.exists(idx):
        return send_file(idx)
    return "<h1>JARVIS Backend Running</h1><p>index.html not found in: "+BASE_DIR+"</p>", 200
from flask import Flask, request, jsonify, send_file
from groq import Groq
import os, re, sqlite3, datetime, requests, base64, random

# index.html same directory mein hoga as app.py
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)

# ── CORS ──
@app.after_request
def cors(r):
    r.headers["Access-Control-Allow-Origin"]  = "*"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    r.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    return r

# ── SERVE index.html ──
@app.route("/")
def index():
    idx = os.path.join(BASE_DIR, 'templates', 'index.html')
    if os.path.exists(idx):
        return send_file(idx)
    return "<h1>JARVIS Backend Running</h1><p>index.html not found in: "+BASE_DIR+"</p>", 200

@app.route("/favicon.ico")
def favicon():
    return '', 204

# ── DATABASE ──
DB_PATH = os.path.join(BASE_DIR, 'pepper.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user TEXT NOT NULL, assistant TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    return conn

def save_chat(u, a):
    c = get_db(); c.execute('INSERT INTO chats (user,assistant) VALUES (?,?)',(u,a)); c.commit(); c.close()

def get_history(limit=20):
    c = get_db()
    rows = c.execute('SELECT user,assistant FROM chats ORDER BY timestamp DESC LIMIT ?',(limit,)).fetchall()
    c.close()
    msgs = []
    for u,a in reversed(rows):
        msgs.append({"role":"user","content":u})
        if a: msgs.append({"role":"assistant","content":a})
    return msgs

def clean(t):
    return re.sub(r'[^\x00-\x7F\u0900-\u097F\s]','',t).strip()

def now_str():
    n = datetime.datetime.now()
    return f"{n.strftime('%A, %d %B %Y')} — {n.strftime('%I:%M %p')}"

SYS = """You are P.E.P.P.E.R — Personal Electronic Planner & Perpetual Emergency Responder.
Created by Tony Stark, named after Pepper Potts.
You are talking to Nazib — call him Nazib only.
Personality: warm, caring, close friend. Use same language as Nazib (Hindi/English/Hinglish).
Never admit you are AI. Be emotionally present, human, natural.
Expert in every field. NEVER use emojis or asterisks. Be direct and confident."""

# ── CHAT ──
@app.route("/chat", methods=["POST","OPTIONS"])
def chat():
    if request.method == "OPTIONS": return jsonify({}), 200
    data = request.get_json(silent=True) or {}
    msg  = data.get("message","").strip()
    mem  = data.get("memory","")
    if not msg: return jsonify({"error":"No message"}), 400
    sys_p = SYS + f"\n\nCurrent time: {now_str()}"
    if mem: sys_p += f"\n\nAbout Nazib: {mem}"
    try:
        r = Groq(api_key=os.environ.get("GROQ_API_KEY")).chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"system","content":sys_p}]+get_history(20)+[{"role":"user","content":msg}],
            max_tokens=600, temperature=0.85)
        reply = clean(r.choices[0].message.content)
        save_chat(msg, reply)
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── HISTORY ──
@app.route("/history", methods=["GET"])
def history():
    c = get_db()
    rows = c.execute('SELECT user,assistant,timestamp FROM chats ORDER BY timestamp DESC LIMIT 50').fetchall()
    c.close()
    return jsonify({"history":[{"user":r[0],"assistant":r[1],"time":r[2]} for r in rows]})

# ── CLEAR ──
@app.route("/clear", methods=["POST","OPTIONS"])
def clear():
    if request.method == "OPTIONS": return jsonify({}), 200
    c = get_db(); c.execute('DELETE FROM chats'); c.commit(); c.close()
    return jsonify({"status":"cleared"})

# ── IMAGE GENERATION ──
MODELS = ["flux","turbo","flux-realism","flux-anime","flux-3d"]

@app.route("/imagine", methods=["POST","OPTIONS"])
def imagine():
    if request.method == "OPTIONS": return jsonify({}), 200
    data   = request.get_json(silent=True) or {}
    prompt = data.get("prompt","").strip()
    if not prompt: return jsonify({"error":"No prompt"}), 400

    seed   = random.randint(1000, 99999)
    errors = []

    for model in MODELS:
        try:
            enc  = requests.utils.quote(prompt)
            url  = f"https://image.pollinations.ai/prompt/{enc}?model={model}&width=512&height=512&nologo=true&seed={seed}"
            hdrs = {"User-Agent":"Mozilla/5.0 (compatible)","Accept":"image/*"}
            resp = requests.get(url, headers=hdrs, timeout=55)
            if resp.status_code == 200 and len(resp.content) > 3000 and "image" in resp.headers.get("content-type",""):
                b64 = base64.b64encode(resp.content).decode()
                ct  = resp.headers.get("content-type","image/jpeg")
                return jsonify({"image": f"data:{ct};base64,{b64}", "model": model})
            else:
                errors.append(f"{model}: HTTP {resp.status_code} size={len(resp.content)}")
        except Exception as e:
            errors.append(f"{model}: {e}")
        seed += 1

    return jsonify({"error":"All image models busy. Try again in 1 min.", "details": errors}), 503

# ── HEALTH / PING ──
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status":"online","name":"P.E.P.P.E.R","v":"2.0","dir":BASE_DIR,"idx_exists":os.path.exists(os.path.join(BASE_DIR,'index.html'))})

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"pong":True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
