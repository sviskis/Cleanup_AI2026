# Architecture

Repository: `sviskis/Cleanup_AI2026` · display name: Cleanup AI 2026

> **Note (v0.2.0):** this document describes the **legacy single-file JSX
> application** in `src/` (phase 1 of the project). The production architecture is
> now the Python orchestrator + Illustrator worker; see
> [`/ARCHITECTURE.md`](../ARCHITECTURE.md) and [`/MIGRATION_PLAN.md`](../MIGRATION_PLAN.md).
> `src/` is still the reference for the ScriptUI workflow and is kept as the
> baseline the Python pipeline is compared against.

## 1. Layering

```text
        +--------------------------------------------------+
        |  src/ui/BatchWindow.jsx        (VIEW)            |
        |  ScriptUI widgets, labels, event wiring.         |
        |  No decisions, no filesystem, no Illustrator DOM. |
        +------------------------+-------------------------+
                                 | view interface
                                 | addLog / renderPageRows / setCurrentText /
                                 | setProgress / setRunning / updateFields / ...
                                 v
        +--------------------------------------------------+
        |  src/core/BatchRunner.jsx      (CONTROLLER)      |
        |  state, page jobs, scan, run loop, counters.     |
        +---+-------------------------+--------------------+
            |                         |
            v                         v
  +-------------------+     +----------------------------+
  | core engines      |     | services                   |
  | PdfCleanup        |     | FileService (File/Folder)  |
  | PdfPageCount      |     | LogService  (logs)         |
  | TemplateManager   |     | ErrorService (reports)     |
  | OutputManager     |     +----------------------------+
  | Diagnostics       |                 |
  +---------+---------+                 |
            |                           |
            v                           v
   Illustrator DOM                     Windows filesystem
   (app, doc, items)                   (ExtendScript File/Folder)
```

Data flows in one direction: the view calls the controller, the controller calls
the core/services, and the core/services never call the view. The controller
reaches the UI only through the small `view` interface object that
`BatchWindow.open()` builds, which is why the whole controller can be tested
without a window.

## 2. Module responsibilities

| Module | Owns | Must not do |
| --- | --- | --- |
| `src/Main.jsx` | entry point, `#target illustrator`, `#include` order, session start, top level error guard, VERSION consistency check | business logic |
| `config/Config.jsx` | every tunable value | touch disk or Illustrator |
| `utils/Namespace.jsx` | the `PDC` root object and `registerModule` | anything else |
| `utils/Paths.jsx` | project paths from `$.fileName`, JOB folder layout, suggested JOB folder | hard coded user paths |
| `utils/TextUtils.jsx` | file name / page number / timestamp formatting, `displayPath` | filesystem access |
| `services/FileService.jsx` | `File`/`Folder` handling, PDF scanning, file signature, safe close, write/append/read text, write test | Illustrator document logic |
| `services/LogService.jsx` | session log lines, job batch log file, log levels | decide what happens on failure |
| `services/ErrorService.jsx` | error message extraction, error report folder, one error dialog | continue a batch |
| `core/PdfCleanup.jsx` | the appearance safe cleanup engine and its stats | IO, GUI, logging decisions |
| `core/PdfPageCount.jsx` | page count through the PDF structure and through an Illustrator probe, `openPdfPage` | cache or UI |
| `core/TemplateManager.jsx` | template detection/ranking, `ARTWORK` layer, duplication of artwork into it | write the master template |
| `core/OutputManager.jsx` | output naming, output existence/overwrite rules, template copy | run documents |
| `core/BatchRunner.jsx` | state, scan, page job list, batch loop, counters, job log trigger | touch widgets |
| `core/Diagnostics.jsx` | environment and configuration checks | change anything |
| `ui/BatchWindow.jsx` | widgets, labels, event wiring, view interface | business logic |

## 3. Module loading (`#include`)

`src/Main.jsx` lists modules in dependency order:

```javascript
#target illustrator

#include "utils/Namespace.jsx"        // PDC root - must be first
#include "config/Config.jsx"          // PDC.CONFIG
#include "utils/TextUtils.jsx"        // PDC.TextUtils
#include "services/FileService.jsx"   // PDC.FileService
#include "utils/Paths.jsx"            // PDC.Paths (uses FileService at call time)
#include "services/LogService.jsx"    // PDC.LogService
#include "services/ErrorService.jsx"  // PDC.ErrorService
#include "core/PdfCleanup.jsx"
#include "core/PdfPageCount.jsx"
#include "core/TemplateManager.jsx"
#include "core/OutputManager.jsx"
#include "core/BatchRunner.jsx"
#include "core/Diagnostics.jsx"
#include "ui/BatchWindow.jsx"
```

* Paths are relative to the including file (`src/`), as ExtendScript requires.
* `#include` is a textual include performed before execution, so the order only
  matters for the `PDC.registerModule(...)` calls, which run at load time.
* `PDC.registerModule` throws on a duplicate name, which catches copy/paste
  mistakes immediately.
* No module has `#target`: only `src/Main.jsx` may be run. Running a single module
  file directly is not supported and not needed - diagnostics are available from
  the window's "Diagnostika" button.

## 4. Where the project root comes from

```javascript
PDC.Paths.getScriptFile()   // new File($.fileName)   -> <project>/src/Main.jsx
PDC.Paths.getProjectRoot()  // ...parent.parent      -> <project>
```

