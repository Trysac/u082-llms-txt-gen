# Project record

## Objective

Provide a small, dependency-free tool that generates `llms.txt` and `llms-full.txt` from a repository's README and docs folder following the llms.txt proposal, and a check mode that fails CI when the committed files are stale.

## Scope

- In scope: the public API documented in [README.md](../README.md) (discovery, rendering, full-text concatenation, format validation, and the `llms-txt-gen` command line), typed and tested.
- Out of scope: fetching websites, MkDocs or Sphinx integration, LLM summarisation, and any runtime dependency or I/O beyond reading the repository files, unless an accepted ADR changes this.

## Timeline

| Date | Event |
|---|---|
| 2026 | Repository created from the factory utility template. |

## Effort metrics

The factory records the figures below; values are filled in from measurements only.

| Metric | Value |
|---|---|
| Tokens (input / output) | 321664 / 134554 |
| Hours (human) | pending measurement |
| Cost (USD) | 0.8251 |

## Factory run u082 (measured from API usage)

| Phase | Model | Batch | Input | Output | Cache write | Cache read | Cost (USD) |
|---|---|---|---|---|---|---|---|
| generation | claude-sonnet-5-5 | yes | 2497 | 123507 | 0 | 4246 | 0.6205 |
| fix-1 | claude-sonnet-5-5 | no | 6 | 497 | 6089 | 39847 | 0.0242 |
| fix-2 | claude-sonnet-5-5 | no | 8 | 817 | 8720 | 60140 | 0.0360 |
| fix-3 | claude-sonnet-5-5 | no | 8 | 1355 | 7318 | 56522 | 0.0375 |
| fix-4 | claude-sonnet-5-5 | no | 4 | 310 | 5703 | 24582 | 0.0198 |
| docs | claude-haiku-5-5 | no | 133804 | 8068 | 0 | 0 | 0.0871 |

Total: $0.8251. Prices: Anthropic list prices.
