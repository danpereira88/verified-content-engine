"""Deterministic offline baseline for every agent role.

These implementations need no model and no network. They exist so the whole pipeline can run in
tests, on fixtures and in air-gapped demos, and so the gate eval has a reproducible baseline.
They are deliberately conservative (the verifier blocks when unsure). They are not the release
gate: a model-backed verifier must pass the gate eval before it ships (CLAUDE.md §7).
Nothing here is product-specific: every name and term comes from the payload.
"""
import re
from collections import Counter

from packages.textstats import heading_case, headings, measure
from packages.util import TAG_RE, name_re, norm_ws, now_iso, split_sentences, strip_tags, tags_in, tokens, word_count


def run(role, payload, box):
    fn = {"claims-extractor": claims_extractor, "style-extractor": style_extractor,
          "positioning-extractor": positioning_extractor, "evidence-extractor": evidence_extractor,
          "strategist": strategist, "copywriter": copywriter, "verifier": verifier,
          "style-checker": style_checker, "best-practice-auditor": best_practice_auditor,
          "synthetic-buyer": synthetic_buyer}[role]
    return fn(payload, box)


def stem(w):
    for suf in ("ations", "ation", "ingly", "ings", "ing", "edly", "ies", "ied", "es", "ed", "ly", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def stems(text):
    return {stem(t) for t in tokens(text) if len(t) > 1}


NUM_RE = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)*(?:\s?%|\s?(?:ms|s|x|gb|tb|mb|k|m))?", re.I)


def numbers(text):
    return {re.sub(r"\s", "", m.group(0)).lower().rstrip(".,") for m in NUM_RE.finditer(strip_tags(text))}


# ---------------- claims-extractor ----------------

CATEGORY_RULES = [
    ("compliance", r"\b(soc ?2|iso ?27001|iso/iec|gdpr|hipaa|pci|fedramp|certif\w*|complian\w*|audit\w*|regulat\w*|data residency|resides? in|attest\w*)\b"),
    ("pricing", r"(\$\d|\bpric\w*|\bcost\w*\b|\bfee\b|\bfees\b|\bper (?:seat|user|month)\b|\bfree tier\b|\bbilling\b)"),
    ("competitive", r"\b(than|compared|unlike|competitor\w*|alternative\w*|versus|vs\.?)\b"),
    ("customer-reference", r"\b(customers? (?:such as|including|like)|used by|trusted by|case study)\b"),
    ("metric", r"(\d+(?:\.\d+)?\s?(?:%|ms|milliseconds?|seconds?|minutes?|hours?|days?)|\buptime\b|\bsla\b|\baccura\w*\b|\blatency\b|\bthroughput\b)"),
    ("security", r"\b(encrypt\w*|tls|aes|key[s]?\b|authenticat\w*|sso|saml|mfa|2fa|access control\w*|role-based|rbac|permission\w*|audit log\w*|tamper\w*)\b"),
    ("integration", r"\b(integrat\w*|api\b|apis\b|webhook\w*|sdk\w*|connector\w*|export\w* to|import\w* from|sync\w* with)\b"),
    ("deployment", r"\b(deploy\w*|on-prem\w*|self-host\w*|cloud|install\w*|region\w*|hosted)\b"),
    ("availability", r"\b(beta|preview|generally available|general availability|early access|available on|plan\b|plans\b|edition)\b"),
    ("limitation", r"\b(cannot|can't|not supported|unsupported|limit\w*|maximum|at most|up to|only)\b"),
]
HEDGE_RE = re.compile(r"\b(typically|usually|may|might|approximately|about|around|up to|can vary|in most cases)\b", re.I)
LOW_RE = re.compile(r"\b(planned|roadmap|coming soon|will be|expected to|in a future release|tbd)\b", re.I)
SKIP_RE = re.compile(r"^(note|tip|see|learn more|for example|click|go to|select|open|navigate)\b", re.I)


def categorize(text):
    low = text.lower()
    for cat, pat in CATEGORY_RULES:
        if re.search(pat, low):
            return cat
    return "capability"


def claims_extractor(p, box):
    claims, seen = [], set()
    for b in p["blocks"]:
        if b["heading_path"] and b["text"] == b["heading_path"][-1]:
            continue  # a heading, not a statement
        for s in split_sentences(b["text"]):
            s = s.strip()
            words = s.split()
            if len(words) < 5 or s.endswith("?") or SKIP_RE.match(s) or not re.search(r"[a-z]", s):
                continue
            quote = " ".join(words[:59]) if len(words) >= 60 else s
            if quote in seen:
                continue
            seen.add(quote)
            conf = "low" if LOW_RE.search(s) else "medium" if HEDGE_RE.search(s) else "high"
            claims.append({"text": s, "quote": quote, "location": b["loc"], "category": categorize(s), "confidence": conf})
    return {"source_id": p["source_id"], "claims": claims, "summary": f"{len(claims)} claims from {p['source']['title']}"}


# ---------------- style-extractor ----------------

HYPE = ["revolutionary", "game-changing", "cutting-edge", "best-in-class", "world-class", "seamless", "synergy",
        "leverage", "unparalleled", "disruptive", "next-generation", "robust"]


