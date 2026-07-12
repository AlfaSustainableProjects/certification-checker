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
    CERT_MODEL          model to use (default: claude-opus-4-8; strongest read.
                        Set claude-sonnet-4-6 / claude-haiku-4-5 for lower cost)
    PORT                port to serve on (default: 5000)
"""

import base64
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, request, jsonify, send_from_directory

from matcher import CertMatcher

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get("CERT_MODEL", "claude-opus-4-8")
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
DEMO_MODE = not API_KEY

SUPPORTED_IMAGE = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
}
SUPPORTED_PDF = {"application/pdf"}
SUPPORTED = SUPPORTED_IMAGE | SUPPORTED_PDF

# Batch limits. Files are read concurrently (each is one API call), so a batch
# finishes in about the time of its slowest file rather than the sum of all.
MAX_FILES = 25       # reject oversized batches with a clear message
MAX_WORKERS = 8      # concurrent reads (bounded to stay within API rate limits)

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


_FALLBACK_EXTRACT_PROMPT = """You are reading a Hebrew building materials delivery note (תעודת משלוח) or invoice.
Extract ONLY the product names. Return a JSON array of strings — nothing else. No explanation, no markdown fences.

═══════════════════════════════════════════════
STEP 1 — ORIENTATION
═══════════════════════════════════════════════
Many real delivery notes are photographed upside-down or mirrored (especially SAKRET Israel and LYMA invoices).
Rotate mentally until the supplier logo / letterhead is at the top, then read normally.

═══════════════════════════════════════════════
STEP 2 — FIND THE PRODUCT COLUMN
═══════════════════════════════════════════════
Almost all delivery notes have a table. Read ONLY the description column (תיאור / תיאור מוצר / שם מוצר).
Ignore all other columns:
  - # / מס' / מק"ט / קוד פריט / אסמ'  →  SKIP (item numbers / SKUs)
  - כמות / יח' / ניר  →  SKIP (quantities / units)
  - מחיר / סה"כ / ₪  →  SKIP (prices)

═══════════════════════════════════════════════
STEP 3 — WHAT TO INCLUDE IN EACH PRODUCT NAME
═══════════════════════════════════════════════
✓ Product / material name
✓ Model codes and grade specs: FL810, AD 700, PR-007, C2TES2, MC1, OC200
✓ Descriptive suffixes that are part of the product: "עמיד אש", "עמיד במים", "EXTRA WHITE"
✓ Tile dimensions (they identify the tile): 120*120  /  80*180*2  /  180*23*0.65
✓ Pipe sizes for plumbing products: 3/8"  /  1/2"  /  110mm  /  45°
✓ Tile color/variant codes when they distinguish the product: גוון 1010, כרמית, GREY

✗ Quantities and units: כמות, ק"ג, ליטר, מ"ר, יח', שק, דלי, ניר, שק 25 ק"ג
✗ Prices: מחיר, סה"כ, ₪, מחיר יחידה
✗ SKU / catalog numbers: מק"ט, ברקוד, אסמ', VS03..., PO23...  (unless the SKU IS the product name)
✗ Lot / shade codes after a model name: the "672 69-315" in "TAMCRETE MC1 672 69-315" → keep only "TAMCRETE MC1"
✗ Column headers, customer name, address, phone, company header, dates, document numbers
✗ Supplier company names alone (מנדלסון, אחד לבנין, LYMA as a company) — only actual product names

═══════════════════════════════════════════════
STEP 4 — CRITICAL: HEBREW PREPOSITIONS
═══════════════════════════════════════════════
Hebrew prepositions ב/ל/מ/כ/ש attach to the NEXT word with NO space. Never drop them.
  "עמיד במים"  ✓  (NOT "עמיד מים")
  "דבק לריצוף" ✓  (NOT "דבק ריצוף")
The database stores the full attached form — dropping the preposition causes a missed match.

═══════════════════════════════════════════════
STEP 5 — LETTER DISAMBIGUATION
═══════════════════════════════════════════════
Hebrew confusables (check if you read something that looks like nonsense):
  ב (bet) vs כ (kaf)      — כ has an open downward curve; ב is rounder
  ד (dalet) vs ר (resh)   — ד has a sharp 90° top-right corner; ר is rounded → "גבס" not "גרס"
  ה (he) vs ח (khet)      — ה has a gap at top-right; ח is closed → "חסין אש" not "הסין אש"
  ו (vav) vs ז (zayin)    — ז has a horizontal top stroke; ו is just a vertical line
  ן (nun sofit) vs ך (kaf sofit) — ן straight; ך curved

Latin / digit confusables in product codes:
  O vs 0  — Letter O in brand names (OC200 starts with letter O)
  l vs 1 vs I  — digit 1 in numeric codes; L in model names (FL810 — L is a letter)
  S vs 5  — always letter S in brand names: SIKA, SAKRET, not 5IKA
  B vs 8  — usually B in codes: TRBR not TR8R

═══════════════════════════════════════════════
STEP 6 — KNOWN BRANDS (sanity-check your reading)
═══════════════════════════════════════════════
Israeli:  תרמוקיר · אורבונד · ROCKBOND/רוקבונד · כוחלה · Tambour/טמבור · LYMA
International: SAKRET · TAMCRETE · KNAUF · MAPEI · SIKA/SIKASIL · Murexin · VALSIR · NAI · ABSOTEC
Distributors (not products): מנדלסון · אחד לבנין

