# ARCHITECTURE: Verified Content Engine

**Status:** Draft v1
**Last updated:** 2026-10-01
**Companion docs:** `PRD.md` (what and why), `CLAUDE.md` (rules for working in this repo)

This document describes how the system is built. Where `PRD.md` and this file disagree, the PRD wins on behavior and this file must be updated. Items marked **(open)** are undecided and tie back to PRD §15.

---

## 1. Design principles

1. **The gate is the product.** Every component exists to feed the gate or act on its result.
2. **Models propose, code decides.** Agents produce structured artifacts. Status, final copy, staleness, ID allocation and ruling application are deterministic code in `packages/gate` and `packages/registry`.
3. **Schemas are the contract.** Every artifact has a JSON schema in `packages/schemas` and is validated before it is saved. Invalid means error.
4. **Snapshots, not live links.** Every source is an immutable, hashed snapshot. Every claim quote points into a snapshot.
5. **Tenancy at the data layer.** Every read and write is scoped by `workspace_id` below the API, not in the UI.
6. **Human actions are application actions.** Agents can't confirm, rule, override, approve or export. Only an authenticated user, through the API, can.

---

## 2. System overview

```
                ┌──────────────────────────── apps/web ────────────────────────────┐
                │ Products · Sources · Claims · Decisions · Create · Review · Gaps · Settings │
                └───────────────────────────────┬──────────────────────────────────┘
                                                │ HTTPS (session / SSO)
                                    ┌───────────▼───────────┐
                                    │     services/api      │  auth, roles, workspace scoping,
                                    │                       │  human actions (rulings, overrides,
                                    └───┬───────────┬───────┘  approvals, exports), audit log
                                        │           │
                         ┌──────────────▼──┐   ┌────▼──────────────────┐
                         │ services/ingest │   │ services/orchestrator │
                         │ uploads, docs-  │   │ pipelines, budgets,   │
                         │ site snapshots, │   │ retries, resume       │
                         │ connectors      │   └────┬─────────┬────────┘
                         └───────┬─────────┘        │         │
                                 │          ┌───────▼───┐ ┌───▼──────────────────┐
                                 │          │  agents/  │ │ packages/gate,        │
                                 │          │ (model    │ │ registry, validate    │
                                 │          │  calls)   │ │ (deterministic)       │
                                 │          └───────────┘ └───────────────────────┘
                         ┌───────▼────────────────────────────────────────────────┐
                         │ Storage: metadata DB + object storage (per workspace)  │
                         └────────────────────────────────────────────────────────┘
```

---

## 3. Components

### 3.1 `apps/web`

- The four pilot screens (Products, Sources, Create, Review) plus Claims, Decisions, Gaps and Settings.
- Rendered views of profiles and positioning packs are read-only. Edits go through structured forms that write the underlying artifact.
- The Review screen is the main working surface. It shows each block's reason, the cited claim and quote, the suggested fixes, and these actions: edit, direct a revision, add a source, override, reject. It also shows the round-by-round comparison.
- Live per-agent progress, streamed from the orchestrator.

### 3.2 `services/api`

- Authentication (session login; SSO for enterprise workspaces in M4).
- Role-based permissions: editor, reviewer, SME, compliance reviewer, admin. One user can hold several.
- The **only** entry point for human actions: claim rulings, conflict rulings, decision edits, overrides, approvals, exports. Each action writes an audit event.
- Injects `workspace_id` into every data-layer call from the authenticated session. Never from the request body.

### 3.3 `services/ingest`

- **Upload:** PDF, DOCX, PPTX, Markdown, HTML, plain text. Each is converted to normalized text with stable locations (page, heading path, paragraph index).
- **Docs-site import:** discovers pages through llms.txt, a sitemap or a URL prefix. Writes a manifest entry per page with URL, fetch time and sha256. Refreshes only on request.
- **Connectors (v1.1):** Google Drive, Notion, Confluence, GitHub. Read-only, snapshot import.
- **Docs search (optional):** a per-product adapter used for discovery and coverage checks only. Its results are never stored as quotes.
- **Change detection:** on refresh, compares hashes. Changed or removed snapshots mark the knowledge base stale and enqueue a staleness computation (§5.3).

### 3.4 `services/orchestrator`

- Runs the pipelines in §4 as resumable step graphs. Steps without dependencies run in parallel.
- Enforces the per-run and per-workspace budgets, the revision cap (2 automatic rounds) and the retry policy (one retry per stalled or crashed agent, then the run fails loudly with context).
- Persists the result of each step before starting the next, so a run can resume from the last completed step.
- Calls `packages/gate` for every decision. It never interprets model output as a status.

### 3.5 `agents/`

One definition per role: a prompt, an input schema, an output schema and a tool allowlist. The roles and their "must never" rules are in `CLAUDE.md` §5.

Runtime rules for every agent call:

