# Code analysis - reference script and refactoring decisions

Analysis date: 2026-09-23
Scope: every `.jsx` file that existed in the project folder before the restructure.

---

## 1. What the script is for

A single Illustrator script that turns **PDF pages into ready to use Illustrator
documents built on a MASTER template**:

1. it opens one chosen page of a PDF file with Illustrator;
2. it runs "PDF Deep Cleanup v6 (APPEARANCE SAFE)" on that document, which
   removes the technical junk Illustrator imports with a PDF page (thousands of
   unnecessary groups, vector clipping masks, crop marks) **without touching the
   appearance** of real artwork;
3. it copies the MASTER template from `TEMPLATE\` to `AI_OUT\<name>.ai`;
4. it opens that copy and duplicates the cleaned artwork of every PDF layer into
   the template layer `ARTWORK`;
5. it saves the AI file and closes the PDF **without saving**.

The batch can process many PDFs and many pages at once; the operator ticks the
pages in a page list inside the ScriptUI window.

## 2. Adobe application

| Item | Value |
| --- | --- |
| Application | **Illustrator** (`#target illustrator`) |
| Language | Adobe ExtendScript (JSX), ES3 generation |
| GUI | ScriptUI (`Window("dialog", ...)`) |
| Platform | Windows (paths, `decodeURI` handling, `File.encoding = "BINARY"`) |

No InDesign, no Photoshop, no Bridge, no COM, no Python in the reference code.

## 3. Sources that were analysed

| File | Lines | Adobe | Role |
| --- | --- | --- | --- |
| `PDF_Deep_Cleanup_AI_Template_BATCH.jsx` | 1283 | Illustrator | **Primary reference.** PDF Deep Cleanup v6 + AI Template Batch v4 PAGE PICKER, ScriptUI, multi PDF, page checkboxes, batch loop. All `src/` modules were extracted from this file. |
| `PDF_Deep_Cleanup_12_MENESI_GUI_v6.jsx` | 2433 | Illustrator | Predecessor. Same cleanup engine plus a project GUI for 12 month calendars (JOB folder wizard, `config\project_info.json`, three template modes, "SAKĀRTOT JOB SAKNI"). |
| `PDF_Deep_Cleanup_AI2026.jsx` | 842 | Illustrator | Oldest version. Cleanup only, runs on the active document, no GUI, no batch. |

All three are stored unchanged in `archive/original/` (see
`archive/original/ARCHIVE_MANIFEST.md` for SHA256 hashes).

