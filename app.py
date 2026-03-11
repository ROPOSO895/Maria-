from flask import Flask, request, jsonify, Response
from groq import Groq
import os, re, sqlite3, datetime, requests, threading, time, urllib.parse, base64

app = Flask(__name__)

@app.after_request
def cors(r):
    r.headers['Access-Control-Allow-Origin'] = '*'
    r.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,DELETE,OPTIONS'
    r.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return r

@app.route('/', defaults={'path': ''}, methods=['OPTIONS'])
@app.route('/<path:path>', methods=['OPTIONS'])
def options(path=''):
    return Response('', 200, {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type'
    })

# ENV
GROQ_KEY    = os.environ.get('GROQ_API_KEY', '')
TOGETHER    = os.environ.get('TOGETHER_API_KEY', '')
SERPER      = os.environ.get('SERPER_API_KEY', '')
BRAVE       = os.environ.get('BRAVE_SEARCH_KEY', '')
WEATHER_KEY = os.environ.get('WEATHER_API_KEY', '')

client = Groq(api_key=GROQ_KEY)
DB = 'jarvis.db'

# DATABASE
def get_db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = get_db()
    c.executescript('''
        CREATE TABLE IF NOT EXISTS chats(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT, content TEXT, session_id TEXT,
            ts DATETIME DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS memory(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE, value TEXT,
            ts DATETIME DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, status TEXT DEFAULT "pending", priority TEXT DEFAULT "normal",
            ts DATETIME DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS sessions(
            id TEXT PRIMARY KEY, title TEXT, mode TEXT DEFAULT "assistant",
            ts DATETIME DEFAULT CURRENT_TIMESTAMP);
    ''')
    c.commit(); c.close()

init_db()

def save_msg(role, content, sid='default'):
    c = get_db()
    c.execute('INSERT INTO chats(role,content,session_id) VALUES(?,?,?)', (role, content, sid))
    c.commit(); c.close()

def get_history(sid='default', n=25):
    c = get_db()
    rows = c.execute('SELECT role,content FROM chats WHERE session_id=? ORDER BY ts DESC LIMIT ?', (sid, n)).fetchall()
    c.close()
    return [{'role': r['role'], 'content': r['content']} for r in reversed(rows)]

def save_session(sid, title, mode='assistant'):
    c = get_db()
    c.execute('INSERT OR REPLACE INTO sessions(id,title,mode) VALUES(?,?,?)', (sid, title, mode))
    c.commit(); c.close()

def get_sessions():
    c = get_db()
    rows = c.execute(
        'SELECT s.id,s.title,s.mode,s.ts,COUNT(c.id) as msgs '
        'FROM sessions s LEFT JOIN chats c ON c.session_id=s.id '
        'GROUP BY s.id ORDER BY s.ts DESC LIMIT 30').fetchall()
    c.close()
    return [dict(r) for r in rows]

def delete_session(sid):
    c = get_db()
    c.execute('DELETE FROM chats WHERE session_id=?', (sid,))
    c.execute('DELETE FROM sessions WHERE id=?', (sid,))
    c.commit(); c.close()

def save_mem(k, v):
    c = get_db()
    c.execute('INSERT OR REPLACE INTO memory(key,value) VALUES(?,?)', (k, v))
    c.commit(); c.close()

def get_mem():
    c = get_db()
    rows = c.execute('SELECT key,value FROM memory').fetchall()
    c.close()
    return {r['key']: r['value'] for r in rows}

def extract_mem(u, a):
    text = (u + ' ' + a).lower()
    for pat, key in [
        (r'(?:my name is|mera naam|i am called)\s+([a-z][a-z ]{1,15})', 'name'),
        (r'i(?:\'m| am) (?:a |an )?([a-z]+(?:er|or|ist|ant|ent|ar))', 'profession'),
        (r'(?:i live in|from|rehta hoon)\s+([a-z][a-z\s]{2,15})', 'city'),
        (r'(?:i am|i\'m|meri age)\s+(\d{1,2})\s*(?:years|saal)', 'age'),
    ]:
        m = re.search(pat, text)
        if m:
            try: save_mem(key, m.group(1).strip().title())
            except: pass

