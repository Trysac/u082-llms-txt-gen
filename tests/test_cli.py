"""Tests for the llms-txt-gen command line interface."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest

import llms_txt_gen.__main__ as cli
from llms_txt_gen import LlmsTxtError

EXPECTED = (
    "# Demo\n\n> A demo tool.\n\n## Docs\n\n"
    "- [Demo](README.md): A demo tool.\n"
    "- [Guide](docs/guide.md): How to use it.\n\n"
    "## Api\n\n- [Ref](docs/api/ref.md): The API.\n"
)


def write(root: Path, rel: str, text: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))


def demo_root(root: Path) -> Path:
    write(root, "README.md", "# Demo\n\nA demo tool.\n")
    write(root, "docs/guide.md", "# Guide\n\nHow to use it.\n")
    write(root, "docs/api/ref.md", "# Ref\n\nThe API.\n")
    return root


def test_generate_then_check_matches(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = demo_root(tmp_path)
    assert cli.main([str(root)]) == 0
    assert (root / "llms.txt").read_bytes() == EXPECTED.encode("utf-8")
    assert "wrote llms.txt" in capsys.readouterr().out
    assert cli.main([str(root), "--check"]) == 0
    assert capsys.readouterr().out == ""


def test_check_prints_a_unified_diff_when_stale(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = demo_root(tmp_path)
    (root / "llms.txt").write_bytes(b"old\n")
    assert cli.main([str(root), "--check"]) == 1
    out = capsys.readouterr().out.splitlines()
    assert out[:2] == ["--- llms.txt", "+++ generated"]
    assert "-old" in out
    assert "+# Demo" in out


def test_check_reports_a_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = demo_root(tmp_path)
    assert cli.main([str(root), "--check"]) == 1
    assert "+++ generated" in capsys.readouterr().out


def test_check_diff_handles_a_missing_final_newline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = demo_root(tmp_path)
    (root / "llms.txt").write_bytes(b"# Demo")
    assert cli.main([str(root), "--check"]) == 1
    assert "-# Demo\n+# Demo\n" in capsys.readouterr().out


def test_no_title_exits_with_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(tmp_path, "README.md", "Just words, no heading.\n")
    assert cli.main([str(tmp_path)]) == 2
    assert "no_title" in capsys.readouterr().err
    assert not (tmp_path / "llms.txt").exists()
    assert cli.main([str(tmp_path), "--name", "Demo"]) == 0
    text = (tmp_path / "llms.txt").read_text(encoding="utf-8")
    assert text.startswith("# Demo\n\n> Just words, no heading.\n")


def test_missing_readme_without_name_exits_with_2(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    assert cli.main([str(tmp_path)]) == 2


def test_summary_option_overrides_the_readme(tmp_path: Path) -> None:
    root = demo_root(tmp_path)
    assert cli.main([str(root), "--summary", "Custom summary."]) == 0
    text = (root / "llms.txt").read_text(encoding="utf-8")
    assert text.startswith("# Demo\n\n> Custom summary.\n")


def test_warnings_go_to_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = demo_root(tmp_path)
    (root / "docs" / "bad.md").write_bytes(b"\xff")
    assert cli.main([str(root)]) == 0
    captured = capsys.readouterr()
    assert "warning: skipped (not valid UTF-8): docs/bad.md" in captured.err
    assert "warning" not in captured.out


def test_full_file_is_written_and_checked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = demo_root(tmp_path)
    assert cli.main([str(root), "--full", "--check"]) == 1
    capsys.readouterr()
    assert cli.main([str(root), "--full"]) == 0
    capsys.readouterr()
    full = (root / "llms-full.txt").read_text(encoding="utf-8")
    assert full.startswith("# README.md\n\n# Demo\n")
    assert "# docs/api/ref.md\n\n# Ref" in full
    assert cli.main([str(root), "--full", "--check"]) == 0
    assert capsys.readouterr().out.count("wrote") == 0


def test_full_with_custom_path_and_cap(tmp_path: Path) -> None:
    root = demo_root(tmp_path)
    assert cli.main([str(root), "--full", "all.txt", "--max-bytes", "64"]) == 0
    text = (root / "all.txt").read_text(encoding="utf-8")
    assert text.endswith("[truncated at 64 bytes]\n")
    assert len(text.encode("utf-8")) <= 64


def test_invalid_max_bytes_exits_with_2(tmp_path: Path) -> None:
    root = demo_root(tmp_path)
    assert cli.main([str(root), "--full", "--max-bytes", "5"]) == 2


def test_optional_and_base_url(tmp_path: Path) -> None:
    root = demo_root(tmp_path)
    write(root, "docs/extra/e.md", "# E\n")
    args = [str(root), "--optional", "docs/extra/*.md", "--base-url", "https://example.com/r"]
    assert cli.main(args) == 0
    text = (root / "llms.txt").read_text(encoding="utf-8")
    assert text.endswith("## Optional\n\n- [E](https://example.com/r/docs/extra/e.md)\n")


def test_custom_output_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = demo_root(tmp_path)
    assert cli.main([str(root), "--out", "out/llms.txt"]) == 2
    assert "error:" in capsys.readouterr().err
    (root / "out").mkdir()
    assert cli.main([str(root), "--out", "out/llms.txt"]) == 0
    assert (root / "out" / "llms.txt").read_text(encoding="utf-8") == EXPECTED


def test_default_root_is_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    demo_root(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert cli.main([]) == 0
    assert (tmp_path / "llms.txt").read_text(encoding="utf-8") == EXPECTED


def test_usage_and_domain_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = demo_root(tmp_path)
    assert cli.main(["--bogus"]) == 2
    assert cli.main([str(tmp_path / "nope")]) == 2
    assert cli.main([str(root), "--base-url", "file:///x"]) == 2
    assert cli.main([str(root), "--optional", "../x"]) == 2
    assert "invalid_glob" in capsys.readouterr().err


def test_help_and_version_exit_with_0(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--help"]) == 0
    assert "usage: llms-txt-gen" in capsys.readouterr().out
    assert cli.main(["--version"]) == 0
    assert "llms-txt-gen 0.1.0" in capsys.readouterr().out


def test_too_many_files_exits_with_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*args: object, **kwargs: object) -> object:
        raise LlmsTxtError("too_many_files", "too many")

    monkeypatch.setattr(cli, "discover_docs", boom)
    assert cli.main([str(tmp_path)]) == 1
    assert "too_many_files" in capsys.readouterr().err


def test_undecodable_document_exits_with_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = demo_root(tmp_path)

    def boom(*args: object, **kwargs: object) -> object:
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch.setattr(cli, "build_llms_full", boom)
    assert cli.main([str(root), "--full"]) == 2
    assert "UnicodeDecodeError" in capsys.readouterr().err


def test_module_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["llms-txt-gen", "--version"])
    monkeypatch.delitem(sys.modules, "llms_txt_gen.__main__", raising=False)
    with pytest.raises(SystemExit) as info:
        runpy.run_module("llms_txt_gen", run_name="__main__")
    assert info.value.code == 0
