# Certification Checker — Install Guide

A quick guide to running the **Certification Checker** on your own computer.
You take a photo of a delivery note or invoice, and the tool tells you which
products are SII-certified and which are made in Israel.

You only do this setup **once**. After that, it's a single double-click to start.

**Before you begin, you'll need:**

- The **company API key** — ask Alfa for it (it's a short secret code). Don't share it outside the company.
- About **10 minutes** the first time, and an internet connection.

---

## Mac

### Step 1 — Install Python (one time)

1. Go to **python.org/downloads** and click the yellow **"Download Python"** button.
2. Open the downloaded file and click through the installer (keep clicking **Continue / Install**).
3. That's it — you won't see an app open. Python just works in the background.

> Not sure if you already have it? You can skip ahead to Step 4 and try running the tool — if it complains about Python, come back and do this step.

### Step 2 — Get the tool folder

1. Download the tool (Alfa will give you the link or a ZIP file).
2. Double-click the downloaded **.zip** to unzip it. You'll get a folder with the tool's files inside.

### Step 3 — Add the company key

1. Inside the folder, find the file **`api_key.txt.example`**.
2. Rename it to **`api_key.txt`** — remove the `.example` so the name is *exactly* `api_key.txt`.
3. Double-click it to open it (it opens in **TextEdit**).
4. **Select everything in the file and delete it.** Then paste the **company key** Alfa gave you, so the key is the *only* thing in the file — one line, nothing else: no spaces before or after, no extra lines, no notes.
5. Save (**Cmd + S**) and close.

When you're done, the entire file should contain **just the key on one line**, like this — and nothing else:

```
sk-ant-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### Step 4 — Start it

1. Double-click **`start.command`**.
2. **First time only:** Mac may say it "cannot be opened because it is from an unidentified developer."
   - Right-click (or Ctrl-click) `start.command` → choose **Open** → click **Open** again.
3. A black window appears and sets things up (first time only — needs internet). Then your browser opens to the tool.

### To use it later

Just double-click **`start.command`** again. To stop, close the black window.

---

## Windows

### Step 1 — Install Python (one time)

1. Go to **python.org/downloads** and click the yellow **"Download Python"** button.
2. Open the downloaded file. **IMPORTANT:** on the first screen, tick the box at the bottom that says **"Add python.exe to PATH"**, *then* click **Install Now**.
3. When it finishes, click **Close**.

### Step 2 — Get the tool folder

1. Download the tool (Alfa will give you the link or a ZIP file).
2. Right-click the downloaded **.zip** → **Extract All… → Extract**. You'll get a folder with the tool's files inside.

### Step 3 — Add the company key

1. Inside the folder, find the file **`api_key.txt.example`**.
2. Rename it to **`api_key.txt`** — remove the `.example` so the name is *exactly* `api_key.txt`.
   (If Windows hides the ending, turn on **View → File name extensions** so you can rename it properly.)
3. Right-click it → **Open with → Notepad**.
4. **Select everything in the file and delete it** (Ctrl + A, then Delete). Then paste the **company key** Alfa gave you, so the key is the *only* thing in the file — one line, nothing else: no spaces before or after, no extra lines, no notes.
5. Save (**Ctrl + S**) and close.

When you're done, the entire file should contain **just the key on one line**, like this — and nothing else:

```
sk-ant-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### Step 4 — Start it

1. Double-click **`start.bat`**.
2. **First time only:** Windows may show a blue "Windows protected your PC" box.
   - Click **More info** → **Run anyway**.
3. A black window appears and sets things up (first time only — needs internet). Then your browser opens to the tool.

### To use it later

Just double-click **`start.bat`** again. To stop, close the black window.

---

## Using the tool

1. When your browser opens to the tool, take or upload a **photo of a delivery note / invoice**.
2. The tool reads the products and checks each one against the Israeli **SII** (standards) and **Made-in-Israel** databases.
3. You'll see, per product: the permit number, the manufacturer, and a "made in Israel" badge where it applies.

---

## If something goes wrong

- **"Python is not recognized" (Windows):** Python wasn't added to PATH. Re-run the Python installer, tick **"Add python.exe to PATH"**, and reinstall.
- **The black window opens and closes instantly:** Python probably isn't installed yet — do Step 1.
- **The page is blank:** wait a few seconds and refresh the browser.
- **"DEMO mode" appears:** the key isn't being read — check that the file is named exactly `api_key.txt` (not `api_key.txt.txt`) and that the key is pasted inside.
- **Still stuck?** Send Alfa a screenshot of the black window — the error message there says what's wrong.

---

*Keep the company key private. Never post it online or share it outside the company.*
