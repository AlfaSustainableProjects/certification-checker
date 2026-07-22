"""
memory.py — shared, learnable correction memory for the certification checker.

Stores, per human-verified product:
  * canonical  — the corrected/true product name
  * aliases    — every misread (OCR output) that was corrected to it
  * answer     — the verified result (permit + official_url + manufacturer + status ...)

So a correction generalises two ways:
  1. Name fix   — the misread string becomes an alias, so the NEXT time the OCR
                  produces that same (wrong) read, it resolves to the right product.
  2. Link fix   — the verified permit/link is stored on the product and always
                  overrides the fuzzy matcher's guess.
Reads also fuzzy-match against the memory, so a slightly different OCR of the
same product still resolves.

STORAGE is pluggable so the memory is NOT tied to one desktop:
  * FileStore  — local JSON file (development / single machine).
  * KvStore    — Vercel KV / Upstash Redis over REST (production). Every deployed
                 instance shares the SAME store, so a correction made by any user
                 on any computer is instantly available to everyone.

Backend is chosen from the environment:
  KV_REST_API_URL + KV_REST_API_TOKEN            (Vercel KV)         -> shared
  UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN (Upstash)        -> shared
  BLOB_READ_WRITE_TOKEN                          (Vercel Blob)       -> shared
  otherwise MEMORY_FILE (or ./corrections.json)                       -> local file

Pure standard library.
"""

import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request

MEM_KEY = "cert_corrections_v2"
MEMORY_THRESHOLD = 0.80  # fuzzy-recall bar for the human-verified memory


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --------------------------------------------------------------------------- #
# Storage backends
# --------------------------------------------------------------------------- #
class FileStore:
    def __init__(self, path):
        self.path = path

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def save(self, data):
        # Unique scratch name per save: concurrent saves each write their own
        # temp file, so overlapping writes can never delete each other's scratch
        # (a fixed ".tmp" name made parallel saves race and fail).
        tmp = "%s.%d.%d.tmp" % (self.path, os.getpid(), threading.get_ident())
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)  # atomic on same filesystem

    def describe(self):
        return "file:" + self.path


