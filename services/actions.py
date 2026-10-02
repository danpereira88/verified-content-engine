"""Application actions performed when a person acts (CLAUDE.md §2.6). Agents never call these.

Each action checks the actor's role, writes its record, and writes an audit event.
"""
import html
import io
import json
import re
import zipfile

from packages import gate, registry
from packages.util import now_iso, new_id, strip_tags, tags_in, split_sentences
from packages.validate import check
from services import ingest, orchestrator

ROLE_FOR = {
    "product.create": {"admin"}, "product.update": {"admin"}, "source.add": {"admin", "editor", "sme"},
    "source.remove": {"admin"}, "ingest": {"admin", "editor", "sme"},
    "claim.confirm": {"sme", "admin"}, "claim.reject": {"sme", "admin"}, "claim.deprioritize": {"sme", "admin", "editor"},
    "claim.doc-wrong": {"sme", "admin"}, "claim.confirm-high-risk": {"compliance", "admin"},
    "conflict.rule": {"sme", "admin"}, "decision.edit": {"admin", "editor"}, "brief.create": {"editor", "admin"},
    "content.run": {"editor", "admin"}, "content.edit": {"editor", "reviewer", "admin"},
    "content.direct": {"editor", "reviewer", "admin"}, "content.override": {"reviewer", "admin"},
    "content.reject": {"reviewer", "admin"}, "content.mark-positioning": {"reviewer", "admin"},
    "content.export": {"editor", "reviewer", "admin"}, "style.accept-threshold": {"admin"},
    "settings.update": {"admin"}, "eval.run": {"admin", "editor"}, "member.manage": {"admin"},
}


class Forbidden(PermissionError):
    pass


def require(actor, action):
    roles = set(actor.get("roles", []))
    if not roles & ROLE_FOR[action]:
        raise Forbidden(f"{actor.get('email', 'user')} needs one of {sorted(ROLE_FOR[action])} to {action}")


# ---------------- products ----------------

def create_product(ws, actor, name, claim_prefix, slug=None, company="", content_types=None, high_risk_categories=None,
                   buyer_persona=None):
    require(actor, "product.create")
    slug = slug or ingest.slugify(name, 40)
    if ws.get("product", slug):
        raise ValueError(f"product {slug} already exists")
    if any(p["claim_prefix"] == claim_prefix for p in ws.list("product")):
        raise ValueError(f"claim prefix {claim_prefix} is already used in this workspace")
    p = {"id": slug, "workspace_id": ws.workspace_id, "slug": slug, "name": name, "company": company,
         "claim_prefix": claim_prefix, "content_types": content_types or sorted(orchestrator.content_types(ws)),
         "high_risk_categories": high_risk_categories or list(registry.DEFAULT_HIGH_RISK),
         "buyer_persona": buyer_persona, "style_threshold": None, "style_threshold_accepted_by": None,
         "checkers": {"style": True, "best_practice": True, "synthetic_buyer": bool(buyer_persona)}, "models": {},
         "created_at": now_iso()}
    ws.put("product", p)
    ws.audit(actor["email"], "product.create", slug, name)
    return p


def update_product(ws, actor, product_id, **fields):
    require(actor, "product.update")
    p = ws.product(product_id)
    for k in ("name", "company", "content_types", "high_risk_categories", "buyer_persona", "checkers", "models"):
        if k in fields and fields[k] is not None:
            p[k] = fields[k]
    ws.put("product", p)
    ws.audit(actor["email"], "product.update", product_id, ", ".join(sorted(fields)))
    return p


def add_source(ws, actor, product_id, source_type, name, data, origin_kind="file", origin=None):
    require(actor, "source.add")
    ws.product(product_id)
    src, changed = ingest.add_source(ws, product_id, source_type, name, data, origin_kind, origin)
    report = None
    if changed:
        ws.audit(actor["email"], "source.add", src["id"], f"{source_type}: {name} sha256={src['sha256'][:12]}")
        report = orchestrator.mark_stale(ws, product_id, [src["id"]])
    return src, changed, report


def remove_source(ws, actor, product_id, source_id):
    require(actor, "source.remove")
    src = ingest.remove_source(ws, source_id)
    ws.audit(actor["email"], "source.remove", source_id)
    return src, orchestrator.mark_stale(ws, product_id, [source_id])


# ---------------- decisions ----------------

