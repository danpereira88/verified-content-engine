# PRD: Verified Content Engine (general-purpose platform)

**Status:** Draft v1
**Last updated:** 2026-10-01
**Builds on:** an internal pilot of the same approach, run on two products in September–October 2026

---

## 1. Summary

A tool any marketing team can use to produce product-marketing content that is accurate, on-brand and on-message for any product. The user connects the product's documentation, example copy and positioning material. The system turns them into a governed knowledge base, writes content from it, and blocks every sentence it can't trace to a verified source before anything ships.

The pilot proved the core loop on two products. This PRD turns that single-user, single-company, local tool into a product that works for any team, any product and any content type, without an engineer in the loop.

---

## 2. Problem

Marketing teams write about products faster than they can check the facts. The result is familiar:

- **Invented or overstated claims.** Copy says "the only", "the first" or "fully compliant" when the product docs say something narrower. In regulated industries this is a legal risk, not just an embarrassment.
- **Drift from the source.** Product docs change, and the marketing copy doesn't.
- **Inconsistent voice and positioning.** Each writer interprets the brand and the positioning differently.
- **Review doesn't scale.** Fact-checking depends on an expert reading every line, so it gets skipped.
- **Every new product starts from zero.** Writers have to be re-briefed from scratch.

Generic AI writing tools make the first problem worse. They write fluent copy with no idea which statements are true.

---

## 3. What the pilot taught us

The pilot ran end to end on two products with 1,000–3,000 verified claims each. These findings shape the requirements below.

| Finding | Evidence from the pilot | What it means for the platform |
|---|---|---|
| The gate works. | In a seeded eval, it caught 100% of false, overstated and partially supported sentences and 100% of untagged factual sentences. It wrongly blocked 3.9% of true ones. | The hard gate is the product's core. Keep it strict and measurable. |
| First drafts are rarely clean. | Both landing pages failed their first gate run with 19 blocks each. One passed after two automatic revisions. The other needed a third, human-directed round. | Revision and human review are the normal path, not an edge case. The UI should be built around them. |
| Revisions don't always converge. | Each gate run checks the whole page fresh. New facts introduce new conflicts: three later attempts to improve an approved page were blocked and rolled back. | Keep the last approved version live. Cap revisions. Show what changed between rounds. |
| The docs can be wrong. | A docs page said customers can't perform a key action on their own. The user, who knows the product, ruled it false, and other doc pages agreed with the user. | Human rulings must be able to override a doc claim, survive re-ingestion, and be reported back to the docs owner. |
| Doc pages contradict each other. | A feature was "beta" on its current page and "fully released" in an older changelog. | Detect conflicts and show them to the user. Don't silently pick a side. |
| Extractors over-read decisions. | A decision to deprioritize one deployment model was stretched into a ban on a separate, verified claim. | Store decisions verbatim and apply them literally. Every rule must show where it came from. |
| Briefs and web pages aren't truth. | Briefs asked for certifications, customer names and speed claims that no doc supported. One brief's mandated H1 was blocked. | Brief instructions are checked like any other claim. A brief can never authorize a fact. |
| Shared writing aids carry stale facts. | Two copywriting skill files suggested claims that the registry contradicted. | Only the product's own verified knowledge reaches the copy. Detect stale facts in prompts and templates. |
| Absolute statements collide. | "No transaction can bypass policy controls" was true of the platform, but conflicted with a documented self-recovery path. | Check claims against each other, not just sentence by sentence. |
| Style profiles can contradict themselves. | One profile named the product two different ways in different sections. | Validate each profile for internal consistency before using it. |
| The style score needs calibrating. | With labeled samples, the style checker separated on-brand from off-brand copy well (AUC 0.96–0.97). Thresholds were set from that data. | Calibrate each product's threshold from its own samples, not a global default. |
| Some proof gaps can't be fixed in copy. | The synthetic buyer stayed at "maybe" on every round because certifications and customer proof didn't exist in the sources. | Report missing proof to the product owner as a list of gaps, rather than letting writers fill it. |
| Confidential material leaks easily. | Call transcripts with prospect names were being copied to a cloud drive by a desktop sync tool. | Data handling has to be deliberate, with clear tenancy, retention and export rules. |
| It isn't cheap. | A single landing page used roughly 1–3M model tokens across all agents. | Budgets, cost display and cheaper modes are requirements, not extras. |

