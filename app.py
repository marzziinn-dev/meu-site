from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

PROMISE_API_KEY = os.getenv("PROMISE_API_KEY")

@app.route("/")
def home():
    return "Revolution Pay API Online 🚀"


# 🔹 Criar cobrança
@app.route("/create-charge", methods=["POST"])
def create_charge():
    data = request.json
    amount = data.get("amount")

    url = "https://api.promise.com/v1/charges"

    headers = {
        "Authorization": f"Bearer {PROMISE_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "amount": amount,
        "payment_method": "pix"
    }

    response = requests.post(url, json=payload, headers=headers)

    return jsonify(response.json())


# 🔹 Webhook da Promise
@app.route("/webhook/promise", methods=["POST"])
def webhook():
    data = request.json
    print("Webhook recebido:", data)

    # Aqui você depois vai atualizar banco

    return "ok", 200


if __name__ == "__main__":
    app.run()