from __future__ import annotations

import pytest

from humanize.cli import main


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["naturalsize", "8589934592"], "8.6 GB\n"),
        (["naturalsize", "--binary", "8589934592"], "8.0 GiB\n"),
        (["naturalsize", "--gnu", "8589934592"], "8.0G\n"),
        (["naturalsize", "--format", "%.3f", "8589934592"], "8.590 GB\n"),
        (["intcomma", "1234567"], "1,234,567\n"),
        (["intword", "1200000"], "1.2 million\n"),
        (["naturaldelta", "3600"], "an hour\n"),
    ],
)
def test_commands(
    capsys: pytest.CaptureFixture[str], argv: list[str], expected: str
) -> None:
    assert main(argv) == 0
    assert capsys.readouterr().out == expected


@pytest.mark.parametrize(
    "argv",
    [
        ["naturalsize", "abc"],
        ["naturalsize", "nan"],
        ["intcomma", "abc"],
        ["intcomma", "inf"],
        ["intword", "abc"],
        ["intword", "nan"],
        ["naturaldelta", "abc"],
        ["naturaldelta", "inf"],
        ["naturaldelta", "nan"],
    ],
)
def test_bad_value(capsys: pytest.CaptureFixture[str], argv: list[str]) -> None:
    assert main(argv) != 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err


def test_no_command() -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code != 0
