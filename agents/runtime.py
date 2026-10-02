"""Agent runtime: load a role definition, give it only its allowlisted tools, validate its output.

Providers:
- `anthropic`: Claude via the Messages API with a tool-use loop (stdlib HTTP; key from ANTHROPIC_API_KEY).
- `offline`: deterministic baseline implementations in agents/offline.py. No model calls, no network.
  Used for tests, fixtures, demos and as a measurable baseline. It is not the release gate.

The model per role is configuration (product.models[role] > env VCE_MODEL_<ROLE> > agent default).
"""
import copy
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from packages.util import tokens
from packages.validate import load_schema, validate

AGENT_DIR = Path(__file__).resolve().parent
SKILL_DIR = AGENT_DIR / "skills"


class AgentError(RuntimeError):
    pass


class ToolDenied(PermissionError):
    pass


def load_agent(role):
    d = AGENT_DIR / role
    if not (d / "agent.json").exists():
        raise AgentError(f"unknown agent role {role}")
    spec = json.loads((d / "agent.json").read_text())
    spec["prompt"] = (d / "prompt.md").read_text()
    return spec


def roles():
    return sorted(p.parent.name for p in AGENT_DIR.glob("*/agent.json"))


def load_skill(name):
    p = SKILL_DIR / f"{name}.md"
    return p.read_text() if p.exists() else ""


# ---------------- tools ----------------

class Toolbox:
    """Tool implementations scoped to one product. The runtime only exposes the role's allowlist."""

    def __init__(self, claims=None, artifacts=None, snapshots=None):
        self.claims = claims or {}            # {id: claim} for this product only
        self.artifacts = artifacts or {}      # {name: object} the orchestrator chose to expose
        self.snapshots = snapshots or {}      # {source_id: [blocks]}
        self.output = None

    def read_artifact(self, name):
        if name not in self.artifacts:
            return {"error": f"no artifact '{name}'. Available: {sorted(self.artifacts)}"}
        return self.artifacts[name]

    def get_claim(self, id):
        c = self.claims.get(id)
        if not c:
            return {"error": f"{id} not found"}
        return {k: c[k] for k in ("id", "text", "quote", "location", "category", "confidence", "status", "source_id")}

    def search_registry(self, query, limit=10, include_unverified=False):
        q = set(tokens(query))
        scored = []
        for c in self.claims.values():
            if not include_unverified and c["status"] != "verified":
                continue
            ct = set(tokens(c["text"]))
            s = len(q & ct) / (len(q) ** 0.5 * max(1, len(ct)) ** 0.5) if q and ct else 0
            if s > 0:
                scored.append((s, c["id"]))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [dict(self.get_claim(i), score=round(s, 3)) for s, i in scored[: int(limit)]]

    def get_snapshot_text(self, source_id, location):
        for b in self.snapshots.get(source_id, []):
            if b["loc"] == location:
                return {"text": b["text"]}
        return {"error": "location not found"}

    def write_output(self, obj):
        self.output = obj
        return {"ok": True}


TOOL_SPECS = {
    "read_artifact": {"description": "Read one artifact the orchestrator exposed for this run.",
                      "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    "get_claim": {"description": "Get one claim (status, quote, location) by ID.",
                  "input_schema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
    "search_registry": {"description": "Find verified claims relevant to a topic.",
                        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
                                         "required": ["query"]}},
    "get_snapshot_text": {"description": "Exact source text at a location.",
                          "input_schema": {"type": "object", "properties": {"source_id": {"type": "string"},
                                                                            "location": {"type": "string"}},
                                           "required": ["source_id", "location"]}},
}


def call_tool(spec, box, name, args):
    if name not in spec["tools"]:
        raise ToolDenied(f"{spec['role']} may not call {name}")
    fn = getattr(box, name)
    return fn(**args)


# ---------------- schema inlining (provider tool schemas must be self-contained) ----------------

def inline_schema(name):
    def resolve(node, base):
        if isinstance(node, dict):
            if "$ref" in node:
                f, _, frag = node["$ref"].partition("#")
                f = f or base
                tgt = load_schema(f)
                for part in [p for p in frag.split("/") if p]:
                    tgt = tgt[part]
                return resolve(copy.deepcopy(tgt), f)
            return {k: resolve(v, base) for k, v in node.items() if k not in ("$schema", "$id", "$defs", "title")}
        if isinstance(node, list):
            return [resolve(x, base) for x in node]
        return node
    return resolve(load_schema(f"{name}.schema.json"), f"{name}.schema.json")


# ---------------- providers ----------------

class Usage:
    def __init__(self):
        self.input_tokens = self.output_tokens = 0

    @property
    def total(self):
        return self.input_tokens + self.output_tokens


def model_for(role, spec, product=None):
    return ((product or {}).get("models") or {}).get(role) or os.environ.get(
        "VCE_MODEL_" + role.upper().replace("-", "_")) or spec["default_model"]


class OfflineProvider:
    name = "offline"

    def run(self, spec, payload, box, product=None):
        from agents import offline
        usage = Usage()
        usage.input_tokens = len(json.dumps(payload, default=str)) // 4
        out = offline.run(spec["role"], payload, box)
        usage.output_tokens = len(json.dumps(out)) // 4
        return out, usage


