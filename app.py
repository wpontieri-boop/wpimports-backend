from flask import Flask, request, jsonify, redirect, render_template_string
import os
import requests
import psycopg
import hmac

from functools import wraps
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
ADMIN_USER = os.getenv("ADMIN_USER")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

# ============================================================
# SEGURANÇA ADMINISTRATIVA
# ============================================================

def require_admin(f):

    @wraps(f)
    def decorated(*args, **kwargs):

        auth = request.authorization

        user_ok = (
            auth
            and ADMIN_USER
            and hmac.compare_digest(
                auth.username or "",
                ADMIN_USER
            )
        )

        password_ok = (
            auth
            and ADMIN_PASSWORD
            and hmac.compare_digest(
                auth.password or "",
                ADMIN_PASSWORD
            )
        )

        if not user_ok or not password_ok:

            return (
                jsonify({
                    "success": False,
                    "error": "unauthorized"
                }),
                401,
                {
                    "WWW-Authenticate":
                        'Basic realm="WP Imports Admin"'
                }
            )

        return f(*args, **kwargs)

    return decorated


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
# PROTEÇÃO ADMINISTRATIVA DO WP IMPORTS HUB
# ============================================================

ADMIN_PROTECTED_PATHS = {
    "/ml/connect",
    "/ml/status",
    "/ml/items",
    "/ml/sync-items",

    "/db/status",
    "/db/items",

    "/admin/products", 
    "/erp/status",
    "/erp/import-ml-listings",
    "/erp/unlinked-listings",
}


@app.before_request
def protect_admin_routes():

    # Rotas públicas continuam funcionando normalmente
    if request.path not in ADMIN_PROTECTED_PATHS:
        return None

    admin_api_key = os.getenv("ADMIN_API_KEY")

    if not admin_api_key:
        return jsonify({
            "success": False,
            "error": "admin_key_not_configured"
        }), 503

    auth = request.authorization

    valid_login = (
        auth
        and auth.username == "admin"
        and hmac.compare_digest(
            auth.password or "",
            admin_api_key
        )
    )

    if not valid_login:

        response = jsonify({
            "success": False,
            "error": "unauthorized",
            "message": "Acesso administrativo necessario."
        })

        response.status_code = 401

        response.headers["WWW-Authenticate"] = (
            'Basic realm="WP Imports Hub Admin"'
        )

        return response

    return None

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
# ERP CENTRAL - PRODUTOS, UNIDADES E ANÚNCIOS
# ============================================================

def init_erp_tables():

    with get_db_connection() as conn:
        with conn.cursor() as cur:

            # Produto central / SKU
            cur.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id BIGSERIAL PRIMARY KEY,
                    internal_sku TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    brand TEXT,
                    model TEXT,
                    storage TEXT,
                    color TEXT,
                    condition_type TEXT NOT NULL,
                    condition_grade TEXT,
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            # Unidade física individual
            cur.execute("""
                CREATE TABLE IF NOT EXISTS product_units (
                    id BIGSERIAL PRIMARY KEY,
                    unit_code TEXT UNIQUE NOT NULL,
                    product_id BIGINT NOT NULL
                        REFERENCES products(id),

                    imei_1 TEXT,
                    imei_2 TEXT,
                    serial_number TEXT,

                    battery_health INTEGER,
                    cost NUMERIC(14,2),

                    status TEXT NOT NULL DEFAULT 'EM_ESTOQUE',

                    qr_token TEXT UNIQUE NOT NULL,

                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                ALTER TABLE products
                ADD COLUMN IF NOT EXISTS condition_type TEXT
            """)

            cur.execute("""
                ALTER TABLE products
                ADD COLUMN IF NOT EXISTS condition_grade TEXT
            """)

            cur.execute("""
                ALTER TABLE products
                DROP COLUMN IF EXISTS product_condition
            """)

            cur.execute("""
                ALTER TABLE products
                DROP CONSTRAINT IF EXISTS products_condition_type_check
            """)

            cur.execute("""
                ALTER TABLE products
                ADD CONSTRAINT products_condition_type_check
                CHECK (
                    condition_type IN (
                        'NOVO',
                        'CAIXA_ABERTA',
                        'RECONDICIONADO',
                        'SEMINOVO'
                    )
                )
            """)

            cur.execute("""
                ALTER TABLE products
                DROP CONSTRAINT IF EXISTS products_condition_grade_check
            """)

            cur.execute("""
                ALTER TABLE products
                ADD CONSTRAINT products_condition_grade_check
                CHECK (
                    condition_grade IS NULL
                    OR condition_grade IN (
                        'EXCELENTE',
                        'BOM',
                        'ACEITAVEL'
                    )
                )
            """)

            cur.execute("""
                ALTER TABLE products
                ALTER COLUMN condition_type SET NOT NULL
            """)

            cur.execute("""
                ALTER TABLE products
                DROP CONSTRAINT IF EXISTS products_condition_rules_check
            """)

            cur.execute("""
                ALTER TABLE products
                ADD CONSTRAINT products_condition_rules_check
                CHECK (
                    (
                        condition_type IN ('NOVO', 'CAIXA_ABERTA')
                        AND condition_grade IS NULL
                    )
                    OR
                    (
                        condition_type IN ('RECONDICIONADO', 'SEMINOVO')
                        AND condition_grade IN (
                            'EXCELENTE',
                            'BOM',
                            'ACEITAVEL'
                        )
                    )
                )
            """)
           
            # Anúncios dos marketplaces
            cur.execute("""
                CREATE TABLE IF NOT EXISTS marketplace_listings (
                    id BIGSERIAL PRIMARY KEY,

                    marketplace TEXT NOT NULL,

                    external_listing_id TEXT NOT NULL,

                    product_id BIGINT
                        REFERENCES products(id),

                    listing_type TEXT,
                    listing_role TEXT,
                    status TEXT,

                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

                    UNIQUE (
                        marketplace,
                        external_listing_id
                    )
                )
            """)


