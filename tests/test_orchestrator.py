import json

from tests.helpers import ADMIN, StoreCase, unittest
from agents.runtime import AgentError, OfflineProvider
from services import actions, orchestrator
from packages import gate


class FlakyProvider(OfflineProvider):
    """Fails a given role a set number of times."""
    def __init__(self, role, failures):
        self.role, self.left, self.calls = role, failures, 0

    def run(self, spec, payload, box, product=None):
        if spec["role"] == self.role:
            self.calls += 1
            if self.left > 0:
                self.left -= 1
                raise AgentError("simulated crash")
        return super().run(spec, payload, box, product)


class LenientVerifier(OfflineProvider):
    """A verifier that passes everything: the gate's code rules must still block what they can."""
    def run(self, spec, payload, box, product=None):
        out, usage = super().run(spec, payload, box, product)
        if spec["role"] == "verifier":
            for s in out["sentences"]:
                s.update(verdict="pass", reason=None)
            out["page_checks"] = []
        return out, usage


class OrchestratorTests(StoreCase):
    def brief(self, **kw):
        args = dict(content_type="landing-page", title="Room-level comfort", audience="Facilities directors",
                    goal="Book a demo", stage="problem-aware", notes="")
        args.update(kw)
        return actions.create_brief(self.ws, ADMIN, "lumen", **args)

    def test_ingest_builds_ready_knowledge_base(self):
        self.load("lumen")
        st = self.ws.get("kb-status", "lumen")
        self.assertEqual(st["state"], "ready")
        self.assertGreater(st["verified"], 50)
        kinds = {c["kind"] for c in self.ws.list("conflict", "lumen")}
        self.assertTrue({"living-vs-changelog", "absolute-vs-exception", "contradiction"} <= kinds)
        pack = self.ws.get("positioning-pack", "lumen")
        needs = [p for t in pack["value_themes"] for p in t["proof_points"] if p["status"] == "needs-claim"]
        self.assertTrue(needs)  # unsupported proof points become gaps, not claims
        prof = self.ws.get("style-profile", "lumen")
        self.assertIn("smart", prof["vocabulary"]["banned"])

    def test_no_truth_sources_blocks_generation(self):
        actions.create_product(self.ws, ADMIN, "Empty", "EMP", slug="empty")
        b = actions.create_brief(self.ws, ADMIN, "empty", "email", "Hi", "x", "y", "problem-aware")
        with self.assertRaises(orchestrator.RunFailed):
            orchestrator.content_run(self.ws, b["id"])

    def test_content_run_respects_revision_cap_and_archives_rounds(self):
        self.load("lumen")
        res = orchestrator.content_run(self.ws, self.brief()["id"])
        item = self.ws.get("content", res["report"]["run_id"] and self.ws.list("content", "lumen")[0]["id"])
        self.assertLessEqual(item["auto_revisions_used"], 2)
        self.assertLessEqual(len(item["rounds"]), 3)
        for r in item["rounds"]:
            self.assertTrue(self.ws.has_object(r["draft_ref"]))
            self.assertTrue(self.ws.has_object(r["report_ref"]))
        if item["live_version"]:
            final = self.ws.get_text(item["live_version"]["final_ref"])
            self.assertNotIn("[[", final)

    def test_lenient_verifier_cannot_pass_uncitable_claims(self):
        self.load("lumen")
        nr = next(c for c in self.ws.claims("lumen").values() if c["status"] == "needs-review")
        md = f"# Test\n\n{nr['text']} [[{nr['id']}]]\n"
        res = orchestrator.quick_check(self.ws, "lumen", md, provider=LenientVerifier())
        self.assertEqual(res["report"]["status"], "blocked")

    def test_failed_step_retries_once_then_fails_loudly(self):
        self.load("lumen")
        b = self.brief()
        p = FlakyProvider("strategist", 1)
        orchestrator.content_run(self.ws, b["id"], provider=p)
        self.assertEqual(p.calls, 2)
        p = FlakyProvider("strategist", 5)
        b2 = self.brief(title="Second")
        with self.assertRaises(orchestrator.RunFailed):
            orchestrator.content_run(self.ws, b2["id"], provider=p)
        self.assertEqual(p.calls, 2)
        run = [r for r in self.ws.list("run") if r.get("brief_id") == b2["id"]][0]
        self.assertEqual(run["status"], "failed")
        self.assertIn("strategist", run["error"])

    def test_verifier_failure_never_passes(self):
        self.load("lumen")
        with self.assertRaises(orchestrator.RunFailed):
            orchestrator.content_run(self.ws, self.brief()["id"], provider=FlakyProvider("verifier", 99))
        item = self.ws.list("content", "lumen")[0]
        self.assertIsNone(item["live_version"])

    def test_style_checker_failure_forces_flagged(self):
        self.load("lumen")
        res = orchestrator.content_run(self.ws, self.brief()["id"], provider=FlakyProvider("style-checker", 99))
        self.assertNotEqual(res["status"], "approved")

    def test_budget_stops_cleanly(self):
        self.load("lumen")
        w = self.store.get_workspace("ws-a")
        w["settings"]["run_budget_tokens"] = 1
        self.store.update_workspace(w)
        with self.assertRaises(orchestrator.BudgetExceeded):
            orchestrator.content_run(self.ws, self.brief()["id"])
        run = [r for r in self.ws.list("run") if r["kind"] == "content"][0]
        self.assertEqual(run["status"], "budget-stopped")

    def test_resume_continues_from_last_completed_step(self):
        self.load("lumen")
        b = self.brief()
        with self.assertRaises(orchestrator.RunFailed):
            orchestrator.content_run(self.ws, b["id"], provider=FlakyProvider("verifier", 2))
        run = [r for r in self.ws.list("run") if r.get("brief_id") == b["id"]][0]
        done_before = {s["name"] for s in run["steps"] if s["status"] == "done"}
        self.assertIn("strategist", done_before)
        counting = FlakyProvider("strategist", 0)
        res = orchestrator.resume(self.ws, run["id"], provider=counting)
        self.assertEqual(counting.calls, 0)  # the plan was not re-made
        self.assertIn(res["status"], ("approved", "flagged", "blocked"))
        self.assertEqual(self.ws.get("run", run["id"])["status"], "succeeded")
        item = self.ws.get("content", b["id"])
        self.assertLessEqual(item["auto_revisions_used"], 2)

    def test_override_requires_reason_and_is_distinct(self):
        self.load("lumen")
        b = self.brief(mandated_wording=[{"where": "H1", "text": "The only climate controller that never fails"}])
        orchestrator.content_run(self.ws, b["id"])
        rep = orchestrator.human_edit(self.ws, b["id"], "# The only climate controller that never fails\n\nTalk to us.\n", ADMIN["email"])
        self.assertEqual(rep["status"], "blocked")
        with self.assertRaises(ValueError):
            orchestrator.override(self.ws, b["id"], "  ", ADMIN["email"])
        rep = orchestrator.override(self.ws, b["id"], "Legal reviewed the H1 on 2026-10-01.", ADMIN["email"])
        self.assertEqual(rep["status"], "approved-override")
        item = self.ws.get("content", b["id"])
        self.assertEqual(item["live_version"]["status"], "approved-override")
        ev = [e for e in self.ws.list("audit") if e["action"] == "content.override"]
        self.assertEqual(ev[0]["reason"], "Legal reviewed the H1 on 2026-10-01.")

    def test_mandated_wording_goes_through_the_gate(self):
        self.load("lumen")
        b = self.brief(mandated_wording=[{"where": "H1", "text": "The only climate controller that cuts your heating bill in half"}])
        orchestrator.content_run(self.ws, b["id"])
        item = self.ws.get("content", b["id"])
        first = self.ws.get_json(item["rounds"][0]["report_ref"])
        self.assertTrue(any("only climate controller" in f.get("sentence", "") for f in first["flags"] if f["severity"] == "block"))

    def test_human_directed_round_not_counted_and_rollback(self):
        self.load("lumen")
        b = self.brief()
        orchestrator.content_run(self.ws, b["id"])
        item = self.ws.get("content", b["id"])
        used = item["auto_revisions_used"]
        orchestrator.human_directed_revision(self.ws, b["id"], 'remove "Talk to our team"', ADMIN["email"])
        item = self.ws.get("content", b["id"])
        self.assertEqual(item["auto_revisions_used"], used)
        self.assertEqual(item["rounds"][-1]["kind"], "human-directed")
        live_before = item["live_version"]
        rep = orchestrator.human_edit(self.ws, b["id"], "# Broken\n\nLumen Hub is the fastest controller ever made.\n", ADMIN["email"])
        self.assertEqual(rep["status"], "blocked")
        item = self.ws.get("content", b["id"])
        self.assertEqual(item["live_version"], live_before)

    def test_doc_wrong_ruling_reflags_approved_content(self):
        self.load("lumen")
        b = self.brief()
        orchestrator.content_run(self.ws, b["id"])
        item = self.ws.get("content", b["id"])
        if not item["live_version"]:
            orchestrator.override(self.ws, b["id"], "Test approval", ADMIN["email"])
            item = self.ws.get("content", b["id"])
        cid = item["live_version"]["cited_ids"][0]
        actions.rule_claim(self.ws, ADMIN, "lumen", cid, "doc-wrong", "Product owner says this is wrong.")
        item = self.ws.get("content", b["id"])
        self.assertEqual(item["status"], "flagged")
        self.assertEqual(item["reflags"][0]["claim_id"], cid)
        with self.assertRaises(ValueError):
            actions.export(self.ws, ADMIN, b["id"])
        # the ruling survives a full re-ingest
        orchestrator.ingest_product(self.ws, "lumen")
        self.assertEqual(self.ws.get("claim", cid)["status"], "deprecated")
        notes = actions.gaps_report(self.ws, "lumen")["doc_corrections"]
        self.assertEqual(notes[0]["ruling"], "Product owner says this is wrong.")

    def test_source_change_marks_kb_stale(self):
        self.load("lumen")
        new_src, changed, _ = actions.add_source(self.ws, ADMIN, "lumen", "truth", "overview.md",
                                                 b"# Changed\nEverything about this page is different now.\n")
        self.assertTrue(changed)
        self.assertEqual(new_src["id"], "tru-overview-md")
        rep = orchestrator.mark_stale(self.ws, "lumen", [new_src["id"]])
        st = self.ws.get("kb-status", "lumen")
        self.assertEqual(st["state"], "stale")
        self.assertTrue(rep["claims"])
        orchestrator.ingest_product(self.ws, "lumen")
        self.assertEqual(self.ws.get("kb-status", "lumen")["state"], "ready")

    def test_evidence_counts_reproduce_and_stay_needs_review(self):
        self.load("lumen")
        ev = [c for c in self.ws.claims("lumen").values() if c["category"] == "market-evidence"]
        self.assertTrue(ev)
        self.assertTrue(all(c["status"] == "needs-review" and c["count"] for c in ev))

    def test_evidence_with_names_is_discarded(self):
        out = {"source_id": "evi-x", "claims": [], "buyer_language": [{"phrase": "spoke with Jane Doe", "count": 3}]}
        with self.assertRaises(AgentError):
            orchestrator.verify_evidence(out, [], {"name": "Acme", "company": ""})

    def test_decision_edit_shows_diff_and_updates_profile(self):
        self.load("lumen")
        d, diff = actions.save_decision(self.ws, ADMIN, "lumen", "Never use the word 'effortless' in copy.")
        self.assertTrue(diff["added"])
        self.assertIn("effortless", self.ws.get("style-profile", "lumen")["vocabulary"]["banned"])
        pack = self.ws.get("positioning-pack", "lumen")
        self.assertIn(d["id"], {g["decision_id"] for g in pack["guardrails"]})

    def test_deprioritize_decision_is_literal(self):
        self.load("lumen")
        claims = self.ws.claims("lumen")
        offline = [c for c in claims.values() if "last synchronized schedule" in c["text"]]
        self.assertTrue(offline)
        self.assertTrue(all(c["status"] == "verified" and not c["deprioritized"] for c in offline))


if __name__ == "__main__":
    unittest.main()
