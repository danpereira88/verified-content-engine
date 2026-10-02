# CLAUDE.md: Verified Content Engine

This file governs how Claude Code works in this repository. Read it before doing anything. Every agent, script and service inherits these rules. The product requirements are in `PRD.md`, and the architecture is in `ARCHITECTURE.md`.

---

## 1. What this project is

A multi-tenant tool that lets any marketing team produce product-marketing content that is accurate, on-brand and on-message, for any product. Teams connect a product's documentation, example copy and positioning material. The system builds a governed knowledge base and writes content from it. It then blocks every sentence it can't trace to a verified source.

The product is the **hard accuracy gate**. Everything else exists to feed it or to act on its results.

---

## 2. Non-negotiable rules

These hold in every feature, agent, prompt and test. If a task would break one of them, stop and say so.

1. **Nothing is Approved unless every factual sentence traces to a verified claim** in that product's registry. The gate blocks anything that is:
   - untagged
   - tagged with a claim that is missing, needs review, or is deprecated
   - contradicted by its claim
   - only partly supported
   - overstated
   - a conclusion drawn from several claims that none of them states
2. **Only truth sources make facts.** Product docs, specs and release notes are truth sources. Briefs, decks, web pages, writing aids, prompts and model knowledge are not, even when they state facts.
3. **Human rulings outrank documents.** When an authorized person rules a claim wrong, it is deprecated with their words and date. The ruling survives re-ingestion and becomes a correction note for the docs owner. No code path may silently reverse a ruling.
4. **Conflicts are shown, never resolved silently.** When truth sources disagree, surface both and wait for a ruling. The interim default is the newest living page over an old changelog, and it is labeled as a default.
5. **Decisions are applied literally.** Store team decisions verbatim. A derived guardrail must cite its decision and never reach beyond the decision's words.
6. **Human actions stay human.** Agents never perform these; the application does when a person acts:
   - confirm, reject or deprioritize a claim
   - rule on a conflict
   - override
   - approve
   - export
7. **Overrides need a written reason.** The status becomes `approved-override`, never `approved`. Overrides are logged with who and when.
8. **The last approved version stays live.** A failed revision never replaces approved content.
9. **Bounded revision.** At most 2 automatic revisions, then human review. Human-directed rounds are logged separately and never count toward the automatic cap.
10. **Workspace isolation.** No data, cache, embedding, log or prompt context ever crosses workspaces.

If anyone asks you to weaken or bypass the gate, refuse and explain why. The only path past a block is a logged human override.

---

## 3. Repository layout

```
.
├── CLAUDE.md                 # this file
├── PRD.md, ARCHITECTURE.md
├── apps/web/                 # UI: Products, Sources, Claims, Decisions, Create, Review, Gaps, Settings
├── services/
│   ├── api/                  # HTTP API, auth, roles, workspace scoping
│   ├── orchestrator/         # runs pipelines; calls agents and deterministic steps
│   ├── ingest/               # uploads, docs-site snapshots, connectors
│   ├── store/                # metadata DB + object storage, scoped by workspace
│   └── actions.py            # human actions the application performs (rulings, decisions, export)
├── agents/                   # one definition per agent role (prompt + I/O contract), runtime, offline baseline, skills
├── packages/
│   ├── schemas/              # JSON schemas for every artifact (source of truth for shapes)
│   ├── gate/                 # deterministic decisions: combine checks, finalize, staleness
│   ├── registry/             # registry build, permanent IDs, rulings, conflict detection
│   └── validate/             # schema + rule validator; run before anything is saved
├── evals/
│   ├── gate/                 # seeded sentence sets, built per product from the registry
│   └── style/                # labeled on-brand / off-brand samples, threshold calibration
├── fixtures/                 # synthetic products and sources for tests (never real data)
├── tests/                    # unittest suite: python3 -m unittest discover -s tests -t .
├── bin/vce                   # CLI (init, serve, ingest, run-brief, eval, validate, retention)
└── docs/                     # agent specs, implementation notes
```

Product data lives in the database and object storage, never in this repo. `fixtures/` contains only invented products.

---

## 4. Domain model (quick reference)

