"""Retention: one policy for drafts, run logs and model inputs of unapproved rounds.

Dry-run by default. Approved live versions, claims, rulings, sources and the audit log are kept;
deleting those is a separate, explicit admin decision outside this tool.
"""
import datetime as dt
import shutil

from packages.util import now_iso


def purge(ws, apply=False):
    days = ws.settings.get("retention_days")
    if not days:
        return {"retention_days": None, "purged": [], "note": "No retention period set."}
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    purged = []
    for item in ws.list("content"):
        live_round = (item.get("live_version") or {}).get("round")
        for r in item["rounds"]:
            if r["created_at"] < cutoff and r["round"] != live_round and not r.get("purged"):
                purged.append({"item": item["id"], "round": r["round"]})
                if apply:
                    d = ws._path(item["product_id"], f"content/{item['id']}/r{r['round']}")
                    shutil.rmtree(d, ignore_errors=True)
                    r["purged"] = now_iso()
        if apply:
            ws.put("content", item)
    runs = [r["id"] for r in ws.list("run") if r["created_at"] < cutoff]
    if apply and (purged or runs):
        ws.audit("retention", "retention.purge", ws.workspace_id, f"{len(purged)} rounds, {len(runs)} run logs before {cutoff}")
        for rid in runs:
            ws.delete("run", rid)
    return {"retention_days": days, "cutoff": cutoff, "rounds": purged, "runs": runs, "applied": apply}