# ============================================================
# STATUS DA ESTRUTURA CENTRAL DO ERP
# ============================================================

@app.route("/erp/status")
def erp_status():

    try:

        init_erp_tables()

        with get_db_connection() as conn:
            with conn.cursor() as cur:

                cur.execute("SELECT COUNT(*) FROM products")
                products_count = cur.fetchone()[0]

                cur.execute(
                    "SELECT COUNT(*) FROM product_units"
                )
                units_count = cur.fetchone()[0]

                cur.execute(
                    "SELECT COUNT(*) FROM marketplace_listings"
                )
                listings_count = cur.fetchone()[0]

        return jsonify({
            "success": True,
            "erp": "WP Imports Hub",
            "database": "postgresql",
            "products": products_count,
            "units": units_count,
            "marketplace_listings": listings_count
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": "erp_database_error",
            "detail": str(e)
        }), 500

# ============================================================
# IMPORTAR ANÚNCIOS ML PARA A ESTRUTURA CENTRAL DO ERP
# ============================================================

@app.route("/erp/import-ml-listings")
def import_ml_listings():

    try:

        init_erp_tables()
        init_ml_items_table()

        with get_db_connection() as conn:
            with conn.cursor() as cur:

                cur.execute("""
                    SELECT
                        item_id,
                        listing_type,
                        status
                    FROM ml_items
                    ORDER BY item_id
                """)

                rows = cur.fetchall()

                imported = 0

                for row in rows:

                    item_id = row[0]
                    listing_type = row[1]
                    status = row[2]

                    cur.execute("""
                        INSERT INTO marketplace_listings (
                            marketplace,
                            external_listing_id,
                            listing_type,
                            status,
                            updated_at
                        )
                        VALUES (
                            'mercado_livre',
                            %s,
                            %s,
                            %s,
                            NOW()
                        )

                        ON CONFLICT (
                            marketplace,
                            external_listing_id
                        )
                        DO UPDATE SET
                            listing_type = EXCLUDED.listing_type,
                            status = EXCLUDED.status,
                            updated_at = NOW()
                    """, (
                        item_id,
                        listing_type,
                        status
                    ))

                    imported += 1

        return jsonify({
            "success": True,
            "marketplace": "mercado_livre",
            "imported_listings": imported
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": "ml_listings_import_failed",
            "detail": str(e)
        }), 500


# ============================================================
# ERP - ANÚNCIOS AINDA NÃO VINCULADOS A PRODUTOS
# ============================================================

