# Implementation notes (v1 build, 2026-10-01)

What exists, what was decided where the PRD left a question open, how it measures today, and what's still missing. The rules are in `CLAUDE.md`; this file only records the build.

## What's built

| Area | Where | Status |
|---|---|---|
| Schemas for every artifact (26) | `packages/schemas` | Done. Validated before every save. |
| Validator (schema subset + rules: quote <60 words and verbatim, high-risk confirmation, profile consistency, guardrail links, plan cites only verified claims) | `packages/validate` | Done |
| Registry: permanent IDs, deprecate-not-delete, rulings re-applied on every build, confirmation lapses if the quote changes, conflict detection (living-vs-changelog, absolute-vs-exception, contradiction), review queue, doc-correction notes, decisions → literal guardrails | `packages/registry` | Done |
| Gate: draft parsing, mechanical block rules that override a lenient verifier, combine, finalize, staleness, KB status, round archive, rollback, re-flag | `packages/gate` | Done |
| Store: SQLite metadata + filesystem objects, scoped by workspace at the data layer, path-traversal guard, no deletes of claims/rulings/sources/audit/content | `services/store` | Done |
| Ingest: MD, HTML, DOCX, PPTX, basic PDF, evidence JSON; stable source IDs per origin; versioned snapshots by sha256; docs-site import via llms.txt / sitemap / URL prefix with a manifest; local docs search (discovery only) | `services/ingest` | Done. Connectors are M4. |
| Orchestrator: resumable steps, one retry then loud failure, run and workspace budgets, parallel extraction and verification, 2-round auto-revision cap, human edit / directed revision / override / reject / mark-as-positioning, quick check, cost estimate | `services/orchestrator` | Done |
| Agents: 10 roles, each with an output schema, tool allowlist and model setting; Anthropic provider (tool-use loop) and an offline deterministic provider | `agents/` | Done. Anthropic path is tested against a mocked API only (see limits). |
| API: session login (PBKDF2), roles, workspace from the session only, CSRF header, background jobs with live step progress, audit log + CSV export | `services/api` | Done. SSO is M4. |
| UI: Products, Sources, Claims, Decisions, Style & positioning, Create, Review, Gaps, Quality & cost, Settings | `apps/web` | Done |
| Exports: Markdown, HTML, DOCX, internal "with citations"; approved or approved-override only | `services/actions.py` | Done. CMS push is v1.1. |
| Reports: gaps (proof points without claims, topics without docs, review backlog, doc corrections, open conflicts, unanswerable objections), quality, cost | `services/actions.py` | Done |
| Evals: gate (seeded from the registry + 46 hand-labeled golden sentences per fixture), style calibration (AUC + recommended threshold) | `evals/` | Done. `extraction/` and `e2e/` eval sets from ARCHITECTURE §7 are covered by unit tests, not separate eval suites. |
| Fixtures: two invented products of different kinds with every pilot pitfall planted (see each `TRAPS.md`) | `fixtures/products` | Done |
| Tests | `tests/` (83) | Pass |

## Decisions taken on open questions

These are build defaults, chosen to unblock v1. Each is easy to change.

| PRD §15 question | Default built | Why |
|---|---|---|
| 15.1 / 15.2 Hosting | **Local-first.** One process, bound to 127.0.0.1, data in `~/.vce/data`. The same code runs hosted behind a TLS proxy. | The pilot's sources were confidential. Local-first is the safe default, and it removes setup cost. |
| 15.3 Compliance reviewer | A separate `compliance` role. Only `compliance` or `admin` can confirm a high-risk claim. | It's easier to merge roles later than to split them. |
| 15.4 Evidence in v1 | Built, but **off by default** per workspace. Encrypted at rest only when `cryptography` + `VCE_EVIDENCE_KEY` are present, otherwise refused (fixtures can opt into plaintext with `VCE_ALLOW_PLAINTEXT_EVIDENCE=1`). | It keeps the handling burden opt-in. |
| 15.6 Model provider | Provider is configuration; per-role model in `product.models`. Defaults: Opus for writer and gate, Sonnet for extractors and checkers. | Model independence (PRD §10). The gate eval decides. |
| Storage (ARCH §5.1) | SQLite with every query keyed by `workspace_id`, filesystem objects under `/{workspace_id}/{product_id}/`. | Zero dependencies. Swap for Postgres + S3 for hosted scale. |

## Eval results (offline baseline)

Run with `bin/vce eval gate --fixture lumen --fixture shiftwell`. Files in `evals/runs/`.

| Product | Hallucination catch (≥95%) | False-block (≤10%) | Untagged detection (≥95%) | Style AUC (≥0.9) |
|---|---|---|---|---|
| Lumen Hub (tuned on) | 98.6% | 6.1% | 100% | 0.968 |
| Shiftwell (held out) | 97.3% | 9.1% | 100% | 1.000 |

**How to read these.** The offline verifier's rules were tuned against Lumen Hub's seeds and golden set (and an earlier second fixture). Before tuning they scored 93% catch, 9–17% false blocks and 78% untagged detection. So the Lumen numbers overstate how the rules would do on new copy.

Shiftwell was written after tuning, and the rules were not changed for it, so it is a held-out check. It still meets every target, but false blocks are close to the limit. Three true sentences were blocked because their wording differed from the claim. It isn't fully independent either: its sentences were written in the same format and by the same kind of process as Lumen's. Samples are small (21 true and 12 positioning sentences per product), so one sentence moves the false-block rate by about 3 points.

The release gate should be the model-backed verifier, measured on the same eval with `VCE_PROVIDER=anthropic`. That hasn't been run: there's no API key on this machine, and the run sends the fixture data to an external service.

The style eval scores on-brand chunks of the team's own copy against off-brand variants generated from them. It shows the scorer separates those variants (an AUC of 1.0 means they're easy to tell apart), not that it matches human judgment. Add labeled samples in `evals/style/<slug>/{on,off}/` to calibrate on real reviewer labels.

## Known limits

- **Offline agents are a baseline, not a writer.** The offline copywriter assembles claim text verbatim under positioning lines, so a landing page comes out around 110 words. It exercises the whole pipeline, but it isn't publishable copy.
- **Offline conflict detection misses some contradictions.** It finds all planted conflicts in both fixtures, but it relies on surface patterns (shared counted nouns, absolute vs exception wording, release-status words). Contradictions phrased differently, such as "only X" against a list of supported options, are missed. An LLM pass would catch more.
- **The offline positioning extractor needs the deck's heading format** (see `fixtures/products/*/sources/positioning/positioning.md`). Other formats fall back to the first paragraph only.
- **PDF parsing is basic.** Scanned or unusually encoded PDFs fail loudly. Export them to DOCX or text.
- **Docs search** is a local keyword search over snapshots. No adapter for a product's own search service yet.
- **Not built (M4 / v1.1):** SSO, connectors (Drive, Notion, Confluence, GitHub), CMS draft push, self-hosted packaging, multi-process deployment.
- **Live progress** is polled every 1.5 s, not streamed.
