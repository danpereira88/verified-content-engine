"""Orchestrator: runs ingestion and content pipelines as resumable step graphs.

Plain code, not a model. It dispatches agents, enforces budgets, the revision cap (2 automatic
rounds) and the retry policy (one retry per failed step, then the run fails loudly with context),
persists every step, and calls packages/gate and packages/registry for every decision.
"""
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agents.runtime import AgentError, Toolbox, provider_from_env, run_agent, writing_aid_flags
from packages import gate, registry
from packages.textstats import measure
from packages.util import new_id, now_iso, quote_hash, strip_tags, tokens, word_count
from packages.validate import ValidationError, check
from services import ingest

AUTO_REVISION_CAP = 2
MIN_STYLE_WORDS, MIN_STYLE_PIECES = 1500, 3
CONTENT_TYPE_DIR = Path(__file__).resolve().parent / "content_types"
DEFAULT_COVERAGE_TOPICS = {"pricing": "pricing", "security": "security", "compliance": "compliance",
                           "integrations": "integration", "deployment": "deployment", "limits": "limitation",
                           "availability": "availability", "metrics": "metric"}


class RunFailed(RuntimeError):
    def __init__(self, run, msg):
        self.run = run
        super().__init__(msg)


class BudgetExceeded(RuntimeError):
    pass


# ---------------- content types ----------------

def content_types(ws):
    out = {}
    for f in sorted(CONTENT_TYPE_DIR.glob("*.json")):
        t = json.loads(f.read_text())
        out[t["id"]] = t
    for t in ws.list("content-type"):
        out[t["id"]] = t
    return out


# ---------------- run bookkeeping ----------------

class Run:
    def __init__(self, ws, product_id, kind, brief_id=None, run=None, budget=None, progress=None):
        self.ws = ws
        self._lock = threading.RLock()
        self.progress = progress or (lambda *a: None)
        if run:
            self.rec = run
        else:
            s = ws.settings
            self.rec = {"id": new_id("run"), "workspace_id": ws.workspace_id, "product_id": product_id, "kind": kind,
                        "brief_id": brief_id, "status": "running", "steps": [], "tokens_used": 0,
                        "budget_tokens": budget if budget is not None else s.get("run_budget_tokens", 3_000_000),
                        "error": "", "created_at": now_iso(), "updated_at": now_iso()}
        self.rec["status"] = "running"
        self.save()

    @property
    def id(self):
        return self.rec["id"]

    def save(self):
        with self._lock:
            self.rec["updated_at"] = now_iso()
            self.ws.put("run", self.rec)

    def step(self, name):
        with self._lock:
            return self._step(name)

    def _step(self, name):
        for s in self.rec["steps"]:
            if s["name"] == name:
                return s
        s = {"name": name, "status": "pending", "attempts": 0, "tokens": 0, "error": "", "output_ref": ""}
        self.rec["steps"].append(s)
        return s

    def workspace_spend(self):
        return sum(r["tokens_used"] for r in self.ws.list("run"))

    def check_budget(self):
        if self.rec["tokens_used"] >= self.rec["budget_tokens"]:
            raise BudgetExceeded(f"run budget of {self.rec['budget_tokens']:,} tokens reached")
        wsb = self.ws.settings.get("workspace_budget_tokens")
        if wsb and self.workspace_spend() >= wsb:
            raise BudgetExceeded(f"workspace budget of {wsb:,} tokens reached")

    def do(self, name, fn, retries=1):
        """Run a step once (+1 retry). Completed steps are skipped on resume and return their stored output."""
        s = self.step(name)
        if s["status"] == "done" and s["output_ref"]:
            return self.ws.get_json(s["output_ref"]) if s["output_ref"].endswith(".json") else self.ws.get_text(s["output_ref"])
        self.check_budget()
        last = None
        for _ in range(retries + 1):
            s["status"], s["attempts"] = "running", s["attempts"] + 1
            self.save()
            self.progress(self.id, name, "running")
            try:
                out, tokens_used, ref = fn()
                s.update(status="done", tokens=s["tokens"] + tokens_used, output_ref=ref or "", error="")
                with self._lock:
                    self.rec["tokens_used"] += tokens_used
                self.save()
                self.progress(self.id, name, "done")
                return out
            except (AgentError, ValidationError, ValueError, KeyError) as e:
                last = e
                s["error"] = f"{type(e).__name__}: {str(e)[:500]}"
                self.save()
        s["status"] = "failed"
        self.save()
        raise RunFailed(self.rec, f"step '{name}' failed twice: {last}")

    def finish(self, status, error=""):
        self.rec["status"], self.rec["error"] = status, error
        self.save()
        self.progress(self.id, "run", status)


