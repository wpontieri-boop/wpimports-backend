from flask import Flask, request, jsonify, redirect
import os
import requests
from urllib.parse import urlencode
from datetime import datetime, timezone

app = Flask(__name__)

ML_CLIENT_ID = os.getenv("ML_CLIENT_ID")
ML_CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET")
ML_REDIRECT_URI = os.getenv("ML_REDIRECT_URI")

# Temporário para validarmos a primeira conexão.
# Depois vamos salvar os tokens de forma persistente no banco.
ML_TOKENS = {}


@app.route("/")
def home():
    return jsonify({
        "app": "WP Imports Backend",
        "status": "online",
        "version": "1.1",
        "mercado_livre": "integration_ready",
        "time": datetime.now(timezone.utc).isoformat()
    })


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "wpimports-backend"
    })


@app.route("/ml/connect")
def ml_connect():

    if not ML_CLIENT_ID or not ML_REDIRECT_URI:
        return jsonify({
            "error": "missing_configuration",
            "message": "ML_CLIENT_ID ou ML_REDIRECT_URI não configurado."
        }), 500

    params = {
        "response_type": "code",
        "client_id": ML_CLIENT_ID,
        "redirect_uri": ML_REDIRECT_URI,
        "state": "wpimports-setup-20260826"
    }

    auth_url = (
        "https://auth.mercadolivre.com.br/authorization?"
        + urlencode(params)
    )

    return redirect(auth_url)


@app.route("/callback")
def callback():

    error = request.args.get("error")

    if error:
        return jsonify({
            "connected": False,
            "error": error,
            "description": request.args.get("error_description")
        }), 400

    code = request.args.get("code")
    state = request.args.get("state")

    if not code:
        return jsonify({
            "connected": False,
            "error": "authorization_code_missing"
        }), 400

    if state and state != "wpimports-setup-20260826":
        return jsonify({
            "connected": False,
            "error": "invalid_state"
        }), 400

    if not ML_CLIENT_ID or not ML_CLIENT_SECRET or not ML_REDIRECT_URI:
        return jsonify({
            "connected": False,
            "error": "missing_environment_variables"
        }), 500

    token_payload = {
        "grant_type": "authorization_code",
        "client_id": ML_CLIENT_ID,
        "client_secret": ML_CLIENT_SECRET,
        "code": code,
        "redirect_uri": ML_REDIRECT_URI
    }

    try:

        response = requests.post(
            "https://api.mercadolibre.com/oauth/token",
            data=token_payload,
            headers={
                "accept": "application/json",
                "content-type": "application/x-www-form-urlencoded"
            },
            timeout=20
        )

        token_data = response.json()

    except Exception as e:

        return jsonify({
            "connected": False,
            "error": "token_request_failed",
            "detail": str(e)
        }), 500

    if response.status_code != 200:

        return jsonify({
            "connected": False,
            "error": "mercado_livre_token_error",
            "status_code": response.status_code,
            "response": token_data
        }), response.status_code

    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")

    # Guardamos apenas temporariamente nesta etapa.
    ML_TOKENS.clear()
    ML_TOKENS.update({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": token_data.get("expires_in"),
        "user_id": token_data.get("user_id"),
        "scope": token_data.get("scope")
    })

    # Confirma que o token realmente pertence a uma conta válida.
    user_response = requests.get(
        "https://api.mercadolibre.com/users/me",
        headers={
            "Authorization": f"Bearer {access_token}"
        },
        timeout=20
    )

    user_data = {}

    if user_response.status_code == 200:
        user_data = user_response.json()

    return jsonify({
        "connected": True,
        "message": "Mercado Livre conectado com sucesso ao WP Imports.",
        "user_id": token_data.get("user_id"),
        "nickname": user_data.get("nickname"),
        "expires_in": token_data.get("expires_in"),
        "scope": token_data.get("scope"),
        "refresh_token_received": bool(refresh_token)
    })


@app.route("/ml/status")
def ml_status():

    access_token = ML_TOKENS.get("access_token")

    if not access_token:
        return jsonify({
            "connected": False,
            "message": "Ainda não existe uma sessão OAuth ativa neste servidor."
        }), 503

    try:

        response = requests.get(
            "https://api.mercadolibre.com/users/me",
            headers={
                "Authorization": f"Bearer {access_token}"
            },
            timeout=20
        )

        if response.status_code != 200:
            return jsonify({
                "connected": False,
                "status_code": response.status_code
            }), response.status_code

        user = response.json()

        return jsonify({
            "connected": True,
            "user_id": user.get("id"),
            "nickname": user.get("nickname")
        })

    except Exception as e:

        return jsonify({
            "connected": False,
            "error": str(e)
        }), 500


@app.route("/notifications", methods=["GET", "POST"])
def notifications():

    # GET apenas para conseguirmos testar a URL no navegador.
    if request.method == "GET":
        return jsonify({
            "status": "ready",
            "endpoint": "Mercado Livre notifications"
        }), 200

    # Mercado Livre envia as notificações por POST.
    data = request.get_json(silent=True) or {}

    topic = data.get("topic")
    resource = data.get("resource")

    # Por enquanto apenas registramos o evento.
    # Na próxima etapa vamos processar pedidos, anúncios, estoque etc.
    print(
        "ML_NOTIFICATION",
        {
            "topic": topic,
            "resource": resource
        }
    )

    # Responder imediatamente ao Mercado Livre.
    return jsonify({
        "received": True
    }), 200


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000))
    )
