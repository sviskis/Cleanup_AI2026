# GUI (milestones 3-6) - Cleanup AI 2026

`python app.py`  (or `python app.py --gui`, or `python -m pdf_ai_batch.gui`) opens the
Tkinter window. Opening it **never** launches Illustrator: Illustrator is only
contacted for an explicit **HEALTH CHECK** or a **RUN**.

## Architecture

```
gui/main_window.py   the window: 4 tabs, the event pump, close safety, run_task()
gui/context.py       GuiContext - what a tab may ask the window for
gui/controller.py    ALL GUI logic - NO Tk, NO COM, NO state.json writes
gui/tasks.py         worker thread + EventBus + QueueLogHandler (NO Tk imports)
gui/project_tab.py   PROJECT: folders, new/open JOB, add PDF/templates
gui/pdf_tab.py       PDF: list, page count (pdf_info), size, config status
gui/mapping_tab.py   MAPPING: page table, template chooser, validation panel
gui/run_tab.py       RUN / LOG: run/continue/retry, progress, live log
```

```
GUI widget -> GuiContext -> AppController -> core/*  -> CONFIG/config.json
                                          -> core/queue.py + core/state.py
                                          -> adapters/illustrator.py (COM, run/health only)
```

Rules (enforced by `tests/test_gui_controller.py::test_gui_python_sources_never_touch_com_tk_or_state_files_directly`):

* no `win32com`/`pythoncom` anywhere under `gui/` - only `adapters/illustrator.py` has COM
* `controller.py` and `tasks.py` do not import Tk (so the whole GUI logic is unit testable)
* no direct `state.json` writes: plan edits go to `CONFIG/config.json`, and
  `BatchQueue.build_queue()`/`reset_item()/retry_*()` own every state transition
* `cleanup.jsx` and the Python<->JSX contract are untouched by the GUI

## Threading

```
Tk main thread                          worker thread
---------------                         -------------
widgets + _pump() every 120 ms  <-----  EventBus (queue.Queue)
run_task(label, task)  --------------->  TaskRunner thread: BatchQueue + adapter
```

* `TaskRunner.start()` runs `task(progress)`; the `progress` callback pushes
  `EVENT_PROGRESS` for every queue item, so no second GUI-owned counter exists.
* `_pump()` is the only place widgets change: log lines, progress, mapping refresh.
* one task at a time; while a task runs, the mutating buttons in PROJECT, PDF and
  MAPPING are disabled (the worker owns `state.json`), only `REFRESH STATUS` stays live.
* the log view is a **view**: `JOB/LOG/app.log` and `JOB/LOG/batch_<timestamp>.log`
  remain canonical (the `QueueLogHandler` only mirrors records into the widget).

## Tabs

| Tab | What it does | Core it uses |
|---|---|---|
| PROJECT | NEW PROJECT / OPEN PROJECT / ADD PDF / ADD TEMPLATES / OPEN JOB FOLDER; shows the six JOB folders with their state | `core/project.py` |
| PDF | the JOB's **document list**: `USE / PDF / PAGES / CONFIG STATUS / QUEUE STATUS` plus IZMANTOT (makes it the active document), IESLĒGT/IZSLĒGT (USE), RECONCILE, PIEVIENOT PDF..., ATJAUNOT; details: path, page count, method, size, config status, queue status, document status | `core/pdf_info.py`, `core/pagejob.py`, `core/config.py`, `core/queue.py` |
| MAPPING | the plan of the **active document** (`PDF: manualis.pdf | Lapas: 42`) as a **visual page browser**: thumbnails with the page state, one large preview (FIT / 100% / + / -), the page info block and the page actions; below that the `USE / PAGE / TEMPLATE / LAYER / OUTPUT / STATUS` table with SELECT ALL/NONE, ENABLE/DISABLE SELECTED, RESET SELECTED, VALIDATE, AUTO ASSIGN TEMPLATES, ASSIGN TEMPLATE, USE DEFAULT TEMPLATE, RECONCILE PDF, double click = change the template of that row | `core/pagejob.py`, `core/template_mapper.py`, `core/config.py`, `core/naming.py`, `core/queue.py`, `core/validation.py`, `preview/*` |
| RUN / LOG | RUN SELECTED, RUN CURRENT PDF, RUN ALL ENABLED PDFs, CONTINUE PROJECT, RETRY PROJECT ERRORS, RETRY INTERRUPTED, REFRESH STATUS, HEALTH CHECK, overwrite checkbox, project + document progress (`PDFs: 2 | Lapas kopā: 7`, `appendix.pdf - lapa 004 / 004`, one line per document) and the live log | `core/queue.py`, `core/state.py`, `adapters/illustrator.py` |