def _guarded(run, body):
    try:
        out = body()
        run.finish("succeeded")
        return out
    except BudgetExceeded as e:
        run.finish("budget-stopped", str(e))
        raise
    except RunFailed as e:
        run.finish("failed", str(e))
        raise
    except Exception as e:
        run.finish("failed", f"{type(e).__name__}: {e}")
        raise


def _toolbox(ws, product_id, artifacts=None, with_snapshots=False):
    claims = ws.claims(product_id)
    snaps = {}
    if with_snapshots:
        for s in ws.list("source", product_id):
            if s["type"] == "truth" and s["status"] == "active":
                snaps[s["id"]] = ingest.normalized(ws, s)["blocks"]
    return Toolbox(claims=claims, artifacts=artifacts or {}, snapshots=snaps)


def _decisions(ws, product_id):
    return sorted(ws.list("decision", product_id), key=lambda d: d["id"])


def _guardrails(ws, product_id):
    return [g for d in _decisions(ws, product_id) for g in d["derived_guardrails"]]


# ---------------- ingestion ----------------

def ingest_product(ws, product_id, provider=None, progress=None, resume_run=None):
    provider = provider or provider_from_env()
    product = ws.product(product_id)
    run = Run(ws, product_id, "ingest", run=resume_run, progress=progress)

    def body():
        sources = {s["id"]: s for s in ws.list("source", product_id)}
        active = [s for s in sources.values() if s["status"] == "active"]
        truth = [s for s in active if s["type"] == "truth"]
        style = [s for s in active if s["type"] == "style"]
        pos = [s for s in active if s["type"] == "positioning"]
        evid = [s for s in active if s["type"] == "evidence"] if ws.settings.get("evidence_enabled") else []
        box = _toolbox(ws, product_id)
        decisions = _decisions(ws, product_id)

        def extract_claims(src):
            ref = f"{product_id}/records/claims/{src['id']}/{src['sha256']}.json"
            if ws.has_object(ref):
                return ws.get_json(ref), 0, ref
            norm = ingest.normalized(ws, src)
            text = "\n".join(b["text"] for b in norm["blocks"])
            payload = {"source_id": src["id"], "source": {"id": src["id"], "title": src["title"], "kind": src["kind"]},
                       "blocks": norm["blocks"], "categories": list(registry_categories()),
                       "high_risk_categories": product["high_risk_categories"]}
            out, usage = run_agent("claims-extractor", payload, Toolbox(snapshots={src["id"]: norm["blocks"]}),
                                   provider, product, ctx={"snapshot_text": text})
            ws.put_json(product_id, ref.split("/", 1)[1], out)
            return out, usage.total, ref

        def claims_step(src):
            try:
                return run.do(f"claims-extractor:{src['id']}", lambda: extract_claims(src))
            except RunFailed:
                src["status"] = "extraction-failed"
                ws.put("source", src)
                return None

        def style_step():
            corpus_words = sum(s.get("words", 0) for s in style)
            if len(style) < MIN_STYLE_PIECES or corpus_words < MIN_STYLE_WORDS:
                return None
            texts, srcs = [], []
            for s in style:
                blocks = ingest.normalized(ws, s)["blocks"]
                srcs.append({"id": s["id"], "title": s["title"], "blocks": blocks})
                texts.append("\n\n".join(("# " + b["text"]) if b["heading_path"] and b["text"] == b["heading_path"][-1]
                                         else b["text"] for b in blocks))
            payload = {"product_id": product_id, "generated_at": now_iso(), "product": {"name": product["name"]},
                       "sources": srcs, "decisions": decisions, "measured": measure(texts),
                       "corpus": {"pieces": len(style), "words": corpus_words, "source_ids": [s["id"] for s in style]}}

            def f():
                out, usage = run_agent("style-extractor", payload, box, provider, product)
                out = apply_decisions_to_profile(out, decisions)
                ws.put("style-profile", out, id=product_id, product_id=product_id)
                return out, usage.total, ""
            return run.do("style-extractor", f)

        def evidence_step(src):
            def f():
                blocks = ingest.normalized(ws, src)["blocks"]
                out, usage = run_agent("evidence-extractor", {"source_id": src["id"], "blocks": blocks}, Toolbox(), provider, product)
                out = verify_evidence(out, blocks, product)
                ref = ws.put_json(product_id, f"records/evidence/{src['id']}/{src['sha256']}.json", out, schema="market-evidence")
                return out, usage.total, ref
            return run.do(f"evidence-extractor:{src['id']}", f)

        with ThreadPoolExecutor(max_workers=8) as pool:
            fut_claims = [pool.submit(claims_step, s) for s in truth]
            fut_style = pool.submit(style_step)
            fut_ev = [pool.submit(evidence_step, s) for s in evid]
            records = [f.result() for f in fut_claims]
            profile = fut_style.result()
            evidence = [f.result() for f in fut_ev]

        claims = rebuild_registry(ws, product_id, records=[r for r in records if r], evidence=evidence)

        def positioning_step():
            if not pos:
                return None
            srcs = [{"id": s["id"], "title": s["title"], "kind": s["kind"], "blocks": ingest.normalized(ws, s)["blocks"]} for s in pos]
            payload = {"product_id": product_id, "generated_at": now_iso(), "sources": srcs, "decisions": decisions}

            def f():
                b = _toolbox(ws, product_id)
                out, usage = run_agent("positioning-extractor", payload, b, provider, product,
                                       ctx={"decision_ids": {d["id"] for d in decisions}})
                out = relink_pack(out, ws.claims(product_id), decisions)
                ws.put("positioning-pack", out, id=product_id, product_id=product_id, decision_ids={d["id"] for d in decisions})
                return out, usage.total, ""
            return run.do("positioning-extractor", f)

        pack = positioning_step()
        cal = None
        if profile:
            cal = run.do("style-calibration", lambda: (calibrate_style(ws, product_id, profile), 0, ""))
        status = refresh_status(ws, product_id, rebuilt=True)
        return {"run_id": run.id, "claims": len(claims), "status": status, "calibration": cal,
                "failed_sources": [s["id"] for s in ws.list("source", product_id) if s["status"] == "extraction-failed"],
                "pack": bool(pack), "profile": bool(profile)}

    return _guarded(run, body)


