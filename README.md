# Cleanup AI 2026

| | |
| --- | --- |
| **Repository** | `sviskis/Cleanup_AI2026` |
| **Local folder** | `Cleanup_AI2026` |
| **Display name** | Cleanup AI 2026 |
| **Version** | 0.5.0 |

Two systems in one repository:

1. **Python orchestrator + Illustrator worker (v0.2.0, current)** - planning,
   page counting, template mapping, naming, validation, logging and the batch in
   Python; Illustrator runs as a one page worker that performs the appearance safe
   cleanup and writes the tiles.
2. **Legacy single-file JSX application (v0.1.0, frozen)** - the original
   ScriptUI batch window, kept as the behavioural baseline.

Both share **one** cleanup engine: `jsx/cleanup.jsx`.

```text
PDF page
  -> Python (PyMuPDF page count, template mapping, output name, request JSON)
  -> Illustrator worker (jsx/worker.jsx + jsx/cleanup.jsx)
       cleanup v6 (appearance safe) -> template copy/convert -> ARTWORK layer
       -> save AI -> result JSON (statistics)
  -> Python (matching job_id + run_id accepted, logged, summarised)
```

## Status

Version **0.9.0**. The Python pipeline, the JSX worker, the one page milestone, the
**persistent batch queue** (state.json, recovery, continue/retry, CLI), the
**Tkinter GUI**, the **multi PDF project queue** (several PDFs per JOB, one plan
and one set of states each, explicit RECONCILE), the **visual page browser**
(thumbnails with their queue state, large preview, page info, PDF rendering with
PyMuPDF on a worker thread), **bulk mapping with reusable presets** (range
assignment, numbered auto mapping, a mapping clipboard that works across PDFs,
`JOB/CONFIG/presets/*.json`), a **production preflight** (`[PREFLIGHT PROJECT]`,
READY / NOT READY, OK / WARNING / ERROR), **immutable job reports**
(`JOB/LOG/reports/report_<stamp>.json` + `.txt` after every pass) and a **plan
history with undo and restore** (`JOB/CONFIG/history/`, every real plan change leaves
an atomic snapshot) are implemented and verified with real Illustrator runs. See
`STATUS.md`, `docs/QUEUE_STATE.md` and `docs/GUI.md`.

A wrong edit is never final: `[UNDO PLAN CHANGE]` puts the previous plan back and
`[RESTORE SNAPSHOT]` picks any of the last 100 snapshots - and a restore keeps the plan
it replaces first, so it is reversible too. Queue states, outputs and the run history
are never touched by a plan restore.

Before a long project, one click answers "can this run at all?": PDFs, page counts,
templates, duplicate outputs, the queue, Illustrator, disk space and the report folder
are checked together and only a real error blocks a run. After every pass, a report
with the counts, the durations, the objects, the retries and the exact failure reasons
lands in `JOB/LOG/reports/` - never overwritten, JSON for tools and TXT for people.

Production start is a single file: `powershell -ExecutionPolicy Bypass -File
tools\build_release.ps1` builds `dist\Cleanup AI 2026\Cleanup AI 2026.exe` (no Python
needed on the target machine, no console window, Illustrator still installed normally);
see `docs/PACKAGING.md`.

Mapping a 300 page magazine no longer means 300 clicks: the MAPPING tab assigns a
template to a whole range (`6-35`), matches numbered templates against page numbers
(`001_cover.ai` -> page 1), copies a mapping from one range to another (even into a
different PDF of the same JOB) and applies a saved preset after showing which pages
would change. Every mapping rule lives in `pdf_ai_batch/core/mapping_rules.py`; the
GUI only collects input.

One JOB can hold several PDFs; each has its own page plan, its own queue states and
its own outputs (`manualis__001.ai`, `appendix__001.ai`). The order is `documents[]`
first, then page number. A PDF whose page count changed is `CONFIG STALE` and a
deleted one is `MISSING PDF` - both keep their mapping and their history until the
operator reconciles or the file comes back.

## Quick start (new pipeline)

