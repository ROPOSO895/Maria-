from flask import Flask, request, jsonify, send_file
from groq import Groq
import os, re, sqlite3, datetime, requests, base64, random, json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
SERPER_KEY = os.environ.get("SERPER_API_KEY", "")

@app.after_request
def cors(r):
    r.headers["Access-Control-Allow-Origin"] = "*"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type"
    r.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    return r

@app.route("/")
def index():
    p = os.path.join(BASE_DIR, 'templates', 'index.html')
    if not os.path.exists(p):
        p = os.path.join(BASE_DIR, 'index.html')
    return send_file(p)

@app.route("/favicon.ico")
def fav(): return '', 204

# ── DB ──
def db():
    c = sqlite3.connect(os.path.join(BASE_DIR, 'jarvis3.db'))
    c.executescript('''
        CREATE TABLE IF NOT EXISTS chats(id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT, role TEXT, content TEXT, ts DATETIME DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS memory(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, status TEXT DEFAULT "pending", ts DATETIME DEFAULT CURRENT_TIMESTAMP);
    ''')
    c.commit()
    return c

def get_hist(session, limit=20):
    c = db()
    rows = c.execute('SELECT role,content FROM chats WHERE session=? ORDER BY ts DESC LIMIT ?',(session,limit)).fetchall()
    c.close()
    return [{"role":r[0],"content":r[1]} for r in reversed(rows)]

def save_msg(session, role, content):
    c = db(); c.execute('INSERT INTO chats(session,role,content) VALUES(?,?,?)',(session,role,content)); c.commit(); c.close()

def get_mem():
    c = db(); rows = c.execute('SELECT key,value FROM memory').fetchall(); c.close()
    return {r[0]:r[1] for r in rows}

def clean(t):
    return re.sub(r'[^\x00-\x7F\u0900-\u097F\s.,!?:;\'"()\-]','',t).strip()

def now_str():
    n = datetime.datetime.now()
    return n.strftime('%A, %d %B %Y, %I:%M %p')

# ── WEB SEARCH ──
def web_search(q):
    try:
        if SERPER_KEY:
            r = requests.post('https://google.serper.dev/search',
                headers={'X-API-KEY': SERPER_KEY, 'Content-Type':'application/json'},
                json={'q': q, 'num': 5}, timeout=8)
            data = r.json()
            results = []
            if data.get('answerBox', {}).get('answer'):
                results.append(data['answerBox']['answer'])
            for item in data.get('organic', [])[:4]:
                results.append(f"{item.get('title','')}: {item.get('snippet','')}")
            return '\n'.join(results)
        # Fallback: DuckDuckGo instant answer
        r = requests.get(f'https://api.duckduckgo.com/?q={requests.utils.quote(q)}&format=json&no_html=1', timeout=6)
        d = r.json()
        ans = d.get('AbstractText') or d.get('Answer') or ''
        return ans[:600] if ans else ''
    except:
        return ''

# ── SYSTEM PROMPT ──
JARVIS_SYS = """You are J.A.R.V.I.S. — Just A Rather Very Intelligent System.
Created by Nazib Siddique. You serve your creator — call him "Sir" or "Boss".

LANGUAGE RULE: Respond in English by default. Switch to Hindi/Hinglish ONLY if Boss writes in Hindi first.

PERSONALITY:
- Highly intelligent, witty, confident like the real JARVIS from Iron Man
- Loyal and respectful to Boss
- Sharp humor when appropriate
- Never say you are an AI — you are JARVIS

CAPABILITIES: Expert in everything — coding, science, math, law, medicine, finance, arts, life advice.

RULES:
- Keep responses concise and sharp unless asked to elaborate
- No unnecessary filler words
- If web search results are provided, use them to give accurate current info
- Format with clear structure when needed"""