### Documents (milestone 4)

* A JOB may hold several PDFs. The **active document** is the one MAPPING shows and
  edits; selecting it in the PDF tab is enough (`select_document`). Plan edits
  always carry the other documents over untouched, so editing one PDF can never
  drop another PDF's plan.
* `USE` is the document switch in `config.json` (`documents[i].enabled`). A disabled
  document keeps its plan and its queue states; the queue simply disables its items.
* `CONFIG STATUS` shows `nav config.json (auto)`, `config.json: N lapas, iespējotas M`
  or `CONFIG STALE: stored 42, current 44` / `PDF nav atrasts - plāns saglabāts`.
* `QUEUE STATUS` shows the current states of that document (`WAITING 3`,
  `DONE 3 | WAITING 1 | ERROR 1`, ...) or `nav rindā`.
* **RECONCILE** (PDF tab and MAPPING tab) asks for confirmation and then reaches
  `core/pagejob.apply_reconcile`: pages that still exist keep template/output/state,
  new pages become `WAITING` with the defaults, removed pages are archived in
  `removed_pages` (never deleted, restored if the page comes back). Nothing in the
  pipeline ever rewrites a mapping on its own.
* A deleted PDF shows `MISSING PDF` (also when it only survives in `state.json`),
  keeps every state and becomes runnable again when the file is back.

* The template chooser lists the files already inside `JOB/TEMPLATE` (natural sort)
  and offers a `PĀRLŪKOT...` button that **copies** an outside file into `JOB/TEMPLATE`
  first, so the operator never has to browse the file system repeatedly.
* `MASTER_AI_TEMPLATE.ai` / `MASTER_TEMPLATE.ai` never enter the numbered automatic
  mapping (see `core/template_mapper.py`); pages beyond the template pool get the
  default template.
* Page numbers are shown zero padded (`001`) via `MappingRow.page_label`, the same
  width the naming rules use.
* STATUS colours are a hint only - the state text is always shown.

### Visual page browser (milestone 5)

The MAPPING tab starts with a preview pane and then the table:

```text
+------------------------------------------------------------------+
| PDF: manualis.pdf | Lapas: 42                       OK (config)  |
+------------------------------+-----------------------------------+
| Lapas (thumbnail)            | Priekšskatījums                   |
|  [001]  [002]  [003]         |            PAGE IMAGE             |
|  WAITING  DONE  ERROR        |      FIT | 100% | + | - | fit      |
+------------------------------+-----------------------------------+
| PDF / Lapa / Izmērs / Template / Layer / Output / Statuss        |
| error or output detail line                                      |
| ASSIGN TEMPLATE TO SELECTED | USE DEFAULT TEMPLATE | ENABLE ...  |
+------------------------------------------------------------------+
| MAPPING TABLE  USE PAGE TEMPLATE LAYER OUTPUT STATUS              |
+------------------------------------------------------------------+
```

* **Every tile prints its page number and its state** (`WAITING`, `RUNNING`, `DONE`,
  `ERROR`, `SKIPPED`, `INTERRUPTED`, `PREVIEW ERROR`); the frame colour is an extra,
  never the only signal.
* **Click** a tile = select that page, **Ctrl+click** = add/remove, **Shift+click** =
  range, mouse wheel scrolls. Selection is applied to the MAPPING Treeview (the
  single source of truth), so the detail line, the row highlight and the preview all
  follow, and the reverse holds too: selecting a row highlights the tile and re-renders
  the preview.
* **Page info** shows PDF, `page / total`, size in mm (from PyMuPDF), template,
  layer, output and state, plus the attempts counter; for an `ERROR` page it also
  shows `error_type: error_message` and for an `INTERRUPTED` page the reason. A DONE
  page whose output vanished says `[nav atrasts, lai gan DONE]`.
