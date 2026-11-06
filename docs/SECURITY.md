# Security

This document describes the threat model of `trysac-llms-txt-gen`. To report a vulnerability, see the `SECURITY.md` file at the repository root.

## Threat model

The tool reads Markdown files from a repository directory and writes `llms.txt` and, on request, `llms-full.txt`. It makes no network requests, runs no external commands and has no runtime dependencies. The repository content is treated as untrusted input.

### Defended

| Input | Protection |
|---|---|
| Globs (`include`, `optional`, `--optional`) | Must be relative, without `..`, drive letters, backslashes, NUL or empty segments; at most 512 characters and 32 segments (`invalid_glob`). Matching works on path segments and never escapes the root. |
| Directory tree | Hidden directories, `node_modules` and symlinked directories are not entered; depth is limited to 32; at most `max_files` (2000) files match (`too_many_files`). |
| Files | Larger than `max_file_bytes` (1 MiB), non-UTF-8 and unreadable files are skipped with a warning; symlinks resolving outside the root are skipped. |
| Paths in `build_llms_full` | Each entry must resolve inside the root (`path_outside_root`). |
| Markdown parsing | Fenced code and front matter are skipped by a linear scan; only the first 2000 characters of a line or paragraph are examined, which bounds the regular expressions. |
| `base_url` | Absolute `http` or `https` only, printable ASCII, no whitespace, brackets, parentheses, query or fragment, at most 2048 characters (`invalid_base_url`). |
| Link text | Square brackets and backslashes are escaped; link targets are percent-encoded. |
| Output size | `build_llms_full` output is capped by `max_bytes`; `validate_llms_txt` rejects text longer than 2,000,000 characters (`input_too_large`). |
| Error messages | Carry a stable `code` and at most 200 characters; they never include file bodies. |

### Not defended

- **Content of `llms-full.txt`**: document content is copied verbatim (only line endings are normalised to LF). It is meant to be fed to language models, so instructions aimed at an assistant reach them unchanged. The tool does not sanitise, redact or scan the content.
- **Secrets in listed files**: any file matched by the globs is read and published. The tool does not detect secrets; review the included files before publishing the generated files.
- **Files that are never listed**: directories no glob can reach are pruned silently, so the tool gives no warning about them.
- **Resource use within limits**: reads are bounded by the limits above, but the tool does not enforce a time budget.
- **Local file races**: the tool does not guard against files changing between discovery and reading.

## Out of scope

Fetching sites, MkDocs or Sphinx integration and LLM summarisation are not implemented, so none of them adds attack surface.
