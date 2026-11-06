"""Generate llms.txt and llms-full.txt from a repository's README and docs folder."""

from __future__ import annotations

import logging

from .core import (
    Discovery,
    DocEntry,
    LlmsTxtError,
    Problem,
    build_llms_full,
    build_llms_txt,
    discover_docs,
    validate_llms_txt,
)

__all__ = [
    "Discovery",
    "DocEntry",
    "LlmsTxtError",
    "Problem",
    "__version__",
    "build_llms_full",
    "build_llms_txt",
    "discover_docs",
    "validate_llms_txt",
]

__version__ = "0.1.0"

logging.getLogger(__name__).addHandler(logging.NullHandler())