Because `$.fileName` is the file Illustrator executes, the project can be copied
or cloned anywhere (OneDrive, network share, USB) without configuration.
`Paths.getScriptFile()` falls back to `Folder.current` when `$.fileName` is empty
(for example in the ExtendScript Toolkit scratch buffer).

## 5. Configuration

`src/config/Config.jsx` is the single source of truth:

| Group | Keys | Notes |
| --- | --- | --- |
| identity | `projectName`, `appName`, `version` | `appName` is the window title |
| safety | `debug`, `dryRun`, `overwriteExisting`, `clearArtworkByDefault` | `dryRun` plans and logs, never writes |
| workflow | `artworkLayerName`, `visiblePageRows`, `maxPdfScanDepth`, `excludedScanFolders` | identical defaults to the reference script |
| layout | `folders.input/template/config/output/temp/logs/errors` | JOB sub folder names (`PDF`, `TEMPLATE`, `AI_OUT`, `LOG`, `ERROR`) |
| logging | `log.level`, `log.sessionFileName`, `log.jobFilePrefix`, `log.errorReportFolder` | level `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| engine | `cleanup.releaseSafeVectorMasks`, `cleanup.deleteCropMarks`, `cleanup.ungroupPasses`, `cleanup.preserve*` | the two `preserve*` keys are documented intent flags (see `docs/CODE_ANALYSIS.md` §8) |
| hint | `defaultJobFolder` | optional starting folder for diagnostics |

`config/default_config.json` mirrors those values for humans and for a future
Python/COM layer. ExtendScript has no `JSON.parse`, so the script always reads
`Config.jsx`; the JSON file is documentation, never an input. Changing a value
means changing `Config.jsx` (and the JSON mirror).

## 6. Logging

```text
2026-09-23 15:30:10 | INFO | Script started
2026-09-23 15:30:12 | INFO | Scan done: pdf=3 pages=18 selected=18 template=OK
2026-09-23 15:30:14 | ERROR | [KĻŪDA] Batch page processing: Neizdevās atvērt PDF
```

| Destination | Written by | Purpose |
| --- | --- | --- |
| `logs/project.log` (project) | `LogService.flushSessionLog()` (append) | one file for all sessions, the long term trace |
| `LOG/batch_<timestamp>.txt` (JOB) | `LogService.writeJobLog()` | one file per batch run, exactly like the reference script |
| GUI log panel | `view.addLog()` + `LogService` | live feedback while working |

Levels: `logDebug` (only when `CONFIG.debug`), `logInfo`, `logWarning`,
`logError`. `logError` is always written. The GUI panel shows the same text that
lands in the file.

## 7. Error handling

```text
per page error        -> view.addLog("ERROR ...") + ErrorService.handleError(..., {silent:true})
                         batch continues, partial output removed, report written
run level error       -> view level try/catch/finally + ErrorService.handleError(...) with dialog
script level error    -> src/Main.jsx top level try/catch -> ErrorService.handleError(...)

logs/errors/2026-09-23_153510/
    error.txt      PROJECT, VERSION, WHEN, OPERATION, ERROR, MESSAGE, FILE, LINE, STACK
    context.txt    ACTIVE DOCUMENT, INPUT FILE, OUTPUT FILE, CURRENT OPERATION,
                   TEMPLATE FILE, PDF PAGE, JOB FOLDER, CONFIG snapshot, EXTRA
```

`ErrorService` never throws: log writing and report writing are individually
guarded, so even a failure while reporting a failure still ends with a dialog.

`screenshot.png` cannot be produced from ExtendScript. The report folder is
deliberately "one folder per incident", so a future Python helper (win32com to
drive Illustrator + Pillow for the screenshot) can write the file into the same
folder later:

```text
logs/errors/<timestamp>/error.txt
logs/errors/<timestamp>/context.txt
logs/errors/<timestamp>/screenshot.png     <- future Python helper
```

## 8. Fail safe rules

1. `CONFIG.overwriteExisting = false` - the script refuses to overwrite an
   existing output unless the operator ticks "Pārrakstīt esošos AI".
2. `CONFIG.dryRun` - every destructive step is replaced by a log line
   (`PLĀNS ...`), counters report the plan, nothing is written or deleted.
3. The MASTER template is only ever read (`templateFile.copy(outputFile)`).
4. Every output is produced by copy-then-edit, never by editing the master.
5. A failed page removes its own partial output and closes both documents without
   saving.
6. `userInteractionLevel` is restored even when a run fails hard.
7. The `ARTWORK` layer is only cleared in the output copy, never in the master.
8. Every skip / overwrite / delete decision is logged with the affected path.

## 9. Extension points

| Want to add | Touch |
| --- | --- |
| a new GUI option | `ui/BatchWindow.jsx` (widget + pass a value into a controller call) and `Config.jsx` for the default |
| a new cleanup switch | `Config.jsx` -> `cleanup` block plus the code path in `core/PdfCleanup.jsx` |
| a new page count strategy | `core/PdfPageCount.jsx` -> `detectPdfPageCount` |
| a different output name scheme | `core/OutputManager.jsx` -> `makePageOutputName` |
| Python / COM automation on top | call `src/Main.jsx` through Illustrator's `do javascript`, or read `logs/project.log` and `config/default_config.json` |
| a ZIP handoff of `AI_OUT` | new `services/ArchiveService.jsx`, called from `BatchRunner.runSelected` after the loop |
