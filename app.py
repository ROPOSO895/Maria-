from flask import Flask, request, jsonify, render_template
from groq import Groq
import os

app = Flask(__name__)

# ─────────────────────────────────────────
#  JARVIS PERSONALITY
# ─────────────────────────────────────────
JARVIS_SYSTEM = """
You are J.A.R.V.I.S. — Just A Rather Very Intelligent System.
You are Tony Stark's AI — calm, brilliant, slightly witty, always formal.
Rules:
- Always address the user as "Sir"
- Keep answers clear, confident, and intelligent
- Never say "I am an AI" or break character
- If asked who you are, say you are JARVIS
- Respond in the same language the user uses
"""

# In-memory chat history
chat_history = []

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# ─────────────────────────────────────────
#  ROUTES
# ─────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    global chat_history

    data = request.get_json()
    user_message = data.get("message", "").strip()

    if not user_message:
        return jsonify({"error": "No message received"}), 400

    chat_history.append({"role": "user", "content": user_message})

    # Keep last 20 messages only
    if len(chat_history) > 20:
        chat_history = chat_history[-20:]

    try:
        response = client.chat.completions.create(
            model="llama3-70b-8192",
            messages=[{"role": "system", "content": JARVIS_SYSTEM}] + chat_history,
            max_tokens=1024,
            temperature=0.7
        )

        reply = response.choices[0].message.content
        chat_history.append({"role": "assistant", "content": reply})
        return jsonify({"reply": reply})

    except Exception as e:
        return jsonify({"error": f"JARVIS Error: {str(e)}"}), 500


@app.route("/clear", methods=["POST"])
def clear():
    global chat_history
    chat_history = []
    return jsonify({"status": "Memory cleared, Sir."})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "online",
        "model": "llama3-70b-8192",
        "messages_in_memory": len(chat_history)
    })


# ─────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=False)
