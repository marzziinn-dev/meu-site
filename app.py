from flask import Flask, request, jsonify, render_template_string
import psycopg2
import os

app = Flask(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id SERIAL PRIMARY KEY,
        amount INTEGER,
        status VARCHAR(20)
    )
    """)

    conn.commit()
    cur.close()
    conn.close()

init_db()

@app.route("/")
def dashboard():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT SUM(amount) FROM transactions WHERE status='paid'")
    total = cur.fetchone()[0] or 0

    cur.execute("SELECT * FROM transactions ORDER BY id DESC")
    txs = cur.fetchall()

    cur.close()
    conn.close()

    html = """
    <html>
    <body style='background:#111;color:white;font-family:Arial;padding:20px'>
        <h2>Revolution Pay</h2>
        <h3>Total Processado: R$ {{total}}</h3>

        <h3>Criar Cobrança</h3>
        <form method="post" action="/create">
            <input name="amount" placeholder="Valor" />
            <button type="submit">Criar</button>
        </form>

        <h3>Transações</h3>
        {% for t in txs %}
            <div>ID {{t[0]}} - R$ {{t[1]}} - {{t[2]}}</div>
        {% endfor %}
    </body>
    </html>
    """

    return render_template_string(html, total=total, txs=txs)

@app.route("/create", methods=["POST"])
def create():
    amount = request.form.get("amount")

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO transactions (amount, status) VALUES (%s, %s)",
        (amount, "pending")
    )

    conn.commit()
    cur.close()
    conn.close()

    return "Cobrança criada! Volte."

@app.route("/webhook/promise", methods=["POST"])
def webhook():
    data = request.json
    tx_id = data.get("id")

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "UPDATE transactions SET status='paid' WHERE id=%s",
        (tx_id,)
    )

    conn.commit()
    cur.close()
    conn.close()

    return "ok", 200

if __name__ == "__main__":
    app.run()