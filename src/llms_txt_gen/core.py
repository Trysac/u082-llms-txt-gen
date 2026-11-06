"""Generate ``llms.txt`` and ``llms-full.txt`` from a repository's Markdown documentation.

The ``llms.txt`` format follows the llms.txt proposal (https://llmstxt.org, 2024): one H1
with the project name (the only required part), an optional blockquote summary, optional
paragraphs, then H2 sections of ``- [name](url)`` items with optional ``: notes``.
``llms-full.txt`` is a community convention and is not part of the proposal.
"""

from __future__ import annotations

import codecs
import fnmatch
import logging
import os
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import chain
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import quote, urlsplit

logger = logging.getLogger(__name__)

ErrorCode = Literal[
    "no_title",
    "root_missing",
    "invalid_base_url",
    "invalid_glob",
    "too_many_files",
    "input_too_large",
    "invalid_limit",
    "path_outside_root",
]
ProblemCode = Literal["missing_h1", "missing_summary", "malformed_link", "heading_order"]

MAX_ENTRIES = 10_000
MAX_VALIDATE_CHARS = 2_000_000

_MAX_TEXT = 10_000
_SUMMARY_LIMIT = 160
_RAW_CAP = 2000
_LINE_CAP = 2000
_MAX_DEPTH = 32
_MAX_WARNINGS = 100
_MAX_GLOB_LENGTH = 512
_MAX_GLOB_PARTS = 32
_MAX_BASE_URL = 2048
_DEFAULT_MAX_FILE_BYTES = 1_048_576

