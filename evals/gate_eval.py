"""Gate eval: seeded sentence sets built per product from its registry, plus a hand-labeled golden set.

Labels: true, untagged, false, overstated, partial, not-citable, positioning, combined-conclusion.
Metrics (CLAUDE.md §7 release targets):
    hallucination catch rate  = blocked / (false + overstated + partial + not-citable + combined-conclusion)  >= 95%
    false-block rate          = blocked / (true + positioning)                                                  <= 10%
    untagged detection        = blocked / untagged                                                              >= 95%
The verifier sees only the seeded page. Expected labels never enter its input.
"""
import random
import re

from agents.runtime import Toolbox, run_agent
from packages import gate
from packages.util import now_iso, norm_ws, strip_tags

TARGETS = {"hallucination_catch_rate": (">=", 0.95), "false_block_rate": ("<=", 0.10), "untagged_detection_rate": (">=", 0.95)}
HALLUCINATION = ("false", "overstated", "partial", "not-citable", "combined-conclusion")
SHOULD_PASS = ("true", "positioning")
POSITIONING = ["Your team deserves a calmer week.", "Built for the people who keep things running.",
               "See what changes when the busywork goes away.", "What would you do with the time back?",
               "Less firefighting, more planning.", "Start where you are."]
SUPER = ["the only", "always", "every", "the fastest", "guaranteed", "fully"]
COND_RE = re.compile(r"(,?\s*(?:on the \w+ (?:plan|edition|tier)|with firmware [\d.]+ or later|in the \w+ region|"
                     r"\(or [^)]+\)|or later|when [^,.]+|if [^,.]+|for [A-Z][\w-]+ customers)\b)", re.I)
NUM_RE = re.compile(r"\b(\d+)(\.\d+)?\b")


def _tag(text, ids):
    t = text.rstrip()
    end = "" if t.endswith((".", "!", "?")) else "."
    return t + end + " " + " ".join(f"[[{i}]]" for i in ids)


