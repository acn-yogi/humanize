"""judge.py with a stand-in for claude -p: independence, rubric claims, A/B blinding, repeat agreement."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import judge  # noqa: E402

QUOTE = "ruff check src tests"


def make_trial(root: Path, name: str, worker="sonnet") -> Path:
    d = root / name
    d.mkdir(parents=True)
    packet = {"taskId": f"t-{name}", "models": {"worker": worker, "reviewer": "opus"}, "allChecksPass": True, "review": {"verdict": "approve"},
              "changedPaths": ["src/x.py"], "loops": {"finish": []}}
    (d / "packet.json").write_text(json.dumps(packet), encoding="utf-8")
    events = [{"type": "system", "subtype": "init", "session_id": "s"},
              {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "1", "name": "Bash", "input": {"command": QUOTE}}]}},
              {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "1", "content": "All checks passed!"}]}},
              {"type": "assistant", "message": {"content": [{"type": "text", "text": "Done."}]}},
              {"type": "result", "subtype": "success", "result": "Done.", "num_turns": 2, "total_cost_usd": 0.1}]
    (d / "transcript.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    (d / "diff.patch").write_text("+++ b/src/x.py\n+x = 1\n", encoding="utf-8")
    (d / "ruff.txt").write_text("All checks passed!\n", encoding="utf-8")
    return d


def reply(verdict="earned", quote=QUOTE, preferred=None, cost=0.05):
    body = {"claims": [{"claim": "the agent ran ruff", "quote": quote, "holds": True}], "verdict": verdict, "reasons": ["ran it"]}
    if preferred:
        body["preferred"] = preferred
    return {"result": json.dumps(body), "total_cost_usd": cost, "num_turns": 1, "subtype": "success"}


class Runner:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def __call__(self, prompt, model, budget, max_turns, config_dir):
        self.prompts.append(prompt)
        return self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]


class JudgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_records_the_judge_model_and_the_rubric_claims(self):
        d = make_trial(self.root, "a")
        out = judge.judge_trial(d, "opus", runner=Runner(reply()))
        self.assertEqual((out["judgeModel"], out["workerModel"], out["verdict"], out["quoteFound"]), ("opus", "sonnet", "earned", True))
        self.assertEqual(out["claims"][0]["quote"], QUOTE)
        self.assertTrue(out["claims"][0]["quoteFound"])
        self.assertEqual(json.loads((d / "judge.json").read_text(encoding="utf-8"))["judgeModel"], "opus")
        self.assertIsNone(out["judgeBlind"])

    def test_refuses_when_the_judge_is_the_model_that_ran_the_trial(self):
        d = make_trial(self.root, "a")
        runner = Runner(reply())
        out = judge.judge_trial(d, "sonnet", runner=runner)
        self.assertEqual(out["verdict"], "judge-not-independent")
        self.assertEqual(out["judgeModel"], "sonnet")
        self.assertEqual(runner.prompts, [])    # nothing was asked, nothing spent
        self.assertEqual(out["costUsd"], 0.0)
        out2 = judge.judge_trial(d, "claude-sonnet-5-5", runner=runner)   # a full id of the same family name
        self.assertEqual(out2["verdict"], "judge-not-independent")
        self.assertEqual(judge.main([str(d), "--model", "sonnet"]), 2)

    def test_the_served_model_counts_as_the_trial_model_too(self):
        d = make_trial(self.root, "a", worker="sonnet")
        p = json.loads((d / "packet.json").read_text(encoding="utf-8"))
        p["fingerprint"] = {"servedModel": {"author": "claude-opus-5-5"}}
        (d / "packet.json").write_text(json.dumps(p), encoding="utf-8")
        self.assertEqual(judge.judge_trial(d, "opus", runner=Runner(reply()))["verdict"], "judge-not-independent")

    def test_a_claim_whose_quote_is_not_in_the_transcript_makes_the_verdict_unknown(self):
        d = make_trial(self.root, "a")
        out = judge.judge_trial(d, "opus", runner=Runner(reply(quote="never said this")))
        self.assertEqual(out["verdict"], "unknown")
        self.assertFalse(out["quoteFound"])

    def test_the_prompt_asks_for_a_rubric_of_quoted_claims_not_a_scale(self):
        d = make_trial(self.root, "a")
        r = Runner(reply())
        judge.judge_trial(d, "opus", runner=r)
        self.assertIn("rubric", r.prompts[0])
        self.assertIn("verbatim quote", r.prompts[0])
        self.assertIn("Do not score on a numeric scale", r.prompts[0])

    def test_the_older_single_quote_reply_still_parses_as_one_claim(self):
        d = make_trial(self.root, "a")
        legacy = {"result": json.dumps({"verdict": "earned", "quote": QUOTE, "reasons": ["x"]}), "total_cost_usd": 0.01}
        out = judge.judge_trial(d, "opus", runner=Runner(legacy))
        self.assertEqual((out["verdict"], len(out["claims"])), ("earned", 1))

    def test_a_reply_with_no_claim_is_unknown(self):
        d = make_trial(self.root, "a")
        out = judge.judge_trial(d, "opus", runner=Runner({"result": json.dumps({"claims": [], "verdict": "earned", "reasons": []})}))
        self.assertEqual(out["verdict"], "unknown")

    def test_ab_shuffle_is_deterministic_per_seed_and_covers_both_orders(self):
        orders = {tuple(judge.shuffle_ab("B4", "AFTER", str(s))[2].values()) for s in range(30)}
        self.assertEqual(orders, {("before", "after"), ("after", "before")})
        self.assertEqual(judge.shuffle_ab("x", "y", "7"), judge.shuffle_ab("x", "y", "7"))
        a, b, order = judge.shuffle_ab("BEFORE-TEXT", "AFTER-TEXT", "1")
        self.assertEqual({a, b}, {"BEFORE-TEXT", "AFTER-TEXT"})
        self.assertEqual(order["A"], "before" if a == "BEFORE-TEXT" else "after")

    def test_compare_mode_is_blind_and_maps_the_preference_back(self):
        before = make_trial(self.root, "before")
        (before / "diff.patch").write_text("+++ b/src/x.py\n+BEFORE_MARK\n", encoding="utf-8")
        after = make_trial(self.root, "after")
        (after / "diff.patch").write_text("+++ b/src/x.py\n+AFTER_MARK\n", encoding="utf-8")
        r = Runner(reply(preferred="A"))
        out = judge.judge_trial(after, "opus", before=before, seed="3", runner=r)
        self.assertTrue(out["judgeBlind"])
        self.assertIn("RESULT A", r.prompts[0])
        self.assertLess(r.prompts[0].index("RESULT A"), r.prompts[0].index("RESULT B"))
        first = "BEFORE_MARK" if out["abOrder"]["A"] == "before" else "AFTER_MARK"
        self.assertLess(r.prompts[0].index(first), r.prompts[0].index("RESULT B"))
        self.assertEqual(out["preferred"], out["abOrder"]["A"])
        self.assertNotIn("before", r.prompts[0].split("RESULT A")[1].split("TRANSCRIPT")[0].lower().replace("before_mark", ""))

    def test_repeat_one_is_unanimous_by_construction(self):
        d = make_trial(self.root, "a")
        out = judge.judge_trial(d, "opus", runner=Runner(reply()))
        self.assertEqual(out["graderAgreement"], {"runs": 1, "agreed": 1, "disagreeing": 0})

    def test_repeat_n_records_agreement_and_runs_the_judge_n_times(self):
        d = make_trial(self.root, "a")
        r = Runner(reply(), reply(), reply())
        out = judge.judge_trial(d, "opus", repeat=3, runner=r)
        self.assertEqual(len(r.prompts), 3)
        self.assertEqual(out["graderAgreement"], {"runs": 3, "agreed": 3, "disagreeing": 0})
        self.assertEqual(out["verdict"], "earned")
        self.assertAlmostEqual(out["costUsd"], 0.15)

    def test_disagreeing_runs_make_the_verdict_unknown(self):
        d = make_trial(self.root, "a")
        out = judge.judge_trial(d, "opus", repeat=3, runner=Runner(reply(), reply("gamed"), reply()))
        self.assertEqual(out["graderAgreement"], {"runs": 3, "agreed": 2, "disagreeing": 1})
        self.assertEqual(out["verdict"], "unknown")
        self.assertTrue(out["reasons"][0].startswith("the judge runs disagreed"))

    def test_the_cli_dry_run_asks_no_model_and_writes_nothing(self):
        d = make_trial(self.root, "a")
        self.assertEqual(judge.main([str(d), "--dry-run", "--repeat", "3"]), 0)
        self.assertFalse((d / "judge.json").exists())
        self.assertEqual(judge.main([str(d), "--repeat", "0"]), 2)


if __name__ == "__main__":
    unittest.main()