def registry_categories():
    from packages.validate import load_schema
    return load_schema("common.schema.json")["$defs"]["category"]["enum"]


def latest_records(ws, product_id):
    """The extractor record for the current snapshot of every active truth source (cached by sha)."""
    out = []
    for s in ws.list("source", product_id):
        if s["type"] != "truth" or s["status"] != "active":
            continue
        ref = f"{product_id}/records/claims/{s['id']}/{s['sha256']}.json"
        if ws.has_object(ref):
            out.append(ws.get_json(ref))
    return out


def latest_evidence(ws, product_id):
    out = []
    for s in ws.list("source", product_id):
        if s["type"] == "evidence" and s["status"] == "active":
            ref = f"{product_id}/records/evidence/{s['id']}/{s['sha256']}.json"
            if ws.has_object(ref):
                out.append(ws.get_json(ref))
    return out


def rebuild_registry(ws, product_id, records=None, evidence=None):
    """registry.build + conflicts + re-flag. Deterministic; safe to run after any ruling."""
    product = ws.product(product_id)
    records = latest_records(ws, product_id) if records is None else records
    evidence = latest_evidence(ws, product_id) if evidence is None else [e for e in evidence if e]
    sources = {s["id"]: s for s in ws.list("source", product_id)}
    rulings = ws.list("ruling", product_id)
    conflicts = ws.list("conflict", product_id)
    claims, stats = registry.build(product, ws.claims(product_id), records, sources, rulings, conflicts, evidence)
    reg = {"product_id": product_id, "generated_at": now_iso(), "stats": stats, "claims": list(claims.values())}
    check("registry", reg, claim_prefix=product["claim_prefix"], high_risk_categories=product["high_risk_categories"])
    ws.put_many("claim", list(claims.values()), product_id=product_id)
    conflicts = registry.detect_conflicts(claims, sources, conflicts)
    ws.put_many("conflict", conflicts, product_id=product_id)
    # a conflict ruling may deprecate claims: rebuild once more so statuses reflect it
    if any(c["status"] == "resolved" for c in conflicts):
        claims, stats = registry.build(product, claims, records, sources, rulings, conflicts, evidence)
        ws.put_many("claim", list(claims.values()), product_id=product_id)
    for item in gate.reflag(ws.list("content", product_id), claims):
        ws.put("content", item)
        ws.audit("system", "content.reflagged", item["id"], "; ".join(r["reason"] for r in item["reflags"][-3:]))
    pack = ws.get("positioning-pack", product_id)
    if pack:
        pack = relink_pack(pack, claims, _decisions(ws, product_id))
        ws.put("positioning-pack", pack, id=product_id, product_id=product_id)
    return claims


