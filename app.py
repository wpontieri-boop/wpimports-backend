from flask import Flask, request, jsonify, redirect
import os
import requests
import psycopg

from urllib.parse import urlencode
from datetime import datetime, timezone, timedelta


app = Flask(__name__)


# ============================================================
# CONFIGURAÇÕES
# ============================================================

ML_CLIENT_ID = os.getenv("ML_CLIENT_ID")
ML_CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET")
ML_REDIRECT_URI = os.getenv("ML_REDIRECT_URI")
DATABASE_URL = os.getenv("DATABASE_URL")


# ============================================================
# BANCO DE DADOS
# ============================================================

def get_db_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL não configurada.")

    return psycopg.connect(DATABASE_URL)


def init_db():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ml_tokens (
                    user_id BIGINT PRIMARY KEY,
                    access_token TEXT NOT NULL,
                    refresh_token TEXT NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    scope TEXT,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)


def save_tokens(
    token_data,
    fallback_user_id=None,
    fallback_refresh_token=None,
    fallback_scope=None
):
    access_token = token_data.get("access_token")

    refresh_token = (
        token_data.get("refresh_token")
        or fallback_refresh_token
    )

    user_id = (
        token_data.get("user_id")
        or fallback_user_id
    )

    scope = (
        token_data.get("scope")
        or fallback_scope
    )

    expires_in = int(
        token_data.get("expires_in") or 21600
    )

    if not access_token:
        raise RuntimeError("Access token não recebido.")

    if not refresh_token:
        raise RuntimeError("Refresh token não recebido.")

    if not user_id:
        raise RuntimeError("User ID do Mercado Livre não recebido.")

    expires_at = (
        datetime.now(timezone.utc)
        + timedelta(seconds=expires_in)
    )

    init_db()

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ml_tokens (
                    user_id,
                    access_token,
                    refresh_token,
                    expires_at,
                    scope,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, NOW())

                ON CONFLICT (user_id)
                DO UPDATE SET
                    access_token = EXCLUDED.access_token,
                    refresh_token = EXCLUDED.refresh_token,
                    expires_at = EXCLUDED.expires_at,
                    scope = EXCLUDED.scope,
                    updated_at = NOW()
            """, (
                user_id,
                access_token,
                refresh_token,
                expires_at,
                scope
            ))

    return user_id


def get_saved_tokens():
    init_db()

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    user_id,
                    access_token,
                    refresh_token,
                    expires_at,
                    scope
                FROM ml_tokens
                ORDER BY updated_at DESC
                LIMIT 1
            """)

            return cur.fetchone()


# ============================================================
# RENOVAÇÃO AUTOMÁTICA DO TOKEN
# ============================================================

def refresh_mercado_livre_token(token_record):

    user_id = token_record[0]
    old_refresh_token = token_record[2]
    old_scope = token_record[4]

    payload = {
        "grant_type": "refresh_token",
        "client_id": ML_CLIENT_ID,
        "client_secret": ML_CLIENT_SECRET,
        "refresh_token": old_refresh_token
    }

    response = requests.post(
        "https://api.mercadolibre.com/oauth/token",
        data=payload,
        headers={
            "accept": "application/json",
            "content-type": "application/x-www-form-urlencoded"
        },
        timeout=20
    )

    try:
        token_data = response.json()
    except Exception:
        raise RuntimeError(
            f"Erro ao renovar token. HTTP {response.status_code}"
        )

    if response.status_code != 200:
        raise RuntimeError(
            f"Mercado Livre recusou renovação. HTTP {response.status_code}"
        )

    save_tokens(
        token_data,
        fallback_user_id=user_id,
        fallback_refresh_token=old_refresh_token,
        fallback_scope=old_scope
    )

    return token_data.get("access_token")


def get_valid_access_token():

    token_record = get_saved_tokens()

    if not token_record:
        return None

    access_token = token_record[1]
    expires_at = token_record[3]

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(
            tzinfo=timezone.utc
        )

    # Renova 5 minutos antes de vencer
    renew_before = (
        datetime.now(timezone.utc)
        + timedelta(minutes=5)
    )

    if expires_at > renew_before:
        return access_token

    return refresh_mercado_livre_token(
        token_record
    )


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():
    return jsonify({
        "app": "WP Imports Backend",
        "status": "online",
        "version": "1.2",
        "mercado_livre": "integration_ready",
        "database": "postgresql",
        "time": datetime.now(timezone.utc).isoformat()
    })


