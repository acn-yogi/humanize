"""The audit's normalizer and checks against planted fixtures, one per failure code."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import audit  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ROOT = Path(__file__).resolve().parents[2]


class NormalizerTests(unittest.TestCase):
    def test_one_session_with_a_tool_call_and_a_result(self):
        traces = audit.normalize(FIXTURES / "clean" / "transcript.jsonl")
        self.assertEqual(len(traces), 1)
        t = traces[0]
        self.assertEqual(t.version, audit.TRACE_VERSION)
        self.assertEqual([c.name for c in t.tool_calls], ["Bash"])
        self.assertIn("pytest", t.tool_calls[0].input)
        self.assertIs(t.tool_calls[0].is_error, False)
        self.assertEqual(t.subtype, "success")
        self.assertAlmostEqual(t.cost_usd, 0.05)
        self.assertTrue(t.final_text.startswith("Done."))

    def test_a_resumed_file_holds_two_sessions(self):
        traces = audit.normalize(FIXTURES / "shapes" / "resumed.jsonl")
        self.assertEqual([t.index for t in traces], [0, 1])
        self.assertEqual(traces[1].final_text, "Round 1 done.")
        self.assertEqual(len(traces[1].tool_calls), 0)

    def test_unknown_event_type_fails_loudly(self):
        with self.assertRaises(audit.UnknownShape):
            audit.normalize(FIXTURES / "shapes" / "unknown-type.jsonl")

    def test_an_event_before_init_fails_loudly(self):
        with self.assertRaises(audit.UnknownShape):
            audit.normalize(FIXTURES / "shapes" / "no-init.jsonl")

    def test_not_json_fails_loudly(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.jsonl"
            p.write_text('{"type":"system","subtype":"init","session_id":"x"}\nnot json\n', encoding="utf-8")
            with self.assertRaises(audit.UnknownShape):
                audit.normalize(p)

    def test_the_real_recordings_normalize(self):
        rec = ROOT / "demo/recordings"
        files = sorted(rec.glob("t-*/transcript.jsonl")) + sorted(rec.glob("t-*/review-transcript.jsonl"))
        self.assertTrue(files, "no recordings to normalize")
        for f in files:
            traces = audit.normalize(f)
            self.assertTrue(all(t.tool_calls or t.final_text for t in traces), f)


class CheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = audit.audit([FIXTURES], ROOT)
        cls.by_code = {c["code"]: c for c in cls.report["classes"]}

    def tasks(self, code: str) -> set[str]:
        return set(self.by_code.get(code, {}).get("taskIds", []))

    def test_clean_fixture_has_no_hit(self):
        hit = [h for c in self.report["classes"] for h in c["items"] if h["taskId"] == "t-FIXTURECLEAN"]
        self.assertEqual(hit, [])

    def test_no_tool_call(self):
        self.assertIn("t-FIXTURENOTOOL", self.tasks("NO_TOOL_CALL"))

    def test_ignored_error(self):
        self.assertIn("t-FIXTUREIGNORED", self.tasks("IGNORED_ERROR"))
        h = next(h for h in self.by_code["IGNORED_ERROR"]["items"] if h["taskId"] == "t-FIXTUREIGNORED")
        self.assertEqual(h["line"], 3)
        self.assertEqual(h["turn"], 1)

    def test_unsourced_specific(self):
        self.assertIn("t-FIXTUREUNSOURCED", self.tasks("UNSOURCED_SPECIFIC"))
        h = next(h for h in self.by_code["UNSOURCED_SPECIFIC"]["items"] if h["taskId"] == "t-FIXTUREUNSOURCED")
        self.assertIn("linter", h["text"])
        # The test claim in the same message is sourced by the pytest call: one hit, not two.
        self.assertEqual(len([h for h in self.by_code["UNSOURCED_SPECIFIC"]["items"] if h["taskId"] == "t-FIXTUREUNSOURCED"]), 1)

    def test_claimed_success_no_state(self):
        self.assertIn("t-FIXTURECLAIMED", self.tasks("CLAIMED_SUCCESS_NO_STATE"))

    def test_review_rejected_carries_the_reasons(self):
        self.assertIn("t-FIXTUREREJECT", self.tasks("REVIEW_REJECTED"))
        h = next(h for h in self.by_code["REVIEW_REJECTED"]["items"] if h["taskId"] == "t-FIXTUREREJECT")
        self.assertIn("intcomma echoes bad input", h["text"])
        self.assertEqual(h["round"], 0)
        self.assertTrue(h["file"].endswith("review-rejected/rounds.jsonl"))
        self.assertNotIn("t-FIXTUREREJECT", self.tasks("LINT_FAILED"))

    def test_stop_hook_blocked_is_a_warning(self):
        self.assertIn("t-FIXTURESTOPHOOK", self.tasks("STOP_HOOK_BLOCKED"))
        self.assertEqual(self.by_code["STOP_HOOK_BLOCKED"]["severity"], "WARN")

    def test_session_error_is_a_warning_and_skips_the_other_checks(self):
        self.assertIn("t-FIXTURESESSERR", self.tasks("SESSION_ERROR"))
        self.assertEqual(self.by_code["SESSION_ERROR"]["severity"], "WARN")
        for code in ("NO_TOOL_CALL", "CLAIMED_SUCCESS_NO_STATE", "UNSOURCED_SPECIFIC"):
            self.assertNotIn("t-FIXTURESESSERR", self.tasks(code))

    def test_model_mismatch_is_a_warning_from_the_fingerprint(self):
        self.assertIn("t-FIXTUREMODEL", self.tasks("MODEL_MISMATCH"))
        self.assertEqual(self.by_code["MODEL_MISMATCH"]["severity"], "WARN")
        h = next(h for h in self.by_code["MODEL_MISMATCH"]["items"] if h["taskId"] == "t-FIXTUREMODEL")
        self.assertEqual(h["text"], "author: configured sonnet, served claude-haiku-5")

    def test_spec_contradiction_from_the_authors_text_and_from_a_check_outside_the_scope(self):
        self.assertIn("t-FIXTURECONTRA", self.tasks("SPEC_CONTRADICTION"))
        self.assertEqual(self.by_code["SPEC_CONTRADICTION"]["severity"], "FAIL")
        items = [h for h in self.by_code["SPEC_CONTRADICTION"]["items"] if h["taskId"] == "t-FIXTURECONTRA"]
        self.assertTrue(any(h["text"].startswith("author:") and "contradict" in h["text"] for h in items))
        self.assertTrue(any("docs/time.md" in h["text"] and "exclude" in h["text"] for h in items))
        self.assertNotIn("t-FIXTURECONTRA", self.tasks("SCOPE_BLOCKS_FIX"))

    def test_scope_blocks_fix_from_a_denial_on_the_test_file_of_a_changed_module(self):
        self.assertIn("t-FIXTURESCOPE", self.tasks("SCOPE_BLOCKS_FIX"))
        self.assertEqual(self.by_code["SCOPE_BLOCKS_FIX"]["severity"], "FAIL")
        h = next(h for h in self.by_code["SCOPE_BLOCKS_FIX"]["items"] if h["taskId"] == "t-FIXTURESCOPE")
        self.assertEqual(h["line"], 2)
        self.assertIn("tests/test_number.py", h["text"])
        self.assertIn("test file of a changed module", h["text"])
        self.assertNotIn("t-FIXTURESCOPE", self.tasks("SPEC_CONTRADICTION"))

    def test_the_recordings_carry_no_structural_stall(self):
        report = audit.audit([ROOT / "demo/recordings"], ROOT)
        codes = {c["code"] for c in report["classes"]}
        self.assertNotIn("SPEC_CONTRADICTION", codes)
        self.assertNotIn("SCOPE_BLOCKS_FIX", codes)

    def test_the_recordings_served_the_configured_models(self):
        report = audit.audit([ROOT / "demo/recordings"], ROOT)
        self.assertNotIn("MODEL_MISMATCH", {c["code"] for c in report["classes"]})

    def test_lint_failed(self):
        self.assertIn("t-FIXTURELINT", self.tasks("LINT_FAILED"))
        self.assertIn("t-FIXTURELINT", self.tasks("REVIEW_REJECTED"))

    def test_ranking_is_by_distinct_tasks_then_hits(self):
        counts = [(c["tasks"], c["hits"]) for c in self.report["classes"]]
        self.assertEqual(counts, sorted(counts, reverse=True))
        self.assertEqual(self.report["classes"][0]["code"], "REVIEW_REJECTED")

    def test_result_and_ledger_join(self):
        self.assertEqual(self.report["result"], "FAIL")
        clean = next(t for t in self.report["tasks"] if t["taskId"] == "t-FIXTURECLEAN")
        self.assertTrue(clean["pr"].endswith("/pull/1"))

    def test_text_render_names_every_class(self):
        text = audit.render(self.report)
        for code in self.by_code:
            self.assertIn(code, text)
        self.assertIn("result: FAIL", text)


class PromoteTests(unittest.TestCase):
    def test_promote_writes_a_draft_with_prompt_sha_and_tasks(self):
        report = audit.audit([FIXTURES], ROOT)
        with tempfile.TemporaryDirectory() as d:
            out = audit.promote(report, "REVIEW_REJECTED", [FIXTURES], Path(d), ROOT)
            draft = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(draft["id"], "review-rejected")
        self.assertEqual(draft["kind"], "trajectory")
        self.assertEqual(draft["failureClass"], "REVIEW_REJECTED")
        self.assertEqual(draft["baseSha"], "0" * 40)
        self.assertEqual(draft["checks"], [])
        self.assertEqual(draft["k"], 3)
        self.assertEqual(set(draft["tasks"]), {"t-FIXTUREREJECT", "t-FIXTURELINT"})
        self.assertIn(draft["spec"], ("0004-cli-entrypoint", "0002-bugfix-precisedelta-sign"))

    def test_promote_requires_a_written_why_hard(self):
        report = audit.audit([FIXTURES], ROOT)
        with tempfile.TemporaryDirectory() as d:
            draft = json.loads(audit.promote(report, "REVIEW_REJECTED", [FIXTURES], Path(d), ROOT).read_text(encoding="utf-8"))
        self.assertEqual(draft["whyHard"], "TODO: why is this hard")
        self.assertRegex(draft["promotedAt"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        import rigor
        self.assertEqual(rigor.why_hard_status(draft), "missing")   # case-run.sh and cases.sh refuse it until a person writes it
        draft["whyHard"] = "The reviewer rejects round 0 for things no check can see."
        self.assertEqual(rigor.why_hard_status(draft), "ok")

    def test_promote_refuses_a_class_with_no_hit(self):
        report = audit.audit([FIXTURES / "clean"], ROOT)
        with tempfile.TemporaryDirectory() as d, self.assertRaises(SystemExit):
            audit.promote(report, "IGNORED_ERROR", [FIXTURES], Path(d), ROOT)


if __name__ == "__main__":
    unittest.main()