@app.route("/erp/unlinked-listings")
def erp_unlinked_listings():

    try:

        init_erp_tables()
        init_ml_items_table()

        with get_db_connection() as conn:
            with conn.cursor() as cur:

                cur.execute("""
                    SELECT
                        ml.external_listing_id,
                        mi.title,
                        mi.price,
                        mi.stock,
                        mi.status,
                        mi.sku,
                        mi.listing_type,
                        mi.permalink
                    FROM marketplace_listings ml

                    LEFT JOIN ml_items mi
                        ON mi.item_id = ml.external_listing_id

                    WHERE
                        ml.marketplace = 'mercado_livre'
                        AND ml.product_id IS NULL

                    ORDER BY
                        mi.title ASC,
                        ml.external_listing_id ASC
                """)

                rows = cur.fetchall()

        listings = []

        for row in rows:

            listings.append({
                "listing_id": row[0],
                "title": row[1],
                "price":
                    float(row[2])
                    if row[2] is not None
                    else None,
                "stock": row[3],
                "status": row[4],
                "sku": row[5],
                "listing_type": row[6],
                "permalink": row[7]
            })

        return jsonify({
            "success": True,
            "marketplace": "mercado_livre",
            "unlinked_count": len(listings),
            "listings": listings
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": "unlinked_listings_failed",
            "detail": str(e)
        }), 500

# ============================================================
# WP IMPORTS HUB - TELA DE PRODUTOS CENTRAIS
# ============================================================

