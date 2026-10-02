from tests.helpers import claim, unittest
from packages import registry
from packages.util import quote_hash

PRODUCT = {"id": "p", "claim_prefix": "ACME", "high_risk_categories": ["compliance", "metric"]}
SOURCES = {"tru-a": {"id": "tru-a", "status": "active", "kind": "living", "updated": "2026-08-01"},
           "tru-b": {"id": "tru-b", "status": "active", "kind": "changelog", "updated": "2025-01-01"}}


def rec(src, *items):
    return {"source_id": src, "summary": "", "claims": [
        {"text": t, "quote": t, "location": f"Doc ¶{i}", "category": cat, "confidence": conf} for i, (t, cat, conf) in enumerate(items)]}


def ruling(cid, kind, note="n", qh=None, at="2026-02-01T00:00:00Z", target_kind="claim", keep=None):
    return {"id": f"r-{cid}-{kind}", "workspace_id": "w", "target_kind": target_kind, "target_id": cid, "kind": kind, "note": note,
            "author": "sme@example.test", "created_at": at, "quote_hash": qh, "keep_claim_id": keep}


class RegistryTests(unittest.TestCase):
    def build(self, existing, records, rulings=(), conflicts=()):
        return registry.build(PRODUCT, existing, records, SOURCES, list(rulings), list(conflicts))[0]

    def test_ids_are_permanent_and_never_reused(self):
        r1 = [rec("tru-a", ("Acme Box stores data for 30 days.", "capability", "high"),
                  ("Acme Box encrypts data with AES-256.", "security", "high"))]
        c1 = self.build({}, r1)
        self.assertEqual(sorted(c1), ["ACME-001", "ACME-002"])
        # re-ingest with the first claim removed and a new one added
        r2 = [rec("tru-a", ("Acme Box encrypts data with AES-256.", "security", "high"),
                  ("Acme Box exports CSV files.", "integration", "high"))]
        c2 = self.build(c1, r2)
        self.assertEqual(c2["ACME-001"]["status"], "deprecated")
        self.assertEqual(c2["ACME-002"]["text"], "Acme Box encrypts data with AES-256.")
        self.assertEqual(c2["ACME-003"]["text"], "Acme Box exports CSV files.")
        c3 = self.build(c2, r2)
        self.assertEqual(sorted(c3), ["ACME-001", "ACME-002", "ACME-003"])

    def test_high_risk_and_low_confidence_enter_needs_review(self):
        c = self.build({}, [rec("tru-a", ("Acme is SOC 2 compliant.", "compliance", "high"),
                                ("Acme may add exports.", "capability", "low"), ("Acme exports CSV.", "integration", "high"))])
        self.assertEqual([c[i]["status"] for i in sorted(c)], ["needs-review", "needs-review", "verified"])

    def test_rulings_survive_reingest(self):
        r = [rec("tru-a", ("Acme is SOC 2 compliant.", "compliance", "high"), ("Acme supports 32 sensors.", "capability", "high"))]
        c = self.build({}, r)
        rulings = [ruling("ACME-001", "confirmed", qh=c["ACME-001"]["quote_hash"]),
                   ruling("ACME-002", "doc-wrong", "The spec says 64; this page is wrong.")]
        c = self.build(c, r, rulings)
        self.assertEqual(c["ACME-001"]["status"], "verified")
        self.assertEqual(c["ACME-002"]["status"], "deprecated")
        c = self.build(c, r, rulings)  # re-ingest of unchanged docs
        self.assertEqual(c["ACME-002"]["status"], "deprecated")
        self.assertEqual(c["ACME-002"]["user_decision"]["note"], "The spec says 64; this page is wrong.")

    def test_confirmation_lapses_when_quote_changes(self):
        r = [rec("tru-a", ("Acme is SOC 2 compliant.", "compliance", "high"))]
        c = self.build({}, r)
        rulings = [ruling("ACME-001", "confirmed", qh=quote_hash("an older quote"))]
        c = self.build(c, r, rulings)
        self.assertEqual(c["ACME-001"]["status"], "needs-review")

    def test_doc_wrong_creates_correction_note(self):
        c = self.build({}, [rec("tru-a", ("Acme supports 32 sensors.", "capability", "high"))])
        rulings = [ruling("ACME-001", "doc-wrong", "It is 64.")]
        c = self.build(c, [rec("tru-a", ("Acme supports 32 sensors.", "capability", "high"))], rulings)
        notes = registry.correction_notes(c, rulings, {"tru-a": {"title": "Overview", "origin": {"value": "x"}}})
        self.assertEqual(notes[0]["ruling"], "It is 64.")

    def test_conflict_ruling_deprecates_the_other_claim(self):
        r = [rec("tru-a", ("Each Acme Hub pairs with up to 64 wireless sensors.", "capability", "high")),
             rec("tru-b", ("Each Acme Hub supports up to 32 wireless sensors.", "capability", "high"))]
        c = self.build({}, r)
        confs = registry.detect_conflicts(c, SOURCES)
        self.assertEqual(len(confs), 1)
        self.assertEqual(confs[0]["kind"], "contradiction")
        conf = dict(confs[0], status="resolved")
        c = self.build(c, r, [ruling(conf["id"], "conflict-resolved", "Spec is right", target_kind="conflict", keep="ACME-001")], [conf])
        self.assertEqual(c["ACME-002"]["status"], "deprecated")
        self.assertEqual(c["ACME-001"]["status"], "verified")

    def test_living_vs_changelog_conflict_defaults_to_living_page(self):
        r = [rec("tru-a", ("Forecasting is in beta.", "availability", "high")),
             rec("tru-b", ("Forecasting is now generally available for all sites.", "availability", "high"))]
        c = self.build({}, r)
        confs = registry.detect_conflicts(c, SOURCES)
        self.assertEqual(confs[0]["kind"], "living-vs-changelog")
        self.assertEqual(c[confs[0]["interim_default"]]["source_id"], "tru-a")
        self.assertIn("default", confs[0]["interim_label"].lower())

    def test_absolute_vs_exception(self):
        r = [rec("tru-a", ("No configuration change can bypass the approval policy.", "security", "high"),
                 ("Emergency recovery applies configuration changes outside the approval policy.", "security", "high"))]
        c = self.build({}, r)
        kinds = [x["kind"] for x in registry.detect_conflicts(c, SOURCES)]
        self.assertIn("absolute-vs-exception", kinds)

    def test_existing_conflicts_are_never_dropped(self):
        old = {"id": "conf-x", "product_id": "p", "claim_ids": ["ACME-008", "ACME-009"], "kind": "contradiction",
               "explanation": "", "interim_default": None, "interim_label": "", "status": "resolved", "created_at": "2026-01-01T00:00:00Z"}
        out = registry.detect_conflicts({"ACME-001": claim("ACME-001")}, SOURCES, [old])
        self.assertIn("conf-x", [c["id"] for c in out])


class DecisionTests(unittest.TestCase):
    def d(self, text):
        return registry.derive_guardrails({"id": "DEC-001", "text": text})

    def test_banned_term(self):
        g = self.d("Never use the word 'seamless' in copy.")
        self.assertEqual((g[0]["type"], g[0]["terms"]), ("banned-term", ["seamless"]))

    def test_naming(self):
        g = self.d("Always call it Acme Box, never 'Acme' or 'AB'.")
        self.assertEqual(g[0]["terms"], ["Acme Box", "Acme", "AB"])

    def test_deprioritize_is_literal(self):
        g = self.d("Deprioritize the Self-Hosted deployment in copy.")
        self.assertEqual(g[0]["terms"], ["Self-Hosted"])
        self.assertIn("other topics are not affected", g[0]["rule"])

    def test_unrecognized_wording_quotes_the_decision(self):
        g = self.d("Refer to customers as finance teams, not accountants.")
        self.assertEqual(g[0]["type"], "other")
        self.assertEqual(g[0]["rule"], "Refer to customers as finance teams, not accountants.")
        self.assertEqual(g[0]["decision_id"], "DEC-001")


if __name__ == "__main__":
    unittest.main()
