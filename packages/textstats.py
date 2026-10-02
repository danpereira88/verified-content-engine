"""Deterministic text measurements shared by style extraction, style checking and calibration."""
import re

from packages.util import split_sentences, word_count

YOU_RE = re.compile(r"\b(you|your|you're|yours)\b", re.I)


def _blocks_from_md(md):
    paras, cur = [], []
    for line in md.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            if cur:
                paras.append(" ".join(cur))
                cur = []
            continue
        cur.append(line.strip().lstrip("-*+ ").strip())
    if cur:
        paras.append(" ".join(cur))
    return paras


def headings(md):
    return [re.sub(r"\[\[[^\]]+\]\]", "", m.group(1)).strip() for m in re.finditer(r"^#{1,6}\s+(.*)$", md, re.M)]


def heading_case(hs):
    def is_title(h):
        words = [w for w in re.findall(r"[A-Za-z][A-Za-z'-]*", h) if len(w) > 3]
        return len(words) >= 2 and sum(w[0].isupper() for w in words[1:]) >= max(1, (len(words) - 1) * 0.6)
    if not hs:
        return "sentence"
    t = sum(is_title(h) for h in hs) / len(hs)
    return "title" if t > 0.6 else "sentence" if t < 0.25 else "mixed"


def measure(texts):
    """texts: list of Markdown/plain strings. Returns cadence + formatting measurements."""
    sents, paras, hs, lists, lines = [], [], [], 0, 0
    for t in texts:
        ps = _blocks_from_md(t)
        paras += [len(split_sentences(p)) for p in ps if p]
        for p in ps:
            sents += split_sentences(p)
        hs += headings(t)
        for line in t.splitlines():
            if line.strip():
                lines += 1
                lists += bool(re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", line))
    lens = sorted(word_count(s) for s in sents) or [0]

    def pct(p):
        return float(lens[min(len(lens) - 1, int(p * (len(lens) - 1)))])
    n = max(1, len(sents))
    return {
        "avg_sentence_words": round(sum(lens) / max(1, len(lens)), 2),
        "sentence_words_p10": pct(0.1), "sentence_words_p90": pct(0.9),
        "avg_paragraph_sentences": round(sum(paras) / max(1, len(paras)), 2),
        "question_rate": round(sum(s.rstrip().endswith("?") for s in sents) / n, 3),
        "second_person_rate": round(sum(bool(YOU_RE.search(s)) for s in sents) / n, 3),
        "exclamation_rate": round(sum(s.rstrip().endswith("!") for s in sents) / n, 3),
        "heading_case": heading_case(hs), "list_line_rate": round(lists / max(1, lines), 3),
        "sentences": len(sents), "words": sum(word_count(t) for t in texts),
    }
