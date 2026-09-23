# Changelog

All notable changes to this project. Format: [Keep a Changelog](https://keepachangelog.com/),
versioning: [Semantic Versioning](https://semver.org/).

Repository: `sviskis/Cleanup_AI2026` · local folder `Cleanup_AI2026` · display name Cleanup AI 2026

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