def style_extractor(p, box):
    texts = ["\n".join(("# " + b["text"]) if b["heading_path"] and b["text"] == b["heading_path"][-1] else b["text"]
                       for b in s["blocks"]) for s in p["sources"]]
    m = p["measured"]
    name = p["product"]["name"]
    corpus = " ".join(texts)
    banned, forbidden, derived = [], [], []
    for d in p["decisions"]:
        for g in d["derived_guardrails"]:
            if g["type"] == "banned-term":
                banned += g["terms"]
                derived.append({"decision_id": d["id"], "rule": g["rule"]})
            elif g["type"] == "naming":
                forbidden += g["terms"][1:]
                derived.append({"decision_id": d["id"], "rule": g["rule"]})
    words = [w for w in tokens(corpus) if len(w) > 3 and not w.isdigit()]
    name_toks = set(tokens(name))
    common = [w for w, c in Counter(words).most_common(60) if c >= 3 and w not in name_toks and w not in banned][:20]
    # naming: capitalised phrases that contain a word of the product name
    first = re.escape(name.split()[0])
    variants = Counter(m_.group(0).strip() for m_ in re.finditer(rf"\b(?:[A-Z][\w-]*\s)?{first}(?:\s[A-Z][\w-]*)?", corpus))
    variants_allowed = [v for v, c in variants.items() if v != name and c >= 2 and v not in forbidden
                        and not v.lower().startswith(("the ", "a ", "your ", "our "))][:5]
    issues = []
    for f in forbidden:
        if name_re(f).search(corpus):
            issues.append(f"Corpus uses the forbidden name '{f}'; copy must use '{name}'.")
    found_banned = [t for t in banned if re.search(rf"\b{re.escape(t)}\b", corpus, re.I)]
    if found_banned:
        issues.append(f"Corpus uses banned terms {found_banned}; the profile bans them for new copy.")
    # Corpus issues are reported, but only profile-internal contradictions make the profile inconsistent.
    profile_issues = [i for i in [] ]
    voice_traits = []
    voice_traits.append("Second person: talks to the reader as 'you'." if m["second_person_rate"] > 0.25 else "Mostly third person.")
    voice_traits.append(f"Short sentences (about {m['avg_sentence_words']:.0f} words)." if m["avg_sentence_words"] < 15
                        else f"Medium-to-long sentences (about {m['avg_sentence_words']:.0f} words).")
    if m["question_rate"] > 0.05:
        voice_traits.append("Uses questions to engage the reader.")
    if m["exclamation_rate"] < 0.01:
        voice_traits.append("No exclamation marks.")
    voice_traits.append(f"{'Sentence' if m['heading_case'] == 'sentence' else 'Title'}-case headings.")
    return {
        "product_id": p["product_id"], "status": "active" if not profile_issues else "draft", "generated_at": p["generated_at"],
        "voice": {"summary": " ".join(voice_traits), "traits": voice_traits},
        "cadence": {k: m[k] for k in ("avg_sentence_words", "sentence_words_p10", "sentence_words_p90",
                                      "avg_paragraph_sentences", "question_rate", "second_person_rate")},
        "vocabulary": {"preferred": common, "avoid": [h for h in HYPE if h not in corpus.lower()], "banned": sorted(set(banned))},
        "naming": {"product_name": name, "variants_allowed": variants_allowed, "forbidden": sorted(set(forbidden))},
        "formatting": {"heading_case": m["heading_case"],
                       "list_style": "frequent short bullet lists" if m["list_line_rate"] > 0.15 else "mostly prose",
                       "notes": issues},
        "rubric": [{"criterion": "voice", "weight": 0.25, "description": "Person, tone and sentence mood match the corpus."},
                   {"criterion": "cadence", "weight": 0.25, "description": "Sentence length within the corpus range."},
                   {"criterion": "vocabulary", "weight": 0.2, "description": "Uses the team's words; no hype or banned terms."},
                   {"criterion": "naming", "weight": 0.2, "description": "Product named as the profile says."},
                   {"criterion": "formatting", "weight": 0.1, "description": "Heading case and list habits match."}],
        "threshold": None,
        "consistency": {"ok": not profile_issues, "issues": profile_issues},
        "corpus": p["corpus"], "derived_from_decisions": derived,
    }


# ---------------- positioning-extractor ----------------

def _sections(blocks):
    """Group blocks by their level-2 heading (the deck format), keeping level-3 subgroups."""
    out = {}
    for b in blocks:
        hp = b["heading_path"]
        if len(hp) < 2 or b["text"] == hp[-1]:
            continue
        out.setdefault(hp[1].lower(), []).append(b)
    return out


def _link(box, text):
    hits = box.search_registry(text, limit=3)
    st = stems(text)
    for h in hits:
        ht = stems(h["text"])
        if len(st & ht) / max(1, len(st)) >= 0.6:
            return [h["id"]]
    return []


