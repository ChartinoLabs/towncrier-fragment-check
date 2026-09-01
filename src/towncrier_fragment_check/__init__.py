"""Fail a branch that adds no towncrier changelog fragment.

This package provides the :mod:`towncrier_fragment_check.cli` entry point used
by the ``towncrier-fragment-check`` console script and by the pre-commit hook
of the same name.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

DISTRIBUTION_NAME = "towncrier-fragment-check"
UNKNOWN_VERSION = "0.0.0"

try:
    __version__ = version(DISTRIBUTION_NAME)
except PackageNotFoundError:  # pragma: no cover - only hit when not installed
    __version__ = UNKNOWN_VERSION

__all__ = ["DISTRIBUTION_NAME", "__version__"]
