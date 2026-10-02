from tests.helpers import claim, unittest
from packages.validate import ValidationError, check, validate


class ValidateTests(unittest.TestCase):
    def test_schema_errors_are_reported(self):
        errs = validate("brief", {"id": "x"})
        self.assertTrue(any("missing required 'title'" in e for e in errs))

    def test_claim_id_pattern(self):
        c = claim("acme-1")
        self.assertTrue(validate("claim", c))
        self.assertEqual(validate("claim", claim("ACME-001"), claim_prefix="ACME"), [])

    def test_quote_must_be_under_60_words(self):
        c = claim("ACME-001", quote=" ".join(["word"] * 60))
        self.assertIn("under 60 words", " ".join(validate("claim", c)))

    def test_quote_must_be_verbatim_in_snapshot(self):
        rec = {"source_id": "tru-doc", "summary": "", "claims": [{"text": "A", "quote": "Acme stores data", "location": "x ¶1",
                                                                   "category": "capability", "confidence": "high"}]}
        self.assertEqual(validate("claims-record", rec, snapshot_text="Acme  stores\ndata for 30 days."), [])
        self.assertTrue(validate("claims-record", rec, snapshot_text="Acme keeps data."))

    def test_high_risk_cannot_be_verified_without_confirmation(self):
        c = claim("ACME-001", category="compliance")
        self.assertTrue(validate("claim", c, high_risk_categories=["compliance"]))
        c["user_decision"] = {"kind": "confirmed", "note": "", "author": "x", "at": "2026-01-01T00:00:00Z", "ruling_id": "r1"}
        self.assertEqual(validate("claim", c, high_risk_categories=["compliance"]), [])

    def test_override_requires_record(self):
        rep = {"run_id": "r", "round": 1, "round_kind": "initial", "draft_hash": "0" * 64, "status": "approved-override",
               "block_count": 1, "high_count": 0, "low_count": 0, "flags": [], "checker_scores": {}, "checkers_missing": [],
               "auto_revisions_used": 0, "override": None, "positioning_marks": [], "generated_at": "2026-01-01T00:00:00Z"}
        with self.assertRaises(ValidationError):
            check("verification-report", rep)

    def test_profile_consistency(self):
        from agents.offline import style_extractor  # noqa: F401  (schema exercised in other tests)
        prof = {"naming": {"product_name": "Acme", "variants_allowed": ["AC"], "forbidden": ["AC"]}}
        from packages.validate import _rules_style_profile
        full = {"naming": prof["naming"], "vocabulary": {"preferred": [], "banned": [], "avoid": []}, "status": "active",
                "consistency": {"ok": True, "issues": []}, "rubric": []}
        self.assertTrue(_rules_style_profile(full, {}))


if __name__ == "__main__":
    unittest.main()