def positioning_extractor(p, box):
    pack = {"product_id": p["product_id"], "generated_at": p["generated_at"], "positioning_statement": "", "category": "",
            "alternatives": [], "value_themes": [], "personas": [], "objections": [], "stages": {}, "messaging": {},
            "guardrails": []}
    for src in p["sources"]:
        if src.get("kind") == "brief":
            continue  # briefs are requests, never positioning truth
        secs = _sections(src["blocks"])
        for b in secs.get("positioning statement", [])[:1]:
            pack["positioning_statement"] = b["text"]
        for b in secs.get("category", [])[:1]:
            pack["category"] = b["text"]
        for b in secs.get("competitive alternatives", []):
            name, _, notes = b["text"].partition(":")
            pack["alternatives"].append({"name": name.strip(), "notes": notes.strip()})
        themes = {}
        for b in secs.get("value themes", []):
            if len(b["heading_path"]) < 3:
                continue
            t = themes.setdefault(b["heading_path"][2], {"name": b["heading_path"][2], "message": "", "proof_points": []})
            m = re.match(r"(?i)proof:\s*(.*)", b["text"])
            if m:
                ids = _link(box, m.group(1))
                t["proof_points"].append({"text": m.group(1).strip(), "status": "has-claim" if ids else "needs-claim", "claim_ids": ids})
            elif not t["message"]:
                t["message"] = b["text"]
        pack["value_themes"] += list(themes.values())
        personas = {}
        for b in secs.get("personas", []):
            if len(b["heading_path"]) < 3:
                continue
            per = personas.setdefault(b["heading_path"][2], {"name": b["heading_path"][2], "role": "", "pains": [], "goals": [],
                                                             "stage": "problem-aware"})
            k, _, v = b["text"].partition(":")
            k = k.strip().lower()
            if k == "role":
                per["role"] = v.strip()
            elif k in ("pains", "goals"):
                per[k] = [x.strip() for x in v.split(";") if x.strip()]
            elif k == "stage" and v.strip() in ("unaware", "problem-aware", "solution-aware", "product-aware", "most-aware"):
                per["stage"] = v.strip()
        pack["personas"] += list(personas.values())
        for b in secs.get("objections", []):
            o, _, r = b["text"].partition("=>")
            pack["objections"].append({"text": o.strip(), "response": r.strip()})
        for b in secs.get("awareness stages", []):
            k, _, v = b["text"].partition(":")
            pack["stages"][k.strip().lower()] = v.strip()
        for b in secs.get("messaging", []):
            k, _, v = b["text"].partition(":")
            pack["messaging"][k.strip().lower()] = v.strip()
        if not pack["positioning_statement"]:
            body = [b["text"] for b in src["blocks"] if not (b["heading_path"] and b["text"] == b["heading_path"][-1])]
            pack["positioning_statement"] = body[0] if body else ""
    for d in p["decisions"]:
        for g in d["derived_guardrails"]:
            pack["guardrails"].append({"rule": g["rule"], "decision_id": d["id"], "decision_quote": d["text"]})
    return pack


# ---------------- evidence-extractor ----------------

def evidence_extractor(p, box):
    rows = []
    for b in p["blocks"]:
        fields = {}
        for part in b["text"].split(" | "):
            k, _, v = part.partition(":")
            fields[k.strip()] = v.strip()
        rows.append(fields)
    total = len(rows)
    claims = []
    for field in sorted({k for r in rows for k in r}):
        if field in ("quote", "id"):
            continue
        vals = Counter(r[field].lower() for r in rows if r.get(field) and len(r[field].split()) <= 8)
        for v, c in vals.most_common(5):
            if c >= 3:
                claims.append({"text": f"{c} of {total} respondents gave '{v}' for {field.replace('_', ' ')}.",
                               "count": c, "total": total, "query": f"{field}={v}", "segment": None})
    phrases = Counter()
    for r in rows:
        ws = [w for w in re.findall(r"[a-z][a-z'-]+", (r.get("quote") or "").lower())]
        for n in (3, 4):
            for i in range(len(ws) - n + 1):
                gram = ws[i:i + n]
                if gram[0] in ("the", "a", "and", "to", "of") or gram[-1] in ("the", "a", "and", "to", "of"):
                    continue
                phrases[" ".join(gram)] += 1
    lang = [{"phrase": ph, "count": c} for ph, c in phrases.most_common(15) if c >= 3]
    return {"source_id": p["source_id"], "claims": claims, "buyer_language": lang}


# ---------------- strategist ----------------

FRAMEWORK = {"unaware": "PAS", "problem-aware": "PAS", "solution-aware": "BAB", "product-aware": "AIDA", "most-aware": "AIDA"}


def _avoid_terms(guardrails):
    terms = []
    for g in guardrails:
        if g["type"] in ("banned-term", "deprioritize"):
            terms += g["terms"]
        elif g["type"] == "naming":
            terms += g["terms"][1:]
    return [t.lower() for t in terms if t]