Duplicates: the files in `PDF_Cleanup_AI2026\PDF_Deep_Cleanup_AI_Template_BATCH\`
were byte identical to the files in `..\PDF_Deep_Cleanup_AI_Template_BATCH\`.

## 4. Entry point of the reference script

There is no `main()` in the reference script. Its entry point is the last line:

```javascript
makeBatchWindow();      // line 1283
```

so the top level of the file is the program: helper functions first, then the
whole `makeBatchWindow()` function (lines 795-1281) which builds the window,
defines the state object, wires the buttons and finally calls `w.show()`.

The new project keeps the same mental model but names it: `src/Main.jsx` is the
entry point and it calls `PDC.BatchWindow.open()`.

## 5. Global variables of the reference script

| Global | Line | Used for |
| --- | --- | --- |
| `BATCH_APP_NAME` | 7 | window title |
| `ARTWORK_LAYER_NAME` | 8 | `"ARTWORK"` layer name in the template |
| `pageCountCache` | 789 | page count cache keyed by lower case `fsName` |
| `pageJobs` | 790 | one entry per PDF page: `pdfFile`, `pageNo`, `pageCount`, `checked`, `outputName`, `key` |
| `running` | 791 | batch in progress flag |
| `pageRows` | 792 | the 9 reused ScriptUI rows of the page list |
| `VISIBLE_PAGE_ROWS` | 793 | `9`, how many page rows exist at once (scrollbar driven list) |

Plus two groups of "constants" that are local to functions: the four cleanup
switches (lines 363-366) and the `state` object (line 929).

## 6. Function inventory of the reference script

### 6.1 File / folder helpers (lines 11-78)

| Function | Purpose |
| --- | --- |
| `pathJoin`, `folderJoin` | build `File` / `Folder` from a parent plus a name |
| `ensureFolder` | create folder, throws when it cannot |
| `baseNameNoExt`, `displayPath` | file name without extension, `decodeURI` for display |
| `sortPdfFiles`, `listPdfFiles` | non recursive PDF listing, sorted |
| `isExcludedPdfScanFolder` | skip `template`, `ai_out`, `log`, `error`, `errors`, `archive`, `.git*` |
| `listPdfFilesRecursive` | depth limited recursive PDF scan (default depth 8) |
| `resolvePdfQueue` | decides the PDF source: manual folder, `JOB\PDF`, else recursive JOB scan |

### 6.2 Template / artwork (lines 79-182)

| Function | Purpose |
| --- | --- |
| `templateScore`, `detectTemplate` | rank and pick the MASTER template in `TEMPLATE\` |
| `findOrCreateArtworkLayer` | find or create the `ARTWORK` layer |
| `clearArtworkLayer` | empty the `ARTWORK` layer of the template copy |
| `duplicateSourceLayersIntoArtwork` | duplicate top level page items of every source layer into `ARTWORK` (bottom to top with `PLACEATBEGINNING` to keep stacking order) |
| `duplicateNestedLayerItemsIntoArtwork` | same for sub layers, recursive |

### 6.3 File safety helpers (lines 183-221)

| Function | Purpose |
| --- | --- |
| `safeClose(doc, saveOption)` | close a document, swallowing errors |
| `removeIfExists(file)` | remove a file when it exists |
| `copyTemplateToOutput(template, output, overwrite)` | copy the master template to `AI_OUT`, refuses to overwrite unless asked |
| `formatTimestamp` | `YYYYMMDD_HHMMSS` for log file names |
| `writeLogFile(logFolder, lines)` | write `LOG\batch_<timestamp>.txt` in UTF-8 |
| `safeFileSignature` | `length + "|" + modified`, used as page count cache key |

### 6.4 PDF page counting (lines 222-358)

| Function | Purpose |
| --- | --- |
| `detectPdfPageCountFromStructure` | raw scan of the PDF for `/Type /Pages ... /Count N`; reads the file as `BINARY` in 2 MB chunks with a 4 kB overlap and handles both key orders |
| `detectPdfPageCountWithIllustrator` | opens the PDF with `pageRangeToOpen = "all"`, counts `artboards`, closes without saving, restores `PDFFileOptions` and `userInteractionLevel` |
| `detectPdfPageCount` | strategy: Illustrator count > 1, else structure count, else 1 |
| `openPdfPage` | sets `pageToOpen` / `pageRangeToOpen` / `placeAsLinks = false` and opens the PDF |
| `padPageNumber`, `makePageOutputName`, `pageJobKey` | `leaflet_p03.ai` naming and cache/check keys |

### 6.5 PDF Deep Cleanup v6, the core engine (lines 360-786)

`runPdfDeepCleanup(doc)` contains about 30 nested functions and returns a stats
object. Order of operations:

1. `saveViewState` / `restoreViewState` - artboard index, zoom, centre point.
2. `unlockLayerRecursive` / `unlockAll` - unlock layers, then items.
3. `ungroupSafeGroups(doc, 40)` - repeatedly ungroup only groups that pass the
   safety tests; `isSafeToUngroup` rejects groups with non default appearance,
   image like artwork, clipped descendants, risky ancestors and more.
4. `releaseSafeVectorClippingMasks` - release only vector-only clipping masks
   (`isSafeVectorClippingGroup`), then delete the released mask paths.
5. `ungroupSafeGroups` again (releasing masks can expose new safe groups).
6. `deleteCropPerimeterObjects` - removes linework that lies on the artboard
   perimeter and spans it.
7. `deleteShortCropMarks` - removes short 2 point stroke-only open paths that sit
   on the artboard edge.
8. `app.executeMenuCommand("deselectall")`, restore view state, return `stats`.

Safety tests used (all "preserve" oriented): `hasNonDefaultAppearance`
(opacity, blending mode, isolation, knockout),
`containsNonDefaultAppearanceDescendant`, `containsImageLikeArtwork`
(`RasterItem`, `PlacedItem`, `MeshItem`, `PluginItem`, `SymbolItem`),
`containsClippedGroupDescendant`, `containsNestedClippedGroup`,
`hasRiskyAncestor`, `containsAnyFill`, `isTechnicalLinework`,
`isCandidateVectorItem`, `getItemDepth`, `pushUnique`, `isValidPageItem`,
`getActiveArtboardBounds`, `safeBounds`.

Counters written into `stats`: `safeGroupsUngrouped`, `riskyGroupsPreserved`,
`vectorMasksReleased`, `riskyMasksPreserved`, `maskPathsDeleted`,
`cropPerimetersDeleted`, `shortCropMarksDeleted`.

### 6.6 GUI (lines 788-1281)

Inside `makeBatchWindow()`:

| Function | Purpose |
| --- | --- |
| `addPathRow` | one label + read only field + optional "Mainīt..." button |
| row loop | builds `VISIBLE_PAGE_ROWS` (9) checkbox rows that are reused for every page |
| state object | `jobFolder`, `pdfFolder`, `manualPdfFolder`, `pdfScanMode`, `templateFolder`, `templateFile`, `outputFolder`, `logFolder`, `errorFolder`, `pdfFiles`, `logLines` |
| `addLog` | appends to the log panel and to `state.logLines` |
| `selectedPageCount`, `updateFields`, `updatePageSummaryAndStart`, `renderPageRows`, `setAllChecks` | view state |
| `getCachedPageInfo`, `rebuildPageJobs` | page list build with cache and check state preservation |
| `scanJob(forceRedetect)` | folder resolution, page list, status line, log block |
| `startBtn.onClick` | the batch loop (lines 1142-1277) |

## 7. File and folder operations

| Operation | Where | Target |
| --- | --- | --- |
| Folder creation | `ensureFolder` | `JOB\TEMPLATE`, `JOB\AI_OUT`, `JOB\LOG`, `JOB\ERROR` (in `scanJob`) |
| Recursive read | `listPdfFilesRecursive`, `Folder.getFiles()` | JOB folder, manual PDF folder |
| Read as text / binary | `detectPdfPageCountFromStructure` | PDF file, `encoding = "BINARY"` |
| Write | `writeLogFile` | `JOB\LOG\batch_<timestamp>.txt`, UTF-8, Windows line feed |
| Copy | `copyTemplateToOutput` | `TEMPLATE\MASTER_*.ai` -> `AI_OUT\<name>.ai` |
| Delete file | `removeIfExists` | partial output after a failed page; existing output when overwrite is ticked |
| Open document | `app.open(pdfFile)`, `app.open(outputFile)` | PDF page, AI template copy |
| Save document | `destDoc.save()` | `AI_OUT\<name>.ai` |
| Close document | `safeClose` | PDF with `DONOTSAVECHANGES`, AI with `SAVECHANGES` (already saved) |
| Delete page items | `item.remove()`, `p.remove()` | crop marks, released mask paths |
| Ungroup / release mask | `app.executeMenuCommand("ungroup" / "releaseMask")` | document level, selection based |
| Clear layer | `clearArtworkLayer` | `ARTWORK` layer of the AI copy |

## 8. Configuration values in the reference script

| Value | Line | Notes |
| --- | --- | --- |
| `BATCH_APP_NAME` | 7 | window title |
| `ARTWORK_LAYER_NAME = "ARTWORK"` | 8 | must match the template |
| `PRESERVE_IMAGE_STRUCTURES = true` | 363 | **declared but never read** |
| `PRESERVE_TRANSPARENCY_STRUCTURES = true` | 364 | **declared but never read** |
| `RELEASE_SAFE_VECTOR_MASKS = true` | 365 | switch for mask release |
| `DELETE_CROP_MARKS = true` | 366 | switch for crop mark removal |
| `ungroupSafeGroups(doc, 40)` | 775, 777 | ungroup pass limit |
| `VISIBLE_PAGE_ROWS = 9` | 793 | page list height |
| `maxDepth = 8` | 48 | PDF scan depth |
| `chunkSize = 2 MB`, `overlap = 4096` | 246, 247 | PDF structure scan |
| page count cache | `pageCountCache` | keyed by `fsName` + file signature |
| `overwriteCb.value = false` | 837 | default: never overwrite an existing output |
| `clearArtworkCb.value = true` | 839 | default: empty the `ARTWORK` layer of the template copy |
| folder names `PDF`, `TEMPLATE`, `AI_OUT`, `LOG`, `ERROR` | 1065-1069 | hard coded JOB layout |
| excluded scan folders | 43 | `template`, `ai_out`, `log`, `error`, `errors`, `archive`, `.git*` |
| crop mark tolerances | 691, 736, 737 | derived from artboard size, not configurable |

`PRESERVE_IMAGE_STRUCTURES` and `PRESERVE_TRANSPARENCY_STRUCTURES` are dead
switches: the same behaviour is enforced by the "safe only" tests inside the
engine. They were kept in `CONFIG.cleanup` as documented intent flags.

## 9. Hard coded paths

**Finding: none.** No absolute path such as `C:\Users\<name>\Desktop\...` exists
in any of the three scripts. Every location comes from:

* `Folder.selectDialog()` / `File.openDialog()` (the operator chooses),
* the chosen JOB folder plus the folder names above,
* `app.activeDocument` (in the oldest version).

This is why the new project needed no path migration at all - only the
project-relative helpers that plan phase 7 asks for (`src/utils/Paths.jsx`).

Windows specifics the code already handles: `decodeURI()` for Latvian characters
and spaces in file names, forward slashes for `File()` / `Folder()`, long OneDrive
paths and `File.encoding` handling for binary PDF reads.

## 10. Adobe DOM API used

| Area | API |
| --- | --- |
| Application | `app.documents`, `app.activeDocument`, `app.open`, `app.preferences.PDFFileOptions` (`pageToOpen`, `pageRangeToOpen`, `placeAsLinks`), `app.userInteractionLevel`, `app.executeMenuCommand`, `app.redraw` |
| Document | `doc.layers`, `doc.groupItems`, `doc.pageItems`, `doc.pathItems`, `doc.artboards`, `doc.views[0].zoom` / `.centerPoint`, `doc.activate()`, `doc.close()`, `doc.save()` |
| Layer / item | `layers.add`, `layers.getByName`, `pageItems`, `typename`, `clipped`, `clipping`, `filled`, `stroked`, `closed`, `pathPoints.length`, `opacity`, `blendingMode`, `isIsolated`, `artworkKnockout`, `selected`, `duplicate(layer, placement)`, `remove()`, `visible`, `locked` |
| Enums | `SaveOptions.DONOTSAVECHANGES`, `SaveOptions.SAVECHANGES`, `ElementPlacement.PLACEATBEGINNING`, `UserInteractionLevel.DONTDISPLAYALERTS`, `BlendModes.NORMAL`, `KnockoutState.*` |
| ExtendScript globals | `File`, `Folder`, `$` (`.gc()`), `decodeURI`, `alert` |

## 11. Error handling in the reference script

* Almost every risky line is wrapped in `try/catch(e) {}` with an **empty**
  handler - a deliberate "never break the batch" style, but errors stay invisible.
* The batch loop has one `try/catch` per page (lines 1204-1242): on error it
  closes both documents without saving, deletes a partially written output and
  appends an `ERROR ...` line to the log panel.
* The error text is only `String(err)` - no `err.message`, no `err.line`, no
  `err.fileName`, no report folder.
* The `ERROR` folder inside the JOB folder is **created but never written to**.
* A failure **before** the loop (page counting, folder creation, template
  detection) is not caught: `startBtn.onClick` has no outer `try/catch`, so the
  normal Illustrator error dialog appears and `userInteractionLevel` or the
  window state can stay changed.
* `writeLogFile` is only reached after the loop, so a hard failure can lose the
  log of the whole run.

## 12. Potentially dangerous operations (fail safe review)

| Operation | Risk | Reference behaviour | New project |
| --- | --- | --- | --- |
| `templateFile.copy(outputFile)` | writing into `AI_OUT` | refuses when the output exists and overwrite is off | same + `CONFIG.dryRun` plans only |
| `outputFile.remove()` | deleting an existing AI file | only with the overwrite checkbox | same, routed through `FileService.removeIfExists` and logged |
| `destDoc.save()` then close with `SAVECHANGES` | writing the AI file | unconditional after a successful duplicate | same |
| `sourceDoc.close(DONOTSAVECHANGES)` | closing the PDF | always without saving | same |
| `app.executeMenuCommand("ungroup" / "releaseMask")` | changing document structure | only on groups / masks that pass the safety tests | unchanged |
| `item.remove()` / `p.remove()` | deleting content | only crop marks and released mask paths | unchanged |
| `removeIfExists(outputFile)` in the error path | deleting the file just created | safe, it is the batch's own output | same |
| MASTER template | could be destroyed | never written, only copied | same, documented as an invariant |
| `clearArtworkLayer` | deleting template placeholders | only in the copy, default on | same + `CONFIG.clearArtworkByDefault` |

## 13. External dependencies

* Illustrator + ExtendScript only.
* No libraries, no includes, no network, no COM, no external executables in the
  reference script.
* Development time tooling introduced by this restructure: PowerShell 5.1 and the
  Windows Script Host (JScript 5.8) for checks and unit tests - see
  `tools/README.md`. These are **not** needed to run the script in Illustrator.

## 14. Where modules were separated (legacy -> new)

| Reference script (lines) | New module | Kind |
| --- | --- | --- |
| 10-15, 25-78, 183-190, 216-221 | `src/services/FileService.jsx` | extracted + 2 config hooks |
| 16-24, 199-203, 344-350 | `src/utils/TextUtils.jsx` | extracted |
| 79-182 | `src/core/TemplateManager.jsx` | extracted + config hook |
| 191-198, 351-358 | `src/core/OutputManager.jsx` | extracted + dry run guard |
| 204-213 | `src/services/LogService.jsx` | extracted + levelled logging |
| 222-343 | `src/core/PdfPageCount.jsx` | extracted |
| 378-771 | `src/core/PdfCleanup.jsx` | extracted (nested functions -> module scope) |
| 796-927 | `src/ui/BatchWindow.jsx` | extracted widget construction |
| 1017-1103, 1142-1277 | `src/core/BatchRunner.jsx` | controller (moved out of the window) |
| 928-1015, 1105-1140 | `src/ui/BatchWindow.jsx` | view glue (rewritten, same behaviour) |
| - | `src/config/Config.jsx` | new: all values collected |
| - | `src/utils/Namespace.jsx`, `src/utils/Paths.jsx` | new: namespace and project relative paths |
| - | `src/services/ErrorService.jsx` | new: central error handling and reports |
| - | `src/core/Diagnostics.jsx` | new: preflight diagnostics |
| - | `src/Main.jsx` | new: single entry point with the `#include` list |