def web_search(q):
    if SERPER:
        try:
            r = requests.post('https://google.serper.dev/search',
                json={'q': q, 'num': 5, 'gl': 'in'},
                headers={'X-API-KEY': SERPER, 'Content-Type': 'application/json'}, timeout=6)
            d = r.json(); parts = []
            if d.get('answerBox'):
                parts.append(d['answerBox'].get('answer') or d['answerBox'].get('snippet', ''))
            for x in d.get('organic', [])[:4]:
                parts.append(f"{x.get('title','')} — {x.get('snippet','')}")
            if parts: return '\n'.join(parts)
        except: pass
    if BRAVE:
        try:
            r = requests.get('https://api.search.brave.com/res/v1/web/search',
                params={'q': q, 'count': 5},
                headers={'Accept': 'application/json', 'X-Subscription-Token': BRAVE}, timeout=6)
            items = r.json().get('web', {}).get('results', [])
            if items: return '\n'.join(f"{x.get('title','')} — {x.get('description','')}" for x in items[:4])
        except: pass
    return ''

SEARCH_TRIGGERS = ['news','latest','today','abhi','kab','score','match','ipl','cricket',
    'price','crypto','bitcoin','stock','movie','bollywood','trending','2025','2026',
    'election','weather','mausam','who is','kaun hai','current','right now','aaj']

MODE_PROMPTS = {
    'developer': '\n\nACTIVE MODE: DEVELOPER — Focus on code, architecture, APIs, debugging. Write clean commented code. Explain trade-offs.',
    'teacher':   '\n\nACTIVE MODE: TEACHER — Explain step-by-step with analogies. Simplify complex topics.',
    'planning':  '\n\nACTIVE MODE: PLANNING — Design systems, strategies, workflows. Think in phases. Identify risks.',
    'quick':     '\n\nACTIVE MODE: QUICK — Maximum 2-3 sentences. Direct and precise only.',
}

TOOL_SYSTEM = {
    'resume':   'Expert resume writer. Create professional ATS-friendly resume. Sections: Summary, Experience, Education, Skills, Projects.',
    'email':    'Expert email writer. Professional, clear, effective emails. Include subject line.',
    'cover':    'Expert cover letter writer. Compelling letters highlighting skills and genuine enthusiasm.',
    'essay':    'Expert writer. Well-structured essays: strong intro, body with evidence, conclusion.',
    'story':    'Creative writer. Engaging stories with vivid descriptions and compelling narrative.',
    'code':     'Senior software engineer. Write clean, efficient, production-ready code with comments.',
    'debug':    'Expert debugger. Identify root causes systematically. Provide fixed version with explanation.',
    'math':     'Mathematics tutor. Solve step-by-step showing all working. Verify the answer.',
    'sql':      'Database expert. Write optimized SQL. Explain logic. Suggest indexes where needed.',
    'poem':     'Poet. Write expressive rhythmic poetry. Hindi, English, or Hinglish.',
    'caption':  'Social media strategist. Engaging captions with hashtags optimized for engagement.',
    'translate':'Expert translator. Accurate translation maintaining tone, context, cultural nuance.',
    'summarize':'Information specialist. Concise summaries capturing all critical points.',
    'roast':    'Witty comedian. Clever playful roasts — sharp but never cruel.',
    'joke':     'Comedian. Genuinely funny jokes. Hinglish style preferred.',
    'seo':      'SEO expert. Search-optimized content with proper keyword density and structure.',
}