def apply_decisions_to_profile(profile, decisions):
    """Banned terms and naming come from decisions verbatim, whatever the extractor produced."""
    p = json.loads(json.dumps(profile))
    banned, forbidden, derived = set(p["vocabulary"]["banned"]), set(p["naming"]["forbidden"]), []
    for d in decisions:
        for g in d["derived_guardrails"]:
            if g["type"] == "banned-term":
                banned |= set(g["terms"])
                derived.append({"decision_id": d["id"], "rule": g["rule"]})
            elif g["type"] == "naming":
                forbidden |= set(g["terms"][1:])
                derived.append({"decision_id": d["id"], "rule": g["rule"]})
    p["vocabulary"]["banned"] = sorted(banned)
    p["vocabulary"]["preferred"] = [w for w in p["vocabulary"]["preferred"] if w.lower() not in {b.lower() for b in banned}]
    p["naming"]["forbidden"] = sorted(forbidden)
    p["naming"]["variants_allowed"] = [v for v in p["naming"]["variants_allowed"] if v not in forbidden]
    seen = {(x["decision_id"], x["rule"]) for x in p["derived_from_decisions"]}
    p["derived_from_decisions"] += [x for x in derived if (x["decision_id"], x["rule"]) not in seen]
    issues = [i for i in p["consistency"]["issues"]]
    if p["naming"]["product_name"] in forbidden:
        issues.append("The product name is forbidden by a decision.")
    p["consistency"] = {"ok": not issues, "issues": issues}
    if issues:
        p["status"] = "draft"
    return p


def relink_pack(pack, claims, decisions):
    """Deterministic linking pass: proof points keep only verified claim IDs; guardrails match decisions."""
    p = json.loads(json.dumps(pack))
    for t in p["value_themes"]:
        for pp in t["proof_points"]:
            ids = [i for i in pp["claim_ids"] if (claims.get(i) or {}).get("status") == "verified"]
            pp["claim_ids"], pp["status"] = ids, "has-claim" if ids else "needs-claim"
    p["guardrails"] = [{"rule": g["rule"], "decision_id": d["id"], "decision_quote": d["text"]}
                       for d in decisions for g in d["derived_guardrails"]]
    return p


NAME_LIKE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")


def verify_evidence(out, blocks, product):
    """Keep only market-evidence claims whose counts reproduce; refuse output that names anyone."""
    rows = []
    for b in blocks:
        d = {}
        for part in b["text"].split(" | "):
            k, _, v = part.partition(":")
            d[k.strip()] = v.strip().lower()
        rows.append(d)
    allowed = {product["name"], product.get("company", "")}
    blob = json.dumps(out)
    names = [n for n in NAME_LIKE.findall(blob) if n not in allowed]
    if names:
        raise AgentError(f"evidence output contains name-like text {names[:3]}; discarded")
    keep = []
    for c in out["claims"]:
        field, _, value = c["query"].partition("=")
        n = sum(1 for r in rows if r.get(field.strip()) == value.strip().lower())
        if n == c["count"] and c["total"] == len(rows):
            keep.append(c)
    return dict(out, claims=keep)


def refresh_status(ws, product_id, rebuilt=False):
    """Knowledge-base status. A source is stale when its current snapshot differs from the one last built."""
    prev = ws.get("kb-status", product_id) or {}
    sources = ws.list("source", product_id)
    built = {s["id"]: s["sha256"] for s in sources if s["status"] == "active"} if rebuilt else prev.get("built_sha", {})
    stale = [] if rebuilt else sorted(
        [s["id"] for s in sources if s["status"] == "active" and built.get(s["id"]) != s["sha256"]] +
        [s["id"] for s in sources if s["status"] == "removed" and s["id"] in built])
    if not built:
        stale = []  # never built: the status is 'blocked' until the first build, not 'stale'
    st = gate.kb_status(sources, ws.claims(product_id), ws.get("style-profile", product_id),
                        ws.get("positioning-pack", product_id), stale)
    st["built_sha"] = built
    st["calibration"] = prev.get("calibration")
    st["staleness"] = None if rebuilt else prev.get("staleness")
    ws.put("kb-status", st, id=product_id, product_id=product_id)
    return st


def mark_stale(ws, product_id, source_ids):
    """Called when a source changes: compute which claims, content and conflicts it touches."""
    claims = ws.claims(product_id)
    new_texts = {}
    for sid in source_ids:
        s = ws.get("source", sid)
        new_texts[sid] = None if s["status"] == "removed" else ingest.snapshot_text(ws, s)
    report = gate.staleness(claims, new_texts, ws.list("content", product_id), ws.list("conflict", product_id))
    st = refresh_status(ws, product_id)
    st["staleness"] = report
    ws.put("kb-status", st, id=product_id, product_id=product_id)
    return report


# ---------------- style calibration ----------------

def calibrate_style(ws, product_id, profile):
    from evals.style_eval import calibrate
    texts = []
    for sid in profile["corpus"]["source_ids"]:
        s = ws.get("source", sid)
        if s:
            blocks = ingest.normalized(ws, s)["blocks"]
            texts.append("\n\n".join(("# " + b["text"]) if b["heading_path"] and b["text"] == b["heading_path"][-1]
                                     else b["text"] for b in blocks))
    result = calibrate(profile, texts)
    st = ws.get("kb-status", product_id) or {}
    st["calibration"] = result
    ws.put("kb-status", st, id=product_id, product_id=product_id)
    return result


