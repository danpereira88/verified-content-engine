"""Run evals against a workspace product or a throwaway fixture workspace.

  bin/vce eval gate --fixture lumen --fixture shiftwell     # release check on fixture products (fresh temp workspace)
  bin/vce eval style --fixture lumen
Results go to evals/runs/<timestamp>-<kind>.json (fixture runs only) and the workspace's eval records.
"""
import json
import os
import tempfile
from pathlib import Path

from evals.gate_eval import run_gate_eval
from packages.util import now_iso, new_id

RUNS = Path(__file__).resolve().parent / "runs"
GOLDEN = Path(__file__).resolve().parent / "gate" / "golden"


def run_gate_for_workspace(ws, product_id, provider):
    product = ws.product(product_id)
    golden_p = GOLDEN / f"{product_id}.json"
    golden = json.loads(golden_p.read_text()) if golden_p.exists() else None
    res = run_gate_eval(ws.claims(product_id), product, ws.list("conflict", product_id), provider, golden)
    rec = dict(res, id=new_id("eval"), product_id=product_id, kind="gate", provider=getattr(provider, "name", "?"))
    ws.put("eval", rec, product_id=product_id)
    return rec


def fixture_workspace(slugs, confirm_all=False):
    """Fresh temporary workspace with fixture products ingested (offline provider for extraction)."""
    from agents.runtime import OfflineProvider
    from services import fixtures, orchestrator
    from services.store import Store
    os.environ.setdefault("VCE_ALLOW_PLAINTEXT_EVIDENCE", "1")
    store = Store(tempfile.mkdtemp(prefix="vce-eval-"))
    store.create_workspace("eval", "ws-eval", {"evidence_enabled": True})
    ws = store.workspace("ws-eval")
    actor = {"email": "eval@example.test", "roles": ["admin", "editor", "reviewer", "sme", "compliance"]}
    for s in slugs:
        fixtures.load(ws, actor, s)
        orchestrator.ingest_product(ws, s, provider=OfflineProvider())
    return ws, actor


def main(kind, slugs, provider):
    ws, _ = fixture_workspace(slugs)
    RUNS.mkdir(exist_ok=True)
    out = {"kind": kind, "provider": getattr(provider, "name", "?"), "computed_at": now_iso(), "products": {}}
    for s in slugs:
        if kind == "gate":
            r = run_gate_for_workspace(ws, s, provider)
            out["products"][s] = {k: r[k] for k in ("metrics", "counts", "per_label", "passed", "all_passed", "skipped_golden", "misses", "tokens")}
        else:
            st = ws.get("kb-status", s) or {}
            out["products"][s] = st.get("calibration")
    if kind == "gate":
        out["all_passed"] = all(p["all_passed"] for p in out["products"].values())
    import shutil
    shutil.rmtree(ws._s.root, ignore_errors=True)  # throwaway fixture workspace
    path = RUNS / f"{out['computed_at'].replace(':', '')}-{kind}-{out['provider']}.json"
    path.write_text(json.dumps(out, indent=2))
    return out, path