---

## 4. Goals

1. **Any product.** A team can onboard a new product in under an hour, without an engineer.
2. **Verified by default.** Every factual sentence in approved content traces to a verified source claim.
3. **The team's voice.** Content matches a style learned from the team's own examples, with a calibrated pass mark.
4. **The team's positioning.** Content follows the product's positioning, personas and decisions.
5. **Fast review.** A reviewer can see exactly what was blocked, why, and how to fix it, in one screen.
6. **Clear ownership of truth.** Every fact, ruling and override is attributed, dated and auditable.

### Non-goals (v1)

- Publishing directly to a CMS or website. Humans approve and export.
- Images, video or visual page design.
- Translation and localization.
- Live crawling of the open web. Sources are uploaded, imported as snapshots, or connected.
- Legal or regulatory sign-off. The tool can route compliance claims to a reviewer, but it doesn't certify anything.

---

## 5. Users

| Role | What they do |
|---|---|
| **Marketer (editor)** | Requests content, edits drafts, resolves flags. |
| **Reviewer / approver** | Approves or overrides blocked content. Can be the same person as the editor on small teams. |
| **Product SME** | Confirms or rejects claims, rules on doc conflicts, and answers "is this true?" questions. |
| **Compliance reviewer** | Confirms claims in high-risk categories (compliance, metrics, pricing, competitive, customer references). |
| **Workspace admin** | Manages products, members, connectors, budgets and data settings. |

The pilot had one user in every role. The platform must support these as separate roles, while letting small teams assign several roles to one person.

---

## 6. Core concepts

**Workspace.** One team or company. Holds members, products, budgets and data settings. Data never crosses workspaces.

**Product.** Anything with documentation: software, a hardware device, a financial product, a service. Each product has its own claim prefix, sources, knowledge base and settings.

**Sources.** Every source belongs to one of four types. The type controls what a source is allowed to do.

| Source type | Examples | Can it back a factual claim? |
|---|---|---|
| **Truth** | Product docs, specs, API references, release notes | Yes. This is the only type that can. |
| **Style** | Published web pages, approved emails, example copy | No. It only teaches voice. |
| **Positioning** | Messaging decks, briefs, personas, positioning canvases | No. It only shapes angle, audience and emphasis. |
| **Evidence** (optional) | Call transcripts, survey data | Only market-evidence claims with reproducible counts, and only after confirmation. Never product facts. Never quoted in copy. |

**Claims registry.** The list of atomic, cited facts that copy is allowed to state about a product. Each claim has a permanent ID, the exact source quote and location, a category, a confidence level and a status: `verified`, `needs-review` or `deprecated`. Only verified claims can be cited.

**Rulings.** A human decision on a claim or a conflict: confirm, reject, deprioritize, or "this doc is wrong". Rulings are stored verbatim with author and date. They survive re-ingestion, and a re-ingest can never silently reverse one.

**Decisions log.** Positioning and vocabulary rules from the team, quoted word for word. Examples: "this word is banned", "use this product name", "lead with this model". Every derived guardrail links back to the decision it came from.

**Style profile.** Voice, cadence, vocabulary, naming, formatting habits and a scoring rubric, all learned from style sources. It carries a pass mark calibrated for that product.

**Positioning pack.** Positioning, messaging, personas, objections, competitive alternatives and awareness stages, extracted from positioning sources. Each proof point either links to a claim or is marked as needing one.

**Brief.** A request for one piece of content: product, content type, audience, goal, awareness stage and notes.

**Verification report.** The combined verdict for a draft: the gate result for every sentence, the other checkers' scores and flags, the revision history, and any override.

---

## 7. Principles

1. **Only truth sources can make a fact.** Briefs, decks, web pages, writing aids and model knowledge cannot.
2. **Human rulings outrank documents.** When a qualified person says a doc is wrong, the ruling wins, is logged, and is sent back to the docs owner.
3. **Conflicts are shown, never resolved silently.** When two truth sources disagree, the system presents both and waits for a ruling. Until then it may default to the newest living page, and must say so.
4. **Decisions are applied literally.** The system never stretches a decision beyond its words.
5. **Blocking is a success.** A blocked draft means the gate did its job. A crashed agent is the failure.
6. **The last approved version stays live.** A failed revision never replaces approved content.
7. **Every action is attributable.** Who confirmed, rejected, overrode, approved or exported, and when.

