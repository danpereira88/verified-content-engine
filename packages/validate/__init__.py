"""Schema + rule validation. Run before any artifact is saved; an invalid artifact is an error.

`validate(name, obj)` returns a list of error strings ([] means valid).
`check(name, obj)` raises ValidationError with every error.
The schema engine is a small, dependency-free subset of JSON Schema that covers what
packages/schemas uses: type, enum, const, pattern, min/maxLength, minimum/maximum,
properties, required, additionalProperties, items, min/maxItems, anyOf, $ref.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

from packages.util import norm_ws, word_count

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"
QUOTE_MAX_WORDS = 60


class ValidationError(ValueError):
    def __init__(self, name, errors):
        self.name, self.errors = name, errors
        super().__init__(f"{name}: " + "; ".join(errors[:10]) + (f" (+{len(errors) - 10} more)" if len(errors) > 10 else ""))


@lru_cache(maxsize=None)
def load_schema(file_name):
    return json.loads((SCHEMA_DIR / file_name).read_text())


def schema_names():
    return sorted(p.name[: -len(".schema.json")] for p in SCHEMA_DIR.glob("*.schema.json"))


_TYPES = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "null": lambda v: v is None,
}


def _resolve(ref, base_file):
    file_part, _, frag = ref.partition("#")
    file_name = file_part or base_file
    node = load_schema(file_name)
    for part in [p for p in frag.split("/") if p]:
        node = node[part]
    return node, file_name


def _walk(schema, value, path, base_file, errors):
    if "$ref" in schema:
        target, f = _resolve(schema["$ref"], base_file)
        _walk(target, value, path, f, errors)
        return
    if "anyOf" in schema:
        if not any(not _collect(s, value, path, base_file) for s in schema["anyOf"]):
            errors.append(f"{path or '$'}: does not match any allowed shape")
        return
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_TYPES[x](value) for x in types):
            errors.append(f"{path or '$'}: expected {'/'.join(types)}, got {type(value).__name__}")
            return
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path or '$'}: must be {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path or '$'}: {value!r} not one of {schema['enum']}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path or '$'}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path or '$'}: longer than {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path or '$'}: {value!r} does not match {schema['pattern']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path or '$'}: below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path or '$'}: above {schema['maximum']}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for r in schema.get("required", []):
            if r not in value:
                errors.append(f"{path or '$'}: missing required '{r}'")
        addl = schema.get("additionalProperties", True)
        for k, v in value.items():
            if k in props:
                _walk(props[k], v, f"{path}.{k}", base_file, errors)
            elif addl is False:
                errors.append(f"{path or '$'}: unexpected property '{k}'")
            elif isinstance(addl, dict):
                _walk(addl, v, f"{path}.{k}", base_file, errors)
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path or '$'}: needs at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path or '$'}: at most {schema['maxItems']} items")
        if "items" in schema:
            for i, v in enumerate(value):
                _walk(schema["items"], v, f"{path}[{i}]", base_file, errors)


def _collect(schema, value, path, base_file):
    errs = []
    _walk(schema, value, path, base_file, errs)
    return errs


def validate_schema(name, obj):
    f = f"{name}.schema.json"
    return _collect(load_schema(f), obj, "", f)


# ---------- rules a schema can't express ----------

def _rules_claims_record(obj, ctx):
    errs = []
    snapshot = ctx.get("snapshot_text")
    norm_snap = norm_ws(snapshot).lower() if snapshot is not None else None
    for i, c in enumerate(obj.get("claims", [])):
        if word_count(c["quote"]) >= QUOTE_MAX_WORDS:
            errs.append(f"claims[{i}]: quote must be under {QUOTE_MAX_WORDS} words")
        if norm_snap is not None and norm_ws(c["quote"]).lower() not in norm_snap:
            errs.append(f"claims[{i}]: quote not found verbatim in snapshot: {c['quote'][:80]!r}")
    return errs


def _rules_claim(obj, ctx):
    errs = []
    prefix = ctx.get("claim_prefix")
    if prefix and not obj["id"].startswith(prefix + "-"):
        errs.append(f"id {obj['id']} does not use product prefix {prefix}")
    if word_count(obj["quote"]) >= QUOTE_MAX_WORDS:
        errs.append(f"{obj['id']}: quote must be under {QUOTE_MAX_WORDS} words")
    hr = set(ctx.get("high_risk_categories") or [])
    ud = obj.get("user_decision")
    if obj["status"] == "verified" and (obj["category"] in hr or obj["confidence"] == "low"):
        if not ud or ud.get("kind") not in ("confirmed", "deprioritized"):
            errs.append(f"{obj['id']}: high-risk or low-confidence claims can only be verified by a human confirmation")
    if obj["category"] == "market-evidence" and obj.get("count") is None:
        errs.append(f"{obj['id']}: market-evidence claims need a reproducible count")
    return errs


def _rules_registry(obj, ctx):
    errs, seen = [], set()
    for c in obj["claims"]:
        if c["id"] in seen:
            errs.append(f"duplicate claim id {c['id']}")
        seen.add(c["id"])
        errs += _rules_claim(c, ctx)
    return errs


def _rules_style_profile(obj, ctx):
    errs = []
    n = obj["naming"]
    if n["product_name"] in n["forbidden"]:
        errs.append("naming.product_name is also listed as forbidden")
    overlap = set(map(str.lower, n["variants_allowed"])) & set(map(str.lower, n["forbidden"]))
    if overlap:
        errs.append(f"naming variants both allowed and forbidden: {sorted(overlap)}")
    banned = set(map(str.lower, obj["vocabulary"]["banned"]))
    pref = banned & set(map(str.lower, obj["vocabulary"]["preferred"]))
    if pref:
        errs.append(f"vocabulary both preferred and banned: {sorted(pref)}")
    if obj["status"] == "active" and not obj["consistency"]["ok"]:
        errs.append("an inconsistent profile cannot be active")
    total = sum(r["weight"] for r in obj["rubric"])
    if obj["rubric"] and abs(total - 1.0) > 0.01:
        errs.append(f"rubric weights must sum to 1.0 (got {total:.2f})")
    return errs


def _rules_positioning_pack(obj, ctx):
    errs = []
    decision_ids = ctx.get("decision_ids")
    for g in obj["guardrails"]:
        if decision_ids is not None and g["decision_id"] not in decision_ids:
            errs.append(f"guardrail '{g['rule'][:60]}' cites unknown decision {g['decision_id']}")
    for t in obj["value_themes"]:
        for p in t["proof_points"]:
            if p["status"] == "has-claim" and not p["claim_ids"]:
                errs.append(f"proof point '{p['text'][:60]}' is has-claim with no claim_ids")
            if p["status"] == "needs-claim" and p["claim_ids"]:
                errs.append(f"proof point '{p['text'][:60]}' is needs-claim but lists claim_ids")
    return errs


def _rules_decision(obj, ctx):
    return [f"guardrail '{g['rule'][:60]}' cites {g['decision_id']}, not {obj['id']}"
            for g in obj["derived_guardrails"] if g["decision_id"] != obj["id"]]


def _rules_plan(obj, ctx):
    verified = ctx.get("verified_ids")
    if verified is None:
        return []
    return [f"section {s['id']} plans around non-verified claim {cid}"
            for s in obj["sections"] for cid in s["claim_ids"] if cid not in verified]


def _rules_verification_report(obj, ctx):
    errs = []
    if obj["status"] == "approved-override" and not obj.get("override"):
        errs.append("approved-override requires an override record")
    if obj["status"] == "approved" and obj["block_count"]:
        errs.append("approved with blocks")
    if obj.get("override") and not obj["override"]["reason"].strip():
        errs.append("override needs a written reason")
    return errs


def _rules_market_evidence(obj, ctx):
    errs = []
    for i, c in enumerate(obj["claims"]):
        if c["count"] > c["total"]:
            errs.append(f"claims[{i}]: count exceeds total")
    return errs


RULES = {
    "claims-record": _rules_claims_record, "claim": _rules_claim, "registry": _rules_registry,
    "style-profile": _rules_style_profile, "positioning-pack": _rules_positioning_pack,
    "decision": _rules_decision, "plan": _rules_plan, "verification-report": _rules_verification_report,
    "market-evidence": _rules_market_evidence,
}


def validate(name, obj, **ctx):
    errs = validate_schema(name, obj)
    if errs:
        return errs
    rule = RULES.get(name)
    return rule(obj, ctx) if rule else []


def check(name, obj, **ctx):
    errs = validate(name, obj, **ctx)
    if errs:
        raise ValidationError(name, errs)
    return obj