The extraction itself is done by `tools/migrate_extract_sections.ps1`, which
slices the reference file by line number, so the working logic was never retyped
by hand.

## 15. Risks and problems found, and how they are handled

| # | Risk / problem | Severity | Handling in the new project |
| --- | --- | --- | --- |
| 1 | Empty `catch {}` blocks hide failing `app.open`, `duplicate`, `remove` calls | medium | kept (batch stability) but every page level failure is now logged through `ErrorService` with a report folder |
| 2 | No outer guard around the batch; `userInteractionLevel` could stay at `DONTDISPLAYALERTS` | medium | the `startBtn` handler has `try/catch/finally`, restores the level and unlocks the window |
| 3 | Log file lost if the run dies hard | medium | `writeJobLog` + `flushSessionLog` inside `finishRun()`, called from `runSelected` and from the view level `finally` |
| 4 | `ERROR` folder created but unused | low | errors now produce `logs/errors/<timestamp>/error.txt + context.txt`; the JOB `ERROR` folder is still created for layout compatibility |
| 5 | Two "preserve" switches declared but never read | low | documented as intent flags in `CONFIG.cleanup` |
| 6 | Duplicated code between the three script versions | medium | one primary reference chosen, predecessors archived, the 12 month pipeline listed in `TODO.md` as an optional future module |
| 7 | Everything in one 1283 line file, GUI and logic interleaved | high (maintainability) | split into 15 modules behind a `PDC` namespace: UI / controller / core / services |
| 8 | No tests, no way to check the code without Illustrator | high | `tools/check_jsx.ps1` (include graph + real ES3 compile + ES3 scan + API wiring) and `tools/run_tests.ps1` (79 unit tests with a stubbed host) |
| 9 | Page detection can open the PDF twice (probe + real open) | low | unchanged; the result is cached per file signature |
| 10 | Both documents stay in memory during a batch | low | unchanged (`$.gc()` after every page) |
| 11 | No dry run, so a first run on a real job always writes files | medium | `CONFIG.dryRun = true` plans and logs without touching anything |
| 12 | A skipped (existing) output is only visible in the GUI log | low | also written to the session log (`SKIP existing output: ...`) |