class AnthropicProvider:
    name = "anthropic"
    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key=None, timeout=600):
        self.key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.key:
            raise AgentError("ANTHROPIC_API_KEY is not set (or use VCE_PROVIDER=offline)")
        self.timeout = timeout

    def _post(self, body):
        req = urllib.request.Request(self.URL, data=json.dumps(body).encode(), method="POST", headers={
            "x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 529) and attempt < 3:
                    time.sleep(2 ** attempt * 3)
                    continue
                raise AgentError(f"model API error {e.code}: {e.read()[:300]!r}")

    def run(self, spec, payload, box, product=None):
        usage = Usage()
        system = spec["prompt"]
        for s in spec.get("skills", []):
            text = load_skill(s)
            if text:
                system += f"\n\n<writing_aid name=\"{s}\" trust=\"style-and-structure-only\">\n{text}\n</writing_aid>\n" \
                          "Facts inside writing aids are not true unless the registry has them."
        tools = [dict(name=n, **TOOL_SPECS[n]) for n in spec["tools"] if n != "write_output"]
        tools.append({"name": "write_output", "description": "Submit your single output artifact (validated).",
                      "input_schema": inline_schema(spec["output_schema"])})
        messages = [{"role": "user", "content": "<input>\n" + json.dumps(payload, ensure_ascii=False, default=str) + "\n</input>"}]
        for _ in range(spec.get("max_turns", 16)):
            resp = self._post({"model": model_for(spec["role"], spec, product), "max_tokens": spec.get("max_output_tokens", 16000),
                               "system": system, "tools": tools, "messages": messages})
            u = resp.get("usage", {})
            usage.input_tokens += u.get("input_tokens", 0)
            usage.output_tokens += u.get("output_tokens", 0)
            messages.append({"role": "assistant", "content": resp["content"]})
            results = []
            for block in resp["content"]:
                if block.get("type") != "tool_use":
                    continue
                name, args = block["name"], block.get("input", {})
                if name == "write_output":
                    obj = _inject(spec, payload, args)
                    errs = validate(spec["output_schema"], obj)
                    if not errs:
                        return obj, usage
                    results.append({"type": "tool_result", "tool_use_id": block["id"], "is_error": True,
                                    "content": "Validation failed:\n" + "\n".join(errs[:30])})
                    continue
                try:
                    res = call_tool(spec, box, name, args)
                    results.append({"type": "tool_result", "tool_use_id": block["id"],
                                    "content": json.dumps(res, ensure_ascii=False)[:60000]})
                except ToolDenied as e:
                    results.append({"type": "tool_result", "tool_use_id": block["id"], "is_error": True, "content": str(e)})
            if not results:
                messages.append({"role": "user", "content": "Call write_output with your result now."})
            else:
                messages.append({"role": "user", "content": results})
        raise AgentError(f"{spec['role']} did not produce valid output within {spec.get('max_turns', 16)} turns")


def _inject(spec, payload, obj):
    obj = dict(obj)
    for k in spec.get("inject", []):
        if k in payload:
            obj[k] = payload[k]
    return obj


def provider_from_env():
    name = os.environ.get("VCE_PROVIDER", "offline")
    if name == "anthropic":
        return AnthropicProvider()
    if name == "offline":
        return OfflineProvider()
    raise AgentError(f"unknown provider {name}")


def run_agent(role, payload, box, provider=None, product=None, ctx=None):
    """Run one agent once. Raises AgentError on invalid output (the orchestrator retries once)."""
    spec = load_agent(role)
    provider = provider or provider_from_env()
    out, usage = provider.run(spec, payload, box, product)
    out = _inject(spec, payload, out)
    errs = validate(spec["output_schema"], out, **(ctx or {}))
    if errs:
        raise AgentError(f"{role} output invalid: " + "; ".join(errs[:8]))
    return out, usage


# ---------------- writing-aid fact check ----------------

def writing_aid_flags(skill_names, product, claims):
    """Flag writing aids that state product facts the registry lacks or contradicts."""
    from packages.util import split_sentences
    from packages.registry import NEG_RE
    flags = []
    names = {product["name"].lower()} | {w.lower() for w in product["name"].split() if len(w) > 3}
    verified = [c for c in claims.values() if c["status"] == "verified"]
    for s in skill_names:
        text = load_skill(s)
        for sent in split_sentences(re.sub(r"[#*`>-]", " ", text)):
            low = sent.lower()
            if not any(n in low for n in names) or len(sent.split()) < 5:
                continue
            st = set(tokens(sent))
            best = max(verified, key=lambda c: len(st & set(tokens(c["text"]))), default=None)
            overlap = len(st & set(tokens(best["text"]))) / max(1, len(st)) if best else 0
            if overlap < 0.6:
                flags.append({"aid": s, "issue": f"States a product fact the registry doesn't have: {sent[:160]}"})
            elif bool(NEG_RE.search(sent)) != bool(NEG_RE.search(best["text"])):
                flags.append({"aid": s, "issue": f"Contradicts {best['id']}: {sent[:160]}"})
    return flags
