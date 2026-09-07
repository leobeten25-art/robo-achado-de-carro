import os
import re
import json
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

from flask import Flask, render_template, request, jsonify
from google import genai
from google.genai import types


APP_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DB_PATH", APP_DIR / "achado_carro.db"))

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
META_DIARIA = 40

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024


COPYWRITER_RULES = """
Você é o copywriter oficial do Achado de Carro, um perfil de ofertas e produtos
voltado para homens que gostam do universo automotivo.

Crie UMA headline curta, criativa, provocativa e vendedora sem parecer anúncio.

Regras:
- idealmente 5 a 12 palavras;
- curta, direta, inteligente, informal e levemente ácida;
- masculina sem caricatura;
- sem emojis;
- não descreva simplesmente o produto;
- venda situação, desejo, problema ou sensação;
- use humor ácido, provocação, identificação, cultura automotiva, benefício
  indireto, duplo sentido ou ironia quando fizer sentido;
- evite perguntas genéricas e "problema + solução";
- não use frases genéricas como "seu carro merece", "não perca tempo",
  "qualidade e praticidade", "ideal para seu carro";
- escreva em MAIÚSCULAS.
"""


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS promos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            promo_date TEXT NOT NULL,
            product_raw TEXT,
            product_clean TEXT NOT NULL,
            normalized TEXT NOT NULL,
            price_from INTEGER,
            price_to INTEGER NOT NULL,
            payment_type TEXT,
            installments INTEGER,
            coupon TEXT,
            affiliate_link TEXT,
            headline TEXT,
            source TEXT DEFAULT 'meu',
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def normalize_text(s):
    s = s or ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)

    stop = {
        "de", "da", "do", "das", "dos", "para", "com", "e",
        "a", "o", "as", "os", "em", "por", "kit", "un",
        "unidade", "unidades", "novo", "original", "produto"
    }

    return " ".join(
        t for t in s.split()
        if t not in stop and len(t) > 1
    )


def similarity(a, b):
    a = normalize_text(a)
    b = normalize_text(b)

    if not a or not b:
        return 0.0

    sa = set(a.split())
    sb = set(b.split())

    jaccard = len(sa & sb) / max(1, len(sa | sb))
    seq = SequenceMatcher(None, a, b).ratio()

    return max(jaccard, seq)


def ai():
    key = os.getenv("GEMINI_API_KEY", "").strip()

    if not key:
        raise RuntimeError("GEMINI_API_KEY não configurada.")

    return genai.Client(api_key=key)


def extract_json_object(text):
    if not text:
        raise ValueError("Gemini não retornou conteúdo.")

    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)

    a = text.find("{")
    b = text.rfind("}")

    if a >= 0 and b > a:
        text = text[a:b + 1]

    return json.loads(text)


def extract_json_array(text):
    if not text:
        raise ValueError("Gemini não retornou conteúdo.")

    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)

    a = text.find("[")
    b = text.rfind("]")

    if a >= 0 and b > a:
        text = text[a:b + 1]

    return json.loads(text)


def analyze_offer(image):
    prompt = """
Analise este print de uma oferta do Mercado Livre.

Retorne SOMENTE JSON válido:

{
  "product_title_raw": "título visível",
  "product_title_clean": "título curto e limpo, mantendo marca/modelo importantes",
  "price_from": 343.30,
  "price_to": 277.10,
  "payment_type": "pix",
  "installments": null,
  "coupon": null
}

Regras:
- não invente informações;
- não invente cupom;
- price_from deve ser null se não existir preço anterior;
- price_to deve ser o preço atual principal;
- se o preço principal destacado for no Pix, use payment_type="pix";
- se a oferta principal for parcelada, use payment_type="installments";
- se não houver condição especial, use payment_type="none";
- installments deve ser null quando não houver parcelas;
- coupon deve ser null quando nenhum código de cupom estiver visível;
- preserve marca e modelo quando ajudarem a identificar o produto;
- remova palavras promocionais desnecessárias do product_title_clean;
- não escreva nada fora do JSON.
"""

    mime = image.mimetype or "image/jpeg"
    raw = image.read()
    image.seek(0)

    image_part = types.Part.from_bytes(
        data=raw,
        mime_type=mime
    )

    client = ai()

    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=[
                prompt,
                image_part
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )

        return extract_json_object(response.text)

    finally:
        client.close()