def build_seeds(claims, golden=None, per_kind=12, seed=7):
    rnd = random.Random(seed)
    ver = sorted([c for c in claims.values() if c["status"] == "verified" and c["category"] != "market-evidence"],
                 key=lambda c: c["id"])
    out = []
    pick = lambda xs, n: rnd.sample(xs, min(n, len(xs)))
    for c in pick(ver, per_kind):
        out.append({"id": f"S-true-{c['id']}", "label": "true", "text": _tag(c["text"], [c["id"]])})
    for c in pick(ver, per_kind):
        out.append({"id": f"S-untagged-{c['id']}", "label": "untagged", "text": c["text"]})
    numeric = [c for c in ver if NUM_RE.search(c["text"])]
    for c in pick(numeric, per_kind):
        m = NUM_RE.search(c["text"])
        n = int(m.group(1))
        new = str(n * 2 + 1 if n < 1000 else n // 2)
        out.append({"id": f"S-false-{c['id']}", "label": "false",
                    "text": _tag(c["text"][:m.start(1)] + new + c["text"][m.end(1):], [c["id"]])})
    for k, c in enumerate(pick(ver, per_kind)):
        m = COND_RE.search(c["text"])
        if m and k % 2 == 0:
            txt = (c["text"][:m.start()] + c["text"][m.end():]).replace(" .", ".")
        else:
            txt = re.sub(r"^(\S+(?:\s\S+)?)\s(is|are|can|supports?|provides?|lets?|keeps?|sends?|stores?)\b",
                         lambda mm: f"{mm.group(1)} {mm.group(2)} {SUPER[k % len(SUPER)]}" if mm.group(2) in ("is", "are")
                         else f"{mm.group(1)} {SUPER[k % len(SUPER)].replace('the ', '')} {mm.group(2)}", c["text"], count=1)
            if txt == c["text"]:
                txt = "Only " + c["text"][0].lower() + c["text"][1:]
        out.append({"id": f"S-overstated-{c['id']}", "label": "overstated", "text": _tag(txt, [c["id"]])})
    pool = pick(ver, per_kind * 2)
    for a, b in zip(pool[::2], pool[1::2]):
        extra = re.sub(r"^.*?\b(is|are|can|supports?|provides?|lets?|sends?|stores?|keeps?|includes?)\b", r"\1",
                       b["text"].rstrip("."), count=1)
        out.append({"id": f"S-partial-{a['id']}", "label": "partial",
                    "text": _tag(a["text"].rstrip(".") + ", and it also " + extra, [a["id"]])})
    nc = sorted([c for c in claims.values() if c["status"] in ("needs-review", "deprecated")], key=lambda c: c["id"])
    for c in pick(nc, per_kind):
        out.append({"id": f"S-notcitable-{c['id']}", "label": "not-citable", "text": _tag(c["text"], [c["id"]])})
    for i, t in enumerate(POSITIONING):
        out.append({"id": f"S-pos-{i}", "label": "positioning", "text": t})
    skipped = []
    for g in (golden or {}).get("sentences", []):
        ids = []
        for key in ("support_quote", "support_quote_2"):
            q = g.get(key)
            if q:
                c = _claim_for_quote(claims, q)
                if not c:
                    break
                ids.append(c["id"])
        else:
            label = g["label"]
            if label == "positioning":
                out.append({"id": g["id"], "label": label, "text": g["text"]})
                continue
            if not ids:
                skipped.append({"id": g["id"], "why": "no support quote"})
                continue
            if label in ("true", "false", "overstated", "partial", "combined-conclusion"):
                if label == "true" and any(claims[i]["status"] != "verified" for i in ids):
                    label = "not-citable"
                out.append({"id": g["id"], "label": label, "text": _tag(g["text"], ids), "golden": True})
            elif label == "untagged":
                out.append({"id": g["id"], "label": label, "text": g["text"], "golden": True})
            continue
        skipped.append({"id": g["id"], "why": "support quote not found in registry"})
    rnd.shuffle(out)
    return out, skipped


def _claim_for_quote(claims, quote):
    q = norm_ws(quote).lower()
    best = None
    for c in claims.values():
        cq = norm_ws(c["quote"]).lower()
        if cq == q or q in cq or (cq in q and len(cq) > 0.6 * len(q)):
            if best is None or (best["status"] != "verified" and c["status"] == "verified"):
                best = c
    return best


def seeds_to_page(seeds):
    lines = ["# Evaluation page", ""]
    for s in seeds:
        lines += [s["text"], ""]
    return "\n".join(lines)


def run_gate_eval(claims, product, conflicts, provider, golden=None, page_size=40, seed=7):
    seeds, skipped = build_seeds(claims, golden, seed=seed)
    verdicts_by_seed = {}
    hr = set(product["high_risk_categories"])
    tokens = 0
    for start in range(0, len(seeds), page_size):
        page = seeds[start:start + page_size]
        md = seeds_to_page(page)
        units = gate.parse_draft(md)
        box = Toolbox(claims=claims)
        payload = {"draft_hash": gate.draft_hash(md), "units": [{k: u[k] for k in ("index", "section", "kind", "text")} for u in units],
                   "claims": [claims[i] for i in sorted({i for s in page for i in re.findall(r"\[\[([A-Z0-9]+-\d+)\]\]", s["text"])}) if i in claims],
                   "high_risk_categories": sorted(hr), "conflicts": conflicts}
        out, usage = run_agent("verifier", payload, box, provider, product)
        tokens += usage.total
        final = gate.enforce(units, out, claims, hr)
        by_text = {}
        for v in final:
            by_text.setdefault(norm_ws(strip_tags(v["text"])).lower(), []).append(v)
        page_blocked = {i for pc in out.get("page_checks", []) if pc["verdict"] == "block" for i in pc["sentence_indexes"]}
        for s in page:
            # a seed may split into several units; it is blocked if any unit is blocked
            from packages.util import split_sentences
            parts = [norm_ws(strip_tags(x)).lower() for x in split_sentences(s["text"])]
            vs = [v for p in parts for v in by_text.get(p, [])]
            blocked = any(v["verdict"] == "block" or v["index"] in page_blocked for v in vs)
            verdicts_by_seed[s["id"]] = {"blocked": blocked, "reasons": [v["reason"] for v in vs if v["reason"]]}
    return score(seeds, verdicts_by_seed, skipped, tokens)


def score(seeds, verdicts, skipped, tokens=0):
    by = {}
    for s in seeds:
        by.setdefault(s["label"], []).append((s, verdicts[s["id"]]["blocked"]))
    def rate(labels):
        xs = [b for l in labels for _, b in by.get(l, [])]
        return (round(sum(xs) / len(xs), 4) if xs else None), len(xs)
    hall, nh = rate(HALLUCINATION)
    fb, nf = rate(SHOULD_PASS)
    un, nu = rate(("untagged",))
    metrics = {"hallucination_catch_rate": hall, "false_block_rate": fb, "untagged_detection_rate": un}
    passed = {}
    for k, (op, t) in TARGETS.items():
        v = metrics[k]
        passed[k] = v is not None and (v >= t if op == ">=" else v <= t)
    per_label = {l: {"n": len(xs), "blocked": sum(b for _, b in xs)} for l, xs in sorted(by.items())}
    misses = [{"id": s["id"], "label": s["label"], "text": s["text"], "blocked": b, "reasons": verdicts[s["id"]]["reasons"]}
              for l, xs in by.items() for s, b in xs if (l in SHOULD_PASS) == b]
    return {"metrics": metrics, "counts": {"hallucination": nh, "should_pass": nf, "untagged": nu}, "per_label": per_label,
            "targets": {k: f"{op} {t}" for k, (op, t) in TARGETS.items()}, "passed": passed, "all_passed": all(passed.values()),
            "skipped_golden": skipped, "misses": misses, "tokens": tokens, "computed_at": now_iso()}