def strategist(p, box):
    brief, ct, pack = p["brief"], p["content_type"], p.get("pack") or {}
    avoid = _avoid_terms(p["guardrails"])
    personas = pack.get("personas") or []
    aud = set(tokens(brief["audience"] + " " + brief.get("notes", "")))
    persona = max(personas, key=lambda x: len(aud & set(tokens(x["name"] + " " + x["role"]))), default=None)
    used, used_text, sections = set(), set(), []
    claims = {c["id"]: c for c in p["claims"]}
    proof_ids = [cid for t in pack.get("value_themes", []) for pp in t["proof_points"] for cid in pp["claim_ids"]]
    theme_text = " ".join(t["name"] + " " + t["message"] for t in pack.get("value_themes", []))
    for s in ct["sections"]:
        want = {"hero": 1, "headline": 1, "subject": 0, "title": 1, "cta": 0, "ask": 0, "problem": 1, "opening": 1}.get(s["id"], 3)
        query = " ".join([s["name"], s["purpose"], brief["goal"], brief["title"], brief.get("notes", ""),
                          theme_text if s["id"] in ("benefits", "capabilities", "value", "body", "solution") else ""])
        picks = []
        if s["id"] in ("benefits", "capabilities", "proof", "value", "details"):
            picks += [cid for cid in proof_ids if cid in claims and cid not in used]
        picks += [h["id"] for h in box.search_registry(query, limit=25)]
        chosen = []
        if want == 0:
            picks = []
        for cid in picks:
            c = claims.get(cid) or box.claims.get(cid)
            if not c or cid in used or c["status"] != "verified" or c.get("deprioritized"):
                continue
            if norm_ws(c["text"]).lower() in used_text:
                continue
            if any(re.search(rf"\b{re.escape(t)}\b", c["text"].lower()) for t in avoid):
                continue
            if s["id"] == "proof" and c["category"] not in ("metric", "compliance", "security", "customer-reference"):
                continue
            chosen.append(cid)
            used.add(cid)
            used_text.add(norm_ws(c["text"]).lower())
            if len(chosen) >= want:
                break
        sections.append({"id": s["id"], "name": s["name"], "purpose": s["purpose"], "claim_ids": chosen,
                         "notes": "" if chosen or want == 0 else "No verified claim fits; keep this section to positioning."})
    gaps = [{"need": pp["text"], "reason": "Positioning proof point with no verified claim."}
            for t in pack.get("value_themes", []) for pp in t["proof_points"] if pp["status"] == "needs-claim"]
    for o in (p.get("persona_objections") or []):
        if not box.search_registry(o, limit=1):
            gaps.append({"need": o, "reason": "Buyer objection the verified claims can't answer."})
    for ask in re.split(r"(?<=[.;])\s+", brief.get("notes", "")):
        if ask.strip() and re.search(r"\b(certif|customer|logo|fastest|faster|only|first|guarantee|award|\d+%)", ask, re.I):
            hits = box.search_registry(ask, limit=1)
            if not hits or len(stems(ask) & stems(hits[0]["text"])) / max(1, len(stems(ask))) < 0.5:
                gaps.append({"need": ask.strip(), "reason": "The brief asks for this, but no verified claim supports it. A brief can't authorize a fact."})
    notes = [f"Mandated wording for {m['where'] or 'the page'} ('{m['text']}') goes through the gate like any other copy."
             for m in brief.get("mandated_wording", [])]
    return {"brief_id": p["brief_id"], "framework": FRAMEWORK[brief["stage"]],
            "angle": (pack.get("messaging") or {}).get("elevator pitch") or pack.get("positioning_statement", "")[:200],
            "persona": persona["name"] if persona else brief["audience"], "stage": brief["stage"], "sections": sections,
            "proof_gaps": gaps, "mandated_wording_notes": notes,
            "style_notes": ["Apply the style profile's naming and banned terms exactly."]}


# ---------------- copywriter ----------------

def _apply_naming(text, profile):
    if not profile:
        return text
    for f in sorted(profile["naming"]["forbidden"], key=len, reverse=True):
        text = name_re(f).sub(profile["naming"]["product_name"], text)
    return text


def _has_banned(text, profile):
    return bool(profile) and any(re.search(rf"\b{re.escape(t)}\b", text, re.I) for t in profile["vocabulary"]["banned"])


def _claim_sentence(c):
    t = c["text"].strip()
    return (t if t.endswith((".", "!", "?")) else t + ".") + f" [[{c['id']}]]"


CTA = {"cta": "Talk to our team to see it with your own setup.", "ask": "Would a 20-minute walkthrough next week be useful?",
       "availability": None, "conclusion": "Talk to our team to learn more."}


def copywriter(p, box):
    rev = p.get("revision")
    if rev:
        return _revise(p, box, rev)
    brief, plan, profile, pack = p["brief"], p["plan"], p.get("profile"), p.get("pack") or {}
    msg = pack.get("messaging") or {}
    claims = {c["id"]: c for c in p["claims"]}
    mandated = {m["where"].lower(): m["text"] for m in brief.get("mandated_wording", [])}
    lines, cmap = [], []
    themes = pack.get("value_themes") or []
    persona = next((x for x in pack.get("personas", []) if x["name"] == plan["persona"]), None)
    for i, s in enumerate(plan["sections"]):
        first = i == 0
        if first:
            h1 = mandated.get("h1") or mandated.get("headline") or msg.get("headline") or brief["title"]
            lines += [f"# {_apply_naming(h1, profile)}", ""]
            sub = msg.get("tagline")
            if sub:
                lines += [_apply_naming(sub, profile), ""]
        else:
            required = next((x["required"] for x in p["content_type"]["sections"] if x["id"] == s["id"]), True)
            if not s["claim_ids"] and not required:
                continue
            lines += [f"## {s['name']}", ""]
        if s["id"] in ("problem", "opening") and persona and persona["pains"]:
            pain = persona["pains"][0].rstrip(".")
            lines += [f"{pain[0].upper() + pain[1:]}. Sound familiar?", ""]
        elif not first and i - 1 < len(themes) and s["id"] in ("benefits", "solution", "value", "body", "capabilities"):
            t = themes[i - 1] if i - 1 < len(themes) else themes[0]
            if t["message"]:
                lines += [_apply_naming(t["message"], profile), ""]
        bullets = s["id"] in ("benefits", "capabilities", "details", "faq", "questions")
        for cid in s["claim_ids"]:
            c = claims.get(cid) or box.claims.get(cid)
            if not c or _has_banned(c["text"], profile):
                continue
            sent = _apply_naming(_claim_sentence(c), profile)
            lines.append(("- " if bullets else "") + sent)
            cmap.append({"sentence": sent, "claim_ids": [cid]})
        if s["claim_ids"]:
            lines.append("")
        if s["id"] in CTA and CTA[s["id"]]:
            lines += [CTA[s["id"]], ""]
    md = "\n".join(lines).strip() + "\n"
    return {"draft_md": md, "claim_map": cmap,
            "missing_claims": [{"need": g["need"], "section": ""} for g in plan.get("proof_gaps", [])],
            "writing_aid_flags": p.get("writing_aid_flags", [])}


