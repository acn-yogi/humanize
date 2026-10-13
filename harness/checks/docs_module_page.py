#!/usr/bin/env python3
"""Check that a module's documentation page introduces the module before its API reference.

    docs_module_page.py docs/number.md humanize.number

Run from the repository root of the result. Today each page under docs/ is a title and a
`::: humanize.<module>` directive, so the site shows an API dump with no introduction. The
page must keep the directive and gain, above it, at least 60 words of prose that says what the
module is for, and at least one fenced ```python block whose code runs as written against the
installed humanize (the block is executed; print output is not compared). Prints one FAIL line
per problem or one PASS line, exits 1 on any problem. Fails on today's code.
"""

from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

MIN_WORDS = 60


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: docs_module_page.py docs/<module>.md humanize.<module>")
        return 2
    page, module = Path(sys.argv[1]), sys.argv[2]
    problems: list[str] = []
    if not page.exists():
        print(f"FAIL: {page} does not exist")
        return 1
    text = page.read_text(encoding="utf-8")
    m = re.search(rf"^:::\s+{re.escape(module)}\s*$", text, re.M)
    if not m:
        problems.append(f"the directive ::: {module} is missing (the API reference must stay)")
        above = text
    else:
        above = text[: m.start()]
    blocks = re.findall(r"```python\n(.*?)```", above, re.S)
    prose = re.sub(r"```.*?```", " ", above, flags=re.S)
    prose = re.sub(r"^#.*$", " ", prose, flags=re.M)
    words = len(re.findall(r"[A-Za-z][A-Za-z'-]+", prose))
    if words < MIN_WORDS:
        problems.append(f"{words} word(s) of prose above the directive; at least {MIN_WORDS} are needed")
    if not blocks:
        problems.append("no ```python example block above the directive")
    importlib.import_module(module)
    for i, code in enumerate(blocks, 1):
        src = "\n".join(line[4:] if line.startswith(">>> ") else line for line in code.splitlines() if not line.startswith("..."))
        if ">>>" in code:
            src = "\n".join(l[4:] for l in code.splitlines() if l.startswith(">>> "))
        try:
            exec(compile(src, f"{page}:block{i}", "exec"), {"__name__": "__docs__"})
        except Exception as e:  # noqa: BLE001
            problems.append(f"python block {i} does not run: {type(e).__name__}: {e}")
    for p in problems:
        print(f"FAIL: {page}: {p}")
    if not problems:
        print(f"PASS: {page}: {words} words of introduction, {len(blocks)} runnable example block(s), directive kept")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
