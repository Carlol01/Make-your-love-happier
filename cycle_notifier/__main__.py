"""Entry point for ``python -m cycle_notifier``."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
