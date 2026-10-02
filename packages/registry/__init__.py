"""Claims registry: build from extractor records, permanent IDs, rulings, conflicts, review queue.

Everything here is deterministic. Agents never call these functions; the orchestrator
(build, conflicts) and the API (rulings) do.

Rules enforced (CLAUDE.md §2, §4):
- IDs are permanent: matched by (source_id, quote hash), then by quote hash alone; never renumbered or reused.
- A claim missing from a rebuilt source becomes `deprecated`, never deleted.
- High-risk categories and low-confidence claims enter as `needs-review`.
- Stored rulings are re-applied on every build. `confirmed` applies only while the quote hash
  still matches (the doc changed, so a human must look again). `rejected` and `doc-wrong` always hold.
"""
import re
from collections import defaultdict

from packages.util import STOPWORDS, new_id, now_iso, quote_hash, tokens

DEFAULT_HIGH_RISK = ["compliance", "metric", "pricing", "competitive", "customer-reference", "market-evidence"]
ID_NUM_RE = re.compile(r"-(\d+)$")


def _num(claim_id):
    m = ID_NUM_RE.search(claim_id)
    return int(m.group(1)) if m else 0


def allocate_ids(prefix, existing_ids, n):
    start = max([_num(i) for i in existing_ids] + [0]) + 1
    return [f"{prefix}-{start + k:03d}" for k in range(n)]


def base_status(category, confidence, high_risk):
    return "needs-review" if (category in high_risk or confidence == "low") else "verified"


# ---------------- rulings ----------------

def rulings_by_target(rulings):
    out = defaultdict(list)
    for r in sorted(rulings, key=lambda r: r["created_at"]):
        out[(r["target_kind"], r["target_id"])].append(r)
    return out


def apply_rulings(claim, claim_rulings, base, conflict_deprecations=None):
    """Return the claim with status/user_decision derived from base status + its ruling history."""
    status, decision, reason, deprioritized = base, None, "", False
    for r in claim_rulings:
        ud = {"kind": r["kind"], "note": r["note"], "author": r["author"], "at": r["created_at"], "ruling_id": r["id"]}
        if r["kind"] == "confirmed":
            if r.get("quote_hash") and r["quote_hash"] != claim["quote_hash"]:
                status, reason = "needs-review", "source quote changed since it was confirmed"
            else:
                status, reason = "verified", "confirmed by " + r["author"]
            decision = ud
        elif r["kind"] in ("rejected", "doc-wrong"):
            status, decision = "deprecated", ud
            reason = ("ruled doc-wrong by " if r["kind"] == "doc-wrong" else "rejected by ") + r["author"]
        elif r["kind"] == "deprioritized":
            deprioritized = True
            decision = ud if decision is None or decision["kind"] != "confirmed" else decision
    if conflict_deprecations and claim["id"] in conflict_deprecations and status != "deprecated":
        r = conflict_deprecations[claim["id"]]
        status, reason = "deprecated", f"conflict ruling {r['target_id']} by {r['author']}"
        decision = {"kind": "doc-wrong", "note": r["note"], "author": r["author"], "at": r["created_at"], "ruling_id": r["id"]}
    claim.update(status=status, user_decision=decision, deprioritized=deprioritized, status_reason=reason)
    return claim


def conflict_deprecations(conflicts, rulings):
    """Claim IDs deprecated by a conflict ruling that kept a different claim."""
    by_t = rulings_by_target(rulings)
    out = {}
    for c in conflicts:
        rs = by_t.get(("conflict", c["id"]), [])
        if not rs:
            continue
        r = rs[-1]
        if r.get("keep_claim_id"):
            for cid in c["claim_ids"]:
                if cid != r["keep_claim_id"]:
                    out[cid] = r
    return out


# ---------------- build ----------------

