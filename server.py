#!/usr/bin/env python3
"""
server.py — Certification Checker backend.

Run:
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 server.py
    # then open http://localhost:5000

Without a key it starts in DEMO mode: the photo-reading step returns a fixed
sample of product names so the whole interface still works offline. Everything
else (matching, permits, badges, banners) is identical in both modes.

Environment variables:
    ANTHROPIC_API_KEY   your API key (absent -> DEMO mode)
    CERT_MODEL          model to use (default: claude-sonnet-4-6)
    PORT                port to serve on (default: 5000)
"""

import base64
import json
import os
import sys

from flask import Flask, request, jsonify, send_from_directory

from matcher import CertMatcher

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get("CERT_MODEL", "claude-sonnet-4-6")
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
DEMO_MODE = not API_KEY

SUPPORTED_IMAGE = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
}
SUPPORTED_PDF = {"application/pdf"}
SUPPORTED = SUPPORTED_IMAGE | SUPPORTED_PDF

# Sample names returned in DEMO mode (real product names from the databases,
# so matching produces a realistic mix of statuses).
DEMO_SAMPLES = {
    "תעודת משלוח – דוגמה 1.jpg": [
        "כוחלה 119",
        "סיקה טופ 107",
        "אקרילפז סופר",
    ],
    "תעודת משלוח – דוגמה 2.jpg": [
        "TAMCRETE 600",
        "טיט לריצוף",
        "בונדטקס 220 דבק אריחים צמנטי",
        "מסמרים פלדה מגולוונים 3 אינץ'",
    ],
}

matcher = CertMatcher(
    os.path.join(HERE, "sii_database.json"),
    os.path.join(HERE, "made_in_israel_products.json"),
    os.path.join(HERE, "verified_answers.json"),
)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # 64 MB per request

# Lazily-created Anthropic client (only when a key is present).
_client = None


def get_client():
    global _client
    if _client is None:
        from anthropic import Anthropic
        _client = Anthropic(api_key=API_KEY)
    return _client


EXTRACT_PROMPT = """אתה קורא תעודת משלוח / חשבונית של חומרי בנייה בעברית.
החזר אך ורק את שמות המוצרים (שורות הפריטים) כפי שהם מופיעים במסמך.

כללים:
- החזר רשימת JSON של מחרוזות בלבד, ללא טקסט נוסף, ללא הסברים, ללא markdown.
- כל מחרוזת = שם מוצר אחד כפי שכתוב, כולל דגם/מספר אם מופיע (למשל "כוחלה 119").
- אל תכלול כמויות, מחירים, מק"ט, ברקודים, כתובות, שם הלקוח, או כותרות.
- אם אין מוצרים, החזר [].

דוגמת פלט תקין:
["כוחלה 119", "דבק אריחים C2TES2", "אקרילפז סופר"]"""


def extract_names(media_type: str, data_b64: str):
    """Call the model on an image OR a PDF and return product-name strings.

    Images use an `image` content block; PDFs use a `document` block, which
    Claude reads natively (both text-based and scanned/visual PDFs) — no
    server-side PDF library or system dependency needed.
    """
    client = get_client()
    if media_type in SUPPORTED_PDF:
        source_block = {"type": "document",
                        "source": {"type": "base64",
                                   "media_type": "application/pdf",
                                   "data": data_b64}}
    else:
        source_block = {"type": "image",
                        "source": {"type": "base64",
                                   "media_type": media_type,
                                   "data": data_b64}}
    msg = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": [source_block, {"type": "text", "text": EXTRACT_PROMPT}],
        }],
    )
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    return _parse_name_list(text)


def _parse_name_list(text: str):
    """Defensively parse a JSON array of strings out of model output."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("\n") + 1:] if "\n" in text else text
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    try:
        arr = json.loads(text)
        return [str(x).strip() for x in arr if str(x).strip()]
    except Exception:
        # Fall back: treat each non-empty line as a product.
        return [ln.strip(" -•\t") for ln in text.splitlines() if ln.strip()]


@app.route("/")
def index():
    return send_from_directory(HERE, "index.html")


@app.route("/api/status")
def status():
    return jsonify({
        "mode": "demo" if DEMO_MODE else "live",
        "model": None if DEMO_MODE else MODEL,
        "databases": matcher.counts,
    })


@app.route("/api/extract", methods=["POST"])
def extract():
    """Read uploaded photos -> extract product names -> match. Per-file results."""
    files = request.files.getlist("files")
    results = []

    if DEMO_MODE:
        # Ignore uploaded bytes; return the canned sample set.
        for fname, names in DEMO_SAMPLES.items():
            results.append({
                "file": fname,
                "products": matcher.match_many(names),
            })
        return jsonify({"mode": "demo", "results": results})

    if not files:
        return jsonify({"error": "no files uploaded"}), 400

    for f in files:
        media_type = (f.mimetype or "").lower()
        # Some browsers send octet-stream; fall back to the extension for PDFs.
        if media_type not in SUPPORTED and (f.filename or "").lower().endswith(".pdf"):
            media_type = "application/pdf"
        if not media_type:
            media_type = "image/jpeg"
        entry = {"file": f.filename, "products": []}
        if media_type not in SUPPORTED:
            entry["error"] = f"unsupported file type: {media_type}"
            results.append(entry)
            continue
        try:
            data_b64 = base64.b64encode(f.read()).decode("ascii")
            names = extract_names(media_type, data_b64)
            entry["products"] = matcher.match_many(names)
        except Exception as exc:  # noqa: BLE001 — surface per-file, keep batch alive
            entry["error"] = str(exc)
        results.append(entry)

    return jsonify({"mode": "live", "results": results})


@app.route("/api/match", methods=["POST"])
def match():
    """Re-match edited / typed product names without touching the vision API."""
    payload = request.get_json(silent=True) or {}
    names = payload.get("names", [])
    if isinstance(names, str):
        names = [names]
    return jsonify({"products": matcher.match_many([str(n) for n in names])})


@app.route("/api/confirm", methods=["POST"])
def confirm():
    """Record (or remove) a human-verified answer for a product name.
    Body: {"raw": "<name>", "record": {...}}  or  {"raw": "<name>", "remove": true}.
    The stored answer is returned by future matches for that name."""
    payload = request.get_json(silent=True) or {}
    raw = str(payload.get("raw", "")).strip()
    if not raw:
        return jsonify({"ok": False, "error": "missing name"}), 400
    if payload.get("remove"):
        removed = matcher.unconfirm(raw)
        return jsonify({"ok": True, "removed": removed, "verified_count": matcher.counts["verified"]})
    record = payload.get("record") or {}
    ok = matcher.confirm(raw, record)
    return jsonify({"ok": ok, "verified_count": matcher.counts["verified"]})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    banner = "DEMO mode (no API key — using sample receipts)" if DEMO_MODE \
        else f"LIVE mode — model: {MODEL}"
    print("=" * 60, file=sys.stderr)
    print("  Certification Checker — בדיקת תקן", file=sys.stderr)
    print(f"  {banner}", file=sys.stderr)
    print(f"  SII products: {matcher.counts['sii']}  |  "
          f"Made-in-Israel: {matcher.counts['mii']}", file=sys.stderr)
    print(f"  Open  ->  http://localhost:{port}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    app.run(host="127.0.0.1", port=port, debug=False)