@app.route("/chat", methods=["POST","OPTIONS"])
def chat():
    if request.method == "OPTIONS": return jsonify({}), 200
    data = request.get_json(silent=True) or {}
    msg     = data.get("message","").strip()
    session = data.get("session_id","default")
    mode    = data.get("mode","assistant")
    do_search = data.get("search", False)
    if not msg: return jsonify({"error":"No message"}), 400

    mem = get_mem()
    mem_str = ', '.join([f"{k}: {v}" for k,v in mem.items()]) if mem else ''

    # Auto-detect if web search needed
    search_triggers = ['news','today','latest','current','price','weather','score','ipl','match','2024','2025','2026','who won','what happened']
    needs_search = do_search or any(t in msg.lower() for t in search_triggers)

    search_ctx = ''
    if needs_search:
        search_ctx = web_search(msg)

    sys_prompt = JARVIS_SYS + f"\n\nDate/Time: {now_str()}"
    if mem_str: sys_prompt += f"\n\nWhat I know about Boss: {mem_str}"
    if search_ctx: sys_prompt += f"\n\nLive web data:\n{search_ctx}"

    # Mode prompts
    mode_map = {
        'developer': '\n\nYou are in DEVELOPER mode — focus on code, technical precision, best practices.',
        'teacher':   '\n\nYou are in TEACHER mode — explain step by step, use examples.',
        'planning':  '\n\nYou are in PLANNING mode — structured plans, bullet points, timelines.',
        'quick':     '\n\nQUICK mode — one or two sentences max. Ultra concise.'
    }
    sys_prompt += mode_map.get(mode, '')

    history = get_hist(session)
    try:
        r = Groq(api_key=GROQ_KEY).chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"system","content":sys_prompt}] + history + [{"role":"user","content":msg}],
            max_tokens=700, temperature=0.8)
        reply = clean(r.choices[0].message.content)
        save_msg(session, 'user', msg)
        save_msg(session, 'assistant', reply)

        # Auto memory extraction
        try:
            mem_check = ['my name is','i am','i work','i live','i like','i hate','i want','mera naam','main']
            if any(t in msg.lower() for t in mem_check):
                Groq(api_key=GROQ_KEY).chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[{"role":"user","content":f"Extract ONE key personal fact from this as JSON {{\"key\":\"...\",\"value\":\"...\"}} or return null:\n{msg}"}],
                    max_tokens=60)
        except: pass

        return jsonify({"reply": reply, "searched": bool(search_ctx)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── MEMORY ──
@app.route("/memory", methods=["GET","POST","DELETE","OPTIONS"])
def memory():
    if request.method == "OPTIONS": return jsonify({}), 200
    c = db()
    if request.method == "GET":
        rows = c.execute('SELECT key,value FROM memory').fetchall()
        c.close(); return jsonify({"memory":{r[0]:r[1] for r in rows}})
    if request.method == "POST":
        d = request.get_json(silent=True) or {}
        c.execute('INSERT OR REPLACE INTO memory(key,value) VALUES(?,?)',(d.get('key',''),d.get('value',''))); c.commit(); c.close()
        return jsonify({"ok":True})
    if request.method == "DELETE":
        key = request.args.get('key')
        if key: c.execute('DELETE FROM memory WHERE key=?',(key,))
        else: c.execute('DELETE FROM memory')
        c.commit(); c.close(); return jsonify({"ok":True})

# ── TASKS ──
@app.route("/tasks", methods=["GET","POST","PUT","DELETE","OPTIONS"])
def tasks():
    if request.method == "OPTIONS": return jsonify({}), 200
    c = db()
    if request.method == "GET":
        rows = c.execute('SELECT id,title,status,ts FROM tasks ORDER BY ts DESC').fetchall()
        c.close(); return jsonify({"tasks":[{"id":r[0],"title":r[1],"status":r[2],"ts":r[3]} for r in rows]})
    if request.method == "POST":
        d = request.get_json(silent=True) or {}
        c.execute('INSERT INTO tasks(title) VALUES(?)',(d.get('title','Task'),)); c.commit(); c.close()
        return jsonify({"ok":True})
    if request.method == "PUT":
        d = request.get_json(silent=True) or {}
        c.execute('UPDATE tasks SET status=? WHERE id=?',(d.get('status','pending'),d.get('id',0))); c.commit(); c.close()
        return jsonify({"ok":True})
    if request.method == "DELETE":
        tid = request.args.get('id')
        if tid: c.execute('DELETE FROM tasks WHERE id=?',(tid,))
        c.commit(); c.close(); return jsonify({"ok":True})

# ── SESSIONS ──
@app.route("/sessions", methods=["GET"])
def sessions():
    c = db()
    rows = c.execute('SELECT DISTINCT session FROM chats ORDER BY MAX(ts) DESC LIMIT 20').fetchall()
    c.close(); return jsonify({"sessions":[r[0] for r in rows]})

# ── CRYPTO (CoinGecko free) ──
@app.route("/crypto", methods=["GET"])
def crypto():
    try:
        r = requests.get('https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,binancecoin,solana,dogecoin&vs_currencies=usd,inr&include_24hr_change=true', timeout=8)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error":str(e)}), 500

# ── WEATHER (Open-Meteo, no key needed) ──
@app.route("/weather", methods=["GET"])
def weather():
    lat = request.args.get('lat','28.6139')
    lon = request.args.get('lon','77.2090')
    try:
        r = requests.get(f'https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,weathercode,windspeed_10m,relative_humidity_2m&wind_speed_unit=kmh', timeout=8)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error":str(e)}), 500

# ── IPL SCORES ──
@app.route("/ipl", methods=["GET"])
def ipl():
    try:
        results = web_search("IPL 2026 today match score live")
        return jsonify({"data": results or "No live match right now"})
    except Exception as e:
        return jsonify({"error":str(e)}), 500

# ── PDF SUMMARIZE ──
@app.route("/summarize-pdf", methods=["POST","OPTIONS"])
def summarize_pdf():
    if request.method == "OPTIONS": return jsonify({}), 200
    data = request.get_json(silent=True) or {}
    text = data.get("text","").strip()[:8000]
    if not text: return jsonify({"error":"No text"}), 400
    try:
        r = Groq(api_key=GROQ_KEY).chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"system","content":"You are JARVIS. Summarize documents clearly and concisely."},
                      {"role":"user","content":f"Summarize this document:\n\n{text}"}],
            max_tokens=600)
        return jsonify({"summary": r.choices[0].message.content})
    except Exception as e:
        return jsonify({"error":str(e)}), 500

