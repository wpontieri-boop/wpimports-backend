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
                        model,
                        storage
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

                <label>Foto 1 — IMEI 1 e IMEI 2</label>
                
                <input
                    type="file"
                    id="device_photo"
                    accept="image/*"
                    capture="environment"
                >
                
                <div class="hint">
                    Use a tela onde aparecem IMEI e IMEI2.
                </div>
                
                <label style="margin-top:18px;">
                    Foto 2 — Modelo e número de série
                </label>
                
                <input
                    type="file"
                    id="model_serial_photo"
                    accept="image/*"
                    capture="environment"
                >
                
                <div class="hint">
                    Use a tela das Configurações onde aparecem
                    o modelo e o número de série.
                </div>

                <label>Produto central</label>

                <select id="product_id">

                    <option value="">
                        Selecione o produto
                    </option>

                    {% for product in products %}

                        <option
                            value="{{ product[0] }}"
                            data-model="{{ product[5] or '' }}"
                            data-storage="{{ product[6] or '' }}"
                        >
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

<script src="https://cdn.jsdelivr.net/npm/tesseract.js@7/dist/tesseract.min.js"></script>

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
        const devicePhoto = document.getElementById("device_photo");

        function onlyDigits(value) {
            return (value || "").replace(/\D/g, "");
        }

        function normalizeOcrDigits(value) {
            return (value || "")
                .replace(/[OQ]/gi, "0")
                .replace(/[IL|]/gi, "1")
                .replace(/\D/g, "");
        }

        function validImei(imei) {
            if (!/^\d{15}$/.test(imei)) {
                return false;
            }

            let sum = 0;

            for (let i = 0; i < 15; i++) {
                let digit = parseInt(imei[i], 10);

                if (i % 2 === 1) {
                    digit *= 2;

                    if (digit > 9) {
                        digit -= 9;
                    }
                }

                sum += digit;
            }

            return sum % 10 === 0;
        }

