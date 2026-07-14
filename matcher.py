"""
matcher.py — Certification matching engine (v3).

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

v3 accuracy improvements:
  - Model-number conflict penalty: when BOTH the query and the DB entry contain
    short numeric identifier tokens that do NOT overlap, the score is halved.
    Prevents SAKRET PR-996 from matching SAKRET PR-007, or תרמוקיר 100 AD from
    matching תרמוקיר 500 AD — different model numbers, different products.
    Does NOT penalise when only one side has a numeric (e.g. quantity in query).
  - Compound Latin sub-token expansion: delivery notes sometimes concatenate brand
    and product names without separators (e.g. "KNAUFORBOND", "SIKASIL"). At
    match time, a long all-alpha Latin query token is expanded with any known DB
    token found as a substring (len ≥ 4), so "KNAUFORBOND" also emits "knauf"
    and can match "שפכטל KNAUF" at review level for human inspection.

Pure standard library — runs anywhere Python runs.
"""

import json
import math
import os
import re
import sys
import unicodedata
from collections import Counter

APPROVED_THRESHOLD = 0.82   # >= this vs SII -> מאושר   (approved, auto)
REVIEW_THRESHOLD = 0.70     # >= this        -> לבדיקה  (surface for human check)
                            # Raised from 0.45 → 0.70: eliminates weak partial
                            # matches (wrong brand / wrong model) that looked like
                            # false reviews. Only show a candidate if confidence is
                            # genuinely high; otherwise return not_found.
MII_THRESHOLD = 0.78        # >= this vs MII -> תוצרת הארץ banner (confident)
MII_REVIEW_THRESHOLD = 0.70 # >= this (but < MII_THRESHOLD) -> surface candidate

STATUS_APPROVED = "approved"
STATUS_REVIEW = "review"
STATUS_NOT_FOUND = "not_found"

