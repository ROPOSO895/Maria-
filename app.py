from flask import Flask, request, jsonify, Response
from groq import Groq
import os, re, sqlite3, datetime, requests, threading, time, urllib.parse

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
    return Response('', 200, {'Access-Control-Allow-Origin':'*','Access-Control-Allow-Methods':'GET,POST,PUT,DELETE,OPTIONS','Access-Control-Allow-Headers':'Content-Type'})

GROQ_KEY  = os.environ.get('GROQ_API_KEY','')
WEATHER   = os.environ.get('WEATHER_API_KEY','')
SERPER    = os.environ.get('SERPER_API_KEY','')
BRAVE     = os.environ.get('BRAVE_SEARCH_KEY','')
TOGETHER  = os.environ.get('TOGETHER_API_KEY','')
NEWS_KEY  = os.environ.get('NEWS_API_KEY','')

client = Groq(api_key=GROQ_KEY)
DB = 'maria3.db'

def get_db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = get_db()
    c.executescript('''
        CREATE TABLE IF NOT EXISTS chats(id INTEGER PRIMARY KEY AUTOINCREMENT,role TEXT,content TEXT,session_id TEXT,ts DATETIME DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS memory(id INTEGER PRIMARY KEY AUTOINCREMENT,key TEXT UNIQUE,value TEXT,ts DATETIME DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,status TEXT DEFAULT "pending",ts DATETIME DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,title TEXT,ts DATETIME DEFAULT CURRENT_TIMESTAMP);
    ''')
    c.commit(); c.close()

init_db()

def save_msg(role, content, session_id='default'):
    c = get_db()
    c.execute('INSERT INTO chats(role,content,session_id) VALUES(?,?,?)', (role, content, session_id))
    c.commit(); c.close()

def get_history(session_id='default', n=30):
    c = get_db()
    rows = c.execute('SELECT role,content FROM chats WHERE session_id=? ORDER BY ts DESC LIMIT ?', (session_id, n)).fetchall()
    c.close()
    return [{'role': r['role'], 'content': r['content']} for r in reversed(rows)]

def get_sessions():
    c = get_db()
    rows = c.execute('SELECT s.id, s.title, s.ts, COUNT(c.id) as msg_count FROM sessions s LEFT JOIN chats c ON c.session_id=s.id GROUP BY s.id ORDER BY s.ts DESC LIMIT 30').fetchall()
    c.close()
    return [dict(r) for r in rows]