def build(product, existing, records, sources, rulings, conflicts=(), evidence=None):
    """Merge extractor records into the registry.

    product   product dict (claim_prefix, high_risk_categories)
    existing  {claim_id: claim} currently stored
    records   [{source_id, claims:[{text, quote, location, category, confidence}]}] for rebuilt truth sources
    sources   {source_id: source} all sources (to know which are active/removed)
    rulings   all rulings for the product
    evidence  optional [{source_id, claims:[{text, count, total, query, segment}]}] market evidence
    Returns (claims_by_id, stats).
    """
    now = now_iso()
    pid, prefix = product["id"], product["claim_prefix"]
    high_risk = set(product.get("high_risk_categories") or DEFAULT_HIGH_RISK)
    claims = {k: dict(v) for k, v in existing.items()}
    by_src_hash = {(c["source_id"], c["quote_hash"], c["text"]): c["id"] for c in claims.values()}
    by_hash = defaultdict(list)
    for c in claims.values():
        by_hash[c["quote_hash"]].append(c["id"])

    rebuilt = {r["source_id"] for r in records} | {r["source_id"] for r in (evidence or [])}
    seen, new = set(), []
    stats = defaultdict(int)

    def upsert(src_id, x, category, confidence, count=None):
        qh = quote_hash(x["quote"])
        cid = by_src_hash.get((src_id, qh, x["text"]))
        if cid is None:
            cid = next((i for i in by_hash.get(qh, []) if i not in seen and claims[i]["text"] == x["text"]), None)
        if cid is None:
            new.append((src_id, x, category, confidence, qh, count))
            return
        seen.add(cid)
        c = claims[cid]
        c.update(text=x["text"], quote=x["quote"], quote_hash=qh, source_id=src_id, location=x["location"],
                 category=category, confidence=confidence, updated_at=now, count=count)

    for rec in records:
        for x in rec["claims"]:
            upsert(rec["source_id"], x, x["category"], x["confidence"])
    for rec in evidence or []:
        for x in rec["claims"]:
            ex = {"text": x["text"], "quote": f"{x['count']} of {x['total']} responses match: {x['query']}",
                  "location": f"query: {x['query']}"}
            upsert(rec["source_id"], ex, "market-evidence", "medium", count=x["count"])

    ids = allocate_ids(prefix, list(claims), len(new))
    for cid, (src_id, x, category, confidence, qh, count) in zip(ids, new):
        claims[cid] = {"id": cid, "product_id": pid, "text": x["text"], "quote": x["quote"], "quote_hash": qh,
                       "source_id": src_id, "location": x["location"], "category": category, "confidence": confidence,
                       "status": "needs-review", "user_decision": None, "deprioritized": False, "status_reason": "",
                       "count": count, "created_at": now, "updated_at": now}
        seen.add(cid)
        stats["new"] += 1

    by_t = rulings_by_target(rulings)
    conf_dep = conflict_deprecations(conflicts, rulings)
    for cid, c in claims.items():
        src = sources.get(c["source_id"])
        gone = (c["source_id"] in rebuilt and cid not in seen) or (src is not None and src["status"] == "removed")
        if gone:
            c.update(status="deprecated", status_reason="no longer present in its source", updated_at=now)
            # rulings still recorded; a deprecated-for-absence claim stays deprecated
            stats["deprecated_missing"] += 1
            continue
        if c["category"] == "market-evidence":
            base = "needs-review"
        else:
            base = base_status(c["category"], c["confidence"], high_risk)
        apply_rulings(c, by_t.get(("claim", cid), []), base, conf_dep)

    for c in claims.values():
        stats[c["status"]] += 1
    stats["total"] = len(claims)
    return claims, dict(stats)


# ---------------- conflicts ----------------

STATUS_WORDS = {"beta": "beta", "preview": "beta", "early access": "beta", "experimental": "beta",
                "generally available": "ga", "general availability": "ga", "deprecated": "deprecated",
                "end of life": "deprecated", "retired": "deprecated"}
ABSOLUTE_RE = re.compile(r"\b(no \w+(?: \w+)? (?:can|may|will|is)|never|cannot|can't|can not|always|impossible|without exception|nothing)\b", re.I)
EXCEPTION_RE = re.compile(r"\b(except(?:ion)?|outside (?:the|of)|bypass\w*|override\w*|break-glass|circumvent\w*|"
                          r"without (?:the |a )?(?:approval|review|second))\b", re.I)