```powershell
# 1. environment (once)
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. sanity check
.venv\Scripts\python.exe app.py --diagnose

# 3. a demo job with a real 14 page PDF
.venv\Scripts\python.exe tools\make_demo_job.py --root temp\DEMO_JOB --pages 14

# 4. put real templates into temp\DEMO_JOB\TEMPLATE (MASTER must have an ARTWORK layer)

# 5. the GUI (PROJECT / PDF / MAPPING / RUN)
.venv\Scripts\python.exe app.py
#    NEW PROJECT or OPEN PROJECT -> pick the PDF -> MAPPING shows the pages as
#    thumbnails (each with its state) + a large preview -> assign templates visually
#    -> VALIDATE -> RUN ALL ENABLED. Opening the GUI never starts Illustrator.

# 6. one page, end to end (CLI)
.venv\Scripts\python.exe -m pdf_ai_batch.run_one --job temp\DEMO_JOB --pdf calendar.pdf --page 3

# 7. the whole queue (state.json in JOB/CONFIG, resumable)
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\DEMO_JOB --build --pages 1-4
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\DEMO_JOB --run-all
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\DEMO_JOB --status
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\DEMO_JOB --continue      # after a crash/stop
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\DEMO_JOB --retry-errors  # after fixing a page

# several PDFs in one JOB: project scope by default, --pdf narrows it
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\MULTI_JOB --build
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\MULTI_JOB --pdf appendix.pdf --run-all
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\MULTI_JOB --pdf appendix.pdf --reconcile
```

`run_one`: `--preflight-only` validates without touching Illustrator; `--dry-run`
writes and prints the request JSON. `batch`: `--status` shows the per page table,
finished pages are never redone, one bad page never stops the batch; exit code 1
means at least one ERROR/INTERRUPTED is still open.

GUI and CLI share the same `state.json`, so a batch started in the GUI can be
continued from the CLI and vice versa (`--status`, `--continue`, `--retry-errors`).


## Quick start (legacy JSX application)

```text
Illustrator -> File -> Scripts -> Other Script... -> src\Main.jsx
```

or run the frozen single file baseline: `legacy\current_working_v10.jsx`.

## Supported Adobe application

| Item | Value |
| --- | --- |
| Application | Illustrator (not InDesign, not Photoshop) |
| Language | ExtendScript / JSX, ES3 syntax only |
| Platform | Windows (verified) |
| Automation | pywin32 COM, isolated in `pdf_ai_batch/adapters/illustrator.py` |
| GUI | legacy: ScriptUI | new: Tkinter (next milestone) |


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
jsx/                          the only Illustrator side code
  cleanup.jsx                 CANONICAL engine: cleanup v6 + document helpers + stats contract
  json2.js                    ES3 JSON polyfill
  worker.jsx                  one page worker (request -> result)

pdf_ai_batch/                 Python orchestrator
  app.py  run_one.py  batch.py  paths.py  logging_setup.py
  core/  project, pdf_info, naming, template_mapper, config, mapping_rules,
         history, preflight, report, contract, pagejob, state, queue, jsonio,
         validation
  preview/  renderer (PyMuPDF page rendering), cache (JOB/.cache/preview)
  gui/   main_window, controller, tasks, project_tab, pdf_tab, mapping_tab,
         bulk_dialogs, preview_panel, preview_loader, run_tab
  diagnostics.py             production diagnostics (--diagnose, startup check)
  paths.py                   app/install paths (source AND packaged layout)
  adapters/illustrator.py    the ONLY COM code (pywin32)
  tests/                     431 pytest tests (contract, encoding, state, queue,
                             mapping rules, history, preflight, reports, preview,
                             packaging, GUI)

tools/                      gates + packaging
  check_jsx.ps1              ES3/API/encoding gate for jsx/ and src/
  run_tests.ps1              JSX unit tests + JSON contract tests
  build_release.ps1          one command: gates + PyInstaller + assets + verify
  cleanup_ai.spec            the PyInstaller recipe (why PyInstaller: see the file)
  create_shortcut.ps1        opt-in desktop shortcut
requirements*.txt           runtime deps / packaging-only deps

src/                          legacy ScriptUI application (phase 1, kept as baseline)
legacy/current_working_v10.jsx frozen baseline (generated, hashed)
archive/original/             the untouched predecessor scripts
tools/                        gates + migration tools (see tools/README.md)
tests/                        JSX unit tests, JSON contract test, shared fixtures
docs/                         CODE_ANALYSIS, ARCHITECTURE (legacy), WORKFLOW, TESTING, PYTHON_ENV
config/default_config.json    JSON mirror of the legacy config
docs/                         CODE_ANALYSIS, ARCHITECTURE (legacy), QUEUE_STATE,
                              WORKFLOW, TESTING, PYTHON_ENV