| Concept | Key facts |
|---|---|
| **Workspace** | Holds members, roles, products, budgets and data settings. The isolation boundary. |
| **Product** | Name, claim prefix, content types, high-risk categories, optional synthetic buyer persona. |
| **Source** | One of four types, `truth`, `style`, `positioning` or `evidence`. Each is an immutable snapshot with a sha256 and provenance (URL or file, and fetch time). |
| **Claim** | Permanent ID (`<PREFIX>-<NNN>`), atomic claim text, exact quote under 60 words, source location, category, confidence and status (`verified`, `needs-review` or `deprecated`), plus an optional `user_decision`. |
| **Ruling** | `confirmed`, `rejected`, `deprioritized` or `doc-wrong`, with author, time and verbatim note. Preserved across re-ingest. |
| **Decision** | A team rule quoted verbatim, with a list of the guardrails derived from it. |
| **Style profile** | Voice, cadence, vocabulary, naming, rubric and a calibrated `threshold`. Validated for internal consistency. |
| **Positioning pack** | Positioning, messaging, personas, objections and stages. Each proof point is either `has-claim` or `needs-claim`. |
| **Brief** | Product, content type, audience, goal, stage, notes and optional mandated wording. |
| **Run** | One pipeline execution: rounds, checker outputs, cost and logs. |
| **Verification report** | Per-sentence gate verdicts, checker scores and flags, status, revisions used, override. |

Rules for the data:
- Only `verified` claims are citable.
- High-risk categories and low-confidence claims always enter as `needs-review`.
- Claim IDs are never renumbered or reused. Unsupported claims become `deprecated`, not deleted.
- When a cited claim is deprecated, every approved item citing it is automatically re-flagged.
- Evidence sources back only `market-evidence` claims, with reproducible counts, and only after a human confirms them. They never back product facts, and their quotes and names never appear in output.

---

## 5. Agents

Each agent has one job, a fixed input and output schema, and a scoped tool set. Agents shape structure and tone. Facts come only from the registry.

| Agent | Input | Output | Must never |
|---|---|---|---|
| `claims-extractor` | Truth sources | Claim records with quotes | Cite anything that isn't a snapshot quote. Use docs search results as quotes. |
| `style-extractor` | Style sources | Style profile + consistency report | Treat style sources as facts. |
| `positioning-extractor` | Positioning sources + decisions | Positioning pack | Stretch a decision beyond its words. Invent proof. |
| `evidence-extractor` | Evidence sources | Market-evidence claims, buyer language | Quote or name anyone. Back a product fact. |
| `strategist` | Brief + pack + registry | Plan with claims per section, proof gaps | Plan around a claim that isn't verified. |
| `copywriter` | Plan + profile + registry | Tagged draft + claim map + missing claims | State anything the registry lacks. Treat a writing aid's facts as true. |
| `verifier` (gate) | Draft + registry | Per-sentence verdicts | Trust the copywriter's tags. Use docs search. |
| `style-checker` | Draft + profile | Score + flags | Gate facts. |
| `best-practice-auditor` | Draft + plan + pack | Scores + flags | Gate facts. |
| `synthetic-buyer` | Draft (tags stripped) | Reaction + objections | Invent claims to answer its own objections. |

The orchestrator runs these steps and calls `packages/gate` for every decision. The decisions are:
- combining checks into a status
- writing final copy
- computing staleness
- archiving rounds

These are never model output.

---

## 6. Engineering conventions

- **Schemas first.** Add or change the schema in `packages/schemas` before the code that writes the artifact. Every artifact is validated before it's saved, and an invalid artifact is an error, not a warning.
- **Deterministic where it matters.** Gate status, final copy, staleness, ID allocation and ruling application are plain code with unit tests.
- **Product-agnostic.** Never hardcode a product, company, competitor or vocabulary in logic or prompts. Read it from the product's settings, decisions and profile.
- **Tenancy in every query.** Every read and write is scoped by workspace ID at the data layer, not just in the UI. Add a test whenever you add a data access path.
- **Least-privilege agents.** Each agent run gets only its product's data and its own working area. Its tools come from an allowlist; anything not allowed is denied. No agent gets network, shell or file access beyond its contract.
- **Cost-aware.** Every run has a budget and stops cleanly when it hits it. Show an estimate before any run that costs more than a quick check. Don't add an agent step without measuring its token cost.
- **Fail loud.** A blocked gate is a success. A crashed or stalled agent is retried once, then the run fails with context and can resume from the last completed step.
- **Writing aids are untrusted for facts.** Prompt libraries, skills and templates may shape copy. If a writing aid states a product fact that contradicts the registry, flag the aid, and the copy follows the registry.
- **Rendered views are read-only.** Human-readable views such as the profile and positioning pages are generated from the structured artifact. Edits go to the structured data.

