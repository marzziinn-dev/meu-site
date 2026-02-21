from flask import Flask, request, jsonify

app = Flask(__name__)

saldo = 0

@app.route("/")
def home():
    return """
    <h1>Infinity Pay</h1>
    <p>Saldo atual: R$ {}</p>
    <form action="/depositar" method="post">
        <input name="valor" placeholder="Valor">
        <button type="submit">Depositar</button>
    </form>
    <form action="/sacar" method="post">
        <input name="valor" placeholder="Valor">
        <button type="submit">Sacar</button>
    </form>
    """.format(saldo)

@app.route("/depositar", methods=["POST"])
def depositar():
    global saldo
    valor = float(request.form["valor"])
    saldo += valor
    return "Depósito realizado!"

@app.route("/sacar", methods=["POST"])
def sacar():
    global saldo
    valor = float(request.form["valor"])
    if saldo >= valor:
        saldo -= valor
        return "Saque solicitado!"
    else:
        return "Saldo insuficiente!"

if __name__ == "__main__":
    app.run()