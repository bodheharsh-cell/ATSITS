"""Executable module entrypoint for python -m atsits.teaching."""

import sys
from atsits.teaching.cli import main

if __name__ == "__main__":
    sys.exit(main())
