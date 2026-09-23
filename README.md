# PDF Deep Cleanup AI 2026

Adobe **Illustrator** ExtendScript tool that turns PDF pages into ready to use
Illustrator documents built on a MASTER template, with an appearance safe
"deep cleanup" of the PDF junk in between.

```text
PDF page (ticked in the GUI)
   -> PDF Deep Cleanup v6 (appearance safe: ungroup only what is provably safe,
      release only vector-only clipping masks, remove crop marks)
   -> copy MASTER_AI_TEMPLATE.ai to AI_OUT\<pdf>_pNN.ai
   -> duplicate the cleaned artwork into the template layer "ARTWORK"
   -> save the AI, close the PDF without saving
```

The master template is never modified.

## Status

Version **0.1.0** - the reference script of the tool, restructured into modules
and covered by automated checks. Behaviour is intended to be identical to
`archive/original/PDF_Deep_Cleanup_AI_Template_BATCH.jsx`. See `STATUS.md`.

## Supported Adobe application

| Item | Value |
| --- | --- |
| Application | Illustrator (not InDesign, not Photoshop) |
| Language | ExtendScript / JSX, ES3 syntax only |
| Platform | Windows (verified); paths are handled in a portable way |
| GUI | ScriptUI dialog window |

## Requirements

* Adobe Illustrator with `File > Scripts > Other Script...` (any modern version).
* Nothing else to install. No libraries, no network, no COM.
* Optional, for development only: PowerShell 5.1 (built into Windows) and the
  Windows Script Host `cscript` for the automated checks.

## Installation

```text
1. Copy or clone this folder anywhere (OneDrive, network share, USB - no config).
2. Keep the folder layout intact: src/Main.jsx locates everything relative to itself.
3. Optional: add a shortcut to src/Main.jsx into the Illustrator Scripts folder.
```

## How to run

```text
Illustrator -> File -> Scripts -> Other Script... -> <project>\src\Main.jsx
```

