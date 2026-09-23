# Changelog

All notable changes to this project. Format: [Keep a Changelog](https://keepachangelog.com/),
versioning: [Semantic Versioning](https://semver.org/).

Repository: `sviskis/Cleanup_AI2026` · local folder `Cleanup_AI2026` · display name Cleanup AI 2026

## [0.9.0] - 2026-09-23

Milestone 8: **plan snapshots, undo and restore**. The plan of a JOB is production
data, so every meaningful change now leaves an atomic snapshot of the plan it replaced
in `JOB/CONFIG/history/`, and `[UNDO PLAN CHANGE]` / `[RESTORE SNAPSHOT]` can put an
older plan back. A restore keeps the plan it replaces first, so it is reversible too.
`jsx/*`, `cleanup.jsx` and the Python <-> JSX contract are untouched.

### Added

- `pdf_ai_batch/core/history.py` - the plan history of a JOB:
  * `JOB/CONFIG/history/<YYYY-MM-DD_HHMMSS>.json`, one file per snapshot:
    `version`, `created`, `kind`, `reason`, `job`, `app_version`, `meta`
    (documents, pages, pinned, config version) and `config` (the exact plan). No queue
    state, no attempts, no run ids, no errors - plan data only (unit tested)
  * `snapshot()` writes atomically through `jsonio.write_json_atomic`; a failed write
    raises `HistoryError` and leaves nothing behind
  * `list_snapshots()` (newest first, an unreadable file is listed but never applied),
    `load_snapshot()` (validates version + plan, so a corrupt copy can never be
    restored), `count_snapshots()`, `latest_snapshot()`, `info_of()`/`summary()`
  * `undo_target()` - the newest snapshot whose plan differs from the current one
  * `restore_snapshot()` - snapshots the CURRENT plan first ("recovery copy"), then
    writes the restored plan atomically: a restore is itself reversible
  * `undo_last()` - one step back, `None` when there is nothing to undo
  * `prune()` retention (`DEFAULT_RETENTION` 100 per JOB); a snapshot marked
    `pinned: true` is never deleted (the hook for manually named snapshots)
- `gui/mapping_tab.py` - `[UNDO PLAN CHANGE]` and `[RESTORE SNAPSHOT]` (with
  `gui/bulk_dialogs.SnapshotDialog`: timestamp, reason, document and page count per
  snapshot, plus the note that the current plan is kept first)
- `gui/controller.py` - `snapshots()`, `snapshot_count()`, `undo_plan_change()`,
  `restore_snapshot()`; `_before_mutation(reason, kind)` now writes the snapshot, so
  the single funnel is the only place a plan change can happen (and the only place
  history comes from). Kinds: `bulk-assign`, `preset`, `auto-map`, `reconcile`,
  `undo`, `restore`, `plan`
- Tests: `tests/test_history.py` (17) and `tests/test_gui_history.py` (13)
- Tools: `temp/run_gui_acceptance_m8.py` (real GUI, evidence
  `temp/gui_acceptance_m8.txt`, screenshots `temp/gui_m8_*.png`)

### Milestone 9 - Windows packaging (same release)

- `tools/cleanup_ai.spec` + `tools/build_release.ps1` - **one command** builds the
  production distribution `dist/Cleanup AI 2026/` (`Cleanup AI 2026.exe` + `program/` +
  `jsx/` + `config/` + `logs/` + docs): it runs the three gates, cleans `build/` and
  `dist/`, runs PyInstaller, copies the assets (next to the exe and into `program/`),
  verifies the result and runs the packaged `--diagnose` as a smoke test. PyInstaller is
  the choice, with the reasoning documented in the spec, the requirements file and
  `docs/PACKAGING.md`; Illustrator is never bundled.
- `tools/create_shortcut.ps1` - documented, **opt-in** desktop shortcut (nothing writes
  to a desktop by itself).
- `requirements-packaging.txt` - PyInstaller plus why not cx_Freeze / Nuitka.
- `pdf_ai_batch/paths.py` - one path resolver for both layouts: everything comes from
  the executable (frozen) or the repository (source), never from the current working
  directory; `PDF_AI_BATCH_HOME` overrides the install folder, and the writable
  `runtime/` + `logs/` folders fall back to `%LOCALAPPDATA%/Cleanup AI 2026/` when the
  install folder is read only (nothing is ever written into Program Files).
- `pdf_ai_batch/diagnostics.py` - production diagnostics for `--diagnose`: version,
  frozen/source, Python + architecture, PyInstaller bundle, pywin32, the JSX assets with
  their paths, `default_config.json`, the writable folders, Illustrator **installed**
  (registry ProgID + Adobe folders, no launch) and reachable only with
  `--with-illustrator`, plus the working directory. Exit code 1 on a missing resource.
- `app.py` - `--diagnose --with-illustrator`, and a packaged startup check that shows a
  human readable message box instead of a traceback when an asset is missing.
- `logging_setup.py` - a windowed build has no stdout: the diagnostics attach to the
  parent console when there is one, otherwise the text goes to
  `<install>/logs/console.log`; the packaged GUI writes one startup record (version,
  exe, install folder, diagnostics result) into `<install>/logs/app.log`.
- The executable carries the version resource (ProductVersion 0.9.0 from `VERSION`,
  the single source of truth, shown in the GUI, `--diagnose`, the logs and every
  report).
- Tests: `tests/test_packaging.py` (22)
- Tools: `temp/run_packaged_acceptance_m9.py` (evidence
  `temp/packaged_acceptance_m9.txt`, screenshot `temp/gui_m9_window.png`)

### Changed (milestone 9)

- `paths.describe()` reports `app_root` + `layout` instead of `repo_root`;
  `config_dir()` and `default_config_file()` moved to `<install>/config`;
  `pdf_ai_batch/core/preflight.py` still resolves the JSX assets through `paths`.
- `.gitignore` - `build/`, `dist/` and `*.spec.tmp`.

### Changed

- `gui/controller.py` - a mutation is only saved (and only snapshotted) when the plan
  really differs from what `config.json` holds: a no-op edit now leaves no history
  entry and does not touch the queue, while an explicit plan action still materialises
  the plan for a JOB that has no `config.json` yet. `_plan_is_on_disk()` does that
  comparison; the enable switch is recorded as a plain plan edit, not a bulk rule.
- `core/__init__.py` - `history` documented and exported.
- `VERSION` / `pdf_ai_batch/__init__.py` - 0.9.0.

### Fixed

- A snapshot of a no-op edit used to be written, which made `[UNDO PLAN CHANGE]` a
  no-op too (the newest snapshot equalled the current plan). Now only real changes are
  recorded, so an undo always has a step to take.
- `history.list_snapshots()` orders by modification time (a second snapshot within the
  same second gets a `-2` suffix and is newer), not by file name.



Milestone 7: **production preflight + immutable job reports**. Before a long project
one action now answers "can this run at all?" (`[PREFLIGHT PROJECT]`, `READY` /
`NOT READY`), and every pass writes a structured report into `JOB/LOG/reports/`
(JSON is canonical, TXT is human readable, nothing is ever overwritten). `jsx/*`,
`cleanup.jsx` and the Python <-> JSX contract are untouched.

### Added

- `pdf_ai_batch/core/preflight.py` - one production readiness report for a whole JOB,
  aggregated instead of duplicated:
  * sections `PROJECT`, `PDF`, `TEMPLATES`, `OUTPUT`, `QUEUE`, `ILLUSTRATOR`, `SYSTEM`
    with `OK` / `WARNING` / `ERROR` per check, and an overall `READY` / `NOT READY`
  * `PROJECT`: JOB root + all six folders, `config.json` valid, `state.json` loadable,
    CONFIG writable
  * `PDF`: every configured document (present, page count readable, `CONFIG STALE`,
    `MISSING PDF`, `PLAN ERROR`), PDFs in the folder, and how many documents are
    really runnable
  * `TEMPLATES`: files in `JOB/TEMPLATE`, every template **named in config.json**
    (a missing one silently fell back to the default before), the default template
    when pages need it, the per-page effective templates
  * `OUTPUT`: AI_OUT writable, valid output names, duplicates per document **and**
    across documents (config level, so an invalid config is never hidden by the auto
    plan), outputs outside AI_OUT, existing outputs that would be `SKIP`
  * `QUEUE`: state.json valid, unique `job_id`s, items outside the plan, stale
    `RUNNING`, runnable count, the six state counts
  * `ILLUSTRATOR`: `worker.jsx` / `cleanup.jsx` / `runtime/` (real package paths,
    never "not specified") plus COM availability and version - contacted **only** for
    this explicit action (`check_illustrator=True`)
  * `SYSTEM`: free disk space (`FREE_SPACE_WARNING_MB` 500 / `FREE_SPACE_ERROR_MB`
    100 thresholds), LOG writable, the report folder creatable
  * `run_preflight()` is read-only: it plans the project to look at what a run would
    do but never writes `config.json`, `state.json` or an output (unit tested)
  * `PreflightReport` offers `status`, `can_run`, `problems`, `warnings`,
    `summary_rows()` (the GUI/console layout), `to_text()` and `to_dict()`
- `pdf_ai_batch/core/report.py` - immutable job reports:
  * `JobReport` (job, root, label, started/finished/duration, counts of all six
    states, documents, errors, interrupted, objects processed, retries, Illustrator
    version, abort reason, session) with `to_text()` and `to_dict()`
  * `build_report()` assembles it from `state.json` (or the given items) plus the pass
    `BatchSummary` - cumulative counts AND what this pass did; no side effects
  * `write_report()` writes `JOB/LOG/reports/report_<YYYYmmdd-HHMMSS>.json` and `.txt`
    atomically; an existing name is never overwritten (a second report in the same
    second gets `-2`), `list_reports()` returns them newest first, `read_report()` reads
    one back
  * a report **cannot break a finished pass**: a failed write is logged as a warning
- `core/queue.py` - `finish_pass()` runs at the end of every pass (RUN ALL, RUN
  CURRENT PDF, RUN SELECTED, CONTINUE, RETRY, and a pass that could not start), writes
  the report, logs the paths and exposes `last_report` / `last_report_paths`;
  retry passes are labelled (`RETRY ERRORS` / `RETRY INTERRUPTED`), and the pass label
  now reaches the report
- GUI `[PREFLIGHT PROJECT]` on the RUN tab: runs in a worker thread, renders the
  summary block and the full report in the progress panel + log, and a **real ERROR**
  blocks the next run (a warning never does). `AppController.preflight_project()`,
  `preflight_report()`, `preflight_text()`, `preflight_blocks_run()`, `reports()` and
  `last_report_paths()`; the RUN tab logs where each report went
- CLI `python -m pdf_ai_batch.batch --preflight-project [--no-illustrator]` (exit code
  1 and `PREFLIGHT: NOT READY` when it is not ready), and the batch CLI prints the
  report paths of the finished pass
- Tests: `tests/test_preflight.py` (25) and `tests/test_report.py` (16)
- Tools: `temp/run_gui_acceptance_m7.py` (real GUI + Illustrator, evidence
  `temp/gui_acceptance_m7.txt`, screenshots `temp/gui_m7_*.png`)

### Changed

- `core/validation.py` - `CheckResult.severity` (`OK` / `WARNING` / `ERROR`) and the
  severity constants, so preflight and the per-page checks speak one language.
- `core/__init__.py` - `preflight` and `report` documented and exported.
- `VERSION` / `pdf_ai_batch/__init__.py` - 0.8.0.

### Fixed

- `preflight` counts a document with `CONFIG STALE` or `PLAN ERROR` as **not runnable**
  (the queue excludes it), so a single-document JOB with a drifted page count is
  `NOT READY` instead of `READY`.
- `preflight` reports a template that `config.json` names but the folder does not have
  (a real `ERROR`: the page would silently use the default template).
- `preflight` reports output duplicates from `config.json` itself; an invalid config
  makes the plan fall back to the automatic plan, which would otherwise hide them.



Milestone 6: **bulk page mapping + reusable mapping presets**. A 100-300 page plan is
no longer a page by page job: ranges, numbered auto mapping, a mapping clipboard that
works across documents, presets and a destructive-apply preview. Every mapping rule
lives in one new core module and every plan change goes through one mutation funnel
(the hook milestone 8 will snapshot in). `jsx/*`, `cleanup.jsx` and the Python <-> JSX
contract are untouched.

### Added

- `pdf_ai_batch/core/mapping_rules.py` - **the only place that decides mapping**:
  * Range parser `parse_pages`: `1`, `1-5`, `1,3,5`, `1-5,8,10-14`, `*` (all pages).
    Rejects `0`, negatives, decimals, `1-`, `1--5`, unknown characters, pages beyond
    the document and (unless `normalize_reversed` is set) `5-3`; the result is always
    ascending and unique. `format_pages` compresses a page list back to `1-5,8`.
  * Bulk assignment: `assign_template` (template + optional layer),
    `use_default_template`, `clear_override` (template and layer back to the document
    defaults), `set_layer`, `set_enabled` - all strictly validated against the plan.
  * `auto_map_by_number` - deterministic page N -> the template numbered N
    (`001_cover.ai` -> page 1). MASTER templates never enter the numbered pool, an
    ambiguous number (two templates with the same number) is reported as a problem and
    those pages are **not** touched, an unnumbered template is listed, a number beyond
    the page count is informational. No fuzzy/AI matching anywhere.
  * `copy_mapping` / `paste_mapping` - a mapping clipboard with **plan data only**
    (`template`, `layer`, `enabled` on request, the document level `clear_layer` on
    request). Queue state, attempts, run ids, errors and outputs never travel through
    it. Pasting works within one PDF and across PDFs (`offset` or explicit target
    pages), never writes beyond the destination page count (`skipped_pages`,
    `unused_pages`, `truncated` are reported) and raises instead of guessing when
    nothing fits.
  * Presets: `preset_from_mapping` (the current mapping compressed into ranges),
    `preset_path` / `save_preset` / `load_preset` / `list_presets`, `validate_preset`,
    `preset_preview` (targets, changes, conflicts: pages beyond the document and
    missing template files) and `apply_preset` (overlay, or `replace_all=True` for the
    destructive variant). Schema version 1, `JOB/CONFIG/presets/<name>.json`.
    `validate_preset` **rejects runtime keys** (`state`, `status`, `attempts`,
    `run_id`, `error_type`, `error_message`, `output`, `job_id`, `stats`, ...), so a
    preset can only ever contain mapping intent.
- `pdf_ai_batch/gui/bulk_dialogs.py` - `RangeAssignDialog` (pages + template + layer +
  enable, validating through the core parser and showing its message inline),
  `SavePresetDialog` and `PresetDialog` (preset list, core preview with the conflicts
  before anything is replaced, "also replace the other pages" switch). Presentation
  only: no mapping rule, no config access.
- Tools: `temp/run_gui_acceptance_m6.py` (36 page JOB, real GUI + Illustrator;
  evidence `temp/gui_acceptance_m6.txt`, screenshots `temp/gui_m6_*.png`).
- `gui/mapping_tab.py` - the MAPPING action bar is now three rows:
  `ASSIGN TO SELECTED`, `ASSIGN TO RANGE`, `USE DEFAULT`, `CLEAR OVERRIDE`,
  `AUTO MAP BY NUMBER`, `REFRESH`, `COPY MAPPING`, `PASTE MAPPING`, `SAVE PRESET`,
  `LOAD / APPLY PRESET`, `AUTO ASSIGN TEMPLATES`, `RECONCILE PDF` (next to the existing
  SELECT / ENABLE / DISABLE / RESET / VALIDATE). Dialog seams
  (`range_dialog_factory`, `save_preset_dialog_factory`, `preset_dialog_factory`) let
  the real handlers be tested without a user; `_handle` returns the core report (used
  for the ambiguity problems of the numbered mapping).
- `gui/controller.py` - `parse_pages`, `format_pages`, `assign_template_to_range`,
  `clear_pages`, `auto_map_by_template_number`, `copy_mapping` / `mapping_clipboard` /
  `paste_mapping`, `presets_dir` / `presets` / `preset_info` / `save_preset` /
  `preset_preview` / `apply_preset`, plus the **single mutation funnel**
  `_mutate_config` -> `_before_mutation` -> validate -> atomic save -> queue rebuild.
  `_mapping_mutation` translates `MappingError` / `PresetError` into `ControllerError`,
  so the GUI keeps one error type.
- Tests: `tests/test_mapping_rules.py` (48: range syntax, bulk assignment, numbered
  mapping incl. natural sort / MASTER exclusion / ambiguity, copy/paste incl. cross-PDF
  and truncation, preset schema, apply/preview, UTF-8 names) and
  `tests/test_gui_bulk_mapping.py` (17: the whole MAPPING action set through the
  controller, cross-document paste, preset conflicts, the mutation funnel counter and a
  guard that the GUI owns no mapping rule of its own).

### Changed

- `gui/controller.py` - `set_enabled`, `assign_template`, `use_default_template`,
  `auto_assign_templates`, `set_document_enabled` and `reconcile_document` now all go
  through the same funnel; `cfg.save_config` is called from exactly one place in the
  GUI layer. `_set_pages` (the old direct edit helper) is gone.
- `core/config.py` - removed an accidentally duplicated `new_project_config` definition
  (the second one shadowed the first; identical behaviour).
- `core/__init__.py` - `mapping_rules` documented and exported.
- `mapping_tab.py` - `DEFAULT_CHOICE` now comes from `bulk_dialogs` (one definition).
- `VERSION` / `pdf_ai_batch/__init__.py` - 0.7.0.

### Fixed

- A range action can never apply to a half-visible selection: every bulk handler
  mirrors the thumbnail selection into the Treeview (the single source of truth) first.
- `paste_mapping` reports the pages it could not write in the error message instead of
  only the document range.

### Known environment quirk (not a product bug)

- On CPython 3.14 a `tkinter` variable collected by a **worker thread** can run
  `Variable.__del__` outside the main loop (`RuntimeError: main thread is not in main
  loop`), and a Tcl call from that thread may then invalidate Tk widgets. It is
  reproducible on the accepted milestone 5 baseline too (the same pytest file selection
  crashes at `dac46e8`) and it made the first milestone 6 acceptance runs die
  mid-flight. The acceptance driver now keeps its dialog objects alive until the window
  closes (`keep()`), which removes the trigger; the product code never creates Tk
  objects on a worker thread.




Milestone 5: **PDF preview + thumbnail page browser**. The MAPPING tab now shows the
pages of the active PDF as thumbnails with one larger preview, the page size, the
template/layer/output/state of the selected page and the page actions. Rendering is
PyMuPDF on a background worker; Illustrator is never contacted for a preview.
`jsx/*` and the Python <-> JSX contract are untouched.

### Added

- `pdf_ai_batch/preview/` - the only place that renders PDFs:
  * `renderer.py` - `render_thumbnail` (160 px wide default), `render_preview`
    (1000 px longest side default), `page_geometry` (points/mm/rotation/page count),
    `document_fingerprint`, `png_size`. Aspect ratio always preserved, scale clamped
    to `0.05 .. 4.0`, every failure raised as `PreviewError` (corrupt page, corrupt
    file, missing file, out of range page). PyMuPDF is imported only through
    `core/pdf_info.load_pymupdf`.
  * `cache.py` - disposable disk cache in `JOB/.cache/preview` (`PreviewCache`).
    The FILE NAME is the identity: `sha1(pdf path + mtime + size)` for the document
    plus `sha1(page + kind + requested size|zoom)` for the request, so a modified
    PDF or a different render size can never hit a stale image. `invalidate_pdf`
    (keep/remove), `clear`, `prune` (LRU, `max_bytes` / `max_files`), `stats`.
    The folder is gitignored and safe to delete by hand.
- `gui/preview_loader.py` - background rendering: one worker thread, a priority
  queue (focused page first), request de-duplication, an `EventBus` sink
  (`tasks.EVENT_PREVIEW`), and a **generation token** per document so pending
  renders are dropped and results of a previous PDF are never delivered. Tk-free.
- `gui/preview_panel.py` - the MAPPING preview pane: thumbnail grid (click =
  select, Ctrl = toggle, Shift = range, wheel scroll, lazy loading of the visible
  tiles), large preview with `FIT` / `100%` / `+` / `-`, page info (PDF, page
  n / total, size in mm, template, layer, output, state, attempts), the error detail
  line and `ASSIGN TEMPLATE TO SELECTED` / `USE DEFAULT TEMPLATE` / `ENABLE` /
  `DISABLE` / `RESET` / `OPEN OUTPUT`. Contains no PDF logic at all.
- `mapping_tab.py` - the preview pane above the table, two-way synchronisation
  (tile click -> Treeview selection -> detail line; Treeview row -> tile highlight
  + preview), `OPEN OUTPUT` for DONE pages (refused when the state is not DONE or
  the file is gone), `_apply_preview_selection` so every action uses the Treeview
  selection as the single source of truth.
- `gui/__init__.py` - `LIVE_STATE_REFRESH_SECONDS` (0.5 s) and
  `MainWindow._maybe_refresh_live_states`: while a batch runs the mapping rows and
  tiles are re-read, so the tile of the page being processed really shows `RUNNING`.
- `gui/context.py` - `preview_loader` and the `open_file` seam (`os.startfile` on
  Windows, injectable for tests).
- `gui/controller.py` - `preview_cache()` (per JOB) and `preview_target()`.
- Tests: `tests/test_preview_renderer.py` (15), `tests/test_preview_cache.py` (15),
  `tests/test_preview_loader.py` (13, including the 160 page progressive/stale
  generation case) and `tests/test_gui_preview.py` (15, Tk, including the
  thumbnail <-> mapping synchronisation, ERROR detail, PREVIEW ERROR isolation and
  the 120 page "opening renders almost nothing" case).
- Tools: `temp/preview_perf.py` (performance report -> `temp/preview_perf_m5.txt`)
  and `temp/run_gui_acceptance_m5.py` (the milestone 5 acceptance on a real JOB).

### Changed

- `main_window.py` - the window owns the `PreviewLoader` (created with the JOB's
  cache), drains `EVENT_PREVIEW` in `_pump`, refreshes the cache root when the JOB
  changes and stops the render worker on close.
- `tasks.py` - `EVENT_PREVIEW`.
- `.gitignore` - `**/.cache/`.
- Docs: `ARCHITECTURE.md` §3c (preview pipeline, cache identity, generations),
  JOB layout (`.cache/preview`), `docs/GUI.md` (preview pane, synchronisation,
  live states, OPEN OUTPUT), `docs/TESTING.md` (preview tests + performance run).

### Fixed

- A window resize used to blank the thumbnail browser (`_draw_tiles` rebuilt the
  canvas while `_requested` still reported the page as queued); already rendered
  tiles are now repainted from the decoded image cache.
- `_ensure_visible` passed a tile-relative fraction to `yview_moveto`, which scrolled
  the browser to the very bottom when a page was selected; it now uses the real
  content height and leaves an unmapped canvas alone.
- The large preview was re-requested on every refresh (each progress event) and the
  zoom label showed the renderer's fit scale instead of the operator's choice; both
  are now keyed on (page, size, zoom).

### Notes

- `pytest`: 273 tests (58 new in this milestone). `tools/check_jsx.ps1` and
  `tools/run_tests.ps1` stay green (no JSX and no contract change in this milestone).
- Performance (160 synthetic pages, `temp/preview_perf_m5.txt`): opening the
  document + queueing 160 thumbnails = 1.3 ms, first thumbnail after 0.03 s, all
  160 render in 2.2 s, 161 cache files = 0.2 MB, a full cached pass = 0.04 s, and a
  document switch mid-render drops 131 pending requests with zero foreign pages
  delivered.
- Real acceptance (`temp/gui_acceptance_m5.txt`): all 20 steps passed, including
  `WAITING -> RUNNING -> DONE` on the thumbnails, an ERROR page showing
  `OUTPUT_PREP_FAILED: ... WinError 32 ...` with attempts, the retry to DONE,
  reopening the GUI (tile text == state.json, cached thumbnails) and
  `Illustrator Documents.Count == 0`.

## [0.5.0] - 2026-09-23

Milestone 4: **multi PDF project queue**. One JOB now holds several PDFs, each with
its own page plan, templates, outputs and persistent states, and the GUI grew the
project level actions to drive them. `jsx/cleanup.jsx`, `jsx/worker.jsx` and the
Python <-> JSX contract are untouched (config `version: 2` is a Python side format).

### Added

- `core/config.py` - **config version 2**: `{version, defaults, documents[]}`, one
  block per PDF (`pdf`, `page_count`, `enabled`, `pages[]`, `removed_pages[]`).
  `load_config` migrates a version 1 file **in memory**, so existing JOBs keep
  working byte for byte; the file is rewritten as v2 on the next plan save.
  New helpers: `new_project_config`, `new_document`, `document_entries`,
  `enabled_document_entries`, `document_for`, `page_entries(config, pdf)`,
  `all_page_entries`, `document_page_count`, `replace_document`,
  `reconcile_document` (kept / restored / added / archived pages).
- `core/naming.py` - `pdf_id_for` (stable, file name derived, never `hash()`),
  `pdf_key_for` (case folded comparison key for duplicate document detection) and
  `job_id_parts`; `job_id_for` is `<pdf_id>_p<page:03d>`, unique across documents.
- `core/pagejob.py` - `DocumentPlan` / `ProjectPlan`, `plan_document` (status
  `OK` / `NEW` / `CONFIG STALE` / `MISSING PDF` / `PLAN ERROR`, drift detected
  without rewriting anything), `plan_project` (config order first, then the PDFs
  found in `JOB/PDF`), `reconcile_plan` / `apply_reconcile` (explicit only) and
  `document_plan_inputs` (one place that resolves a document's plan source).
- `core/queue.py` - the queue is built for the whole project by default
  (`build_queue(pdf=...)` narrows it to one document), `run_documents()` (RUN
  CURRENT PDF), `duplicate_outputs()` + a collision guard that aborts a pass before
  the first Illustrator call, per document counts/summaries, `document_progress()`
  and a deterministic order (document order, then page ascending). `find()` is
  document aware: a bare page number in a multi PDF JOB is reported as ambiguous.
- `core/state.py` - `pdf_id` on every item (derived from the PDF path for old
  files), `counts_of`, `document_summaries`, `StateDocument.items_of`,
  `document_ids`, `candidates`.
- `batch.py` - project scope by default, `--pdf NAME` narrows a build, a run or an
  ID lookup, new `--reconcile` (with `--pdf`), PDF column in `--status`.
- GUI: the PDF tab is now the JOB's **document list** (`USE / PDF / PAGES /
  CONFIG STATUS / QUEUE STATUS`, with IZMANTOT, IESLĒGT/IZSLĒGT, RECONCILE,
  PIEVIENOT PDF, ATJAUNOT), the MAPPING tab shows which PDF it edits
  (`PDF: manualis.pdf | Lapas: 42`) and has its own RECONCILE PDF button, and the
  RUN tab has RUN CURRENT PDF / RUN ALL ENABLED PDFs / CONTINUE PROJECT /
  RETRY PROJECT ERRORS plus a per document progress list and a project summary
  (`PDFs: 2 | Lapas kopā: 7`, `appendix.pdf - lapa 004 / 004`).
- Tests: `tests/test_multi_pdf.py` (16), `tests/test_gui_multi_pdf.py` (12) and a
  PDF tab active document regression test in `tests/test_gui_smoke.py` (7):
  two PDFs with the same page numbers, unique job ids, deterministic order, one
  PDF error not stopping another, output collision detection (config + runtime),
  v1 -> v2 migration, reopening a v1 JOB, state files without `pdf_id`, page count
  drift, missing PDFs, RECONCILE (added / removed / restored / DONE preserved),
  multi PDF continue and retry, project summary and current PDF filtering.

### Changed

- A document that is disabled, missing or unplannable has its queue items
  **disabled** (never reset, never deleted); a document that was not planned in a
  pass keeps its state untouched. State is only ever dropped by an explicit reset.
- `--status`, `--dry-run` and the batch summary are project aware: PDFs, pages
  total and one line per document.
- The active document of the GUI is the one MAPPING edits; plan edits carry the
  other documents over untouched (`replace_document`), so editing one PDF can never
  drop another PDF's plan.
- Project level runs (`RUN ALL ENABLED PDFs`, `CONTINUE PROJECT`,
  `RETRY PROJECT ERRORS`) no longer require a readable active PDF: the queue skips
  exactly the broken document and runs the rest.

### Fixed

- A document whose PDF was deleted showed up nowhere while its queue state still
  existed; it is now listed as `MISSING PDF` with its queue status and stays
  recoverable when the file comes back.
- The MAPPING table could pick up a page number from another PDF through a bare
  `find("14")`; lookups are now document scoped and ambiguous ids raise a clear
  error.
- `validate_config` no longer rejects a version 1 file (it migrates it) and now
  also reports duplicate documents and one output name used by two documents.
- The PDF tab reverted a document switch made through the controller: its own tree
  selection was treated as authoritative, so a programmatic switch (a reconcile, a
  closed JOB, the acceptance driver) snapped back to the previously selected PDF.
  The tab now renders the controller's active document (found by the milestone 4
  screenshot evidence, regression test `test_gui_smoke.py`).

## [0.4.0] - 2026-09-23

Milestone 3: the **Tkinter GUI** (`python app.py`) as a thin presentation layer over
the proven core. `jsx/cleanup.jsx`, `jsx/worker.jsx` and the Python <-> JSX contract
are untouched; no cleanup logic, no queue logic and no validation logic was copied
into the GUI.

### Added

- `pdf_ai_batch/gui/controller.py` - `AppController`, `MappingRow`, `PdfEntry`,
  `ProgressSnapshot`: every GUI action as a plain method (project, PDF, mapping,
  run, progress), no Tk and no COM, so the whole GUI logic is unit testable.
- `pdf_ai_batch/gui/tasks.py` - `EventBus`, `QueueLogHandler`, `TaskRunner`: the
  worker thread bridge. Long work runs off the Tk main thread, events come back
  through `queue.Queue` and `root.after(...)`; one task at a time.
- `pdf_ai_batch/gui/context.py` - `GuiContext`, the only thing a tab may ask the
  window for (status bar, log view, refresh, run a task, busy state).
- `pdf_ai_batch/gui/main_window.py` - the window "Cleanup AI 2026": four tabs, the
  120 ms event pump, per JOB file logging, close safety.
- `pdf_ai_batch/gui/project_tab.py` - NEW PROJECT / OPEN PROJECT / ADD PDF /
  ADD TEMPLATES / OPEN JOB FOLDER + the six JOB folders with their state.
- `pdf_ai_batch/gui/pdf_tab.py` - PDF list of `JOB/PDF` with file name, absolute
  path, page count (`core/pdf_info.py`), method, size and config status.
- `pdf_ai_batch/gui/mapping_tab.py` - the `USE / PAGE / TEMPLATE / LAYER / OUTPUT /
  STATUS` Treeview, SELECT ALL/NONE, ENABLE/DISABLE SELECTED, RESET SELECTED,
  VALIDATE, AUTO ASSIGN TEMPLATES, ASSIGN TEMPLATE, USE DEFAULT TEMPLATE, REFRESH,
  double click = change that row's template, and a validation panel.
- `pdf_ai_batch/gui/run_tab.py` - RUN SELECTED / RUN ALL ENABLED / CONTINUE /
  RETRY ERRORS / RETRY INTERRUPTED / REFRESH STATUS / HEALTH CHECK, an
  "overwrite" checkbox, the progress panel (`Page 014 / 014` + bar + counts, all
  derived from the queue state) and the live log view.
- `pdf_ai_batch/gui/__main__.py` - `python -m pdf_ai_batch.gui`.
- `pdf_ai_batch/core/queue.py` - `BatchQueue.run_items()` (run exactly a selection;
  only WAITING/INTERRUPTED rows, DONE/SKIPPED/ERROR need an explicit reset/retry)
  and `BatchQueue.reload()` (re-read `state.json` without recovery).
- `docs/GUI.md` - GUI architecture, threading model, tab reference, validation,
  overwrite, close safety and the acceptance evidence.
- Tests: `tests/test_gui_controller.py` (17), `tests/test_gui_tasks.py` (6),
  `tests/test_gui_smoke.py` (6) and 4 new queue/adapter tests. All GUI tests run
  without a display (the window test skips itself when Tk cannot open).

### Changed

- `app.py` - the default action (no arguments) is now the GUI; `--gui` is explicit,
  `--batch` / `--run-one` / `--diagnose` / `--health` are unchanged.
- `adapters/illustrator.py` - COM is apartment aware: `_prepare_thread()` calls
  `CoInitialize` once per thread, a cached application object is dropped when it
  belongs to another thread or is stale, and `invoke_worker()` validates the
  connection instead of trusting it. Needed because the GUI runs every batch in a
  fresh worker thread (the CLI ran in the main thread).
- `core/queue.py` - `recover_running()` also removes a partial output AI that the
  interrupted attempt was still writing, so `CONTINUE`/`RETRY INTERRUPTED` really
  re-process the page instead of reporting `SKIP`.
- Validation in the GUI is a composition of existing core checks only:
  `validation.preflight`, `validation.check_file` per distinct template and
  `config.validate_config`. Illustrator is checked only after an explicit
  HEALTH CHECK, so opening the GUI never launches it.
- `VERSION` / `pdf_ai_batch/__init__.py` - 0.4.0.

### Fixed

- MAPPING: a table refresh (RESET/ENABLE/DISABLE/VALIDATE, or the progress pump)
  dropped the operator's row selection, so "RESET SELECTED" followed by
  "RUN SELECTED" reported "no pages selected".
- MAPPING: the detail line kept a stale message (e.g. "no JOB open") after the JOB
  was opened.
- `invoke_worker`/`ensure_app`/`health_check` trusted a cached COM object: after
  Illustrator was closed, restarted or when a new worker thread used it, every call
  failed with "Object is not connected to server".
- Window close cancels the pending `after(...)` pump (no "invalid command name
  ..._pump" noise from a destroyed window).

## [0.3.0] - 2026-09-23

Milestone 2: a **persistent batch queue with state recovery** on top of the proven
one page pipeline. No GUI, no change to the cleanup algorithm, no change to the
Python <-> JSX contract.

### Added

- `pdf_ai_batch/core/state.py` - `JOB/CONFIG/state.json`: the queue model
  (`WAITING`, `RUNNING`, `DONE`, `ERROR`, `SKIPPED`, `INTERRUPTED`), atomic writes
  through `jsonio.write_json_atomic`, transition helpers with timestamps and attempt
  counting, tolerant loading (a corrupt file never raises), `RUNNING -> INTERRUPTED`
  startup recovery and per state summaries.
- `pdf_ai_batch/core/queue.py` - `BatchQueue` with `build_queue()`, `run_next()`,
  `run_all_enabled()`, `continue_queue()`, `retry_errors()`, `retry_interrupted()`,
  `skip_item()`, `reset_item()`, `set_enabled()`, `status_table()` and `summary()`.
  The queue is adapter agnostic (duck typed `run_job`) and contains no COM code.
- `pdf_ai_batch/core/pagejob.py` - the one implementation of
  "page -> template / output / layer / mode" used by **both** `run_one` and the
  queue (config.json wins over the automatic positional plan), plus the DONE rule
  (`output_ready`: the output must exist and be non-empty) and
  `prepare_output_copy` (`copied` / `skipped` / `failed`).
- `pdf_ai_batch/batch.py` - the batch CLI: `--build`, `--status`, `--run-next`,
  `--run-all`, `--continue`, `--retry-errors`, `--retry-interrupted`, `--skip ID`,
  `--reset ID`, plus `--pages`, `--pdf`, `--overwrite`, `--dry-run`, `--json`,
  `--max-items`. Exit code 0 = nothing failed, 1 = at least one ERROR/INTERRUPTED
  left, 2 = usage/setup problem. `app.py --batch ...` forwards to it.
- `pdf_ai_batch/tests/test_state.py` (18 tests) and
  `pdf_ai_batch/tests/test_queue.py` (29 tests) with
  `pdf_ai_batch/tests/fakes.py`, a fake Illustrator adapter (no COM).
- `docs/QUEUE_STATE.md` - state machine, `state.json` schema and example, queue API,
  CLI, failure policy, recovery/continue, test coverage and the real run evidence.

### Changed

- `run_one` now builds its request through `core/pagejob.py`, so one page and a
  batch page use exactly the same plan; a valid `config.json` for the PDF also
  applies to `run_one`. `new_run_id()` moved to `core/naming.py`.
- `run_one` applies the same DONE rule as the queue: a worker `OK` with a missing
  or empty output is reported as `MILESTONE FAILED`, not as success.
- `app.py` argument forwarding fixed: `app.py --run-one --job ...`
  (and the new `--batch`) used `argparse.REMAINDER`, which rejected option-like
  arguments; it now uses `parse_known_args`.
- `pdf_ai_batch/core/__init__.py` documents and exports the new modules.

### Fixed

- A **missing per-page template aborts only that page**, not the whole plan: the
  intended template path is kept in the plan (with a warning) so the page fails as
  `ERROR`/`OUTPUT_PREP_FAILED` and can be retried, while every other page still runs.
- A **failed attempt deletes its partial output** (the template copy or a partial
  AI), so `--retry-errors` really re-runs the page instead of skipping it because a
  leftover file exists.
- A missing template or an unwritable output is `ERROR`, never `SKIPPED`
  (`prepare_output_copy` distinguishes `skipped` from `failed`).
- The per-pass statistics counted a `SKIPPED` outcome as an error (the queue state
  name differs from the worker status); a state -> status mapping fixes it.

### Verified

- `pytest`: 143 tests green (18 state, 29 queue, 2 fake-adapter helper modules'
  coverage included in the queue suite).
- Real Illustrator batch (`temp/QUEUE_JOB`, 14 page PDF, page 3 with its own
  template through `config.json`), driven by `temp/run_queue_batch_test.py`:
  `--build` -> 4 x WAITING; `--run-all` -> `001 DONE`, `002 SKIPPED`, `003 DONE`,
  `004 DONE`; a second `--run-all` runs nothing; a lost per-page template ->
  `003 ERROR` while **11 further pages finished in the same pass**
  (`DONE=11 ERROR=1 SKIPPED=1`, 43 objects); `--retry-errors` -> `003 DONE`; the
  process killed while page 4 was `RUNNING` -> `004 INTERRUPTED` after `--status`
  -> `--continue` -> `004 DONE`. Final queue: `DONE=13 SKIPPED=1`. Illustrator had
  0 documents open afterwards, `state.json` was written after every page and the
  MASTER template was never modified.
- CLI outputs of every step: `temp/queue_test_logs/*.txt`.

## [Unreleased]

### Added

- `pdf_ai_batch/tests/test_request_paths.py` - the request must carry absolute
  paths: a relative `--job` path, spaces, Latvian characters, a OneDrive style
  location, all three fields absolute, and independence from the current working
  directory.
- `pdf_ai_batch/tests/test_encoding.py` - `jsx/` sources are pure ASCII (no BOM,
  LF), no cp1252 mojibake anywhere in the text sources, request JSON, result JSON
  and the worker log are UTF-8 in both directions, and the worker keeps its strict
  path validation.
- `tools/check_jsx.ps1` check 5: every file in `jsx/` must be ASCII only, without a
  BOM and with LF line endings - Illustrator decodes a large BOM-less `.jsx` as
  ANSI, so a raw Latvian literal inside `jsx/` would be corrupted.
- `run_one` now prints and logs the final absolute request paths
  (`--- galīgie pieprasījuma ceļi (absolūti) ---`) before Illustrator is invoked,
  so every run is auditable.

### Fixed

- **End to end contract bug: relative paths in `runtime/current_job.json`.**
  `run_one` wrote `temp\REAL_TEST\PDF\mans_fails.pdf` (relative to the shell's
  working directory). `jsx/worker.jsx` runs inside Illustrator, which has its own
  current directory, so `File(request.pdf).exists` was false for `pdf`, `template`
  and `output` and every job ended as `INVALID_REQUEST`. Verified with two real
  runs: `temp\REAL_TEST` (14 page PDF, page 3) and a Latvian job folder with a
  Latvian PDF name - both `Statuss : OK`, output AI written, `MILESTONE OK`.
- **UTF-8 mojibake in the JSX chain.** ExtendScript decoded the raw Latvian
  literals of `jsx/worker.jsx` as ANSI, so the worker message in
  `runtime/current_result.json` was unreadable. `jsx/worker.jsx` and the
  regenerated `jsx/cleanup.jsx` are now pure ASCII (`\uXXXX` escapes), which no
  decoder can corrupt, and `tools/check_jsx.ps1` fails on a non-ASCII byte in
  `jsx/`.
- **`tools/migrate_extract_sections.ps1` had lost its UTF-8 BOM**, so PowerShell
  5.1 read its Latvian here-strings as ANSI and wrote mojibake into the generated
  files (`jsx/cleanup.jsx`, `src/ui/BatchWindow.jsx`). The BOM is restored, the
  tool escapes its `jsx/` output to ASCII, and both files were regenerated
  byte-identically apart from the repaired text.

### Changed

- **The request JSON carries absolute paths with forward slashes.** Python
  resolves `pdf`, `template` and `output` with `Path.resolve()`
  (`core.contract.contract_path`), `JobProject.open` resolves the JOB root, and
  `core.contract.validate_request` rejects a request that still contains a
  relative path. The worker never resolves or joins paths: it only checks that the
  path is absolute and that the file exists (strict, including
  `output exists when template_mode == "copy"`).
- **Project renamed** to `Cleanup_AI2026` / display name **Cleanup AI 2026**
  (repository `sviskis/Cleanup_AI2026`, local folder `Cleanup_AI2026`).
  All project-name and path references in tracked files were updated in one
  commit; git history, branches, tests, the frozen baseline
  (`legacy/current_working_v10.jsx`, SHA256 unchanged) and the read-only archive
  (`archive/original/`) are untouched. Runtime code derives every path from its own
  location, so no runtime path needed a change. The legacy GUI title
  `PDF Deep Cleanup → AI Template Batch` (a workflow label) and the engine name
  `PDF Deep Cleanup v6` were deliberately kept.

### Fixed

- `app.py --health` reported "Illustrator nav atvērts" with exit code 1 while
  Illustrator was in fact running: `GetActiveObject` can fail even then (the
  Running Object Table entry is not always visible, for example when the instance
  was started elevated), while `Dispatch` connects fine. `--health` now uses the
  same `attach -> launch` strategy as a real run - the same path `run_one` uses -
  and prints `connected_via` (`attach (GetActiveObject)` / `launch (Dispatch)`),
  so the check answers the question that matters: can a job run right now?

## [0.2.0] - 2026-09-23

Migration to a **Python orchestrator + Illustrator JSX worker**, without
rewriting the working cleanup algorithm.

### Added

- `jsx/cleanup.jsx` - the canonical Illustrator engine: the cleanup v6 body
  (appearance safe) plus all document helpers (open PDF page, safe close, MASTER
  template copy, `.ait` -> `.ai` conversion, ARTWORK layer, artwork duplication)
  and `statsToContract`. Extracted from the reference script by line range.
- `jsx/json2.js` - ES3 JSON polyfill (`JSON.stringify` / `JSON.parse`) with a
  positioned error message; installs itself only when Illustrator lacks JSON.
- `jsx/worker.jsx` - one page per invocation: reads `runtime/current_job.json`,
  validates it, opens the PDF page, cleans up, prepares the output AI, transfers
  the artwork, saves, closes both documents, writes the result JSON, and always
  produces a result even for a broken request.
- `pdf_ai_batch/` Python package:
  - `core/project.py` (JOB folders and paths), `core/pdf_info.py` (discovery,
    natural sort, **PyMuPDF page count with a pypdf fallback**),
    `core/template_mapper.py` (natural sort, positional mapping, master
    exclusion, default fallback), `core/naming.py` (`manual__017.ai` naming, job
    ids, collisions), `core/config.py` (`config.json` validation + atomic save),
    `core/contract.py` (request/result schemas, stats mapping, summaries),
    `core/validation.py` (preflight), `core/jsonio.py` (atomic IO and
    `wait_for_json`).
  - `adapters/illustrator.py` - the only COM code: attach to a running
    Illustrator, launch when needed, file based handoff (no business data through
    COM), result accepted only on matching `job_id` + `run_id`, timeout with the
    worker log tail, scoped `close_documents`.
  - `run_one.py` - the one page milestone command; `app.py` - CLI entry with
    `--diagnose`, `--health`, `--run-one`.
  - `logging_setup.py` - `LOG/app.log` + `LOG/batch_<timestamp>.log`, UTF-8
    console (Windows code page switched to 65001).
- `tools/freeze_legacy.ps1`, `tools/make_demo_job.py`, `tests/fixtures/*.json`,
  `tests/jscript/test_json_contract.js`, the Python test suite (80 tests) and the
  adapter handshake tests that run without Illustrator.
- Documentation: `ARCHITECTURE.md` (rewritten for the hybrid system),
  `MIGRATION_PLAN.md`, `docs/PYTHON_ENV.md`, updated `README.md`, `STATUS.md`,
  `TODO.md`, `docs/TESTING.md`, `tools/README.md`.

### Changed

- **Single source of truth for the cleanup engine**: `src/core/PdfCleanup.jsx`
  was deleted and `src/Main.jsx` now includes `../jsx/cleanup.jsx`. The legacy
  ScriptUI application registers it into the `PDC` namespace; the worker uses the
  plain `PDFCleanup` global.
- `PDFCleanup.run(doc, options)` takes its switches as arguments
  (`releaseSafeVectorMasks`, `deleteCropMarks`, `ungroupPasses`) with the
  reference defaults, so the engine no longer depends on `PDC.CONFIG`.
- The document helpers moved with it: `src/services/FileService.jsx` no longer
  defines `safeClose`, `src/core/PdfPageCount.jsx` no longer defines
  `openPdfPage`, `src/core/TemplateManager.jsx` keeps only template discovery, and
  `src/core/OutputManager.jsx` keeps only naming.
- `tools/check_jsx.ps1` now validates **both** entry points (`src/Main.jsx` and
  `jsx/worker.jsx`), scans `src/` and `jsx/`, and treats `JSON.*` as available
  when `jsx/json2.js` is part of the bundle.
- `tools/run_tests.ps1` builds the bundle from `jsx/cleanup.jsx` and also runs the
  JSON contract test.
- Page counting for the new pipeline is PyMuPDF first, pypdf second - the
  Illustrator probe stays only in the legacy application.
- Output naming for the new pipeline is `manual__017.ai` (width
  `max(3, digits(page_count))`); the legacy `manual_p03.ai` scheme lives on only
  inside the frozen baseline.
- Version raised to 0.2.0 (VERSION, `src/config/Config.jsx`,
  `config/default_config.json`, `src/Main.jsx`).

### Fixed

- The Windows console no longer raises `UnicodeEncodeError` on Latvian text; the
  code page is set to UTF-8.
- Directory comparison for `close_documents` normalises path separators, so a COM
  path with backslashes and a Python path with forward slashes compare correctly.
- `default_template()` returns the **real** file from the folder listing, so the
  configured default keeps the case the file has on disk.
- Natural sorting now has documented, deterministic tie-breaks: digit runs sort
  before letter runs, numbers compare numerically first, and equal numbers fall
  back to the raw text (`02` before `2`).
- `pywin32` is imported only inside the adapter, so every other Python module
  stays usable (and testable) without COM.

## [0.1.0] - 2026-09-23

First version of the structured project. The reference script
`PDF_Deep_Cleanup_AI_Template_BATCH.jsx` (1283 lines, one file) was split into
modules without changing its logic.

### Added

- `src/Main.jsx` as the single entry point with the `#include` module list,
  session start, `VERSION` consistency check and a top level error guard.
- `PDC` namespace (`src/utils/Namespace.jsx`) with `registerModule` and a
  duplicate-name guard.
- Configuration system `src/config/Config.jsx` (identity, safety switches, folder
  layout, logging, cleanup switches) plus the JSON mirror
  `config/default_config.json`.
- Project relative path helpers `src/utils/Paths.jsx` (`getProjectRoot`,
  `getLogsFolder`, `getErrorsFolder`, `jobFolders`, ...).
- `src/utils/TextUtils.jsx` with the reference naming/formatting helpers and new
  log/report timestamps.
- `src/services/FileService.jsx`: PDF scanning, folder helpers, file signature,
  safe close, write test, text read/write/append.
- `src/services/LogService.jsx`: levelled logging (`logDebug/Info/Warning/Error`),
  session log `logs/project.log`, job batch log `LOG/batch_<timestamp>.txt`.
- `src/services/ErrorService.jsx`: central error handling, `logs/errors/<ts>/`
  reports (`error.txt`, `context.txt`) and a single error dialog.
- `src/core/PdfCleanup.jsx`: the appearance safe cleanup engine of the reference
  script, module scoped, driven by `CONFIG.cleanup`, with `summaryLine()` stats.
- `src/core/PdfPageCount.jsx`: Illustrator probe and raw PDF `/Pages /Count` scan,
  plus `openPdfPage`.
- `src/core/TemplateManager.jsx`: template ranking/detection, `ARTWORK` layer,
  artwork duplication.
- `src/core/OutputManager.jsx`: output naming (`<pdf>_pNN.ai`), page job keys,
  template copy with overwrite and dry run rules.
- `src/core/BatchRunner.jsx`: controller with the scan, page job list and batch
  loop moved out of the GUI.
- `src/core/Diagnostics.jsx`: preflight checks and the "Diagnostika" report window.
- `src/ui/BatchWindow.jsx`: ScriptUI view only (widgets, event wiring, view
  interface), including the new "Diagnostika" button.
- `CONFIG.dryRun`: plan and log every action without writing or deleting anything.
- Development tooling (no Illustrator needed):
  `tools/check_jsx.ps1`, `tools/run_tests.ps1`, `tools/jscript_parse.js`,
  `tools/migrate_extract_sections.ps1`, `tools/normalize_eol.ps1`,
  `tests/jscript/stubs.js`, `tests/jscript/run_tests.js` (79 unit tests).
- Documentation: `README.md`, `docs/CODE_ANALYSIS.md`, `docs/ARCHITECTURE.md`,
  `docs/WORKFLOW.md`, `docs/TESTING.md`, `tests/TEST_PLAN.md`, `STATUS.md`,
  `TODO.md`, `CHANGELOG.md`, `VERSION`, `examples/JOB_STRUCTURE.md`,
  `tools/README.md`, `logs/README.md`, `archive/original/ARCHIVE_MANIFEST.md`,
  `.gitignore`, `.gitattributes`, `.clinerules`.
- Read only archive of the three reference scripts in `archive/original/` with
  SHA256 hashes recorded.

### Changed

- The GUI no longer contains business logic: buttons call `PDC.BatchRunner`, which
  calls `core/*` and `services/*`; the window is only updated through the `view`
  interface.
- The batch summary now also reports the plan count in dry run mode.
- The JOB batch log is written by `LogService` and is also flushed when a run is
  aborted at the view level.
- Folder exclusion during the PDF scan and the scan depth now come from `CONFIG`.
- Log file name uses `CONFIG.log.jobFilePrefix` (still `batch_<timestamp>.txt`).

### Fixed

- `userInteractionLevel` is now restored in a `try/catch/finally`, so a hard
  failure can no longer leave Illustrator in "no alerts" mode or leave the window
  locked while a batch is running.
- Errors now carry context: `err.message`, `err.fileName`, `err.line`, the input
  file, the output file, the template, the PDF page, the JOB folder and a config
  snapshot land in `logs/errors/<timestamp>/`.
- A failing page level operation is written to both the GUI log and the session
  log instead of an empty `catch {}` only.
- `writeJobLog` can no longer abort a batch when the log folder is not writable.
- Every project file is written as UTF-8 without BOM and LF only
  (`tools/normalize_eol.ps1`), matching the reference script's format.

### Removed

- Nothing. All source files, including the loose legacy copies in the project
  root, remain on disk. The two duplicated legacy copies are git-ignored because
  byte identical versions are committed under `archive/original/`.
