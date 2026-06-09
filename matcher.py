"""
matcher.py — Certification matching engine (v2).

Given a product name read off a delivery note, finds the best match in:
  * SII  — Standards Institution certified products (תו תקן) -> permit + manufacturer
  * MII  — "Made in Israel" / תוצרת הארץ registry -> Israeli-made flag + link

v2 changes (tuned on real delivery notes):
  - IDF weighting so distinctive tokens (brand names, model codes) outweigh
    filler words ("לבן", "דלי", "שק", "ק\"ג"). Real notes are verbose; the
    database stores short canonical names, so a DB name embedded inside a long
    line must still score high.
  - Asymmetric containment: rewards a DB product name found *inside* a longer
    extracted line without penalising the extra descriptor words.
  - Short numeric-only tokens damped (model numbers vary; they shouldn't create
    spurious matches on their own).
  - Threshold structure errs safe: "approved" stays strict (only confident full
    matches auto-approve); "review" casts a wider net so a borderline-but-real
    product surfaces with its candidate permit for a human glance, rather than
    being hidden as "not found".

Pure standard library — runs anywhere Python runs.
"""

import json
import math
import os
import re
import unicodedata
from collections import Counter

APPROVED_THRESHOLD = 0.82   # >= this vs SII -> מאושר   (approved, auto)
REVIEW_THRESHOLD = 0.45     # >= this        -> לבדיקה  (surface for human check)
MII_THRESHOLD = 0.78        # >= this vs MII -> תוצרת הארץ banner (confident)
MII_REVIEW_THRESHOLD = 0.45 # >= this (but < MII_THRESHOLD) -> surface candidate
                            # + link for a human glance, WITHOUT asserting origin.
                            # Mirrors the SII review band: cast wide, claim nothing.

STATUS_APPROVED = "approved"
STATUS_REVIEW = "review"
STATUS_NOT_FOUND = "not_found"

# The full shape of a match result, used to sanitize stored verified answers.
RESULT_KEYS = ("query", "status", "confidence", "permit", "manufacturer",
               "matched_name", "made_in_israel", "mii_confidence",
               "official_url", "mii_status", "mii_matched_name")

_NIQQUD = re.compile(r"[\u0591-\u05C7]")
_NON_WORD = re.compile(r"[^\u05D0-\u05EAa-z0-9]+")
# Split tokens glued across scripts: Hebrew<->Latin and digit<->Hebrew.
# (NOT digit<->Latin, so codes like C2TES2 / F30 / RAL7044 / MC1 stay intact.)
# ~100 DB entries store names like "לריצוףTAMCRETE" / "672כינוי" with no space,
# which hides the brand/model token from matching.
_BND_HL = re.compile(r"([\u05D0-\u05EA])([a-z])|([a-z])([\u05D0-\u05EA])")
_BND_DH = re.compile(r"([0-9])([\u05D0-\u05EA])|([\u05D0-\u05EA])([0-9])")
def _split_boundaries(t):
    prev = None
    while prev != t:
        prev = t
        t = _BND_HL.sub(lambda m: f"{m.group(1) or m.group(3)} {m.group(2) or m.group(4)}", t)
        t = _BND_DH.sub(lambda m: f"{m.group(1) or m.group(3)} {m.group(2) or m.group(4)}", t)
    return t
_STOPWORDS = {
    "בע", "מ", "בעמ", "ltd", "kg", "קג", "ק", "גרם", "גר", "ל", "מל", "ליטר",
    "ה", "של", "עם", "את", "ב", "לבן", "שחור", "אפור", "דלי", "שק", "חבית",
    "גליל", "סט", "יח", "יחי", "יחידה", "עובי",
}


