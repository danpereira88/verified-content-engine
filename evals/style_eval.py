"""Style eval and threshold calibration.

Labeled set = on-brand chunks of the team's own approved copy + off-brand variants generated from
them (hype, corporate third person, wrong naming, banned terms). Labeled samples in
evals/style/<slug>/{on,off}/*.md are added when present. Scores every sample, reports AUC and
recommends the threshold that best separates the two (Youden's J). An admin accepts it; it is
never hardcoded.
"""
import re
from pathlib import Path

from agents.offline import style_score
from packages.util import now_iso, split_sentences

HERE = Path(__file__).resolve().parent
HYPE = ["revolutionary", "game-changing", "cutting-edge", "best-in-class", "world-class", "unparalleled", "synergy"]


def chunks(text, target=180):
    out, cur, n = [], [], 0
    for para in re.split(r"\n\s*\n", text):
        w = len(para.split())
        if not para.strip():
            continue
        cur.append(para)
        n += w
        if n >= target:
            out.append("\n\n".join(cur))
            cur, n = [], 0
    if cur and (n >= target / 2 or not out):
        out.append("\n\n".join(cur))
    return out


def _title_case(md):
    return re.sub(r"^(#{1,6}\s+)(.*)$", lambda m: m.group(1) + m.group(2).title(), md, flags=re.M)


def off_brand(md, profile, k):
    name = profile["naming"]["product_name"]
    variants = []
    hype = HYPE[k % len(HYPE)]
    sents = split_sentences(re.sub(r"^#.*$", "", md, flags=re.M))
    body = " ".join(sents)
    # 1. hype and exclamation
    v = re.sub(r"\.(\s|$)", r"!\1", md, count=6)
    v = v.replace(name, f"the {hype} {name}", 2)
    variants.append(_title_case(v))
    # 2. corporate third person, long merged sentences
    corp = re.sub(r"\byou(r)?\b", lambda m: "organizations'" if m.group(1) else "organizations", body, flags=re.I)
    merged = [", and furthermore, ".join(sents[i:i + 3]).replace("., and", ", and") for i in range(0, len(sents), 3)]
    variants.append(re.sub(r"\byou(r)?\b", "organizations", " ".join(merged), flags=re.I) or corp)
    # 3. wrong naming
    forb = profile["naming"]["forbidden"]
    variants.append(md.replace(name, forb[k % len(forb)]) if forb else md.replace(name, "the solution"))
    # 4. banned terms
    banned = profile["vocabulary"]["banned"]
    if banned:
        variants.append(re.sub(r"\b(easy|simple|clear|quick)\b", banned[k % len(banned)], md, count=3, flags=re.I)
                        + f"\n\nIt is {banned[k % len(banned)]} and {hype}.")
    return variants


def auc(pos, neg):
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return round(wins / (len(pos) * len(neg)), 4)


def best_threshold(pos, neg):
    cands = sorted(set(pos + neg))
    best, best_j = None, -1
    for i, t in enumerate(cands):
        tpr = sum(p >= t for p in pos) / len(pos)
        fpr = sum(n >= t for n in neg) / len(neg)
        j = tpr - fpr
        if j > best_j:
            lower = max([x for x in cands if x < t], default=t)
            best, best_j = round((t + lower) / 2, 3), j
    return best, round(best_j, 3)


def calibrate(profile, texts, labeled_dir=None, scorer=None):
    scorer = scorer or (lambda md: style_score(md, profile)[0])
    pos_texts = [c for t in texts for c in chunks(t)]
    neg_texts = [v for k, c in enumerate(pos_texts) for v in off_brand(c, profile, k)]
    if labeled_dir and Path(labeled_dir).exists():
        pos_texts += [p.read_text() for p in sorted(Path(labeled_dir, "on").glob("*.md"))]
        neg_texts += [p.read_text() for p in sorted(Path(labeled_dir, "off").glob("*.md"))]
    pos = [scorer(t) for t in pos_texts]
    neg = [scorer(t) for t in neg_texts]
    thr, j = best_threshold(pos, neg) if pos and neg else (None, None)
    return {"auc": auc(pos, neg), "recommended_threshold": thr, "youden_j": j, "on_brand": len(pos), "off_brand": len(neg),
            "on_mean": round(sum(pos) / max(1, len(pos)), 3), "off_mean": round(sum(neg) / max(1, len(neg)), 3),
            "target_auc": 0.9, "meets_target": (auc(pos, neg) or 0) >= 0.9, "scorer": "deterministic-style-score",
            "computed_at": now_iso()}
