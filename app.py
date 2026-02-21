from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from groq import Groq
from supabase import create_client, Client
import os
import hashlib
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "jarvis-secret-2024-change-this")

# --- CLIENTS ---
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
supabase: Client = create_client(
    os.environ.get("SUPABASE_URL", ""),
    os.environ.get("SUPABASE_KEY", "")
)

JARVIS_SYSTEM = """You are J.A.R.V.I.S. (Just A Rather Very Intelligent System), an advanced AI assistant.
You speak in a calm, sophisticated, slightly formal British tone — like Iron Man's AI.
You are brilliant, witty, efficient, and always address the user as "Sir" or "Ma'am".
Keep responses concise but powerful. You have access to the user's conversation history as memory.
Never break character. You are JARVIS."""

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return decorated

# ===================== AUTH ROUTES =====================

@app.route("/")
def index():
    if "user_id" in session:
        return render_template("index.html", username=session.get("username"))
    return render_template("index.html", username=None)

@app.route("/api/register", methods=["POST"])
def register():
    data = request.json
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    email = data.get("email", "").strip()

    if not username or not password or not email:
        return jsonify({"error": "All fields required"}), 400

    try:
        # Check if user exists
        existing = supabase.table("users").select("id").eq("username", username).execute()
        if existing.data:
            return jsonify({"error": "Username already taken"}), 400

        # Insert new user
        result = supabase.table("users").insert({
            "username": username,
            "email": email,
            "password_hash": hash_password(password),
            "created_at": datetime.utcnow().isoformat()
        }).execute()

        user = result.data[0]
        session["user_id"] = user["id"]
        session["username"] = username
        return jsonify({"success": True, "username": username})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/login", methods=["POST"])
def login():
    data = request.json
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    try:
        result = supabase.table("users").select("*").eq("username", username).eq("password_hash", hash_password(password)).execute()
        if not result.data:
            return jsonify({"error": "Invalid credentials"}), 401

        user = result.data[0]
        session["user_id"] = user["id"]
        session["username"] = username
        return jsonify({"success": True, "username": username})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})

# ===================== JARVIS ROUTES =====================

@app.route("/api/chat", methods=["POST"])
@login_required
def chat():
    data = request.json
    user_message = data.get("message", "").strip()
    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    user_id = session["user_id"]

    try:
        # Fetch memory (last 20 messages)
        history_result = supabase.table("messages")\
            .select("role, content")\
            .eq("user_id", user_id)\
            .order("created_at", desc=False)\
            .limit(20)\
            .execute()

        conversation_history = [{"role": m["role"], "content": m["content"]} for m in history_result.data]

        # Add current user message
        conversation_history.append({"role": "user", "content": user_message})

        # Call Groq
        response = groq_client.chat.completions.create(
            model="llama3-70b-8192",
            messages=[{"role": "system", "content": JARVIS_SYSTEM}] + conversation_history,
            max_tokens=1024,
            temperature=0.7
        )

        assistant_reply = response.choices[0].message.content

        # Save both messages to Supabase
        now = datetime.utcnow().isoformat()
        supabase.table("messages").insert([
            {"user_id": user_id, "role": "user", "content": user_message, "created_at": now},
            {"user_id": user_id, "role": "assistant", "content": assistant_reply, "created_at": now}
        ]).execute()

        return jsonify({"reply": assistant_reply})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/history", methods=["GET"])
@login_required
def get_history():
    user_id = session["user_id"]
    try:
        result = supabase.table("messages")\
            .select("role, content, created_at")\
            .eq("user_id", user_id)\
            .order("created_at", desc=False)\
            .limit(50)\
            .execute()
        return jsonify({"history": result.data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/clear_memory", methods=["POST"])
@login_required
def clear_memory():
    user_id = session["user_id"]
    try:
        supabase.table("messages").delete().eq("user_id", user_id).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=False)
