"""Source ingestion: uploads, docs-site snapshots, change detection.

Every source is an immutable, hashed snapshot. A source keeps a stable id per origin (file name or
URL) so claim IDs stay stable; each new version of its bytes is stored under its sha256.
Normalized text is a list of blocks with stable locations ("Heading > Sub ¶2", "Slide 3 ¶1", "Page 4").
"""
import html
import io
import json
import os
import re
import urllib.parse
import urllib.request
import zipfile
import zlib
from html.parser import HTMLParser

from packages.util import now_iso, sha256_bytes, word_count

SOURCE_TYPES = ("truth", "style", "positioning", "evidence")
UPLOAD_EXT = {".md", ".markdown", ".txt", ".html", ".htm", ".docx", ".pptx", ".pdf", ".json"}


class IngestError(ValueError):
    pass


def slugify(s, maxlen=48):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return (s[:maxlen].rstrip("-") or "source")


# ---------------- parsers ----------------

FRONT_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)


def parse_frontmatter(text):
    m = FRONT_RE.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.split("#")[0].strip().strip('"').strip("'") if k.strip() != "url" else v.strip()
    return meta, text[m.end():]


class _Blocks:
    def __init__(self):
        self.path, self.blocks, self.counter = [], [], {}

    def heading(self, level, text):
        text = text.strip()
        if not text:
            return
        self.path = self.path[: level - 1] + [text]
        self.blocks.append({"loc": " > ".join(self.path), "heading_path": list(self.path), "text": text})

    def para(self, text):
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return
        key = tuple(self.path)
        self.counter[key] = self.counter.get(key, 0) + 1
        loc = (" > ".join(self.path) + " " if self.path else "") + f"¶{self.counter[key]}"
        self.blocks.append({"loc": loc, "heading_path": list(self.path), "text": text})


def parse_markdown(text):
    meta, body = parse_frontmatter(text)
    b, para, in_code = _Blocks(), [], False

    def flush():
        if para:
            b.para(" ".join(para))
            para.clear()

    for line in body.splitlines():
        if line.strip().startswith("```"):
            flush()
            in_code = not in_code
            continue
        if in_code:
            continue
        h = re.match(r"^(#{1,6})\s+(.*)$", line)
        if h:
            flush()
            b.heading(len(h.group(1)), re.sub(r"[*_`]", "", h.group(2)))
            continue
        if not line.strip():
            flush()
            continue
        li = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$", line)
        if li:
            flush()
            b.para(_md_inline(li.group(1)))
            continue
        if line.strip().startswith("|"):
            flush()
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not all(set(c) <= set("-: ") for c in cells):
                b.para(" | ".join(_md_inline(c) for c in cells))
            continue
        para.append(_md_inline(line.strip()))
    flush()
    return meta, b.blocks


def _md_inline(s):
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    return re.sub(r"(\*\*|__|`)", "", s)