# ── URL / YOUTUBE SUMMARIZE ──
@app.route("/summarize-url", methods=["POST","OPTIONS"])
def summarize_url():
    if request.method == "OPTIONS": return jsonify({}), 200
    data = request.get_json(silent=True) or {}
    url  = data.get("url","").strip()
    if not url: return jsonify({"error":"No URL"}), 400
    try:
        if 'youtube.com' in url or 'youtu.be' in url:
            vid_id = url.split('v=')[-1].split('&')[0].split('/')[-1]
            search_data = web_search(f"youtube video summary {vid_id} {url}")
            content = search_data or "YouTube video content"
        else:
            resp = requests.get(url, timeout=10, headers={"User-Agent":"Mozilla/5.0"})
            text = re.sub(r'<[^>]+>','',resp.text)
            text = re.sub(r'\s+',' ',text).strip()[:6000]
            content = text

        r = Groq(api_key=GROQ_KEY).chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"system","content":"You are JARVIS. Extract and summarize the key information from this content."},
                      {"role":"user","content":f"URL: {url}\n\nContent:\n{content}\n\nProvide: Title, Main Topic, 5 Key Points, Conclusion"}],
            max_tokens=500)
        return jsonify({"summary": r.choices[0].message.content, "url": url})
    except Exception as e:
        return jsonify({"error":str(e)}), 500

# ── HEALTH / PING ──
@app.route("/health")
def health():
    return jsonify({"status":"online","name":"JARVIS","version":"3.0"})

@app.route("/ping")
def ping():
    return jsonify({"pong":True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT",5000))
    app.run(host="0.0.0.0", port=port, debug=False)