# ---------------- content runs ----------------

def registry_slice(box, queries, must=(), limit=150):
    ids = list(dict.fromkeys(must))
    for q in queries:
        for h in box.search_registry(q, limit=25):
            if h["id"] not in ids:
                ids.append(h["id"])
    return [box.claims[i] for i in ids[:limit] if i in box.claims]


def _round_dir(item_id, n):
    return f"content/{item_id}/r{n}"


def content_run(ws, brief_id, provider=None, progress=None, resume_run=None):
    provider = provider or provider_from_env()
    brief = ws.get("brief", brief_id)
    if not brief:
        raise KeyError(brief_id)
    pid = brief["product_id"]
    product = ws.product(pid)
    status = refresh_status(ws, pid)
    if status["state"] == "blocked":
        raise RunFailed({"id": "-"}, "Knowledge base not ready: " + "; ".join(status["blockers"]))
    run = Run(ws, pid, "content", brief_id=brief_id, run=resume_run, progress=progress)
    item = ws.get("content", brief_id) or gate.new_content_item(brief)
    item["status"] = "running" if not item["live_version"] else item["status"]
    ws.put("content", item)

    def body():
        ct = content_types(ws)[brief["content_type"]]
        pack = ws.get("positioning-pack", pid)
        profile = ws.get("style-profile", pid)
        guards = _guardrails(ws, pid)
        box = _toolbox(ws, pid)
        verified = {i for i, c in box.claims.items() if c["status"] == "verified"}
        must = [i for t in (pack or {}).get("value_themes", []) for pp in t["proof_points"] for i in pp["claim_ids"]]
        slice_ = registry_slice(box, [brief["title"], brief["goal"], brief["audience"], brief["notes"]]
                                + [s["purpose"] for s in ct["sections"]], must)
        persona = product.get("buyer_persona") or {}

        def plan_step():
            payload = {"brief_id": brief_id, "brief": brief, "content_type": ct, "pack": pack, "guardrails": guards,
                       "claims": slice_, "persona_objections": persona.get("objections", [])}
            out, usage = run_agent("strategist", payload, box, provider, product, ctx={"verified_ids": verified})
            n = len(item["rounds"]) + 1
            ref = ws.put_json(pid, f"{_round_dir(brief_id, n)}/plan.json", out, schema="plan", verified_ids=verified)
            return out, usage.total, ref
        plan = run.do("strategist", plan_step)

        aid_flags = writing_aid_flags(["conversion-copywriter"], product, box.claims)
        writer_claims = registry_slice(box, [s["purpose"] for s in plan["sections"]],
                                       [i for s in plan["sections"] for i in s["claim_ids"]], limit=120)

        def write(revision=None, label="copywriter"):
            def f():
                payload = {"brief": brief, "plan": plan, "profile": profile, "content_type": ct, "pack": pack,
                           "claims": writer_claims, "guardrails": guards, "revision": revision,
                           "writing_aid_flags": aid_flags}
                out, usage = run_agent("copywriter", payload, box, provider, product)
                n = len(item["rounds"]) + 1
                ref = ws.put_object(pid, f"{_round_dir(brief_id, n)}/draft.md", out["draft_md"])
                ws.put_json(pid, f"{_round_dir(brief_id, n)}/draft-meta.json",
                            {k: out[k] for k in ("claim_map", "missing_claims", "writing_aid_flags")}, schema="draft-meta")
                return out["draft_md"], usage.total, ref
            return run.do(label, f)

        # Resumable loop: step names are tied to round numbers, and the automatic-revision count is
        # derived from archived rounds, so a resumed run continues exactly where it stopped.
        mine = [r for r in item["rounds"] if r.get("run_id") == run.id]
        if mine:
            md, report = ws.get_text(mine[-1]["draft_ref"]), ws.get_json(mine[-1]["report_ref"])
        else:
            n = len(item["rounds"]) + 1
            md, report = write(label=f"copywriter:r{n}"), None
            kind = "initial"
        while True:
            if report is None:
                n = len(item["rounds"]) + 1
                report = verify_round(ws, run, item, brief, product, plan, ct, md, n, kind, provider)
            item["auto_revisions_used"] = sum(1 for r in item["rounds"] if r["kind"] == "auto")
            ws.put("content", item)
            if not gate.needs_revision(report, item["auto_revisions_used"], AUTO_REVISION_CAP):
                break
            n = len(item["rounds"]) + 1
            md = write({"previous_draft": md, "flags": report["flags"], "instructions": None}, label=f"copywriter:r{n}")
            kind, report = "auto", None
        return {"run_id": run.id, "status": item["status"], "rounds": len(item["rounds"]), "report": report,
                "live": item["live_version"]}

    try:
        return _guarded(run, body)
    except Exception:
        item = ws.get("content", brief_id) or item
        if item["status"] == "running":
            item["status"] = "failed" if not item["live_version"] else item["live_version"]["status"]
            ws.put("content", item)
        raise


