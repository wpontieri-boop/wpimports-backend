from flask import Blueprint, jsonify, request
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


    return bp
