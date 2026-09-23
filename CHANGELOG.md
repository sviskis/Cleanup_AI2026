# Changelog

All notable changes to this project. Format: [Keep a Changelog](https://keepachangelog.com/),
versioning: [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- nothing yet

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