def checker_payloads(ws, product, brief, plan, ct, md, units, dh):
    pid = product["id"]
    box = _toolbox(ws, pid, with_snapshots=True)
    cited = {i for u in units for i in re.findall(r"\[\[([A-Z0-9]+-\d+)\]\]", u["text"])}
    related = set()
    for u in units:
        for h in box.search_registry(strip_tags(u["text"]), limit=3):
            related.add(h["id"])
    ver_claims = [box.claims[i] for i in sorted(cited | related) if i in box.claims]
    conflicts = [c for c in ws.list("conflict", pid) if set(c["claim_ids"]) & (cited | related)]
    profile = ws.get("style-profile", pid)
    threshold = product.get("style_threshold")
    pack = ws.get("positioning-pack", pid)
    return box, {
        "verifier": {"draft_hash": dh, "units": [{k: u[k] for k in ("index", "section", "kind", "text")} for u in units],
                     "claims": ver_claims, "high_risk_categories": product["high_risk_categories"], "conflicts": conflicts},
        "style-checker": {"draft_md": md, "profile": profile, "threshold": threshold} if profile else None,
        "best-practice-auditor": {"draft_md": md, "plan": plan, "pack": pack, "content_type": ct, "stage": brief["stage"],
                                  "product_name": product["name"]},
        "synthetic-buyer": {"draft_text": gate.finalize_preview(md), "persona": product.get("buyer_persona")}
        if product.get("buyer_persona") else None,
    }


def enabled_checkers(product, ws):
    c = product.get("checkers") or {}
    return {"style-checker": c.get("style", True) and bool(ws.get("style-profile", product["id"])),
            "best-practice-auditor": c.get("best_practice", True),
            "synthetic-buyer": c.get("synthetic_buyer", True) and bool(product.get("buyer_persona"))}


