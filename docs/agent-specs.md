# Agent, skill and orchestrator specifications

Each unit below lists its **responsibility, inputs, context, tools, outputs, dependencies** and **failure behavior**. "Context" means what is loaded into the agent's context window. "Tools" is the full allowlist; anything not listed is denied.

Diagram: [`diagrams/multi-agent-architecture.excalidraw`](../diagrams/multi-agent-architecture.excalidraw). Rules every unit inherits: [`CLAUDE.md`](../CLAUDE.md) §2.

Shared tool names used below:

| Tool | What it does |
|---|---|
| `read_artifact(path)` | Reads one artifact from the current product's storage. Workspace and product are injected by the orchestrator, not chosen by the agent. |
| `write_output(obj)` | Writes the agent's single output artifact to its own working area. Schema-validated on write. |
| `get_claim(id)` | Returns one claim with its status, quote and source location. |
| `search_registry(query)` | Returns verified claims relevant to a topic (keyword + semantic). |
| `get_snapshot_text(source_id, location)` | Returns the exact text at a location in a source snapshot. |

---

## 1. Orchestrator

| Field | Spec |
|---|---|
| **Type** | Deterministic code (`services/orchestrator`). Not an LLM. |
| **Responsibility** | Run the ingestion and content pipelines as step graphs; dispatch agents; enforce budgets, the revision cap (2) and retry policy; call `packages/gate` for every decision; persist each step so runs can resume. |
| **Inputs** | A pipeline request from the API: `ingest(product_id, source_ids)` or `content_run(brief_id)`. |
| **Context** | No model context. Holds run state: step graph, completed steps, round count, spend so far, budget. |
| **Tools** | Agent runtime (spawn agent with input + allowlist), `packages/validate`, `packages/registry`, `packages/gate`, storage, progress events to the UI. |
| **Outputs** | `run` record: steps, rounds, per-step cost, final status, pointers to every artifact. |
| **Dependencies** | API (requests), all agents, all deterministic packages, storage. |
| **Failure** | Agent step fails or stalls → retry once with the same input → if it fails again, mark run `failed` with the step, error and inputs, and stop. Budget reached → stop before the next step, save state. Resume restarts from the last completed step. |

**Why code and not an LLM orchestrator:** the decisions it makes (when to revise, when to stop, what status to assign) must be reproducible and auditable. An LLM deciding "this is good enough" is exactly what the gate exists to prevent.

---

## 2. Ingestion agents (run in parallel)

### 2.1 `claims-extractor`

| Field | Spec |
|---|---|
| **Responsibility** | Turn one truth source into atomic, cited claims. |
| **Inputs** | One truth-source snapshot (normalized text with locations); product's high-risk categories. |
| **Context** | That one source only, plus the claim schema and category list. Not other sources (prevents cross-source blending). |
| **Tools** | `read_artifact`, `get_snapshot_text`, `write_output`. No web, no docs search. |
| **Outputs** | `claims-record.json` for that file: claim text, exact quote (<60 words), location, category, confidence. No IDs (code allocates them). |
| **Dependencies** | Ingest service (snapshot exists). Feeds `registry.build`. |
| **Failure** | Schema-invalid output or a quote not found verbatim in the snapshot → step fails → retry once → source marked `extraction-failed`, others continue. |

### 2.2 `style-extractor`

| Field | Spec |
|---|---|
| **Responsibility** | Learn voice, cadence, vocabulary, naming and formatting from style sources; produce a scoring rubric. |
| **Inputs** | All style sources for the product (min ~1,500 words across 3 pieces). |
| **Context** | Style sources and the profile schema. No truth sources (style sources teach voice, never facts). |
| **Tools** | `read_artifact`, `write_output`. |
| **Outputs** | `style-profile.json` + consistency report (e.g. product named two ways). |
| **Dependencies** | Ingest. Feeds calibration (code) and `style-checker`. |
| **Failure** | Corpus under minimum → not run, warning shown. Inconsistent profile → saved as `draft`, admin must resolve before use. |

### 2.3 `positioning-extractor`