@app.route("/admin/products", methods=["GET", "POST"])
def admin_products():

    init_erp_tables()
    init_ml_items_table()

    error = None

    if request.method == "POST":

        internal_sku = (
            request.form.get("internal_sku") or ""
        ).strip()

        name = (
            request.form.get("name") or ""
        ).strip()

        brand = (
            request.form.get("brand") or ""
        ).strip() or None

        model = (
            request.form.get("model") or ""
        ).strip() or None

        storage = (
            request.form.get("storage") or ""
        ).strip() or None

        color = (
            request.form.get("color") or ""
        ).strip() or None

        product_condition = (
            request.form.get("product_condition") or ""
        ).strip() or None

        listing_ids = request.form.getlist(
            "listing_ids"
        )

        if not internal_sku:
            error = "Informe o SKU interno."

        elif not name:
            error = "Informe o nome do produto."

        elif not listing_ids:
            error = (
                "Selecione pelo menos um anúncio "
                "do Mercado Livre."
            )

        else:

            try:

                with get_db_connection() as conn:
                    with conn.cursor() as cur:

                        cur.execute("""
                            INSERT INTO products (
                                internal_sku,
                                name,
                                brand,
                                model,
                                storage,
                                color,
                                product_condition,
                                updated_at
                            )
                            VALUES (
                                %s, %s, %s, %s,
                                %s, %s, %s, NOW()
                            )
                            RETURNING id
                        """, (
                            internal_sku,
                            name,
                            brand,
                            model,
                            storage,
                            color,
                            product_condition
                        ))

                        product_id = cur.fetchone()[0]

                        cur.execute("""
                            UPDATE marketplace_listings

                            SET
                                product_id = %s,
                                updated_at = NOW()

                            WHERE
                                marketplace = 'mercado_livre'
                                AND product_id IS NULL
                                AND external_listing_id = ANY(%s)
                        """, (
                            product_id,
                            listing_ids
                        ))

                        linked_count = cur.rowcount

                return redirect(
                    "/admin/products"
                    f"?created={product_id}"
                    f"&linked={linked_count}"
                )

            except psycopg.errors.UniqueViolation:

                error = (
                    "Esse SKU interno já existe. "
                    "Escolha outro SKU."
                )

            except Exception as e:

                error = f"Erro ao criar produto: {str(e)}"

    created = request.args.get("created")
    linked = request.args.get("linked")

    with get_db_connection() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    ml.external_listing_id,
                    mi.title,
                    mi.price,
                    mi.stock,
                    mi.status,
                    mi.sku,
                    ml.listing_type,
                    mi.permalink

                FROM marketplace_listings ml

                LEFT JOIN ml_items mi
                    ON mi.item_id =
                       ml.external_listing_id

                WHERE
                    ml.marketplace = 'mercado_livre'
                    AND ml.product_id IS NULL

                ORDER BY
                    mi.title ASC NULLS LAST,
                    ml.external_listing_id ASC
            """)

            rows = cur.fetchall()

            cur.execute("""
                SELECT COUNT(*)
                FROM products
            """)

            products_count = cur.fetchone()[0]

    listings = []

    for row in rows:

        listings.append({
            "listing_id": row[0],
            "title": row[1],
            "price":
                float(row[2])
                if row[2] is not None
                else None,
            "stock": row[3],
            "status": row[4],
            "sku": row[5],
            "listing_type": row[6],
            "permalink": row[7]
        })

    html = """
    <!DOCTYPE html>

    <html lang="pt-BR">

    <head>

        <meta charset="UTF-8">

        <meta
            name="viewport"
            content="width=device-width, initial-scale=1"
        >

        <title>WP Imports Hub</title>

        <style>

            body {
                font-family: Arial, sans-serif;
                background: #f4f6f8;
                margin: 0;
                color: #1f2937;
            }

            .header {
                background: #111827;
                color: white;
                padding: 22px 30px;
            }

            .header h1 {
                margin: 0;
                font-size: 25px;
            }

            .header p {
                margin: 6px 0 0;
                color: #cbd5e1;
            }

            .container {
                max-width: 1450px;
                margin: 25px auto;
                padding: 0 20px;
            }

            .card {
                background: white;
                border-radius: 12px;
                padding: 22px;
                margin-bottom: 22px;
                box-shadow:
                    0 2px 10px rgba(0,0,0,.08);
            }

            .stats {
                display: flex;
                gap: 15px;
                flex-wrap: wrap;
            }

            .stat {
                background: #f8fafc;
                border: 1px solid #e5e7eb;
                border-radius: 10px;
                padding: 14px 20px;
            }

            .stat strong {
                display: block;
                font-size: 24px;
            }

            .grid {
                display: grid;
                grid-template-columns:
                    repeat(4, minmax(180px, 1fr));
                gap: 15px;
            }

            label {
                font-weight: bold;
                display: block;
                margin-bottom: 5px;
            }

            input,
            select {
                box-sizing: border-box;
                width: 100%;
                padding: 10px;
                border: 1px solid #cbd5e1;
                border-radius: 7px;
            }

            .search {
                margin: 18px 0;
                font-size: 16px;
            }

            table {
                width: 100%;
                border-collapse: collapse;
            }

            th,
            td {
                border-bottom: 1px solid #e5e7eb;
                padding: 10px;
                text-align: left;
                vertical-align: middle;
            }

            th {
                background: #f8fafc;
                position: sticky;
                top: 0;
            }

            .checkbox {
                width: 22px;
                height: 22px;
            }

            .table-wrap {
                max-height: 570px;
                overflow: auto;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
            }

            .btn {
                margin-top: 20px;
                background: #111827;
                color: white;
                padding: 13px 22px;
                border: 0;
                border-radius: 8px;
                font-size: 16px;
                cursor: pointer;
            }

            .success {
                background: #dcfce7;
                color: #166534;
                padding: 14px;
                border-radius: 8px;
                margin-bottom: 18px;
            }

            .error {
                background: #fee2e2;
                color: #991b1b;
                padding: 14px;
                border-radius: 8px;
                margin-bottom: 18px;
            }

            .small {
                font-size: 12px;
                color: #64748b;
            }

            .active {
                color: #15803d;
                font-weight: bold;
            }

            .paused {
                color: #b45309;
                font-weight: bold;
            }

            @media (max-width: 900px) {

                .grid {
                    grid-template-columns: 1fr 1fr;
                }

            }

        </style>

    </head>

    <body>

        <div class="header">

            <h1>WP IMPORTS HUB</h1>

            <p>
                Produtos centrais e anúncios
                do Mercado Livre
            </p>

        </div>

        <div class="container">

            <div class="card">

                <div class="stats">

                    <div class="stat">
                        <span>Produtos centrais</span>
                        <strong>
                            {{ products_count }}
                        </strong>
                    </div>

                    <div class="stat">
                        <span>Anúncios não vinculados</span>
                        <strong>
                            {{ listings|length }}
                        </strong>
                    </div>

                </div>

            </div>

            {% if created %}

                <div class="success">

                    ✅ Produto criado com sucesso.

                    ID interno:
                    <strong>{{ created }}</strong>

                    — anúncios vinculados:
                    <strong>{{ linked }}</strong>

                </div>

            {% endif %}

            {% if error %}

                <div class="error">
                    {{ error }}
                </div>

            {% endif %}

            <form method="POST">

                <div class="card">

                    <h2>
                        Criar produto central
                    </h2>

                    <p>
                        Um produto central pode possuir vários
                        anúncios no Mercado Livre.
                    </p>

                    <div class="grid">

                        <div>

                            <label>
                                SKU interno *
                            </label>

                            <input
                                name="internal_sku"
                                placeholder="Ex: WP-IPH16P-256-PT"
                                required
                            >

                        </div>

                        <div>

                            <label>
                                Nome do produto *
                            </label>

                            <input
                                name="name"
                                placeholder=
                                "iPhone 16 Pro 256GB Preto"
                                required
                            >

                        </div>

                        <div>

                            <label>Marca</label>

                            <input
                                name="brand"
                                placeholder="Apple"
                            >

                        </div>

                        <div>

                            <label>Modelo</label>

                            <input
                                name="model"
                                placeholder="iPhone 16 Pro"
                            >

                        </div>

                        <div>

                            <label>Capacidade</label>

                            <input
                                name="storage"
                                placeholder="256 GB"
                            >

                        </div>

                        <div>

                            <label>Cor</label>

                            <input
                                name="color"
                                placeholder="Preto"
                            >

                        </div>

                        <div>

                            <label>Condição</label>

                            <select name="product_condition">

                                <option value="">
                                    Selecione
                                </option>

                                <option value="NOVO">
                                    Novo
                                </option>

                                <option value="SEMINOVO">
                                    Seminovo
                                </option>

                            </select>

                        </div>

                    </div>

                </div>

                <div class="card">

                    <h2>
                        Vincular anúncios
                    </h2>

                    <p>
                        Marque somente os anúncios que representam
                        exatamente o mesmo produto físico.
                    </p>

                    <input
                        class="search"
                        type="text"
                        id="searchInput"
                        placeholder=
                        "Pesquisar iPhone, memória, cor..."
                        onkeyup="filterRows()"
                    >

                    <div class="table-wrap">

                        <table id="listingsTable">

                            <thead>

                                <tr>

                                    <th></th>
                                    <th>Produto</th>
                                    <th>Tipo</th>
                                    <th>Preço</th>
                                    <th>Estoque ML</th>
                                    <th>Status</th>
                                    <th>ID</th>

                                </tr>

                            </thead>

                            <tbody>

                                {% for item in listings %}

                                <tr>

                                    <td>

                                        <input
                                            class="checkbox"
                                            type="checkbox"
                                            name="listing_ids"
                                            value=
                                            "{{ item.listing_id }}"
                                        >

                                    </td>

                                    <td>

                                        <strong>
                                            {{ item.title }}
                                        </strong>

                                        {% if item.sku %}

                                            <div class="small">

                                                SKU ML:
                                                {{ item.sku }}

                                            </div>

                                        {% endif %}

                                    </td>

                                    <td>
                                        {{ item.listing_type }}
                                    </td>

                                    <td>

                                        {% if item.price is not none %}

                                            R$
                                            {{ "%.2f"|format(item.price) }}

                                        {% endif %}

                                    </td>

                                    <td>
                                        {{ item.stock }}
                                    </td>

                                    <td
                                        class=
                                        "{{ item.status }}"
                                    >
                                        {{ item.status }}
                                    </td>

                                    <td>

                                        {% if item.permalink %}

                                            <a
                                                href=
                                                "{{ item.permalink }}"
                                                target="_blank"
                                            >
                                                {{ item.listing_id }}
                                            </a>

                                        {% else %}

                                            {{ item.listing_id }}

                                        {% endif %}

                                    </td>

                                </tr>

                                {% endfor %}

                            </tbody>

                        </table>

                    </div>

                    <button
                        class="btn"
                        type="submit"
                    >
                        Criar produto e vincular anúncios
                    </button>

                </div>

            </form>

        </div>

        <script>

            function filterRows() {

                const input =
                    document
                    .getElementById("searchInput")
                    .value
                    .toLowerCase();

                const rows =
                    document
                    .querySelectorAll(
                        "#listingsTable tbody tr"
                    );

                rows.forEach(row => {

                    const text =
                        row.innerText.toLowerCase();

                    row.style.display =
                        text.includes(input)
                        ? ""
                        : "none";

                });

            }

        </script>

    </body>

    </html>
    """

    return render_template_string(
        html,
        listings=listings,
        products_count=products_count,
        error=error,
        created=created,
        linked=linked
    )
# ============================================================
# NOTIFICAÇÕES MERCADO LIVRE
# ============================================================
# ============================================================
# SINCRONIZAÇÃO DOS ANÚNCIOS COM O POSTGRESQL
# ============================================================

def init_ml_items_table():

    with get_db_connection() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                CREATE TABLE IF NOT EXISTS ml_items (
                    item_id TEXT PRIMARY KEY,
                    seller_id BIGINT NOT NULL,
                    title TEXT,
                    price NUMERIC(14,2),
                    stock INTEGER,
                    status TEXT,
                    sku TEXT,
                    listing_type TEXT,
                    permalink TEXT,
                    thumbnail TEXT,
                    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)


def save_ml_items_to_db(items, seller_id):

    init_ml_items_table()

    with get_db_connection() as conn:
        with conn.cursor() as cur:

            for item in items:

                cur.execute("""
                    INSERT INTO ml_items (
                        item_id,
                        seller_id,
                        title,
                        price,
                        stock,
                        status,
                        sku,
                        listing_type,
                        permalink,
                        thumbnail,
                        synced_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        NOW()
                    )

                    ON CONFLICT (item_id)
                    DO UPDATE SET
                        seller_id = EXCLUDED.seller_id,
                        title = EXCLUDED.title,
                        price = EXCLUDED.price,
                        stock = EXCLUDED.stock,
                        status = EXCLUDED.status,
                        sku = EXCLUDED.sku,
                        listing_type = EXCLUDED.listing_type,
                        permalink = EXCLUDED.permalink,
                        thumbnail = EXCLUDED.thumbnail,
                        synced_at = NOW()
                """, (
                    item.get("id"),
                    seller_id,
                    item.get("title"),
                    item.get("price"),
                    item.get("available_quantity"),
                    item.get("status"),
                    item.get("seller_custom_field"),
                    item.get("listing_type_id"),
                    item.get("permalink"),
                    item.get("thumbnail")
                ))


@app.route("/ml/sync-items")
def ml_sync_items():

    try:

        access_token = get_valid_access_token()

        if not access_token:
            return jsonify({
                "success": False,
                "error": "mercado_livre_not_connected"
            }), 503

        token_record = get_saved_tokens()

        if not token_record:
            return jsonify({
                "success": False,
                "error": "seller_not_found"
            }), 503

        seller_id = token_record[0]

        offset = 0
        limit = 50

        total_found = 0
        total_saved = 0

        while True:

            search_response = requests.get(
                f"https://api.mercadolibre.com/users/{seller_id}/items/search",
                headers={
                    "Authorization": f"Bearer {access_token}"
                },
                params={
                    "limit": limit,
                    "offset": offset
                },
                timeout=30
            )

            if search_response.status_code != 200:
                return jsonify({
                    "success": False,
                    "error": "items_search_failed",
                    "status_code": search_response.status_code
                }), search_response.status_code

            search_data = search_response.json()

            item_ids = search_data.get("results", [])
            paging = search_data.get("paging", {})

            total_found = paging.get(
                "total",
                total_found
            )

            if not item_ids:
                break

            raw_items = []

            # Mercado Livre permite até 20 itens por Multiget
            for i in range(0, len(item_ids), 20):

                batch_ids = item_ids[i:i + 20]

                details_response = requests.get(
                    "https://api.mercadolibre.com/items",
                    headers={
                        "Authorization":
                            f"Bearer {access_token}"
                    },
                    params={
                        "ids": ",".join(batch_ids),
                        "attributes": (
                            "id,title,price,available_quantity,"
                            "status,seller_custom_field,permalink,"
                            "thumbnail,listing_type_id"
                        )
                    },
                    timeout=30
                )

                if details_response.status_code != 200:
                    return jsonify({
                        "success": False,
                        "error": "items_details_failed",
                        "status_code":
                            details_response.status_code
                    }), details_response.status_code

                raw_items.extend(
                    details_response.json()
                )

            items_to_save = []

            for entry in raw_items:

                if entry.get("code") != 200:
                    continue

                body = entry.get("body", {})

                if body.get("id"):
                    items_to_save.append(body)

            save_ml_items_to_db(
                items_to_save,
                seller_id
            )

            total_saved += len(items_to_save)

            offset += len(item_ids)

            if offset >= total_found:
                break

        return jsonify({
            "success": True,
            "message":
                "Anuncios sincronizados com o PostgreSQL.",
            "total_found": total_found,
            "synced_items": total_saved
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": "sync_failed",
            "detail": str(e)
        }), 500


# ============================================================
# VISUALIZAR ANÚNCIOS SALVOS NO BANCO
# ============================================================

@app.route("/db/items")
def db_items():

    try:

        init_ml_items_table()

        with get_db_connection() as conn:
            with conn.cursor() as cur:

                cur.execute("""
                    SELECT
                        item_id,
                        title,
                        price,
                        stock,
                        status,
                        sku,
                        synced_at
                    FROM ml_items
                    ORDER BY synced_at DESC
                    LIMIT 50
                """)

                rows = cur.fetchall()

                cur.execute("""
                    SELECT COUNT(*)
                    FROM ml_items
                """)

                total = cur.fetchone()[0]

        items = []

        for row in rows:

            items.append({
                "id": row[0],
                "title": row[1],
                "price":
                    float(row[2])
                    if row[2] is not None
                    else None,
                "stock": row[3],
                "status": row[4],
                "sku": row[5],
                "synced_at":
                    row[6].isoformat()
                    if row[6]
                    else None
            })

        return jsonify({
            "success": True,
            "total_saved": total,
            "count": len(items),
            "items": items
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": "database_items_failed",
            "detail": str(e)
        }), 500
# ============================================================
# ANÚNCIOS DO MERCADO LIVRE - SOMENTE LEITURA
# ============================================================

@app.route("/ml/items")
def ml_items():

    try:
        access_token = get_valid_access_token()

        if not access_token:
            return jsonify({
                "success": False,
                "error": "mercado_livre_not_connected"
            }), 503

        token_record = get_saved_tokens()

        if not token_record:
            return jsonify({
                "success": False,
                "error": "seller_not_found"
            }), 503

        user_id = token_record[0]

        # Quantidade máxima por página
        try:
            limit = int(request.args.get("limit", 50))
        except ValueError:
            limit = 50

        limit = max(1, min(limit, 50))

        try:
            offset = int(request.args.get("offset", 0))
        except ValueError:
            offset = 0

        offset = max(0, offset)

        status = request.args.get("status")

        params = {
            "limit": limit,
            "offset": offset
        }

        if status:
            params["status"] = status

        search_response = requests.get(
            f"https://api.mercadolibre.com/users/{user_id}/items/search",
            headers={
                "Authorization": f"Bearer {access_token}"
            },
            params=params,
            timeout=30
        )

        if search_response.status_code != 200:
            return jsonify({
                "success": False,
                "error": "items_search_failed",
                "status_code": search_response.status_code
            }), search_response.status_code

        search_data = search_response.json()

        item_ids = search_data.get("results", [])
        paging = search_data.get("paging", {})

        if not item_ids:
            return jsonify({
                "success": True,
                "seller_id": user_id,
                "total": paging.get("total", 0),
                "offset": offset,
                "limit": limit,
                "count": 0,
                "items": []
            })
# O Multiget do Mercado Livre aceita no máximo
# 20 itens por chamada.
               # Busca os detalhes dos anúncios em lotes de até 20
        raw_items = []

        for i in range(0, len(item_ids), 20):

            batch_ids = item_ids[i:i + 20]

            items_response = requests.get(
                "https://api.mercadolibre.com/items",
                headers={
                    "Authorization": f"Bearer {access_token}"
                },
                params={
                    "ids": ",".join(batch_ids),
                    "attributes": (
                        "id,title,price,available_quantity,"
                        "status,seller_custom_field,permalink,"
                        "thumbnail,listing_type_id"
                    )
                },
                timeout=30
            )

            if items_response.status_code != 200:
                return jsonify({
                    "success": False,
                    "error": "items_details_failed",
                    "status_code": items_response.status_code
                }), items_response.status_code

            raw_items.extend(items_response.json())
        items = []

        for entry in raw_items:

            if entry.get("code") != 200:
                continue

            item = entry.get("body", {})

            items.append({
                "id": item.get("id"),
                "title": item.get("title"),
                "price": item.get("price"),
                "stock": item.get("available_quantity"),
                "status": item.get("status"),
                "sku": item.get("seller_custom_field"),
                "listing_type": item.get("listing_type_id"),
                "permalink": item.get("permalink"),
                "thumbnail": item.get("thumbnail")
            })

        return jsonify({
            "success": True,
            "seller_id": user_id,
            "total": paging.get("total", len(items)),
            "offset": paging.get("offset", offset),
            "limit": paging.get("limit", limit),
            "count": len(items),
            "items": items
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": "internal_error",
            "detail": str(e)
        }), 500
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
