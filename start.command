#!/bin/bash
# start.command — double-click this on a Mac to run the Certification Checker.
# It installs what it needs the first time, then opens the tool in your browser.

cd "$(dirname "$0")" || exit 1

echo "============================================================"
echo "   בדיקת תקן — Certification Checker"
echo "============================================================"

# --- 1. API key -------------------------------------------------------------
# The key is read from a file called  api_key.txt  in this same folder.
# (Create that file once, paste the sk-ant-... key into it, save.)
if [ -f "api_key.txt" ]; then
  export ANTHROPIC_API_KEY="$(tr -d '[:space:]' < api_key.txt)"
fi

# --- 2. Dependencies (first run only) --------------------------------------
if ! python3 -c "import flask, anthropic" 2>/dev/null; then
  echo "מתקין רכיבים (פעם ראשונה בלבד)..."
  pip3 install -r requirements.txt --break-system-packages --quiet \
    || pip3 install -r requirements.txt --quiet
fi

# --- 3. Launch + open browser ----------------------------------------------
( sleep 2 ; open "http://localhost:5000" ) &
echo "פותח את http://localhost:5000 בדפדפן..."
echo "להפסקה: סגרו חלון זה."
echo "------------------------------------------------------------"
python3 server.py