═══════════════════════════════════════════════
OUTPUT — JSON ARRAY ONLY
═══════════════════════════════════════════════
["כוחלה 119 לבן", "TAMCRETE MC1", "MOTIF 120G 120*120", "VALSIR 110 45 זית", "C2TES2 דבק אריחים"]

Empty result: []
If a line is unclear, include your best reading — do not skip."""


# The hebrew-invoice-reader Cowork skill is the single source of truth for the
# extraction rules. We bundle its SKILL.md alongside this file and build the
# vision prompt from it at startup, so editing the skill (and re-copying the
# file) updates the app without touching this code. If the file is missing or
# unreadable (e.g. an unexpected deploy), we fall back to the embedded prompt
# above so the app never breaks.
SKILL_FILE = os.path.join(HERE, "hebrew_invoice_reader_SKILL.md")


def _strip_frontmatter(text: str) -> str:
    """Remove a leading YAML '--- ... ---' block from a markdown skill file."""
    text = text.lstrip()
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            nl = text.find("\n", end + 1)
            text = text[nl + 1:] if nl != -1 else ""
    return text.strip()


def _build_extract_prompt() -> str:
    """Build the vision prompt from the bundled skill, or fall back."""
    try:
        with open(SKILL_FILE, encoding="utf-8") as fh:
            body = _strip_frontmatter(fh.read())
        if not body:
            raise ValueError("empty skill body")
        return (
            "You are reading a Hebrew building materials delivery note "
            "(תעודת משלוח) or invoice. Follow the rules below to extract the "
            "product names. Return ONLY a JSON array of strings — no "
            "explanation, no markdown fences.\n\n" + body
        )
    except Exception as exc:  # noqa: BLE001 — never let a bad file break startup
        print(f"  [skill] could not load {SKILL_FILE} ({exc}); "
              f"using embedded fallback prompt", file=sys.stderr)
        return _FALLBACK_EXTRACT_PROMPT


EXTRACT_PROMPT = _build_extract_prompt()


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
    if len(files) > MAX_FILES:
        return jsonify({"error": f"יותר מדי קבצים: {len(files)} (מקסימום {MAX_FILES} בבת אחת)"}), 400

    # Read bytes + resolve media types up front (cheap, in the request thread),
    # so the worker threads only do the network-bound API calls.
    jobs = []
    for f in files:
        media_type = (f.mimetype or "").lower()
        # Some browsers send octet-stream; fall back to the extension for PDFs.
        if media_type not in SUPPORTED and (f.filename or "").lower().endswith(".pdf"):
            media_type = "application/pdf"
        if not media_type:
            media_type = "image/jpeg"
        jobs.append({"file": f.filename, "media_type": media_type, "data": f.read()})

    get_client()  # initialise the shared client once before threads start

    def process(job):
        entry = {"file": job["file"], "products": []}
        if job["media_type"] not in SUPPORTED:
            entry["error"] = f"unsupported file type: {job['media_type']}"
            return entry
        try:
            data_b64 = base64.b64encode(job["data"]).decode("ascii")
            names = extract_names(job["media_type"], data_b64)
            entry["products"] = matcher.match_many(names)
        except Exception as exc:  # noqa: BLE001 — surface per-file, keep batch alive
            entry["error"] = str(exc)
        return entry

    # Process files concurrently; ex.map preserves input order in the output.
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(jobs))) as ex:
        results = list(ex.map(process, jobs))

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
    # `original` = the exact OCR read (becomes an alias); `corrected` = the
    # human-fixed name. Older clients send only `raw` — treat it as the original.
    original = str(payload.get("original") or payload.get("raw") or "").strip()
    corrected = (str(payload.get("corrected") or "").strip() or None)
    if payload.get("remove"):
        target = corrected or original
        if not target:
            return jsonify({"ok": False, "error": "missing name"}), 400
        removed = matcher.unconfirm(target)
        return jsonify({"ok": True, "removed": removed, "verified_count": matcher.counts["verified"]})
    if not original:
        return jsonify({"ok": False, "error": "missing name"}), 400
    record = payload.get("record") or {}
    ok = matcher.confirm(original, record, corrected_name=corrected)
    return jsonify({"ok": ok, "verified_count": matcher.counts["verified"]})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    banner = "DEMO mode (no API key — using sample receipts)" if DEMO_MODE \
        else f"LIVE mode — model: {MODEL}"
    print("=" * 60, file=sys.stderr)
    print("  Certification Checker — בדיקת תקן", file=sys.stderr)
    print(f"  {banner}", file=sys.stderr)
    print(f"  Extraction rules: {'hebrew-invoice-reader skill' if EXTRACT_PROMPT is not _FALLBACK_EXTRACT_PROMPT else 'embedded fallback'}",
          file=sys.stderr)
    print(f"  SII products: {matcher.counts['sii']}  |  "
          f"Made-in-Israel: {matcher.counts['mii']}", file=sys.stderr)
    print(f"  Open  ->  http://localhost:{port}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    app.run(host="127.0.0.1", port=port, debug=False)