1. Choose the **JOB folder** (the one that contains `PDF\` and `TEMPLATE\`).
2. Press **Diagnostika** once to confirm folders, write access and template.
3. Tick the pages you want, then press **START BATCH**.

`src/Main.jsx` is the only entry point: it loads all modules with `#include`.

## Project structure

```text
src/
  Main.jsx                    entry point (#target illustrator, #include list, boot)
  config/Config.jsx           every tunable value in one place
  utils/Namespace.jsx         PDC namespace + registerModule
  utils/Paths.jsx             project paths, JOB folder layout
  utils/TextUtils.jsx         file name / page number / timestamp helpers
  services/FileService.jsx    File, Folder, PDF scan, write test, safe close
  services/LogService.jsx     levelled logging, session log, job batch log
  services/ErrorService.jsx   error dialog + logs/errors/<ts>/{error,context}.txt
  core/PdfCleanup.jsx         the appearance safe cleanup engine
  core/PdfPageCount.jsx       page count (PDF structure scan + Illustrator probe)
  core/TemplateManager.jsx    template detection, ARTWORK layer, artwork duplication
  core/OutputManager.jsx      output naming, overwrite rules, template copy
  core/BatchRunner.jsx        controller: scan, page jobs, batch loop
  core/Diagnostics.jsx        environment and config checks
  ui/BatchWindow.jsx          ScriptUI view (widgets + event wiring only)

config/default_config.json    JSON mirror of Config.jsx (documentation, not input)
docs/                         CODE_ANALYSIS, ARCHITECTURE, WORKFLOW, TESTING
tests/                        TEST_PLAN.md, jscript/ unit tests + host stubs
examples/JOB_STRUCTURE.md     the JOB folder contract and a minimum test job
logs/                         runtime session log + error reports (git ignored)
temp/                         generated verify/test bundles (git ignored)
archive/original/             the untouched reference scripts + manifest
tools/                        check_jsx, run_tests, migration, normalisation
```

## Configuration

All values live in `src/config/Config.jsx`:

```javascript
PDC.CONFIG = {
    appName: "PDF Deep Cleanup → AI Template Batch",
    version: "0.1.0",
    debug: false,              // verbose logging
    dryRun: false,             // true = plan and log only, write nothing
    overwriteExisting: false,  // default for the "Pārrakstīt esošos AI" checkbox
    clearArtworkByDefault: true,
    artworkLayerName: "ARTWORK",
    visiblePageRows: 9,
    maxPdfScanDepth: 8,
    folders: { input: "PDF", template: "TEMPLATE", output: "AI_OUT", logs: "LOG", errors: "ERROR", ... },
    log: { level: "INFO", ... },
    cleanup: { releaseSafeVectorMasks: true, deleteCropMarks: true, ungroupPasses: 40, ... }
};
```

`config/default_config.json` mirrors these values for humans and tooling.
ExtendScript has no `JSON.parse`, so the script always reads `Config.jsx`.

## Workflow

```text
JOB\
  PDF\        input PDFs (scanned recursively; TEMPLATE/AI_OUT/LOG/ERROR are skipped)
  TEMPLATE\   MASTER_AI_TEMPLATE.ai - only read, never written
  AI_OUT\     results: <pdf>.ai for single page PDFs, <pdf>_p03.ai for multi page
  LOG\        batch_<timestamp>.txt, one file per run
  ERROR\      reserved for the JOB layout (project error reports live in logs/errors/)
```

Details, first-run procedure and troubleshooting: `docs/WORKFLOW.md`.

## Input

`*.pdf` files inside the JOB `PDF\` folder or a folder chosen with
"PDF: Mainīt...". Sizes from a few pages to hundreds of pages per file are
supported (page count is cached per file signature).

## Output

One Illustrator file per processed PDF page inside `AI_OUT\` (or a folder chosen
with "AI OUT: Mainīt..."), built from the template copy, with the cleaned artwork
in the layer `ARTWORK`.

## Logging

* `logs/project.log` - append-only session log with timestamps and levels.
* `JOB\LOG\batch_<timestamp>.txt` - one file per batch run, same style as the
  reference script.
* GUI log panel - live view of the same events.

```text
2026-09-23 15:30:10 | INFO | Session started. Version 0.1.0 | PDF Deep Cleanup → AI Template Batch
2026-09-23 15:30:12 | INFO | Scan done: pdf=3 pages=18 selected=18 template=OK
2026-09-23 15:30:14 | ERROR | [KĻŪDA] Batch page processing: Neizdevās atvērt PDF
```

## Error handling

One central entry point, `PDC.ErrorService.handleError(error, context)`. It logs
the error, writes a report and shows one dialog:

```text
logs/errors/2026-09-23_153510/
    error.txt      PROJECT, VERSION, WHEN, OPERATION, ERROR, MESSAGE, FILE, LINE, STACK
    context.txt    ACTIVE DOCUMENT, INPUT FILE, OUTPUT FILE, CURRENT OPERATION,
                   TEMPLATE FILE, PDF PAGE, JOB FOLDER, CONFIG snapshot
```

Per page errors never stop the batch: the page is marked `ERROR`, its partial
output is deleted and the next page continues. A screenshot cannot be captured
from ExtendScript; the report folder is ready for a future Python helper.

## Fail safe behaviour

* `overwriteExisting = false` by default - existing outputs are reported as `SKIP`.
* `dryRun = true` plans and logs every action without touching a single file.
* The MASTER template is only ever read.
* A failed page removes only its own output file.
* `userInteractionLevel` is restored even if a run fails hard.

## Development

```powershell
# automated gate - must be green before every commit
powershell -ExecutionPolicy Bypass -File tools\check_jsx.ps1
powershell -ExecutionPolicy Bypass -File tools\run_tests.ps1

# regenerate the modules extracted from the reference script (never hand edit those)
powershell -ExecutionPolicy Bypass -File tools\migrate_extract_sections.ps1
powershell -ExecutionPolicy Bypass -File tools\normalize_eol.ps1
```

Rules for contributors and coding agents: `.clinerules`. Architecture and data
flow: `docs/ARCHITECTURE.md`. The reference script and its analysis:
`archive/original/ARCHIVE_MANIFEST.md`, `docs/CODE_ANALYSIS.md`.

## Testing

* Automation: `tools/check_jsx.ps1` (include graph, real ES3 compile, ES3 scan,
  module API wiring) and `tools/run_tests.ps1` (79 unit tests with a stubbed
  ExtendScript host). Both run without Illustrator.
* Manual: the smoke / functional / error / regression checklist in
  `docs/TESTING.md`, planned in `tests/TEST_PLAN.md`.

## Known limitations

* The cleanup engine is only covered by manual visual tests - it needs
  Illustrator.
* `PRESERVE_IMAGE_STRUCTURES` / `PRESERVE_TRANSPARENCY_STRUCTURES` are documented
  intent flags without code behind them (the safe-only tests do that job).
* Python/COM helpers for screenshots and end to end automation do not exist yet.
* Page count of an unusual or damaged PDF falls back to `1` when both detection
  strategies fail.
* The 12 month calendar pipeline of the older script is archived, not migrated.

## Roadmap

* P1 - run the regression comparison (R1-R5 in `docs/TESTING.md`) on a real job.
* P2 - migrate the 12 month project pipeline (three template modes, month layers,
  `project_info.json`) as an optional mode.
* P2 - Python/COM helper: run the script headless, collect logs, attach a
  screenshot to the error report.
* P3 - optional SQLite log/history, ZIP handoff of `AI_OUT`, batch resume.
