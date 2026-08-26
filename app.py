from flask import Flask, request, jsonify
from datetime import datetime
import os

app = Flask(__name__)


@app.get("/")
def home():
    return {
        "app": "WP Imports Backend",
        "status": "online",
        "version": "1.0"
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.route("/mercadolivre/notifications", methods=["GET", "POST"])
def mercado_livre_notifications():
    if request.method == "GET":
        return {
            "status": "WP Imports webhook online"
        }

    payload = request.get_json(silent=True) or {}

    print("=== NOTIFICACAO MERCADO LIVRE ===")
    print(payload)

    return jsonify({
        "received": True
    }), 200


@app.get("/mercadolivre/oauth/callback")
def mercado_livre_oauth_callback():
    code = request.args.get("code")
    error = request.args.get("error")

    if error:
        return f"""
        <h2>WP Imports Suite</h2>
        <p>Não foi possível autorizar o Mercado Livre.</p>
        <p>Erro: {error}</p>
        """

    if not code:
        return """
        <h2>WP Imports Suite</h2>
        <p>Callback OAuth funcionando.</p>
        <p>Aguardando autorização do Mercado Livre.</p>
        """

    # Nesta primeira etapa NÃO trocamos o code por token.
    # Isso será feito depois usando credenciais protegidas na Render.
    return """
    <html>
        <head>
            <title>WP Imports Suite</title>
        </head>
        <body style="
            font-family: Arial;
            background:#0d0f14;
            color:white;
            text-align:center;
            padding-top:100px;
        ">
            <h1 style="color:#1769ff;">WP IMPORT</h1>
            <h2>Mercado Livre conectado</h2>
            <p>A autorização foi recebida pelo WP Imports Suite.</p>
            <p>Você pode fechar esta janela.</p>
        </body>
    </html>
    """


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
