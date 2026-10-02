"""Deterministic gate decisions: parse drafts, enforce mechanical block rules, combine checks,
finalize, staleness, knowledge-base status, round archiving and rollback, re-flagging.

Models propose, code decides. Nothing in this module calls a model.

Status rule (PRD §8.6, ARCHITECTURE §6):
    any sentence or page-level BLOCK          -> blocked
    elif any high-severity flag               -> flagged
    else                                      -> approved
    a logged override on the same draft hash  -> approved-override (never plain approved)
A missing gate result is never a pass: it is blocked.
"""
import re

from packages.util import TAG_RE, now_iso, sha256_text, split_sentences, strip_tags, tags_in

CHECKERS = ("style-checker", "best-practice-auditor", "synthetic-buyer")
APPROVED = ("approved", "approved-override")


class GateError(RuntimeError):
    pass


# ---------------- draft parsing ----------------

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def parse_draft(md):
    """Split a Markdown draft into gate units: every heading, list item and prose sentence.

    Returns [{index, section, kind, text}]. The verifier and the mechanical checks both use
    this, so sentence indexes line up across them.
    """
    md = COMMENT_RE.sub("", md)
    units, section, para = [], "", []

    def flush():
        if para:
            for s in split_sentences(" ".join(para)):
                units.append({"section": section, "kind": "sentence", "text": s})
            para.clear()

    for line in md.splitlines():
        if not line.strip():
            flush()
            continue
        h = HEADING_RE.match(line)
        if h:
            flush()
            section = strip_tags(h.group(2)).strip()
            units.append({"section": section, "kind": "heading", "text": h.group(2).strip()})
            continue
        li = LIST_RE.match(line)
        if li:
            flush()
            for s in split_sentences(li.group(1)):
                units.append({"section": section, "kind": "list-item", "text": s})
            continue
        if line.strip().startswith(("|", "---", "```")):
            flush()
            cells = [c.strip() for c in line.strip().strip("|").split("|") if c.strip() and not set(c.strip()) <= set("-:")]
            for c in cells:
                units.append({"section": section, "kind": "table-cell", "text": c})
            continue
        para.append(line.strip())
    flush()
    for i, u in enumerate(units):
        u["index"] = i
    return units


def draft_hash(md):
    return sha256_text(md)


# ---------------- mechanical enforcement ----------------

def _norm(t):
    return re.sub(r"\s+", " ", strip_tags(t)).strip().lower()


def align_verdicts(units, verdicts):
    """Map each unit index to the verifier's verdict for it (by index, confirmed by text)."""
    by_index = {v["index"]: v for v in verdicts.get("sentences", [])}
    by_text = {_norm(v["text"]): v for v in verdicts.get("sentences", [])}
    out = {}
    for u in units:
        v = by_index.get(u["index"])
        if v is None or _norm(v["text"]) != _norm(u["text"]):
            v = by_text.get(_norm(u["text"]))
        out[u["index"]] = v
    return out


def mechanical_verdict(unit, claims, high_risk):
    """Block/flag reasons code can determine without judgment. Returns (verdict, reason, explanation) or None."""
    ids = tags_in(unit["text"])
    worst = None
    for cid in ids:
        c = claims.get(cid)
        if c is None:
            return ("block", "missing-claim", f"{cid} does not exist in the registry.")
        if c["status"] == "deprecated":
            return ("block", "deprecated", f"{cid} is deprecated ({c.get('status_reason') or 'no reason recorded'}).")
        if c["status"] != "verified":
            return ("block", "needs-review", f"{cid} is {c['status']}; only verified claims are citable.")
        if c["confidence"] == "low" and c["category"] in high_risk and not (c.get("user_decision") or {}).get("kind") == "confirmed":
            return ("block", "high-risk-low-confidence", f"{cid} is low-confidence in high-risk category {c['category']}.")
        if c["confidence"] == "low":
            worst = worst or ("flag", "low-confidence", f"{cid} is low-confidence.")
    return worst


def enforce(units, verdicts, claims, high_risk, positioning_marks=()):
    """Final per-unit verdicts: the verifier's judgment, made stricter (never looser) by code rules."""
    marks = {_norm(m["sentence"]) for m in positioning_marks}
    aligned = align_verdicts(units, verdicts) if verdicts else {}
    final = []
    for u in units:
        v = aligned.get(u["index"])
        if v is None:
            v = {"index": u["index"], "text": u["text"], "section": u["section"], "classification": "factual",
                 "cited_ids": tags_in(u["text"]), "relevant_ids": [], "verdict": "block", "reason": "untagged",
                 "explanation": "The verifier returned no verdict for this sentence, so it cannot pass.",
                 "suggested_fix": "Re-run verification."}
        v = dict(v, index=u["index"], text=u["text"], section=u["section"], cited_ids=tags_in(u["text"]))
        v["kind"] = u["kind"]
        mech = mechanical_verdict(u, claims, high_risk)
        if mech and (mech[0] == "block" or v["verdict"] == "pass"):
            if not (v["verdict"] == "block" and mech[0] == "flag"):
                v.update(verdict=mech[0], reason=mech[1], explanation=mech[2])
        if v["verdict"] == "block" and v.get("reason") == "untagged" and not v["cited_ids"] and _norm(u["text"]) in marks:
            v.update(verdict="pass", reason=None, classification="positioning",
                     explanation="Marked as positioning by a reviewer (logged).")
        final.append(v)
    return final