def save_session(sid, title):
    c = get_db()
    c.execute('INSERT OR REPLACE INTO sessions(id,title) VALUES(?,?)', (sid, title))
    c.commit(); c.close()

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
    text = (u+' '+a).lower()
    for pat, key in [
        (r'(?:my name is|mera naam|i am called)\s+([a-z][a-z ]{1,15})', 'name'),
        (r'i(?:\'m| am) (?:a |an )?([a-z]+(?:er|or|ist|ant|ent|ar))', 'profession'),
        (r'(?:i live in|from|rehta hoon in|mera sheher)\s+([a-z][a-z\s]{2,15})', 'city'),
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
                parts.append(d['answerBox'].get('answer') or d['answerBox'].get('snippet',''))
            for x in d.get('organic', [])[:4]:
                parts.append(f"{x.get('title','')} - {x.get('snippet','')}")
            if parts: return '\n'.join(parts)
        except: pass
    if BRAVE:
        try:
            r = requests.get('https://api.search.brave.com/res/v1/web/search',
                params={'q': q, 'count': 5},
                headers={'Accept': 'application/json', 'X-Subscription-Token': BRAVE}, timeout=6)
            items = r.json().get('web', {}).get('results', [])
            parts = [f"{x.get('title','')} - {x.get('description','')}" for x in items[:4]]
            if parts: return '\n'.join(parts)
        except: pass
    return ''

SEARCH_TRIGGERS = ['news','latest','today','abhi','kab','release','score','match','ipl',
    'cricket','price','crypto','bitcoin','stock','movie','film','bollywood','trending',
    '2025','2026','election','weather','mausam','who is','kaun hai','current','right now']

TOOL_PROMPTS = {
    'resume': 'You are an expert resume writer. Create a professional, ATS-friendly resume based on the information provided. Format it clearly with sections: Summary, Experience, Education, Skills.',
    'email': 'You are an expert email writer. Write a professional, clear, and effective email based on the context provided. Include subject line.',
    'cover': 'You are an expert cover letter writer. Write a compelling cover letter that highlights relevant skills and enthusiasm for the role.',
    'essay': 'You are an expert essay writer. Write a well-structured, engaging essay with introduction, body paragraphs, and conclusion.',
    'story': 'You are a creative story writer. Write an engaging, imaginative story with vivid descriptions and compelling characters.',
    'code': 'You are an expert programmer. Write clean, well-commented, production-ready code. Include explanations for complex parts.',
    'debug': 'You are an expert code debugger. Analyze the code carefully, identify all bugs, explain each issue, and provide the fixed version.',
    'math': 'You are a math tutor. Solve the problem step by step, explaining each step clearly. Show all working.',
    'sql': 'You are a SQL expert. Write efficient, optimized SQL queries with explanations.',
    'poem': 'You are a creative poet. Write beautiful, expressive poems. Can write in Hindi, English, or Hinglish.',
    'caption': 'You are a social media expert. Write engaging captions with relevant hashtags for Instagram/Twitter/LinkedIn.',
    'roast': 'You are a friendly roast comedian. Write a funny, clever roast - keep it playful and not mean-spirited.',
    'joke': 'You are a comedian. Write genuinely funny jokes in Hinglish style that Boss will enjoy.',
    'translate': 'You are an expert translator. Translate accurately while maintaining tone and context. State the target language.',
    'summarize': 'You are an expert at summarization. Create a concise, comprehensive summary capturing all key points.',
    'imagine': 'You are an AI image prompt expert. Help create the perfect image generation prompt.',
}

def build_system(tool=None):
    mems = get_mem()
    now = datetime.datetime.now().strftime('%A %d %B %Y, %I:%M %p')

    if tool and tool in TOOL_PROMPTS:
        base = TOOL_PROMPTS[tool]
    else:
        base = """You are Maria — a powerful AI assistant created by Nazib Siddique.
PERSONALITY: Sharp, witty, confident, slightly sarcastic, highly intelligent. Like a brilliant best friend.
LANGUAGE: Hinglish by default (natural Hindi+English mix). Switch language if user switches.
ALWAYS call user "Boss". No cringe phrases. No "As an AI". Sound confident always.
STYLE: Short question = short punchy answer. Long question = detailed structured markdown response."""

    sys = base + f'\n\nCurrent time: {now}'
    if mems:
        sys += '\nBoss profile: ' + ', '.join(f'{k}={v}' for k,v in mems.items())
    sys += '\nIf LIVE SEARCH provided, use it as primary source.'
    return sys

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json(force=True) or {}
        user_msg = (data.get('message') or '').strip()
        img_b64 = data.get('image_base64', '')
        img_type = data.get('image_type', 'image/jpeg')
        session_id = data.get('session_id', 'default')
        tool = data.get('tool', '')

        if not user_msg and not img_b64:
            return jsonify({'error': 'Empty'}), 400

        sys_text = build_system(tool)

        if user_msg and any(t in user_msg.lower() for t in SEARCH_TRIGGERS):
            sr = web_search(user_msg)
            if sr: sys_text += f'\n\nLIVE SEARCH:\n{sr}'

        history = get_history(session_id, 20)

        if img_b64:
            content = [
                {'type': 'text', 'text': user_msg or 'Analyze this image.'},
                {'type': 'image_url', 'image_url': {'url': f'data:{img_type};base64,{img_b64}'}}
            ]
            model = 'meta-llama/llama-4-scout-17b-16e-instruct'
        else:
            content = user_msg
            model = 'llama-3.3-70b-versatile'

        msgs = [{'role': 'system', 'content': sys_text}] + history + [{'role': 'user', 'content': content}]
        resp = client.chat.completions.create(model=model, messages=msgs, max_tokens=2048, temperature=0.8)
        reply = resp.choices[0].message.content.strip()

        save_msg('user', user_msg or '[image]', session_id)
        save_msg('assistant', reply, session_id)
        extract_mem(user_msg, reply)

        # Auto-save session title from first message
        if user_msg:
            title = user_msg[:40] + ('...' if len(user_msg) > 40 else '')
            save_session(session_id, title)

        return jsonify({'reply': reply})

    except Exception as e:
        try:
            resp = client.chat.completions.create(
                model='llama-3.1-8b-instant',
                messages=[{'role':'system','content':build_system()},{'role':'user','content':user_msg or 'Hi'}],
                max_tokens=512)
            reply = resp.choices[0].message.content.strip()
            save_msg('user', user_msg, session_id)
            save_msg('assistant', reply, session_id)
            return jsonify({'reply': reply})
        except Exception as e2:
            return jsonify({'error': str(e2)}), 500

@app.route('/imagine', methods=['POST'])
def imagine():
    try:
        data = request.get_json(force=True) or {}
        prompt = (data.get('prompt') or '').strip()
        if not prompt:
            return jsonify({'error': 'No prompt'}), 400

        # Enhance prompt with AI first
        enhanced = prompt
        try:
            r = client.chat.completions.create(
                model='llama-3.1-8b-instant',
                messages=[{'role':'user','content':f'Convert this to a detailed image generation prompt (max 50 words, English only, descriptive): {prompt}'}],
                max_tokens=80)
            enhanced = r.choices[0].message.content.strip().replace('"','')
        except: pass

        # Try Together AI (free tier)
        if TOGETHER:
            try:
                r = requests.post('https://api.together.xyz/v1/images/generations',
                    json={'model':'black-forest-labs/FLUX.1-schnell-Free','prompt':enhanced,'n':1,'width':512,'height':512},
                    headers={'Authorization':f'Bearer {TOGETHER}','Content-Type':'application/json'}, timeout=30)
                d = r.json()
                url = d.get('data',[{}])[0].get('url','')
                if url: return jsonify({'url': url, 'prompt': enhanced})
            except: pass

        # Pollinations AI — completely free, no key needed
        url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(enhanced)}?width=512&height=512&nologo=true&seed={int(time.time())}"
        return jsonify({'url': url, 'prompt': enhanced})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/sessions', methods=['GET'])