_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_H1_RE = re.compile(r"^ {0,3}#[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")
_HEADING_RE = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|$)")
_HEADING_LEVEL_RE = re.compile(r"^ {0,3}(#{1,6})[ \t]+\S")
_NON_PROSE_RES = (
    re.compile(r"^(?: {4}|\t)"),
    re.compile(r"^\s*(?:[-*+]|\d+[.)])\s"),
    re.compile(r"^\s*(?:\||<!--)"),
    re.compile(r"^\s*[-*_](?:\s*[-*_]){2,}\s*$"),
)
_BLOCKQUOTE_RE = re.compile(r"^ {0,3}>[ \t]?")
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_REF_LINK_RE = re.compile(r"\[([^\]]*)\]\[[^\]]*\]")
_HTML_RE = re.compile(r"</?[A-Za-z][^>]*>")
_BOLD_RE = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_EM_STAR_RE = re.compile(r"\*(?=\S)([^*]+?)(?<=\S)\*")
_EM_UNDER_RE = re.compile(r"(?<!\w)_(?=\S)([^_]+?)(?<=\S)_(?!\w)")
_ITEM_START_RE = re.compile(r"^[-*+](?:\s|$)")
_ITEM_RE = re.compile(r"^- \[(?:\\.|[^\\\]])+\]\([^)\s]+\)(: .*)?$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_BAD_URL_RE = re.compile(r"[^\x21-\x7e]|[()<>\x22\\\[\]]")
_LINE_BREAK_RE = re.compile(r"[\r\n]")


class LlmsTxtError(Exception):
    """Base error of the library; ``code`` is a stable machine-readable identifier."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message[:200])
        self.code: ErrorCode = code


@dataclass(frozen=True, slots=True)
class DocEntry:
    """One documentation file listed in ``llms.txt``.

    Attributes:
        path: POSIX path relative to the repository root.
        title: Title of the document (first H1, else the file stem).
        summary: First paragraph of the document with Markdown markers removed.
        section: Name of the ``llms.txt`` H2 section the entry belongs to.
    """

    path: str
    title: str
    summary: str
    section: str


@dataclass(frozen=True, slots=True)
class Discovery:
    """Result of :func:`discover_docs`: the entries found and the warnings for skipped paths."""

    entries: list[DocEntry]
    warnings: list[str]


@dataclass(frozen=True, slots=True)
class Problem:
    """A format problem reported by :func:`validate_llms_txt` (``line`` is 1-based)."""

    code: ProblemCode
    line: int


def _clip(value: str, limit: int = 80) -> str:
    """Return at most ``limit`` characters of ``value`` on a single line."""
    return " ".join(value[:limit].split())


class _Warnings:
    """Collects at most ``_MAX_WARNINGS`` warnings and counts the overflow."""

    def __init__(self) -> None:
        self._items: list[str] = []
        self._overflow = 0

    def add(self, message: str) -> None:
        logger.debug("%s", message)
        if len(self._items) < _MAX_WARNINGS:
            self._items.append(message)
        else:
            self._overflow += 1

    def finish(self) -> list[str]:
        if self._overflow:
            return [*self._items, f"and {self._overflow} more"]
        return list(self._items)


# --------------------------------------------------------------------------- Markdown extraction


def _split_lines(text: str) -> list[str]:
    cleaned = text.removeprefix("\ufeff")
    return cleaned.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _opens_fence(match: re.Match[str]) -> bool:
    marker, info = match.group(1), match.group(2)
    return not (marker[0] == "`" and "`" in info)


def _closes_fence(match: re.Match[str], fence: tuple[str, int]) -> bool:
    marker = match.group(1)
    return marker[0] == fence[0] and len(marker) >= fence[1] and not match.group(2).strip()


def _scan(
    lines: Sequence[str],
    start: int = 0,
    cap: int = _LINE_CAP,
) -> Iterator[tuple[int, str]]:
    """Yield ``(line number, line)`` pairs outside fenced code blocks (numbers are 1-based)."""
    fence: tuple[str, int] | None = None
    for index in range(start, len(lines)):
        line = lines[index][:cap]
        match = _FENCE_RE.match(line)
        if fence is None:
            if match is not None and _opens_fence(match):
                fence = (match.group(1)[0], len(match.group(1)))
            else:
                yield index + 1, line
        elif match is not None and _closes_fence(match, fence):
            fence = None


def _front_matter_end(lines: Sequence[str]) -> int:
    """Return the index of the first line after YAML front matter (0 when there is none)."""
    if not lines or lines[0].rstrip() != "---":
        return 0
    for index in range(1, len(lines)):
        if lines[index].rstrip() in ("---", "..."):
            return index + 1
    return 0


def _content_lines(text: str) -> Iterator[str]:
    """Yield the lines of ``text`` outside YAML front matter and fenced code blocks."""
    lines = _split_lines(text)
    for _, line in _scan(lines, _front_matter_end(lines)):
        yield line


def _clean_inline(text: str) -> str:
    """Strip Markdown links, images, emphasis, inline code and HTML tags from ``text``."""
    text = _HTML_RE.sub("", text)
    text = _IMAGE_RE.sub("", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _REF_LINK_RE.sub(r"\1", text)
    text = _BOLD_RE.sub(r"\2", text)
    text = _EM_STAR_RE.sub(r"\1", text)
    text = _EM_UNDER_RE.sub(r"\1", text)
    text = text.replace("`", "")
    return " ".join(text.split())


def _shorten(text: str) -> str:
    if len(text) <= _SUMMARY_LIMIT:
        return text
    cut = text.rfind(" ", 0, _SUMMARY_LIMIT)
    if cut <= 0:
        cut = _SUMMARY_LIMIT
    return text[:cut].rstrip() + "..."


def _block_summary(block: list[str]) -> str:
    if not block or any(pattern.match(block[0]) for pattern in _NON_PROSE_RES):
        return ""
    joined = " ".join(_BLOCKQUOTE_RE.sub("", line) for line in block)
    return _clean_inline(joined[:_RAW_CAP])


def extract_title(text: str) -> str | None:
    """Return the first ATX H1 outside front matter and fenced code, or ``None``."""
    for line in _content_lines(text):
        match = _H1_RE.match(line)
        if match is not None:
            title = _clean_inline(match.group(1))
            if title:
                return title
    return None


def extract_summary(text: str) -> str:
    """Return the first prose paragraph of ``text`` as plain text.

    Links, images, emphasis and code markers are removed. Text longer than 160 characters is
    cut at the last space before that limit and ``...`` is appended.
    """
    block: list[str] = []
    size = 0
    for line in chain(_content_lines(text), [""]):
        if line.strip() and not _HEADING_RE.match(line):
            if size < _RAW_CAP:
                block.append(line)
                size += len(line)
            continue
        summary = _block_summary(block)
        if summary:
            return _shorten(summary)
        block = []
        size = 0
    return ""


# --------------------------------------------------------------------------------- discovery


def _validate_glob(pattern: str) -> tuple[str, ...]:
    """Split ``pattern`` into segments, rejecting absolute, drive-letter and ``..`` globs."""
    problem = f"invalid glob: {_clip(pattern)}"
    if not pattern or len(pattern) > _MAX_GLOB_LENGTH or "\x00" in pattern or "\\" in pattern:
        raise LlmsTxtError("invalid_glob", problem)
    if pattern.startswith("/") or _DRIVE_RE.match(pattern):
        raise LlmsTxtError("invalid_glob", problem)
    parts = tuple(part for part in pattern.split("/") if part != ".")
    if not parts or len(parts) > _MAX_GLOB_PARTS or any(part in ("", "..") for part in parts):
        raise LlmsTxtError("invalid_glob", problem)
    return parts


def _closure(pattern: tuple[str, ...], states: set[int]) -> set[int]:
    """Add the states reachable by letting ``**`` segments match nothing."""
    result = set(states)
    pending = list(states)
    while pending:
        index = pending.pop()
        if index < len(pattern) and pattern[index] == "**" and index + 1 not in result:
            result.add(index + 1)
            pending.append(index + 1)
    return result


def _advance(pattern: tuple[str, ...], parts: Sequence[str]) -> set[int]:
    """Return the pattern positions reachable after consuming the path ``parts``."""
    states = _closure(pattern, {0})
    for part in parts:
        moved: set[int] = set()
        for index in states:
            if index < len(pattern):
                segment = pattern[index]
                if segment == "**":
                    moved.add(index)
                elif fnmatch.fnmatchcase(part, segment):
                    moved.add(index + 1)
        states = _closure(pattern, moved)
        if not states:
            break
    return states


def _matches(globs: Sequence[tuple[str, ...]], parts: Sequence[str]) -> bool:
    return any(len(pattern) in _advance(pattern, parts) for pattern in globs)


def _prefix_possible(globs: Sequence[tuple[str, ...]], parts: Sequence[str]) -> bool:
    """Return whether a file below the directory ``parts`` could still match a glob."""
    return any(any(index < len(pattern) for index in _advance(pattern, parts)) for pattern in globs)


def _skip_reason(path: Path, name: str, depth: int) -> str | None:
    if name.startswith("."):
        return "hidden directory"
    if name == "node_modules":
        return "node_modules directory"
    if path.is_symlink():
        return "symlinked directory"
    if depth > _MAX_DEPTH:
        return "directory nested too deeply"
    return None


def _walk_files(
    base: Path,
    globs: Sequence[tuple[str, ...]],
    warnings: _Warnings,
) -> Iterator[tuple[str, ...]]:
    """Yield the relative path parts of every file matching a glob, in sorted order."""
    for current, dirnames, filenames in os.walk(base, followlinks=False):
        prefix = Path(current).relative_to(base).parts
        kept: list[str] = []
        for name in sorted(dirnames):
            parts = (*prefix, name)
            if not _prefix_possible(globs, parts):
                continue
            reason = _skip_reason(Path(current) / name, name, len(parts))
            if reason is None:
                kept.append(name)
            else:
                label = "/".join(parts)
                warnings.add(f"skipped {reason}: {label}")
        dirnames[:] = kept
        for name in sorted(filenames):
            parts = (*prefix, name)
            if _matches(globs, parts):
                yield parts


def _read_doc(
    base: Path,
    root_real: Path,
    parts: tuple[str, ...],
    max_bytes: int,
    warnings: _Warnings,
) -> str | None:
    """Read one document as UTF-8, or record a warning and return ``None``."""
    label = "/".join(parts)
    full = base.joinpath(*parts)
    try:
        target = full
        if full.is_symlink():
            target = full.resolve()
            if not target.is_relative_to(root_real):
                warnings.add(f"skipped (symlink outside root): {label}")
                return None
        if not target.is_file():
            warnings.add(f"skipped (not a regular file): {label}")
            return None
        with target.open("rb") as handle:
            data = handle.read(max_bytes + 1)
    except (OSError, RuntimeError):
        warnings.add(f"skipped (unreadable): {label}")
        return None
    if len(data) > max_bytes:
        warnings.add(f"skipped (larger than {max_bytes} bytes): {label}")
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        warnings.add(f"skipped (not valid UTF-8): {label}")
        return None


def _section_for(parts: tuple[str, ...], is_optional: bool) -> str:
    if is_optional:
        return "Optional"
    if len(parts) == 1:
        return "Docs"
    if parts[0] == "docs":
        if len(parts) == 2:
            return "Docs"
        directory = parts[1]
    else:
        directory = parts[0]
    title = directory.replace("-", " ").title().strip()
    return title or "Docs"


def discover_docs(
    root: Path,
    *,
    include: Sequence[str] = ("README.md", "docs/**/*.md"),
    optional: Sequence[str] = (),
    max_file_bytes: int = 1_048_576,
    max_files: int = 2000,
) -> Discovery:
    """Find the Markdown documents under ``root`` and describe each one.

    Args:
        root: Repository root directory.
        include: Relative globs (``**`` matches any number of directories) of files to list.
        optional: Relative globs of files to list in the trailing ``Optional`` section.
        max_file_bytes: Larger files are skipped with a warning.
        max_files: Maximum number of files matching the globs.

    Hidden directories, ``node_modules``, symlinked directories, symlinks resolving outside
    ``root``, unreadable files and non-UTF-8 files are skipped and named in ``warnings``
    (at most 100, then one line ``and N more``).

    Raises:
        LlmsTxtError: ``root_missing``, ``invalid_glob``, ``invalid_limit`` or
            ``too_many_files``.
    """
    base = Path(root)
    if not base.is_dir():
        raise LlmsTxtError("root_missing", f"root is not a directory: {_clip(str(base))}")
    if max_file_bytes < 0 or max_files < 0:
        raise LlmsTxtError("invalid_limit", "limits must not be negative")
    include_globs = [_validate_glob(pattern) for pattern in include]
    optional_globs = [_validate_glob(pattern) for pattern in optional]
    root_real = base.resolve()
    warnings = _Warnings()
    entries: list[DocEntry] = []
    matched = 0
    for parts in _walk_files(base, [*include_globs, *optional_globs], warnings):
        matched += 1
        if matched > max_files:
            raise LlmsTxtError("too_many_files", f"more than {max_files} matching files")
        text = _read_doc(base, root_real, parts, max_file_bytes, warnings)
        if text is None:
            continue
        entry = DocEntry(
            path="/".join(parts),
            title=extract_title(text) or PurePosixPath(parts[-1]).stem,
            summary=extract_summary(text),
            section=_section_for(parts, _matches(optional_globs, parts)),
        )
        entries.append(entry)
    entries.sort(key=lambda item: item.path)
    return Discovery(entries=entries, warnings=warnings.finish())


def project_title(root: Path) -> str | None:
    """Return the H1 of ``root/README.md``, or ``None`` when there is no readable README."""
    base = Path(root)
    text = _read_doc(base, base.resolve(), ("README.md",), _DEFAULT_MAX_FILE_BYTES, _Warnings())
    return None if text is None else extract_title(text)


# ------------------------------------------------------------------------------- llms.txt


def _normalize_base_url(base_url: str | None) -> str | None:
    """Validate ``base_url`` (absolute http or https) and make it end with a slash."""
    if base_url is None:
        return None
    problem = f"invalid base URL: {_clip(base_url)}"
    if len(base_url) > _MAX_BASE_URL or _BAD_URL_RE.search(base_url):
        raise LlmsTxtError("invalid_base_url", problem)
    if "?" in base_url or "#" in base_url:
        raise LlmsTxtError("invalid_base_url", problem)
    try:
        parts = urlsplit(base_url)
        _port = parts.port
    except ValueError as exc:
        raise LlmsTxtError("invalid_base_url", problem) from exc
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise LlmsTxtError("invalid_base_url", problem)
    return base_url if base_url.endswith("/") else base_url + "/"


def _escape_text(text: str) -> str:
    collapsed = " ".join(text.split())
    return collapsed.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _format_item(entry: DocEntry, base: str | None) -> str:
    text = _escape_text(entry.title) or _escape_text(entry.path)
    url = quote(entry.path, safe="/")
    if base is not None:
        url = base + url
    note = " ".join(entry.summary.split())
    item = f"- [{text}]({url})"
    return f"{item}: {note}" if note else item


def _section_key(section: str) -> tuple[int, str]:
    if section == "Docs":
        return (0, "")
    if section == "Optional":
        return (2, "")
    return (1, section)


def _group(entries: Sequence[DocEntry]) -> list[tuple[str, list[DocEntry]]]:
    grouped: dict[str, list[DocEntry]] = {}
    for entry in entries:
        section = " ".join(entry.section.split()) or "Docs"
        grouped.setdefault(section, []).append(entry)
    ordered = sorted(grouped, key=_section_key)
    return [(name, sorted(grouped[name], key=lambda item: item.path)) for name in ordered]


def build_llms_txt(
    name: str,
    summary: str,
    entries: Sequence[DocEntry],
    *,
    base_url: str | None = None,
) -> str:
    """Render an ``llms.txt`` document.

    Sections are ordered ``Docs``, then the others by name, then ``Optional``; entries are
    sorted by path. Link targets are percent-encoded and, with ``base_url``, appended to it.
    The result uses LF line endings and ends with exactly one newline.

    Raises:
        LlmsTxtError: ``no_title`` for a blank ``name``, ``invalid_base_url``,
            ``input_too_large`` or ``too_many_files``.
    """
    if len(name) > _MAX_TEXT or len(summary) > _MAX_TEXT:
        raise LlmsTxtError("input_too_large", "name or summary is too long")
    title = " ".join(name.split())
    if not title:
        raise LlmsTxtError("no_title", "a project name is required")
    if len(entries) > MAX_ENTRIES:
        raise LlmsTxtError("too_many_files", f"more than {MAX_ENTRIES} entries")
    base = _normalize_base_url(base_url)
    blocks = [f"# {title}"]
    blurb = " ".join(summary.split())
    if blurb:
        blocks.append(f"> {blurb}")
    for section, items in _group(entries):
        block = [f"## {section}", ""]
        block.extend(_format_item(item, base) for item in items)
        blocks.append("\n".join(block))
    return "\n\n".join(blocks) + "\n"


# --------------------------------------------------------------------------- llms-full.txt


def _resolve_inside(root_real: Path, path: str) -> Path:
    """Resolve the entry ``path`` below ``root_real``, refusing anything that escapes it."""
    problem = f"path escapes the root: {_clip(path)}"
    segments = path.split("/")
    if not path or path.startswith(("/", "\\")) or _DRIVE_RE.match(path) or ".." in segments:
        raise LlmsTxtError("path_outside_root", problem)
    if "\x00" in path:  # resolve() does not reject NUL everywhere (Windows, Python 3.13)
        raise LlmsTxtError("path_outside_root", problem)
    try:
        target = (root_real / path).resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise LlmsTxtError("path_outside_root", problem) from exc
    if not target.is_relative_to(root_real):
        raise LlmsTxtError("path_outside_root", problem)
    return target


def _read_capped(target: Path, cap: int) -> str:
    """Read at most ``cap`` bytes of ``target`` and decode them without splitting a character."""
    with target.open("rb") as handle:
        data = handle.read(cap + 1)
    truncated = len(data) > cap
    if truncated:
        data = data[:cap]
    decoder = codecs.getincrementaldecoder("utf-8")()
    return decoder.decode(data, final=not truncated)


def _truncate(full: str, max_bytes: int, marker: str, marker_size: int) -> str:
    budget = max(max_bytes - marker_size - 1, 0)
    body = full.encode("utf-8")[:budget].decode("utf-8", errors="ignore")
    if body and not body.endswith("\n"):
        body += "\n"
    return body + marker


def build_llms_full(
    root: Path,
    entries: Sequence[DocEntry],
    *,
    max_bytes: int = 2_000_000,
) -> str:
    """Concatenate the documents of ``entries`` into a ``llms-full.txt`` text.

    ``llms-full.txt`` is a community convention, not part of the llms.txt proposal. Each
    document starts with a ``# path`` line and a blank line; its content follows with LF line
    endings. When the total would exceed ``max_bytes`` the text is cut at a UTF-8 character
    boundary so that it plus the line ``[truncated at <max_bytes> bytes]`` and LF fit.
    The content is copied as is: it is not sanitised and may reach an LLM.

    Raises:
        LlmsTxtError: ``root_missing``, ``invalid_limit``, ``too_many_files`` or
            ``path_outside_root``.
        OSError: if a listed file cannot be read.
        UnicodeDecodeError: if a listed file is not valid UTF-8.
    """
    base = Path(root)
    if not base.is_dir():
        raise LlmsTxtError("root_missing", f"root is not a directory: {_clip(str(base))}")
    marker = f"[truncated at {max_bytes} bytes]\n"
    marker_size = len(marker.encode("utf-8"))
    if max_bytes < marker_size:
        raise LlmsTxtError("invalid_limit", f"max_bytes must be at least {marker_size}")
    if len(entries) > MAX_ENTRIES:
        raise LlmsTxtError("too_many_files", f"more than {MAX_ENTRIES} entries")
    root_real = base.resolve()
    blocks: list[str] = []
    total = 1
    for entry in entries:
        target = _resolve_inside(root_real, entry.path)
        content = _read_capped(target, max_bytes).removeprefix("\ufeff")
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        label = _LINE_BREAK_RE.sub(" ", entry.path)
        blocks.append(f"# {label}\n\n{content}".rstrip("\n"))
        total += len(blocks[-1].encode("utf-8")) + (2 if len(blocks) > 1 else 0)
        if total > max_bytes:
            break
    if not blocks:
        return ""
    full = "\n\n".join(blocks) + "\n"
    if len(full.encode("utf-8")) <= max_bytes:
        return full
    return _truncate(full, max_bytes, marker, marker_size)


# ------------------------------------------------------------------------------ validation


def validate_llms_txt(text: str, *, max_chars: int = MAX_VALIDATE_CHARS) -> list[Problem]:
    """Check ``text`` against the llms.txt format and return the problems found.

    Reports ``missing_h1`` (line 1), ``missing_summary`` (line of the H1), ``heading_order``
    (a heading before the H1 or a second H1) and ``malformed_link`` for list items under an
    H2 that do not match ``- [name](url)`` with optional ``: notes``. Fenced code is ignored.

    Raises:
        LlmsTxtError: ``input_too_large`` when ``text`` is longer than ``max_chars``.
    """
    if len(text) > max_chars:
        raise LlmsTxtError("input_too_large", f"text is longer than {max_chars} characters")
    lines = _split_lines(text)
    problems: list[Problem] = []
    h1_line: int | None = None
    early: list[int] = []
    has_summary = False
    summary_zone = False
    in_h2 = False
    for number, line in _scan(lines, cap=max_chars):
        heading = _HEADING_LEVEL_RE.match(line)
        if heading is not None:
            level = len(heading.group(1))
            in_h2 = level == 2
            if level == 1:
                if h1_line is None:
                    h1_line = number
                    summary_zone = True
                else:
                    problems.append(Problem("heading_order", number))
            else:
                summary_zone = False
                if h1_line is None:
                    early.append(number)
        elif summary_zone and _BLOCKQUOTE_RE.match(line):
            has_summary = True
        elif in_h2 and _ITEM_START_RE.match(line) and not _ITEM_RE.match(line):
            problems.append(Problem("malformed_link", number))
    if h1_line is None:
        problems.append(Problem("missing_h1", 1))
    else:
        problems.extend(Problem("heading_order", early_line) for early_line in early)
        if not has_summary:
            problems.append(Problem("missing_summary", h1_line))
    problems.sort(key=lambda problem: problem.line)
    return problems
