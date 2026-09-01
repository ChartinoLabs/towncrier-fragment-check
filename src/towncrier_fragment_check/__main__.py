"""Allow the checker to run as ``python -m towncrier_fragment_check``."""

from __future__ import annotations

import sys

from towncrier_fragment_check.cli import main

if __name__ == "__main__":
    sys.exit(main())