# The full shape of a match result, used to sanitize stored verified answers.
RESULT_KEYS = ("query", "status", "confidence", "permit", "manufacturer",
               "matched_name", "cert_url", "made_in_israel", "mii_confidence",
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


# Domain abbreviations written with a dot on Israeli delivery notes, expanded so
# the reader's literal text meets the DB spelling. "צ.זכוכית" -> "צמר זכוכית",
# "ע. מים" -> "עמיד מים". Applied token-wise inside normalize() on BOTH sides.
_ABBREV = {
    "צ": "צמר",   # צמר (wool): צ.זכוכית / צ.סלעים / צ.מינרלי
    "ע": "עמיד",  # עמיד (resistant): ע. מים = עמיד מים
}


def normalize(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = _NIQQUD.sub("", text)
    text = text.lower()
    text = _split_boundaries(text)
    text = _NON_WORD.sub(" ", text).strip()
    if _ABBREV:
        text = " ".join(_ABBREV.get(w, w) for w in text.split())
    return text


# Field text often glues a model code ("MP10") that the DB writes split ("MP-10"/"MP 10").
# For tokens of 2+ letters followed by digits, also emit the split halves, keeping the
# glued form — so "MP10" matches "MP 10" while "F30"/"C2TES2" (no 2-letter+digits tail) stay atomic.
_ALNUM_SPLIT = re.compile(r"^([a-z]{2,})([0-9]+)$")


def _tokens(norm_text: str) -> frozenset:
    out = set()
    for t in norm_text.split():
        if not t or t in _STOPWORDS:
            continue
        m = _ALNUM_SPLIT.match(t)
        if m:
            # "FL810" -> "fl","810": emit the split halves ONLY (drop the glued
            # form) so a jammed model code tokenizes exactly like the spaced
            # "FL 810" the SII DB stores. Keeping the glued token inflated the
            # query token count and pushed real matches below the approve threshold.
            out.add(m.group(1))
            out.add(m.group(2))
        else:
            out.add(t)
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

        # Known long alpha tokens from the DB (len >= 4, no digits) used for
        # sub-token expansion of compound Latin query tokens (v3).
        self._known_sub_tokens = frozenset(
            t for entry in (self.sii + self.mii)
            for t in entry["tokens"]
            if len(t) >= 4 and t.isalpha()
        )

        # Learnable, SHARED correction memory (aliases + human-verified answers).
        # Migrates the old flat verified_answers.json in on first run.
        try:
            from memory import Memory, make_store
            self.memory = Memory(make_store(), normalize,
                                 lambda s: self._qtokens(s),
                                 result_keys=RESULT_KEYS,
                                 migrate_from=self.verified)
            print("memory: %d learned corrections (%s)" % (
                self.memory.count, self.memory.describe()), file=sys.stderr)
        except Exception as exc:
            print("memory init failed (%s); continuing without learning" % exc, file=sys.stderr)
            self.memory = None

    def _idf(self, t: str) -> float:
        base = math.log((self._N + 1) / (self._df.get(t, 0) + 1)) + 1.0
        if t.isdigit() and len(t) <= 3:      # damp short model-number tokens
            base *= 0.45
        return base

    def _qtokens(self, norm_text: str) -> frozenset:
        """Tokenize a query with compound Latin sub-token expansion (v3).

        For long all-alpha Latin tokens (len >= 7) that appear in delivery notes
        as concatenated brand+model strings (e.g. "KNAUFORBOND", "SIKASIL"),
        also emit any known DB token found as a substring (len >= 4).  This lets
        "KNAUFORBOND" surface a "review" match against "שפכטל KNAUF" so the
        human can confirm rather than silently returning not_found.
        """
        base = _tokens(norm_text)
        extra = set()
        for t in base:
            if len(t) >= 7 and t.isalpha():
                for kt in self._known_sub_tokens:
                    if kt in t and kt != t:
                        extra.add(kt)
        return base | frozenset(extra) if extra else base

    def _model_penalty(self, qtok: frozenset, ctok: frozenset) -> float:
        """Penalise when query and DB entry carry conflicting short numeric IDs (v3).

        Rule: if BOTH sides have short digit-only tokens (2–4 chars) AND those
        sets are completely disjoint, the match is almost certainly the wrong
        model — halve the score.  Single-side numerics (e.g. a quantity in the
        query that the terse DB name omits) are not penalised.

        Examples that trigger the penalty:
          SAKRET PR-996  vs  SAKRET PR-007   (996 ≠ 007 on both sides)
          תרמוקיר 100 AD vs תרמוקיר 500 AD  (100 ≠ 500 on both sides)
        """
        is_model = lambda t: t.isdigit() and 2 <= len(t) <= 4
        q_nums = frozenset(t for t in qtok if is_model(t))
        c_nums = frozenset(t for t in ctok if is_model(t))
        if q_nums and c_nums and q_nums.isdisjoint(c_nums):
            return 0.5
        return 1.0

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
        penalty = self._model_penalty(qtok, ctok)
        return min(1.0, (0.60 * cov_c + 0.40 * cov_q) * penalty)

    def _confidence(self, qtok, ctok) -> float:
        # DISPLAY confidence for the chosen winner: same blend, plus a bonus
        # when the DB product name is fully present in the line (cov_c ~ 1),
        # so an exact name match auto-approves even inside a verbose line.
        cov_c, cov_q = self._covs(qtok, ctok)
        base = 0.60 * cov_c + 0.40 * cov_q
        if cov_c >= 0.95:
            base += 0.15
        penalty = self._model_penalty(qtok, ctok)
        return min(1.0, base * penalty)

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
        qtok = self._qtokens(normalize(raw_name))
        result = {"query": raw_name, "status": STATUS_NOT_FOUND, "confidence": 0.0,
                  "permit": None, "manufacturer": None, "matched_name": None,
                  "cert_url": None, "made_in_israel": False, "mii_confidence": 0.0, "official_url": None,
                  "mii_status": "none", "mii_matched_name": None}

        # 1) Learned memory wins outright: exact alias (fixes a repeated misread)
        #    + fuzzy recall (tolerates OCR variance). Human-verified & shared.
        if self.memory is not None:
            mem = self.memory.lookup(raw_name, self._confidence)
            if mem:
                rec = dict(result)
                rec.update(mem)
                rec["query"] = raw_name
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

    def confirm(self, original_read: str, record: dict, corrected_name: str = None) -> bool:
        """Record a human correction into the shared memory.

        original_read  — exactly what the OCR produced (becomes an alias).
        corrected_name — the human-fixed product name (defaults to the read/match).
        record         — the verified result carrying the corrected permit/link/status.

        A name fix makes the misread resolve next time; a link/permit fix is stored
        on the product and overrides the fuzzy matcher from then on."""
        if self.memory is None:
            return False
        canonical = corrected_name or record.get("query") or record.get("matched_name") or original_read
        rec = {k: record.get(k) for k in RESULT_KEYS if k in record}
        return self.memory.learn(original_read, canonical, rec)

    def unconfirm(self, raw_name: str) -> bool:
        """Remove a learned correction (undo)."""
        return self.memory.forget(raw_name) if self.memory is not None else False

    def match_many(self, names):
        return [self.match(n) for n in names]

    @property
    def counts(self):
        return {"sii": len(self.sii), "mii": len(self.mii),
                "verified": self.memory.count if self.memory is not None else 0}
