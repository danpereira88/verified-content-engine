from tests.helpers import claim, unittest
from packages import gate

CLAIMS = {"ACME-001": claim("ACME-001", "Acme Box stores data for 30 days."),
          "ACME-002": claim("ACME-002", "Acme Box is SOC 2 compliant.", status="needs-review", category="compliance"),
          "ACME-003": claim("ACME-003", "Acme Box exports CSV.", status="deprecated"),
          "ACME-004": claim("ACME-004", "Acme Box has a 99.9% SLA.", category="metric", confidence="low")}
HR = {"compliance", "metric"}
MD = "# Calm data\n\nAcme Box stores data for 30 days. [[ACME-001]]\n\nTalk to us.\n"


def verdicts(md, overrides=None):
    units = gate.parse_draft(md)
    out = []
    for u in units:
        v = {"index": u["index"], "text": u["text"], "section": u["section"], "classification": "positioning",
             "cited_ids": [], "relevant_ids": [], "verdict": "pass", "reason": None, "explanation": "", "suggested_fix": ""}
        v.update((overrides or {}).get(u["index"], {}))
        out.append(v)
    return units, {"draft_hash": gate.draft_hash(md), "sentences": out, "page_checks": []}


def combine(md, verdict_obj, units, checkers=None, enabled=None, override=None, marks=()):
    return gate.combine(run_id="run-1", round_no=1, round_kind="initial", md=md, units=units, verdicts=verdict_obj,
                        claims=CLAIMS, high_risk=HR, checker_reports=checkers or {}, enabled=enabled or {},
                        auto_revisions_used=0, override=override, positioning_marks=marks)[0]


