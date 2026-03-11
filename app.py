from flask import Flask, request, jsonify, send_from_directory
from groq import Groq
import os, re, sqlite3, datetime, requests, base64, random

app = Flask(__name__, static_folder='.', static_url_path='')

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# ── CORS ──
@app.after_request
def cors(r):
    r.headers["Access-Control-Allow-Origin"]  = "*"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type"
    r.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    return r

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve(path):
    if path and os.path.exists(path):
        return send_from_directory('.', path)
    return send_from_directory('.', 'index.html')

# ── DATABASE ──
def get_db():
    conn = sqlite3.connect('pepper.db')
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
    sys = SYS + f"\n\nCurrent time: {now_str()}"
    if mem: sys += f"\n\nAbout Nazib: {mem}"
    try:
        r = Groq(api_key=os.environ.get("GROQ_API_KEY")).chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"system","content":sys}]+get_history(20)+[{"role":"user","content":msg}],
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

# ── IMAGE GENERATION — SERVER SIDE FETCH (NO CORS PROBLEM) ──
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
            enc = requests.utils.quote(prompt)
            url = f"https://image.pollinations.ai/prompt/{enc}?model={model}&width=512&height=512&nologo=true&seed={seed}&enhance=true"
            hdrs = {"User-Agent":"Mozilla/5.0","Accept":"image/*,*/*"}
            resp = requests.get(url, headers=hdrs, timeout=55)

            if resp.status_code == 200 and len(resp.content) > 3000:
                ct = resp.headers.get("content-type","image/jpeg")
                if "image" in ct:
                    b64 = base64.b64encode(resp.content).decode()
                    return jsonify({"image": f"data:{ct};base64,{b64}", "model": model})
                else:
                    errors.append(f"{model}: wrong content-type {ct}")
            else:
                errors.append(f"{model}: HTTP {resp.status_code}, size {len(resp.content)}")
        except Exception as e:
            errors.append(f"{model}: {e}")
        seed += 1

    return jsonify({"error":"Image gen failed — all models busy. Try again in 1 min.", "details": errors}), 503

# ── HEALTH ──
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status":"online","name":"P.E.P.P.E.R","version":"2.0"})

# ── PING (keep-alive) ──
@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"pong": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