* **Actions** (`ASSIGN TEMPLATE TO SELECTED`, `USE DEFAULT TEMPLATE`, `ENABLE`,
  `DISABLE`, `RESET`) call exactly the same controller/core functions as the table
  buttons. **OPEN OUTPUT** opens the finished AI with the Windows default
  (`os.startfile`), only when the page is `DONE` and the file exists - the AI is never
  modified.
* **Rendering happens in Python** (`pdf_ai_batch/preview`, PyMuPDF) on a worker
  thread; results travel through the event bus (`tasks.EVENT_PREVIEW`) and only the
  `_pump()` in the Tk thread touches widgets. Thumbnails are requested for the pages
  around the focus and for the visible area, so a 200 page PDF opens instantly and
  fills in progressively; switching documents bumps a generation token that drops
  stale work instead of painting the wrong PDF.
* **Cache**: `JOB/.cache/preview` (disposable, gitignored, safe to delete). The file
  name carries the PDF path + mtime + size + page + render size, so a modified PDF
  can never show an old thumbnail.
* **While a batch runs** the rows and tiles are re-read every 0.5 s
  (`LIVE_STATE_REFRESH_SECONDS`), so the page being processed shows `RUNNING` and not
  just a jump from WAITING to DONE.
* A page that cannot be rendered shows `PREVIEW ERROR` with the reason; the table,
  the plan and `state.json` stay untouched - a rendering problem is never a
  processing problem.

### Bulk mapping + presets (milestone 6)

The MAPPING tab no longer needs a page by page click for a 100-300 page magazine. The
action bar has three rows; the second and third are the bulk tools.

| Button | What it does | Core call |
| --- | --- | --- |
| `ASSIGN TO SELECTED` | template (via the chooser) for the selected rows | `mapping_rules.assign_template` |
| `ASSIGN TO RANGE` | dialog: **Lapas** (`1`, `1-5`, `1,3,5`, `1-5,8,10-14`, `*`), **Template** (or `(noklusētais)`), **Layer**, **Iespējot** (nemainīt / iespējot / izslēgt) | `parse_pages` + `assign_template` (+ `set_enabled`) |
| `USE DEFAULT` | back to `defaults.template` (usually the MASTER) | `use_default_template` |
| `CLEAR OVERRIDE` | back to the default template **and** the default layer | `clear_override` |
| `AUTO MAP BY NUMBER` | page N <- the template numbered N (`001_cover.ai` -> page 1) | `auto_map_by_number` |
| `COPY MAPPING` | copies template + layer of the selected pages | `copy_mapping` |
| `PASTE MAPPING` | pastes onto the selected pages (or onto the same pages when nothing is selected) | `paste_mapping` |
| `SAVE PRESET` | asks for a name and writes `JOB/CONFIG/presets/<name>.json` | `preset_from_mapping` + `save_preset` |
| `LOAD / APPLY PRESET` | lists the presets, shows the **core preview** (pages that would change, conflicts) and applies it | `preset_preview` + `apply_preset` |
| `AUTO ASSIGN TEMPLATES` | the old positional mapping (natural order, MASTER excluded) | `template_mapper.build_page_plan` |
| `RECONCILE PDF` | after the PDF page count changed (CONFIG STALE) | `core/queue.reconcile_document` |

Rules that come straight from the core:

* **The range dialog validates with the core parser** and shows its Latvian message
  inline (`Lapas numurs sākas no 1: '0'`, `Lapas ārpus dokumenta (1-36): 99`); the GUI
  has no parser of its own.
* **Numbered mapping never guesses.** MASTER templates are excluded; a number used by
  two templates is reported (`Neskaidri numuri: Numurs 2 ir vairākiem template: ...`)
  and those pages keep whatever they had.
* **The clipboard is plan data only** - no queue state, no attempts, no run ids, no
  errors, no outputs. It works across documents (copy from `manualis.pdf`, paste into
  `appendix.pdf`, with an offset if needed) and never writes past the last page; it
  reports what it skipped instead (`izlaistas`, `neizmantotas`, `bez vietas`).
