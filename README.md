# Verified Content Engine

A multi-agent system that writes product-marketing content and **blocks every sentence it can't trace to a verified source** before anything ships.

![Multi-agent architecture](diagrams/multi-agent-architecture.png)

Editable diagram: [`diagrams/multi-agent-architecture.excalidraw`](diagrams/multi-agent-architecture.excalidraw) (open at [excalidraw.com](https://excalidraw.com) → Open). Regenerate with `python3 diagrams/gen_diagram.py`.

| Doc | What's in it |
|---|---|
| [`PRD.md`](PRD.md) | Problem, pilot findings, requirements, success metrics |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Components, pipelines, data model, gate logic, evals |
| [`docs/agent-specs.md`](docs/agent-specs.md) | Every agent, skill and the orchestrator: responsibility, inputs, context, tools, outputs, dependencies, failure behavior; handoff table |
| [`CLAUDE.md`](CLAUDE.md) | Rules for building this repo with Claude Code |

---

## The problem

Marketing teams write about products faster than they can check facts. Generic AI writers make it worse: fluent copy, no idea which statements are true. One model that plans, writes and checks its own work grades its own homework.

## How the work decomposes

The work splits along **trust boundaries**, not just tasks:

| Piece | Why it's its own unit |
|---|---|
| Extract claims from docs | Needs one source at a time and exact quotes. The only path by which facts enter the system. |
| Extract style, positioning, evidence | Different source types with different permissions. Style and positioning may shape copy but can never create a fact. |
| Plan (strategist) | Picks which verified claims go where before any prose exists. |
| Write (copywriter) | Creative work, constrained to tagged claims. |
| Verify (gate) | Must be independent of the writer: different context, no access to the writer's reasoning. |
| Style, best-practice, buyer checks | Independent opinions about the same draft. |
| Decide, finalize, retry, budget | Must be reproducible. Done in code, not by a model. |

## The architecture: orchestrator-worker, with sequential handoffs and parallel fan-out

1. **A code orchestrator** dispatches every step, owns the budget, the revision cap and retries, and calls deterministic code for every decision.
2. **Parallel fan-out in ingestion.** Four extractors (claims, style, positioning, evidence) run at once; claims extraction runs per file. A code join (`registry.build`) merges results, allocates permanent IDs and re-applies human rulings.
3. **Sequential handoff in generation.** Strategist → copywriter, because the draft depends on the plan.
4. **Parallel fan-out in verification.** The gate, style-checker, best-practice-auditor and synthetic buyer read the same draft simultaneously. A code join (`gate.combine`) turns their outputs into Blocked / Flagged / Approved.
5. **A bounded loop.** Blocked or Flagged with fewer than 2 rounds → copywriter revises from the flags → the whole page is re-verified. After 2 rounds → human review.
6. **Humans at the edges.** Only people confirm claims, rule on conflicts, override (with a written reason) and approve. Agents never do.

Skills (`conversion-copywriter`, `positioning-auditor`, `awareness-scorer`, a buyer-persona skill) are loaded into the agents that need them. They shape structure and tone; facts come only from the claims registry.

## Why this architecture

| Choice | Reason |
|---|---|
| **Orchestrator in code, not an LLM** | Status, revision and stop decisions must be reproducible and auditable. A model deciding "good enough" is what the gate exists to prevent. |
| **Separate writer and verifier** | Self-review misses the writer's own overstatements. The verifier gets the draft and the claims, not the plan or the writer's intent, and ignores the writer's tags as evidence. |
| **Parallel checkers** | They're independent reads with no shared state, so running them together cuts latency (target: brief to reviewable draft in ≤15 minutes) without changing results. Keeping them isolated also stops a positive buyer reaction from softening the gate. |
| **Parallel, per-file extraction** | Small contexts give exact quotes. Thousands of claims per product don't fit well in one context. |
| **Sequential strategist → copywriter** | A real dependency. Planning first also surfaces proof gaps before anyone writes around them. |
| **Revision cap + rollback** | In the pilot, revisions didn't always converge: each fresh check found new conflicts. A cap bounds cost; rollback keeps the last approved version live. |

### Alternatives considered

| Option | Why not |
|---|---|
| Single agent with all tools | Grades its own work; context overload with a large registry; no clean place to enforce permissions per source type. |
| Agent team (peers talking freely) | Hard to audit, non-deterministic, and the writer could influence the verifier. |
| Fully sequential pipeline | Same results as the parallel steps, but slower and more expensive in wall-clock time. |
| LLM orchestrator | Flexible, but the decisions that matter most would no longer be testable code. |

## Failure handling

| Failure | Behavior |
|---|---|
| Agent crashes or stalls | Retry once with the same input, then fail the run loudly with context. Resume from the last completed step. |
| Schema-invalid output | Treated as a failed step. |
| One extractor file fails | That file is marked `extraction-failed`; the rest continue. |
| Gate result missing | Never treated as a pass: Blocked. |
| Style or best-practice checker fails | High-severity flag, so the draft can't be auto-approved. |
| Synthetic buyer fails | Optional: the run continues and the report notes it. |
| Budget reached | Clean stop before the next step; state saved. |
| A revision of approved copy fails | The approved version stays live; the failed round is archived. |

## Evals

The gate is evaluated on seeded sentence sets (true, false, overstated, partial, untagged, not citable, positioning). Any change to prompts, models or gate rules must keep: catch rate ≥95%, false-block rate ≤10%, untagged detection ≥95%. See `ARCHITECTURE.md` §7.

## Run it

Requirements: Python 3.9+ and nothing else. The core uses only the standard library, so it works offline on a locked-down laptop.

```bash
bin/vce init --workspace "Demo" --email you@example.test     # first admin; prompts for a password
bin/vce load-fixture lumen --ingest                           # an invented demo product
bin/vce serve                                                 # http://127.0.0.1:8780
```

To try it with two invented demo products instead, run `bin/demo ~/vce-demo-data`, then `VCE_DATA_DIR=~/vce-demo-data bin/vce serve`. The demo prints a one-time random password for admin@example.test.

Data lives in `~/.vce/data` (override with `VCE_DATA_DIR`). Keep it out of cloud-synced folders such as Desktop or Documents when those sync.

**Model provider.** `VCE_PROVIDER=offline` (default) runs deterministic baseline agents: no model calls, no network. Use it for tests, demos and air-gapped review. `VCE_PROVIDER=anthropic` with `ANTHROPIC_API_KEY` runs every agent on Claude through a tool-use loop with per-role tool allowlists. The model per role is configuration (`product.models`, or `VCE_MODEL_<ROLE>`). A model-backed verifier must pass the gate eval before it's used for real content.

| Command | What it does |
|---|---|
| `bin/vce serve` | Web UI + API on 127.0.0.1 |
| `bin/vce ingest <product>` | Build or refresh a product's knowledge base |
| `bin/vce run-brief <brief-id>` | Run a content brief end to end |
| `bin/vce eval gate --fixture lumen --fixture shiftwell` | Release check: catch ≥95%, false-block ≤10%, untagged ≥95% |
| `bin/vce eval style --fixture lumen` | Style AUC and recommended threshold |
| `bin/vce validate` | Schema and rule check of every stored artifact |
| `bin/vce retention [--apply]` | Purge unapproved rounds and run logs past the retention period (dry run by default) |
| `python3 -m unittest discover -s tests -t .` | Unit, tenancy, pipeline, API and eval tests |

See [`docs/implementation.md`](docs/implementation.md) for what's built, the choices made on PRD §15's open questions, current eval numbers and known limits.

## Repository layout

```
apps/web/                 UI (vanilla JS, no build step)
services/api/             HTTP API: auth, roles, workspace scoping, human actions, background jobs
services/orchestrator/    pipelines (ingest, content run, review actions), budgets, retries, content-type templates
services/ingest/          parsers (MD, HTML, DOCX, PPTX, PDF, evidence JSON), snapshots, docs-site import, docs search
services/store/           SQLite metadata + object storage, scoped by workspace at the data layer
services/actions.py       application actions a person performs (rulings, decisions, export, reports)
agents/<role>/            agent.json (schema, tools, model) + prompt.md, one per role
agents/runtime.py         tool allowlists, output validation, Anthropic and offline providers
agents/offline.py         deterministic baseline for every role
agents/skills/            writing aids (structure and tone only)
packages/schemas/         JSON schemas for every artifact
packages/validate/        schema + rule validator
packages/registry/        registry build, permanent IDs, rulings, conflicts, decisions → guardrails
packages/gate/            draft parsing, mechanical block rules, combine, finalize, staleness, rollback, re-flag
evals/                    gate eval (seeded + golden), style calibration, results in evals/runs/
fixtures/products/        two invented products (Lumen Hub, Shiftwell) with planted traps
tests/                    unittest suite
bin/vce                   CLI
```
