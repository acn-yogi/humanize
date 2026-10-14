#!/usr/bin/env python3
"""The environment fingerprint of a run: pack id, Claude Code version, served model.

    fingerprint.py served <transcript.jsonl>     -> the served model, read from the transcript, as JSON
    fingerprint.py packet <task run dir>         -> the task's fingerprint and its configured models
    fingerprint.py compare <a.json> <b.json>     -> {comparison, differences}

The served model is what the API answered with, not what the configuration asked for: Claude
Code's stream-json carries it on every assistant message (message.model). A session that ran
on the account's headless default instead of the configured model shows up here, in the
packet, instead of being discovered later from a transcript. One unique model is the string;
several (a mid-session switch) are joined with commas; none is null.

A configured model is an alias ("sonnet", "opus", "haiku") or a full id. An alias matches a
served id of that family (claude-sonnet-5-5 for "sonnet"); a full id matches itself only.

Two runs compare only when their fingerprints agree on everything but the pack id, which is
the one thing a proof changes on purpose. Standard library only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ALIASES = ("sonnet", "opus", "haiku")
FIELDS = ("packId", "claudeCodeVersion", "servedModel")


def served_model(path: Path) -> str | None:
    """The model(s) the assistant messages of a stream-json transcript carry; null when none."""
    if not path.exists():
        return None
    seen: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict) or ev.get("type") != "assistant":
            continue
        msg = ev.get("message")
        model = msg.get("model") if isinstance(msg, dict) else None
        # "<synthetic>" is Claude Code's placeholder on the assistant message it writes itself
        # when the API call failed (an API error, a proxy death): nothing was served.
        if isinstance(model, str) and model and not model.startswith("<") and model not in seen:
            seen.append(model)
    return ",".join(seen) if seen else None


def matches(configured: str | None, served: str | None) -> bool | None:
    """True when the served model is what was configured; None when either side is unknown."""
    if not configured or not served:
        return None
    for one in served.split(","):
        if one == configured:
            continue
        if configured in ALIASES and one.startswith("claude-") and f"-{configured}-" in f"-{one[len('claude-'):]}-":
            continue
        return False
    return True


def of_packet(packet: dict, task_dir: Path | None = None) -> dict:
    """The packet's fingerprint; derived from the transcripts beside it when the packet predates the field."""
    fp = packet.get("fingerprint")
    if isinstance(fp, dict) and all(k in fp for k in FIELDS):
        return {k: fp.get(k) for k in FIELDS}
    served = {"author": None, "reviewer": None}
    if task_dir is not None:
        served = {"author": served_model(task_dir / "transcript.jsonl"), "reviewer": served_model(task_dir / "review-transcript.jsonl")}
    return {"packId": packet.get("packId"), "claudeCodeVersion": packet.get("claudeCodeVersion"), "servedModel": served}


def configured_models(packet: dict) -> dict:
    models = packet.get("configuredModel")
    if isinstance(models, dict):
        return {"author": models.get("author"), "reviewer": models.get("reviewer")}
    models = packet.get("models") or {}
    return {"author": models.get("worker"), "reviewer": models.get("reviewer")}


def mismatches(fp: dict, configured: dict) -> list[str]:
    """One line per role whose served model is not the configured one."""
    out = []
    for role in ("author", "reviewer"):
        served = (fp.get("servedModel") or {}).get(role)
        if matches(configured.get(role), served) is False:
            out.append(f"{role}: configured {configured.get(role)}, served {served}")
    return out


def strip(fp: dict | None, ignore: tuple[str, ...] = ("packId",)) -> dict | None:
    if not isinstance(fp, dict):
        return None
    return {k: fp.get(k) for k in FIELDS if k not in ignore}


def compare(before: list[dict] | dict | None, after: list[dict] | dict | None, ignore: tuple[str, ...] = ("packId",)) -> dict:
    """Whether two sides of a proof ran on the same environment. Each side is one fingerprint or
    the list of fingerprints its trials carried; the pack id is ignored (it is the thing under test)."""
    def norm(side) -> list[dict]:
        if side is None:
            return []
        rows = side if isinstance(side, list) else [side]
        out: list[dict] = []
        for r in rows:
            s = strip(r, ignore)
            if s is not None and s not in out:
                out.append(s)
        return out
    b, a = norm(before), norm(after)
    if not b or not a:
        return {"comparison": "fingerprint-not-recorded", "differences": ["one side carries no fingerprint"]}
    differences: list[str] = []
    for field in FIELDS:
        if field in ignore:
            continue
        bv = sorted({json.dumps(x.get(field), sort_keys=True) for x in b})
        av = sorted({json.dumps(x.get(field), sort_keys=True) for x in a})
        if bv != av or len(bv) > 1 or len(av) > 1:
            differences.append(f"{field}: before {', '.join(bv)}; after {', '.join(av)}")
    return {"comparison": "invalid-fingerprint" if differences else "valid", "differences": differences}


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "served":
        print(json.dumps(served_model(Path(argv[1]))))
        return 0
    if len(argv) == 2 and argv[0] == "packet":
        d = Path(argv[1])
        packet = json.loads((d / "packet.json").read_text(encoding="utf-8"))
        fp = of_packet(packet, d)
        cfg = configured_models(packet)
        print(json.dumps({"fingerprint": fp, "configuredModel": cfg, "mismatches": mismatches(fp, cfg)}))
        return 0
    if len(argv) == 3 and argv[0] == "compare":
        a = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        b = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        print(json.dumps(compare(a, b)))
        return 0
    print("usage: fingerprint.py served <transcript.jsonl> | packet <task run dir> | compare <a.json> <b.json>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
