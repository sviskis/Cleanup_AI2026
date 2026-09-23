"""`python -m pdf_ai_batch.gui` entry point."""

from __future__ import annotations

import sys

from . import run_gui

if __name__ == "__main__":
    sys.exit(run_gui(sys.argv[1:]))
