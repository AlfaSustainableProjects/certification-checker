"""
api/index.py — Vercel serverless entrypoint for the Certification Checker.

Wraps the existing Flask app from server.py and adds:
  1. A shared-password gate (APP_PASSWORD env var). No var -> no gate (local dev).
  2. Persistence of verified answers in Vercel Blob (BLOB_READ_WRITE_TOKEN env
     var, auto-set when a Blob store is connected). No var -> in-memory only.

Environment variables (set in Vercel dashboard):
  ANTHROPIC_API_KEY       Claude API key (absent -> DEMO mode)
  APP_PASSWORD            shared company password for the login gate
  BLOB_READ_WRITE_TOKEN   auto-added when you connect a Blob store
  CERT_MODEL              optional model override
"""

import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE
sys.path.insert(0, ROOT)

import server  # noqa: E402  (the original Flask app)

app = server.app

# ---------------------------------------------------------------- password gate
APP_PASSWORD = os.environ.get("APP_PASSWORD", "").strip()

if APP_PASSWORD:
    from flask import request, session, redirect, jsonify

    app.secret_key = hashlib.sha256(
        ("cert-checker-session|" + APP_PASSWORD).encode()
    ).digest()
    app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 60  # 60 days
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    LOGIN_PAGE = """<!DOCTYPE html><html lang="he" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>כניסה — בדיקת תקן</title><style>
 body{font-family:"Heebo",sans-serif;background:#f7f5ef;color:#1b2430;display:flex;
      align-items:center;justify-content:center;min-height:100vh;margin:0}
 .card{background:#fffdf8;border:1px solid #e3e0d8;border-radius:14px;padding:36px 32px;
       box-shadow:0 8px 30px rgba(27,36,48,.10);width:min(360px,90vw);text-align:center}
 h1{font-size:22px;margin:0 0 6px}p{color:#586173;font-size:14px;margin:0 0 22px}
 input{width:100%%;box-sizing:border-box;padding:12px 14px;font-size:16px;border:1px solid #e3e0d8;
       border-radius:10px;text-align:center;direction:ltr}
 button{width:100%%;margin-top:14px;padding:12px;font-size:16px;font-weight:600;border:0;
        border-radius:10px;background:#1b2430;color:#fff;cursor:pointer}
 .err{color:#9a3b34;font-size:14px;margin-top:12px;min-height:18px}
</style></head><body><div class="card">
<h1>בדיקת תקן</h1><p>הזינו את סיסמת החברה</p>
<form method="post" action="/login">
  <input type="password" name="password" autofocus autocomplete="current-password">
  <button type="submit">כניסה</button>
  <div class="err">%s</div>
</form></div></body></html>"""

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            given = (request.form.get("password") or "").strip()
            if hmac.compare_digest(given, APP_PASSWORD):
                session.permanent = True
                session["auth"] = True
                return redirect("/")
            time.sleep(1)  # damp brute force
            return LOGIN_PAGE % "סיסמה שגויה", 401
        return LOGIN_PAGE % ""

    @app.before_request
    def _gate():
        if request.path == "/login":
            return None
        if session.get("auth"):
            return None
        if request.path.startswith("/api/"):
            return jsonify({"error": "unauthorized"}), 401
        return redirect("/login")

# ------------------------------------------------------------ blob persistence
# NOTE: correction persistence now lives in memory.py (BlobStore) — it detects
# BLOB_READ_WRITE_TOKEN itself and stores the learnable memory in the blob
# cert_corrections_v2.json. The code below only MIGRATES answers saved by the
# old deployment into the old blob (verified_answers.json), one time.
BLOB_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN", "").strip()
BLOB_API = os.environ.get("BLOB_API_URL", "https://blob.vercel-storage.com")
BLOB_PATH = "verified_answers.json"


def _blob_headers(extra=None):
    h = {"authorization": "Bearer " + BLOB_TOKEN, "x-api-version": "7"}
    if extra:
        h.update(extra)
    return h


def _blob_load():
    """Fetch the verified-answers blob; {} if it doesn't exist yet."""
    q = urllib.parse.urlencode({"prefix": BLOB_PATH, "limit": "10"})
    req = urllib.request.Request(BLOB_API + "?" + q, headers=_blob_headers())
    with urllib.request.urlopen(req, timeout=10) as r:
        listing = json.load(r)
    for b in listing.get("blobs", []):
        if b.get("pathname") == BLOB_PATH:
            url = b["url"] + "?v=" + str(int(time.time()))  # bust CDN cache
            with urllib.request.urlopen(url, timeout=10) as r:
                return json.load(r)
    return {}


def _blob_save(obj):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        BLOB_API + "/" + BLOB_PATH, data=body, method="PUT",
        headers=_blob_headers({
            "x-add-random-suffix": "0",
            "x-allow-overwrite": "1",
            "x-content-type": "application/json",
            "x-cache-control-max-age": "60",
        }),
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        r.read()


if BLOB_TOKEN and getattr(server.matcher, "memory", None) is not None:
    # One-time migration: pull answers the OLD deployment stored in the old
    # verified_answers.json blob into the new learnable memory (skips ones
    # already there). New corrections persist via memory.py's BlobStore.
    try:
        legacy = _blob_load()
        mem = server.matcher.memory
        imported = 0
        for k, rec in (legacy or {}).items():
            canonical = rec.get("query") or k
            if mem._normalize(canonical) in mem._by_norm:
                continue
            answer = {kk: vv for kk, vv in rec.items() if kk not in ("query", "verified")}
            mem.learn(k, canonical, answer)
            imported += 1
        if imported:
            print("migrated %d legacy verified answers from blob" % imported, file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print("legacy blob import failed:", exc, file=sys.stderr)
