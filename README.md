# בדיקת תקן — Certification Checker

Reads photos of delivery notes / invoices, extracts the product names with
Claude's vision API, and checks each one against two Israeli databases:

* **SII** — Standards Institution certified products → permit number + manufacturer
* **MII** — Made-in-Israel registry → "תוצרת הארץ" flag + official link

The reading step uses the API. Everything else (matching, permits, badges,
banners) runs locally on the machine.

## Files

| File | What it is |
|------|------------|
| `server.py` | Flask backend: serves the UI, reads photos, matches products |
| `matcher.py` | The matching engine (pure Python, no dependencies) |
| `index.html` | The web interface (RTL Hebrew) |
| `requirements.txt` | Python packages (`flask`, `anthropic`) |
| `start.command` | Double-click launcher for Mac |
| `SETUP_go-live.html` | One-page setup sheet (open in a browser) |
| `sii_database.json` | 1,216 SII-certified products |
| `made_in_israel_products.json` | 1,713 Made-in-Israel products |
| `verified_answers.json` | Human-confirmed answers (grows as Naomi taps ✓/✗); checked before matching |

## Run it

**Easiest (Mac):** put your key in a file named `api_key.txt` in this folder,
then double-click `start.command`.

**Manually (any OS):**

```bash
pip3 install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...      # Windows: set ANTHROPIC_API_KEY=...
python3 server.py
# open http://localhost:5000
```

Without a key it runs in **DEMO mode** — the photo-reading step returns a fixed
sample so the whole interface still works for a walkthrough. Everything
downstream is identical to live mode.

## Settings (optional env vars)

* `CERT_MODEL` — model to use (default `claude-sonnet-4-6`; more accurate on
  hard/garbled photos. Set to `claude-haiku-4-5` for ~3× lower cost if reads are clean)
* `PORT` — port to serve on (default `5000`)

## Cost

~0.6 agorot per receipt with Sonnet 4.6 (~3× Haiku's rate). $5 of credit ≈ 600–700 receipts.
Keep auto-reload **off** in the Console and the loaded amount is your hard cap.
```
