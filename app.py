from flask import Flask, request, jsonify, Response
from groq import Groq
import os, re, sqlite3, datetime, requests, threading, time

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

GROQ_KEY = os.environ.get('GROQ_API_KEY','')
WEATHER  = os.environ.get('WEATHER_API_KEY','')
SERPER   = os.environ.get('SERPER_API_KEY','')
BRAVE    = os.environ.get('BRAVE_SEARCH_KEY','')
client   = Groq(api_key=GROQ_KEY)
DB       = 'maria3.db'

def get_db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = get_db()
    c.executescript('''
        CREATE TABLE IF NOT EXISTS chats(id INTEGER PRIMARY KEY AUTOINCREMENT,role TEXT,content TEXT,ts DATETIME DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS memory(id INTEGER PRIMARY KEY AUTOINCREMENT,key TEXT UNIQUE,value TEXT,ts DATETIME DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,status TEXT DEFAULT "pending",ts DATETIME DEFAULT CURRENT_TIMESTAMP);
    ''')
    c.commit(); c.close()

init_db()

def save_msg(role, content):
    c = get_db(); c.execute('INSERT INTO chats(role,content) VALUES(?,?)',(role,content)); c.commit(); c.close()

def get_history(n=20):
    c = get_db()
    rows = c.execute('SELECT role,content FROM chats ORDER BY ts DESC LIMIT ?',(n,)).fetchall()
    c.close()
    return [{'role':r['role'],'content':r['content']} for r in reversed(rows)]

def save_mem(k,v):
    c = get_db(); c.execute('INSERT OR REPLACE INTO memory(key,value) VALUES(?,?)',(k,v)); c.commit(); c.close()

def get_mem():
    c = get_db()
    rows = c.execute('SELECT key,value FROM memory').fetchall()
    c.close()
    return {r['key']:r['value'] for r in rows}

def extract_mem(u,a):
    text = (u+' '+a).lower()
    for pat,key in [
        (r'(?:my name is|mera naam|i am)\s+([a-z][a-z ]{1,15})','name'),
        (r'i(?:\'m| am) (?:a |an )?([a-z]+(?:er|or|ist|ant|ent))','profession'),
        (r'(?:i live in|from|rehta|rehti)\s+([a-z][a-z\s]{2,15})','city'),
        (r'(?:i am|i\'m|meri age)\s+(\d{1,2})\s*(?:years|saal)','age'),
    ]:
        m = re.search(pat, text)
        if m:
            try: save_mem(key, m.group(1).strip().title())
            except: pass

def web_search(q):
    if SERPER:
        try:
            r = requests.post('https://google.serper.dev/search',json={'q':q,'num':5,'gl':'in'},headers={'X-API-KEY':SERPER,'Content-Type':'application/json'},timeout=6)
            d = r.json(); parts = []
            if d.get('answerBox'): parts.append(d['answerBox'].get('answer') or d['answerBox'].get('snippet',''))
            for x in d.get('organic',[])[:4]: parts.append(f"{x.get('title','')} - {x.get('snippet','')}")
            if parts: return '\n'.join(parts)
        except: pass
    if BRAVE:
        try:
            r = requests.get('https://api.search.brave.com/res/v1/web/search',params={'q':q,'count':5},headers={'Accept':'application/json','X-Subscription-Token':BRAVE},timeout=6)
            items = r.json().get('web',{}).get('results',[])
            parts = [f"{x.get('title','')} - {x.get('description','')}" for x in items[:4]]
            if parts: return '\n'.join(parts)
        except: pass
    return ''

SEARCH_TRIGGERS = ['news','latest','today','abhi','kab','release','score','match','ipl','cricket','price','crypto','bitcoin','stock','movie','film','bollywood','trending','2025','2026','election','weather','mausam','who is','kaun hai']