def save_decision(ws, actor, product_id, text, decision_id=None):
    require(actor, "decision.edit")
    text = text.strip()
    if not text:
        raise ValueError("decision text is required")
    old = ws.get("decision", f"{product_id}:{decision_id}") if decision_id else None
    if not decision_id:
        nums = [int(re.sub(r"\D", "", d["id"]) or 0) for d in ws.list("decision", product_id)]
        decision_id = f"DEC-{max(nums + [0]) + 1:03d}"
    d = {"id": decision_id, "product_id": product_id, "text": text, "author": actor["email"], "created_at": now_iso()}
    d["derived_guardrails"] = registry.derive_guardrails(d)
    ws.put("decision", d, id=f"{product_id}:{decision_id}")
    diff = registry.guardrail_diff(old["derived_guardrails"] if old else [], d["derived_guardrails"])
    ws.audit(actor["email"], "decision.edit" if old else "decision.add", decision_id, text)
    _apply_decisions(ws, product_id)
    return d, diff


def _apply_decisions(ws, product_id):
    decisions = orchestrator._decisions(ws, product_id)
    prof = ws.get("style-profile", product_id)
    if prof:
        ws.put("style-profile", orchestrator.apply_decisions_to_profile(prof, decisions), id=product_id, product_id=product_id)
    pack = ws.get("positioning-pack", product_id)
    if pack:
        ws.put("positioning-pack", orchestrator.relink_pack(pack, ws.claims(product_id), decisions), id=product_id,
               product_id=product_id, decision_ids={d["id"] for d in decisions})


# ---------------- rulings ----------------

def rule_claim(ws, actor, product_id, claim_id, kind, note=""):
    if kind not in ("confirmed", "rejected", "deprioritized", "doc-wrong"):
        raise ValueError("kind must be confirmed, rejected, deprioritized or doc-wrong")
    product = ws.product(product_id)
    c = ws.get("claim", claim_id)
    if not c or c["product_id"] != product_id:
        raise KeyError(claim_id)
    action = {"confirmed": "claim.confirm", "rejected": "claim.reject", "deprioritized": "claim.deprioritize",
              "doc-wrong": "claim.doc-wrong"}[kind]
    require(actor, action)
    if kind == "confirmed" and c["category"] in product["high_risk_categories"]:
        require(actor, "claim.confirm-high-risk")
    if kind in ("doc-wrong", "rejected") and not note.strip():
        raise ValueError("say why: the note is stored verbatim and sent to the docs owner")
    r = {"id": new_id("rul"), "workspace_id": ws.workspace_id, "target_kind": "claim", "target_id": claim_id, "kind": kind,
         "note": note, "author": actor["email"], "created_at": now_iso(), "quote_hash": c["quote_hash"], "keep_claim_id": None}
    ws.put("ruling", r, product_id=product_id)
    ws.audit(actor["email"], action, claim_id, note)
    orchestrator.rebuild_registry(ws, product_id)
    orchestrator.refresh_status(ws, product_id)
    return ws.get("claim", claim_id)


def bulk_rule(ws, actor, product_id, claim_ids, kind, note=""):
    product = ws.product(product_id)
    for cid in claim_ids:
        c = ws.get("claim", cid)
        if c and c["category"] in product["high_risk_categories"]:
            raise ValueError(f"{cid} is high-risk ({c['category']}); review it individually")
    return [rule_claim(ws, actor, product_id, cid, kind, note) for cid in claim_ids]


def rule_conflict(ws, actor, product_id, conflict_id, keep_claim_id, note):
    """keep_claim_id = the claim that is right (others are deprecated as doc-wrong), or None = both stand."""
    require(actor, "conflict.rule")
    conf = ws.get("conflict", conflict_id)
    if not conf or conf["product_id"] != product_id:
        raise KeyError(conflict_id)
    if keep_claim_id and keep_claim_id not in conf["claim_ids"]:
        raise ValueError("keep_claim_id must be one of the conflict's claims")
    if not note.strip():
        raise ValueError("a conflict ruling needs a note")
    r = {"id": new_id("rul"), "workspace_id": ws.workspace_id, "target_kind": "conflict", "target_id": conflict_id,
         "kind": "conflict-resolved", "note": note, "author": actor["email"], "created_at": now_iso(), "quote_hash": None,
         "keep_claim_id": keep_claim_id}
    ws.put("ruling", r, product_id=product_id)
    conf["status"] = "resolved"
    ws.put("conflict", conf)
    ws.audit(actor["email"], "conflict.rule", conflict_id, f"keep={keep_claim_id or 'both'}: {note}")
    orchestrator.rebuild_registry(ws, product_id)
    return ws.get("conflict", conflict_id)


# ---------------- style ----------------