NEG_RE = re.compile(r"\b(not|no|never|cannot|can't|doesn't|does not|isn't|unsupported|unavailable)\b", re.I)
NUM_RE = re.compile(r"\d+(?:\.\d+)?")
GENERIC = {"product", "feature", "features", "support", "supports", "supported", "customers", "customer", "data", "use",
           "using", "available", "page", "explains", "describes"}
STATUS_TOKENS = {"beta", "preview", "generally", "available", "ga", "general", "availability", "deprecated", "early",
                 "access", "experimental", "now", "released", "release"}


def _stem(w):
    for suf in ("ations", "ation", "ings", "ing", "ies", "es", "ed", "ly", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def _stems(text, common=frozenset()):
    return {_stem(t) for t in tokens(text) if len(t) > 2 and t not in GENERIC and not NUM_RE.fullmatch(t)} - common


def _jaccard(a, b):
    return len(a & b) / max(1, len(a | b))


def _status_of(text):
    low = text.lower()
    return {v for k, v in STATUS_WORDS.items() if re.search(r"\b" + re.escape(k) + r"\b", low)}


def _num_nouns(text):
    """(number, stem of the next content word) pairs: '64 wireless sensors' -> {('64','wireless'), ('64','sensor')}."""
    out = set()
    words = re.findall(r"[A-Za-z]+|\d+(?:\.\d+)?", text)
    for i, w in enumerate(words):
        if NUM_RE.fullmatch(w):
            for nxt in words[i + 1:i + 4]:
                if not NUM_RE.fullmatch(nxt) and nxt.lower() not in STOPWORDS:
                    out.add((w, _stem(nxt.lower())))
    return out


SUBJECT_END_RE = re.compile(r"\b(is|are|was|were|has|have|had|can|cannot|can't|will|does|do|must|may|lets?|"
                            r"supports?|pairs?|includes?|requires?|provides?|offers?|stores?|keeps?|sends?|records?|"
                            r"retains?|uses?|runs?|shows?|marks?|applies|apply|connects?|accepts?|reconciles?|matches?|"
                            r"returns?|ships?|deletes?|holds?|resumes?|installs?|predicts?|measures?|reaches?)\b", re.I)


def _subject(text):
    m = SUBJECT_END_RE.search(text)
    head = text[: m.start()] if m and m.start() > 0 else " ".join(text.split()[:3])
    return {_stem(t) for t in tokens(head) if len(t) > 1}


def _same_subject(a, b):
    sa, sb = _subject(a), _subject(b)
    return bool(sa) and bool(sb) and _jaccard(sa, sb) >= 0.75


QUALIFIER_RE = re.compile(r"\b(?:on|in|for) the (\w+) (?:plan|edition|tier|region)\b", re.I)


def _different_scope(a, b):
    """Statements scoped to different plans/regions/editions don't contradict each other."""
    qa = {m.lower() for m in QUALIFIER_RE.findall(a)}
    qb = {m.lower() for m in QUALIFIER_RE.findall(b)}
    return bool(qa and qb and qa != qb)


def detect_conflicts(claims, sources, existing_conflicts=()):
    """Deterministic conflict candidates between active claims. Existing conflicts are kept by claim set.

    - living-vs-changelog / contradiction: same subject, different release status
    - contradiction: different numbers for the same counted thing, or opposite polarity on near-identical statements
    - absolute-vs-exception: an absolute ("no X can", "never") and a documented exception path ("outside the", "bypass")
    Tokens that appear in more than a fifth of all claims (product names, the core noun) don't count as shared subject.
    """
    now = now_iso()
    active = [c for c in claims.values() if c["status"] != "deprecated" and c["category"] != "market-evidence"]
    if not active:
        return list(existing_conflicts)
    df = defaultdict(int)
    for c in active:
        for t in _stems(c["text"]):
            df[t] += 1
    common = frozenset(t for t, n in df.items() if n > max(4, len(active) // 5))
    sal = {c["id"]: _stems(c["text"], common) for c in active}
    nn = {c["id"]: _num_nouns(c["text"]) for c in active}
    found = {}

    def src(c):
        return sources.get(c["source_id"], {})

    def newest_living(a, b):
        cands = [(x, src(x)) for x in (a, b) if src(x).get("kind") == "living"] or [(a, src(a)), (b, src(b))]
        cands.sort(key=lambda xs: (xs[1].get("updated") or "", xs[1].get("fetched_at") or ""), reverse=True)
        return cands[0][0]["id"]

    for i, a in enumerate(active):
        for b in active[i + 1:]:
            if a["text"] == b["text"]:
                continue  # the same statement in two places is corroboration, not conflict
            ta, tb = sal[a["id"]], sal[b["id"]]
            shared = ta & tb
            if len(shared) < 1:
                continue
            key = tuple(sorted((a["id"], b["id"])))
            kinds = {src(a).get("kind"), src(b).get("kind")}
            sa, sb = _status_of(a["text"]), _status_of(b["text"])
            if sa and sb and sa != sb and len((ta - STATUS_TOKENS) & (tb - STATUS_TOKENS)) >= 1 and \
                    _jaccard(ta - STATUS_TOKENS, tb - STATUS_TOKENS) >= 0.25:
                kind = "living-vs-changelog" if kinds == {"living", "changelog"} else "contradiction"
                found[key] = (kind, f"Release status differs: {sorted(sa)} vs {sorted(sb)}.", newest_living(a, b),
                              "Interim default: newest living page over an older changelog." if kind == "living-vs-changelog"
                              else "Interim default: newest living page.")
                continue
            # same counted thing, different number
            na, nb = nn[a["id"]], nn[b["id"]]
            nouns_a = {w for _, w in na if w not in common}
            nouns_b = {w for _, w in nb if w not in common}
            if nouns_a & nouns_b and len(shared) >= 2 and _same_subject(a["text"], b["text"]) and _jaccard(ta, tb) >= 0.4 \
                    and not _different_scope(a["text"], b["text"]):
                same = nouns_a & nouns_b
                va = {n for n, w in na if w in same}
                vb = {n for n, w in nb if w in same}
                if va and vb and not (va & vb):
                    found[key] = ("contradiction", f"Different numbers for the same thing: {sorted(va)} vs {sorted(vb)} "
                                  f"({', '.join(sorted(same))}).", newest_living(a, b), "Interim default: newest living page.")
                    continue
            for x, y in ((a, b), (b, a)):
                if ABSOLUTE_RE.search(x["text"]) and EXCEPTION_RE.search(y["text"]) and not ABSOLUTE_RE.search(y["text"]) \
                        and len(sal[x["id"]] & sal[y["id"]]) >= 3:
                    found[key] = ("absolute-vs-exception",
                                  f"{x['id']} states an absolute; {y['id']} documents an exception path.", None,
                                  "No interim default: scope the absolute claim or rule on it.")
                    break
            if key in found:
                continue
            if _jaccard(ta, tb) >= 0.6 and _same_subject(a["text"], b["text"]) and \
                    bool(NEG_RE.search(a["text"])) != bool(NEG_RE.search(b["text"])):
                found[key] = ("contradiction", "One statement negates the other.", newest_living(a, b),
                              "Interim default: newest living page.")

    by_key = {tuple(sorted(c["claim_ids"])): c for c in existing_conflicts}
    out = []
    for key, (kind, expl, default, label) in found.items():
        if key in by_key:
            out.append(by_key.pop(key))
            continue
        out.append({"id": new_id("conf"), "product_id": active[0]["product_id"], "claim_ids": list(key), "kind": kind,
                    "explanation": expl, "interim_default": default, "interim_label": label, "status": "open",
                    "created_at": now})
    out.extend(by_key.values())  # never drop a conflict that has history
    return out


# ---------------- review queue, corrections ----------------

def review_queue(claims, sources=None):
    """needs-review claims grouped by category, then by heading theme (first heading in location)."""
    groups = defaultdict(list)
    for c in claims.values():
        if c["status"] != "needs-review":
            continue
        theme = c["location"].split(">")[0].split("¶")[0].strip() or "General"
        groups[(c["category"], theme)].append(c)
    out = []
    for (cat, theme), items in sorted(groups.items()):
        out.append({"category": cat, "theme": theme, "claims": sorted(items, key=lambda c: _num(c["id"])),
                    "bulk_allowed": cat not in DEFAULT_HIGH_RISK})
    return out


def correction_notes(claims, rulings, sources):
    """Doc corrections for the docs owner: every doc-wrong ruling and conflict ruling, with the reviewer's words."""
    notes = []
    for r in sorted(rulings, key=lambda r: r["created_at"]):
        if r["kind"] == "doc-wrong" and r["target_kind"] == "claim" and r["target_id"] in claims:
            c = claims[r["target_id"]]
            s = sources.get(c["source_id"], {})
            notes.append({"claim_id": c["id"], "source": s.get("title") or c["source_id"],
                          "url": s.get("origin", {}).get("value"), "location": c["location"], "doc_says": c["quote"],
                          "ruling": r["note"], "by": r["author"], "at": r["created_at"]})
    return notes


# ---------------- decisions -> guardrails ----------------

_Q = r"['\"‘’“”]"


def _quoted(s):
    return [m.group(1) or m.group(2) for m in re.finditer(rf"{_Q}([^'\"‘’“”]+){_Q}|\b(?:call it|use)\s+([A-Z][\w-]*(?:\s+[A-Z][\w-]*)*)", s)]


def derive_guardrails(decision):
    """Literal guardrails from one verbatim decision. Each rule stays within the decision's words:
    a rule about one topic never restricts another. Unrecognized wording becomes an 'other'
    guardrail that quotes the decision itself."""
    did, text = decision["id"], decision["text"].strip()
    out = []
    for sent in [s.strip() for s in re.split(r"(?<=[.!])\s+", text) if s.strip()]:
        low = sent.lower()
        m = re.match(rf"(?i)(?:never|do not|don't) use (?:the )?(?:word|term|phrase)s?\s+(.+?)(?: in [\w\s-]+)?\.?$", sent)
        if m:
            terms = [t for t in re.findall(rf"{_Q}([^'\"‘’“”]+){_Q}", m.group(1))] or \
                [t.strip(" .") for t in re.split(r",\s*|\s+or\s+|\s+and\s+", m.group(1)) if t.strip(" .")]
            out.append({"rule": f"Do not use {', '.join(repr(t) for t in terms)} in copy.", "type": "banned-term",
                        "terms": terms, "decision_id": did})
            continue
        m = re.match(r"(?i)always call it\s+(.+?),\s*never\s+(.+?)\.?$", sent)
        if m:
            keep = m.group(1).strip(" '\"")
            drop = re.findall(rf"{_Q}([^'\"‘’“”]+){_Q}", m.group(2)) or [x.strip(" .") for x in re.split(r",| or ", m.group(2)) if x.strip()]
            drop = [re.sub(r"(?i)^(just|only)\s+", "", d).strip() for d in drop]
            out.append({"rule": f"Name the product '{keep}'; never {', '.join(repr(d) for d in drop)}.", "type": "naming",
                        "terms": [keep] + drop, "decision_id": did})
            continue
        m = re.match(r"(?i)deprioriti[sz]e\s+(?:the\s+)?(.+?)(?:\s+(?:deployment|option|model|feature))?(?:\s+in copy)?\.?$", sent)
        if m:
            topic = m.group(1).strip(" .")
            out.append({"rule": f"Do not feature {topic} in copy. Claims about other topics are not affected.",
                        "type": "deprioritize", "terms": [topic], "decision_id": did})
            continue
        if low.startswith("lead with"):
            out.append({"rule": sent.rstrip(".") + ".", "type": "emphasis", "terms": [], "decision_id": did})
            continue
        out.append({"rule": sent.rstrip(".") + ".", "type": "other", "terms": [], "decision_id": did})
    return out


def guardrail_diff(old, new):
    o = {g["rule"] for g in old}
    n = {g["rule"] for g in new}
    return {"added": sorted(n - o), "removed": sorted(o - n)}