class _HTML(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "header", "noscript", "svg"}
    BLOCK = {"p", "li", "td", "th", "blockquote", "dd", "dt", "figcaption", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.b, self.buf, self.skip, self.head, self.title, self.in_title = _Blocks(), [], 0, None, "", False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag == "title":
            self.in_title = True
        elif re.fullmatch(r"h[1-6]", tag) or tag in self.BLOCK or tag in ("br", "div"):
            self._flush()
            if re.fullmatch(r"h[1-6]", tag):
                self.head = int(tag[1])

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag == "title":
            self.in_title = False
        elif re.fullmatch(r"h[1-6]", tag) or tag in self.BLOCK or tag == "div":
            self._flush()

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.skip:
            self.buf.append(data)

    def _flush(self):
        text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        self.buf = []
        if not text:
            self.head = None
            return
        if self.head:
            self.b.heading(self.head, text)
        else:
            self.b.para(text)
        self.head = None


def parse_html(text):
    p = _HTML()
    p.feed(text)
    p._flush()
    return {"title": html.unescape(p.title.strip())}, p.b.blocks


def _xml_text(xml, para_tag, text_tag):
    paras = re.findall(rf"<{para_tag}[ >].*?</{para_tag}>", xml, re.S)
    out = []
    for p in paras:
        style = re.search(r'w:pStyle w:val="([^"]+)"', p)
        t = "".join(html.unescape(x) for x in re.findall(rf"<{text_tag}(?: [^>]*)?>(.*?)</{text_tag}>", p, re.S))
        out.append((style.group(1) if style else "", t))
    return out


def parse_docx(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
        core = z.read("docProps/core.xml").decode("utf-8", "replace") if "docProps/core.xml" in z.namelist() else ""
    b = _Blocks()
    for style, t in _xml_text(xml, "w:p", "w:t"):
        m = re.match(r"(?i)heading\s?(\d)", style)
        level = int(m.group(1)) if m else 1 if re.match(r"(?i)title$", style) else 0
        if level and t.strip():
            b.heading(level, t)
        else:
            b.para(t)
    title = re.search(r"<dc:title>(.*?)</dc:title>", core)
    return {"title": html.unescape(title.group(1)) if title else ""}, b.blocks


def parse_pptx(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                       key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)))
        blocks = []
        for n in names:
            num = int(re.search(r"slide(\d+)\.xml", n).group(1))
            xml = z.read(n).decode("utf-8", "replace")
            k = 0
            for _, t in _xml_text(xml, "a:p", "a:t"):
                if t.strip():
                    k += 1
                    blocks.append({"loc": f"Slide {num} ¶{k}", "heading_path": [f"Slide {num}"], "text": t.strip()})
    return {}, blocks


def parse_pdf(data):
    """Basic text extraction (Flate or uncompressed content streams, Tj/TJ operators).
    Scanned or unusually encoded PDFs need OCR or a full parser; they fail loudly here."""
    pages, blocks = re.split(rb"/Type\s*/Page[^s]", data), []
    streams = re.findall(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S)
    texts = []
    for s in streams:
        try:
            raw = zlib.decompress(s)
        except zlib.error:
            raw = s
        parts = []
        for m in re.finditer(rb"\((.*?)(?<!\\)\)\s*Tj|\[(.*?)\]\s*TJ|(T\*|ET)", raw, re.S):
            if m.group(1) is not None:
                parts.append(_pdf_str(m.group(1)))
            elif m.group(2) is not None:
                parts.append("".join(_pdf_str(x) for x in re.findall(rb"\((.*?)(?<!\\)\)", m.group(2), re.S)))
            else:
                parts.append("\n")
        t = "".join(parts).strip()
        if t:
            texts.append(t)
    if not texts:
        raise IngestError("No extractable text in this PDF (scanned or unsupported encoding). Export it as text or DOCX.")
    for pi, t in enumerate(texts, 1):
        for k, para in enumerate([p for p in re.split(r"\n\s*\n|\n", t) if p.strip()], 1):
            blocks.append({"loc": f"Page {pi} ¶{k}", "heading_path": [f"Page {pi}"], "text": re.sub(r"\s+", " ", para).strip()})
    return {}, blocks


def _pdf_str(b):
    b = re.sub(rb"\\([nrtbf()\\])", lambda m: {b"n": b"\n", b"r": b"", b"t": b" ", b"b": b"", b"f": b""}.get(m.group(1), m.group(1)), b)
    return b.decode("latin-1")


def parse_evidence_json(data):
    obj = json.loads(data)
    blocks = []
    for r in obj.get("responses", []):
        rid = str(r.get("id", len(blocks) + 1))
        ans = r.get("answers", {})
        text = " | ".join(f"{k}: {v}" for k, v in ans.items())
        if r.get("segment"):
            text = f"segment: {r['segment']} | " + text
        blocks.append({"loc": f"response {rid}", "heading_path": ["responses"], "text": text})
    return {"title": obj.get("title", "evidence"), "kind": "evidence"}, blocks


