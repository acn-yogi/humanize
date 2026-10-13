"""The reason classifier, the human-or-harness test, task ids from PRs, and the dedupe."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import corrections  # noqa: E402

TASK = "t-01M4RZHVGFWY1FXM7RNXWAVNQA"
PR = {"number": 3, "headRefName": f"workbench/{TASK}", "body": "**Workbench evidence packet** for spec `0002`...", "url": "https://github.com/acn-yogi/humanize/pull/3"}


def comment(body, login="reviewer-person", url="https://github.com/acn-yogi/humanize/pull/3#discussion_r1", at="2026-10-13T10:00:00Z"):
    return {"user": {"login": login}, "body": body, "html_url": url, "created_at": at}


class ClassifierTests(unittest.TestCase):
    def test_lint(self):
        self.assertEqual(corrections.classify("New test lines exceed 88 chars; E501 is enabled via ruff"), "lint")
        self.assertEqual(corrections.classify("black would reformat this"), "lint")
        self.assertEqual(corrections.classify("Unused import at the top"), "lint")

    def test_test(self):
        self.assertEqual(corrections.classify("This path is untested; add a pytest case for inf"), "test")
        self.assertEqual(corrections.classify("Coverage dropped on cli.py"), "test")

    def test_scope(self):
        self.assertEqual(corrections.classify("adds docs/cli.md, which is out of scope for this spec"), "scope")
        self.assertEqual(corrections.classify("Please revert the unrelated mkdocs change"), "scope")

    def test_wrong_behaviour(self):
        self.assertEqual(corrections.classify("intcomma echoes bad input with exit 0; it should exit 1"), "wrong-behaviour")
        self.assertEqual(corrections.classify("This breaks negative zero handling"), "wrong-behaviour")

    def test_style(self):
        self.assertEqual(corrections.classify("Nit: rename _precisedelta to something clearer"), "style")
        self.assertEqual(corrections.classify("Typo in the docstring"), "style")

    def test_question_and_other(self):
        self.assertEqual(corrections.classify("Why not keep the old helper?"), "question")
        self.assertEqual(corrections.classify("Looks good to me."), "other")

    def test_order_lint_beats_style_and_behaviour_beats_test(self):
        self.assertEqual(corrections.classify("Style nit: line too long for ruff"), "lint")
        self.assertEqual(corrections.classify("The test shows the wrong exit code"), "test")  # test words come before behaviour words
        self.assertEqual(corrections.classify("Wrong exit code on bad input"), "wrong-behaviour")

    def test_every_code_is_a_known_reason(self):
        for text in ("ruff", "pytest", "scope", "bug", "typo", "why?", ""):
            self.assertIn(corrections.classify(text), corrections.REASONS)


class HumanOrHarnessTests(unittest.TestCase):
    def test_harness_text_is_not_a_correction(self):
        self.assertTrue(corrections.is_harness_text("**Workbench evidence packet** for spec `0002`"))
        self.assertTrue(corrections.is_harness_text('Findings\n{"verdict": "reject", "reasons": ["x"]}'))
        self.assertTrue(corrections.is_harness_text("The workbench checked your change and did not accept it. Findings:"))
        self.assertFalse(corrections.is_harness_text("Please fix the long lines."))

    def test_bots(self):
        self.assertTrue(corrections.is_bot("github-actions[bot]", []))
        self.assertTrue(corrections.is_bot("workbench-bot", ["workbench-bot"]))
        self.assertFalse(corrections.is_bot("acn-yogi", []))

    def test_task_id_from_branch_or_body(self):
        self.assertEqual(corrections.task_id_of(PR), TASK)
        self.assertEqual(corrections.task_id_of({"headRefName": "main", "body": f"Task `{TASK}`"}), TASK)
        self.assertEqual(corrections.task_id_of({"headRefName": "main", "body": "nothing"}), "")

    def test_rows_from_comments_keeps_only_human_ones(self):
        rows = corrections.rows_from_comments(PR, [
            comment("Please wrap the long lines, ruff E501", url="u1"),
            comment("**Workbench evidence packet** ...", login="acn-yogi", url="u2"),
            comment("LGTM", login="dependabot[bot]", url="u3"),
            comment("", url="u4"),
            comment("Why the helper?", url="u5", at="2026-10-01T00:00:00Z"),
        ], bots=[], since="2026-10-10T00:00:00Z")
        self.assertEqual([r["url"] for r in rows], ["u1"])
        r = rows[0]
        self.assertEqual((r["event"], r["source"], r["pr"], r["taskId"], r["reasonCode"], r["author"]),
                         ("corrected", "pr-comment", 3, TASK, "lint", "reviewer-person"))

    def test_dedupe_on_url_and_on_manual_row(self):
        existing = [{"event": "corrected", "source": "pr-comment", "url": "u1"},
                    {"event": "corrected", "source": "manual", "taskId": TASK, "action": "takeover", "reasonCode": "lint"}]
        new = [{"event": "corrected", "source": "pr-comment", "url": "u1"},
               {"event": "corrected", "source": "pr-comment", "url": "u2"},
               {"event": "corrected", "source": "manual", "taskId": TASK, "action": "takeover", "reasonCode": "lint"},
               {"event": "corrected", "source": "manual", "taskId": TASK, "action": "edit", "reasonCode": "lint"}]
        kept = corrections.dedupe(existing, new)
        self.assertEqual([k.get("url") or k.get("action") for k in kept], ["u2", "edit"])


if __name__ == "__main__":
    unittest.main()