- Input is assembled by the orchestrator from the product's own artifacts only.
- Output is validated against the schema. Invalid output counts as a failed step, which is retried once.
- No network, shell or file access beyond the contract. Tools not on the allowlist are denied.
- The model per role is configuration, not code (PRD §10, model independence). **(open)** One provider or a choice per workspace.

### 3.6 Deterministic packages

| Package | Responsibilities |
|---|---|
| `packages/schemas` | JSON schemas for every artifact. Versioned. The source of truth for shapes. |
| `packages/validate` | Schema validation plus rule checks: quote under 60 words, quote found verbatim in its snapshot, IDs well-formed, profile internal consistency, decision-to-guardrail links present. |
| `packages/registry` | Registry build from extractor output, permanent ID allocation, applying rulings, preserving rulings across re-ingest, conflict detection, deprecation and re-flagging of approved content. |
| `packages/gate` | Combining checker outputs into a status, writing final copy (tag stripping), staleness computation, round archiving, rollback to the last approved version. |

---

## 4. Pipelines

### 4.1 Ingestion → knowledge base

```
snapshot sources
  → [parallel] claims-extractor (truth) · style-extractor (style)
               · positioning-extractor (positioning + decisions) · evidence-extractor (evidence, optional)
  → validate every per-source record
  → registry.build: allocate IDs, merge, apply stored rulings, set needs-review for high-risk / low-confidence
  → registry.detect_conflicts → conflicts queue (UI)
  → style calibration (labeled set → recommended threshold → admin accepts)
  → positioning pack: link proof points to claims or mark needs-claim
  → knowledge base status = ready | stale | blocked (no truth sources)
```

Each extractor writes one record per source file plus a combined master, as the pilot did.

### 4.2 Content run

```
brief (incl. optional mandated wording)
  → strategist → plan (framework, angle, persona, stage, outline, claims per section, proof gaps)
  → copywriter → tagged draft + claim map + missing-claims list
  → [parallel] verifier (gate) · style-checker · best-practice-auditor · synthetic-buyer (optional)
  → gate.combine → Blocked | Flagged | Approved
  → if not Approved and auto rounds < 2: copywriter revises from flags → re-verify (full page)
  → if Approved: gate.finalize → final copy (tags stripped)
  → else: human review record in the Review queue
```

- The verifier classifies every sentence itself and ignores the copywriter's tags as evidence (PRD §9).
- Each verification checks the whole page, including page-level tension and implied conclusions, not only changed sentences.
- Every round is archived with its draft, checker outputs and report.

### 4.3 Human review loop

| Action | Effect |
|---|---|
| Edit | Saves a new draft version and re-runs verification. |
| Direct a revision | Copywriter revises from written instructions. Logged as human-directed. Not counted toward the auto cap. |
| Add a source | Ingests the new snapshot. New claims enter as `needs-review`. After an SME confirms them, the draft is re-verified. Adding a source never clears a block by itself. |
| Override | Requires a written reason. Status becomes `approved-override`. Audit event written. |
| Reject | Closes the item. History kept. |

If a revision of already-approved content fails, `gate` keeps the approved version live and archives the failed round.

---

## 5. Data model and storage

### 5.1 Storage split

- **Metadata database:** workspaces, members, roles, products, claims, rulings, decisions, briefs, runs, reports, statuses, audit events, budgets.
- **Object storage:** source snapshots, normalized text, per-source extractor records, drafts, final copy, eval sets and results. Paths are prefixed `/{workspace_id}/{product_id}/...`.
- Every artifact is versioned. Nothing approved is overwritten in place.

**(open)** Concrete database and storage choices depend on the hosting default (PRD §15.2). The design assumes a relational database with row-level workspace scoping and S3-compatible object storage, which also works in self-hosted mode.

### 5.2 Key entities

| Entity | Key fields |
|---|---|
| `workspace` | id, name, data settings (retention, residency), budgets |
| `product` | id, workspace_id, name, claim_prefix, content_types, high_risk_categories, buyer_persona, style_threshold |
| `source` | id, product_id, type (`truth` / `style` / `positioning` / `evidence`), origin (file or URL), fetched_at, sha256, status |
| `claim` | id (`<PREFIX>-<NNN>`, permanent), product_id, text, quote, source_id, location, category, confidence, status, user_decision |
| `ruling` | id, claim_id or conflict_id, kind (`confirmed` / `rejected` / `deprioritized` / `doc-wrong`), note (verbatim), author, created_at |
| `conflict` | id, claim_ids, kind (contradiction / absolute-vs-exception / living-vs-changelog), interim_default, status |
| `decision` | id, product_id, text (verbatim), author, created_at, derived_guardrails[] |
| `brief` | id, product_id, content_type, audience, goal, stage, notes, mandated_wording |
| `run` | id, brief_id, rounds[], cost, status, logs_ref |
| `report` | run_id, round, sentence_verdicts[], checker_scores, flags[], status, override |
| `audit_event` | id, workspace_id, actor, action, target, reason, created_at |