def _revise(p, box, rev):
    md = rev["previous_draft"]
    instr = rev.get("instructions") or ""
    for a, b in re.findall(r'replace\s+"([^"]+)"\s+with\s+"([^"]+)"', instr, re.I):
        md = md.replace(a, b)
    for a in re.findall(r'remove\s+"([^"]+)"', instr, re.I):
        md = "\n".join(l for l in md.splitlines() if a not in l)
    flagged = {}
    for f in rev.get("flags", []):
        if f.get("sentence") and f["severity"] in ("block", "high"):
            flagged.setdefault(norm_ws(strip_tags(f["sentence"])).lower(), f)
    out = []
    for line in md.splitlines():
        m = re.match(r"^(\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)?)(.*)$", line)
        prefix, body = m.group(1), m.group(2)
        if not body.strip():
            out.append(line)
            continue
        kept = []
        for s in split_sentences(body):
            key = norm_ws(strip_tags(s)).lower()
            f = flagged.get(key) or next((v for k, v in flagged.items() if key and key in k), None)
            if not f:
                kept.append(s)
                continue
            fix = _fix_sentence(s, f, box)
            if fix:
                kept.append(fix)
        if kept:
            out.append(prefix + " ".join(kept))
        elif prefix.strip().startswith("#"):
            out.append(prefix + "Overview")
    md2 = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"
    cmap = [{"sentence": s, "claim_ids": tags_in(s)} for s in split_sentences(strip_tags(md2) and md2) if tags_in(s)]
    return {"draft_md": md2, "claim_map": cmap, "missing_claims": [], "writing_aid_flags": []}


def _fix_sentence(s, f, box):
    """Narrow a flagged sentence to its claim's own words, or drop it."""
    reason = f.get("reason") or ""
    ids = tags_in(s)
    if reason in ("overstated", "partial", "contradicted", "combined-conclusion") and len(ids) == 1:
        c = box.claims.get(ids[0])
        if c and c["status"] == "verified":
            return _claim_sentence(c)
    if reason == "untagged":
        hits = box.search_registry(strip_tags(s), limit=1)
        if hits and len(stems(s) & stems(hits[0]["text"])) / max(1, len(stems(s))) >= 0.8:
            return _claim_sentence(box.claims[hits[0]["id"]])
    return None


# ---------------- verifier (baseline gate) ----------------

SUPERLATIVE_RE = re.compile(
    r"\b(only|first|fastest|best|leading|unique|unmatched|unrivaled|guarantee[sd]?|always|never|all|every|any|"
    r"fully|completely|entirely|totally|unlimited|instant(?:ly)?|zero|100\s?%|most|no other|industry-leading|world-class|"
    r"perfect(?:ly)?|bulletproof|effortless(?:ly)?|anywhere|everywhere|everything|absolutely|certified|compliant|ever)\b", re.I)
CONDITION_RE = re.compile(
    r"\b(only (?:on|in|with|for|when)|on the \w+ (?:plan|edition|tier)|(?:plan|edition|tier)s?\b|"
    r"version \d[\w.]*|v\d[\w.]*|\d+(?:\.\d+)+ or later|or later|or above|or newer|beta|preview|early access|when |if |unless|"
    r"except|in (?:the )?(?:us|eu|uk)\b|regions?|self-hosted|on-prem\w*|cloud|or (?:a |an )?(?:software |hardware )?equivalent)", re.I)
FACT_VERB_RE = re.compile(
    r"\b(is|are|was|were|has|have|supports?|integrates?|encrypts?|stores?|offers?|includes?|provides?|runs?|requires?|"
    r"connects?|syncs?|works?|keeps?|lets?|allows?|enables?|delivers?|reduces?|cuts?|detects?|alerts?|records?|"
    r"protects?|meets?|complies|certified|compliant|available|guarantees?|ensures?|handles?|processes?|reconciles?|"
    r"matches?|exports?|imports?|sends?|logs?|retains?|lasts?|measures?|controls?|adjusts?|learns?|never|always|"
    r"can|cannot|can't|will|lose|loses|saves?|saving|means?)\b", re.I)
CTA_RE = re.compile(r"^(talk|book|get|start|see|try|request|contact|learn|join|sign up|schedule|download|read|ask|let's|would)\b", re.I)
QUANTIFIER_RE = re.compile(r"\b(every|all|never|always|zero|no more|nothing|100\s?%|guaranteed|anywhere|everywhere)\b", re.I)
NORMATIVE_RE = re.compile(r"\b(deserves?|worth|should|matters?|best defen[cs]e|built for|designed for|made for|imagine|"
                          r"peace of mind|confidence|calm(?:er)?|trust(?:s|ed)?)\b", re.I)