# ---------------- combine ----------------

def combine(*, run_id, round_no, round_kind, md, units, verdicts, claims, high_risk, checker_reports, enabled,
            auto_revisions_used, override=None, positioning_marks=()):
    """Join all checker outputs into a verification report (schema: verification-report)."""
    dh = draft_hash(md)
    flags, scores, missing = [], {}, []
    if verdicts is None or verdicts.get("draft_hash") not in (None, dh):
        final = enforce(units, None, claims, high_risk)
        flags.append({"source": "gate", "severity": "block",
                      "issue": "Gate result missing or for a different draft; a missing gate result is never a pass."})
        verdicts = {"sentences": [], "page_checks": []}
    else:
        final = enforce(units, verdicts, claims, high_risk, positioning_marks)

    for v in final:
        if v["verdict"] == "block":
            flags.append({"source": "gate", "severity": "block", "sentence": v["text"], "reason": v["reason"] or "",
                          "issue": f"{v['reason']}: {v['explanation']}" + (f" Fix: {v['suggested_fix']}" if v.get("suggested_fix") else "")})
        elif v["verdict"] == "flag":
            flags.append({"source": "gate", "severity": "low", "sentence": v["text"], "reason": v["reason"] or "",
                          "issue": f"{v['reason']}: {v['explanation']}"})
    for p in verdicts.get("page_checks", []):
        sents = " / ".join(final[i]["text"] for i in p["sentence_indexes"] if i < len(final))
        flags.append({"source": "gate", "severity": "block" if p["verdict"] == "block" else "low", "sentence": sents,
                      "reason": p["reason"], "issue": f"{p['kind']}: {p['explanation']}"})

    for name in CHECKERS:
        if not enabled.get(name):
            continue
        rep = checker_reports.get(name)
        if name == "synthetic-buyer":
            if rep is None:
                missing.append(name)
                continue
            scores[name] = rep["verdict"]
            if rep["verdict"] != "yes":
                flags.append({"source": name, "severity": "low", "issue": f"Buyer reaction '{rep['verdict']}': {rep.get('summary', '')}"})
            continue
        if rep is None or rep.get("status") == "checker-unavailable":
            missing.append(name)
            flags.append({"source": name, "severity": "high", "issue": f"{name} unavailable; draft can't be auto-approved."})
            continue
        scores[name] = rep.get("score")
        for f in rep["flags"]:
            e = {"source": name, "severity": f["severity"], "issue": f["issue"] + (f" Fix: {f['fix']}" if f.get("fix") else "")}
            if f.get("sentence"):
                e["sentence"] = f["sentence"]
            flags.append(e)

    blocks = sum(1 for f in flags if f["severity"] == "block")
    high = sum(1 for f in flags if f["severity"] == "high")
    low = sum(1 for f in flags if f["severity"] == "low")
    status = "blocked" if blocks else "flagged" if high else "approved"
    ov = None
    if override and override.get("draft_hash") == dh and status != "approved":
        ov = {"by": override["by"], "at": override["at"], "reason": override["reason"]}
        status = "approved-override"
    return {"run_id": run_id, "round": round_no, "round_kind": round_kind, "draft_hash": dh, "status": status,
            "block_count": blocks, "high_count": high, "low_count": low, "flags": flags, "checker_scores": scores,
            "checkers_missing": missing, "auto_revisions_used": auto_revisions_used, "override": ov,
            "positioning_marks": [dict(sentence=m["sentence"], by=m["by"], at=m["at"]) for m in positioning_marks],
            "generated_at": now_iso()}, final


def needs_revision(report, auto_revisions_used, cap=2):
    return report["status"] in ("blocked", "flagged") and auto_revisions_used < cap


# ---------------- finalize / export ----------------

def finalize(md, report):
    """Final copy: tags stripped. Only from approved or approved-override reports for this exact draft."""
    if report["status"] not in APPROVED:
        raise GateError(f"cannot finalize a {report['status']} draft")
    if report["draft_hash"] != draft_hash(md):
        raise GateError("report is for a different draft")
    if report["status"] == "approved" and report["block_count"]:
        raise GateError("approved report has blocks")
    out = COMMENT_RE.sub("", md)
    out = strip_tags(out)
    return re.sub(r"\n{3,}", "\n\n", out).strip() + "\n"


def finalize_preview(md):
    """Tag-stripped text for readers that must not see tags (synthetic buyer). Not final copy."""
    return re.sub(r"\n{3,}", "\n\n", strip_tags(COMMENT_RE.sub("", md))).strip() + "\n"