def generate_headline(product):
    prompt = COPYWRITER_RULES + f"""

Produto:
{product}

Retorne apenas UMA headline.
Não coloque aspas.
Não explique.
"""

    client = ai()

    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt
        )

        if not response.text:
            raise ValueError("Gemini não conseguiu gerar a headline.")

        headline = response.text.strip()
        headline = headline.strip('"').strip("'")
        headline = re.sub(r"\s+", " ", headline)

        return headline.upper()

    finally:
        client.close()


def money_int(v):
    if v in (None, "", 0, "0"):
        return None

    return int(float(v))


def price_line(d):
    pfrom = money_int(d.get("price_from"))
    pto = money_int(d.get("price_to"))

    suffix = ""

    if d.get("payment_type") == "pix":
        suffix = " no Pix"

    elif d.get("payment_type") == "installments" and d.get("installments"):
        suffix = f" em {int(d['installments'])}x"

    if pfrom is not None:
        return f"De R$ {pfrom} por R$ {pto}{suffix}"

    return f"R$ {pto}{suffix}"


def build_message(d, link, headline):
    blocks = [
        headline.strip(),
        d["product_title_clean"].strip(),
        price_line(d)
    ]

    coupon = (d.get("coupon") or "").strip()

    if coupon:
        blocks.append(f"🎟️ Use o Cupom: *{coupon}*")

    blocks.append(link.strip())

    return "\n\n".join(blocks)


def best_match_for_day(product, day):
    conn = get_db()

    rows = conn.execute(
        """
        SELECT product_clean, price_to, source
        FROM promos
        WHERE promo_date=?
        """,
        (day,)
    ).fetchall()

    matches = []

    for r in rows:
        score = similarity(product, r["product_clean"])

        if score >= 0.72:
            matches.append(
                (
                    r["product_clean"],
                    r["price_to"],
                    r["source"],
                    score
                )
            )

    return max(matches, key=lambda x: x[3]) if matches else None