def normalize(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = _NIQQUD.sub("", text)
    text = text.lower()
    text = _split_boundaries(text)
    text = _NON_WORD.sub(" ", text)
    return text.strip()


# Field text often glues a model code ("MP10") that the DB writes split ("MP-10"/"MP 10").
# For tokens of 2+ letters followed by digits, also emit the split halves, keeping the
# glued form — so "MP10" matches "MP 10" while "F30"/"C2TES2" (no 2-letter+digits tail) stay atomic.
_ALNUM_SPLIT = re.compile(r"^([a-z]{2,})([0-9]+)$")


def _tokens(norm_text: str) -> frozenset:
    out = set()
    for t in norm_text.split():
        if not t or t in _STOPWORDS:
            continue
        out.add(t)
        m = _ALNUM_SPLIT.match(t)
        if m:
            out.add(m.group(1))
            out.add(m.group(2))
    return frozenset(out)


class CertMatcher:
    def __init__(self, sii_path: str, mii_path: str, verified_path: str = None):
        with open(sii_path, encoding="utf-8") as f:
            sii_raw = json.load(f)
        with open(mii_path, encoding="utf-8") as f:
            mii_raw = json.load(f)

        # Human-verified answers: normalized product name -> confirmed result.
        # Checked BEFORE fuzzy matching, so a confirmed product is always
        # returned exactly as a human verified it (the tool's "memory").
        self.verified_path = verified_path
        self.verified = {}
        if verified_path and os.path.exists(verified_path):
            try:
                with open(verified_path, encoding="utf-8") as f:
                    self.verified = json.load(f)
            except Exception:
                self.verified = {}

        self.sii, self.mii = [], []
        for r in sii_raw:
            n = normalize(r.get("k") or r.get("n", ""))
            self.sii.append({"name": r.get("n", ""), "company": r.get("c", ""),
                             "permit": r.get("p"), "norm": n, "tokens": _tokens(n)})
        for r in mii_raw:
            n = normalize(r.get("k") or r.get("n", ""))
            self.mii.append({"name": r.get("n", ""), "company": r.get("c", ""),
                             "url": r.get("u", ""), "norm": n, "tokens": _tokens(n)})

        # Document frequency across BOTH databases -> IDF.
        self._df = Counter()
        for entry in self.sii + self.mii:
            for t in entry["tokens"]:
                self._df[t] += 1
        self._N = len(self.sii) + len(self.mii)

    def _idf(self, t: str) -> float:
        base = math.log((self._N + 1) / (self._df.get(t, 0) + 1)) + 1.0
        if t.isdigit() and len(t) <= 3:      # damp short model-number tokens
            base *= 0.45
        return base

    def _wcov(self, inter, toks) -> float:
        den = sum(self._idf(t) for t in toks)
        return (sum(self._idf(t) for t in inter) / den) if den else 0.0

    def _covs(self, qtok, ctok):
        inter = qtok & ctok
        if not inter:
            return 0.0, 0.0
        cov_c = self._wcov(inter, ctok)   # how much of the DB name is in the line
        cov_q = self._wcov(inter, qtok)   # how much of the line is the DB name
        # guard: a match resting only on common words isn't real specificity
        if max((self._idf(t) for t in inter), default=0) < 3.0 and cov_c < 0.999:
            cov_c *= 0.6
        return cov_c, cov_q

    def _score(self, qtok: frozenset, ctok: frozenset) -> float:
        # SELECTION score: rewards matching the line's distinctive tokens
        # (brand/model), so the specific entry beats a generic substring.
        cov_c, cov_q = self._covs(qtok, ctok)
        if cov_c == 0.0 and cov_q == 0.0:
            return 0.0
        return min(1.0, 0.60 * cov_c + 0.40 * cov_q)

    def _confidence(self, qtok, ctok) -> float:
        # DISPLAY confidence for the chosen winner: same blend, plus a bonus
        # when the DB product name is fully present in the line (cov_c ~ 1),
        # so an exact name match auto-approves even inside a verbose line.
        cov_c, cov_q = self._covs(qtok, ctok)
        base = 0.60 * cov_c + 0.40 * cov_q
        if cov_c >= 0.95:
            base += 0.15
        return min(1.0, base)

    def _best(self, db, qtok):
        best, best_s = None, 0.0
        for entry in db:
            s = self._score(qtok, entry["tokens"])   # pick by selection score
            if s > best_s:
                best, best_s = entry, s
        if best is None:
            return None, 0.0
        return best, self._confidence(qtok, best["tokens"])  # report display confidence

    def match(self, raw_name: str) -> dict:
        qtok = _tokens(normalize(raw_name))
        result = {"query": raw_name, "status": STATUS_NOT_FOUND, "confidence": 0.0,
                  "permit": None, "manufacturer": None, "matched_name": None,
                  "made_in_israel": False, "mii_confidence": 0.0, "official_url": None,
                  "mii_status": "none", "mii_matched_name": None}

        # 1) Verified-answer key wins outright (the tool's confirmed memory).
        vkey = normalize(raw_name)
        if vkey and vkey in self.verified:
            rec = dict(result)
            rec.update(self.verified[vkey])
            rec["query"] = raw_name
            rec["verified"] = True
            return rec

        if not qtok:
            return result

        sii_hit, sii_s = self._best(self.sii, qtok)
        if sii_hit:
            result["confidence"] = round(sii_s, 3)
            if sii_s >= REVIEW_THRESHOLD:
                result["matched_name"] = sii_hit["name"]
                result["permit"] = sii_hit["permit"]
                result["manufacturer"] = sii_hit["company"]
                result["status"] = STATUS_APPROVED if sii_s >= APPROVED_THRESHOLD else STATUS_REVIEW

        mii_hit, mii_s = self._best(self.mii, qtok)
        if mii_hit and mii_s >= MII_REVIEW_THRESHOLD:
            result["mii_confidence"] = round(mii_s, 3)
            result["mii_matched_name"] = mii_hit["name"]
            result["official_url"] = mii_hit["url"] or None
            if mii_s >= MII_THRESHOLD:
                # Confident: assert תוצרת הארץ.
                result["made_in_israel"] = True
                result["mii_status"] = "confirmed"
                if not result["manufacturer"] and mii_hit["company"] not in ("", "(לזיהוי)"):
                    result["manufacturer"] = mii_hit["company"]
            else:
                # Borderline: surface the candidate + link for a human glance.
                # Do NOT assert origin and do NOT borrow the manufacturer.
                result["mii_status"] = "review"

        return result

    def _persist_verified(self):
        if not self.verified_path:
            return
        tmp = self.verified_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.verified, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.verified_path)   # atomic on same filesystem

    def confirm(self, raw_name: str, record: dict) -> bool:
        """Store a human-verified result for this product name. Sanitizes to the
        known result keys so UI cruft isn't persisted. Overwrites any prior entry."""
        key = normalize(raw_name)
        if not key:
            return False
        rec = {k: record.get(k) for k in RESULT_KEYS if k in record}
        rec["verified"] = True
        self.verified[key] = rec
        self._persist_verified()
        return True

    def unconfirm(self, raw_name: str) -> bool:
        """Remove a verified answer (undo)."""
        key = normalize(raw_name)
        if key in self.verified:
            del self.verified[key]
            self._persist_verified()
            return True
        return False

    def match_many(self, names):
        return [self.match(n) for n in names]

    @property
    def counts(self):
        return {"sii": len(self.sii), "mii": len(self.mii),
                "verified": len(self.verified)}
