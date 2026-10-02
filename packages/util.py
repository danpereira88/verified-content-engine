"""Small shared helpers: time, hashing, ids, text normalization, sentence splitting."""
import datetime as _dt
import hashlib
import json
import re
import secrets

TAG_RE = re.compile(r"\[\[([A-Z][A-Z0-9]{1,15}-[0-9]{3,})\]\]")
WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’\-\.]*")


def now_iso():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def new_id(prefix=""):
    return (prefix + "-" if prefix else "") + secrets.token_hex(6)


def norm_ws(text):
    return re.sub(r"\s+", " ", (text or "").replace("’", "'").replace("“", '"').replace("”", '"')).strip()


def quote_hash(quote):
    return sha256_text(norm_ws(quote).lower())


def word_count(text):
    return len(WORD_RE.findall(text or ""))


def strip_tags(text):
    out = TAG_RE.sub("", text)
    out = re.sub(r"[ \t]+([.,;:!?])", r"\1", out)
    return re.sub(r"[ \t]{2,}", " ", out)


def tags_in(text):
    return TAG_RE.findall(text or "")


_ABBREV = {"e.g", "i.e", "etc", "vs", "approx", "inc", "ltd", "no", "fig", "v", "mr", "ms", "dr"}


def split_sentences(text):
    """Split prose into sentences. Keeps claim tags attached to the sentence they follow."""
    text = norm_ws(text)
    if not text:
        return []
    out, start = [], 0
    for m in re.finditer(r"[.!?](?:\s*\[\[[A-Z0-9\-]+\]\])*(?=\s+[\"'(\[]?[A-Z0-9]|$)", text):
        end = m.end()
        prev = re.search(r"([A-Za-z.]+)\.$", text[start:m.start() + 1])
        if prev and prev.group(1).lower().rstrip(".") in _ABBREV:
            continue
        if re.search(r"\d\.$", text[start:m.start() + 1]) and end < len(text) and text[end:end + 2].strip()[:1].isdigit():
            continue
        s = text[start:end].strip()
        if s:
            out.append(s)
        start = end
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out


def tokens(text, stop=None):
    words = [w.lower().strip(".'’-") for w in WORD_RE.findall(strip_tags(text or ""))]
    stop = STOPWORDS if stop is None else stop
    return [w for w in words if w and w not in stop]


STOPWORDS = set("""a an the and or but if then of to in on for with by at from as is are was were be been being it its this that
these those can will may might must should would could do does did has have had not no your you we our us their they them he she
his her i me my so than too very just also into over under about up down out more most such only own same other any each all both
via per""".split())


def dumps(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False)


def name_re(name, flags=0):
    """Match a product name used on its own: not as the start of a longer capitalised name
    ('Acme' must not match inside 'Acme Cloud')."""
    return re.compile(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])(?!\s+[A-Z0-9])(?!['’]s\s+[A-Z])", flags)