def parse_file(filename, data):
    ext = os.path.splitext(filename.lower())[1]
    if ext not in UPLOAD_EXT:
        raise IngestError(f"Unsupported file type {ext or '(none)'}. Supported: {', '.join(sorted(UPLOAD_EXT))}")
    if ext in (".md", ".markdown", ".txt"):
        return parse_markdown(data.decode("utf-8", "replace"))
    if ext in (".html", ".htm"):
        return parse_html(data.decode("utf-8", "replace"))
    if ext == ".docx":
        return parse_docx(data)
    if ext == ".pptx":
        return parse_pptx(data)
    if ext == ".pdf":
        return parse_pdf(data)
    return parse_evidence_json(data)


# ---------------- evidence encryption ----------------

def _fernet():
    key = os.environ.get("VCE_EVIDENCE_KEY")
    try:
        from cryptography.fernet import Fernet  # optional dependency
    except ImportError:
        return None
    return Fernet(key.encode()) if key else None


def protect_evidence(data):
    f = _fernet()
    if f:
        return b"FERNET:" + f.encrypt(data)
    if os.environ.get("VCE_ALLOW_PLAINTEXT_EVIDENCE") == "1":
        return data
    raise IngestError("Evidence sources must be encrypted at rest. Install the 'cryptography' package and set "
                      "VCE_EVIDENCE_KEY, or (local fixtures only) set VCE_ALLOW_PLAINTEXT_EVIDENCE=1.")


def unprotect_evidence(data):
    if data.startswith(b"FERNET:"):
        f = _fernet()
        if not f:
            raise IngestError("VCE_EVIDENCE_KEY is required to read encrypted evidence.")
        return f.decrypt(data[len(b"FERNET:"):])
    return data


# ---------------- snapshots ----------------

def _kind_for(source_type, meta, name):
    k = (meta.get("kind") or "").lower()
    if source_type == "truth":
        if k in ("living", "changelog"):
            return k
        return "changelog" if re.search(r"change.?log|release.?notes", name, re.I) else "living"
    if source_type == "positioning" and (k == "brief" or re.search(r"\bbrief\b", name, re.I)):
        return "brief"
    return {"style": "style", "positioning": "positioning", "evidence": "evidence"}[source_type]


def add_source(ws, product_id, source_type, name, data, origin_kind="file", origin=None):
    """Store a new snapshot. Returns (source, changed: bool). Same origin + same bytes = no change."""
    if source_type not in SOURCE_TYPES:
        raise IngestError(f"source type must be one of {SOURCE_TYPES}")
    if source_type == "evidence" and not ws.settings.get("evidence_enabled"):
        raise IngestError("Evidence sources are disabled for this workspace (Settings → data handling).")
    meta, blocks = parse_file(name, data)
    if not blocks:
        raise IngestError(f"{name}: no text found")
    sha = sha256_bytes(data)
    sid = f"{source_type[:3]}-" + slugify(origin or name)
    prev = ws.get("source", sid)
    if prev and prev["sha256"] == sha and prev["status"] == "active":
        return prev, False
    raw = protect_evidence(data) if source_type == "evidence" else data
    ws.put_object(product_id, f"sources/{sid}/{sha}.raw", raw)
    norm = {"source_id": sid, "sha256": sha, "blocks": blocks}
    norm_bytes = json.dumps(norm, ensure_ascii=False).encode("utf-8")
    ws.put_object(product_id, f"sources/{sid}/{sha}.json",
                  protect_evidence(norm_bytes) if source_type == "evidence" else norm_bytes)
    src = {"id": sid, "product_id": product_id, "type": source_type,
           "title": meta.get("title") or os.path.splitext(os.path.basename(name))[0],
           "origin": {"kind": origin_kind, "value": origin or meta.get("url") or name},
           "kind": _kind_for(source_type, meta, name), "updated": meta.get("updated"),
           "fetched_at": now_iso(), "sha256": sha, "status": "active",
           "words": sum(word_count(b["text"]) for b in blocks)}
    ws.put("source", src)
    return src, True


