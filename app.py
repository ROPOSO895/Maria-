from flask import Flask, request, jsonify, render_template, session
from groq import Groq
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "supersecretkey")

client = Groq(
    api_key=os.environ.get("GROQ_API_KEY")
)

SYSTEM_PROMPT = {
    "role": "system",
    "content": "You are Jarvis, a futuristic intelligent AI assistant. Answer clearly and concisely."
}

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/ask", methods=["POST"])
def ask():
    try:
        user_input = request.json.get("message")

        if not user_input:
            return jsonify({"reply": "No input provided."})

        if "chat_memory" not in session:
            session["chat_memory"] = [SYSTEM_PROMPT]

        chat_memory = session["chat_memory"]
        chat_memory.append({"role": "user", "content": user_input})

        completion = client.chat.completions.create(
            model="llama3-8b-8192",
            messages=chat_memory
        )

        reply = completion.choices[0].message.content
        chat_memory.append({"role": "assistant", "content": reply})

        session["chat_memory"] = chat_memory

        return jsonify({"reply": reply})

    except Exception as e:
        return jsonify({"reply": f"Error: {str(e)}"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
