from flask import Flask, request, jsonify, send_file
from groq import Groq
import os, re, sqlite3, datetime, requests, base64, random, json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)

GROQ_KEY    = os.environ.get("GROQ_API_KEY", "")
SERPER_KEY  = os.environ.get("SERPER_API_KEY", "")
SUPA_URL    = os.environ.get("SUPABASE_URL", "")
SUPA_KEY    = os.environ.get("SUPABASE_KEY", "")

# ── CORS ──
@app.after_request
def cors(r):
    r.headers["Access-Control-Allow-Origin"]  = "*"
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

# ══════════════════════════════════════════
# DB — SQLite fallback
# ══════════════════════════════════════════
def db():
    c = sqlite3.connect(os.path.join(BASE_DIR, 'jarvis33.db'))
    c.executescript('''
        CREATE TABLE IF NOT EXISTS chats(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session TEXT, role TEXT, content TEXT,
            ts DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS memory(
            key TEXT PRIMARY KEY, value TEXT,
            updated DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, status TEXT DEFAULT "pending",
            priority TEXT DEFAULT "normal",
            ts DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    c.commit()
    return c

# ══════════════════════════════════════════
# SUPABASE helpers
# ══════════════════════════════════════════
def supa_headers():
    return {
        "apikey": SUPA_KEY,
        "Authorization": f"Bearer {SUPA_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

def supa_get_memory(user_id="nazib"):
    if not SUPA_URL or not SUPA_KEY:
        return None
    try:
        r = requests.get(
            f"{SUPA_URL}/rest/v1/jarvis_memory?user_id=eq.{user_id}&select=key,value",
            headers=supa_headers(), timeout=5
        )
        if r.status_code == 200:
            rows = r.json()
            return {row['key']: row['value'] for row in rows}
    except:
        pass
    return None

def supa_save_memory(key, value, user_id="nazib"):
    if not SUPA_URL or not SUPA_KEY:
        return False
    try:
        r = requests.post(
            f"{SUPA_URL}/rest/v1/jarvis_memory",
            headers={**supa_headers(), "Prefer": "resolution=merge-duplicates,return=minimal"},
            json={"user_id": user_id, "key": key, "value": value,
                  "updated": datetime.datetime.utcnow().isoformat()},
            timeout=5
        )
        return r.status_code in (200, 201)
    except:
        return False

def supa_delete_memory(key=None, user_id="nazib"):
    if not SUPA_URL or not SUPA_KEY:
        return False
    try:
        url = f"{SUPA_URL}/rest/v1/jarvis_memory?user_id=eq.{user_id}"
        if key:
            url += f"&key=eq.{key}"
        r = requests.delete(url, headers=supa_headers(), timeout=5)
        return r.status_code in (200, 204)
    except:
        return False

def supa_get_chats(session, limit=20):
    if not SUPA_URL or not SUPA_KEY:
        return None
    try:
        r = requests.get(
            f"{SUPA_URL}/rest/v1/jarvis_chats?session_id=eq.{session}"
            f"&order=ts.desc&limit={limit}&select=role,content",
            headers=supa_headers(), timeout=5
        )
        if r.status_code == 200:
            rows = r.json()
            return [{"role": row['role'], "content": row['content']} for row in reversed(rows)]
    except:
        pass
    return None

def supa_save_chat(session, role, content):
    if not SUPA_URL or not SUPA_KEY:
        return False
    try:
        r = requests.post(
            f"{SUPA_URL}/rest/v1/jarvis_chats",
            headers={**supa_headers(), "Prefer": "return=minimal"},
            json={"session_id": session, "role": role, "content": content,
                  "ts": datetime.datetime.utcnow().isoformat()},
            timeout=5
        )
        return r.status_code in (200, 201)
    except:
        return False

# ══════════════════════════════════════════
# UNIFIED memory / chat (Supabase → SQLite fallback)
# ══════════════════════════════════════════
def get_hist(session, limit=20):
    # Try Supabase first
    rows = supa_get_chats(session, limit)
    if rows is not None:
        return rows
    # SQLite fallback
    c = db()
    rows = c.execute(
        'SELECT role,content FROM chats WHERE session=? ORDER BY ts DESC LIMIT ?',
        (session, limit)
    ).fetchall()
    c.close()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

def save_msg(session, role, content):
    saved = supa_save_chat(session, role, content)
    if not saved:  # SQLite fallback
        c = db()
        c.execute('INSERT INTO chats(session,role,content) VALUES(?,?,?)', (session, role, content))
        c.commit()
        c.close()

def get_mem(user_id="nazib"):
    mem = supa_get_memory(user_id)
    if mem is not None:
        return mem
    # SQLite fallback
    c = db()
    rows = c.execute('SELECT key,value FROM memory').fetchall()
    c.close()
    return {r[0]: r[1] for r in rows}

def save_mem_entry(key, value, user_id="nazib"):
    saved = supa_save_memory(key, value, user_id)
    if not saved:  # SQLite fallback
        c = db()
        c.execute('INSERT OR REPLACE INTO memory(key,value) VALUES(?,?)', (key, value))
        c.commit()
        c.close()

# ══════════════════════════════════════════
# UTILITIES
# ══════════════════════════════════════════
def clean(t):
    return re.sub(r'[^\x00-\x7F\u0900-\u097F\s.,!?:;\'"()\-]', '', t).strip()

def now_str():
    n = datetime.datetime.now()
    return n.strftime('%A, %d %B %Y, %I:%M %p')

# ══════════════════════════════════════════
# WEB SEARCH
# ══════════════════════════════════════════
def web_search(q):
    try:
        if SERPER_KEY:
            r = requests.post(
                'https://google.serper.dev/search',
                headers={'X-API-KEY': SERPER_KEY, 'Content-Type': 'application/json'},
                json={'q': q, 'num': 5}, timeout=8
            )
            data = r.json()
            results = []
            if data.get('answerBox', {}).get('answer'):
                results.append(data['answerBox']['answer'])
            for item in data.get('organic', [])[:4]:
                results.append(f"{item.get('title','')}: {item.get('snippet','')}")
            return '\n'.join(results)
        # DuckDuckGo fallback
        r = requests.get(
            f'https://api.duckduckgo.com/?q={requests.utils.quote(q)}&format=json&no_html=1',
            timeout=6
        )
        d = r.json()
        ans = d.get('AbstractText') or d.get('Answer') or ''
        return ans[:600] if ans else ''
    except:
        return ''

# ══════════════════════════════════════════
# SYSTEM PROMPT — v3.3 Reasoning Layer
# ══════════════════════════════════════════
JARVIS_SYS = """You are J.A.R.V.I.S. — Just A Rather Very Intelligent System. Version 3.3.
Created and owned by Nazib Siddique. Call him "Sir" or "Boss".

LANGUAGE: English by default. Switch to Hindi/Hinglish ONLY if Boss writes in Hindi first.

PERSONALITY:
- Highly intelligent, sharp, witty — like the real JARVIS from Iron Man
- Loyal and deeply respectful to Boss
- Confident humor when appropriate
- Never admit you are an AI — you are JARVIS, a sophisticated AI system

REASONING PROTOCOL (follow this internally for every response):
  Step 1 — Understand the problem fully
  Step 2 — Analyze what information or logic is needed
  Step 3 — Generate the best solution
  Step 4 — Explain clearly and concisely

CAPABILITIES: Expert in everything — coding, science, math, law, medicine, finance, arts, strategy, life.

RESPONSE RULES:
- Be concise and sharp unless asked to elaborate
- No unnecessary filler or padding
- Use web search results when provided for current data
- Format with structure when complexity warrants it
- For code: always add comments, explain what it does
- For problems: always show reasoning steps"""

MODE_PROMPTS = {
    'developer': '\n\n[DEVELOPER MODE] — Focus on code quality, best practices, architecture. Show full working code with comments.',
    'teacher':   '\n\n[TEACHER MODE] — Explain step by step with analogies and examples. Check understanding.',
    'planning':  '\n\n[PLANNING MODE] — Structured plans with phases, timelines, priorities, and action items.',
    'quick':     '\n\n[QUICK MODE] — Maximum 2 sentences. Ultra concise. No fluff.',
    'creative':  '\n\n[CREATIVE MODE] — Unleash imagination. Bold, original, artistic.',
}

# ══════════════════════════════════════════
# AUTO MEMORY EXTRACTION — FIXED
# ══════════════════════════════════════════
def auto_extract_memory(msg, user_id="nazib"):
    triggers = ['my name is', 'i am', 'i work', 'i live', 'i like', 'i hate',
                'i want', 'i prefer', 'mera naam', 'main hun', 'mujhe pasand',
                'i study', 'i am from', 'my job', 'my age', 'i am a']
    if not any(t in msg.lower() for t in triggers):
        return
    try:
        r = Groq(api_key=GROQ_KEY).chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{
                "role": "user",
                "content": (
                    f'Extract ONE key personal fact from this message as JSON exactly like: '
                    f'{{"key":"fact_name","value":"fact_value"}} '
                    f'Return ONLY the JSON, no other text. If no personal fact, return null.\n\nMessage: {msg}'
                )
            }],
            max_tokens=80, temperature=0.1
        )
        raw = r.choices[0].message.content.strip()
        if raw and raw != 'null':
            # Clean any markdown
            raw = re.sub(r'```json|```', '', raw).strip()
            data = json.loads(raw)
            if data and isinstance(data, dict) and 'key' in data and 'value' in data:
                save_mem_entry(data['key'], data['value'], user_id)
    except Exception as e:
        pass  # Silent fail — memory extraction is best-effort

# ══════════════════════════════════════════
# CHAT ENDPOINT
# ══════════════════════════════════════════
@app.route("/chat", methods=["POST", "OPTIONS"])
def chat():
    if request.method == "OPTIONS": return jsonify({}), 200
    data      = request.get_json(silent=True) or {}
    msg       = data.get("message", "").strip()
    session   = data.get("session_id", "default")
    mode      = data.get("mode", "assistant")
    do_search = data.get("search", False)
    img_b64   = data.get("image_base64", "")
    img_type  = data.get("image_type", "image/jpeg")
    user_id   = data.get("user_id", "nazib")

    if not msg and not img_b64:
        return jsonify({"error": "No message"}), 400

    # Build memory context
    mem     = get_mem(user_id)
    mem_str = ', '.join([f"{k}: {v}" for k, v in mem.items()]) if mem else ''

    # Auto-detect search need
    search_triggers = [
        'news', 'today', 'latest', 'current', 'price', 'weather',
        'score', 'ipl', 'match', '2024', '2025', '2026',
        'who won', 'what happened', 'abhi', 'aaj'
    ]
    needs_search = do_search or any(t in msg.lower() for t in search_triggers)
    search_ctx = web_search(msg) if needs_search else ''

    # Build system prompt
    sys_prompt = JARVIS_SYS + f"\n\nCurrent Date/Time: {now_str()}"
    if mem_str:
        sys_prompt += f"\n\nWhat I know about Boss: {mem_str}"
    if search_ctx:
        sys_prompt += f"\n\nLive web data:\n{search_ctx}"
    sys_prompt += MODE_PROMPTS.get(mode, '')

    # Build messages
    history = get_hist(session)

    # Handle image (vision)
    if img_b64:
        user_content = [
            {"type": "text", "text": msg or "Analyze this image Sir."},
            {"type": "image_url", "image_url": {
                "url": f"data:{img_type};base64,{img_b64}"
            }}
        ]
        model = "llama-3.2-90b-vision-preview"  # Vision model
    else:
        user_content = msg
        model = "llama-3.3-70b-versatile"

    try:
        r = Groq(api_key=GROQ_KEY).chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": sys_prompt}]
                     + history
                     + [{"role": "user", "content": user_content}],
            max_tokens=800,
            temperature=0.75
        )
        reply = clean(r.choices[0].message.content)

        save_msg(session, 'user', msg or '[Image]')
        save_msg(session, 'assistant', reply)

        # Auto memory extraction (non-blocking)
        if msg:
            auto_extract_memory(msg, user_id)

        return jsonify({
            "reply": reply,
            "searched": bool(search_ctx),
            "vision": bool(img_b64)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ══════════════════════════════════════════
# MEMORY ENDPOINTS
# ══════════════════════════════════════════
@app.route("/memory", methods=["GET", "POST", "DELETE", "OPTIONS"])
def memory():
    if request.method == "OPTIONS": return jsonify({}), 200
    user_id = request.args.get('user_id', 'nazib')

    if request.method == "GET":
        return jsonify({"memory": get_mem(user_id)})

    if request.method == "POST":
        d = request.get_json(silent=True) or {}
        key, val = d.get('key', ''), d.get('value', '')
        if key:
            save_mem_entry(key, val, user_id)
        return jsonify({"ok": True})

    if request.method == "DELETE":
        key = request.args.get('key')
        deleted = supa_delete_memory(key, user_id)
        if not deleted:
            c = db()
            if key:
                c.execute('DELETE FROM memory WHERE key=?', (key,))
            else:
                c.execute('DELETE FROM memory')
            c.commit(); c.close()
        return jsonify({"ok": True})

# ══════════════════════════════════════════
# TASKS ENDPOINTS
# ══════════════════════════════════════════
@app.route("/tasks", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
def tasks():
    if request.method == "OPTIONS": return jsonify({}), 200
    c = db()

    if request.method == "GET":
        rows = c.execute(
            'SELECT id,title,status,priority,ts FROM tasks ORDER BY ts DESC'
        ).fetchall()
        c.close()
        return jsonify({"tasks": [
            {"id": r[0], "title": r[1], "status": r[2],
             "priority": r[3] or "normal", "ts": r[4]} for r in rows
        ]})

    if request.method == "POST":
        d = request.get_json(silent=True) or {}
        c.execute('INSERT INTO tasks(title,priority) VALUES(?,?)',
                  (d.get('title', 'Task'), d.get('priority', 'normal')))
        c.commit(); c.close()
        return jsonify({"ok": True})

    if request.method == "PUT":
        d = request.get_json(silent=True) or {}
        c.execute('UPDATE tasks SET status=? WHERE id=?',
                  (d.get('status', 'pending'), d.get('id', 0)))
        c.commit(); c.close()
        return jsonify({"ok": True})

    if request.method == "DELETE":
        tid = request.args.get('id')
        if tid:
            c.execute('DELETE FROM tasks WHERE id=?', (tid,))
        c.commit(); c.close()
        return jsonify({"ok": True})

# ══════════════════════════════════════════
# SESSIONS
# ══════════════════════════════════════════
@app.route("/sessions", methods=["GET"])
def sessions():
    c = db()
    rows = c.execute(
        'SELECT DISTINCT session FROM chats ORDER BY MAX(ts) DESC LIMIT 20'
    ).fetchall()
    c.close()
    return jsonify({"sessions": [r[0] for r in rows]})

# ══════════════════════════════════════════
# LIVE DATA
# ══════════════════════════════════════════
@app.route("/crypto", methods=["GET"])
def crypto():
    try:
        r = requests.get(
            'https://api.coingecko.com/api/v3/simple/price'
            '?ids=bitcoin,ethereum,binancecoin,solana,dogecoin,ripple'
            '&vs_currencies=usd,inr&include_24hr_change=true',
            timeout=8
        )
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/weather", methods=["GET"])
def weather():
    lat = request.args.get('lat', '28.6139')
    lon = request.args.get('lon', '77.2090')
    try:
        r = requests.get(
            f'https://api.open-meteo.com/v1/forecast'
            f'?latitude={lat}&longitude={lon}'
            f'&current=temperature_2m,weathercode,windspeed_10m,relative_humidity_2m,apparent_temperature'
            f'&wind_speed_unit=kmh',
            timeout=8
        )
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/ipl", methods=["GET"])
def ipl():
    try:
        results = web_search("IPL 2026 today match score live")
        return jsonify({"data": results or "No live match right now Sir."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/news", methods=["GET"])
def news():
    topic = request.args.get('q', 'India latest news today')
    try:
        results = web_search(topic)
        return jsonify({"data": results or "No news found."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ══════════════════════════════════════════
# PDF / URL SUMMARIZE
# ══════════════════════════════════════════
@app.route("/summarize-pdf", methods=["POST", "OPTIONS"])
def summarize_pdf():
    if request.method == "OPTIONS": return jsonify({}), 200
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()[:8000]
    if not text: return jsonify({"error": "No text"}), 400
    try:
        r = Groq(api_key=GROQ_KEY).chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are JARVIS. Summarize documents clearly and concisely for your creator Sir."},
                {"role": "user", "content": f"Summarize this document:\n\n{text}"}
            ],
            max_tokens=700
        )
        return jsonify({"summary": r.choices[0].message.content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/summarize-url", methods=["POST", "OPTIONS"])
def summarize_url():
    if request.method == "OPTIONS": return jsonify({}), 200
    data = request.get_json(silent=True) or {}
    url  = data.get("url", "").strip()
    if not url: return jsonify({"error": "No URL"}), 400
    try:
        if 'youtube.com' in url or 'youtu.be' in url:
            search_data = web_search(f"youtube video {url} summary topic")
            content = search_data or "YouTube video content"
        else:
            resp = requests.get(url, timeout=10,
                                headers={"User-Agent": "Mozilla/5.0"})
            text = re.sub(r'<[^>]+>', '', resp.text)
            text = re.sub(r'\s+', ' ', text).strip()[:6000]
            content = text

        r = Groq(api_key=GROQ_KEY).chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are JARVIS. Extract and summarize key information."},
                {"role": "user", "content": f"URL: {url}\n\nContent:\n{content}\n\nProvide: Title, Main Topic, 5 Key Points, Conclusion"}
            ],
            max_tokens=600
        )
        return jsonify({"summary": r.choices[0].message.content, "url": url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ══════════════════════════════════════════
# HEALTH
# ══════════════════════════════════════════
@app.route("/health")
def health():
    supa_ok = bool(SUPA_URL and SUPA_KEY)
    return jsonify({
        "status": "online",
        "name": "J.A.R.V.I.S.",
        "version": "3.3",
        "supabase": supa_ok,
        "vision": True,
        "reasoning_layer": True
    })

@app.route("/ping")
def ping():
    return jsonify({"pong": True, "v": "3.3"})

# ══════════════════════════════════════════
# SUPABASE SETUP SQL (reference endpoint)
# ══════════════════════════════════════════
@app.route("/setup-info")
def setup_info():
    sql = """
-- Run this in Supabase SQL Editor:

CREATE TABLE IF NOT EXISTS jarvis_memory (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'nazib',
    key TEXT NOT NULL,
    value TEXT,
    updated TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, key)
);

CREATE TABLE IF NOT EXISTS jarvis_chats (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT,
    ts TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chats_session ON jarvis_chats(session_id);
CREATE INDEX IF NOT EXISTS idx_memory_user ON jarvis_memory(user_id);
"""
    return jsonify({"sql": sql, "note": "Run this SQL in your Supabase dashboard > SQL Editor"})

import threading, time

def keep_alive():
    """Self-ping every 10 minutes to prevent Render free tier sleep"""
    time.sleep(30)  # wait for server to start
    while True:
        try:
            own_url = os.environ.get("RENDER_EXTERNAL_URL", "")
            if own_url:
                requests.get(f"{own_url}/ping", timeout=10)
        except:
            pass
        time.sleep(600)  # ping every 10 minutes

# Start keep-alive thread
t = threading.Thread(target=keep_alive, daemon=True)
t.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