class KvStore:
    """Vercel KV / Upstash Redis over REST. Whole memory blob under one key."""

    def __init__(self, url, token, key=MEM_KEY):
        self.url = url.rstrip("/")
        self.token = token
        self.key = key

    def _cmd(self, command):
        req = urllib.request.Request(
            self.url,
            data=json.dumps(command).encode("utf-8"),
            headers={"Authorization": "Bearer " + self.token,
                     "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))

    def load(self):
        try:
            res = self._cmd(["GET", self.key]).get("result")
            return json.loads(res) if res else None
        except Exception:
            return None

    def save(self, data):
        self._cmd(["SET", self.key, json.dumps(data, ensure_ascii=False)])

    def describe(self):
        return "kv:" + self.url


class BlobStore:
    """Vercel Blob over REST (BLOB_READ_WRITE_TOKEN, auto-set when a Blob store
    is connected to the project). Whole memory as one JSON blob."""

    API = os.environ.get("BLOB_API_URL", "https://blob.vercel-storage.com")
    PATH = "cert_corrections_v2.json"

    def __init__(self, token):
        self.token = token

    def _headers(self, extra=None):
        h = {"authorization": "Bearer " + self.token, "x-api-version": "7"}
        if extra:
            h.update(extra)
        return h

    def load(self):
        try:
            q = urllib.parse.urlencode({"prefix": self.PATH, "limit": "10"})
            req = urllib.request.Request(self.API + "?" + q, headers=self._headers())
            with urllib.request.urlopen(req, timeout=10) as r:
                listing = json.loads(r.read().decode("utf-8"))
            for b in listing.get("blobs", []):
                if b.get("pathname") == self.PATH:
                    url = b["url"] + "?v=" + str(int(time.time()))  # bust CDN cache
                    with urllib.request.urlopen(url, timeout=10) as r:
                        return json.loads(r.read().decode("utf-8"))
        except Exception:
            pass
        return None

    def save(self, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.API + "/" + self.PATH, data=body, method="PUT",
            headers=self._headers({
                "x-add-random-suffix": "0",
                "x-allow-overwrite": "1",
                "x-content-type": "application/json",
                "x-cache-control-max-age": "60",
            }),
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()

    def describe(self):
        return "vercel-blob:" + self.PATH


def make_store():
    url = os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")
    token = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    if url and token:
        return KvStore(url, token)
    blob_token = (os.environ.get("BLOB_READ_WRITE_TOKEN") or "").strip()
    if blob_token:
        return BlobStore(blob_token)
    path = os.environ.get("MEMORY_FILE") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "corrections.json")
    return FileStore(path)


# --------------------------------------------------------------------------- #
# Memory
# --------------------------------------------------------------------------- #
class Memory:
    """Alias-based, human-verified correction memory. `normalize` and `qtokens`
    are injected from the matcher so keys/tokens match the matcher exactly."""

    def __init__(self, store, normalize, qtokens, result_keys=None, migrate_from=None):
        self.store = store
        self._normalize = normalize
        self._qtokens = qtokens
        self._result_keys = tuple(result_keys) if result_keys else None
        self.entries = []
        self._reload(migrate_from)

    # ---- load / index ----
    def _reload(self, migrate_from=None):
        data = self.store.load()
        if not data and migrate_from:
            data = self._migrate(migrate_from)
        if isinstance(data, dict):
            self.entries = data.get("entries", []) or []
        else:
            self.entries = []
        self._index()

    def _entry_keys(self, e):
        return [e.get("canonical", "")] + list(e.get("aliases", []))

    def _index(self):
        self._by_norm = {}
        for e in self.entries:
            keytok = []
            for key in self._entry_keys(e):
                nk = self._normalize(key)
                if nk:
                    self._by_norm[nk] = e
                    keytok.append(frozenset(self._qtokens(nk)))
            e["_keytok"] = keytok

    def _migrate(self, verified_dict):
        """Convert an old flat verified_answers.json {norm_name: result} into the
        new alias structure, and persist it once."""
        entries = []
        for k, rec in (verified_dict or {}).items():
            canonical = rec.get("query") or k
            aliases = []
            if self._normalize(k) != self._normalize(canonical):
                aliases.append(k)
            answer = {kk: vv for kk, vv in rec.items() if kk not in ("query", "verified")}
            entries.append({"canonical": canonical, "aliases": aliases,
                            "answer": answer, "hit_count": 0, "updated_at": rec.get("updated_at", "")})
        data = {"version": 2, "entries": entries}
        try:
            self.store.save(data)
        except Exception:
            pass
        return data

    # ---- read path ----
    def lookup(self, raw, score_fn, threshold=MEMORY_THRESHOLD):
        n = self._normalize(raw)
        if not n:
            return None
        # 1) exact alias / canonical hit — zero risk, fixes the repeated misread
        e = self._by_norm.get(n)
        if e:
            return self._answer(e, raw)
        # 2) fuzzy hit against verified memory: score the read against EACH stored
        #    form (canonical + each alias) individually, take the best.
        qtok = frozenset(self._qtokens(n))
        best, best_s = None, 0.0
        for e in self.entries:
            s = max((score_fn(qtok, kt) for kt in e.get("_keytok", [])), default=0.0)
            if s > best_s:
                best, best_s = e, s
        if best and best_s >= threshold:
            self._add_alias_mem(best, raw)  # in-memory only (no write on reads)
            return self._answer(best, raw)
        return None

    def _answer(self, e, raw):
        e["hit_count"] = e.get("hit_count", 0) + 1
        ans = dict(e.get("answer", {}))
        ans["query"] = raw
        if not ans.get("matched_name"):
            ans["matched_name"] = e.get("canonical")
        # "verified" (the SII-side flag) is intentionally NOT persisted as raw
        # data — learn() strips it before storing. It's derived here instead,
        # from whether this entry carries genuine SII-confirmation evidence
        # (a status/permit set by a human confirm, or a verified cert link).
        # This is deliberate, not a legacy shim: without it, a product that was
        # ONLY ever confirmed on the MII side would be mistaken for an
        # SII-verified one too, since both registries share the same memory
        # entry. mii_verified / mii_link_verified / cert_verified ARE stored
        # as-is and never derived — they reflect exactly what was confirmed.
        ans["verified"] = bool(ans.get("status") or ans.get("permit") is not None or ans.get("cert_verified"))
        ans["from_memory"] = True
        return ans

    def _add_alias_mem(self, e, raw):
        cnorm = self._normalize(e.get("canonical", ""))
        onorm = self._normalize(raw)
        if onorm and onorm != cnorm and raw not in e.get("aliases", []):
            e.setdefault("aliases", []).append(raw)
            self._by_norm[onorm] = e
            e.setdefault("_keytok", []).append(frozenset(self._qtokens(onorm)))

    # ---- write path ----
    def learn(self, original_read, corrected_name, answer):
        """Record a human correction. `original_read` = what the OCR produced,
        `corrected_name` = the human-fixed name (may equal original), `answer` =
        the verified result (corrected permit/link/status)."""
        self._reload()  # pull latest shared state first, to reduce clobber
        canonical = (corrected_name or original_read or "").strip()
        cnorm = self._normalize(canonical)
        if not cnorm:
            return False
        e = self._by_norm.get(cnorm)
        if not e:
            e = {"canonical": canonical, "aliases": [], "answer": {}, "hit_count": 0}
            self.entries.append(e)
        e["canonical"] = canonical
        if original_read:
            onorm = self._normalize(original_read)
            if onorm and onorm != cnorm and original_read not in e["aliases"]:
                e["aliases"].append(original_read)
        clean = dict(answer or {})
        for junk in ("query", "verified", "from_memory"):
            clean.pop(junk, None)
        if self._result_keys:
            clean = {k: v for k, v in clean.items() if k in self._result_keys}
        e.setdefault("answer", {}).update({k: v for k, v in clean.items() if v is not None})
        e["updated_at"] = _now()
        self._index()
        self._persist()
        return True

    def forget(self, name):
        """Surgical un-learn. If `name` is an entry's CANONICAL, the whole entry
        is removed (the user is cancelling that product's verification). If it
        only matches an ALIAS, just that alias is dropped — the canonical name,
        verified permit/link and other aliases stay intact."""
        n = self._normalize(name)
        if not n:
            return False
        keep = []
        changed = False
        for e in self.entries:
            if self._normalize(e.get("canonical", "")) == n:
                changed = True          # canonical -> remove entire entry
                continue
            aliases = e.get("aliases", [])
            pruned = [a for a in aliases if self._normalize(a) != n]
            if len(pruned) != len(aliases):
                e["aliases"] = pruned   # alias -> drop only that reading
                changed = True
            keep.append(e)
        if changed:
            self.entries = keep
            self._index()
            self._persist()
        return changed

    def _persist(self):
        data = {"version": 2, "entries": [
            {k: v for k, v in e.items() if not k.startswith("_")} for e in self.entries]}
        try:
            self.store.save(data)
        except Exception as exc:
            # e.g. read-only filesystem on serverless with no shared store
            # connected: keep the correction for this process, warn loudly.
            print("memory: persist failed (%s) — correction is in-memory only; "
                  "connect a Blob/KV store for shared persistence" % exc,
                  file=sys.stderr)

    @property
    def count(self):
        return len(self.entries)

    def describe(self):
        return self.store.describe()
