"""Adapters package: the boundary to the outside world.

illustrator.py is the ONLY module that talks to Illustrator (COM/pywin32).
Everything else in pdf_ai_batch stays testable without Illustrator.
"""

from __future__ import annotations

from .illustrator import (
    IllustratorAdapter,
    IllustratorError,
    illustrator_process_running,
)

__all__ = ["IllustratorAdapter", "IllustratorError", "illustrator_process_running"]
