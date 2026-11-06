# trysac-llms-txt-gen

[![CI](https://github.com/Trysac/u082-llms-txt-gen/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u082-llms-txt-gen/actions/workflows/ci.yml)

Generate `llms.txt` and `llms-full.txt` from a repository's README and docs folder per the
[llms.txt proposal](https://llmstxt.org), with a check mode that fails CI when the file is stale.
Zero runtime dependencies.

## Problem

Projects want an `llms.txt` file so coding assistants can find their documentation. Writing it by
hand is tedious and the file drifts as the docs change. Existing tools either parse `llms.txt` files
or depend on a specific site generator. `llms-txt-gen` builds the file from the Markdown files of any
repository, and `--check` returns exit code 1 when the committed file differs from what would be
generated.

## Install

```bash
pip install trysac-llms-txt-gen
```

The import name is `llms_txt_gen`. The package requires Python 3.10 or newer.

## Usage

### Python

```python
from pathlib import Path
from llms_txt_gen import build_llms_txt, discover_docs

found = discover_docs(Path("."))
for warning in found.warnings:
    print("warning:", warning)
print(build_llms_txt("Demo", "A demo tool.", found.entries), end="")
```

### Command line

```bash
python -m llms_txt_gen [ROOT] [--name TEXT] [--summary TEXT] [--base-url URL] \
    [--optional GLOB] [--out llms.txt] [--full [llms-full.txt]] [--max-bytes N] [--check]
```

- `ROOT` defaults to the current directory; `--out` and `--full` paths are relative to `ROOT`.
- `--name` defaults to the H1 of `README.md`; `--summary` defaults to the first paragraph of the README.
- `--optional GLOB` may be repeated; matching files go to the trailing `Optional` section.
- `--base-url` must be an absolute `http` or `https` URL; it is prepended to every link.
- `--check` writes nothing. It prints a unified diff (`--- llms.txt`, `+++ generated`) and exits
  with 1 when a file differs from the generated text, or with 0 when it matches byte for byte.
- Warnings about skipped files go to stderr.

Exit codes: `0` success; `1` stale files (`--check`) or too many matching files; `2` usage, I/O or
parse error, including a missing title (no H1 in `README.md` and no `--name`).

## Public API

The package exports `DocEntry`, `Discovery`, `Problem`, `LlmsTxtError`, `discover_docs`,
`build_llms_txt`, `build_llms_full`, `validate_llms_txt` and `__version__`.

- `discover_docs(root, *, include=('README.md', 'docs/**/*.md'), optional=(), max_file_bytes=1_048_576, max_files=2000) -> Discovery`.
  Returns `Discovery(entries, warnings)`. Each `DocEntry` is a frozen dataclass with `path`, `title`,
  `summary` and `section`.
- `build_llms_txt(name, summary, entries, *, base_url=None) -> str`. Raises `LlmsTxtError` with code `no_title` for a blank name and `invalid_base_url` for a bad base URL.
- `build_llms_full(root, entries, *, max_bytes=2_000_000) -> str`. Raises `LlmsTxtError` with code `path_outside_root`, `invalid_limit` or `root_missing`.
- `validate_llms_txt(text, *, max_chars=2_000_000) -> list[Problem]`. `Problem` has `code` (`missing_h1`, `missing_summary`, `malformed_link`, `heading_order`) and a 1-based `line`.
- `LlmsTxtError` has a stable `code` attribute. Codes: `no_title`, `root_missing`, `invalid_base_url`, `invalid_glob`, `too_many_files`, `input_too_large`, `invalid_limit`, `path_outside_root`. Messages are at most 200 characters.

## Why not llms_txt or mkdocs-llmstxt

The `llms_txt` package parses existing `llms.txt` files, so it does not create them. `mkdocs-llmstxt`
requires MkDocs. `llms-txt-gen` generates the file from any repository that contains Markdown and has
no runtime dependencies.

## What it generates

The format follows the llms.txt proposal (2024): one H1 with the project name (the only required
part), a blockquote summary, then H2 sections of `- [name](url): notes` items.

- Title: first ATX H1 outside fenced code and YAML front matter, else the file stem.
- Summary: first paragraph, with links, emphasis and code markers removed, cut at the last space
  before 160 characters with `...` appended when cut.
- Sections: README and files directly in `docs/` go to `Docs`; `docs/<dir>/` files go to a
  section titled from `<dir>`; `--optional` files go to `Optional`, which comes last.
- Entries are sorted by path. Output uses LF line endings and ends with exactly one newline.
- Hidden directories, `node_modules`, symlinks leaving the root, oversized files and non-UTF-8
  files are skipped and named in the warnings.

## llms-full.txt

`llms-full.txt` is a community convention and is not part of the llms.txt proposal. Each document
starts with a `# path` line and a blank line, followed by its content; the total is capped by
`--max-bytes` and cut at a character boundary, ending with `[truncated at N bytes]`. Its content
is passed to LLMs unsanitised, so it must not contain secrets. See [docs/SECURITY.md](docs/SECURITY.md).

## Limits

- At most 2000 files match the globs (`max_files`); at most 32 directory levels are entered.
- Files over 1 MiB (`max_file_bytes`) are skipped with a warning; at most 100 warnings are listed.
- Globs are at most 512 characters and 32 segments, and must be relative with no `..`.
- `base_url` is at most 2048 characters and must be absolute `http` or `https`.
- `validate_llms_txt` rejects text longer than 2,000,000 characters by default.

## Security

The threat model, the defended and undefended cases and the content limits are described in
[docs/SECURITY.md](docs/SECURITY.md).

## Development

```bash
uv sync
uv run python scripts/check.py
```

## License

MIT. See `LICENSE`.
