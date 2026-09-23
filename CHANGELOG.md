# Changelog

All notable changes to this project. Format: [Keep a Changelog](https://keepachangelog.com/),
versioning: [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- nothing yet

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
