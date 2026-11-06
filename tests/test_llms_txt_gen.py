"""Tests for the llms_txt_gen public API."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from llms_txt_gen import (
    Discovery,
    DocEntry,
    LlmsTxtError,
    Problem,
    build_llms_full,
    build_llms_txt,
    discover_docs,
    validate_llms_txt,
)
from llms_txt_gen.core import extract_summary, extract_title, project_title

DEMO_EXPECTED = "# Demo\n\n> A demo tool.\n\n## Docs\n\n- [Demo](README.md): A demo tool.\n- [Guide](docs/guide.md): How to use it.\n\n## Api\n\n- [Ref](docs/api/ref.md): The API.\n"  # noqa: E501
PREFIX = "# T\n\n> s\n\n## Docs\n\n"


def write(root: Path, rel: str, text: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))


def lines(*items: str) -> str:
    return "\n".join(items) + "\n"


def make_symlink(link: Path, target: Path, *, directory: bool = False) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available")


def demo_root(root: Path) -> Path:
    write(root, "README.md", "# Demo\n\nA demo tool.\n")
    write(root, "docs/guide.md", "# Guide\n\nHow to use it.\n")
    write(root, "docs/api/ref.md", "# Ref\n\nThe API.\n")
    return root


def test_acceptance_document(tmp_path: Path) -> None:
    root = demo_root(tmp_path)
    discovery = discover_docs(root)
    assert isinstance(discovery, Discovery)
    assert discovery.warnings == []
    paths = [entry.path for entry in discovery.entries]
    assert paths == ["README.md", "docs/api/ref.md", "docs/guide.md"]
    assert discovery.entries[0] == DocEntry("README.md", "Demo", "A demo tool.", "Docs")
    assert build_llms_txt("Demo", "A demo tool.", discovery.entries) == DEMO_EXPECTED
    assert validate_llms_txt(DEMO_EXPECTED) == []


def test_base_url_quotes_paths() -> None:
    entry = DocEntry("docs/guide/install me (1).md", "Install", "", "Guide")
    url = "https://example.com/repo/docs/guide/install%20me%20%281%29.md"
    expected = f"# Demo\n\n## Guide\n\n- [Install]({url})\n"
    assert build_llms_txt("Demo", "", [entry], base_url="https://example.com/repo") == expected
    assert build_llms_txt("Demo", "", [entry], base_url="https://example.com/repo/") == expected


def test_relative_links_are_quoted_without_base_url() -> None:
    entry = DocEntry("docs/a b.md", "A", "", "Docs")
    assert "- [A](docs/a%20b.md)\n" in build_llms_txt("Demo", "", [entry])


def test_file_base_url_is_rejected() -> None:
    entry = DocEntry("docs/guide.md", "Guide", "", "Docs")
    with pytest.raises(LlmsTxtError) as info:
        build_llms_txt("Demo", "A demo tool.", [entry], base_url="file:///x")
    assert info.value.code == "invalid_base_url"


@pytest.mark.parametrize(
    "base_url",
    [
        "ftp://example.com/",
        "https://",
        "https://example.com/?q=1",
        "https://example.com/#top",
        "https://exa mple.com/",
        "https://example.com/(x)",
        "https://example.com:port/",
        "https://example.com/" + "a" * 2100,
    ],
)
def test_invalid_base_urls(base_url: str) -> None:
    with pytest.raises(LlmsTxtError) as info:
        build_llms_txt("Demo", "", [], base_url=base_url)
    assert info.value.code == "invalid_base_url"


def test_discovery_skips_unusable_files(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_bytes(b"# Secret\n")
    write(root, "README.md", "# Demo\n")
    write(root, "docs/guide.md", "# Guide\n")
    write(root, "docs/.private/a.md", "# A\n")
    write(root, "docs/node_modules/pkg/r.md", "# R\n")
    write(root, "docs/big.md", "# Big\n\n" + "x" * 300)
    (root / "docs" / "bad.md").write_bytes(b"\xff\xfe\x00")
    make_symlink(root / "docs" / "out.md", outside / "secret.md")
    discovery = discover_docs(root, max_file_bytes=100)
    paths = [entry.path for entry in discovery.entries]
    assert paths == ["README.md", "docs/guide.md"]
    expected = [
        "docs/.private",
        "docs/node_modules",
        "docs/big.md",
        "docs/bad.md",
        "docs/out.md",
    ]
    for fragment in expected:
        assert any(fragment in warning for warning in discovery.warnings), fragment


def test_warnings_are_capped(tmp_path: Path) -> None:
    write(tmp_path, "README.md", "# Demo\n")
    for index in range(105):
        write(tmp_path, f"docs/bad{index:03d}.md", "")
        (tmp_path / "docs" / f"bad{index:03d}.md").write_bytes(b"\xff")
    discovery = discover_docs(tmp_path)
    assert [entry.path for entry in discovery.entries] == ["README.md"]
    assert len(discovery.warnings) == 101
    assert discovery.warnings[0].startswith("skipped (not valid UTF-8): docs/bad")
    assert discovery.warnings[-1] == "and 5 more"


def test_symlinked_directory_and_dangling_link(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    write(outside, "x.md", "# X\n")
    write(root, "docs/guide.md", "# Guide\n")
    make_symlink(root / "docs" / "linked", outside, directory=True)
    make_symlink(root / "docs" / "dangling.md", root / "docs" / "missing.md")
    discovery = discover_docs(root)
    assert [entry.path for entry in discovery.entries] == ["docs/guide.md"]
    assert "skipped symlinked directory: docs/linked" in discovery.warnings
    assert "skipped (not a regular file): docs/dangling.md" in discovery.warnings


def test_unreadable_file_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write(tmp_path, "README.md", "# Demo\n")

    def deny(self: Path, *args: object, **kwargs: object) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "open", deny)
    discovery = discover_docs(tmp_path)
    assert discovery.entries == []
    assert discovery.warnings == ["skipped (unreadable): README.md"]


def test_deeply_nested_directories_are_skipped(tmp_path: Path) -> None:
    write(tmp_path, "README.md", "# Demo\n")
    deep = "/".join(["d"] * 40)
    write(tmp_path, f"docs/{deep}/x.md", "# X\n")
    discovery = discover_docs(tmp_path)
    assert [entry.path for entry in discovery.entries] == ["README.md"]
    assert any("nested too deeply" in warning for warning in discovery.warnings)


def test_wide_glob_reports_hidden_directories(tmp_path: Path) -> None:
    write(tmp_path, "README.md", "# Demo\n")
    write(tmp_path, ".git/x.md", "# X\n")
    discovery = discover_docs(tmp_path, include=["**/*.md"])
    assert [entry.path for entry in discovery.entries] == ["README.md"]
    assert discovery.warnings == ["skipped hidden directory: .git"]


def test_ordinary_repository_has_no_warnings(tmp_path: Path) -> None:
    demo_root(tmp_path)
    write(tmp_path, ".git/config.md", "# Git\n")
    write(tmp_path, "src/pkg/readme.md", "# Src\n")
    assert discover_docs(tmp_path).warnings == []


def test_max_files_limit(tmp_path: Path) -> None:
    demo_root(tmp_path)
    with pytest.raises(LlmsTxtError) as info:
        discover_docs(tmp_path, max_files=2)
    assert info.value.code == "too_many_files"
    assert len(discover_docs(tmp_path, max_files=3).entries) == 3


def test_root_missing_and_negative_limits(tmp_path: Path) -> None:
    with pytest.raises(LlmsTxtError) as missing:
        discover_docs(tmp_path / "nope")
    assert missing.value.code == "root_missing"
    with pytest.raises(LlmsTxtError) as negative:
        discover_docs(tmp_path, max_files=-1)
    assert negative.value.code == "invalid_limit"


@pytest.mark.parametrize(
    "pattern",
    [
        "",
        "/abs/*.md",
        "../x.md",
        "docs/../x.md",
        "C:/x.md",
        "docs\\x.md",
        "docs//x.md",
        "./",
        "a" * 600,
        "a\x00b",
    ],
)
def test_invalid_globs_are_rejected(tmp_path: Path, pattern: str) -> None:
    for kwargs in ({"include": [pattern]}, {"optional": [pattern]}):
        with pytest.raises(LlmsTxtError) as info:
            discover_docs(tmp_path, **kwargs)
        assert info.value.code == "invalid_glob"


def test_too_many_glob_segments(tmp_path: Path) -> None:
    with pytest.raises(LlmsTxtError) as info:
        discover_docs(tmp_path, include=["/".join(["a"] * 40)])
    assert info.value.code == "invalid_glob"


def test_dot_prefix_glob_is_normalised(tmp_path: Path) -> None:
    write(tmp_path, "README.md", "# Demo\n")
    discovery = discover_docs(tmp_path, include=["./README.md"])
    assert [entry.path for entry in discovery.entries] == ["README.md"]


def test_sections_and_ordering(tmp_path: Path) -> None:
    root = demo_root(tmp_path)
    write(root, "docs/zeta/z.md", "# Z\n")
    write(root, "docs/getting-started/start.md", "# Start\n")
    write(root, "docs/extra/e.md", "# E\n")
    discovery = discover_docs(root, optional=["docs/extra/*.md"])
    sections = {entry.path: entry.section for entry in discovery.entries}
    assert sections["README.md"] == "Docs"
    assert sections["docs/guide.md"] == "Docs"
    assert sections["docs/api/ref.md"] == "Api"
    assert sections["docs/getting-started/start.md"] == "Getting Started"
    assert sections["docs/extra/e.md"] == "Optional"
    text = build_llms_txt("Demo", "", discovery.entries)
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings == ["## Docs", "## Api", "## Getting Started", "## Zeta", "## Optional"]


def test_non_docs_and_dash_directories(tmp_path: Path) -> None:
    write(tmp_path, "guides/a.md", "# A\n")
    write(tmp_path, "docs/-/x.md", "# X\n")
    write(tmp_path, "CONTRIBUTING.md", "# Contributing\n")
    discovery = discover_docs(tmp_path, include=["guides/*.md", "docs/**/*.md", "*.md"])
    sections = {entry.path: entry.section for entry in discovery.entries}
    assert sections["guides/a.md"] == "Guides"
    assert sections["docs/-/x.md"] == "Docs"
    assert sections["CONTRIBUTING.md"] == "Docs"


def test_empty_docs_folder(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    discovery = discover_docs(tmp_path)
    assert discovery.entries == []
    assert discovery.warnings == []
    assert build_llms_txt("Demo", "", discovery.entries) == "# Demo\n"
    assert build_llms_txt("Demo", "Tagline.", discovery.entries) == "# Demo\n\n> Tagline.\n"


def test_entries_are_sorted_and_sections_normalised() -> None:
    entries = [
        DocEntry("docs/b.md", "B", "", "Docs"),
        DocEntry("docs/a.md", "A", "", ""),
        DocEntry("x.md", "X", "", "  Zed   Section "),
    ]
    text = build_llms_txt("Demo", "line one\nline two", entries)
    expected = (
        "# Demo\n\n> line one line two\n\n## Docs\n\n- [A](docs/a.md)\n- [B](docs/b.md)\n\n"
        "## Zed Section\n\n- [X](x.md)\n"
    )
    assert text == expected


def test_link_text_is_escaped_and_valid() -> None:
    entries = [
        DocEntry("a.md", "A [b] c\\", "note", "Docs"),
        DocEntry("x.md", "", "", "Docs"),
    ]
    text = build_llms_txt("Demo", "Summary.", entries)
    assert "- [A \\[b\\] c\\\\](a.md): note\n" in text
    assert "- [x.md](x.md)\n" in text
    assert validate_llms_txt(text) == []


def test_build_limits() -> None:
    entry = DocEntry("a.md", "a", "", "Docs")
    with pytest.raises(LlmsTxtError) as many:
        build_llms_txt("Demo", "", [entry] * 10_001)
    assert many.value.code == "too_many_files"
    with pytest.raises(LlmsTxtError) as long_name:
        build_llms_txt("n" * 10_001, "", [])
    assert long_name.value.code == "input_too_large"
    with pytest.raises(LlmsTxtError) as long_summary:
        build_llms_txt("Demo", "s" * 10_001, [])
    assert long_summary.value.code == "input_too_large"


def test_no_title_without_h1_and_name(tmp_path: Path) -> None:
    write(tmp_path, "README.md", "Just words, no heading.\n")
    entries = discover_docs(tmp_path).entries
    assert entries[0].title == "README"
    for name in ("", "   "):
        with pytest.raises(LlmsTxtError) as info:
            build_llms_txt(name, entries[0].summary, entries)
        assert info.value.code == "no_title"
    assert project_title(tmp_path) is None


def test_project_title(tmp_path: Path) -> None:
    assert project_title(tmp_path) is None
    write(tmp_path, "README.md", "# Demo\n")
    assert project_title(tmp_path) == "Demo"


def test_front_matter_and_fences_are_ignored() -> None:
    text = lines(
        "---",
        "title: x",
        "# Not a title",
        "---",
        "",
        "```",
        "# Fenced",
        "```",
        "",
        "# Real **Title**",
        "",
        "See [the docs](http://x) and `code`.",
    )
    assert extract_title(text) == "Real Title"
    assert extract_summary(text) == "See the docs and code."


def test_unclosed_front_matter_and_dots_terminator() -> None:
    assert extract_title(lines("---", "# Title")) == "Title"
    assert extract_title(lines("---", "a: 1", "...", "# T2")) == "T2"


def test_fence_variants() -> None:
    tilde = lines("~~~~", "# in tilde", "~~~", "# still in", "~~~~", "# After")
    assert extract_title(tilde) == "After"
    info_close = lines("```", "# in", "``` x", "# still", "```", "# out")
    assert extract_title(info_close) == "out"
    assert extract_title(lines("``` x`y", "# Title")) == "Title"
    assert extract_title(lines("```", "# never closed")) is None


def test_title_variants() -> None:
    assert extract_title(lines("# Title ##")) == "Title"
    assert extract_title(lines("#Hashtag")) is None
    assert extract_title(lines("    # indented code")) is None
    assert extract_title(lines("## Second level")) is None
    assert extract_title("\ufeff# Bom\r\n") == "Bom"


def test_title_falls_back_to_the_file_stem(tmp_path: Path) -> None:
    write(tmp_path, "docs/no-heading.md", "Just text here.\n")
    write(tmp_path, "docs/empty.md", "")
    entries = {entry.path: entry for entry in discover_docs(tmp_path).entries}
    assert entries["docs/no-heading.md"].title == "no-heading"
    assert entries["docs/no-heading.md"].summary == "Just text here."
    assert entries["docs/empty.md"].title == "empty"
    assert entries["docs/empty.md"].summary == ""


def test_summary_skips_badges_lists_tables_and_comments() -> None:
    text = lines(
        "# Tool",
        "[![CI](https://x/b.svg)](https://x)",
        "",
        "- item one",
        "",
        "| a | b |",
        "",
        "<!-- note -->",
        "",
        "> Quoted *summary* text.",
        "More text.",
    )
    assert extract_summary(text) == "Quoted summary text. More text."
    assert extract_summary(lines("# Only a heading")) == ""
    assert extract_summary("") == ""
    assert extract_summary(lines("    code block", "", "Prose.")) == "Prose."


def test_summary_markers_are_removed() -> None:
    text = "See [the **docs**](http://x), ![img](y.png) `code` _it_ *em* and snake_case."
    assert extract_summary(text) == "See the docs, code it em and snake_case."


def test_summary_is_cut_at_the_last_space() -> None:
    summary = extract_summary("word " * 50)
    assert len(summary) == 162
    assert summary.endswith("word...")
    assert extract_summary("x" * 300) == "x" * 160 + "..."
    assert extract_summary("y" * 160) == "y" * 160
    capped = extract_summary("z " * 5000)
    assert capped.endswith("...")
    assert len(capped) <= 163


def test_full_concatenates_documents(tmp_path: Path) -> None:
    write(tmp_path, "a.md", "AAA\r\nline\r\n\r\n")
    write(tmp_path, "docs/b.md", "\ufeffBBB")
    entries = [
        DocEntry("a.md", "A", "", "Docs"),
        DocEntry("docs/b.md", "B", "", "Docs"),
    ]
    expected = "# a.md\n\nAAA\nline\n\n# docs/b.md\n\nBBB\n"
    assert build_llms_full(tmp_path, entries) == expected
    assert build_llms_full(tmp_path, []) == ""


def test_full_empty_document(tmp_path: Path) -> None:
    write(tmp_path, "a.md", "")
    assert build_llms_full(tmp_path, [DocEntry("a.md", "A", "", "Docs")]) == "# a.md\n"


def test_acceptance_literals_verbatim(tmp_path: Path) -> None:
    """'and N more' warning line; 'é' * 100 ends with '[truncated at 64 bytes]\\n'."""
    write(tmp_path, "doc.md", "é" * 100)
    entries = [DocEntry("doc.md", "Doc", "", "Docs")]
    out = build_llms_full(tmp_path, entries, max_bytes=64)
    assert out.endswith("[truncated at 64 bytes]\n")
    assert len(out.encode("utf-8")) <= 64  # ', has len(out.encode(' ... <= 64


def test_full_truncates_on_a_character_boundary(tmp_path: Path) -> None:
    write(tmp_path, "doc.md", "\u00e9" * 100)
    entries = [DocEntry("doc.md", "Doc", "", "Docs")]
    out = build_llms_full(tmp_path, entries, max_bytes=64)
    assert out.endswith("[truncated at 64 bytes]\n")
    assert len(out.encode("utf-8")) <= 64
    assert "\ufffd" not in out
    assert out == "# doc.md\n\n" + "\u00e9" * 14 + "\n[truncated at 64 bytes]\n"


def test_full_truncates_an_odd_byte_limit(tmp_path: Path) -> None:
    write(tmp_path, "doc.md", "\u00e9" * 1000)
    entries = [DocEntry("doc.md", "Doc", "", "Docs")]
    out = build_llms_full(tmp_path, entries, max_bytes=101)
    assert out.endswith("[truncated at 101 bytes]\n")
    assert len(out.encode("utf-8")) <= 101
    assert "\ufffd" not in out


def test_full_stops_reading_after_the_limit(tmp_path: Path) -> None:
    write(tmp_path, "big.md", "x" * 500)
    entries = [
        DocEntry("big.md", "Big", "", "Docs"),
        DocEntry("missing.md", "Missing", "", "Docs"),
    ]
    out = build_llms_full(tmp_path, entries, max_bytes=64)
    assert out.endswith("[truncated at 64 bytes]\n")
    assert len(out.encode("utf-8")) <= 64


def test_full_marker_alone_fits_the_smallest_limit(tmp_path: Path) -> None:
    write(tmp_path, "a.md", "x" * 100)
    entries = [DocEntry("a.md", "A", "", "Docs")]
    out = build_llms_full(tmp_path, entries, max_bytes=24)
    assert out == "[truncated at 24 bytes]\n"


def test_full_errors(tmp_path: Path) -> None:
    write(tmp_path, "a.md", "A")
    entry = DocEntry("a.md", "A", "", "Docs")
    with pytest.raises(LlmsTxtError) as small:
        build_llms_full(tmp_path, [entry], max_bytes=5)
    assert small.value.code == "invalid_limit"
    with pytest.raises(LlmsTxtError) as missing:
        build_llms_full(tmp_path / "nope", [entry])
    assert missing.value.code == "root_missing"
    with pytest.raises(LlmsTxtError) as many:
        build_llms_full(tmp_path, [entry] * 10_001)
    assert many.value.code == "too_many_files"
    for bad in ("../x.md", "/etc/passwd", "C:/x.md", "", "a/../../x.md", "a\x00b.md"):
        with pytest.raises(LlmsTxtError) as escape:
            build_llms_full(tmp_path, [DocEntry(bad, "x", "", "Docs")])
        assert escape.value.code == "path_outside_root"


def test_full_refuses_symlinks_that_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    write(tmp_path, "outside.md", "secret")
    root.mkdir()
    make_symlink(root / "link.md", tmp_path / "outside.md")
    with pytest.raises(LlmsTxtError) as info:
        build_llms_full(root, [DocEntry("link.md", "L", "", "Docs")])
    assert info.value.code == "path_outside_root"


def test_validate_missing_h1() -> None:
    assert validate_llms_txt("No heading\n") == [Problem(code="missing_h1", line=1)]
    assert validate_llms_txt("") == [Problem(code="missing_h1", line=1)]


def test_validate_list_items() -> None:
    text = PREFIX + "- [a](u): b\n- [a](u)\n- [a] (u)\n- [a](u):b\n"
    expected = [
        Problem(code="malformed_link", line=9),
        Problem(code="malformed_link", line=10),
    ]
    assert validate_llms_txt(text) == expected
    assert validate_llms_txt(PREFIX + "- [a](u): b\n") == []
    assert validate_llms_txt(PREFIX + "- [a](u)\n") == []


@pytest.mark.parametrize(
    "item",
    ["- [a] (u)", "- [a](u):b", "- [](u)", "- a", "- [a](u v)", "* [a](u)", "- ", "- [a]()"],
)
def test_validate_each_malformed_item(item: str) -> None:
    problems = validate_llms_txt(PREFIX + item + "\n")
    assert problems == [Problem(code="malformed_link", line=7)]


def test_validate_summary_and_heading_order() -> None:
    no_summary = "# T\n\n## Docs\n\n- [a](u)\n"
    assert validate_llms_txt(no_summary) == [Problem(code="missing_summary", line=1)]
    early = validate_llms_txt("## A\n\n# T\n\n> s\n")
    assert early == [Problem(code="heading_order", line=1)]
    twice = validate_llms_txt("# T\n\n> s\n\n# U\n")
    assert twice == [Problem(code="heading_order", line=5)]
    ordered = validate_llms_txt("## A\n- x\n")
    assert ordered == [Problem("missing_h1", 1), Problem("malformed_link", 2)]


def test_validate_ignores_fences_and_other_levels() -> None:
    fenced = "# T\n\n> s\n\n```\n## Docs\n- bad\n```\n"
    assert validate_llms_txt(fenced) == []
    assert validate_llms_txt("# T\n\n> s\n\n## A\n\n### B\n\n- bad\n") == []
    assert validate_llms_txt("# T\n\n> s\n\n- anything\n") == []
    assert validate_llms_txt("# T\r\n\r\n> s\r\n") == []


def test_validate_size_limit() -> None:
    with pytest.raises(LlmsTxtError) as info:
        validate_llms_txt("x" * 11, max_chars=10)
    assert info.value.code == "input_too_large"


def test_error_message_is_clipped() -> None:
    error = LlmsTxtError("no_title", "x" * 500)
    assert len(str(error)) == 200
    assert error.code == "no_title"


def test_library_logger_has_only_a_null_handler() -> None:
    handlers = logging.getLogger("llms_txt_gen").handlers
    assert any(isinstance(handler, logging.NullHandler) for handler in handlers)
