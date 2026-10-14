"""The environment fingerprint: served model from the recorded transcripts, alias matching, comparison."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import fingerprint  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RECORDED = sorted((ROOT / "demo/recordings").glob("t-*"))


def fp(pack="pack-a", version="2.1.296 (Claude Code)", author="claude-sonnet-5-5", reviewer="claude-opus-5-5"):
    return {"packId": pack, "claudeCodeVersion": version, "servedModel": {"author": author, "reviewer": reviewer}}


class ServedModelTests(unittest.TestCase):
    def test_the_recorded_transcripts_name_the_served_models(self):
        self.assertTrue(RECORDED, "no recorded task")
        for d in RECORDED:
            self.assertEqual(fingerprint.served_model(d / "transcript.jsonl"), "claude-sonnet-5-5", d.name)
            self.assertEqual(fingerprint.served_model(d / "review-transcript.jsonl"), "claude-opus-5-5", d.name)

    def test_synthetic_messages_are_not_a_served_model(self):
        # The proof trials that died on a proxy carry only Claude Code's own "<synthetic>" assistant message.
        dead = ROOT / "demo/recordings/proof/lint-in-quick-checks/current/t-01M4TWWB3XYF0CN8WP2XG415N8/transcript.jsonl"
        self.assertIsNone(fingerprint.served_model(dead))
        mixed = ROOT / "demo/recordings/proof/lint-in-quick-checks/current/t-01M4TW8TYH7AES6AB31KYJ3GMQ/review-transcript.jsonl"
        self.assertEqual(fingerprint.served_model(mixed), "claude-opus-5-5")

    def test_a_missing_transcript_is_null(self):
        self.assertIsNone(fingerprint.served_model(ROOT / "demo/recordings/no-such-file.jsonl"))

    def test_a_recorded_packet_without_the_field_derives_it_from_the_transcripts(self):
        d = RECORDED[0]
        packet = json.loads((d / "packet.json").read_text(encoding="utf-8"))
        got = fingerprint.of_packet(packet, d)
        self.assertEqual(got["packId"], packet["packId"])
        self.assertEqual(got["claudeCodeVersion"], packet["claudeCodeVersion"])
        self.assertEqual(got["servedModel"], {"author": "claude-sonnet-5-5", "reviewer": "claude-opus-5-5"})
        self.assertEqual(fingerprint.mismatches(got, fingerprint.configured_models(packet)), [])

    def test_a_packet_with_the_field_is_read_as_is(self):
        packet = {"packId": "x", "claudeCodeVersion": "y", "fingerprint": fp(author="claude-haiku-5"), "configuredModel": {"author": "sonnet", "reviewer": "opus"}}
        got = fingerprint.of_packet(packet, RECORDED[0])
        self.assertEqual(got["servedModel"]["author"], "claude-haiku-5")
        self.assertEqual(fingerprint.mismatches(got, fingerprint.configured_models(packet)), ["author: configured sonnet, served claude-haiku-5"])


class MatchTests(unittest.TestCase):
    def test_an_alias_matches_its_family(self):
        self.assertTrue(fingerprint.matches("sonnet", "claude-sonnet-5-5"))
        self.assertTrue(fingerprint.matches("opus", "claude-opus-5-5"))
        self.assertFalse(fingerprint.matches("opus", "claude-sonnet-5-5"))

    def test_a_full_id_matches_itself_only(self):
        self.assertTrue(fingerprint.matches("claude-sonnet-5-5", "claude-sonnet-5-5"))
        self.assertFalse(fingerprint.matches("claude-sonnet-5-5", "claude-sonnet-5"))

    def test_a_mid_session_switch_is_a_mismatch(self):
        self.assertFalse(fingerprint.matches("sonnet", "claude-sonnet-5-5,claude-opus-5-5"))

    def test_unknown_sides_are_undecided(self):
        self.assertIsNone(fingerprint.matches("sonnet", None))
        self.assertIsNone(fingerprint.matches(None, "claude-sonnet-5-5"))


class CompareTests(unittest.TestCase):
    def test_same_environment_with_a_new_pack_is_valid(self):
        c = fingerprint.compare([fp("pack-a")], [fp("pack-b")])
        self.assertEqual(c, {"comparison": "valid", "differences": []})

    def test_a_different_claude_code_version_is_invalid(self):
        c = fingerprint.compare([fp()], [fp(version="2.2.0 (Claude Code)")])
        self.assertEqual(c["comparison"], "invalid-fingerprint")
        self.assertTrue(c["differences"][0].startswith("claudeCodeVersion"))

    def test_a_different_served_model_is_invalid(self):
        c = fingerprint.compare(fp(), fp(author="claude-haiku-5"))
        self.assertEqual(c["comparison"], "invalid-fingerprint")
        self.assertTrue(c["differences"][0].startswith("servedModel"))

    def test_a_mixed_side_is_invalid(self):
        c = fingerprint.compare([fp(), fp(author="claude-haiku-5")], [fp()])
        self.assertEqual(c["comparison"], "invalid-fingerprint")

    def test_a_side_without_a_fingerprint_is_not_a_comparison(self):
        self.assertEqual(fingerprint.compare([], [fp()])["comparison"], "fingerprint-not-recorded")
        self.assertEqual(fingerprint.compare(None, None)["comparison"], "fingerprint-not-recorded")


if __name__ == "__main__":
    unittest.main()
