from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Revolution Pay</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {
                margin: 0;
                font-family: Arial, sans-serif;
                background: linear-gradient(135deg, #0f0f0f, #1a1a1a);
                color: white;
                text-align: center;
            }

            .container {
                padding: 20px;
            }

            .logo {
                font-size: 28px;
                font-weight: bold;
                color: #ff1a1a;
                margin-bottom: 20px;
            }

            .card {
                background: #1e1e1e;
                padding: 20px;
                border-radius: 15px;
                margin-bottom: 20px;
                box-shadow: 0 0 20px rgba(255,0,0,0.2);
            }

            .saldo {
                font-size: 24px;
                margin: 10px 0;
            }

            input {
                width: 80%;
                padding: 10px;
                margin: 10px 0;
                border-radius: 8px;
                border: none;
                outline: none;
            }

            button {
                width: 85%;
                padding: 12px;
                margin-top: 10px;
                border: none;
                border-radius: 8px;
                background: #ff1a1a;
                color: white;
                font-weight: bold;
                font-size: 16px;
                cursor: pointer;
            }

            button:hover {
                background: #cc0000;
            }
        </style>
    </head>
    <body>

        <div class="container">
            <div class="logo">Revolution Pay</div>

            <div class="card">
                <div>Saldo disponível</div>
                <div class="saldo">R$ 0,00</div>
            </div>

            <div class="card">
                <h3>Depositar</h3>
                <input type="number" placeholder="Digite o valor">
                <button>Gerar PIX</button>
            </div>

            <div class="card">
                <h3>Solicitar Saque</h3>
                <input type="number" placeholder="Digite o valor">
                <button>Solicitar</button>
            </div>

        </div>

    </body>
    </html>
    """
    
if __name__ == "__main__":
    app.run()