def accept_threshold(ws, actor, product_id, threshold=None):
    require(actor, "style.accept-threshold")
    p = ws.product(product_id)
    st = ws.get("kb-status", product_id) or {}
    thr = threshold if threshold is not None else (st.get("calibration") or {}).get("recommended_threshold")
    if thr is None:
        raise ValueError("no calibrated threshold to accept: build the knowledge base first")
    p["style_threshold"], p["style_threshold_accepted_by"] = float(thr), actor["email"]
    ws.put("product", p)
    prof = ws.get("style-profile", product_id)
    if prof:
        prof["threshold"] = float(thr)
        ws.put("style-profile", prof, id=product_id, product_id=product_id)
    ws.audit(actor["email"], "style.accept-threshold", product_id, str(thr))
    orchestrator.refresh_status(ws, product_id)
    return p


# ---------------- briefs ----------------

def create_brief(ws, actor, product_id, content_type, title, audience, goal, stage, notes="", mandated_wording=None):
    require(actor, "brief.create")
    p = ws.product(product_id)
    if content_type not in orchestrator.content_types(ws):
        raise ValueError(f"unknown content type {content_type}")
    if content_type not in p["content_types"]:
        raise ValueError(f"{content_type} is not enabled for {p['name']}")
    b = {"id": ingest.slugify(title, 40) + "-" + new_id()[:4], "product_id": product_id, "content_type": content_type,
         "title": title, "audience": audience, "goal": goal, "stage": stage, "notes": notes,
         "mandated_wording": mandated_wording or [], "created_by": actor["email"], "created_at": now_iso()}
    ws.put("brief", b)
    ws.audit(actor["email"], "brief.create", b["id"], title)
    return b


# ---------------- export ----------------

def export(ws, actor, item_id, fmt="md", with_citations=False):
    """Export approved or override-approved content only, tags stripped. Evidence is never exported."""
    require(actor, "content.export")
    item = ws.get("content", item_id)
    if not item or not gate.can_export(item):
        raise ValueError("only approved or approved-override content can be exported")
    lv = item["live_version"]
    final = ws.get_text(lv["final_ref"])
    if with_citations:
        r = next(x for x in item["rounds"] if x["round"] == lv["round"])
        draft = ws.get_text(r["draft_ref"])
        final = citations_view(ws, item["product_id"], draft)
    ws.audit(actor["email"], "content.export", item_id, f"{fmt}{' with citations' if with_citations else ''}")
    if fmt == "md":
        return final.encode("utf-8"), "text/markdown", f"{item_id}.md"
    if fmt == "html":
        return md_to_html(final).encode("utf-8"), "text/html", f"{item_id}.html"
    if fmt == "docx":
        return md_to_docx(final), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"{item_id}.docx"
    raise ValueError("format must be md, html or docx")


def citations_view(ws, product_id, draft):
    claims = ws.claims(product_id)
    srcs = {s["id"]: s for s in ws.list("source", product_id)}
    out = ["<!-- INTERNAL REVIEW COPY: includes citations. Do not publish. -->", ""]
    for line in draft.splitlines():
        out.append(strip_tags(line))
        for cid in tags_in(line):
            c = claims.get(cid)
            if c and srcs.get(c["source_id"], {}).get("type") != "evidence":
                s = srcs.get(c["source_id"], {})
                out.append(f"    > {cid}: \"{c['quote']}\" ({s.get('title', c['source_id'])}, {c['location']})")
    return "\n".join(out) + "\n"


def _inline_html(s):
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    return re.sub(r"\*(.+?)\*", r"<em>\1</em>", s)


def md_to_html(md):
    out, in_list = [], False
    for line in md.splitlines():
        h = re.match(r"^(#{1,6})\s+(.*)$", line)
        li = re.match(r"^\s*[-*+]\s+(.*)$", line)
        if in_list and not li:
            out.append("</ul>")
            in_list = False
        if h:
            n = len(h.group(1))
            out.append(f"<h{n}>{_inline_html(h.group(2))}</h{n}>")
        elif li:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline_html(li.group(1))}</li>")
        elif line.strip():
            out.append(f"<p>{_inline_html(line.strip())}</p>")
    if in_list:
        out.append("</ul>")
    return "<!doctype html>\n<html><head><meta charset=\"utf-8\"></head><body>\n" + "\n".join(out) + "\n</body></html>\n"


def md_to_docx(md):
    def para(text, style=None):
        text = re.sub(r"[*_`]", "", text)
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        return f'<w:p>{ppr}<w:r><w:t xml:space="preserve">{html.escape(text)}</w:t></w:r></w:p>'
    body = []
    for line in md.splitlines():
        h = re.match(r"^(#{1,6})\s+(.*)$", line)
        li = re.match(r"^\s*[-*+]\s+(.*)$", line)
        if h:
            body.append(para(h.group(2), f"Heading{len(h.group(1))}"))
        elif li:
            body.append(para("• " + li.group(1)))
        elif line.strip():
            body.append(para(line.strip()))
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document '
           'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + "".join(body) + "</w:body></w:document>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