class GateTests(unittest.TestCase):
    def test_parse_units(self):
        units = gate.parse_draft("# Title [[ACME-001]]\n\nOne. Two [[ACME-001]].\n\n- item one\n- item two\n")
        self.assertEqual([u["kind"] for u in units], ["heading", "sentence", "sentence", "list-item", "list-item"])

    def test_approved_when_all_pass(self):
        units, v = verdicts(MD)
        self.assertEqual(combine(MD, v, units)["status"], "approved")

    def test_missing_gate_result_is_blocked(self):
        units, _ = verdicts(MD)
        rep = combine(MD, None, units)
        self.assertEqual(rep["status"], "blocked")

    def test_gate_result_for_other_draft_is_blocked(self):
        units, v = verdicts(MD)
        v["draft_hash"] = "f" * 64
        self.assertEqual(combine(MD, v, units)["status"], "blocked")

    def test_unclassified_sentence_blocks(self):
        units, v = verdicts(MD)
        v["sentences"] = v["sentences"][:1]
        rep = combine(MD, v, units)
        self.assertEqual(rep["status"], "blocked")

    def test_code_overrides_a_lenient_verifier(self):
        for cid, reason in (("ACME-002", "needs-review"), ("ACME-003", "deprecated"), ("ACME-099", "missing-claim"),
                            ("ACME-004", "high-risk-low-confidence")):
            md = f"# T\n\nAcme Box claim. [[{cid}]]\n"
            units, v = verdicts(md)
            rep = combine(md, v, units)
            self.assertEqual(rep["status"], "blocked", cid)
            self.assertEqual([f["reason"] for f in rep["flags"] if f["severity"] == "block"], [reason])

    def test_flag_high_severity(self):
        units, v = verdicts(MD)
        rep = combine(MD, v, units, {"style-checker": {"checker": "style-checker", "status": "ok", "score": 0.4, "passed": False,
                                                       "flags": [{"severity": "high", "issue": "Banned term"}]}},
                      {"style-checker": True})
        self.assertEqual(rep["status"], "flagged")

    def test_unavailable_checker_prevents_auto_approval(self):
        units, v = verdicts(MD)
        rep = combine(MD, v, units, {}, {"style-checker": True, "best-practice-auditor": True})
        self.assertEqual(rep["status"], "flagged")
        self.assertEqual(sorted(rep["checkers_missing"]), ["best-practice-auditor", "style-checker"])

    def test_synthetic_buyer_failure_is_optional(self):
        units, v = verdicts(MD)
        rep = combine(MD, v, units, {}, {"synthetic-buyer": True})
        self.assertEqual(rep["status"], "approved")
        self.assertEqual(rep["checkers_missing"], ["synthetic-buyer"])

    def test_override_only_for_same_draft(self):
        units, v = verdicts(MD, {1: {"verdict": "block", "reason": "overstated", "explanation": "x"}})
        ov = {"by": "r@example.test", "at": "2026-01-01T00:00:00Z", "reason": "Legal approved", "draft_hash": gate.draft_hash(MD)}
        self.assertEqual(combine(MD, v, units, override=ov)["status"], "approved-override")
        ov["draft_hash"] = "0" * 64
        self.assertEqual(combine(MD, v, units, override=ov)["status"], "blocked")

    def test_positioning_mark_clears_only_untagged_blocks(self):
        md = "# T\n\nNever lose a reading.\n\nAcme Box stores data forever. [[ACME-001]]\n"
        units, v = verdicts(md, {1: {"verdict": "block", "reason": "untagged", "explanation": "x"},
                                 2: {"verdict": "block", "reason": "overstated", "explanation": "x"}})
        marks = [{"sentence": "Never lose a reading.", "by": "r", "at": "2026-01-01T00:00:00Z"},
                 {"sentence": "Acme Box stores data forever.", "by": "r", "at": "2026-01-01T00:00:00Z"}]
        rep = combine(md, v, units, marks=marks)
        self.assertEqual(rep["block_count"], 1)
        self.assertEqual(len(rep["positioning_marks"]), 2)

    def test_finalize_strips_tags_and_requires_approval(self):
        units, v = verdicts(MD)
        rep = combine(MD, v, units)
        self.assertNotIn("[[", gate.finalize(MD, rep))
        with self.assertRaises(gate.GateError):
            gate.finalize(MD, dict(rep, status="blocked"))
        with self.assertRaises(gate.GateError):
            gate.finalize(MD + "x", rep)

    def test_rollback_keeps_last_approved_version(self):
        item = gate.new_content_item({"id": "b1", "product_id": "p"})
        ok = {"status": "approved", "block_count": 0}
        gate.apply_result(item, {"round": 1, "kind": "initial", "draft_ref": "d1", "report_ref": "r1", "created_at": "t"}, ok, "f1", ["ACME-001"])
        bad = {"status": "blocked", "block_count": 3}
        gate.apply_result(item, {"round": 2, "kind": "edit", "draft_ref": "d2", "report_ref": "r2", "created_at": "t"}, bad, "", [])
        self.assertEqual(item["live_version"]["final_ref"], "f1")
        self.assertEqual(item["status"], "approved")
        self.assertEqual([r["status"] for r in item["rounds"]], ["approved", "blocked"])

    def test_reflag_when_cited_claim_is_deprecated(self):
        item = gate.new_content_item({"id": "b1", "product_id": "p"})
        gate.apply_result(item, {"round": 1, "kind": "initial", "draft_ref": "d", "report_ref": "r", "created_at": "t"},
                          {"status": "approved", "block_count": 0}, "f", ["ACME-001"])
        claims = dict(CLAIMS, **{"ACME-001": dict(CLAIMS["ACME-001"], status="deprecated", status_reason="doc-wrong")})
        changed = gate.reflag([item], claims)
        self.assertEqual(len(changed), 1)
        self.assertEqual(item["status"], "flagged")
        self.assertFalse(gate.can_export(item))
        self.assertEqual(gate.reflag([item], claims), [])  # idempotent

    def test_revision_cap(self):
        self.assertTrue(gate.needs_revision({"status": "blocked"}, 1))
        self.assertFalse(gate.needs_revision({"status": "blocked"}, 2))
        self.assertFalse(gate.needs_revision({"status": "approved"}, 0))

    def test_staleness(self):
        out = gate.staleness(CLAIMS, {"tru-doc": "Acme Box stores data for 30 days."},
                             [{"id": "b1", "live_version": {"cited_ids": ["ACME-002"]}}], [])
        self.assertIn("ACME-002", out["claims"])
        self.assertNotIn("ACME-001", out["claims"])
        self.assertEqual(out["content_items"], ["b1"])


if __name__ == "__main__":
    unittest.main()