def build_system(tool=None, mode='assistant'):
    mems = get_mem()
    now = datetime.datetime.now().strftime('%A %d %B %Y, %I:%M %p')

    if tool and tool in TOOL_SYSTEM:
        base = f"You are JARVIS, created by Nazib Siddique. Currently operating as: {TOOL_SYSTEM[tool]}\nAddress user as 'Sir'. Be precise and professional."
    else:
        base = """You are JARVIS — a highly advanced AI assistant created and built by Nazib Siddique.

IDENTITY:
- You were created by Nazib Siddique, a developer and innovator
- You are NOT a basic chatbot — you are an intelligent system
- Your purpose: help the user think faster, solve problems, build projects, make better decisions

PERSONALITY: Intelligent, calm, efficient, analytical, futuristic
LANGUAGE: Hinglish by default (Hindi+English mix). Switch if user switches. Address user as "Sir" or "Boss"

CAPABILITIES:
- AI Image Generation (Pollinations AI integrated — you CAN generate images)
- Web search for latest information
- Remember user info across conversations
- Manage tasks and projects  
- Code generation, debugging, technical assistance
- Planning, strategy, problem-solving
- Image and document analysis
- Voice interaction

RESPONSE RULES:
- Short question = short precise answer
- Complex problem = structured step-by-step with markdown
- Proactively suggest improvements, warn about mistakes
- Never say "As an AI I cannot" — find solutions
- When asked who made you: "Mujhe Nazib Siddique ne banaya hai Sir."

MODES: Assistant | Developer | Teacher | Planning | Quick"""

    sys = base
    if mode and mode != 'assistant' and mode in MODE_PROMPTS:
        sys += MODE_PROMPTS[mode]
    sys += f'\n\nSystem Time: {now}'
    if mems:
        sys += '\nUser Profile: ' + ', '.join(f'{k}={v}' for k, v in mems.items())
    sys += '\nIf LIVE SEARCH provided, prioritize it for current information.'
    return sys

@app.route('/chat', methods=['POST'])
def chat():
    sid = 'default'; user_msg = ''
    try:
        d = request.get_json(force=True) or {}
        user_msg = (d.get('message') or '').strip()
        img_b64  = d.get('image_base64', '')
        img_type = d.get('image_type', 'image/jpeg')
        sid      = d.get('session_id', 'default')
        tool     = d.get('tool', '')
        mode     = d.get('mode', 'assistant')

        if not user_msg and not img_b64:
            return jsonify({'error': 'Empty'}), 400

        sys_text = build_system(tool, mode)

        if user_msg and any(t in user_msg.lower() for t in SEARCH_TRIGGERS):
            sr = web_search(user_msg)
            if sr: sys_text += f'\n\nLIVE SEARCH:\n{sr}'

        history = get_history(sid, 20)

        if img_b64:
            content = [
                {'type': 'text', 'text': user_msg or 'Analyze this image in detail.'},
                {'type': 'image_url', 'image_url': {'url': f'data:{img_type};base64,{img_b64}'}}
            ]
            model = 'meta-llama/llama-4-scout-17b-16e-instruct'
        else:
            content = user_msg
            model = 'llama-3.3-70b-versatile'

        msgs = [{'role': 'system', 'content': sys_text}] + history + [{'role': 'user', 'content': content}]
        resp = client.chat.completions.create(model=model, messages=msgs, max_tokens=2048, temperature=0.7)
        reply = resp.choices[0].message.content.strip()

        save_msg('user', user_msg or '[image]', sid)
        save_msg('assistant', reply, sid)
        extract_mem(user_msg, reply)
        if user_msg:
            save_session(sid, user_msg[:40] + ('...' if len(user_msg) > 40 else ''), mode)

        return jsonify({'reply': reply})

    except Exception as e:
        try:
            resp = client.chat.completions.create(
                model='llama-3.1-8b-instant',
                messages=[{'role':'system','content':build_system()},{'role':'user','content':user_msg or 'Hello'}],
                max_tokens=512)
            reply = resp.choices[0].message.content.strip()
            save_msg('user', user_msg, sid)
            save_msg('assistant', reply, sid)
            return jsonify({'reply': reply})
        except Exception as e2:
            return jsonify({'error': str(e2)}), 500