| Field | Spec |
|---|---|
| **Responsibility** | Build the positioning pack: positioning, messaging, personas, objections, alternatives, awareness stages. |
| **Inputs** | Positioning sources, decisions log (verbatim), registry claim list (IDs + text). |
| **Context** | The above. Decisions are passed verbatim with an instruction to apply them literally. |
| **Tools** | `read_artifact`, `search_registry`, `write_output`. |
| **Outputs** | `positioning-pack.json`. Each proof point is `has-claim` (with ID) or `needs-claim`. Each guardrail cites its decision ID. |
| **Dependencies** | Ingest; runs in parallel with claims extraction, then a cheap linking pass after `registry.build` attaches claim IDs. |
| **Failure** | A guardrail with no decision ID fails validation → retry once → pack saved without that guardrail and flagged. |

### 2.4 `evidence-extractor` (optional)

| Field | Spec |
|---|---|
| **Responsibility** | Extract market-evidence claims with reproducible counts and buyer language from calls or surveys. |
| **Inputs** | Evidence sources (encrypted, role-restricted). |
| **Context** | Evidence sources only. |
| **Tools** | `read_artifact`, `write_output`. |
| **Outputs** | `market-evidence.json`: claims with counts, all `needs-review`. No names, no quotes for copy. |
| **Dependencies** | Ingest. Feeds registry as `market-evidence` category only. |
| **Failure** | Any person or company name detected in output → output discarded, step fails. |

### 2.5 `registry.build` + `validate` (code, join point)

Waits for all extractors, then: allocates permanent IDs, merges records, re-applies stored rulings by ID and quote hash, sets high-risk and low-confidence claims to `needs-review`, detects conflicts, computes staleness. Outputs the claims registry and the SME review queue. Deterministic, unit-tested.

---

## 3. Content agents (sequential handoff)

### 3.1 `strategist`

| Field | Spec |
|---|---|
| **Responsibility** | Plan the piece: framework, angle, persona, stage, outline, and which verified claims go in each section. List proof gaps. |
| **Inputs** | Brief; positioning pack; registry slice (verified claims relevant to the brief). |
| **Context** | Brief + pack + registry slice + content-type template. Skill: `conversion-copywriter` (frameworks only). |
| **Tools** | `read_artifact`, `search_registry`, `get_claim`, `write_output`. |
| **Outputs** | `plan.json`: sections, claim IDs per section, proof gaps, mandated-wording notes. |
| **Dependencies** | Knowledge base ready. Hands off to `copywriter`. |
| **Failure** | Plan cites a non-verified claim → validation fails → retry once → run fails with the offending IDs. |

### 3.2 `copywriter`

| Field | Spec |
|---|---|
| **Responsibility** | Write the draft from the plan, tagging every factual sentence, heading, card title and caption with claim IDs. On revision rounds, fix the flagged sentences. |
| **Inputs** | Plan; style profile; registry slice; (revision rounds) previous draft + verification report flags, or a human's written instructions. |
| **Context** | The above. Skill: `conversion-copywriter` for structure and tone. Any product fact in a skill is ignored unless it's in the registry. |
| **Tools** | `read_artifact`, `get_claim`, `search_registry`, `write_output`. |
| **Outputs** | `draft.md` (tagged) + `claim-map.json` + `missing-claims.json`. |
| **Dependencies** | `strategist`. Fans out to the four checkers. |
| **Failure** | Retry once → run fails. A revision that fails verification never replaces an approved version. |

---

## 4. Verification agents (parallel fan-out on the same draft)

All four receive the same draft version and run at the same time. None sees another's output.

### 4.1 `verifier` — the gate

| Field | Spec |
|---|---|
| **Responsibility** | Classify every sentence (factual / positioning / positioning-hiding-fact) and return pass, block or flag with a reason code and a suggested fix. Check page-level tension and implied conclusions. |
| **Inputs** | Draft; full set of claims cited plus related claims (for conflict checks); product's high-risk categories. |
| **Context** | Draft + those claims with quotes. Not the plan, not the brief, not the copywriter's reasoning (independence from the writer). |
| **Tools** | `get_claim`, `search_registry`, `get_snapshot_text`, `write_output`. No docs search, no web. |
| **Outputs** | `gate-verdicts.json`: per-sentence verdicts with reason codes from the enum. |
| **Dependencies** | `copywriter`. Feeds `gate.combine`. |
| **Failure** | Retry once → run fails. A missing gate result is never treated as a pass. |

### 4.2 `style-checker`