def build_system():
    mems = get_mem()
    now  = datetime.datetime.now().strftime('%A %d %B %Y, %I:%M %p')
    sys  = f"""You are M.A.R.I.A — Most Advanced Responsive Intelligent Assistant. Created by Nazib Siddique.
NEVER say you're Groq/Llama/GPT. You are MARIA — Jarvis-level AI.
PERSONALITY: Sharp, witty, confident, slightly sarcastic, highly intelligent.
LANGUAGE: Hinglish by default. ALWAYS call user "Boss". No cringe phrases.
STYLE: Short question = short punchy answer. Long question = detailed markdown.
Current time: {now}"""
    if mems: sys += '\nBOSS PROFILE: ' + ', '.join(f'{k}={v}' for k,v in mems.items())
    sys += '\nIf LIVE SEARCH provided, use it. Prioritize fresh data.'
    return sys

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data     = request.get_json(force=True) or {}
        user_msg = (data.get('message') or '').strip()
        img_b64  = data.get('image_base64','')
        img_type = data.get('image_type','image/jpeg')
        if not user_msg and not img_b64: return jsonify({'error':'Empty'}),400

        sys_text = build_system()
        if user_msg and any(t in user_msg.lower() for t in SEARCH_TRIGGERS):
            sr = web_search(user_msg)
            if sr: sys_text += f'\n\nLIVE SEARCH:\n{sr}'

        history  = get_history(20)
        if img_b64:
            content = [{'type':'text','text': user_msg or 'Analyze this image.'},{'type':'image_url','image_url':{'url':f'data:{img_type};base64,{img_b64}'}}]
            model = 'meta-llama/llama-4-scout-17b-16e-instruct'
        else:
            content = user_msg
            model   = 'llama-3.3-70b-versatile'

        msgs = [{'role':'system','content':sys_text}] + history + [{'role':'user','content':content}]
        resp  = client.chat.completions.create(model=model,messages=msgs,max_tokens=1024,temperature=0.8)
        reply = resp.choices[0].message.content.strip()
        save_msg('user', user_msg or '[image]')
        save_msg('assistant', reply)
        extract_mem(user_msg, reply)
        return jsonify({'reply': reply})
    except Exception as e:
        try:
            resp  = client.chat.completions.create(model='llama-3.1-8b-instant',messages=[{'role':'system','content':build_system()},{'role':'user','content':user_msg or 'Hi'}],max_tokens=512)
            reply = resp.choices[0].message.content.strip()
            save_msg('user', user_msg); save_msg('assistant', reply)
            return jsonify({'reply': reply})
        except Exception as e2:
            return jsonify({'error': str(e2)}),500

@app.route('/memory', methods=['GET'])
def mem_get(): return jsonify({'memory': get_mem()})

@app.route('/memory', methods=['POST'])
def mem_post():
    d = request.get_json(force=True) or {}
    if d.get('key') and d.get('value'): save_mem(d['key'],d['value'])
    return jsonify({'ok':True})

@app.route('/memory', methods=['DELETE'])
def mem_del():
    k = request.args.get('key'); c = get_db()
    if k: c.execute('DELETE FROM memory WHERE key=?',(k,))
    else: c.execute('DELETE FROM memory')
    c.commit(); c.close(); return jsonify({'ok':True})

@app.route('/history')
def hist(): return jsonify({'history': get_history(50)})

@app.route('/clear', methods=['POST'])
def clear():
    c = get_db(); c.execute('DELETE FROM chats'); c.commit(); c.close()
    return jsonify({'ok':True})

@app.route('/tasks', methods=['GET'])
def tasks_get():
    c = get_db(); rows = c.execute('SELECT * FROM tasks ORDER BY ts DESC').fetchall(); c.close()
    return jsonify({'tasks':[dict(r) for r in rows]})

@app.route('/tasks', methods=['POST'])
def tasks_add():
    d = request.get_json(force=True) or {}; title = (d.get('title') or '').strip()
    if not title: return jsonify({'error':'No title'}),400
    c = get_db(); c.execute('INSERT INTO tasks(title) VALUES(?)',(title,)); c.commit(); c.close()
    return jsonify({'ok':True})

@app.route('/tasks', methods=['PUT'])
def tasks_upd():
    d = request.get_json(force=True) or {}; c = get_db()
    c.execute('UPDATE tasks SET status=? WHERE id=?',(d.get('status','done'),d.get('id'))); c.commit(); c.close()
    return jsonify({'ok':True})

@app.route('/tasks', methods=['DELETE'])
def tasks_del():
    tid = request.args.get('id'); c = get_db()
    if tid: c.execute('DELETE FROM tasks WHERE id=?',(tid,))
    else:   c.execute('DELETE FROM tasks')
    c.commit(); c.close(); return jsonify({'ok':True})

@app.route('/health')
def health(): return jsonify({'status':'ok','name':'M.A.R.I.A','version':'3.0'})

@app.route('/ping')
def ping(): return 'pong',200

@app.route('/')
def index():
    for p in ['templates/index.html','index.html']:
        if os.path.exists(p):
            with open(p,encoding='utf-8') as f: return f.read(),200,{'Content-Type':'text/html; charset=utf-8'}
    return '<h1>MARIA 3.0</h1>',200

def keep_alive():
    url = os.environ.get('RENDER_EXTERNAL_URL','')
    if not url: return
    while True:
        try: requests.get(url+'/ping',timeout=10)
        except: pass
        time.sleep(840)

threading.Thread(target=keep_alive,daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)),debug=False)
    