def save_promo(d, link, headline, source="meu", promo_date=None):
    promo_date = promo_date or date.today().isoformat()

    conn = get_db()

    conn.execute("""
        INSERT INTO promos (
            promo_date,
            product_raw,
            product_clean,
            normalized,
            price_from,
            price_to,
            payment_type,
            installments,
            coupon,
            affiliate_link,
            headline,
            source,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        promo_date,
        d.get("product_title_raw"),
        d["product_title_clean"],
        normalize_text(d["product_title_clean"]),
        money_int(d.get("price_from")),
        money_int(d.get("price_to")),
        d.get("payment_type"),
        d.get("installments"),
        d.get("coupon"),
        link,
        headline,
        source,
        datetime.now().isoformat(timespec="seconds")
    ))

    conn.commit()


def stats():
    conn = get_db()
    today = date.today().isoformat()

    mine = conn.execute(
        """
        SELECT COUNT(*) c
        FROM promos
        WHERE promo_date=? AND source='meu'
        """,
        (today,)
    ).fetchone()["c"]

    return {
        "mine": mine,
        "goal": META_DIARIA,
        "remaining": max(0, META_DIARIA - mine)
    }


@app.route("/")
def index():
    return render_template(
        "index.html",
        stats=stats()
    )


@app.post("/api/analyze")
def api_analyze():
    image = request.files.get("image")
    link = (request.form.get("affiliate_link") or "").strip()

    if not image or not link:
        return jsonify({
            "ok": False,
            "error": "Envie o print e o link de afiliado."
        }), 400

    try:
        d = analyze_offer(image)

        if not d.get("product_title_clean") or d.get("price_to") is None:
            raise ValueError(
                "Não consegui identificar produto/preço no print."
            )

        today_match = best_match_for_day(
            d["product_title_clean"],
            date.today().isoformat()
        )

        yesterday_match = best_match_for_day(
            d["product_title_clean"],
            (date.today() - timedelta(days=1)).isoformat()
        )

        blocked_reason = None

        if today_match:
            blocked_reason = (
                f"Já apareceu hoje: "
                f"{today_match[0]} "
                f"(R$ {today_match[1]})."
            )

        elif (
            yesterday_match
            and money_int(d["price_to"]) > int(yesterday_match[1])
        ):
            blocked_reason = (
                f"Preço pior que ontem: "
                f"ontem R$ {yesterday_match[1]} "
                f"e hoje R$ {money_int(d['price_to'])}."
            )

        return jsonify({
            "ok": True,
            "data": d,
            "affiliate_link": link,
            "blocked": bool(blocked_reason),
            "blocked_reason": blocked_reason,
            "yesterday": (
                None
                if not yesterday_match
                else {
                    "product": yesterday_match[0],
                    "price": yesterday_match[1]
                }
            )
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


@app.post("/api/generate")
def api_generate():
    payload = request.get_json(force=True)

    d = payload["data"]
    link = payload["affiliate_link"].strip()

    today_match = best_match_for_day(
        d["product_title_clean"],
        date.today().isoformat()
    )

    yesterday_match = best_match_for_day(
        d["product_title_clean"],
        (date.today() - timedelta(days=1)).isoformat()
    )

    if today_match:
        return jsonify({
            "ok": False,
            "blocked": True,
            "error": "Produto já apareceu hoje."
        }), 409

    if (
        yesterday_match
        and money_int(d["price_to"]) > int(yesterday_match[1])
    ):
        return jsonify({
            "ok": False,
            "blocked": True,
            "error": "Preço atual está pior que ontem."
        }), 409

    try:
        headline = generate_headline(
            d["product_title_clean"]
        )

        message = build_message(
            d,
            link,
            headline
        )

        return jsonify({
            "ok": True,
            "headline": headline,
            "message": message
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


@app.post("/api/save")
def api_save():
    payload = request.get_json(force=True)

    save_promo(
        payload["data"],
        payload["affiliate_link"],
        payload["headline"],
        source="meu"
    )

    return jsonify({
        "ok": True,
        "stats": stats()
    })


@app.post("/api/import-group")
def api_import_group():
    payload = request.get_json(force=True)

    text = (payload.get("text") or "").strip()
    which = payload.get("day", "today")

    target = (
        date.today()
        if which == "today"
        else date.today() - timedelta(days=1)
    )

    if not text:
        return jsonify({
            "ok": False,
            "error": "Cole as mensagens do grupo."
        }), 400

    prompt = f"""
Extraia as promoções das mensagens abaixo.

Retorne APENAS JSON válido neste formato:

[
  {{
    "product_title_raw": "título como aparece",
    "product_title_clean": "título curto e limpo",
    "price_to": 123.45
  }}
]

Regras:
- ignore headlines, links e cupons na identificação do produto;
- em "De X por Y", price_to é Y;
- se houver só um preço, use esse;
- não invente produtos;
- não escreva nada fora do JSON.

MENSAGENS:

{text}
"""

    try:
        client = ai()

        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )

            promos = extract_json_array(response.text)

        finally:
            client.close()

        imported = 0

        for p in promos:
            if (
                not p.get("product_title_clean")
                or p.get("price_to") is None
            ):
                continue

            d = {
                "product_title_raw": p.get("product_title_raw"),
                "product_title_clean": p["product_title_clean"],
                "price_from": None,
                "price_to": p["price_to"],
                "payment_type": "none",
                "installments": None,
                "coupon": None
            }

            save_promo(
                d,
                "",
                "",
                source="outro_curador",
                promo_date=target.isoformat()
            )

            imported += 1

        return jsonify({
            "ok": True,
            "imported": imported
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


@app.get("/api/history")
def api_history():
    conn = get_db()

    rows = conn.execute("""
        SELECT
            promo_date,
            product_clean,
            price_to,
            source,
            headline,
            affiliate_link
        FROM promos
        ORDER BY id DESC
        LIMIT 150
    """).fetchall()

    return jsonify({
        "ok": True,
        "items": [dict(r) for r in rows],
        "stats": stats()
    })


@app.get("/health")
def health():
    return {
        "ok": True,
        "ai": "gemini",
        "model": MODEL
    }


if __name__ == "__main__":
    get_db()

    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        debug=False
  )
