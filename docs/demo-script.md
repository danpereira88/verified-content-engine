# Demo script (about 8 minutes)

Setup, before presenting:

```bash
bin/demo ~/vce-demo-data          # note the password it prints
VCE_DATA_DIR=~/vce-demo-data bin/vce serve
```

Open http://127.0.0.1:8780 and sign in as admin@example.test. Use a browser window at least 1000px wide.

## 1. The problem (30 s)

"AI writers produce fluent copy with no idea what's true. This tool blocks every sentence it can't trace to the product's own docs."

## 2. Products (1 min)

- **Products** shows two invented products of different kinds: a climate controller (Lumen Hub) and a scheduling app (Shiftwell).
- Point at the readiness card: the verified and needs-review claim counts, and the onboarding checklist.

## 3. The knowledge base (2 min)

- **Sources**: docs are truth sources; web copy and decks only shape style and positioning, never facts.
- **Claims → Review queue**: each claim sits next to its exact source quote. High-risk claims (compliance, metrics) wait for a human. Confirm one.
- **Claims → Conflicts** (Lumen): "beta" on the current page vs "generally available" in an old changelog. The tool shows both and labels its interim pick as a default, never a ruling. Also: 32 vs 64 sensors, and "no change can bypass approval" vs an emergency override.
- **Decisions**: team rules stored word for word, each with the guardrail it produced.

## 4. A content run (2 min)

- **Review** → "Room-level comfort for facilities teams".
- Select **Round 1**. It was blocked: the brief's mandated H1 ("The only climate controller...") and the tagline "Never lose a reading" are red. Click one: the reason, the explanation and a suggested fix.
- Select **Round 2**: the copywriter revised from the flags and it passed. Every factual line carries a claim ID.
- **Compare rounds**: which blocks were fixed.
- Export the final copy: the tags are stripped.

## 5. Human review (1.5 min)

- Open **"Fill open shifts faster"** (Shiftwell). It's Flagged after two automatic revisions, so a person decides now.
- Show the actions: edit, direct a revision, add a source, override.
- Override needs a written reason, and the status becomes **Approved (override)**, never plain Approved. Show it in **Settings → Audit log**.

## 6. Proof it works (1 min)

- **Quality & cost**: run the gate eval, or show the table from `docs/writeup.md`: catch ≥95%, false blocks ≤10%, untagged facts 100%, including on a held-out product.
- **Gaps**: what the docs owner has to add, such as pricing and certifications the positioning claims but the docs don't support.

## Close (30 s)

"The model writes; code decides. Nothing ships unless every fact traces to a verified source, or a named person logged why."