### 5.3 Staleness

When a snapshot changes or is removed, `gate.staleness` finds:

1. claims whose quote no longer appears verbatim in the new snapshot, which go to `needs-review`
2. content items citing those claims, which are re-flagged
3. conflicts that may need a new ruling

Stored rulings are re-applied by ID and quote hash. A re-ingest can never reverse a ruling without a new human ruling.

---

## 6. Gate decision logic

`gate.combine(sentence_verdicts, checker_outputs) → status`

```
if any sentence verdict is BLOCK                → Blocked
elif any flag has severity = high               → Flagged
else                                            → Approved
```

Block and flag conditions are those in PRD §9. The verifier returns, for each sentence:

- the sentence text and its location
- a classification: factual, positioning, or positioning-hiding-fact
- the cited claim IDs and the claim IDs the verifier itself judges relevant
- a verdict (pass / block / flag) with a reason code (untagged, missing-claim, needs-review, deprecated, contradicted, partial, overstated, combined-conclusion, high-risk-low-confidence)
- a suggested fix

Reason codes are an enum in `packages/schemas`. They drive the Review screen and the per-category eval breakdown.

---

## 7. Evals

Evals are part of the release process, not a separate project.

```
evals/
├── gate/         seeded sentence sets built per product from its registry
│                 + a fixed golden set of hand-labeled sentences
├── style/        labeled on-brand / off-brand samples; threshold calibration
├── extraction/   claims-extractor: quote exactness, recall against hand-listed claims
├── conflicts/    seeded contradictory and absolute-vs-exception pairs
└── e2e/          fixed briefs on fixture products; rounds-to-approval, cost, latency
```

- **Gate eval** labels: true, false, overstated, partial, untagged, not-citable, positioning, plus page-level implied-conclusion cases. Metrics are reported in total and by reason code.
- **Release check:** any change to verifier prompts, gate rules, a model, or `packages/gate` re-runs the gate eval on at least two fixture products. It ships only if catch rate ≥95%, false-block rate ≤10% and untagged detection ≥95% (`CLAUDE.md` §7).
- **Style eval** recomputes AUC and the recommended threshold when the profile or checker changes. An admin accepts the new threshold.
- Results are stored per release and compared with the previous release.
- Eval seeds use only `fixtures/` data. Never real customer material.

`extraction/`, `conflicts/` and `e2e/` go beyond the current PRD §8.10 and should be added to it if adopted.

---

## 8. Security and tenancy

- **Isolation:** row-level workspace scoping in the database, workspace-prefixed object paths, and no caches, embeddings or prompt context shared across workspaces. Every new data access path gets a tenancy test.
- **Agent sandboxing:** each agent call receives only its product's artifacts. A tool allowlist is enforced. No ambient network or file access.
- **Evidence sources:** encrypted at rest, restricted by role, excluded from exports and debug logs, never quoted or named in output.
- **Training:** customer data is never used for model training. Provider settings must guarantee this.
- **Retention:** one policy covering sources, drafts, run logs and model inputs.
- **Exfiltration review:** sync clients, connectors and telemetry are reviewed before they're enabled.

---

## 9. Cost, latency and reliability

- **Budgets:** per workspace and per run, with a hard stop. The orchestrator checks the remaining budget before each agent step.
- **Estimates:** shown before any run more expensive than a quick check, based on brief type and registry size.
- **Quick-check mode:** runs only the verifier on supplied copy.
- **Cost recording:** tokens and spend recorded per step, rolled up per run, product and workspace.
- **Latency target:** brief to reviewable draft in 15 minutes or less for a landing page. Parallel verification is the main lever. Registry slicing (sending only the claims relevant to the plan, plus related claims for conflict checks) is the second.
- **Reliability:** one retry per failed or stalled agent step, then a loud failure. Runs resume from the last completed step.

---

## 10. Deployment

- **Hosted multi-tenant SaaS** by default, or **self-hosted / local mode** for teams that can't send sources off their machines. The same services run in both. Self-hosted mode swaps managed storage and model endpoints through configuration.
- **(open)** Which mode is the default depends on PRD §15.1 and §15.2.

---

## 11. Mapping to milestones

| Milestone | Components |
|---|---|
| M1 | api (workspaces, roles), ingest (upload, docs-site), registry, validate, schemas, claims and decisions UI |
| M2 | orchestrator content pipeline, strategist, copywriter, verifier, gate (combine, finalize, archive, rollback) |
| M3 | Review screen, style-checker, best-practice-auditor, synthetic-buyer, evals (gate, style), Gaps report |
| M4 | connectors, budgets and quick-check, audit export, SSO, self-hosted mode, CMS draft push |
