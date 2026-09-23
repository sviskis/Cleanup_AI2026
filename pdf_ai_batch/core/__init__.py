"""Core package: everything Python owns.

Modules
    jsonio           atomic JSON/text IO (shared by config, state, adapter)
    naming           output file names, job ids, run ids
    pdf_info         PDF discovery, natural sort, page count (PyMuPDF/pypdf)
    template_mapper  template discovery, natural sort, page -> template mapping
    project          the JOB folder model and its paths
    config           config.json read/validate/write
    mapping_rules    bulk mapping: ranges, bulk assign, numbered auto map,
                     copy/paste, presets (the only place that decides mapping)
    contract         the Python <-> JSX request/result contract
    pagejob          page -> template/output/layer/mode plan (shared by run_one and
                     the queue) plus the DONE rule (output_ready)
    state            JOB/CONFIG/state.json: the queue model, atomic persistence,
                     transition helpers, RUNNING -> INTERRUPTED recovery
    queue            the persistent batch queue (build/run/continue/retry/skip/reset)
    validation       preflight checks before Illustrator is touched
    preflight        production preflight: the whole project in one READY / NOT READY
                     report (aggregates validation, does not duplicate it)
    report           immutable job reports after every pass (JOB/LOG/reports)
"""

from __future__ import annotations

__all__ = [
    "jsonio",
    "naming",
    "pdf_info",
    "template_mapper",
    "project",
    "config",
    "mapping_rules",
    "contract",
    "pagejob",
    "state",
    "queue",
    "validation",
    "preflight",
    "report",
]
