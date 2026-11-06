# Testing

## Running

```sh
uv run pytest --cov=llms_txt_gen   # tests with coverage report
uv run python scripts/check.py      # every gate, as CI and the factory run it
```

## Policy

- Branch coverage of `src/llms_txt_gen` must stay at or above 80 %; the gate fails below it.
- Tests exercise the public API (`import llms_txt_gen`) and the CLI (`main`), and check return values, raised `LlmsTxtError` codes and exit codes.
- Each bug fix starts with a failing test that reproduces it.
- Tests are deterministic: no network, no wall clock, no dependence on test order.

## What is covered

The behaviours checked by the acceptance criteria of the specification are:

- `build_llms_txt` output for a README, a `docs/` file and a `docs/<dir>/` file, including section order and sorting.
- `base_url` handling: percent-encoding of paths and rejection of non-http schemes with `invalid_base_url`.
- `main([... , '--check'])`: exit 1 with a unified diff when a file differs, exit 0 when it matches.
- `discover_docs` skipping of hidden directories, `node_modules`, oversized files, outside-root symlinks and non-UTF-8 files, and the warning cap of 100 plus `and N more`.
- `build_llms_full` truncation at a UTF-8 boundary within `max_bytes`.
- `validate_llms_txt` problems for a missing H1 and for malformed list items under an H2.
- `no_title` when there is no H1 and no `--name`, with exit code 2.

The individual test module names are not listed here; run `uv run pytest --collect-only -q` to see them.