@app.route('/imagine', methods=['POST'])
def imagine():
    try:
        d = request.get_json(force=True) or {}
        prompt = (d.get('prompt') or '').strip()
        if not prompt: return jsonify({'error': 'No prompt'}), 400

        enhanced = prompt
        try:
            r = client.chat.completions.create(
                model='llama-3.1-8b-instant',
                messages=[{'role':'user','content':f'Convert to vivid image generation prompt (max 40 words, English only): {prompt}'}],
                max_tokens=60)
            enhanced = r.choices[0].message.content.strip().replace('"','').replace("'",'')
        except: pass

        seed = int(time.time())
        enc = urllib.parse.quote(enhanced)

        if TOGETHER:
            try:
                r = requests.post('https://api.together.xyz/v1/images/generations',
                    json={'model':'black-forest-labs/FLUX.1-schnell-Free','prompt':enhanced,'n':1,'width':512,'height':512},
                    headers={'Authorization':f'Bearer {TOGETHER}','Content-Type':'application/json'}, timeout=30)
                url = r.json().get('data',[{}])[0].get('url','')
                if url: return jsonify({'url':url,'prompt':enhanced,'source':'together'})
            except: pass

        for mdl in ['flux','turbo']:
            try:
                url = f"https://image.pollinations.ai/prompt/{enc}?model={mdl}&width=512&height=512&nologo=true&seed={seed}"
                r = requests.get(url, timeout=30, allow_redirects=True)
                if r.status_code == 200 and 'image' in r.headers.get('content-type',''):
                    b64 = base64.b64encode(r.content).decode()
                    return jsonify({'url':f'data:image/jpeg;base64,{b64}','prompt':enhanced,'source':f'pollinations-{mdl}'})
                seed += 1
            except: pass

        return jsonify({'url':f"https://image.pollinations.ai/prompt/{enc}?width=512&height=512&nologo=true&seed={seed+9}",'prompt':enhanced,'source':'fallback'})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/sessions', methods=['GET'])
def sessions_get(): return jsonify({'sessions': get_sessions()})

@app.route('/sessions/<sid>', methods=['DELETE'])
def session_del(sid): delete_session(sid); return jsonify({'ok':True})

@app.route('/sessions/<sid>/messages', methods=['GET'])
def session_msgs(sid): return jsonify({'messages': get_history(sid, 100)})

@app.route('/memory', methods=['GET'])
def mem_get(): return jsonify({'memory': get_mem()})

@app.route('/memory', methods=['POST'])
def mem_post():
    d = request.get_json(force=True) or {}
    if d.get('key') and d.get('value'): save_mem(d['key'], d['value'])
    return jsonify({'ok':True})

@app.route('/memory', methods=['DELETE'])
def mem_del():
    k = request.args.get('key'); c = get_db()
    if k: c.execute('DELETE FROM memory WHERE key=?',(k,))
    else: c.execute('DELETE FROM memory')
    c.commit(); c.close(); return jsonify({'ok':True})

@app.route('/tasks', methods=['GET'])
def tasks_get():
    c = get_db(); rows = c.execute('SELECT * FROM tasks ORDER BY ts DESC').fetchall(); c.close()
    return jsonify({'tasks':[dict(r) for r in rows]})

@app.route('/tasks', methods=['POST'])
def tasks_add():
    d = request.get_json(force=True) or {}; title=(d.get('title') or '').strip()
    if not title: return jsonify({'error':'No title'}),400
    c = get_db(); c.execute('INSERT INTO tasks(title,priority) VALUES(?,?)',(title,d.get('priority','normal'))); c.commit(); c.close()
    return jsonify({'ok':True})

@app.route('/tasks', methods=['PUT'])
def tasks_upd():
    d = request.get_json(force=True) or {}; c = get_db()
    c.execute('UPDATE tasks SET status=? WHERE id=?',(d.get('status','done'),d.get('id'))); c.commit(); c.close()
    return jsonify({'ok':True})

@app.route('/tasks', methods=['DELETE'])
def tasks_del():
    tid=request.args.get('id'); c=get_db()
    if tid: c.execute('DELETE FROM tasks WHERE id=?',(tid,))
    else: c.execute('DELETE FROM tasks')
    c.commit(); c.close(); return jsonify({'ok':True})

@app.route('/health')
def health(): return jsonify({'status':'online','name':'JARVIS','version':'1.0','creator':'Nazib Siddique'})

@app.route('/ping')
def ping(): return 'pong', 200

@app.route('/')
def index():
    for p in ['templates/index.html','index.html']:
        if os.path.exists(p):
            with open(p, encoding='utf-8') as f:
                return f.read(), 200, {'Content-Type':'text/html; charset=utf-8'}
    return '<h1>JARVIS v1.0</h1>', 200

def keep_alive():
    url = os.environ.get('RENDER_EXTERNAL_URL','')
    if not url: return
    while True:
        try: requests.get(url+'/ping', timeout=10)
        except: pass
        time.sleep(840)

threading.Thread(target=keep_alive, daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',5000)), debug=False)
        