# ============================================================
# HEALTH
# ============================================================

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "wpimports-backend"
    })


# ============================================================
# STATUS DO BANCO
# ============================================================

@app.route("/db/status")
def db_status():

    try:
        init_db()

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM ml_tokens"
                )

                total = cur.fetchone()[0]

        return jsonify({
            "connected": True,
            "database": "postgresql",
            "saved_ml_accounts": total
        })

    except Exception as e:
        return jsonify({
            "connected": False,
            "error": str(e)
        }), 500


# ============================================================
# CONECTAR MERCADO LIVRE
# ============================================================

@app.route("/ml/connect")
def ml_connect():

    if not ML_CLIENT_ID or not ML_REDIRECT_URI:
        return jsonify({
            "error": "missing_configuration"
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


# ============================================================
# CALLBACK MERCADO LIVRE
# ============================================================

@app.route("/callback")
def callback():

    error = request.args.get("error")

    if error:
        return jsonify({
            "connected": False,
            "error": error,
            "description": request.args.get(
                "error_description"
            )
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

    if (
        not ML_CLIENT_ID
        or not ML_CLIENT_SECRET
        or not ML_REDIRECT_URI
    ):
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
                "content-type":
                    "application/x-www-form-urlencoded"
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
            "status_code": response.status_code
        }), response.status_code

    try:
        user_id = save_tokens(token_data)

    except Exception as e:
        return jsonify({
            "connected": False,
            "error": "database_save_failed",
            "detail": str(e)
        }), 500

    access_token = token_data.get(
        "access_token"
    )

    nickname = None

    try:

        user_response = requests.get(
            "https://api.mercadolibre.com/users/me",
            headers={
                "Authorization":
                    f"Bearer {access_token}"
            },
            timeout=20
        )

        if user_response.status_code == 200:
            nickname = (
                user_response
                .json()
                .get("nickname")
            )

    except Exception:
        pass

    return jsonify({
        "connected": True,
        "message":
            "Mercado Livre conectado com sucesso ao WP Imports.",
        "user_id": user_id,
        "nickname": nickname,
        "token_storage": "postgresql",
        "automatic_refresh": True,
        "refresh_token_received":
            bool(token_data.get("refresh_token"))
    })


# ============================================================
# STATUS MERCADO LIVRE
# ============================================================

@app.route("/ml/status")
def ml_status():

    try:
        access_token = get_valid_access_token()

        if not access_token:
            return jsonify({
                "connected": False,
                "message":
                    "Nenhuma conta do Mercado Livre salva no banco."
            }), 503

        response = requests.get(
            "https://api.mercadolibre.com/users/me",
            headers={
                "Authorization":
                    f"Bearer {access_token}"
            },
            timeout=20
        )

        if response.status_code != 200:
            return jsonify({
                "connected": False,
                "status_code":
                    response.status_code
            }), response.status_code

        user = response.json()

        return jsonify({
            "connected": True,
            "user_id": user.get("id"),
            "nickname": user.get("nickname"),
            "token_storage": "postgresql",
            "automatic_refresh": True
        })

    except Exception as e:
        return jsonify({
            "connected": False,
            "error": str(e)
        }), 500


# ============================================================
# NOTIFICAÇÕES MERCADO LIVRE
# ============================================================

@app.route(
    "/notifications",
    methods=["GET", "POST"]
)
def notifications():

    if request.method == "GET":
        return jsonify({
            "status": "ready",
            "endpoint":
                "Mercado Livre notifications"
        }), 200

    data = request.get_json(
        silent=True
    ) or {}

    topic = data.get("topic")
    resource = data.get("resource")

    print(
        "ML_NOTIFICATION",
        {
            "topic": topic,
            "resource": resource
        }
    )

    return jsonify({
        "received": True
    }), 200


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(
            os.getenv("PORT", 5000)
        )
    )
