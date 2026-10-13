"""Command-line interface: `humanize` and `python -m humanize`."""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Sequence

import humanize


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="humanize", description="Humanize numbers, sizes and durations."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    size = sub.add_parser("naturalsize", help="format a number of bytes")
    size.add_argument("value")
    size.add_argument("--binary", action="store_true", help="use KiB, MiB, ...")
    size.add_argument("--gnu", action="store_true", help="use GNU-style suffixes")
    size.add_argument("--format", default="%.1f", help="printf-style format")

    comma = sub.add_parser("intcomma", help="add thousands separators")
    comma.add_argument("value")

    word = sub.add_parser("intword", help="express a large number in words")
    word.add_argument("value")

    delta = sub.add_parser("naturaldelta", help="describe a duration in seconds")
    delta.add_argument("value", help="number of seconds")
    return parser


def _check_finite(value: str) -> None:
    """Raise ValueError unless value is a finite number."""
    try:
        number = float(value)
    except ValueError:
        msg = f"not a number: {value!r}"
        raise ValueError(msg) from None
    if not math.isfinite(number):
        msg = f"not a finite number: {value!r}"
        raise ValueError(msg)


def _run(args: argparse.Namespace) -> str:
    _check_finite(args.value)
    if args.command == "naturalsize":
        return humanize.naturalsize(
            args.value, binary=args.binary, gnu=args.gnu, format=args.format
        )
    if args.command == "intcomma":
        return humanize.intcomma(args.value)
    if args.command == "intword":
        return humanize.intword(args.value)
    return humanize.naturaldelta(float(args.value))


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line interface and return the exit status."""
    args = _build_parser().parse_args(argv)
    try:
        result = _run(args)
    except (ValueError, TypeError, OverflowError) as e:
        print(f"humanize: error: {e}", file=sys.stderr)
        return 1
    print(result)
    return 0