* **A preset is mapping intent.** Entries are ranges
  (`{"pages": "6-20", "template": "MASTER_AI_TEMPLATE.ai", "layer": "ARTWORK"}`), the
  schema version is 1 and runtime keys are rejected, so a preset can never carry state.
  Applying one shows the conflicts first (pages beyond the document, missing template
  files) and only writes the pages the document really has; "Aizstāt arī pārējās lapas"
  is the destructive variant that also resets the pages the preset does not mention.
* **Bulk changes are reversible in milestone 8, not by hand**: every plan change goes
  through one funnel (`_mutate_config` -> `_before_mutation` -> validate -> atomic save
  -> queue rebuild), which is where the snapshot/undo feature will hook in.

Layout note: the mapping table keeps the selection as the single source of truth, so a
thumbnail click, a range action and the preview buttons all act on the same rows. While
a batch runs, all bulk buttons are disabled (`set_busy`).

## Overwrite

`RESET SELECTED` sets a page back to `WAITING`, but an existing `AI_OUT/...ai` would
make the copy step report `SKIP` (`overwrite=False`). Tick **Pārrakstīt esošos AI
(overwrite)** on the RUN tab to re-process such pages (the CLI's `--overwrite`).

## Validation

`VALIDATE` and every RUN start call `AppController.validate()`, which is only a
composition of existing core checks:

* `core/validation.preflight()` - JOB folders, PDF, template, output name/folder,
  `worker.jsx`, `cleanup.jsx`, runtime writability, Illustrator (only when known)
* `core/validation.check_file()` - one line per distinct template file
* `core/config.validate_config()` - duplicate outputs, page ranges, layer, extensions

The Illustrator check is skipped until an explicit HEALTH CHECK ran, so validation
never launches Illustrator. A run with hard failures is refused and the problems are
shown. Illustrator COM problems are reported the same way (`check_illustrator()`).

## Close / crash safety

Closing the window while a task runs or a page is `RUNNING` asks for confirmation and
explains that the page will stay `RUNNING` and become `INTERRUPTED` on the next start.
Illustrator is never killed: startup recovery (`BatchQueue.open` -> `state.recover_running`)
stays authoritative, and `CONTINUE` finishes the recovered pages. Recovery also deletes
a partial output AI left by the killed attempt, so the retry really re-processes the
page instead of reporting `SKIP`.

## Not in this milestone

No drag/drop reordering, no database/SQLite, no multiprocessing, no second
Illustrator instance, no parallel Illustrator work, no UXP, no template
"intelligence", no cloud sync. (Multiple PDFs per JOB arrived in milestone 4 and
the visual page browser in milestone 5; each document is still processed strictly
one page at a time.)

Deliberately still absent from the preview: **no OCR, no page text extraction, no
image/AI analysis, no content based template choice** - the preview shows pages, it
never interprets them.

## Acceptance evidence (real Illustrator, 2026-09-23)

### Milestone 6 - bulk mapping, presets and a 36 page project

Script `temp/run_gui_acceptance_m6.py`, evidence `temp/gui_acceptance_m6.txt`,
screenshots `temp/gui_m6_a_assigned.png`, `gui_m6_b_preset.png`, `gui_m6_c_outputs.png`.
JOB: `temp/BULK_JOB` - `magazine.pdf` (36 pages) with `001_cover.ai`, `002_intro.ai`,
`021_separator.ai` and the real MASTER. **PASS (16 steps)**:

| Step | Evidence |
| --- | --- |
| range dialog (real `RangeAssignDialog`) | `'0'` -> `Lapas numurs sākas no 1: '0'`, `'99'` -> `Lapas ārpus dokumenta (1-36): 99`, `'2-5'` -> `pages=[2, 3, 4, 5] template=002_intro.ai` |
| ASSIGN TO RANGE | page 1 -> `001_cover.ai`; 2-5 -> `002_intro.ai` x4; `CLEAR OVERRIDE` 6-20 -> all `(noklusētais)`; page 21 -> `021_separator.ai`, layer `SEPARATOR` |
| COPY / PASTE MAPPING | `4 lapas no magazine.pdf (2-5) | 002_intro.ai` -> pasted onto 22-25, source range untouched |
| SAVE PRESET | 6 rules: `1`, `2-5`, `6-20`, `21`, `22-25`, `26-36` - no runtime key in the file |
| AUTO MAP BY NUMBER | 1 -> `001_cover.ai`, 2 -> `002_intro.ai`, 21 -> `021_separator.ai`, `MASTER nav izmantots=True` |
| reset + APPLY PRESET | all 36 pages reset to the default, preset preview `Mainīsies 10 lapas (pirmās: 1, 2, 3, 4, 5, 21, 22, 23, 24, 25)` / `Konfliktu nav.`, then `plāns atjaunots identiski: True` |
| VALIDATE | 30 checks, 0 errors |
| 5 real pages | `RUN SELECTED [1, 2, 6, 21, 22]` -> all `DONE` |
| which template produced which output | page 1 `001_cover.ai` 520x720 `COVER-TEMPLATE SOURCE PAGE 1`; page 2 `002_intro.ai` 460x620 `INTRO-TEMPLATE SOURCE PAGE 2`; page 6 `MASTER_AI_TEMPLATE.ai` 411x397 `SOURCE PAGE 6`; page 21 `021_separator.ai` 460x520 `SEP-TEMPLATE SOURCE PAGE 21`; page 22 (the **pasted** range) `002_intro.ai` 460x620 `INTRO-TEMPLATE SOURCE PAGE 22` |
| safety | MASTER template SHA256 unchanged, `state.json` untouched by the mapping work, `Illustrator atvērti dokumenti: 0` |

The output proof works because the templates are PDF compatible `.ai` files whose
marker text and artboard survive the worker: PyMuPDF can read the marker of the
finished output, so "page 22 used the INTRO template because it was pasted there" is
verified from the product, not from the plan.

### Milestone 5 - the visual page browser

`temp/run_gui_acceptance_m5.py` runs the 20 milestone 5 steps against the same real
JOB (`temp/MULTI_JOB`, `manualis.pdf` 3 pages + `appendix.pdf` 3 pages, real
Illustrator): thumbnails appear, clicking page 1/3 switches the preview and the
mapping row, a Ctrl+click selection gets `section_blue.ai`, switching to
`appendix.pdf` and back shows the other thumbnails and then the cached ones,
running 3 selected pages shows `WAITING -> RUNNING -> DONE` on the tiles, a locked
output produces `ERROR` (shown on the tile with its detail and attempts), the retry
returns to `DONE`, reopening the GUI shows the same states (tile text ==
state.json) and Illustrator ends with 0 open documents. Output:
`temp/gui_acceptance_m5.txt`, screenshots `temp/gui_m5_*.png`.

Performance (`temp/preview_perf.py`, 160 page PDF): see `temp/preview_perf_m5.txt`.

### Milestone 4 - two PDFs in one JOB

`temp/run_gui_acceptance_m4.py` builds a real JOB (`temp/MULTI_JOB`: `manualis.pdf`
3 pages + `appendix.pdf` 3 pages, both extracted from the 14 page demo PDF, real
`MASTER_AI_TEMPLATE.ai`) and drives the real widgets. Transcript:
`temp/gui_acceptance_m4.txt`, screenshots `temp/gui_m4_pdf.png`,
`temp/gui_m4_run.png`, `temp/gui_m4_reopen.png`.

```
2 PDF      appendix.pdf   lapas=3  nav config.json (auto)   | WAITING 3
2 PDF      manualis.pdf   lapas=3  nav config.json (auto)   | WAITING 3
3 MAPPING  PDF: manualis.pdf | Lapas: 3 | rindas=3 ; PDF: appendix.pdf | Lapas: 3 | rindas=3
   dokumentu secība (config.json): ['manualis.pdf', 'appendix.pdf']
4 RUN CURRENT PDF live: {manualis#1..3: 'WAITING->RUNNING->DONE'} | appendix {1,2,3: 'WAITING'}
5 PDF      appendix.pdf: WAITING 3
6 RUN ALL ENABLED PDFs live: {appendix#1..3: 'WAITING->RUNNING->DONE'} | manualis DONE 3
7 PDF      appendix.pdf: lapas=4 (stored 3) | CONFIG STALE (stored: 3, current: 4)   (config.json nav mainīts)
8 RECONCILE -> OK (config) | 4 lapas | WAITING 1 | DONE 3      (jaunā lapa 004 = WAITING)
9 ERROR    manualis 002 -> ERROR (output aizņemts)  live={'manualis#2': 'WAITING->ERROR',
                                                        'appendix#4': 'WAITING->RUNNING->DONE'}
10 RETRY PROJECT ERRORS live: {'manualis#2': 'ERROR->RUNNING'} -> manualis 002 DONE
11 close + reopen: {"manualis.pdf": 1..3 DONE, "appendix.pdf": 1..4 DONE} | output faili 7/7
12 MASTER template nemainīts (SHA256 7214386ADC8FCFA1...)
13 Illustrator atvērti dokumenti: 0
=== MILESTONE 4 ACCEPTANCE OK ===
```

### Milestone 3 - one PDF, twelve tabs-steps

`temp/run_gui_acceptance.py` drives the **real widgets** through their handlers
(dialogs stubbed, no mouse) against the real `temp/QUEUE_JOB` (14 page PDF,
`AI_OUT` outputs from milestone 2). Full transcript: `temp/gui_acceptance.txt`,
the GUI log view: `temp/gui_acceptance_log.txt`.

```
1 PROJECT  on_open_project -> ...\temp\QUEUE_JOB      (folders PDF/TEMPLATE/CONFIG/AI_OUT/LOG/ERROR)
2 PDF      mans_fails.pdf: lapas=14 (PyMuPDF) izmērs=35.7 MB (37464514 B)
3 MAPPING  rindas=14 | pirmā: ('[x]', '001', 'MASTER_AI_TEMPLATE.ai', 'ARTWORK', 'mans_fails__001.ai', 'DONE')
visas 14 lapas: DONE  (restored from state.json, written by the CLI in milestone 2)
4 RESET SELECTED -> {1: 'WAITING', 2: 'WAITING', 3: 'WAITING'} (overwrite=True)
           lapa 003 template mainīts uz: 003_pagina.ai   (chooser: ASSIGN TEMPLATE on the selection)
5 VALIDATE rezultāts: 24 pārbaudes, kļūdas=0, brīdinājumi=0   can_run=True
6 RUN SELECTED live (WAITING -> RUNNING -> DONE):
           {1: 'WAITING->RUNNING->DONE', 2: 'WAITING->RUNNING->DONE', 3: 'WAITING->RUNNING->DONE'}
           kopsavilkums: DONE=14 ERROR=0 SKIPPED=0 | Page 014 / 014 | bar=1000/1000
  HEALTH CHECK 1: Illustrator pieejams
7 ERROR    lapa 003 -> ERROR  (output fails ir aizņemts)
           detaļas: OUTPUT_PREP_FAILED: nevar izdzēst esošo output: [WinError 32] ...
           RETRY ERRORS live: {3: 'ERROR->WAITING->RUNNING->DONE'} -> lapa 003 DONE
8 close + reopen: jauns logs {1..14: 'DONE'}  (states restored from state.json)
9 Illustrator atvērti dokumenti: 0
=== MILESTONE 3 ACCEPTANCE OK ===
```

The forced ERROR is a real one: the output AI is held open, so
`prepare_output_copy` cannot replace it (`OUTPUT_PREP_FAILED`). Note that a *missing*
per page template never reaches the worker - `VALIDATE` (and every RUN) refuses to
start and shows "Template 003_pagina.ai: nav atrasts" instead.

### Bugs the acceptance run found (all fixed, each with a regression test)

| Bug | Effect | Fix |
| --- | --- | --- |
| A table refresh dropped the row selection | `RESET SELECTED` then `RUN SELECTED` reported "no pages selected" | `MappingTab.refresh()` re-selects the job ids that are still present |
| Stale COM object trusted | after Illustrator was closed/restarted every call failed with "Object is not connected to server" | `ensure_app()`/`health_check()`/`invoke_worker()` validate the connection with `_is_alive()` and re-attach |
| No COM apartment in worker threads | a task in a *new* thread failed every COM call with "CoInitialize has not been called" (the GUI creates a thread per task) | `_prepare_thread()` calls `CoInitialize` once per thread and a cached app owned by another thread is dropped |
| A recovered INTERRUPTED page could be skipped | the killed attempt's partial output made the retry report `SKIP` | `recover_running()` removes that output (mtime compared with the attempt start) |
| No way to re-run a page whose output exists | `RESET` + RUN reported `SKIP` | RUN tab checkbox "Pārrakstīt esošos AI (overwrite)" (the CLI's `--overwrite`) |
| Stale detail line in MAPPING | showed "Nav atvērts neviens JOB" after the JOB was opened | `refresh()` re-renders the detail from the current selection |
| `after(...)` pump outlived the window | "invalid command name ..._pump" in the console | `on_close()` cancels the pending callback |
| (M4) PDF tab overrode a programmatic document switch | selecting a document in the controller (reconcile, acceptance, a deleted PDF) snapped back to the tree's old selection, so MAPPING showed the wrong PDF | `PdfTab.refresh()` renders the controller's active document and only falls back to its own selection when that document is gone |
| (M5) Thumbnails vanished after a window resize | `_draw_tiles()` rebuilt the canvas, and because the page was still in `_requested` no new render came - the browser stayed empty | `_repaint_thumbnails()` re-adds already rendered tiles from the decoded image cache |
| (M5) `_ensure_visible` scrolled to the very bottom | it passed a tile-relative fraction to `yview_moveto` (page 1: `275 / 271` -> 1.0), so the tile hit test then missed every click (`canvasy(550)` became 1354) | the fraction is now `target / content_height`, and an unmapped canvas is left alone |
| (M5) The large preview was re-requested on every refresh | each progress event (and every zoom refresh) re-rendered the preview pane and the zoom label showed the renderer's fit scale (`60%` instead of `fit`) | the request is keyed on `(page, long_side, zoom)`, and `_zoom` only ever holds the operator's choice |
| (M5) Tiles never showed `RUNNING` | a progress event only arrives after a page finished, so a thumbnail jumped `WAITING -> DONE` | `MainWindow._maybe_refresh_live_states()` re-reads the rows while a batch runs (0.5 s), found by the real acceptance run |

| (M6) `_handle` swallowed the core report | the ambiguity problems of `AUTO MAP BY NUMBER` were invisible (the handler could not read the report) | `MappingTab._handle` returns the action's result, so the numbered mapping reports its problems |
| (M6, not a product bug) A milestone 6 acceptance run died mid-flight with `invalid command name` / `application has been destroyed` | on CPython 3.14 a `tkinter` variable collected by the render worker runs `Variable.__del__` outside the main loop (`RuntimeError: main thread is not in main loop`), and that Tcl call can invalidate Tk widgets; the same failure class makes a subset of the pytest GUI files crash at the milestone 5 baseline `dac46e8` too | the acceptance driver keeps its dialog objects alive until the window closes (`keep()`); the product code never creates Tk objects on a worker thread, so nothing changed there |

### Screenshots

`temp/grab_gui.py [mapping|run|project|pdf]` captures a tab with `PrintWindow`
(no focus needed):

* `temp/gui_mapping.png` - MAPPING: 14 rows (`[x] / 007 / MASTER_AI_TEMPLATE.ai /
  ARTWORK / mans_fails__007.ai / DONE`), page 003 with its own template, the
  validation panel with `[OK]` lines and the status bar.
* `temp/gui_run.png` - RUN / LOG: `Page 014 / 014`, the full progress bar, the
  DONE/WAITING/RUNNING/ERROR/SKIPPED/INTERRUPTED counts, the overwrite checkbox and
  the live log panel.
* `temp/gui_project.png` - PROJECT: JOB path, the six folders with "ir"/"NAV" and
  their absolute paths, NEW PROJECT / OPEN PROJECT / ADD PDF / ADD TEMPLATES /
  OPEN JOB FOLDER, and the PDF/template counters.
* `temp/gui_pdf.png` - PDF: the JOB/PDF list, `mans_fails.pdf` selected, page count
  `14`, method `PyMuPDF`, size `35.7 MB (37464514 B)` and the config status line.
* `temp/gui_m6_a_assigned.png` - MAPPING after the range assignments, the copy/paste and
  the three bulk button rows (36 page plan).
* `temp/gui_m6_b_preset.png` - MAPPING after the preset was reapplied (cover 1, intro
  2-5 and 22-25, MASTER 6-20, separator 21).
* `temp/gui_m6_c_outputs.png` - MAPPING after the run: the five processed pages `DONE`.


