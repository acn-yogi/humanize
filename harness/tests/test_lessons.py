"""The lessons ledger: feeds, dedup, dispositions, the person-only gate, routing, closing, recurrence, seed, scorecard."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import audit  # noqa: E402
import lessons  # noqa: E402
import scorecard  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIXTURES = HERE / "fixtures"
T1, T2, T3 = "t-01M4RYVYEG6H31MRD8C2N01K04", "t-01M4RZHVFWTPBC0BG9QVPBAS3T", "t-01M4RZHVGFWY1FXM7RNXWAVNQA"
NOW = "2026-10-16T00:00:00Z"
AGENT = {lessons.AGENT_ENV: "1"}


def halted(task, at, fclass="genuine", stall=None, **extra):
    r = {"at": at, "taskId": task, "spec": "0001", "class": "bugfix", "path": "reject", "reasons": ["x"], "costUsd": 0.1,
         "failureClass": fclass, "stall": stall}
    r.update(extra)
    return r


def corrected(at, reason, url=None, task=T1):
    return {"at": at, "event": "corrected", "source": "pr-comment", "pr": 3, "taskId": task, "author": "p", "reasonCode": reason, "url": url or f"https://x/{reason}/{at}"}


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = Path(self.tmp.name)
        (self.cwd / "runs").mkdir()
        self.lessons = self.cwd / "runs/lessons.jsonl"
        self.ledger = self.cwd / "runs/ledger.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def put_ledger(self, rows):
        self.ledger.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def put_proof(self, case, **v):
        d = self.cwd / "runs/proofs" / case
        d.mkdir(parents=True, exist_ok=True)
        v.setdefault("case", case)
        v.setdefault("at", "2026-10-14T20:00:00Z")
        (d / "verdict.json").write_text(json.dumps(v), encoding="utf-8")
        return d / "verdict.json"

    def draft(self, stamp=NOW):
        return lessons.draft(self.cwd, self.lessons, use_audit=False, stamp=stamp)[0]

    def folded(self):
        return lessons.fold(lessons.read_rows(self.lessons))

    def only(self):
        f = self.folded()
        self.assertEqual(len(f), 1, f)
        return next(iter(f.values()))


class WeightsAndSources(unittest.TestCase):
    def test_weights(self):
        self.assertEqual(lessons.WEIGHTS, {"human-correction": 3, "eval-fail": 2, "test-fail": 1, "build-retro": 2, "external": 2})
        self.assertEqual(lessons.SOURCES, ("eval-fail", "test-fail", "human-correction", "build-retro", "external"))
        self.assertEqual(lessons.STATUSES, ("draft", "approved", "routed", "in-progress", "closed", "recurred", "rejected"))

    def test_row_shape(self):
        row = lessons.apply([], [lessons.Cand("test-fail", "halt", "genuine", "A task halted", "task:a", ["task:a"], None, detail="genuine|")], NOW)[0]
        self.assertEqual(set(row), {"id", "ts", "source", "sourceRef", "finding", "class", "signature", "evidence", "proposedDisposition", "status",
                                    "links", "recurrences", "portable", "weight", "approvedBy", "closedBy", "note"})
        self.assertEqual(set(row["links"]), {"caseId", "specId", "packId", "prRef"})
        self.assertEqual(row["id"], "les-" + row["signature"][:8])
        self.assertEqual((row["status"], row["recurrences"], row["portable"], row["weight"]), ("draft", 1, False, 1))


class FeedTests(Env):
    def test_eval_fail_feed_reads_proof_verdicts(self):
        self.put_proof("a", verdict="noise-too-high", failureClass="LINT_FAILED")
        self.put_proof("b", verdict="NO-SHIP", failureClass="REVIEW_REJECTED", rule={"decision": "overfit-suspected"},
                       impossibleOrAmbiguous=["c1"], graderAgreement={"runs": 4, "agreed": 3, "disagreeing": 1})
        self.put_proof("c", verdict="cost-not-lower")
        self.put_proof("d", verdict="judge-not-independent")
        self.put_proof("e", verdict="SHIP", failureClass="LINT_FAILED", graderAgreement={"runs": 2, "agreed": 2, "disagreeing": 0})
        self.put_proof("f", verdict="case-missing-why-hard")
        added = self.draft()
        got = {(r["class"], r["proposedDisposition"], r["source"]) for r in added}
        self.assertEqual(got, {
            ("noise-too-high", "case", "eval-fail"), ("REVIEW_REJECTED", "pack", "eval-fail"), ("overfit-suspected", "pack", "eval-fail"),
            ("impossible-or-ambiguous", "case", "eval-fail"), ("grader-disagreement", "code", "eval-fail"),
            ("cost-not-lower", "pack", "eval-fail"), ("judge-not-independent", "code", "eval-fail")})
        self.assertTrue(all(r["weight"] == 2 for r in added))
        ev = [e for r in added for e in r["evidence"]]
        self.assertTrue(any(e.endswith("runs/proofs/a/verdict.json") for e in ev))

    def test_testing_feed_reads_halts_reviews_checks_and_stall_review(self):
        self.put_ledger([
            halted(T1, "2026-10-12T21:00:00Z", "harness-error", "harness-or-infra"),
            halted(T2, "2026-10-12T22:00:00Z", "genuine", "structural"),
            {"at": "2026-10-12T23:00:00Z", "taskId": T3, "spec": "s", "class": "c", "path": "per_pr", "costUsd": 0.2,
             "reasons": ["adversarial review raised findings", "trusted checks failed"]},
            halted("t-01M4RZHVGFWY1FXM7RNXWAVNQB", "2026-10-13T01:00:00Z", "genuine", None,
                   stallReview={"flatAttempts": 2, "edited": False, "continueWith": ["a failure"]}),
        ])
        added = self.draft()
        got = {(r["class"], r["proposedDisposition"], r["source"]) for r in added}
        self.assertEqual(got, {("harness-or-infra", "code", "test-fail"), ("structural", "spec", "test-fail"),
                               ("REVIEW_REJECTED", "parked", "test-fail"), ("CHECKS_FAILED", "parked", "test-fail"),
                               ("genuine", "parked", "test-fail"), ("genuine-continue", "parked", "test-fail")})
        self.assertTrue(all(r["weight"] == 1 for r in added))

    def test_human_correction_feed(self):
        rows = [corrected("2026-10-13T10:00:00Z", "lint"), corrected("2026-10-13T10:05:00Z", "question"),
                {"at": "2026-10-13T11:00:00Z", "event": "corrected", "source": "manual", "taskId": T2, "action": "takeover", "reasonCode": "scope", "author": "p"}]
        self.put_ledger(rows)
        got = {(r["class"], r["proposedDisposition"], r["source"], r["weight"]) for r in self.draft()}
        self.assertEqual(got, {("lint", "pack", "human-correction", 3), ("question", "none", "human-correction", 3), ("scope", "spec", "human-correction", 3)})

    def test_audit_feed_skips_the_stop_hook_and_dedupes_with_the_ledger(self):
        shutil.copytree(FIXTURES / "review-rejected", self.cwd / "runs" / "t-FIXTUREREJECT")
        self.put_ledger([{"at": "2026-10-12T23:00:00Z", "taskId": "t-FIXTUREREJECT", "spec": "s", "class": "c", "path": "per_pr", "costUsd": 0.2,
                          "reasons": ["adversarial review raised findings"]}])
        added = lessons.draft(self.cwd, self.lessons, roots=[self.cwd / "runs"], stamp=NOW)[0]
        review = [r for r in self.folded().values() if r["class"] == "REVIEW_REJECTED"]
        self.assertEqual(len(review), 1)
        self.assertEqual(review[0]["recurrences"], 1, "one task seen by the audit and the ledger is one occurrence")
        self.assertTrue(added)


class DedupTests(Env):
    def test_idempotent_draft(self):
        self.put_ledger([halted(T1, "2026-10-12T21:00:00Z", "harness-error", "harness-or-infra"), corrected("2026-10-13T10:00:00Z", "lint")])
        self.put_proof("a", verdict="NO-SHIP", failureClass="LINT_FAILED")
        first = self.draft()
        self.assertEqual(len(first), 3)
        before = self.lessons.read_text(encoding="utf-8")
        self.assertEqual(self.draft(stamp="2026-10-17T00:00:00Z"), [])
        self.assertEqual(self.lessons.read_text(encoding="utf-8"), before)

    def test_many_halts_for_one_cause_are_one_lesson_with_a_count(self):
        self.put_ledger([halted(t, f"2026-10-12T2{i}:00:00Z", "harness-error", "harness-or-infra")
                         for i, t in enumerate([T1, T2, T3])])
        self.draft()
        les = self.only()
        self.assertEqual(les["recurrences"], 3)
        self.assertEqual([e for e in les["evidence"] if e.startswith("task:")], [f"task:{T1}", f"task:{T2}", f"task:{T3}"])
        self.assertTrue(any(e.endswith(f"#{T2}") for e in les["evidence"]), "evidence is appended")
        self.put_ledger([halted(t, f"2026-10-12T2{i}:00:00Z", "harness-error", "harness-or-infra") for i, t in enumerate([T1, T2, T3, "t-01M4RZHVGFWY1FXM7RNXWAVNQB"])])
        self.draft()
        self.assertEqual(self.only()["recurrences"], 4)

    def test_signature_is_class_plus_normalized_finding(self):
        a = lessons.signature("X", "Failed on t-01M4RYVYEG6H31MRD8C2N01K04 at src/a/b.py line 12")
        b = lessons.signature("X", "failed on t-01M4RZHVFWTPBC0BG9QVPBAS3T at docs/c.md line 99")
        self.assertEqual(a, b)
        self.assertNotEqual(a, lessons.signature("Y", "Failed on t-01M4RYVYEG6H31MRD8C2N01K04 at src/a/b.py line 12"))
        self.assertEqual(len(a), 40)

    def test_weight_is_the_highest_among_sources(self):
        row = lessons.apply([], [lessons.Cand("test-fail", "x", "c", "same", "o1", ["o1"], None)], NOW)
        more = lessons.apply(row, [lessons.Cand("human-correction", "x", "c", "same", "o2", ["o2"], None)], NOW)
        self.assertEqual((more[0]["weight"], more[0]["recurrences"], more[0]["source"]), (3, 2, "test-fail"))

    def test_a_rejected_signature_is_not_drafted_again(self):
        self.put_ledger([halted(T1, "2026-10-12T21:00:00Z", "refusal")])
        self.draft()
        lessons.reject(self.lessons, self.only()["id"], "yogi", "not worth it", env={})
        self.put_ledger([halted(T1, "2026-10-12T21:00:00Z", "refusal"), halted(T2, "2026-10-12T22:00:00Z", "refusal")])
        self.assertEqual(self.draft(), [])
        self.assertEqual(self.only()["status"], "rejected")


class DispositionTests(unittest.TestCase):
    def test_rules(self):
        p = lessons.propose
        self.assertEqual(p("audit", "REVIEW_REJECTED", "", 1), "parked")
        self.assertEqual(p("audit", "REVIEW_REJECTED", "", 2), "case")
        self.assertEqual(p("halt", "structural", "genuine|structural", 1), "spec")
        self.assertEqual(p("halt", "artifact-gap", "genuine|artifact-gap", 1), "spec")
        self.assertEqual(p("audit", "SCOPE_BLOCKS_FIX", "", 1), "spec")
        self.assertEqual(p("proof", "NO-SHIP", "", 1), "pack")
        self.assertEqual(p("proof", "cost-not-lower", "", 1), "pack")
        self.assertEqual(p("proof", "noise-too-high", "", 1), "case")
        self.assertEqual(p("halt", "harness-or-infra", "harness-error|harness-or-infra", 1), "code")
        self.assertEqual(p("halt", "timeout", "timeout|", 1), "code")
        self.assertEqual(p("halt", "refusal", "refusal|", 1), "pack")
        self.assertEqual(p("halt", "variance", "genuine|variance", 1), "none")
        self.assertEqual(p("human", "wrong-behaviour", "", 1), "case")
        self.assertEqual(p("human", "other", "", 1), "parked")
        self.assertIn(p("audit", "LINT_FAILED", "", 1), lessons.DISPOSITIONS)

    def test_a_draft_is_re_evaluated_when_it_recurs_but_an_approved_lesson_keeps_its_disposition(self):
        one = lessons.apply([], [lessons.Cand("test-fail", "review", "REVIEW_REJECTED", "f", "o1", ["o1"], None)], NOW)
        self.assertEqual(one[0]["proposedDisposition"], "parked")
        two = lessons.apply(one, [lessons.Cand("test-fail", "review", "REVIEW_REJECTED", "f", "o2", ["o2"], None)], NOW)
        self.assertEqual(two[0]["proposedDisposition"], "case")
        approved = dict(one[0], status="approved")
        three = lessons.apply([approved], [lessons.Cand("test-fail", "review", "REVIEW_REJECTED", "f", "o2", ["o2"], None)], NOW)
        self.assertEqual(three[0]["proposedDisposition"], "parked")


class PersonGateTests(Env):
    def setUp(self):
        super().setUp()
        self.put_ledger([halted(T1, "2026-10-12T21:00:00Z", "refusal")])
        self.draft()
        self.lid = self.only()["id"]

    def test_approve_needs_a_name_and_a_person(self):
        with self.assertRaises(lessons.LessonError) as c:
            lessons.approve(self.lessons, self.lid, None, env={})
        self.assertEqual(c.exception.code, 2)
        r = lessons.approve(self.lessons, self.lid, "yogi", env={}, stamp=NOW)
        self.assertEqual((r["status"], r["approvedBy"]), ("approved", "yogi"))

    def test_agent_session_cannot_approve_or_reject(self):
        for fn in (lambda: lessons.approve(self.lessons, self.lid, "yogi", env=AGENT), lambda: lessons.reject(self.lessons, self.lid, "yogi", env=AGENT)):
            with self.assertRaises(lessons.LessonError) as c:
                fn()
            self.assertEqual(c.exception.code, 2)
            self.assertIn("agent", str(c.exception))
        self.assertEqual(self.only()["status"], "draft")

    def test_command_line_exits_2_under_an_agent_session(self):
        env = dict(os.environ, **AGENT)
        for cmd in ("approve", "reject"):
            r = subprocess.run([sys.executable, str(ROOT / "harness/lib/lessons.py"), "--cwd", str(self.cwd), cmd, self.lid, "--by", "yogi"],
                               capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("agents cannot approve their own lessons", r.stderr)
        env.pop(lessons.AGENT_ENV)
        r = subprocess.run([sys.executable, str(ROOT / "harness/lib/lessons.py"), "--cwd", str(self.cwd), "approve", self.lid, "--by", "yogi"],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_the_scripts_that_run_claude_export_the_marker(self):
        for name in ("workbench", "dispatch", "shape", "case-run", "prove", "judge", "watch-tickets"):
            self.assertIn("export HARNESS_AGENT_SESSION=1", (ROOT / f"harness/bin/{name}.sh").read_text(encoding="utf-8"), name)

    def test_reject_keeps_the_reason(self):
        r = lessons.reject(self.lessons, self.lid, "yogi", "model refusal is not ours", env={})
        self.assertEqual((r["status"], r["note"]), ("rejected", "model refusal is not ours"))
        with self.assertRaises(lessons.LessonError):
            lessons.approve(self.lessons, self.lid, "yogi", env={})


class RouteTests(Env):
    def approved(self, cls="REVIEW_REJECTED", disposition="case", **links):
        row = {"id": "les-test0001", "ts": NOW, "source": "eval-fail", "sourceRef": "o", "finding": "f", "class": cls, "signature": "s" * 40,
               "evidence": ["o"], "proposedDisposition": disposition, "status": "approved",
               "links": dict({"caseId": None, "specId": None, "packId": None, "prRef": None}, **links), "recurrences": 2, "portable": False,
               "weight": 2, "approvedBy": "yogi", "closedBy": None, "note": ""}
        lessons.append_rows(self.lessons, [row])
        return row["id"]

    def test_case_routes_through_audit_promote(self):
        shutil.copytree(FIXTURES / "review-rejected", self.cwd / "runs" / "t-FIXTUREREJECT")
        lid = self.approved()
        res = lessons.route(self.lessons, self.cwd, roots=[self.cwd / "runs"], stamp=NOW)
        self.assertEqual([r["result"] for r in res], ["routed"])
        draft = json.loads((self.cwd / "harness/cases/drafts/review-rejected.json").read_text(encoding="utf-8"))
        self.assertEqual(draft["whyHard"], "TODO: why is this hard")
        self.assertIn("promotedAt", draft)
        les = self.folded()[lid]
        self.assertEqual((les["status"], les["links"]["caseId"]), ("routed", "review-rejected"))

    def test_case_for_a_class_with_no_audit_hit_is_skipped_and_stays_approved(self):
        lid = self.approved(cls="noise-too-high")
        res = lessons.route(self.lessons, self.cwd, roots=[self.cwd / "runs"], stamp=NOW)
        self.assertEqual(res[0]["result"], "skipped")
        self.assertEqual(self.folded()[lid]["status"], "approved")

    def test_spec_writes_a_draft_and_runs_nothing(self):
        lid = self.approved(cls="structural", disposition="spec")
        lessons.route(self.lessons, self.cwd, stamp=NOW)
        text = (self.cwd / f"specs/drafts/{lid}.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("+++\n"))
        self.assertIn('status = "draft"', text)
        self.assertIn(f'lesson = "{lid}"', text)
        self.assertEqual(self.folded()[lid]["links"]["specId"], f"draft-{lid}")
        self.assertEqual(list((self.cwd / "specs").glob("[0-9]*.md")), [], "the dispatcher reads specs/NNNN-*.md only")

    def test_pack_prints_the_proving_loop_commands_and_writes_nothing(self):
        lid = self.approved(cls="cost-not-lower", disposition="pack")
        res = lessons.route(self.lessons, self.cwd, stamp=NOW)
        self.assertIn("harness/bin/case-run.sh harness/cases/", res[0]["message"])
        self.assertIn("--pack candidate --k 3", res[0]["message"])
        self.assertIn("python3 harness/lib/proof.py .", res[0]["message"])
        self.assertFalse((self.cwd / "harness").exists())
        self.assertEqual(self.folded()[lid]["status"], "routed")

    def test_code_and_parked_are_recorded_only(self):
        a, b = self.approved(cls="a", disposition="code"), None
        lessons.route(self.lessons, self.cwd, stamp=NOW)
        self.assertEqual(self.folded()[a]["status"], "routed")
        self.assertFalse((self.cwd / "specs").exists() or (self.cwd / "harness").exists())

    def test_guardrail_paths_are_refused(self):
        for path in ("harness/guardrails/probe.sh", ".claude/settings.json", "managed-settings.json", "harness/hooks/scope.sh", "runs/HALT",
                     "harness/guardrails", "C:\\x\\harness\\guardrails\\a"):
            self.lessons.write_text("", encoding="utf-8")
            lid = self.approved(cls="structural", disposition="spec", changePaths=[path])
            res = lessons.route(self.lessons, self.cwd, stamp=NOW)
            self.assertEqual(res[0]["result"], "refused", path)
            self.assertEqual(self.folded()[lid]["status"], "approved", path)
        self.assertFalse((self.cwd / "specs").exists())

    def test_guardrail_path_given_at_route_time_is_refused_and_ordinary_paths_pass(self):
        lid = self.approved(cls="structural", disposition="spec")
        res = lessons.route(self.lessons, self.cwd, change_paths=["harness/guardrails/guardrails.sh"], stamp=NOW)
        self.assertEqual(res[0]["result"], "refused")
        res = lessons.route(self.lessons, self.cwd, change_paths=["src/humanize/number.py"], stamp=NOW)
        self.assertEqual(res[0]["result"], "routed")
        self.assertEqual(self.folded()[lid]["links"]["changePaths"], ["src/humanize/number.py"])

    def test_the_router_may_only_write_drafts(self):
        for bad in ("harness/guardrails/x", "specs/0001-a.md", ".claude/settings.json", "harness/cases/x.json"):
            with self.assertRaises(lessons.LessonError):
                lessons.assert_writable(bad)
        lessons.assert_writable("specs/drafts/a.md")
        lessons.assert_writable("harness/cases/drafts/a.json")

    def test_command_line_exits_3_on_a_guardrail(self):
        self.approved(cls="structural", disposition="spec")
        r = subprocess.run([sys.executable, str(ROOT / "harness/lib/lessons.py"), "--cwd", str(self.cwd), "route", "--change-path", "harness/guardrails/probe.sh"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)

    def test_only_approved_lessons_route(self):
        lid = self.approved(cls="a", disposition="code")
        lessons.route(self.lessons, self.cwd, stamp=NOW)
        again = lessons.route(self.lessons, self.cwd, [lid], stamp=NOW)
        self.assertEqual(again[0]["result"], "skipped")


class CloseTests(Env):
    def setUp(self):
        super().setUp()
        self.put_ledger([halted(T1, "2026-10-12T21:00:00Z", "refusal")])
        self.draft()
        self.lid = self.only()["id"]
        lessons.approve(self.lessons, self.lid, "yogi", env={}, stamp="2026-10-16T00:00:00Z")

    def test_needs_exactly_one_real_reference(self):
        with self.assertRaises(lessons.LessonError):
            lessons.close(self.lessons, self.cwd, self.lid, "yogi")
        with self.assertRaises(lessons.LessonError):
            lessons.close(self.lessons, self.cwd, self.lid, "yogi", proof="a", pr="1")

    def test_proof_must_exist_and_be_ship(self):
        with self.assertRaises(lessons.LessonError) as c:
            lessons.close(self.lessons, self.cwd, self.lid, "yogi", proof="runs/proofs/none/verdict.json")
        self.assertIn("does not exist", str(c.exception))
        bad = self.put_proof("bad", verdict="NO-SHIP")
        with self.assertRaises(lessons.LessonError) as c:
            lessons.close(self.lessons, self.cwd, self.lid, "yogi", proof=str(bad))
        self.assertIn("only a SHIP", str(c.exception))
        good = self.put_proof("good", verdict="SHIP")
        r = lessons.close(self.lessons, self.cwd, self.lid, "yogi", proof="runs/proofs/good/verdict.json", stamp="2026-10-18T12:00:00Z")
        self.assertEqual((r["status"], r["closedBy"], r["links"]["proof"]), ("closed", "yogi", "runs/proofs/good/verdict.json"))
        self.assertTrue(good.exists())

    def test_pr_must_be_merged(self):
        prs = [{"number": 7, "url": "https://x/pull/7", "mergedAt": None}, {"number": 8, "url": "https://x/pull/8", "mergedAt": "2026-10-17T00:00:00Z"}]
        for ref, text in (("7", "not merged"), ("#9", "not found"), ("nonsense", "not a PR reference")):
            with self.assertRaises(lessons.LessonError) as c:
                lessons.close(self.lessons, self.cwd, self.lid, "yogi", pr=ref, prs=prs)
            self.assertIn(text, str(c.exception))
        r = lessons.close(self.lessons, self.cwd, self.lid, "yogi", pr="https://github.com/acn-yogi/humanize/pull/8", prs=prs)
        self.assertEqual((r["status"], r["links"]["prRef"]), ("closed", "https://github.com/acn-yogi/humanize/pull/8"))

    def test_a_draft_cannot_close(self):
        self.lessons.write_text("", encoding="utf-8")
        self.draft()
        self.put_proof("good", verdict="SHIP")
        with self.assertRaises(lessons.LessonError):
            lessons.close(self.lessons, self.cwd, self.only()["id"], "yogi", proof="runs/proofs/good/verdict.json")


class RecurrenceTests(Env):
    def closed_lesson(self):
        self.put_ledger([halted(T1, "2026-10-12T21:00:00Z", "refusal")])
        self.draft(stamp="2026-10-13T00:00:00Z")
        lid = self.only()["id"]
        lessons.approve(self.lessons, lid, "yogi", env={}, stamp="2026-10-14T00:00:00Z")
        self.put_proof("good", verdict="SHIP")
        lessons.close(self.lessons, self.cwd, lid, "yogi", proof="runs/proofs/good/verdict.json", stamp="2026-10-15T00:00:00Z")
        return lid

    def test_a_newer_occurrence_of_a_closed_signature_reopens_it(self):
        lid = self.closed_lesson()
        self.put_ledger([halted(T1, "2026-10-12T21:00:00Z", "refusal"), halted(T2, "2026-10-16T09:00:00Z", "refusal")])
        added = self.draft(stamp="2026-10-16T10:00:00Z")
        self.assertEqual(len(added), 1)
        les = self.folded()[lid]
        self.assertEqual((les["status"], les["recurrences"]), ("recurred", 2))
        self.assertIn(f"task:{T2}", les["evidence"])
        self.assertEqual(self.draft(stamp="2026-10-16T11:00:00Z"), [], "idempotent after the reopen")

    def test_an_occurrence_older_than_the_close_only_adds_evidence(self):
        lid = self.closed_lesson()
        self.put_ledger([halted(T1, "2026-10-12T21:00:00Z", "refusal"), halted(T2, "2026-10-14T09:00:00Z", "refusal")])
        self.draft(stamp="2026-10-16T10:00:00Z")
        les = self.folded()[lid]
        self.assertEqual((les["status"], les["recurrences"]), ("closed", 2))

    def test_recurred_ranks_first_and_can_be_approved_and_closed_again(self):
        lid = self.closed_lesson()
        self.put_ledger([halted(T1, "2026-10-12T21:00:00Z", "refusal"), halted(T2, "2026-10-16T09:00:00Z", "refusal"),
                         corrected("2026-10-16T09:30:00Z", "lint"), corrected("2026-10-16T09:31:00Z", "lint", url="https://x/other")])
        self.draft(stamp="2026-10-16T10:00:00Z")
        ranked = lessons.listing(lessons.read_rows(self.lessons))
        self.assertEqual(ranked[0]["id"], lid)
        self.assertEqual(ranked[0]["status"], "recurred")
        lessons.approve(self.lessons, lid, "yogi", env={}, stamp="2026-10-16T11:00:00Z")
        lessons.close(self.lessons, self.cwd, lid, "yogi", proof="runs/proofs/good/verdict.json", stamp="2026-10-17T00:00:00Z")
        self.assertEqual(self.folded()[lid]["status"], "closed")


class ListTests(unittest.TestCase):
    def rows(self):
        def r(i, status, source, rec, ts, w=None, disp="case"):
            return {"id": i, "ts": ts, "source": source, "finding": "f", "class": "c", "status": status, "recurrences": rec,
                    "weight": w or lessons.WEIGHTS[source], "proposedDisposition": disp}
        return [r("a", "draft", "test-fail", 5, "2026-10-01T00:00:00Z"),                # 1 x 5 = 5
                r("b", "draft", "human-correction", 2, "2026-10-02T00:00:00Z"),         # 3 x 2 = 6
                r("c", "recurred", "test-fail", 1, "2026-10-03T00:00:00Z"),             # 1, but recurred
                r("d", "draft", "eval-fail", 3, "2026-10-04T00:00:00Z"),                # 2 x 3 = 6, newer than b
                r("e", "closed", "eval-fail", 9, "2026-10-05T00:00:00Z"),
                r("f", "draft", "test-fail", 1, "2026-10-06T00:00:00Z", disp="parked")]

    def test_order_filters(self):
        order = [l["id"] for l in lessons.listing(self.rows())]
        self.assertEqual(order[0], "c")
        self.assertEqual(order[:3], ["c", "e", "d"])
        self.assertLess(order.index("d"), order.index("b"), "equal weight x recurrences: newest first")
        self.assertEqual([l["id"] for l in lessons.listing(self.rows(), status="draft")][:2], ["d", "b"])
        self.assertEqual({l["id"] for l in lessons.listing(self.rows(), source="human-correction")}, {"b"})

    def test_open_ranked_leaves_out_closed_and_parked(self):
        self.assertEqual([l["id"] for l in lessons.open_ranked(self.rows())], ["c", "d", "b", "a"])

    def test_the_mine_step_prints_open_lessons(self):
        report = {"summary": {"tasks": 0, "roots": ["runs"], "sessions": 0, "toolCalls": 0, "evidenceLines": 0}, "notes": [], "classes": [],
                  "result": "clean", "failHits": 0, "warnHits": 0, "lessons": lessons.open_ranked(self.rows())}
        out = audit.render(report)
        self.assertIn("open lessons", out)
        self.assertLess(out.index(" c "), out.index(" d "))


class SeedTests(Env):
    def test_export_keeps_only_portable_rows_and_no_path_or_ref(self):
        base = {"ts": NOW, "source": "human-correction", "sourceRef": "https://github.com/acn-yogi/humanize/pull/3#c1", "signature": "x" * 40,
                "status": "closed", "recurrences": 4, "weight": 3, "approvedBy": "yogi", "closedBy": "yogi", "note": "see C:\\code\\acme\\notes.md",
                "links": {"caseId": "case-1", "specId": "s", "packId": "pack-d812d07de777", "prRef": "https://github.com/acn-yogi/humanize/pull/3"}}
        rows = [dict(base, id="les-aaaaaaaa", portable=True, **{"class": "lint"}, proposedDisposition="pack",
                     finding="Lint findings in src/humanize/number.py at Acme PR #3 (https://github.com/acn-yogi/humanize/pull/3) t-01M4RYVYEG6H31MRD8C2N01K04 abcdef1234",
                     evidence=["runs/proofs/a/verdict.json", "task:t-01M4RYVYEG6H31MRD8C2N01K04", "C:\\code\\acme\\x.py"]),
                dict(base, id="les-bbbbbbbb", portable=False, **{"class": "scope"}, proposedDisposition="spec", finding="not portable", evidence=["runs/x"])]
        lessons.append_rows(self.lessons, rows)
        out = self.cwd / "seed.json"
        n = lessons.seed_export(lessons.read_rows(self.lessons), out, deny=["Acme"])
        self.assertEqual(n, 1)
        text = out.read_text(encoding="utf-8")
        data = json.loads(text)
        self.assertEqual(set(data["lessons"][0]), {"class", "finding", "proposedDisposition"})
        for leak in ("src/humanize", "runs/", "C:\\", "acme", "Acme", "pull/", "#3", "t-01M4", "abcdef1234", "pack-d812", "case-1", "https", "yogi", "evidence", "not portable"):
            self.assertNotIn(leak, text)
        self.assertIn("Lint findings", data["lessons"][0]["finding"])

    def test_import_makes_external_drafts_and_is_idempotent(self):
        seed = self.cwd / "seed.json"
        seed.write_text(json.dumps({"v": 1, "lessons": [{"class": "lint", "finding": "Lint findings", "proposedDisposition": "pack"}]}), encoding="utf-8")
        first = lessons.seed_import(self.lessons, seed, NOW)
        self.assertEqual(len(first), 1)
        les = self.only()
        self.assertEqual((les["source"], les["status"], les["proposedDisposition"], les["weight"], les["portable"]), ("external", "draft", "pack", 2, True))
        self.assertEqual(les["evidence"][0].split(":")[0], "seed")
        self.assertEqual(lessons.seed_import(self.lessons, seed, NOW), [])

    def test_a_round_trip_matches_the_signature_of_a_local_lesson(self):
        self.put_ledger([corrected("2026-10-13T10:00:00Z", "lint")])
        self.draft()
        lid = self.only()["id"]
        lessons.approve(self.lessons, lid, "yogi", portable=True, env={}, stamp=NOW)
        out = self.cwd / "seed.json"
        lessons.seed_export(lessons.read_rows(self.lessons), out)
        other = self.cwd / "other.jsonl"
        lessons.seed_import(other, out, NOW)
        self.assertEqual(next(iter(lessons.fold(lessons.read_rows(other)))), lid)

    def test_import_refuses_a_malformed_seed(self):
        seed = self.cwd / "seed.json"
        seed.write_text(json.dumps({"lessons": [{"class": "x", "finding": "y", "proposedDisposition": "invent"}]}), encoding="utf-8")
        with self.assertRaises(lessons.LessonError):
            lessons.seed_import(self.lessons, seed, NOW)


class MetricsTests(unittest.TestCase):
    def row(self, i, ts, status, source="test-fail"):
        return {"id": i, "ts": ts, "source": source, "status": status, "recurrences": 1, "weight": 1, "proposedDisposition": "case"}

    def rows(self):
        return [self.row("a", "2026-10-01T00:00:00Z", "draft", "human-correction"), self.row("a", "2026-10-03T00:00:00Z", "closed", "human-correction"),
                self.row("b", "2026-10-01T00:00:00Z", "draft", "eval-fail"), self.row("b", "2026-10-02T00:00:00Z", "closed", "eval-fail"),
                self.row("b", "2026-10-05T00:00:00Z", "recurred", "eval-fail"),
                self.row("c", "2026-10-02T00:00:00Z", "draft"), self.row("d", "2026-10-02T00:00:00Z", "draft"),
                self.row("e", "2026-10-01T00:00:00Z", "draft"), self.row("e", "2026-10-07T00:00:00Z", "closed")]

    def test_numbers(self):
        m = lessons.metrics(self.rows())
        self.assertEqual((m["opened"], m["closed"], m["closedEver"], m["recurred"], m["open"]), (5, 2, 3, 1, 3))
        self.assertEqual(m["medianDaysToClose"], 2.0)    # closes took 2, 1 and 6 days
        self.assertEqual(m["bySource"]["human-correction"], 1)
        self.assertEqual(m["bySource"]["eval-fail"], 1)
        self.assertEqual(m["bySource"]["test-fail"], 3)
        self.assertEqual(m["shareBySource"]["test-fail"], 0.6)
        self.assertEqual(m["closedLessonsThatCameBack"], {"count": 1, "ofClosed": 3, "rate": 0.3333})

    def test_empty(self):
        m = lessons.metrics([])
        self.assertEqual((m["opened"], m["medianDaysToClose"], m["closedLessonsThatCameBack"]["rate"]), (0, None, None))
        self.assertTrue(lessons.render_metrics(m))

    def test_scorecard_carries_the_block(self):
        s = scorecard.compute([], None, [], {"bytes": 1, "files": 1, "paths": []}, self.rows())
        self.assertEqual(s["lessons"]["opened"], 5)
        text = scorecard.render(s)
        self.assertIn("5 opened, 2 closed, 1 recurred", text)
        self.assertIn("closed lessons that came back  1 of 3 closed (33%)", text)
        self.assertIn("human correction 20%, eval fail 20%, test 60%", text)
        self.assertEqual(scorecard.compute([], None, [], {"bytes": 1, "files": 1, "paths": []})["lessons"]["opened"], 0)


class RecordedSampleTests(unittest.TestCase):
    def test_the_recorded_sample_is_what_draft_makes_from_the_recordings(self):
        sample = ROOT / "demo/recordings/lessons.jsonl"
        self.assertTrue(sample.exists())
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "l.jsonl"
            lessons.draft(ROOT, out, ledger=ROOT / "demo/recordings/ledger.jsonl", proof_dirs=[ROOT / "demo/recordings/proof"],
                          roots=[ROOT / "demo/recordings"], stamp="2026-10-16T00:00:00Z")
            self.assertEqual(out.read_text(encoding="utf-8"), sample.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
