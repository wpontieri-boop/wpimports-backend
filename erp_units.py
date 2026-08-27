from flask import Blueprint, jsonify, request, render_template_string
from decimal import Decimal, InvalidOperation
import secrets


def create_units_blueprint(get_db_connection):

    bp = Blueprint("erp_units", __name__)


    # ==========================================================
    # STATUS DAS UNIDADES FÍSICAS
    # ==========================================================

    @bp.route("/erp/units/status")
    def units_status():

        with get_db_connection() as conn:
            with conn.cursor() as cur:

                cur.execute("""
                    SELECT COUNT(*)
                    FROM product_units
                """)

                total = cur.fetchone()[0]

                cur.execute("""
                    SELECT COUNT(*)
                    FROM product_units
                    WHERE status = 'EM_ESTOQUE'
                """)

                in_stock = cur.fetchone()[0]

        return jsonify({
            "success": True,
            "module": "ERP Units",
            "total_units": total,
            "in_stock": in_stock
        })


    # ==========================================================
    # CRIAR UNIDADE FÍSICA
    # ==========================================================

    @bp.route("/erp/units/create", methods=["POST"])
    def create_unit():

        data = request.get_json(silent=True) or request.form

        product_id = data.get("product_id")

        imei_1 = (
            data.get("imei_1") or ""
        ).strip() or None

        imei_2 = (
            data.get("imei_2") or ""
        ).strip() or None

        serial_number = (
            data.get("serial_number") or ""
        ).strip() or None

        battery_health = data.get("battery_health")

        cost = data.get("cost")


        if not product_id:
            return jsonify({
                "success": False,
                "error": "product_id_required"
            }), 400


        try:
            product_id = int(product_id)

        except (TypeError, ValueError):

            return jsonify({
                "success": False,
                "error": "invalid_product_id"
            }), 400


        if battery_health not in (None, ""):

            try:
                battery_health = int(battery_health)

            except (TypeError, ValueError):

                return jsonify({
                    "success": False,
                    "error": "invalid_battery_health"
                }), 400

            if battery_health < 0 or battery_health > 100:

                return jsonify({
                    "success": False,
                    "error": "battery_health_out_of_range"
                }), 400

        else:
            battery_health = None


        if cost not in (None, ""):

            try:
                cost = Decimal(str(cost))

            except InvalidOperation:

                return jsonify({
                    "success": False,
                    "error": "invalid_cost"
                }), 400

        else:
            cost = None


        qr_token = secrets.token_urlsafe(24)

        temporary_unit_code = (
            "TMP-" + secrets.token_hex(8).upper()
        )


        with get_db_connection() as conn:

            with conn.cursor() as cur:

                cur.execute("""
                    SELECT id
                    FROM products
                    WHERE id = %s
                    AND active = TRUE
                """, (
                    product_id,
                ))

                product = cur.fetchone()

                if not product:

                    return jsonify({
                        "success": False,
                        "error": "product_not_found"
                    }), 404


                cur.execute("""
                    INSERT INTO product_units (
                        unit_code,
                        product_id,
                        imei_1,
                        imei_2,
                        serial_number,
                        battery_health,
                        cost,
                        status,
                        qr_token,
                        updated_at
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        'EM_ESTOQUE',
                        %s,
                        NOW()
                    )
                    RETURNING id
                """, (
                    temporary_unit_code,
                    product_id,
                    imei_1,
                    imei_2,
                    serial_number,
                    battery_health,
                    cost,
                    qr_token
                ))

                unit_id = cur.fetchone()[0]

                unit_code = (
                    f"WP-U-{unit_id:06d}"
                )

                cur.execute("""
                    UPDATE product_units
                    SET
                        unit_code = %s,
                        updated_at = NOW()
                    WHERE id = %s
                """, (
                    unit_code,
                    unit_id
                ))


        return jsonify({
            "success": True,
            "message": "Unidade física criada.",
            "unit_id": unit_id,
            "unit_code": unit_code,
            "product_id": product_id,
            "status": "EM_ESTOQUE",
            "qr_token": qr_token
        }), 201


    # ==========================================================
    # CONSULTAR UNIDADE PELO QR
    # ==========================================================

    @bp.route("/erp/units/qr/<qr_token>")
    def unit_by_qr(qr_token):

        with get_db_connection() as conn:

            with conn.cursor() as cur:

                cur.execute("""
                    SELECT
                        pu.id,
                        pu.unit_code,
                        pu.product_id,
                        p.internal_sku,
                        p.name,
                        p.brand,
                        p.model,
                        p.storage,
                        p.color,
                        p.condition_type,
                        p.condition_grade,
                        pu.imei_1,
                        pu.imei_2,
                        pu.serial_number,
                        pu.battery_health,
                        pu.status
                    FROM product_units pu

                    JOIN products p
                        ON p.id = pu.product_id

                    WHERE pu.qr_token = %s
                """, (
                    qr_token,
                ))

                row = cur.fetchone()


        if not row:

            return jsonify({
                "success": False,
                "error": "unit_not_found"
            }), 404


        return jsonify({
            "success": True,
            "unit": {
                "id": row[0],
                "unit_code": row[1],
                "product_id": row[2],
                "sku": row[3],
                "product": row[4],
                "brand": row[5],
                "model": row[6],
                "storage": row[7],
                "color": row[8],
                "condition_type": row[9],
                "condition_grade": row[10],
                "imei_1": row[11],
                "imei_2": row[12],
                "serial_number": row[13],
                "battery_health": row[14],
                "status": row[15]
            }
        })
    # ==========================================================
    # PWA - ENTRADA DE APARELHO
    # ==========================================================

    @bp.route("/erp/units/entry")
    def unit_entry_page():

        with get_db_connection() as conn:
            with conn.cursor() as cur:

                cur.execute("""
                    SELECT
                        id,
                        internal_sku,
                        name,
                        condition_type,
                        condition_grade
                    FROM products
                    WHERE active = TRUE
                    ORDER BY name
                """)

                products = cur.fetchall()

        html = """
        <!DOCTYPE html>
        <html lang="pt-BR">

        <head>
            <meta charset="UTF-8">
            <meta
                name="viewport"
                content="width=device-width, initial-scale=1.0"
            >

            <title>WP Imports - Entrada</title>

            <style>
                body {
                    font-family: Arial, sans-serif;
                    background: #f5f5f5;
                    margin: 0;
                    padding: 20px;
                }

                .container {
                    max-width: 600px;
                    margin: auto;
                    background: white;
                    padding: 24px;
                    border-radius: 18px;
                    box-shadow: 0 4px 20px rgba(0,0,0,.10);
                }

                h1 {
                    margin-top: 0;
                }

                label {
                    display: block;
                    font-weight: bold;
                    margin-top: 16px;
                    margin-bottom: 6px;
                }

                input,
                select {
                    width: 100%;
                    box-sizing: border-box;
                    padding: 14px;
                    font-size: 16px;
                    border: 1px solid #ccc;
                    border-radius: 10px;
                }

                button {
                    width: 100%;
                    margin-top: 22px;
                    padding: 16px;
                    border: 0;
                    border-radius: 12px;
                    font-size: 17px;
                    font-weight: bold;
                    cursor: pointer;
                }

                .photo {
                    background: #222;
                    color: white;
                }

                .save {
                    background: #111;
                    color: white;
                }

                .hint {
                    color: #666;
                    font-size: 14px;
                    margin-top: 6px;
                }
            </style>
        </head>

        <body>

            <div class="container">

                <h1>Entrada de aparelho</h1>

                <p>
                    WP Imports Hub
                </p>

                <label>Foto do aparelho / etiqueta</label>

                <input
                    type="file"
                    id="device_photo"
                    accept="image/*"
                    capture="environment"
                >

                <div class="hint">
                    A leitura automática por IA será conectada
                    no próximo passo.
                </div>

                <label>Produto central</label>

                <select id="product_id">

                    <option value="">
                        Selecione o produto
                    </option>

                    {% for product in products %}

                        <option value="{{ product[0] }}">
                            {{ product[2] }}
                            -
                            {{ product[1] }}

                            {% if product[3] %}
                                - {{ product[3] }}
                            {% endif %}

                            {% if product[4] %}
                                / {{ product[4] }}
                            {% endif %}
                        </option>

                    {% endfor %}

                </select>

                <label>IMEI 1</label>
                <input id="imei_1" inputmode="numeric">

                <label>IMEI 2</label>
                <input id="imei_2" inputmode="numeric">

                <label>Número de série</label>
                <input id="serial_number">

                <label>Saúde da bateria (%)</label>
                <input
                    id="battery_health"
                    type="number"
                    min="0"
                    max="100"
                >

                <label>Custo</label>
                <input
                    id="cost"
                    type="number"
                    step="0.01"
                >

                <button
                    class="save"
                    onclick="saveUnit()"
                >
                    Criar unidade e QR Code
                </button>

                <div
                    id="result"
                    style="margin-top:20px;"
                ></div>

            </div>


            <script>

                async function saveUnit() {

                    const payload = {
                        product_id:
                            document.getElementById(
                                "product_id"
                            ).value,

                        imei_1:
                            document.getElementById(
                                "imei_1"
                            ).value,

                        imei_2:
                            document.getElementById(
                                "imei_2"
                            ).value,

                        serial_number:
                            document.getElementById(
                                "serial_number"
                            ).value,

                        battery_health:
                            document.getElementById(
                                "battery_health"
                            ).value,

                        cost:
                            document.getElementById(
                                "cost"
                            ).value
                    };


                    const response = await fetch(
                        "/erp/units/create",
                        {
                            method: "POST",

                            headers: {
                                "Content-Type":
                                    "application/json"
                            },

                            body: JSON.stringify(payload)
                        }
                    );


                    const data = await response.json();

                    const result =
                        document.getElementById(
                            "result"
                        );


                    if (data.success) {

                        result.innerHTML =
                            "<b>Unidade criada:</b> "
                            + data.unit_code
                            + "<br><b>Status:</b> "
                            + data.status;

                    } else {

                        result.innerHTML =
                            "<b>Erro:</b> "
                            + (
                                data.error ||
                                "Não foi possível criar."
                            );
                    }
                }

            </script>

        </body>
        </html>
        """

        return render_template_string(
            html,
            products=products
        )

    return bp
