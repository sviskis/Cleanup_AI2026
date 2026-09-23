"""Cleanup AI 2026 - Python orchestrator.

Python owns: GUI, project folders, PDF discovery, page counting (PyMuPDF /
pypdf), template discovery and sorting, page -> template mapping, config JSON,
queue and state, progress, resume, error handling, logging, output names,
validation and orchestration.

Illustrator (jsx/worker.jsx + jsx/cleanup.jsx) owns: opening the PDF page,
Illustrator DOM work, the appearance safe cleanup, template/ARTWORK handling,
saving the AI and reporting statistics.

The contract between the two halves is JSON in runtime/; see
pdf_ai_batch/core/contract.py and docs/ARCHITECTURE.md.
"""

__version__ = "0.4.0"
__all__ = ["__version__"]