CONCLUDE_RE = re.compile(r"\b(so|therefore|which means|that means|this means|as a result|thus|meaning|so you can|so your)\b", re.I)
NEG_RE = re.compile(r"\b(not|no|never|cannot|can't|doesn't|does not|isn't|aren't|without|unsupported|unavailable)\b", re.I)
GENERIC_STEMS = {"product", "featur", "help", "team", "customer", "make", "us", "way", "get", "new", "one", "use", "work"}


def _vocab(box):
    v = getattr(box, "_vce_vocab", None)
    if v is None:
        from collections import Counter as _C
        df = _C(t for c in box.claims.values() for t in stems(c["text"]))
        n = max(1, len(box.claims))
        v = {t for t, k in df.items() if k >= 2 and k < max(5, n * 0.2)}
        box._vce_vocab = v
    return v


def _registry_overlap(box, text):
    st = stems(text) - GENERIC_STEMS
    if not st:
        return 0, 0.0
    hit = _best_claim(box, text)
    if not hit:
        return 0, 0.0
    shared = st & stems(hit["text"])
    return len(shared), len(shared) / len(st)


def _classify(u, box=None):
    text = strip_tags(u["text"]).strip()
    if not text:
        return "positioning"
    if text.endswith("?"):
        return "positioning"
    if CTA_RE.match(text) and not numbers(text):
        return "positioning"
    has_num = bool(numbers(text))
    absolute = bool(SUPERLATIVE_RE.search(text))
    verb = bool(FACT_VERB_RE.search(text))
    reg_n, reg_ratio = _registry_overlap(box, text) if box is not None else (0, 0.0)
    if reg_n >= 3 and reg_ratio >= 0.6 and not NORMATIVE_RE.search(text):
        return "positioning-hiding-fact" if u["kind"] == "heading" and not tags_in(u["text"]) else "factual"
    if u["kind"] == "heading" or len(text.split()) <= 7:
        if has_num or (absolute and verb) or QUANTIFIER_RE.search(text):
            return "positioning-hiding-fact"
        return "positioning" if not tags_in(u["text"]) else "factual"
    if has_num or tags_in(u["text"]):
        return "factual"
    if re.match(r"^(if|imagine|what if|picture|when)\b", text, re.I) and not absolute and not (box and _registry_overlap(box, text)[1] >= 0.6):
        return "positioning"
    if NORMATIVE_RE.search(text) and not has_num:
        return "positioning"
    if box is not None:
        n, ratio = _registry_overlap(box, text)
        if n >= 3 and ratio >= 0.5:
            return "factual"
        if n <= 1 and not absolute:
            return "positioning"
    return "factual" if verb else "positioning"


def _best_claim(box, text):
    hits = box.search_registry(strip_tags(text), limit=3, include_unverified=True)
    return hits[0] if hits else None


def verifier(p, box):
    units = p["units"]
    out, prev_tagged = [], None
    for u in units:
        text = strip_tags(u["text"]).strip()
        cls = _classify(u, box)
        ids = tags_in(u["text"])
        v = {"index": u["index"], "text": u["text"], "section": u["section"], "classification": cls, "cited_ids": ids,
             "relevant_ids": [], "verdict": "pass", "reason": None, "explanation": "", "suggested_fix": ""}
        if cls == "positioning":
            v["explanation"] = "No checkable fact."
            out.append(v)
            continue
        if not ids:
            best = _best_claim(box, text)
            v.update(verdict="block", reason="untagged",
                     explanation="Factual assertion with no claim ID." if cls == "factual"
                     else "Reads as a tagline but asserts something checkable.",
                     suggested_fix=(f"Tag with {best['id']} if it says exactly: \"{best['text']}\"" if best else "Remove or rephrase as positioning."))
            if best:
                v["relevant_ids"] = [best["id"]]
            out.append(v)
            continue
        cited = [box.claims.get(i) for i in ids]
        if any(c is None for c in cited):
            v.update(verdict="block", reason="missing-claim", explanation="A cited claim does not exist.", suggested_fix="Remove.")
            out.append(v)
            continue
        bad = next((c for c in cited if c["status"] != "verified"), None)
        if bad:
            v.update(verdict="block", reason="deprecated" if bad["status"] == "deprecated" else "needs-review",
                     explanation=f"{bad['id']} is {bad['status']}.", suggested_fix="Use a verified claim or remove.")
            out.append(v)
            continue
        ctext = " ".join(c["text"] for c in cited)
        v["relevant_ids"] = ids
        reason, why = _support(text, ctext, cited, box, _vocab(box))
        if reason:
            fix = cited[0]["text"] if len(cited) == 1 else "Split into one sentence per claim, each in the claim's words."
            v.update(verdict="block", reason=reason, explanation=why, suggested_fix=fix)
        else:
            v["explanation"] = "Supported by the cited claims."
        out.append(v)

    page = []
    for a, b in zip(out, out[1:]):
        tb = strip_tags(b["text"])
        if CONCLUDE_RE.search(tb) and b["verdict"] == "pass" and len(b["cited_ids"]) and a["cited_ids"] and \
                not set(b["cited_ids"]) >= set(a["cited_ids"]):
            # a passing sentence that draws a conclusion right after another claim: check it isn't implied by both
            extra = stems(tb) - stems(" ".join(box.claims[i]["text"] for i in b["cited_ids"])) - GENERIC_STEMS
            if len(extra) >= 2:
                page.append({"kind": "implied-conclusion", "sentence_indexes": [a["index"], b["index"]],
                             "claim_ids": a["cited_ids"] + b["cited_ids"], "verdict": "block", "reason": "combined-conclusion",
                             "explanation": "Read together, these sentences imply a conclusion the claims don't state."})
    # tension: cited claims that are in an open conflict with each other or with a related claim
    cited_all = {i for v in out for i in v["cited_ids"]}
    for conf in p.get("conflicts", []):
        if conf["status"] == "open" and cited_all & set(conf["claim_ids"]):
            idx = [v["index"] for v in out if set(v["cited_ids"]) & set(conf["claim_ids"])]
            on_page = cited_all & set(conf["claim_ids"])
            severity = "block" if conf["kind"] == "absolute-vs-exception" and any(
                SUPERLATIVE_RE.search(box.claims[i]["text"]) for i in on_page if i in box.claims) else "flag"
            page.append({"kind": "colliding-absolutes" if conf["kind"] == "absolute-vs-exception" else "tension",
                         "sentence_indexes": idx, "claim_ids": list(conf["claim_ids"]), "verdict": severity,
                         "reason": "overstated" if severity == "block" else "tension",
                         "explanation": f"Open conflict {conf['id']} ({conf['kind']}): {conf['explanation']}"})
    return {"draft_hash": p["draft_hash"], "sentences": out, "page_checks": page}