def sessions_get():
    return jsonify({'sessions': get_sessions()})

@app.route('/sessions/<sid>', methods=['DELETE'])
def session_del(sid):
    delete_session(sid)
    return jsonify({'ok': True})

@app.route('/sessions/<sid>/messages', methods=['GET'])
def session_msgs(sid):
    return jsonify({'messages': get_history(sid, 100)})

@app.route('/memory', methods=['GET'])
def mem_get(): return jsonify({'memory': get_mem()})

@app.route('/memory', methods=['POST'])
def mem_post():
    d = request.get_json(force=True) or {}
    if d.get('key') and d.get('value'): save_mem(d['key'], d['value'])
    return jsonify({'ok': True})

@app.route('/memory', methods=['DELETE'])
def mem_del():
    k = request.args.get('key'); c = get_db()
    if k: c.execute('DELETE FROM memory WHERE key=?', (k,))
    else: c.execute('DELETE FROM memory')
    c.commit(); c.close()
    return jsonify({'ok': True})

@app.route('/history')
def hist():
    sid = request.args.get('session', 'default')
    return jsonify({'history': get_history(sid, 100)})

@app.route('/clear', methods=['POST'])
def clear():
    sid = request.args.get('session', 'default')
    c = get_db()
    c.execute('DELETE FROM chats WHERE session_id=?', (sid,))
    c.execute('DELETE FROM sessions WHERE id=?', (sid,))
    c.commit(); c.close()
    return jsonify({'ok': True})

@app.route('/tasks', methods=['GET'])
def tasks_get():
    c = get_db(); rows = c.execute('SELECT * FROM tasks ORDER BY ts DESC').fetchall(); c.close()
    return jsonify({'tasks': [dict(r) for r in rows]})

@app.route('/tasks', methods=['POST'])
def tasks_add():
    d = request.get_json(force=True) or {}; title = (d.get('title') or '').strip()
    if not title: return jsonify({'error': 'No title'}), 400
    c = get_db(); c.execute('INSERT INTO tasks(title) VALUES(?)', (title,)); c.commit(); c.close()
    return jsonify({'ok': True})

@app.route('/tasks', methods=['PUT'])
def tasks_upd():
    d = request.get_json(force=True) or {}; c = get_db()
    c.execute('UPDATE tasks SET status=? WHERE id=?', (d.get('status','done'), d.get('id')))
    c.commit(); c.close(); return jsonify({'ok': True})

@app.route('/tasks', methods=['DELETE'])
def tasks_del():
    tid = request.args.get('id'); c = get_db()
    if tid: c.execute('DELETE FROM tasks WHERE id=?', (tid,))
    else: c.execute('DELETE FROM tasks')
    c.commit(); c.close(); return jsonify({'ok': True})

@app.route('/weather')
def weather():
    city = request.args.get('city', 'Delhi')
    if not WEATHER: return jsonify({'error': 'No API key'})
    try:
        r = requests.get('https://api.openweathermap.org/data/2.5/weather',
            params={'q': city, 'appid': WEATHER, 'units': 'metric'}, timeout=5)
        d = r.json()
        if d.get('main'):
            return jsonify({'weather': f"{city}: {d['main']['temp']}°C, feels like {d['main']['feels_like']}°C, {d['weather'][0]['description']}, humidity {d['main']['humidity']}%"})
    except: pass
    return jsonify({'error': 'Weather fetch failed'})

@app.route('/news')
def news():
    cat = request.args.get('category', 'general')
    if not NEWS_KEY: return jsonify({'error': 'No API key'})
    try:
        r = requests.get('https://newsapi.org/v2/top-headlines',
            params={'country': 'in', 'category': cat, 'pageSize': 5, 'apiKey': NEWS_KEY}, timeout=5)
        articles = r.json().get('articles', [])
        items = [{'title': a['title'], 'desc': a.get('description',''), 'url': a.get('url','')} for a in articles[:5]]
        return jsonify({'news': items})
    except: pass
    return jsonify({'error': 'News fetch failed'})

@app.route('/health')
def health(): return jsonify({'status': 'ok', 'name': 'Maria', 'version': '3.2'})

@app.route('/ping')
def ping(): return 'pong', 200

@app.route('/')
def index():
    for p in ['templates/index.html', 'index.html']:
        if os.path.exists(p):
            with open(p, encoding='utf-8') as f:
                return f.read(), 200, {'Content-Type': 'text/html; charset=utf-8'}
    return '<h1>Maria 3.2</h1>', 200

def keep_alive():
    url = os.environ.get('RENDER_EXTERNAL_URL', '')
    if not url: return
    while True:
        try: requests.get(url + '/ping', timeout=10)
        except: pass
        time.sleep(840)

threading.Thread(target=keep_alive, daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