---

## 8. Functional requirements

### 8.1 Product onboarding

- Create a product with a name, a claim prefix and optional settings: content types, synthetic buyer persona and high-risk categories.
- Use a guided checklist: add truth sources, add style examples, add positioning material, build the knowledge base, review claims.
- Show readiness for each source type. Missing truth sources block generation. Missing style or positioning sources show a warning.

### 8.2 Source ingestion

- **Upload** PDF, DOCX, PPTX, Markdown, HTML and plain text.
- **Import a docs site** as a snapshot, using llms.txt, a sitemap or a URL prefix. Keep a manifest with the URL, fetch time and hash for every page. Refresh only on request.
- **Connectors** (v1.1): Google Drive, Notion, Confluence, GitHub. These are read-only and import snapshots, never live links.
- **Docs search** (optional): if a product's docs offer a search service, use it to find pages, check coverage and support review. Search results are never citable. Every quote comes from the snapshot.
- **Staleness:** when a source changes, mark the knowledge base stale and show which claims and content items are affected.

### 8.3 Claims extraction and review

- Extract atomic claims from truth sources. Each claim must have an exact quote under 60 words and a location in the source.
- Ingest high-risk categories as `needs-review` by default. Low-confidence claims are also `needs-review`.
- **Review queue:** claims grouped by theme. Each shows its quote and source side by side, with Confirm, Reject and Deprioritize actions, an optional note, and bulk actions for low-risk themes.
- **Conflict detection:**
  - between claims that contradict each other
  - between absolute claims and documented exceptions (the "cannot be bypassed" vs "can self-recover" case)
  - between a newer living page and an older changelog
- **"This doc is wrong" ruling:** deprecates the claim with the reviewer's words and creates a correction note for the docs owner.
- **Coverage report:** topics the docs should cover but don't, such as pricing.
- **Permanent IDs:** never renumber or reuse an ID. Unsupported claims become deprecated, not deleted. Any approved content citing a deprecated claim is re-flagged automatically.

### 8.4 Decisions, style and positioning

- **Decisions log:** add rules in plain language. The system stores them verbatim and shows every guardrail derived from each one. Editing a decision re-derives its guardrails and shows the diff.
- **Style profile:**
  - extracted from style sources
  - requires a minimum corpus (default about 1,500 words across 3 pieces)
  - validated for internal consistency, for example one product name, not two
  - editable through the structured profile, not the rendered view
- **Style calibration:** build a labeled set from approved copy plus generated off-brand samples. Score it and recommend a threshold for the admin to accept. Re-run after the profile changes.
- **Positioning pack:** extracted from positioning sources. Every proof point is linked to a claim or marked "needs claim". Proof points that need claims feed the gaps report (8.9).

### 8.5 Content requests and generation

- **Content types are templates.** v1 ships landing page, one-pager, email, blog post, FAQ and release note. Admins can add types with a section outline, length range and checklist.
- **Brief form:** product, type, audience (suggested from the personas), goal, awareness stage, notes and optional mandated wording.
  - Mandated wording is checked like any other copy. If it fails the gate, the reviewer sees why and can choose an alternative or override.
- **Strategy step:** framework, angle, persona, stage, outline, and the specific claims to feature in each section. It lists proof gaps so the writer doesn't fill them.
- **Draft step:** every factual sentence, heading, card title and caption is tagged with claim IDs. The internal claim map and missing-claims list stay out of exported copy.
- **Writing aids:** prompt libraries and skills may shape structure and tone, but any product fact they carry is ignored unless the registry has it. Flag writing aids whose facts contradict the registry.

### 8.6 Verification

- **Hard gate (always on):** see §9.
- **Checkers (configurable per product):**
  - style compliance, scored against the calibrated threshold
  - best practice: structure, CTA, positioning fit, awareness-stage match
  - synthetic buyer: an optional persona reaction
- **Run in parallel** and combine into one verdict:
  - any gate block → **Blocked**
  - else any high-severity flag → **Flagged**
  - else → **Approved**