def _support(text, ctext, cited, box, vocab=frozenset()):
    """Return (reason, explanation) if the cited claims don't fully support the sentence, else (None, '')."""
    s_low, c_low = text.lower(), ctext.lower()
    for m in SUPERLATIVE_RE.finditer(text):
        w = m.group(0).lower()
        if not re.search(rf"\b{re.escape(w)}\b", c_low):
            return "overstated", f"'{m.group(0)}' is not in the claim."
    sn, cn = numbers(text), numbers(ctext)
    if sn - cn:
        if cn:
            return "contradicted", f"Numbers {sorted(sn - cn)} differ from the claim's {sorted(cn)}."
        return "partial", f"Numbers {sorted(sn - cn)} are not in the claim."
    if bool(NEG_RE.search(text)) != bool(NEG_RE.search(ctext)) and \
            len(stems(text) & stems(ctext)) / max(1, len(stems(text) | stems(ctext))) >= 0.6:
        return "contradicted", "The sentence and the claim differ in negation."
    for m in CONDITION_RE.finditer(ctext):
        cond = m.group(0).lower().strip()
        key = [w for w in tokens(cond) if len(w) > 2] or [cond]
        if not all(re.search(rf"\b{re.escape(k)}", s_low) for k in key):
            return "overstated", f"Drops the condition '{m.group(0).strip()}'."
    st, ct = stems(text) - GENERIC_STEMS, stems(ctext)
    extra = {w for w in st - ct if not w.isdigit()}
    known_extra = extra & vocab
    if st and ((len(extra) / len(st) > 0.34 and len(extra) >= 2) or len(extra) >= 4 or (len(known_extra) >= 1 and len(extra) >= 2)):
        return ("combined-conclusion" if len(cited) > 1 else "partial"), \
            f"Says more than the claim{'s' if len(cited) > 1 else ''}: {', '.join(sorted(extra)[:6])}."
    # absolute claim on the page vs documented exception elsewhere in the registry
    return None, ""


# ---------------- style-checker ----------------

def _crit_weights(profile):
    return {r["criterion"].lower(): r["weight"] for r in profile["rubric"]} or {"voice": .25, "cadence": .25, "vocabulary": .2, "naming": .2, "formatting": .1}


def style_score(md, profile):
    """Deterministic score (0-1) of a Markdown text against a profile, with flags. Used by the checker and calibration."""
    text = strip_tags(md)
    m = measure([text])
    cad = profile["cadence"]
    flags, s = [], {}
    avg, pavg = m["avg_sentence_words"], max(1.0, cad["avg_sentence_words"])
    s["cadence"] = max(0.0, 1 - abs(avg - pavg) / pavg)
    s["voice"] = max(0.0, 1 - abs(m["second_person_rate"] - cad["second_person_rate"]) * 1.5 - m["exclamation_rate"] * 3)
    low = text.lower()
    pref = profile["vocabulary"]["preferred"]
    used = sum(1 for w in pref if re.search(rf"\b{re.escape(w.lower())}\b", low))
    hype = [w for w in profile["vocabulary"]["avoid"] if re.search(rf"\b{re.escape(w.lower())}\b", low)]
    s["vocabulary"] = max(0.0, min(1.0, used / max(1, min(6, len(pref)))) - 0.2 * len(hype))
    for w in hype:
        flags.append({"severity": "low", "issue": f"Uses '{w}', which the team's copy avoids.", "fix": f"Remove '{w}'."})
    banned = [w for w in profile["vocabulary"]["banned"] if re.search(rf"\b{re.escape(w.lower())}\b", low)]
    for w in banned:
        flags.append({"severity": "high", "issue": f"Banned term '{w}'.", "fix": f"Remove '{w}'."})
    name = profile["naming"]["product_name"]
    forb = [f for f in profile["naming"]["forbidden"] if name_re(f).search(text)]
    s["naming"] = 0.0 if forb else 1.0 if name.lower() in low else 0.6
    for f in forb:
        flags.append({"severity": "high", "issue": f"Uses forbidden product name '{f}'.", "fix": f"Use '{name}'."})
    hc = heading_case(headings(md))
    s["formatting"] = 1.0 if hc == profile["formatting"]["heading_case"] or not headings(md) else 0.5
    if s["formatting"] < 1:
        flags.append({"severity": "low", "issue": f"Headings are {hc}-case; the profile uses {profile['formatting']['heading_case']}-case."})
    w = _crit_weights(profile)
    total = sum(w.values()) or 1
    score = sum(w.get(k, 0) * v for k, v in s.items()) / total
    if banned:
        score = min(score, 0.4)
    return round(score, 3), {k: round(v, 3) for k, v in s.items()}, flags