function findImeis(text) {

            const imeis = [];

            function addImei(value) {

                if (!value) {
                    return;
                }

                const digits = normalizeOcrDigits(value);

                if (digits.length < 15) {
                    return;
                }

                /*
                 * Percorre possíveis blocos de 15 dígitos.
                 * Assim conseguimos recuperar o IMEI mesmo quando
                 * o OCR trouxe algum caractere ou número extra.
                 */
                for (
                    let start = 0;
                    start <= digits.length - 15;
                    start++
                ) {

                    const imei =
                        digits.substring(
                            start,
                            start + 15
                        );

                    if (
                        validImei(imei) &&
                        !imeis.includes(imei)
                    ) {
                        imeis.push(imei);
                    }

                    if (imeis.length >= 2) {
                        return;
                    }
                }
            }

            /*
             * PRIMEIRO:
             * procura especificamente o número
             * que aparece depois de IMEI 1.
             */
            const imei1Patterns = [
                /IMEI\s*1\s*[:\-]?\s*([0-9OQIL|\s\-]{15,45})/i,
                /IMEI1\s*[:\-]?\s*([0-9OQIL|\s\-]{15,45})/i
            ];

            for (const pattern of imei1Patterns) {

                const match = text.match(pattern);

                if (match && match[1]) {
                    addImei(match[1]);
                }

                if (imeis.length >= 1) {
                    break;
                }
            }

            /*
             * SEGUNDO:
             * procura especificamente o número
             * que aparece depois de IMEI 2.
             */
            const imei2Patterns = [
                /IMEI\s*2\s*[:\-]?\s*([0-9OQIL|\s\-]{15,45})/i,
                /IMEI2\s*[:\-]?\s*([0-9OQIL|\s\-]{15,45})/i
            ];

            for (const pattern of imei2Patterns) {

                const match = text.match(pattern);

                if (match && match[1]) {
                    addImei(match[1]);
                }

                if (imeis.length >= 2) {
                    break;
                }
            }

            /*
             * PLANO B:
             * se o OCR não reconheceu os textos
             * "IMEI 1" ou "IMEI 2", procura todos
             * os números candidatos existentes na foto.
             */
            if (imeis.length < 2) {

                const candidates =
                    text.match(
                        /(?:[0-9OQIL|][\s\-]*){15,20}/gi
                    ) || [];

                for (const candidate of candidates) {

                    addImei(candidate);

                    if (imeis.length >= 2) {
                        break;
                    }
                }
            }

            return imeis.slice(0, 2);
        }        

        function findSerialNumber(text) {

            const patterns = [
                /serial\s*(?:number|no|nº|#)?\s*[:\-]?\s*([A-Z0-9\-]{5,30})/i,
                /s\/n\s*[:\-]?\s*([A-Z0-9\-]{5,30})/i,
                /n[uú]mero\s+de\s+s[eé]rie\s*[:\-]?\s*([A-Z0-9\-]{5,30})/i
            ];

            for (const pattern of patterns) {

                const match = text.match(pattern);

                if (match && match[1]) {
                    return match[1]
                        .trim()
                        .toUpperCase();
                }
            }

            return "";
        }

        function findBatteryHealth(text) {

            const patterns = [
                /battery\s*health\s*[:\-]?\s*(\d{1,3})\s*%?/i,
                /sa[uú]de\s+da\s+bateria\s*[:\-]?\s*(\d{1,3})\s*%?/i,
                /maximum\s+capacity\s*[:\-]?\s*(\d{1,3})\s*%?/i,
                /capacidade\s+m[aá]xima\s*[:\-]?\s*(\d{1,3})\s*%?/i
            ];

            for (const pattern of patterns) {

                const match = text.match(pattern);

                if (match && match[1]) {

                    const value =
                        parseInt(
                            match[1],
                            10
                        );

                    if (
                        value >= 1 &&
                        value <= 100
                    ) {
                        return value;
                    }
                }
            }

            return "";
        }

        function normalizeProductText(value) {
            return (value || "")
                .toUpperCase()
                .replace(/\s+/g, "")
                .replace(/TB/g, "000GB")
                .replace(/[^A-Z0-9]/g, "");
        }

        function findStorage(text) {

            const normalized =
                (text || "").toUpperCase();

            const tb =
                normalized.match(
                    /\b([124])\s*TB\b/
                );

            if (tb) {
                return (
                    parseInt(tb[1], 10) *
                    1000
                ) + "GB";
            }

            const gb =
                normalized.match(
                    /\b(32|64|128|256|512)\s*GB\b/
                );

            if (gb) {
                return gb[1] + "GB";
            }

            return "";
        }
                
        function findProductFromPhoto(
            text,
            storage
        ) {

            const select =
                document.getElementById(
                    "product_id"
                );

            const normalizedText =
                normalizeProductText(text);

            const normalizedStorage =
                normalizeProductText(storage);

            let bestMatch = null;
            let detectedModel = "";

            for (
                const option of select.options
            ) {

                if (!option.value) {
                    continue;
                }

                const model =
                    option.dataset.model || "";

                const productStorage =
                    option.dataset.storage || "";

                if (!model) {
                    continue;
                }

                const normalizedModel =
                    normalizeProductText(model);

                const optionStorage =
                    normalizeProductText(
                        productStorage
                    );

                const modelFound =
                    normalizedText.includes(
                        normalizedModel
                    );

                const storageFound =
                    !normalizedStorage ||
                    optionStorage.includes(
                        normalizedStorage
                    );

                if (
                    modelFound &&
                    storageFound
                ) {
                    bestMatch = option;
                    detectedModel = model;
                    break;
                }
            }

            if (bestMatch) {
                select.value =
                    bestMatch.value;
            }

            return {
                found: Boolean(bestMatch),
                model: detectedModel
            };
        }

        devicePhoto.addEventListener(
            "change",
            async function () {

                const file = devicePhoto.files[0];

                if (!file) {
                    return;
                }

                const result =
                    document.getElementById("result");

                result.innerHTML =
                    "<b>📷 Lendo foto...</b><br>" +
                    "Aguarde alguns segundos.";

                try {

                    const ocrResult =
                        await Tesseract.recognize(
                            file,
                            "eng",
                            {
                                logger: function (m) {

                                    if (
                                        m.status ===
                                        "recognizing text"
                                    ) {

                                        const percent =
                                            Math.round(
                                                m.progress * 100
                                            );

                                        result.innerHTML =
                                            "<b>📷 Lendo foto...</b><br>" +
                                            percent + "%";
                                    }
                                }
                            }
                        );

                    const text =
                        ocrResult.data.text || "";
                    const storage =
                        findStorage(text);

                    const productMatch =
                        findProductFromPhoto(
                            text,
                            storage
                        );                        

                    console.log(
                        "OCR WP Imports:",
                        text
                    );

                    const imeis =
                        findImeis(text);

                    const serial =
                        findSerialNumber(text);

                    const battery =
                        findBatteryHealth(text);

                    if (imeis[0]) {
                        document
                            .getElementById("imei_1")
                            .value = imeis[0];
                    }

                    if (imeis[1]) {
                        document
                            .getElementById("imei_2")
                            .value = imeis[1];
                    }

                    if (serial) {
                        document
                            .getElementById(
                                "serial_number"
                            )
                            .value = serial;
                    }

                    if (battery) {
                        document
                            .getElementById(
                                "battery_health"
                            )
                            .value = battery;
                    }

                    let found = [];
                    if (productMatch.model) {
                        found.push(
                            "modelo " +
                            productMatch.model
                        );
                    }

                    if (storage) {
                        found.push(
                            storage
                        );
                    }                    

                    if (imeis.length) {
                        found.push(
                            imeis.length +
                            " IMEI(s)"
                        );
                    }

                    if (serial) {
                        found.push("serial");
                    }

                    if (battery) {
                        found.push(
                            "bateria " +
                            battery +
                            "%"
                        );
                    }

                    if (found.length) {

                        result.innerHTML =
                            "<b>✅ Foto analisada.</b><br>" +
                            "Encontrado: " +
                            found.join(", ") +
                            ".<br>" +
                            "Confira os dados antes de salvar.";

                    } else {

                        result.innerHTML =
                            "<b>⚠️ Foto lida, mas não consegui identificar os dados.</b><br>" +
                            "Tente outra foto mais próxima e sem reflexo.";
                    }

                } catch (error) {

                    console.error(
                        "Erro OCR:",
                        error
                    );

                    result.innerHTML =
                        "<b>Erro ao ler a foto.</b><br>" +
                        "Tente novamente.";
                }
            }
        ); 

        
const modelSerialPhoto =
    document.getElementById("model_serial_photo");


function normalizeOcrText(value) {
    return (value || "")
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .toUpperCase()
        .replace(/[^A-Z0-9]+/g, " ")
        .replace(/\s+/g, " ")
        .trim();
}


function autoSelectProductFromText(text) {

    const select =
        document.getElementById("product_id");

    if (!select) {
        return "";
    }

    const normalizedText =
        normalizeOcrText(text);

    const storage =
        findStorage(text);

    let bestOption = null;
    let bestScore = 0;

    for (const option of select.options) {

        if (!option.value) {
            continue;
        }

        const optionText =
            normalizeOcrText(
                option.textContent || ""
            );

        const tokens =
            optionText
                .split(" ")
                .filter(
                    token =>
                        token.length >= 2 &&
                        ![
                            "APPLE",
                            "GB",
                            "NOVO",
                            "SEMINOVO",
                            "RECONDICIONADO",
                            "CAIXA",
                            "ABERTA"
                        ].includes(token)
                );

        let score = 0;

        for (const token of tokens) {
            if (normalizedText.includes(token)) {
                score += 2;
            }
        }

        if (
            storage &&
            optionText.includes(
                normalizeOcrText(storage)
            )
        ) {
            score += 4;
        }

        if (score > bestScore) {
            bestScore = score;
            bestOption = option;
        }
    }

    if (bestOption && bestScore >= 4) {

        select.value =
            bestOption.value;

        return (
            bestOption.textContent || ""
        ).trim();
    }

    return "";
}


if (modelSerialPhoto) {

    modelSerialPhoto.addEventListener(
        "change",
        async function () {

            const file =
                this.files &&
                this.files[0];

            if (!file) {
                return;
            }

            const result =
                document.getElementById(
                    "result"
                );

            result.innerHTML =
                "<b>📷 Lendo Foto 2...</b><br>" +
                "Procurando modelo e número de série.";

            try {

                const ocrResult =
                    await Tesseract.recognize(
                        file,
                        "eng",
                        {
                            logger: function (m) {

                                if (
                                    m.status ===
                                    "recognizing text"
                                ) {

                                    const percent =
                                        Math.round(
                                            m.progress *
                                            100
                                        );

                                    result.innerHTML =
                                        "<b>📷 Lendo Foto 2...</b><br>" +
                                        percent +
                                        "%";
                                }
                            }
                        }
                    );

                const text =
                    ocrResult.data.text || "";

                const serial =
                    findSerialNumber(text);

                const selectedProduct =
                    autoSelectProductFromText(
                        text
                    );

                if (serial) {

                    document
                        .getElementById(
                            "serial_number"
                        )
                        .value = serial;
                }

                const found = [];

                if (serial) {
                    found.push(
                        "Número de série"
                    );
                }

                if (selectedProduct) {
                    found.push(
                        "Produto selecionado: " +
                        selectedProduct
                    );
                }

                if (found.length) {

                    result.innerHTML =
                        "<b>✅ Foto 2 analisada.</b><br>" +
                        found.join("<br>") +
                        "<br><br>Confira os dados antes de salvar.";

                } else {

                    result.innerHTML =
                        "<b>⚠️ Foto lida, mas não consegui identificar modelo ou número de série.</b><br>" +
                        "Tire outra foto mais próxima da tela.";
                }

            } catch (error) {

                console.error(
                    "Erro OCR Foto 2:",
                    error
                );

                result.innerHTML =
                    "<b>Erro ao ler a Foto 2.</b><br>" +
                    "Tente novamente.";
            }
        }
    );
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