- **Deterministic decision:** the combining and final-copy steps are code, not model output.

### 8.7 Revision and review

- **Automatic revision:** up to 2 rounds using the flags. Each round is archived with its draft, checks and report.
- **After that, human review.** A reviewer can:
  - **edit** the copy directly, then re-verify
  - **direct a revision** with written instructions. This is logged as human-directed and doesn't count against the automatic cap.
  - **add a source.** The new claim enters as needs-review, the reviewer confirms it, and the draft is re-verified. Adding a source never clears a block by itself.
  - **override** with a required written reason. The status becomes **Approved (override)**, never plain Approved.
  - **reject** the draft.
- **Round comparison:** a side-by-side diff of drafts and verdicts between rounds, showing which blocks are new and which are fixed.
- **Rollback:** if a revision of approved content fails, the approved version stays live and the failed round is kept in history.

### 8.8 Export and integrations

- Export Markdown, HTML and DOCX, with claim tags stripped, from approved or override-approved content only.
- Optional "with citations" export for internal review: each sentence followed by its claim and source quote.
- v1.1: push to CMS or document tools as drafts, never as published pages.

### 8.9 Reporting

- **Gaps report for product owners:**
  - proof points without claims
  - topics with no docs
  - claims needing review
  - doc corrections from rulings
  - the buyer objections the docs can't answer
- **Quality dashboard:**
  - gate eval results
  - override rate
  - average revision rounds
  - blocks by type
  - style scores over time
- **Cost dashboard:** tokens and spend per run, per product and per workspace.

### 8.10 Evals

- **Gate eval:** a seeded set per product (true, false, overstated, partial, untagged, not citable and positioning sentences) is built from that product's registry. Run it on demand and after any model or prompt change.
- **Style eval:** calibrates the threshold (see 8.4).
- Results are stored and compared release to release. A drop below target blocks a model or prompt upgrade.

---

## 9. The gate

**Block** a sentence if any of these is true:

- it makes a factual assertion with no claim ID
- it cites a claim that is missing, needs review, or is deprecated
- it contradicts the cited claim
- the claim supports only part of it
- it overstates the claim: superlatives ("only", "first", "fastest"), broader scope, stronger certainty, an implied comparison, or a dropped condition such as a version or a deployment model
- it combines claims into a conclusion none of them states, for example "you can't restore the backup without the hardware module"
- it cites a low-confidence claim in a high-risk category

**Flag, but don't block:**

- a low-confidence claim in a lower-risk category
- tension between claims on the same page, where each sentence passes on its own
- style deviation
- weak positioning
- awareness-stage mismatch
- a tepid synthetic-buyer reaction

**Positioning language** (tone, framing, adjectives, questions) isn't gated, but it is checked for style and positioning. A line that hides a checkable fact inside a tagline is treated as a factual assertion. Reviewers can mark a specific line as positioning, which is logged.

The verifier classifies every sentence itself and never trusts the writer's tags.

---

## 10. Non-functional requirements

| Area | Requirement |
|---|---|
| **Tenancy and access** | Strict workspace isolation. Role-based permissions (§5). SSO for enterprise workspaces. |
| **Data handling** | Customer sources are never used to train models. A retention setting covers sources, drafts and run logs. Evidence sources, such as call data, are encrypted and access-restricted, and are never quoted or named in output. |
| **Deployment** | Hosted multi-tenant SaaS by default, plus a self-hosted or local mode for teams that can't send sources off their machines. |
| **Agent permissions** | Agents can read only the product's own knowledge, write only its own working files, and run only approved tools. Claim rulings, overrides and approvals are human actions performed by the application, never by an agent. |
| **Cost control** | Budgets per workspace and per run, with a hard stop. A cost estimate before each run. A cheaper "quick check" mode that runs only the gate. |
| **Reliability** | Agents that stall or crash are retried once, then the run fails loudly with context. Runs can resume from the last completed step. |
| **Latency** | Brief to reviewable draft in 15 minutes or less for a landing page. Live per-agent progress throughout. |
| **Determinism** | All knowledge artifacts and reports use fixed schemas and are validated before use. Gate decisions and final copy are produced by code from the checker outputs. |
| **Audit** | Every ruling, override, approval, export, decision edit and source change is logged with who and when, and can be exported. |
| **Model independence** | Agents are defined by role and schema, so the underlying model can change. The gate eval must pass before a model change ships. |