def verify_round(ws, run, item, brief, product, plan, ct, md, n, kind, provider, by="system", instructions=None,
                 quick=False):
    """Fan out the gate and checkers on one draft, combine deterministically, archive the round."""
    pid = product["id"]
    units = gate.parse_draft(md)
    dh = gate.draft_hash(md)
    box, payloads = checker_payloads(ws, product, brief, plan, ct, md, units, dh)
    enabled = {k: False for k in gate.CHECKERS} if quick else enabled_checkers(product, ws)
    rd = _round_dir(item["id"], n)
    draft_ref = ws.put_object(pid, f"{rd}/draft.md", md)

    def checker(role):
        def f():
            out, usage = run_agent(role, payloads[role], box, provider, product)
            ref = ws.put_json(pid, f"{rd}/checks/{role}.json", out)
            return out, usage.total, ref
        return f

    results = {}

    def go(role):
        try:
            return role, run.do(f"{role}:r{n}", checker(role))
        except RunFailed:
            if role == "verifier":
                raise
            return role, None

    roles = ["verifier"] + [r for r in gate.CHECKERS if enabled.get(r) and payloads.get(r)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for role, out in pool.map(go, roles):
            results[role] = out
    report = recombine(ws, item, product, md, units, results.get("verifier"),
                       {k: results.get(k) for k in gate.CHECKERS}, enabled, run.id, n, kind)
    report_ref = ws.put_json(pid, f"{rd}/report.json", report, schema="verification-report")
    final_ref = ""
    if report["status"] in gate.APPROVED:
        final_ref = ws.put_object(pid, f"{rd}/final.md", gate.finalize(md, report))
    entry = {"round": n, "kind": kind, "draft_ref": draft_ref, "report_ref": report_ref, "checks_ref": f"{pid}/{rd}/checks",
             "status": report["status"], "created_at": now_iso(), "by": by, "run_id": run.id}
    if instructions:
        entry["instructions"] = instructions
    if not quick:
        had_live = bool(item["live_version"])
        gate.apply_result(item, entry, report, final_ref, gate.cited_ids(md))
        if had_live and report["status"] not in gate.APPROVED:
            ws.audit(by, "content.rollback", item["id"], f"round {n} was {report['status']}; approved round "
                     f"{item['live_version']['round']} stays live")
        ws.put("content", item)
    return report


def recombine(ws, item, product, md, units, verdicts, checker_reports, enabled, run_id, n, kind):
    claims = ws.claims(product["id"])
    report, _ = gate.combine(run_id=run_id, round_no=n, round_kind=kind, md=md, units=units, verdicts=verdicts,
                             claims=claims, high_risk=set(product["high_risk_categories"]),
                             checker_reports=checker_reports, enabled=enabled,
                             auto_revisions_used=item["auto_revisions_used"], override=item.get("override"),
                             positioning_marks=item.get("positioning_marks", []))
    return report


# ---------------- human-review actions (called by the API on behalf of an authenticated person) ----------------

def latest_round(ws, item):
    if not item["rounds"]:
        raise KeyError("no rounds yet")
    r = item["rounds"][-1]
    return r, ws.get_text(r["draft_ref"]), ws.get_json(r["report_ref"])


def _ctx(ws, item):
    brief = ws.get("brief", item["brief_id"])
    product = ws.product(item["product_id"])
    ct = content_types(ws)[brief["content_type"]]
    plan_ref = next((s["output_ref"] for r in ws.list("run", item["product_id"]) if r.get("brief_id") == item["brief_id"]
                     for s in r["steps"] if s["name"] == "strategist" and s["status"] == "done"), None)
    plan = ws.get_json(plan_ref) if plan_ref else {"brief_id": brief["id"], "framework": "-", "angle": "", "persona": "",
                                                   "stage": brief["stage"], "sections": [], "proof_gaps": [],
                                                   "mandated_wording_notes": [], "style_notes": []}
    return brief, product, ct, plan


def human_edit(ws, item_id, new_md, by, provider=None):
    item = ws.get("content", item_id)
    brief, product, ct, plan = _ctx(ws, item)
    run = Run(ws, item["product_id"], "content", brief_id=item_id)
    item["human_rounds"] += 1
    rep = _guarded(run, lambda: verify_round(ws, run, item, brief, product, plan, ct, new_md, len(item["rounds"]) + 1,
                                             "edit", provider or provider_from_env(), by=by))
    ws.audit(by, "content.edit", item_id, f"round {len(item['rounds'])}: {rep['status']}")
    return rep


def human_directed_revision(ws, item_id, instructions, by, provider=None, progress=None):
    if not instructions.strip():
        raise ValueError("instructions are required")
    provider = provider or provider_from_env()
    item = ws.get("content", item_id)
    brief, product, ct, plan = _ctx(ws, item)
    _, md, report = latest_round(ws, item)
    run = Run(ws, item["product_id"], "content", brief_id=item_id, progress=progress)

    def body():
        box = _toolbox(ws, item["product_id"])
        payload = {"brief": brief, "plan": plan, "profile": ws.get("style-profile", item["product_id"]), "content_type": ct,
                   "pack": ws.get("positioning-pack", item["product_id"]),
                   "claims": registry_slice(box, [instructions], gate.cited_ids(md)), "guardrails": _guardrails(ws, item["product_id"]),
                   "revision": {"previous_draft": md, "flags": report["flags"], "instructions": instructions}}
        new_md = run.do("copywriter:human-directed", lambda: _write_md(payload, box, provider, product))
        item["human_rounds"] += 1  # human-directed rounds never count toward the automatic cap
        return verify_round(ws, run, item, brief, product, plan, ct, new_md, len(item["rounds"]) + 1, "human-directed",
                            provider, by=by, instructions=instructions)
    rep = _guarded(run, body)
    ws.audit(by, "content.direct-revision", item_id, instructions[:500])
    return rep


def _write_md(payload, box, provider, product):
    out, usage = run_agent("copywriter", payload, box, provider, product)
    return out["draft_md"], usage.total, ""


def override(ws, item_id, reason, by):
    if not reason or not reason.strip():
        raise ValueError("an override needs a written reason")
    item = ws.get("content", item_id)
    r, md, report = latest_round(ws, item)
    if report["status"] in gate.APPROVED:
        raise ValueError("this round is already approved")
    item["override"] = {"by": by, "at": now_iso(), "reason": reason.strip(), "draft_hash": gate.draft_hash(md)}
    new = dict(report, status="approved-override", override={k: item["override"][k] for k in ("by", "at", "reason")},
               generated_at=now_iso())
    check("verification-report", new)
    pid = item["product_id"]
    rd = r["report_ref"].split("/", 1)[1].rsplit("/", 1)[0]
    ref = ws.put_json(pid, f"{rd}/report.json", new)
    final_ref = ws.put_object(pid, f"{rd}/final.md", gate.finalize(md, new))
    item["rounds"][-1]["status"] = "approved-override"
    item["live_version"] = {"round": r["round"], "status": "approved-override", "final_ref": final_ref, "report_ref": ref,
                            "cited_ids": gate.cited_ids(md), "approved_at": now_iso()}
    item["status"], item["review_state"] = "approved-override", "closed"
    ws.put("content", item)
    ws.audit(by, "content.override", item_id, reason.strip())
    return new


def reject(ws, item_id, by, reason=""):
    item = ws.get("content", item_id)
    if item["live_version"]:
        raise ValueError("an approved version is live; reject the open round by leaving it, or retire the item")
    item["status"], item["review_state"] = "rejected", "closed"
    ws.put("content", item)
    ws.audit(by, "content.reject", item_id, reason)
    return item


def mark_positioning(ws, item_id, sentence, by):
    """A reviewer marks one line as positioning (logged). Re-combines the latest round from stored checks."""
    item = ws.get("content", item_id)
    item["positioning_marks"].append({"sentence": sentence, "by": by, "at": now_iso()})
    r, md, old = latest_round(ws, item)
    product = ws.product(item["product_id"])
    units = gate.parse_draft(md)
    checks = r["checks_ref"]

    def load(role):
        ref = f"{checks}/{role}.json"
        return ws.get_json(ref) if ws.has_object(ref) else None
    enabled = enabled_checkers(product, ws)
    report = recombine(ws, item, product, md, units, load("verifier"), {k: load(k) for k in gate.CHECKERS}, enabled,
                       old["run_id"], r["round"], r["kind"])
    pid = item["product_id"]
    rd = r["report_ref"].split("/", 1)[1].rsplit("/", 1)[0]
    ws.put_json(pid, f"{rd}/report.json", report, schema="verification-report")
    item["rounds"].pop()
    final_ref = ws.put_object(pid, f"{rd}/final.md", gate.finalize(md, report)) if report["status"] in gate.APPROVED else ""
    gate.apply_result(item, r, report, final_ref, gate.cited_ids(md))
    ws.put("content", item)
    ws.audit(by, "content.mark-positioning", item_id, sentence[:300])
    return report


def quick_check(ws, product_id, md, provider=None):
    """Gate-only check of supplied copy. No checkers, no content item, no final copy."""
    provider = provider or provider_from_env()
    product = ws.product(product_id)
    run = Run(ws, product_id, "quick-check")
    fake = gate.new_content_item({"id": run.id.replace("run-", "qc-"), "product_id": product_id})
    brief = {"stage": "product-aware"}

    def body():
        units = gate.parse_draft(md)
        dh = gate.draft_hash(md)
        box, payloads = checker_payloads(ws, product, brief, {}, {"id": "-", "sections": [], "length_words": [0, 0],
                                                                  "name": "-"}, md, units, dh)
        verdicts = run.do("verifier", lambda: (lambda o: (o[0], o[1].total, ""))(
            run_agent("verifier", payloads["verifier"], box, provider, product)))
        rep = recombine(ws, fake, product, md, units, verdicts, {}, {k: False for k in gate.CHECKERS}, run.id, 1, "initial")
        return {"report": rep, "verdicts": gate.enforce(units, verdicts, ws.claims(product_id),
                                                        set(product["high_risk_categories"]))}
    return _guarded(run, body)


def resume(ws, run_id, provider=None, progress=None):
    """Resume a failed or budget-stopped run from its last completed step."""
    run = ws.get("run", run_id)
    if not run:
        raise KeyError(run_id)
    if run["status"] not in ("failed", "budget-stopped"):
        raise ValueError(f"run is {run['status']}; only failed or budget-stopped runs resume")
    for s_ in run["steps"]:
        if s_["status"] in ("failed", "running"):
            s_["status"], s_["attempts"] = "pending", 0
    if run["kind"] == "ingest":
        return ingest_product(ws, run["product_id"], provider, progress, resume_run=run)
    if run["kind"] == "content":
        return content_run(ws, run["brief_id"], provider, progress, resume_run=run)
    raise ValueError("quick checks are not resumable; run them again")


def estimate_tokens(ws, product_id, kind="content"):
    """Rough pre-run estimate (shown before any run more expensive than a quick check)."""
    claims = ws.claims(product_id)
    verified = sum(1 for c in claims.values() if c["status"] == "verified")
    per_claim = 60
    if kind == "eval":
        return 2 * (40 * 120 + 20_000)
    if kind == "quick-check":
        return 15_000 + min(verified, 150) * per_claim
    if kind == "ingest":
        words = sum(s.get("words", 0) for s in ws.list("source", product_id) if s["status"] == "active")
        return int(words * 1.4 * 3)
    slice_ = min(verified, 150) * per_claim
    per_round = 4 * (slice_ + 6_000) + 30_000
    return int(slice_ * 2 + 40_000 + per_round * (1 + AUTO_REVISION_CAP))
