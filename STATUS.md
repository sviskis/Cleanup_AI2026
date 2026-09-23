# Current Status

Version: 0.1.0
Status: **restructured and verified statically; awaiting the first real Illustrator run of the new modules**

## Working

* Project structure, entry point `src/Main.jsx` with the `#include` module list.
* `PDC` namespace with 12 registered modules: `TextUtils`, `Paths`,
  `FileService`, `LogService`, `ErrorService`, `PdfCleanup`, `PdfPageCount`,
  `TemplateManager`, `OutputManager`, `BatchRunner`, `Diagnostics`,
  `BatchWindow` (15 files in `src/`: those 12 plus `Main.jsx`, `Namespace.jsx`,
  `Config.jsx`).
* All logic of the reference script `PDF_Deep_Cleanup_AI_Template_BATCH.jsx` was
  extracted by line range, not retyped: helpers, page counting, the cleanup
  engine, template detection, artwork duplication, output naming, batch loop.
* GUI rebuilt with the same widgets, labels and behaviour plus a "Diagnostika"
  button; the window contains no business logic any more.
* Config system (`src/config/Config.jsx`) with `dryRun`, `overwriteExisting`,
  `debug`, log level, folder layout and cleanup switches.
* Project relative paths from `$.fileName`; no hard coded user paths (the
  reference had none either).
* Logging: `logs/project.log` (append, levelled) + `JOB\LOG\batch_<ts>.txt`.
* Error handling: central `ErrorService`, per page reports in
  `logs/errors/<timestamp>/{error.txt,context.txt}`, run level guard that restores
  `userInteractionLevel` and unlocks the window.
* Diagnostics: Illustrator version, project folders, write access, config values,
  module loading, JOB folder, PDF queue, template.
* Tools: `check_jsx.ps1` (include graph, real ES3 compile through WSH JScript,
  ES3 scan, module API wiring) and `run_tests.ps1` (79 unit tests, stubbed host).
* Docs: `README.md`, `docs/CODE_ANALYSIS.md`, `docs/ARCHITECTURE.md`,
  `docs/WORKFLOW.md`, `docs/TESTING.md`, `tests/TEST_PLAN.md`,
  `archive/original/ARCHIVE_MANIFEST.md`, `examples/JOB_STRUCTURE.md`.

## Verified

| Check | Result |
| --- | --- |
| `tools/check_jsx.ps1` | 0 errors, 0 warnings (include graph, ES3 compile, ES3 scan, API wiring) |
| `tools/run_tests.ps1` | 79 passed, 0 failed |
| Reference scripts archived | 3 files, SHA256 recorded, byte identical |
| Encoding / line endings | UTF-8 without BOM, LF only (`tools/normalize_eol.ps1`: 0 CRLF) |

## Partially working / not yet verified

* Cleanup behaviour in Illustrator: logic is unchanged, but the new module split
  has **not** been executed inside Illustrator yet.
* Visual result (artwork placement, layer `ARTWORK` content, no leftover crop
  marks) - manual cases F3/F4/R3 pending.
* `dryRun` was tested at unit level only (config + branch logging), not yet in a
  live run together with a real batch.
* Error report folders were unit tested for content, not produced by a real
  failing page.

## Known bugs / open issues

* None known in the refactor itself. Three items carried over from the reference
  and kept deliberately: empty `catch {}` blocks around Illustrator calls, the
  two unused "preserve" switches, and the `JOB\ERROR` folder that is created but
  never written to.
* `JOB\ERROR` is not used because error reports go to the project
  `logs/errors/<timestamp>/` folder.

## Next milestone

1. Run smoke + functional cases S1-S5, F1-F10 in Illustrator on a test JOB.
2. Run the reference comparison R1-R5 (`docs/TESTING.md`) and confirm behaviour
   neutrality.
3. Then set `STATUS.md` to "verified against the reference" and raise the version
   to 0.2.0.