def remove_source(ws, source_id):
    src = ws.get("source", source_id)
    if not src:
        raise KeyError(source_id)
    src["status"] = "removed"
    ws.put("source", src)
    return src


def normalized(ws, source):
    raw = ws.get_object(f"{source['product_id']}/sources/{source['id']}/{source['sha256']}.json")
    if source["type"] == "evidence":
        raw = unprotect_evidence(raw)
    return json.loads(raw)


def snapshot_text(ws, source):
    return "\n".join(b["text"] for b in normalized(ws, source)["blocks"])


# ---------------- docs-site import ----------------

def _fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "VerifiedContentEngine/1.0 (snapshot import)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.headers.get("Content-Type", "")


def discover(base, mode):
    """Page URLs from llms.txt, a sitemap, or links under a URL prefix."""
    if mode == "llms":
        url = base if base.endswith("llms.txt") else base.rstrip("/") + "/llms.txt"
        body, _ = _fetch(url)
        links = re.findall(r"\]\((https?://[^)\s]+|/[^)\s]+)\)", body.decode("utf-8", "replace"))
        return [urllib.parse.urljoin(url, u) for u in links]
    if mode == "sitemap":
        url = base if base.endswith(".xml") else base.rstrip("/") + "/sitemap.xml"
        body, _ = _fetch(url)
        return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body.decode("utf-8", "replace"))
    if mode == "prefix":
        body, _ = _fetch(base)
        hrefs = re.findall(r'href="([^"#]+)"', body.decode("utf-8", "replace"))
        urls = {urllib.parse.urljoin(base, h) for h in hrefs}
        return sorted([base] + [u for u in urls if u.startswith(base) and u != base])
    raise IngestError("mode must be llms, sitemap or prefix")


def import_docs_site(ws, product_id, base, mode="llms", limit=500, label=None):
    """Snapshot a docs site as truth sources. Writes a manifest (url, fetch time, sha256 per page)."""
    urls = list(dict.fromkeys(discover(base, mode)))[:limit]
    manifest, changed, errors = [], [], []
    for url in urls:
        try:
            body, ctype = _fetch(url)
            name = urllib.parse.urlparse(url).path or "/index"
            if not re.search(r"\.(md|markdown|txt|html?)$", name, re.I):
                name = name.rstrip("/") + (".md" if "markdown" in ctype or "text/plain" in ctype else ".html")
            src, ch = add_source(ws, product_id, "truth", name, body, origin_kind="url", origin=url)
            manifest.append({"url": url, "source_id": src["id"], "fetched_at": src["fetched_at"], "sha256": src["sha256"]})
            if ch:
                changed.append(src["id"])
        except Exception as e:  # one bad page never stops the import
            errors.append({"url": url, "error": str(e)[:200]})
    label = label or slugify(urllib.parse.urlparse(base).netloc)
    ws.put_json(product_id, f"sources/_manifests/{label}.json",
                {"base": base, "mode": mode, "imported_at": now_iso(), "pages": manifest, "errors": errors})
    return {"pages": len(manifest), "changed": changed, "errors": errors, "manifest": f"{product_id}/sources/_manifests/{label}.json"}


# ---------------- optional docs search (discovery only, never citable) ----------------

class DocsSearch:
    """Adapter interface for a product's docs search service. Results are hints for discovery and
    coverage; they are never stored as quotes. The default implementation searches local snapshots."""

    def __init__(self, ws, product_id):
        self.ws, self.product_id = ws, product_id

    def search(self, query, limit=10):
        from packages.util import tokens
        q = set(tokens(query))
        hits = []
        for s in self.ws.list("source", self.product_id):
            if s["type"] != "truth" or s["status"] != "active":
                continue
            for b in normalized(self.ws, s)["blocks"]:
                score = len(q & set(tokens(b["text"])))
                if score:
                    hits.append({"source_id": s["id"], "title": s["title"], "loc": b["loc"], "score": score,
                                 "snippet": b["text"][:200]})
        return sorted(hits, key=lambda h: -h["score"])[:limit]