MIGRATION_PLAN.md             the approved migration plan and its status
```

## How to run

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
pdf_ai_batch/                 Python orchestrator + Tkinter GUI (new pipeline)
  app.py                      entry point: no args -> GUI, --batch/--run-one/--diagnose/--health
  gui/                        Tkinter GUI (main_window, project/pdf/mapping/run tabs,
                              controller without Tk/COM, tasks = worker thread bridge)
docs/                         CODE_ANALYSIS, ARCHITECTURE, WORKFLOW, TESTING, QUEUE_STATE, GUI
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
    version: "0.2.0",
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
2026-09-23 15:30:10 | INFO | Session started. Version 0.2.0 | PDF Deep Cleanup → AI Template Batch
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
.venv\Scripts\python.exe -m pytest

# production build: the same gates, then PyInstaller, asset copy, verification and a
# packaged --diagnose smoke test -> dist\Cleanup AI 2026\Cleanup AI 2026.exe
powershell -ExecutionPolicy Bypass -File tools\build_release.ps1

# regenerate the modules extracted from the reference script (never hand edit those)
powershell -ExecutionPolicy Bypass -File tools\migrate_extract_sections.ps1
powershell -ExecutionPolicy Bypass -File tools\normalize_eol.ps1
```

Rules for contributors and coding agents: `.clinerules`. Architecture and data
flow: `docs/ARCHITECTURE.md`. The reference script and its analysis:
`archive/original/ARCHIVE_MANIFEST.md`, `docs/CODE_ANALYSIS.md`.

## Testing

* JSX gates: `tools\check_jsx.ps1` (include graph, real ES3 compile for both entry
  points, ES3 scan, module API wiring) and `tools\run_tests.ps1` (79 unit tests +
  44 JSON contract tests).
* Python: `.venv\Scripts\python.exe -m pytest` (80 tests, no Illustrator needed).
* Manual: the smoke / functional / error / regression checklist in
  `docs/TESTING.md`, planned in `tests/TEST_PLAN.md`.

## Known limitations

* The one page milestone still needs its first real Illustrator run
  (`MIGRATION_PLAN.md` §3); everything else is verified automatically.
* The queue / state (`state.json`, resume, retry) and the Tkinter GUI are the next
  milestone - today the CLI processes one page at a time.
* The cleanup engine's visual result can only be judged in Illustrator
  (`docs/TESTING.md` §2).
* `PRESERVE_IMAGE_STRUCTURES` / `PRESERVE_TRANSPARENCY_STRUCTURES` are documented
  intent flags without code behind them (the safe-only tests do that job).
* Page count of an unusual or damaged PDF falls back to `1` when both PyMuPDF and
  pypdf fail (the legacy JSX behaviour was the same).
* The 12 month calendar pipeline of the older script is archived, not migrated.

## Roadmap

* P1 - regression R1-R5 against `legacy/current_working_v10.jsx`, and a real `.ait`
  template run (`template_mode = "saveas"`).
* P1 - **queue + state: done** (`state.json`, WAITING/RUNNING/DONE/ERROR/SKIPPED/
  INTERRUPTED, resume, continue, retry errors, per page status, final batch summary)
  - see `docs/QUEUE_STATE.md`.
* P2 - Tkinter GUI: PROJECT / PDF / MAPPING / RUN tabs with the mapping treeview,
  driven by `core/queue.py` + `core/state.py`. **Done** (milestone 3).
* P2 - multi PDF queue in one run. **Done** (milestone 4).
* P2 - visual page browser (thumbnails + large preview, PyMuPDF on a worker thread).
  **Done** (milestone 5).
* P2 - bulk mapping + reusable presets (ranges, numbered auto map, copy/paste
  mapping, `JOB/CONFIG/presets/`). **Done** (milestone 6).
* P2 - production preflight (`[PREFLIGHT PROJECT]`, READY / NOT READY) and immutable
  job reports (`JOB/LOG/reports/`). **Done** (milestone 7).
* P2 - plan snapshots / undo (`JOB/CONFIG/history/`, `[UNDO PLAN CHANGE]`,
  `[RESTORE SNAPSHOT]`). **Done** (milestone 8). Windows packaging (milestone 9) is
  next, then production hardening to v1.0.0.
* P3 - SQLite history, ZIP handoff of `AI_OUT`, profiles ("conservative" /
  "aggressive" cleanup).

