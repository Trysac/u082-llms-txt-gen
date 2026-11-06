"""Command line interface: ``python -m llms_txt_gen``."""

from __future__ import annotations

import argparse
import difflib
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .core import (
    DocEntry,
    LlmsTxtError,
    build_llms_full,
    build_llms_txt,
    discover_docs,
    project_title,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llms-txt-gen",
        description="Generate llms.txt and llms-full.txt from a repository's Markdown docs.",
    )
    parser.add_argument("root", nargs="?", default=".", help="repository root (default: .)")
    parser.add_argument("--name", help="project name (default: the H1 of README.md)")
    parser.add_argument("--summary", help="summary (default: first README paragraph)")
    parser.add_argument("--base-url", help="absolute http(s) URL prefixed to every link")
    parser.add_argument(
        "--optional",
        action="append",
        default=[],
        metavar="GLOB",
        help="glob of files for the Optional section (repeatable)",
    )
    parser.add_argument("--out", default="llms.txt", help="llms.txt path, relative to ROOT")
    parser.add_argument(
        "--full",
        nargs="?",
        const="llms-full.txt",
        default=None,
        metavar="PATH",
        help="also write llms-full.txt (default path: llms-full.txt)",
    )
    parser.add_argument("--max-bytes", type=int, default=2_000_000, help="llms-full byte cap")
    parser.add_argument("--check", action="store_true", help="fail with a diff when stale")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _readme_summary(entries: Sequence[DocEntry]) -> str:
    for entry in entries:
        if entry.path == "README.md":
            return entry.summary
    return ""


def _report_drift(path: Path, label: str, text: str) -> bool:
    """Print a unified diff when ``path`` differs from ``text``; return whether it differs."""
    expected = text.encode("utf-8")
    try:
        current: bytes | None = path.read_bytes()
    except FileNotFoundError:
        current = None
    if current == expected:
        return False
    old_text = "" if current is None else current.decode("utf-8", errors="replace")
    diff = difflib.unified_diff(
        old_text.splitlines(keepends=True),
        text.splitlines(keepends=True),
        fromfile=label,
        tofile="generated",
    )
    for line in diff:
        sys.stdout.write(line if line.endswith("\n") else f"{line}\n")
    return True


def _run(args: argparse.Namespace) -> int:
    root = Path(args.root)
    discovery = discover_docs(root, optional=args.optional)
    for warning in discovery.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    name = args.name or project_title(root) or ""
    summary = args.summary if args.summary is not None else _readme_summary(discovery.entries)
    text = build_llms_txt(name, summary, discovery.entries, base_url=args.base_url)
    outputs: list[tuple[str, str]] = [(args.out, text)]
    if args.full is not None:
        full = build_llms_full(root, discovery.entries, max_bytes=args.max_bytes)
        outputs.append((args.full, full))
    if args.check:
        stale = [_report_drift(root / label, label, content) for label, content in outputs]
        return 1 if any(stale) else 0
    for label, content in outputs:
        (root / label).write_bytes(content.encode("utf-8"))
        print(f"wrote {label}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the command line interface and return the process exit code.

    Exit codes: 0 success; 1 stale files (``--check``) or too many files; 2 usage, I/O or
    parse error. Warnings about skipped files go to stderr.
    """
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    try:
        return _run(args)
    except LlmsTxtError as exc:
        print(f"error: {exc.code}: {exc}", file=sys.stderr)
        return 1 if exc.code == "too_many_files" else 2
    except (OSError, UnicodeDecodeError) as exc:
        print(f"error: {type(exc).__name__}: {exc!s:.200}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