---

## 11. Architecture (summary)

The architecture stays as proven in the pilot, generalized:

- **Orchestrator:** owns the flow, runs independent steps in parallel, enforces caps and rules, and calls deterministic scripts for decisions.
- **Ingestion agents:** claims, style, positioning, and optionally evidence. Each writes one record per source file plus a combined master, in fixed schemas.
- **Generation agents:** strategist, then copywriter.
- **Verification agents:** gate, style, best practice and synthetic buyer, run in parallel.
- **Deterministic services:**
  - schema validation
  - registry build
  - knowledge-base status and staleness
  - report combining
  - finalize and export
  - claim rulings
  - overrides
  - evals
- **Storage:** per-workspace, per-product artifacts with version history. The pilot's file layout becomes object storage plus a metadata database.
- **UI:** the pilot's four screens (Products, Sources, Create, Review), plus Claims, Decisions, Gaps and Settings.

---

## 12. Success metrics

| Metric | Target |
|---|---|
| Claim traceability in approved content | 100% |
| Hallucination catch rate (gate eval) | ≥95% |
| False-block rate (gate eval) | ≤10% |
| Untagged-assertion detection (gate eval) | ≥95% |
| Style separation (style eval AUC) | ≥0.9 per product |
| Time to onboard a product | Under 1 hour of user time, excluding claim review |
| Brief to reviewable draft | ≤15 minutes |
| Drafts approved within 2 automatic revisions | Tracked. Pilot baseline: 1 of 2. |
| Override rate | Tracked, not targeted. A rising rate means a thin registry or an over-strict gate. |
| Reviewer time per approved asset | Baseline on the first 10 assets, then reduce. |
| Cost per approved asset | Baseline from the pilot, then reduce. |

---

## 13. Milestones

1. **M1. Multi-product foundation.**
   - workspaces, roles and product onboarding
   - upload and docs-site import
   - claims extraction with the review queue, rulings and conflict detection
   - decisions log
2. **M2. Generation and gate.**
   - content type templates
   - strategy, draft and the full gate
   - deterministic report and finalize
   - automatic revision with the round archive and rollback
3. **M3. Review and quality.**
   - review screen with edit, direct revision, add a source, override and round comparison
   - style calibration
   - gate and style evals
   - gaps report
4. **M4. Scale.**
   - connectors
   - cost budgets and quick-check mode
   - audit export
   - SSO
   - self-hosted mode
   - CMS draft push

---

## 14. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Thin or wrong documentation gives a thin registry. | Coverage and gaps reports, "doc is wrong" rulings fed back to the docs owner, and blocking rather than guessing. |
| Over-blocking frustrates users. | Clear block reasons with suggested fixes, add-a-source, human-directed revisions, and logged overrides. |
| Override becomes the default path. | Required reason, a distinct status, and the override rate shown on the dashboard. |
| Revisions don't converge and cost climbs. | Revision cap, rollback to the last approved version, round comparison, and per-run budgets. |
| Model or prompt changes weaken the gate. | The gate eval must pass before any change ships. |
| Confidential sources leak. | Workspace isolation, encryption, retention controls, no training on customer data, and a local mode. |
| Generic writing aids reintroduce false facts. | Product facts come only from the registry, and stale facts in writing aids are flagged. |
| Style overfits a small corpus. | Minimum corpus, consistency validation, and per-product calibration. |

---

## 15. Open questions

1. **Who is it for?** An internal tool for every team at one company, or a commercial product for any company? This changes tenancy, pricing, SSO priority and the hosted vs. self-hosted default.
2. **Hosting default.** Hosted SaaS, or local-first with an optional hosted mode? The pilot was local-only because its sources were confidential.
3. **Compliance reviewers.** Is a separate compliance-reviewer role required in v1, or can it be a permission on the SME role?
4. **Evidence sources.** Should call and survey data be in v1 at all, given the handling burden?
5. **Pricing model**, if commercial: per seat, per product, per approved asset, or usage-based?
6. **Model provider.** One provider, or a choice per workspace? Either way, the gate eval is the release check.
7. **Export targets for v1.1.** Which CMS and document tools matter most?
