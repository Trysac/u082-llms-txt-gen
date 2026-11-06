# Generate llms.txt with a dependency-free, deterministic builder and a drift-check CLI

Status: accepted (generated, pending human review)

## Context

Projects want an llms.txt so coding assistants find their documentation, but a hand-written file drifts. Existing tools parse llms.txt or depend on MkDocs. The generator must work on any repository, produce byte-identical output on every run so CI can detect staleness, and treat repository content as untrusted.

## Decision

Implement discovery, extraction, rendering and validation as pure standard-library functions in one module with a thin argparse CLI. Discovery walks the tree itself and matches globs with a small segment state machine instead of pathlib.glob, so hidden directories, node_modules, symlinked directories and deep trees are pruned before being read, and a glob can never escape the root. Output ordering is fixed (Docs, other sections by name, Optional last; entries by path), links are quoted with urllib.parse.quote and joined to the base URL by plain concatenation, and --check compares bytes and prints a unified diff. llms-full.txt is documented as a community convention and is capped and cut on a UTF-8 boundary. LlmsTxtError carries a stable code; three codes were added to the specified five so that every size limit and path check raises the typed error.

## Consequences

Output is deterministic and reviewable, so a stale llms.txt fails CI with a readable diff. There are no runtime dependencies to audit. Glob support is deliberately small (fnmatch per segment plus **). Markdown extraction is heuristic, not a full CommonMark parser, so unusual documents may yield an imperfect title or summary. Directories that no glob could reach are pruned without a warning. llms-full.txt forwards document text to LLMs unchanged, which is recorded as a risk in docs/SECURITY.md.