# ---------------- reporting ----------------

def gaps_report(ws, product_id):
    claims = ws.claims(product_id)
    pack = ws.get("positioning-pack", product_id) or {}
    product = ws.product(product_id)
    sources = {s["id"]: s for s in ws.list("source", product_id)}
    rulings = ws.list("ruling", product_id)
    cats = {}
    for c in claims.values():
        if c["status"] != "deprecated":
            cats[c["category"]] = cats.get(c["category"], 0) + 1
    coverage = [{"topic": t, "category": cat, "claims": cats.get(cat, 0)} for t, cat in orchestrator.DEFAULT_COVERAGE_TOPICS.items()]
    objections = []
    box = orchestrator._toolbox(ws, product_id)
    from agents.offline import stems
    for o in (product.get("buyer_persona") or {}).get("objections", []):
        hits = box.search_registry(o, limit=1)
        ok = bool(hits) and len(stems(o) & stems(hits[0]["text"])) / max(1, len(stems(o))) >= 0.5
        if not ok:
            objections.append(o)
    for item in ws.list("content", product_id):
        for r in item["rounds"][-1:]:
            ref = f"{r['checks_ref']}/synthetic-buyer.json"
            if ws.has_object(ref):
                objections += [o["text"] for o in ws.get_json(ref)["objections"] if not o["answerable_by_docs"]]
    return {
        "proof_points_without_claims": [{"theme": t["name"], "proof": p["text"]} for t in pack.get("value_themes", [])
                                        for p in t["proof_points"] if p["status"] == "needs-claim"],
        "topics_without_docs": [c for c in coverage if c["claims"] == 0],
        "coverage": coverage,
        "claims_needing_review": sum(1 for c in claims.values() if c["status"] == "needs-review"),
        "review_queue": [{"category": g["category"], "theme": g["theme"], "count": len(g["claims"])}
                         for g in registry.review_queue(claims)],
        "doc_corrections": registry.correction_notes(claims, rulings, sources),
        "open_conflicts": [c for c in ws.list("conflict", product_id) if c["status"] == "open"],
        "unanswerable_objections": sorted(set(objections)),
    }


def quality_dashboard(ws, product_id=None):
    items = ws.list("content", product_id) if product_id else ws.list("content")
    reports, blocks = [], {}
    for it in items:
        for r in it["rounds"]:
            if r.get("report_ref") and ws.has_object(r["report_ref"]):
                rep = ws.get_json(r["report_ref"])
                reports.append(rep)
                for f in rep["flags"]:
                    if f["severity"] == "block":
                        blocks[f.get("reason") or "page"] = blocks.get(f.get("reason") or "page", 0) + 1
    approved = [i for i in items if i.get("live_version")]
    overrides = [i for i in approved if i["live_version"]["status"] == "approved-override"]
    evals = sorted([e for e in ws.list("eval") if not product_id or e.get("product_id") == product_id],
                   key=lambda e: e["computed_at"])
    return {"items": len(items), "approved": len(approved), "override_rate": round(len(overrides) / len(approved), 3) if approved else None,
            "avg_rounds": round(sum(len(i["rounds"]) for i in items) / len(items), 2) if items else None,
            "approved_within_auto_cap": sum(1 for i in approved if i["live_version"]["round"] <= 1 + orchestrator.AUTO_REVISION_CAP
                                            and i["live_version"]["status"] == "approved"),
            "blocks_by_reason": dict(sorted(blocks.items(), key=lambda kv: -kv[1])),
            "style_scores": [{"at": r["generated_at"], "score": r["checker_scores"].get("style-checker")} for r in reports
                             if r["checker_scores"].get("style-checker") is not None],
            "evals": evals[-10:]}


def cost_dashboard(ws):
    runs = ws.list("run")
    by_product, by_kind = {}, {}
    for r in runs:
        by_product[r["product_id"]] = by_product.get(r["product_id"], 0) + r["tokens_used"]
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + r["tokens_used"]
    s = ws.settings
    return {"workspace_tokens": sum(by_product.values()), "workspace_budget": s.get("workspace_budget_tokens"),
            "run_budget": s.get("run_budget_tokens"), "by_product": by_product, "by_kind": by_kind,
            "runs": [{"id": r["id"], "product_id": r["product_id"], "kind": r["kind"], "status": r["status"],
                      "tokens": r["tokens_used"], "created_at": r["created_at"]}
                     for r in sorted(runs, key=lambda r: r["created_at"], reverse=True)[:50]]}
