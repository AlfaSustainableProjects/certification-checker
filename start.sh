#!/bin/bash
# start.sh — run the Certification Checker on Linux.
# First time:  chmod +x start.sh    then run:  ./start.sh
# It installs what it needs the first time, then opens the tool in your browser
# (on a desktop). On a headless server it just runs the web app on port 5000.

cd "$(dirname "$0")" || exit 1

echo "============================================================"
echo "   בדיקת תקן — Certification Checker"
echo "============================================================"

# --- 1. API key -------------------------------------------------------------
# Preferred (servers): set an ANTHROPIC_API_KEY environment variable.
# Otherwise: the key is read from a file called  api_key.txt  in this folder.
if [ -z "$ANTHROPIC_API_KEY" ] && [ -f "api_key.txt" ]; then
  export ANTHROPIC_API_KEY="$(tr -d '[:space:]' < api_key.txt)"
fi

# --- 2. Dependencies (first run only) --------------------------------------
if ! python3 -c "import flask, anthropic" 2>/dev/null; then
  echo "Installing dependencies (first run only)..."
  pip3 install -r requirements.txt --break-system-packages --quiet \
    || pip3 install -r requirements.txt --quiet
fi

# --- 3. Launch + open browser (browser opens only on a desktop) -------------
( sleep 2 ; command -v xdg-open >/dev/null 2>&1 && xdg-open "http://localhost:5000" >/dev/null 2>&1 ) &
echo "Running on http://localhost:5000"
echo "To stop: press Ctrl+C."
echo "------------------------------------------------------------"
python3 server.py