## 16. Recommended structure (delivered)

```text
PDF_Cleanup_AI2026/
├── src/
│   ├── Main.jsx                  entry point, #include list
│   ├── config/Config.jsx         all values
│   ├── utils/                    Namespace, Paths, TextUtils
│   ├── services/                 FileService, LogService, ErrorService
│   ├── core/                     PdfCleanup, PdfPageCount, TemplateManager,
│   │                             OutputManager, BatchRunner, Diagnostics
│   └── ui/BatchWindow.jsx        ScriptUI view only
├── config/                       JSON mirror of the config for humans/tools
├── docs/                         CODE_ANALYSIS, ARCHITECTURE, WORKFLOW, TESTING
├── tests/                        TEST_PLAN.md + JScript unit tests
├── examples/JOB_STRUCTURE.md     the JOB folder contract
├── logs/                         runtime session log + error reports (ignored)
├── temp/                         generated verify/test bundles (ignored)
├── archive/original/             untouched reference scripts
├── tools/                        check_jsx, run_tests, migration, normalisation
└── README.md STATUS.md TODO.md CHANGELOG.md VERSION .gitignore .gitattributes
```

Folders that are deliberately **not** created: `output/`, `input/`, `temp/` as a
source folder. The tool never writes into the project folder - PDFs and AI files
live in the JOB folder chosen by the operator (`examples/JOB_STRUCTURE.md`). No
empty folders were added for theory's sake.

## 17. Known gaps after the refactor

* Cleanup behaviour is not covered by automated tests (it needs Illustrator). Use
  the manual checklist in `docs/TESTING.md` before a real batch.
* The 12 month pipeline (`project_info.json`, month layers, `SAKĀRTOT JOB SAKNI`)
  is **not** migrated. It is archived and listed in `TODO.md` P2.
* `TemplateManager.duplicateSourceLayersIntoArtwork` order and grouping behaviour
  is unchanged, but the visual result should be confirmed once on a real job.
* Error reporting cannot attach a screenshot from ExtendScript; the folder layout
  is prepared for a future Python helper (`docs/ARCHITECTURE.md`).
