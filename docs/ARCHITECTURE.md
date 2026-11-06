# Architecture

## Purpose

`trysac-llms-txt-gen` is a small, dependency-free Python library and command line tool. It generates `llms.txt` and, on request, `llms-full.txt` from a repository's README and docs folder, and it can check that committed files match the generated text.

## Shape

```text
caller code / CLI (__main__.py) --> llms_txt_gen (public API in __init__.py)
                                        |
                                        +-- core.py: discovery, extraction, rendering, validation
```

- **Public API**: the names listed in `__all__` of `src/llms_txt_gen/__init__.py`. Other names are internal.
- **Errors**: the library raises `LlmsTxtError`, which carries a stable `code`. It does not print or exit.
- **Side effects**: `discover_docs` and `build_llms_full` read files under the root. The library makes no network requests and runs no external commands. Only the CLI writes files (or prints a diff in `--check` mode) and writes to stdout and stderr.
- **Logging**: the module logger has a `NullHandler` only; skipped paths are logged at debug level.

## Module outline

- `core.py`: the Markdown extraction (title, summary, fence and front matter handling), glob matching, directory walking, section grouping, rendering of `llms.txt` and `llms-full.txt`, and the format validator.
- `__main__.py`: argument parsing, the `--check` diff, and mapping of errors to exit codes.

## Quality contract

`scripts/check.py` is the single definition of the gates; CI runs the same script. See [TESTING.md](TESTING.md).

## Decisions

The architecture follows the notes in the project specification. The additions beyond it are listed in the implementation summary: three extra error codes, the optional `max_chars` argument of `validate_llms_txt`, backslash escaping in link text, and the silent pruning of unreachable directories.
