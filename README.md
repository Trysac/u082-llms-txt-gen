# llms-txt-gen

[![PyPI version](https://img.shields.io/pypi/v/trysac-llms-txt-gen)](https://pypi.org/project/trysac-llms-txt-gen/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-llms-txt-gen)](LICENSE)
[![CI](https://github.com/Trysac/u082-llms-txt-gen/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u082-llms-txt-gen/actions/workflows/ci.yml)

Generate llms.txt and llms-full.txt from a repository README and docs folder per the llms.txt proposal, with a check mode for CI drift

## Problem

Describe in two or three sentences the concrete problem this utility solves, who hits it, and what
they do today without it. Replace this paragraph when the first real feature lands.

## Install

```sh
pip install trysac-llms-txt-gen
# or
uv add trysac-llms-txt-gen
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
import llms_txt_gen

# normalize() trims surrounding whitespace and lower-cases the text.
print(llms_txt_gen.normalize("  Hello World "))  # -> "hello world"

# Blank input is rejected explicitly instead of returning an empty string.
try:
    llms_txt_gen.normalize("   ")
except ValueError as exc:
    print(f"rejected: {exc}")
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