| Field | Spec |
|---|---|
| **Responsibility** | Score the draft against the style profile; flag deviations. |
| **Inputs / context** | Draft + style profile (incl. calibrated threshold). |
| **Tools** | `read_artifact`, `write_output`. |
| **Outputs** | `style-report.json`: score, pass/fail vs threshold, flags with severity. |
| **Failure** | Retry once → recorded as `checker-unavailable`, high-severity flag (forces Flagged, not Approved). |

### 4.3 `best-practice-auditor`

| Field | Spec |
|---|---|
| **Responsibility** | Check structure, CTA, positioning fit and awareness-stage match. |
| **Inputs / context** | Draft + plan + positioning pack. Skills: `positioning-auditor`, `awareness-scorer`. |
| **Tools** | `read_artifact`, `write_output`. |
| **Outputs** | `best-practice-report.json`: scores + flags. Never gates facts. |
| **Failure** | Same as style-checker. |

### 4.4 `synthetic-buyer` (optional)

| Field | Spec |
|---|---|
| **Responsibility** | React as the product's buyer persona: verdict (yes / maybe / no), objections, missing proof. |
| **Inputs / context** | Draft with tags stripped + persona. Skill: buyer-persona skill. |
| **Tools** | `write_output`. |
| **Outputs** | `buyer-reaction.json`. Objections the docs can't answer go to the Gaps report. |
| **Failure** | Optional: on failure the run continues without it and the report notes it. |

---

## 5. Deterministic decision and finalize (code)

| Unit | Responsibility |
|---|---|
| `gate.combine` | Joins all four checker outputs. Any block → **Blocked**; else any high-severity flag → **Flagged**; else **Approved**. Missing gate output → Blocked. |
| Revision router (orchestrator) | Blocked/Flagged and auto rounds < 2 → copywriter revises from flags → full re-verification. Otherwise → human review queue. |
| `gate.finalize` | Approved or approved-override only: strip tags, write final copy, archive the round. |
| `gate.archive` / rollback | Every round archived. If revised approved content fails, the approved version stays live. |

---

## 6. Skills

Skills are reusable instruction packs loaded into an agent's context. They shape **how** to write or judge, never **what is true**.

| Skill | Loaded by | Responsibility | Guardrail |
|---|---|---|---|
| `conversion-copywriter` | strategist, copywriter | Frameworks (PAS, AIDA, BAB), awareness-stage matching, headline and CTA craft. | Product facts in the skill are ignored unless the registry has them. Contradictions flag the skill. |
| `positioning-auditor` | best-practice-auditor | Positioning-strength checks. | Doesn't gate facts. |
| `awareness-scorer` | best-practice-auditor | Scores which awareness stage the copy meets the reader in. | Doesn't gate facts. |
| buyer-persona skill | synthetic-buyer | The persona's priorities, objections and language. | Can't invent claims to answer its own objections. |

---

## 7. Handoffs

| # | From → To | Payload | Mode |
|---|---|---|---|
| H1 | API → orchestrator | `ingest(product, sources)` | — |
| H2 | orchestrator → 4 extractors | one source type each (claims: one file per call) | **parallel** |
| H3 | extractors → `registry.build` | per-file records | **join** (wait for all; failed files reported) |
| H4 | `registry.build` → SME queue | needs-review claims, conflicts | async, human |
| H5 | SME → registry (via API) | rulings | human action |
| H6 | API → orchestrator | `content_run(brief)` | — |
| H7 | orchestrator → strategist | brief, pack, registry slice | sequential |
| H8 | strategist → copywriter | `plan.json` | sequential |
| H9 | copywriter → 4 checkers | same draft version | **parallel** |
| H10 | checkers → `gate.combine` | verdicts, scores, flags | **join** |
| H11 | `gate.combine` → copywriter | flags (round < 2) | loop |
| H12 | `gate.combine` → finalize / review queue | status + report | branch |
| H13 | reviewer → orchestrator (via API) | edit, instructions, new source, override, reject | human action |

---

## 8. Where it runs in parallel and why

| Fan-out | Why it's safe |
|---|---|
| Four extractors | Each reads a different source type and writes a different artifact. No shared state until the code join. |
| Claims extraction per file | One call per truth file keeps each context small and quotes exact. |
| Four checkers | Each is a read-only judgment of the same draft. Independence is a feature: the gate must not be influenced by style or buyer opinions. |

Sequential where there's a real dependency: strategist → copywriter (the draft needs the plan), checkers → combine (the verdict needs all results).