def cited_ids(md):
    return sorted(set(TAG_RE.findall(md)))


# ---------------- content item: rounds, rollback, re-flag ----------------

def new_content_item(brief):
    return {"id": brief["id"], "product_id": brief["product_id"], "brief_id": brief["id"], "status": "running",
            "live_version": None, "rounds": [], "auto_revisions_used": 0, "human_rounds": 0, "review_state": "none",
            "reflags": [], "positioning_marks": [], "override": None, "updated_at": now_iso()}


def apply_result(item, round_entry, report, final_ref, cited):
    """Archive the round and update the live version. A failed revision never replaces approved content."""
    round_entry = dict(round_entry, status=report["status"], block_count=report["block_count"])
    item["rounds"].append(round_entry)
    if report["status"] in APPROVED:
        item["live_version"] = {"round": round_entry["round"], "status": report["status"], "final_ref": final_ref,
                                "report_ref": round_entry["report_ref"], "cited_ids": cited, "approved_at": now_iso()}
        item["status"], item["review_state"] = report["status"], "closed"
    else:
        # rollback semantics: the previous live version (if any) stays exactly as it was
        item["status"] = item["live_version"]["status"] if item["live_version"] else report["status"]
        item["review_state"] = "open"
    item["updated_at"] = now_iso()
    return item


def reflag(items, claims):
    """Re-flag every live version that cites a claim no longer verified. Returns the items that changed."""
    changed = []
    for item in items:
        lv = item.get("live_version")
        if not lv:
            continue
        bad = [cid for cid in lv["cited_ids"] if (claims.get(cid) or {}).get("status") != "verified"]
        known = {r["claim_id"] for r in item["reflags"] if not r.get("cleared")}
        fresh = [cid for cid in bad if cid not in known]
        if not fresh:
            continue
        for cid in fresh:
            c = claims.get(cid) or {}
            item["reflags"].append({"claim_id": cid, "at": now_iso(), "reason": f"cited claim is now {c.get('status', 'missing')}"
                                    + (f" ({c.get('status_reason')})" if c.get("status_reason") else "")})
        lv["status"] = "flagged"
        item["status"], item["review_state"] = "flagged", "open"
        item["updated_at"] = now_iso()
        changed.append(item)
    return changed


def can_export(item):
    lv = item.get("live_version")
    return bool(lv and lv["status"] in APPROVED)


# ---------------- staleness and knowledge-base status ----------------

def staleness(claims, new_texts, content_items=(), conflicts=()):
    """new_texts: {source_id: normalized text of the new snapshot, or None if removed}.
    Returns claims whose quote no longer appears verbatim, plus the content and conflicts they touch."""
    from packages.util import norm_ws
    affected = []
    for c in claims.values():
        if c["source_id"] not in new_texts or c["status"] == "deprecated":
            continue
        txt = new_texts[c["source_id"]]
        if txt is None or norm_ws(c["quote"]).lower() not in norm_ws(txt).lower():
            affected.append(c["id"])
    aset = set(affected)
    items = [i["id"] for i in content_items if i.get("live_version") and aset & set(i["live_version"]["cited_ids"])]
    confs = [c["id"] for c in conflicts if aset & set(c["claim_ids"])]
    return {"claims": sorted(affected), "content_items": items, "conflicts": confs}


def kb_status(sources, claims, profile, pack, stale_sources=()):
    by_type = {"truth": 0, "style": 0, "positioning": 0, "evidence": 0}
    for s in sources:
        if s["status"] == "active":
            by_type[s["type"]] += 1
    verified = sum(1 for c in claims.values() if c["status"] == "verified")
    review = sum(1 for c in claims.values() if c["status"] == "needs-review")
    warnings, blockers = [], []
    if not by_type["truth"]:
        blockers.append("No truth sources: add product docs before generating.")
    elif not verified:
        blockers.append("No verified claims yet: build the knowledge base and review claims.")
    if not by_type["style"]:
        warnings.append("No style sources: copy will not be style-checked against your voice.")
    elif not profile:
        warnings.append("Style profile not built (needs about 1,500 words across 3 pieces).")
    elif profile["status"] != "active":
        warnings.append("Style profile is a draft: resolve its consistency issues.")
    elif profile.get("threshold") is None:
        warnings.append("Style threshold not calibrated and accepted.")
    if not by_type["positioning"]:
        warnings.append("No positioning sources: content will use generic framing.")
    elif not pack:
        warnings.append("Positioning pack not built.")
    if stale_sources:
        warnings.append(f"{len(stale_sources)} source(s) changed since the last build: knowledge base is stale.")
    state = "blocked" if blockers else "stale" if stale_sources else "ready"
    return {"state": state, "sources": by_type, "verified": verified, "needs_review": review,
            "blockers": blockers, "warnings": warnings, "stale_sources": list(stale_sources), "updated_at": now_iso()}