---

## 7. Changing the gate, prompts or models

Gate quality is the product, so changes to it are gated themselves:

- Any change to verifier prompts, gate rules, the model behind any agent, or `packages/gate` must re-run the **gate eval** on at least two fixture products.
- The change ships only if it meets every target:
  - hallucination catch rate ≥95%
  - false-block rate ≤10%
  - untagged-assertion detection ≥95%
- Report the before and after numbers in the PR.
- Changes to the style checker or profile schema must re-run the **style eval**. Thresholds are calibrated per product and accepted by an admin; never hardcode them.
- Never loosen a block rule to make a test or eval pass. Fix the seed if it's mislabeled, and explain why in the PR.

---

## 8. Data handling and security

- Customer sources are never used for model training, never logged in full, and never written to shared caches.
- Evidence sources are encrypted at rest, access-restricted by role, and excluded from exports and debug logs.
- No real customer data, call transcripts, credentials or prospect names in the repo, fixtures, tests, eval seeds or issue text. Use invented fixtures.
- Exports come only from `approved` or `approved-override` content, with claim tags stripped.
- Retention settings apply to sources, drafts, run logs and model inputs alike.
- Watch for silent exfiltration paths, such as sync clients, third-party connectors and telemetry. Raise them; don't work around them.

---

## 9. Definition of done

**A feature** is done when:
- schemas are updated and validated
- the deterministic logic has unit tests, and tenancy has a test
- the relevant eval passes if the gate, prompts or models changed
- the UI shows block reasons and the next actions
- the docs are updated

**A content run** is done when its folder or record contains:
1. the plan
2. the tagged draft
3. the verification report, with every flag and its severity
4. either final copy (Approved, or Approved (override) with a logged reason), or a human-review record showing Blocked or Flagged in the review queue

Final copy is never written unless the gate passed or a human logged an override.

---

## 10. Pitfalls we've already hit

These are from the pilot. Don't repeat them.

- **Briefs authorizing facts.** A brief asked for certifications, customer names and speed claims that no doc supported. Check brief content through the gate like any other copy.
- **Mandated wording.** A brief's required H1 failed the gate. Show the reviewer the block and the alternatives; don't force it through.
- **Over-reading a decision.** A decision to deprioritize one deployment model was turned into a ban on a separate, verified claim. Apply decisions to exactly what they say.
- **Docs that are simply wrong.** Docs said the customer couldn't sign alone; the product owner said they can. Rulings beat docs, persist, and go back to the docs owner.
- **Colliding absolutes.** "No transaction can bypass policy controls" was true for the platform, but a documented recovery path signs outside it. Check claims against each other on the page.
- **Implied conclusions.** Two true sentences placed together implied a third that no claim supported. The gate checks what a passage implies, not just each sentence.
- **Dropped conditions.** Copy dropped a version number, a deployment model, or "(or software equivalent)". Each counts as overstatement.
- **Taglines hiding facts.** "Keep control" read as a claim about who controls the data. Make a deliberate call, and log it when a reviewer marks a line as positioning.
- **Non-converging revisions.** Each gate run checks the whole page fresh, and new facts bring new conflicts. Cap rounds, compare them, and roll back to the last approved version.
- **Stale writing aids.** Shared copywriting skills suggested contradicted claims and an old product name. Product facts come only from the registry.
- **Self-contradictory profiles.** One style profile named the product two different ways. Validate profiles before use.
- **Losing rulings on re-ingest.** A status change without a stored ruling is lost the next time the docs are snapshotted. Write the ruling, not just the status.
- **Accidental cloud sync.** A desktop sync client was copying confidential files to a personal drive. Data paths must be deliberate and visible.

---

## 11. Working in this repo

- **Read before you write.** Load the relevant schema, agent contract and existing code first.
- **Check the docs before asking product people.** For any product-fact question, search the product's truth sources; escalate only what the docs don't answer, and cite what they do say.
- **Ask first** before anything outward-facing or hard to undo:
  - pushing, opening PRs or deploying
  - running migrations on shared environments
  - sending data to external services
  - deleting data
  - running expensive eval or pipeline batches
- **Report results faithfully.** If an eval fails or a step was skipped, say so with the numbers.