def style_checker(p, box):
    profile, threshold = p["profile"], p.get("threshold")
    score, scores, flags = style_score(p["draft_md"], profile)
    passed = None if threshold is None else score >= threshold
    if threshold is None:
        flags.append({"severity": "low", "issue": "Style threshold not calibrated; score is informational."})
    elif not passed:
        flags.append({"severity": "high", "issue": f"Style score {score:.3f} is below the calibrated threshold {threshold:.3f}."})
    return {"checker": "style-checker", "status": "ok", "score": score, "threshold": threshold, "passed": passed,
            "scores": scores, "flags": flags}


# ---------------- best-practice-auditor ----------------

def best_practice_auditor(p, box):
    md, plan, ct, pack = p["draft_md"], p["plan"], p["content_type"], p.get("pack") or {}
    text = strip_tags(md)
    flags, s = [], {}
    hs = headings(md)
    has_h1 = bool(re.search(r"^#\s+\S", md, re.M))
    s["structure"] = 1.0 if has_h1 else 0.3
    if not has_h1 and ct["id"] not in ("email",):
        flags.append({"severity": "high", "issue": "No headline (H1).", "fix": "Add a headline that meets the reader's stage."})
    required = [x for x in ct["sections"] if x["required"]]
    missing = [x["name"] for x in required[1:] if not any(x["name"].lower() in h.lower() for h in hs)]
    if ct["id"] != "email" and missing:
        s["structure"] -= 0.15 * len(missing)
        flags.append({"severity": "low", "issue": f"Missing sections from the {ct['name']} outline: {', '.join(missing)}."})
    sents = [x for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")
             for x in split_sentences(line.strip().lstrip("-*+ ").strip())]
    ctas = [x for x in sents if CTA_RE.match(x.strip("# ").strip()) or x.strip().endswith("?") and re.search(r"\b(walkthrough|demo|call|chat)\b", x, re.I)]
    s["cta"] = 1.0 if len(ctas) >= 1 else 0.0
    if not ctas:
        flags.append({"severity": "high", "issue": "No call to action.", "fix": "End with one clear next step."})
    elif len({c.lower() for c in ctas}) > 2:
        s["cta"] = 0.7
        flags.append({"severity": "low", "issue": "More than two different CTAs; pick one primary next step."})
    words = word_count(text)
    lo, hi = ct["length_words"]
    s["length"] = 1.0 if lo <= words <= hi else max(0.0, 1 - abs(words - (lo if words < lo else hi)) / max(lo, 1))
    if s["length"] < 1:
        flags.append({"severity": "low", "issue": f"{words} words; the {ct['name']} template expects {lo}–{hi}."})
    persona = next((x for x in pack.get("personas", []) if x["name"] == plan.get("persona")), None)
    if persona:
        pains = stems(" ".join(persona["pains"]))
        hit = len(pains & stems(text)) / max(1, len(pains))
        s["positioning"] = min(1.0, hit * 2)
        if hit < 0.2:
            flags.append({"severity": "low", "issue": f"Barely touches {persona['name']}'s pains.", "fix": "Name their main pain early."})
    else:
        s["positioning"] = 0.5
    opening = " ".join(sents[:3]).lower()
    stage = p["stage"]
    pname = (p.get("product_name") or "").lower()
    if stage in ("unaware", "problem-aware") and pname and pname in opening and not persona:
        s["stage"] = 0.5
        flags.append({"severity": "low", "issue": "Opens with the product for a problem-aware reader; lead with the problem."})
    else:
        s["stage"] = 1.0
    score = round(sum(s.values()) / len(s), 3)
    return {"checker": "best-practice-auditor", "status": "ok", "score": max(0.0, score), "threshold": None,
            "passed": not any(f["severity"] == "high" for f in flags), "scores": {k: round(max(0, v), 3) for k, v in s.items()},
            "flags": flags}


# ---------------- synthetic-buyer ----------------

def synthetic_buyer(p, box):
    persona, text = p["persona"], p["draft_text"]
    ts = stems(text)
    pri = persona.get("priorities", [])
    hit = [x for x in pri if len(stems(x) & ts) / max(1, len(stems(x))) >= 0.34]
    objections = []
    for o in persona.get("objections", []):
        if len(stems(o) & ts) / max(1, len(stems(o))) < 0.5:
            ans = box.search_registry(o, limit=1)
            ok = bool(ans) and len(stems(o) & stems(ans[0]["text"])) / max(1, len(stems(o))) >= 0.5
            objections.append({"text": o, "answerable_by_docs": ok})
    verdict = "yes" if pri and len(hit) == len(pri) and not objections else "no" if not hit else "maybe"
    return {"verdict": verdict,
            "summary": f"Covers {len(hit)} of {len(pri)} of my priorities; {len(objections)} objection(s) still open.",
            "objections": objections, "missing_proof": [o["text"] for o in objections if not o["answerable_by_docs"]]}
