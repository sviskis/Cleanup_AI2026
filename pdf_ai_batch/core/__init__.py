"""Core package: everything Python owns.

Modules
    jsonio           atomic JSON/text IO (shared by config, state, adapter)
    naming           output file names and job ids
    pdf_info         PDF discovery, natural sort, page count (PyMuPDF/pypdf)
    template_mapper  template discovery, natural sort, page -> template mapping
    project          the JOB folder model and its paths
    config           config.json read/validate/write
    contract         the Python <-> JSX request/result contract
    validation       preflight checks before Illustrator is touched
"""

from __future__ import annotations

__all__ = [
    "jsonio",
    "naming",
    "pdf_info",
    "template_mapper",
    "project",
    "config",
    "contract",
    "validation",
]
