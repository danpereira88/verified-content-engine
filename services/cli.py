"""Command line for the Verified Content Engine.

  bin/vce init --workspace "Acme marketing" --email you@acme.test        # first admin (prompts for a password)
  bin/vce serve [--port 8780]                                             # web UI + API on 127.0.0.1
  bin/vce load-fixture lumen [--ingest]                                   # invented demo product
  bin/vce ingest <product>
  bin/vce run-brief <brief-id>
  bin/vce resume <run-id>                                                 # continue a failed or budget-stopped run
  bin/vce eval gate --fixture lumen --fixture shiftwell                      # release check
  bin/vce eval style --fixture lumen
  bin/vce validate                                                        # schema + rule check of every stored artifact
  bin/vce retention [--apply]                                             # purge content/run data past retention
Environment: VCE_DATA_DIR (default ~/.vce/data), VCE_PROVIDER (offline | anthropic), ANTHROPIC_API_KEY.
"""
import argparse
import getpass
import json
import os
import sys

from services.store import Store


def _ws(store, ws_id=None):
    wss = store.list_workspaces()
    if not wss:
        sys.exit("No workspace yet: run `bin/vce init` first.")
    w = next((w for w in wss if w["id"] == ws_id), wss[0]) if ws_id else wss[0]
    return store.workspace(w["id"])


SYSTEM_ACTOR = {"email": "cli", "roles": ["admin", "editor", "reviewer", "sme", "compliance"]}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="vce", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir")
    ap.add_argument("--workspace")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("--workspace-name", "--workspace", dest="wname", required=True)
    p.add_argument("--email", required=True); p.add_argument("--password"); p.add_argument("--evidence", action="store_true")
    p = sub.add_parser("serve"); p.add_argument("--port", type=int, default=8780); p.add_argument("--host", default="127.0.0.1")
    p = sub.add_parser("load-fixture"); p.add_argument("slug"); p.add_argument("--ingest", action="store_true")
    p = sub.add_parser("ingest"); p.add_argument("product")
    p = sub.add_parser("run-brief"); p.add_argument("brief")
    p = sub.add_parser("resume"); p.add_argument("run_id")
    p = sub.add_parser("eval"); p.add_argument("kind", choices=["gate", "style"]); p.add_argument("--fixture", action="append", required=True)
    sub.add_parser("validate")
    p = sub.add_parser("retention"); p.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    if a.data_dir:
        os.environ["VCE_DATA_DIR"] = a.data_dir

    if a.cmd == "eval":
        from agents.runtime import provider_from_env
        from evals.cli import main as eval_main
        out, path = eval_main(a.kind, a.fixture, provider_from_env())
        for s, r in out["products"].items():
            print(f"{s}: " + json.dumps(r.get("metrics") if a.kind == "gate" else r))
            if a.kind == "gate":
                print("   passed:", r["passed"], "| per label:", json.dumps(r["per_label"]))
        if a.kind == "gate":
            print("ALL TARGETS MET" if out["all_passed"] else "TARGETS NOT MET", "->", path)
        return 0 if a.kind != "gate" or out["all_passed"] else 1

    store = Store()
    if a.cmd == "init":
        from services.api import create_user, set_member, user_by_email
        ws = store.create_workspace(a.wname, settings={"evidence_enabled": a.evidence})
        pw = a.password or getpass.getpass("Password (10+ chars): ")
        u = user_by_email(store, a.email)
        uid = u["id"] if u else create_user(store, a.email, pw)
        set_member(store, ws["id"], uid, ["admin", "editor", "reviewer", "sme", "compliance"])
        print(f"Workspace {ws['id']} created; {a.email} is admin. Data: {store.root}")
        return 0
    if a.cmd == "serve":
        from services.api import serve
        serve(store, a.host, a.port)
        return 0
    ws = _ws(store, a.workspace)
    if a.cmd == "load-fixture":
        from services import fixtures, orchestrator
        p, added = fixtures.load(ws, SYSTEM_ACTOR, a.slug)
        print(f"Loaded {p['name']} ({len(added)} sources) into {ws.workspace_id}")
        if a.ingest:
            print(json.dumps({k: v for k, v in orchestrator.ingest_product(ws, a.slug).items() if k != "status"}, default=str))
        return 0
    if a.cmd == "ingest":
        from services import orchestrator
        res = orchestrator.ingest_product(ws, a.product)
        print(json.dumps(res, indent=2, default=str))
        return 0
    if a.cmd == "run-brief":
        from services import orchestrator
        res = orchestrator.content_run(ws, a.brief)
        print(json.dumps({k: res[k] for k in ("run_id", "status", "rounds")}, indent=2))
        return 0
    if a.cmd == "resume":
        from services import orchestrator
        res = orchestrator.resume(ws, a.run_id)
        print(json.dumps({k: v for k, v in res.items() if k in ("run_id", "status", "rounds", "claims")}, indent=2, default=str))
        return 0
    if a.cmd == "validate":
        from packages.validate import validate
        from services.store import KINDS
        bad = 0
        for kind, schema in KINDS.items():
            if not schema:
                continue
            for obj in ws.list(kind):
                errs = validate(schema, obj)
                if errs:
                    bad += 1
                    print(f"{kind} {obj.get('id')}: {errs[:3]}")
        print("0 errors" if not bad else f"{bad} invalid artifact(s)")
        return 1 if bad else 0
    if a.cmd == "retention":
        from services.retention import purge
        res = purge(ws, apply=a.apply)
        print(json.dumps(res, indent=2))
        return 0


if __name__ == "__main__":
    sys.exit(main())
