"""Load an invented fixture product (fixtures/products/<slug>) into a workspace. Never real data."""
import json
import os
from pathlib import Path

from services import actions

ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "products"


def available():
    return sorted(p.name for p in ROOT.iterdir() if (p / "product.json").exists())


def load(ws, actor, slug, evidence=True):
    d = ROOT / slug
    meta = json.loads((d / "product.json").read_text())
    p = ws.get("product", slug) or actions.create_product(
        ws, actor, meta["name"], meta["claim_prefix"], slug=slug, company=meta.get("company", ""),
        content_types=meta.get("content_types"), high_risk_categories=meta.get("high_risk_categories"),
        buyer_persona=meta.get("buyer_persona"))
    existing = {x["id"] for x in ws.list("decision", slug)}
    for dec in json.loads((d / "decisions.json").read_text()):
        if dec["id"] not in existing:
            actions.save_decision(ws, actor, slug, dec["text"], decision_id=dec["id"])
    added = []
    for stype in ("truth", "style", "positioning", "evidence"):
        sd = d / "sources" / stype
        if not sd.exists() or (stype == "evidence" and not (evidence and ws.settings.get("evidence_enabled"))):
            continue
        for f in sorted(sd.iterdir()):
            if f.is_file():
                src, changed, _ = actions.add_source(ws, actor, slug, stype, f.name, f.read_bytes())
                added.append((src["id"], changed))
    return p, added
