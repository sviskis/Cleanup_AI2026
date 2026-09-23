"""Root launcher: ``python app.py`` (the layout from the approved plan).

All real code lives in the ``pdf_ai_batch`` package; this file only forwards the
command line so that both of these work:

    python app.py --diagnose
    python -m pdf_ai_batch.app --diagnose
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pdf_ai_batch.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
