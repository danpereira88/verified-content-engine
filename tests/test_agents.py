import json
from unittest import mock

from tests.helpers import ADMIN, StoreCase, claim, unittest
from agents import runtime
from agents.runtime import AgentError, Toolbox, ToolDenied, load_agent, roles, run_agent
from evals import gate_eval, style_eval


class RuntimeTests(unittest.TestCase):
    def test_every_role_has_a_valid_definition(self):
        expected = {"claims-extractor", "style-extractor", "positioning-extractor", "evidence-extractor", "strategist",
                    "copywriter", "verifier", "style-checker", "best-practice-auditor", "synthetic-buyer"}
        self.assertEqual(set(roles()), expected)
        for r in expected:
            spec = load_agent(r)
            self.assertIn("write_output", spec["tools"])
            runtime.inline_schema(spec["output_schema"])  # resolvable for providers

    def test_tool_allowlist_enforced(self):
        spec = load_agent("synthetic-buyer")
        with self.assertRaises(ToolDenied):
            runtime.call_tool(spec, Toolbox(), "search_registry", {"query": "x"})
        spec = load_agent("verifier")
        self.assertNotIn("read_artifact", spec["tools"])  # the gate can't read the plan or brief

    def test_invalid_output_raises(self):
        class Bad(runtime.OfflineProvider):
            def run(self, spec, payload, box, product=None):
                return {"nope": 1}, runtime.Usage()
        with self.assertRaises(AgentError):
            run_agent("synthetic-buyer", {}, Toolbox(), Bad())

    def test_prompts_are_product_agnostic(self):
        from pathlib import Path
        fixture_names = []
        for p in (Path(runtime.AGENT_DIR).parent / "fixtures" / "products").glob("*/product.json"):
            meta = json.loads(p.read_text())
            fixture_names += [meta["name"], meta["company"], meta["claim_prefix"]]
        for f in list(Path(runtime.AGENT_DIR).rglob("*.md")) + list(Path(runtime.AGENT_DIR).glob("*.py")):
            text = f.read_text()
            for n in fixture_names:
                self.assertNotIn(n, text, f"{f} mentions fixture name {n}")

    def test_writing_aid_with_stale_fact_is_flagged(self):
        product = {"name": "Acme Box"}
        claims = {"ACME-001": claim("ACME-001", "Acme Box stores data for 30 days.")}
        with mock.patch.object(runtime, "load_skill", return_value="Acme Box is ISO 27001 certified and loved by banks."):
            flags = runtime.writing_aid_flags(["x"], product, claims)
        self.assertEqual(len(flags), 1)


class EvalTests(unittest.TestCase):
    def test_score_math(self):
        seeds = [{"id": "a", "label": "false", "text": ""}, {"id": "b", "label": "true", "text": ""},
                 {"id": "c", "label": "untagged", "text": ""}, {"id": "d", "label": "positioning", "text": ""}]
        v = {"a": {"blocked": True, "reasons": []}, "b": {"blocked": False, "reasons": []},
             "c": {"blocked": True, "reasons": []}, "d": {"blocked": True, "reasons": []}}
        r = gate_eval.score(seeds, v, [])
        self.assertEqual(r["metrics"], {"hallucination_catch_rate": 1.0, "false_block_rate": 0.5, "untagged_detection_rate": 1.0})
        self.assertFalse(r["all_passed"])

    def test_auc_and_threshold(self):
        self.assertEqual(style_eval.auc([0.9, 0.8], [0.2, 0.1]), 1.0)
        thr, j = style_eval.best_threshold([0.9, 0.8], [0.2, 0.1])
        self.assertTrue(0.2 < thr < 0.8)


class FixtureEvalTests(StoreCase):
    def test_offline_gate_meets_targets_on_fixtures(self):
        """Release check, offline baseline. A model-backed verifier must pass the same check (CLAUDE.md §7)."""
        from agents.runtime import OfflineProvider
        from evals.cli import run_gate_for_workspace
        for slug in ("lumen", "shiftwell"):
            self.load(slug)
            r = run_gate_for_workspace(self.ws, slug, OfflineProvider())
            self.assertTrue(r["all_passed"], f"{slug}: {r['metrics']}")
            self.assertEqual(r["skipped_golden"], [])


if __name__ == "__main__":
    unittest.main()


class AnthropicProviderLoopTests(unittest.TestCase):
    def test_tool_loop_validation_retry_and_denial(self):
        p = runtime.AnthropicProvider(api_key="test-key-not-real")
        good = {"verdict": "maybe", "summary": "s", "objections": [], "missing_proof": []}
        replies = iter([
            {"content": [{"type": "tool_use", "id": "t1", "name": "search_registry", "input": {"query": "x"}}], "usage": {"input_tokens": 10, "output_tokens": 5}},
            {"content": [{"type": "tool_use", "id": "t2", "name": "write_output", "input": {"verdict": "perhaps"}}], "usage": {"input_tokens": 10, "output_tokens": 5}},
            {"content": [{"type": "tool_use", "id": "t3", "name": "write_output", "input": good}], "usage": {"input_tokens": 10, "output_tokens": 5}},
        ])
        sent = []

        def fake_post(body):
            sent.append(json.loads(json.dumps(body)))
            return next(replies)
        with mock.patch.object(p, "_post", side_effect=fake_post):
            out, usage = p.run(load_agent("synthetic-buyer"), {"draft_text": "x", "persona": {}}, Toolbox())
        self.assertEqual(out, good)
        self.assertEqual(usage.total, 45)
        # the synthetic buyer may not search the registry: denied, and the model is told so
        self.assertTrue(sent[1]["messages"][-1]["content"][0]["is_error"])
        # invalid output is returned to the model with validation errors
        self.assertIn("Validation failed", sent[2]["messages"][-1]["content"][0]["content"])
        # only allowlisted tools are offered
        self.assertEqual([t["name"] for t in sent[0]["tools"]], ["write_output"])
        self.assertIn("writing_aid", sent[0]["system"])
