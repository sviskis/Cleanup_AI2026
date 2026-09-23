# ARCHITECTURE - Python orchestrator + Illustrator JSX worker

> **Repository:** `sviskis/Cleanup_AI2026` · **Local folder:** `Cleanup_AI2026` ·
> **Display name:** Cleanup AI 2026

Architecture **as of v0.2.0**: the production pipeline is Python, and Illustrator
runs as a one-page worker.

The earlier phase (the single file JSX application) still lives in the repository
as the **frozen baseline** and as the source of the cleanup engine:
`docs/ARCHITECTURE.md` describes it, `legacy/current_working_v10.jsx` is its frozen
snapshot, and `archive/original/` holds the predecessors.

```text
  +---------------------------------------------------------------------------------+
  | PYTHON  (pdf_ai_batch/)                                                          |
  |                                                                                  |
  |  app.py / run_one.py     CLI entry points (GUI is the next milestone)            |
  |                                                                                  |
  |  core/project.py         JOB folder model, creates missing folders               |
  |  core/pdf_info.py        PDF discovery, natural sort, PAGE COUNT (PyMuPDF/pypdf) |
  |  core/template_mapper.py template discovery, natural sort, page -> template      |
  |  core/naming.py          output names, job ids, collisions                       |
  |  core/config.py          config.json read/validate/write                         |
  |  core/contract.py        the JSON contract (request/result), stats mapping       |
  |  core/validation.py      preflight checks                                        |
  |  core/preflight.py       production preflight: READY / NOT READY for a whole JOB  |
  |  core/report.py          immutable job reports (JOB/LOG/reports, JSON + TXT)      |
  |  core/jsonio.py          atomic read/write, wait for a matching result           |
  |  core/mapping_rules.py   bulk mapping: ranges, numbered auto map, clipboard,      |
  |                          presets (the ONLY place that decides mapping)           |
  |  logging_setup.py        LOG/app.log + LOG/batch_<ts>.log, UTF-8 console         |
  +-------------------------------+--------------------------------------------------+
                                  |  writes runtime/current_job.json   (atomic rename)
                                  |  reads  runtime/current_result.json (job_id+run_id)
                                  v
  +----------------------------------------------------------------------------------+
  | adapters/illustrator.py   - the ONLY module that talks to COM (pywin32)          |
  |   attach to running Illustrator -> else launch -> DoJavaScriptFile(worker.jsx)   |
  +-------------------------------+--------------------------------------------------+
                                  |  file based handoff, no COM arguments
                                  v
  +----------------------------------------------------------------------------------+
  | ILLUSTRATOR  (jsx/)                                                              |
  |   worker.jsx    one page per invocation: read request, validate, orchestrate,    |
  |                 write result JSON (JSON polyfill in json2.js)                    |
  |   cleanup.jsx   THE canonical document engine:                                   |
  |                   cleanup v6 (appearance safe) + document helpers (open page,    |
  |                   safe close, template copy / .ait -> .ai, ARTWORK layer,        |
  |                   artwork duplication) + stats contract mapping                  |
  +----------------------------------------------------------------------------------+
```

## 1. Division of ownership

| Python owns | Illustrator (JSX) owns |
| --- | --- |
| GUI, project creation, JOB folder structure | opening a PDF page |
| PDF discovery, **page count** (PyMuPDF -> pypdf) | all Illustrator DOM access |
| template discovery + natural sorting | unlock, safe ungroup |
| page -> template mapping, default template | clipping mask handling |
| preview, config JSON, validation | crop / perimeter cleanup |
| batch queue, job state, progress, resume | Illustrator object inspection |
| error handling, logging | template document handling |
| output file names, `.ai` template copy, overwrite decisions | ARTWORK layer, artwork duplication, save AI, close documents |
| orchestrating one job per page | returning processing statistics |

Illustrator is **never** asked how many pages a PDF has, and Python never touches
the Illustrator DOM.

The **GUI** (`pdf_ai_batch/gui/`) is a presentation layer on top of the same core:

```
tk widget  ->  GuiContext  ->  AppController  ->  core/*  (+ adapters/illustrator.py
                                                 only for a health check or a run)
```

* no COM, no JSX and no direct `state.json`/`config.json` writes in `gui/`
* long work in a `TaskRunner` worker thread, UI updates through `queue.Queue` +
  `root.after` (widgets are only touched in `_pump()`)
* plan edits go to `CONFIG/config.json` and are merged into `state.json` by
  `BatchQueue.build_queue`; RESET/RETRY/CONTINUE are core queue transitions
* progress and the status column derive from `state.json`, never from a GUI counter
* opening the window does not launch Illustrator (the adapter is lazy; the
  Illustrator check only appears in `validate()` after an explicit health check)

Details: [docs/GUI.md](docs/GUI.md).

## 2. The JSON contract

Two files in `runtime/` (both written atomically: temp file + rename):

**Request** `runtime/current_job.json` - written by Python:

```json
{
  "schema": "pdf_ai_batch/job_request/v1",
  "run_id": "20260923-164233-1055d1",
  "job_id": "calendar_p003",
  "pdf": "C:/JOB/PDF/calendar.pdf",
  "page": 3,
  "template": "C:/JOB/TEMPLATE/MASTER_AI_TEMPLATE.ai",
  "template_mode": "copy",
  "output": "C:/JOB/AI_OUT/calendar__003.ai",
  "layer": "ARTWORK",
  "clear_layer": true,
  "overwrite": false,
  "cleanup": { "releaseSafeVectorMasks": true, "deleteCropMarks": true, "ungroupPasses": 40 }
}
```

**Result** `runtime/current_result.json` - written by `jsx/worker.jsx`:

```json
{
  "schema": "pdf_ai_batch/job_result/v1",
  "run_id": "20260923-164233-1055d1",
  "job_id": "calendar_p003",
  "status": "OK",
  "page": 3,
  "output": "C:/JOB/AI_OUT/calendar__003.ai",
  "objects_copied": 241,
  "stats": {
    "safe_groups_ungrouped": 19, "risky_groups_preserved": 0,
    "vector_masks_released": 3, "risky_masks_preserved": 1,
    "mask_paths_deleted": 1, "crop_perimeters_deleted": 6,
    "short_crop_marks_deleted": 2, "crop_objects_deleted": 8
  }
}
```

`status` is `OK`, `ERROR` or `SKIP`. On failure the result carries `message`,
`error_type`, `error_file` and `error_line` instead of statistics.

**Paths on the wire.** `pdf`, `template` and `output` are always **absolute** and
use forward slashes; Python resolves them (`core.contract.contract_path` ->
`Path.resolve().as_posix()`) before serialising. The worker runs inside
Illustrator with its own current working directory, so a relative path would point
somewhere else and `File(request.pdf).exists` would be false. The JSX side never
resolves or joins paths: it rejects a path that is not absolute
(`isAbsolutePath`) and then checks existence (`pdf`, `template`, and `output`
when `template_mode == "copy"`).

**Handshake rules** (implemented in `core/jsonio.wait_for_json` and the adapter):

1. Python deletes a stale `current_result.json` before every job.
2. Python writes the request through `*.tmp` + `os.replace` (atomic rename).
3. Python runs `worker.jsx` - no business data travels through COM arguments.
4. Python polls for a result and accepts it **only** when `job_id` **and**
   `run_id` match; anything else is logged as rejected and ignored.
5. The wait has a timeout (default 900 s) and returns a clean `ERROR` outcome
   together with the tail of `runtime/worker.log` when nothing valid arrives.

`template_mode`:

* `copy` - Python already copied the template into `AI_OUT` (normal `.ai` path;
  Python owns the overwrite decision).
* `saveas` - Illustrator opens the template and saves **as** the output, which is
  required for real `.ait` templates (format conversion by Illustrator).

Fixtures `tests/fixtures/{request,result}_sample.json` are verified from **both**
sides: `pdf_ai_batch/tests/test_contract.py` (Python) and
`tests/jscript/test_json_contract.js` (JScript / ExtendScript).

## 3. Queue and state

Milestone 2 added a persistent queue between "planning" and "running one page".
The full description (state machine, schema, CLI, evidence) is
[`docs/QUEUE_STATE.md`](docs/QUEUE_STATE.md); the short version:

* `JOB/CONFIG/state.json` holds one item per page with the paths, the layer, the
  mode and the run history (`state`, `attempts`, `last_run_id`, `error_*`,
  timestamps). It is written atomically before **and** after every item.
* States: `WAITING`, `RUNNING`, `DONE`, `ERROR`, `SKIPPED`, `INTERRUPTED`. A stale
  `RUNNING` item is recovered as `INTERRUPTED` at startup - never `DONE`, never
  stuck.
* `DONE` requires the worker result `OK` **and** an existing output
  (`core/pagejob.output_ready`); `OK` without output is `ERROR`.
* A page level failure never stops the batch; only an adapter/COM failure aborts the
  pass and leaves the remaining items `WAITING`.
* `core/queue.py` (`BatchQueue`) is adapter agnostic - it calls the proven
  `run_job()` of `adapters/illustrator.py` and imports no COM. `batch.py` is the
  operator CLI (`--run-all`, `--continue`, `--retry-errors`, `--status`, ...).
* `core/pagejob.py` is the ONE place where a page becomes
  template/output/layer/mode, shared by `run_one` and the queue, so a single page
  test and a batch page cannot drift apart.

## 3b. Multi PDF projects (milestone 4)

One JOB holds several PDFs; each one is planned, queued and reported separately.

* **Identity**: `pdf_id` (stable, derived from the file name, never `hash()`) plus
  the page. `job_id = <pdf_id>_p<page:03d>` (`manualis_p001`, `appendix_p001`), so
  the same page number in two documents never collides. A bare page number in a
  multi PDF JOB is ambiguous and is reported as such instead of guessing.
* **Config**: `config.json` version 2 = `{version: 2, defaults, documents[]}` with
  one block per PDF (`pdf`, `page_count`, `enabled`, `pages[]`, `removed_pages[]`).
  A version 1 file is migrated **in memory** by `load_config` (the existing JOB
  keeps working, byte identical, until a plan edit is saved).
* **Order**: `documents[]` order first, then page number ascending. New PDFs appear
  after the configured ones, in natural sort order.
* **Drift**: a PDF whose page count no longer matches the stored one is
  `CONFIG STALE (stored: 42, current: 44)`; the stored plan is used and nothing is
  rewritten. RECONCILE (`core/pagejob.apply_reconcile`) is explicit, keeps the
  settings and the states of the pages that still exist, makes new pages `WAITING`
  and archives removed pages in `removed_pages` (restored when the page returns).
* **Missing PDF**: `MISSING PDF`; the plan and every queue state of that document
  are kept, its items are disabled so nothing can be run from it, and it becomes
  runnable again as soon as the file is back.
* **Output collisions**: names stay PDF aware (`manualis__001.ai`); the config
  validator AND `BatchQueue.duplicate_outputs()` refuse a plan in which two
  documents would write the same AI. A colliding pass aborts before the first
  Illustrator call.
* **Failure isolation** (unchanged): a page level failure never stops the batch,
  not even across documents; only a global adapter/COM failure aborts the pass.

## 3c. PDF preview (milestone 5)

The page plan is visual: PDF pages are rendered as thumbnails and as one large
preview, straight into the Tk GUI. **Python renders, the GUI only draws.**

```text
JOB/PDF/*.pdf
   |
   v  pdf_ai_batch/preview/renderer.py      PyMuPDF, one page at a time
PNG bytes
   |
   v  gui/preview_loader.py                 worker thread + request generations
   |                                        (queue.Queue -> EventBus -> root.after)
   v  gui/preview_panel.py                  tk.PhotoImage on a canvas (display only)
MAPPING tab: [thumbnails | large preview] + page info + page actions
```

* **`preview/renderer.py`** - `render_thumbnail` (default 160 px wide),
  `render_preview` (longest side, default 1000 px), `page_geometry` (points, mm,
  rotation, page count), `document_fingerprint`. Aspect ratio is always preserved,
  the scale is clamped to `0.05 .. 4.0` (no blurry upscaling, no insane renders)
  and every failure is a catchable `PreviewError`. PyMuPDF is imported in exactly
  one place in the project (`core/pdf_info.load_pymupdf`).
* **`preview/cache.py`** - `JOB/.cache/preview/*.png`, disposable at any moment
  (gitignored). A cache file's NAME is the identity:
  `<kind>_<pdf stem>_p<page>_<fingerprint>_<request>.png`, where the fingerprint is
  `sha1(pdf absolute path + mtime + size)` and the request is
  `sha1(page + kind + requested size|zoom)`. A modified PDF, a changed page or a
  different size can therefore never hit an old file; `invalidate_pdf(pdf, keep=...)`
  drops the entries of a replaced PDF and keeps the current one. The cache is
  bounded (`max_bytes` / `max_files`, LRU by access time) and never enters
  `state.json` / `config.json`.
* **`gui/preview_loader.py`** - ONE worker thread, a priority queue (the focused
  page first, then thumbnails) and an `EventBus` sink (`tasks.EVENT_PREVIEW`,
  drained by the Tk main thread). Requests are de-duplicated, so re-asking for a
  page is free. `set_document()` bumps a **generation token**: pending requests of
  the old document are dropped before they are rendered and results of an old
  generation are discarded instead of delivered - a thumbnail of PDF A can never
  appear on PDF B. Nothing in this module imports Tk.
* **`gui/preview_panel.py`** - the widgets: thumbnail grid, large preview, the
  FIT / 100% / +/- controls, the page info block, the error/status detail line and
  the page action buttons. It contains no PDF logic: it turns the PNG bytes it
  receives into `tk.PhotoImage` objects and draws them.
* **Selection stays in the Treeview.** A click on a tile only ASKS the mapping tab
  to select those pages; the tab applies the selection to the Treeview (the single
  source of truth, fed by the controller's plan) and then tells the panel what is
  selected. Ctrl/Shift multi-selection and the template actions therefore reuse
  exactly the proven controller/core calls.
* **States are visible, not implied**: every tile prints `001` / `WAITING` /
  `RUNNING` / `DONE` / `ERROR` / `SKIPPED` / `INTERRUPTED` (or `PREVIEW ERROR`) as
  text; colour is only an extra. While a batch runs the rows and tiles are re-read
  every `LIVE_STATE_REFRESH_SECONDS` (0.5 s), because a progress event only arrives
  AFTER a page finished.
* **A preview failure is not a processing failure**: an unrenderable page shows
  `PREVIEW ERROR` with its reason in the detail line, the mapping table keeps
  working and `state.json` is not touched.
* Drift handling is unchanged: a PDF that changed keeps showing `CONFIG STALE`
  (stored/current) and RECONCILE stays the explicit action; the changed mtime/size
  simply produces new cache keys.

## 4. JOB layout

```text
JOB/
  PDF/       input PDFs (recursive scan, bookkeeping folders skipped)
  TEMPLATE/  MASTER_AI_TEMPLATE.ai (default) + page templates 001_cover.ai, ...
  CONFIG/    config.json, state.json, presets/<name>.json (mapping intent)
  AI_OUT/    results: manualis__003.ai
  LOG/       app.log (all sessions) + batch_<timestamp>.log (one per run)
  ERROR/     reserved (layout compatibility)
  .cache/    preview/ - disposable PDF render cache (gitignored, safe to delete)
```

Python creates missing folders (`JobProject.ensure_structure`); the worker never
creates project folders. The preview cache folder is the one exception: it is
created lazily by `preview/cache.py` on the first render and only contains
disposable files.

## 5. Naming

Python owns output names (`core/naming.py`):

| Input | Output |
| --- | --- |
| `manual.pdf`, page 1 of 42 | `manual__001.ai` |
| `manual.pdf`, page 17 of 42 | `manual__017.ai` |
| `big.pdf`, page 7 of 1000 | `big__0007.ai` |

Width is `max(3, digits(page_count))`; the job id is `manual_p017`. The older
scheme (`manual_p03.ai`) exists only inside the frozen baseline
(`legacy/current_working_v10.jsx`). Because a JOB can hold several PDFs, the stem in
both names is the document's `pdf_id`, which keeps `manualis__001.ai` and
`appendix__001.ai` apart.

## 6. Page count

```python
from pdf_ai_batch.core.pdf_info import count_pages
count, method = count_pages("C:/JOB/PDF/manual.pdf")   # (42, "PyMuPDF")
```

PyMuPDF first, `pypdf` as fallback, an explicit `PdfPageCountError` when both
fail. No Illustrator probing and no assumptions about months or calendars: this is
generic multi page PDF processing.

## 7. Template mapping

1. Templates in `JOB/TEMPLATE` are sorted **naturally** (`1.ai`, `2.ai`, `3.ai`,
   `10.ai`; digit runs before letter runs, so `001_cover.ai` precedes
   `MASTER_AI_TEMPLATE.ai`).
2. `MASTER_AI_TEMPLATE.ai` / `MASTER_TEMPLATE.ai` (anything starting with
   `master`) is the **default** template and never part of the positional pool.
3. Automatic mapping is positional: page 1 -> first page template, page 2 ->
   second, and so on.
4. A page without its own template inherits `defaults.template`.

## 7b. Bulk mapping and presets (milestone 6)

`pdf_ai_batch/core/mapping_rules.py` is the **only** place that decides how pages are
mapped in bulk. The GUI collects input and calls the controller; the controller calls
this module. There is no range parsing, no numbered matching and no preset logic
anywhere else (a test asserts the GUI module contains none of it).

| Operation | Rule |
| --- | --- |
| `parse_pages` | `1`, `1-5`, `1,3,5`, `1-5,8,10-14`, `*` / `all` / `visas`; ascending, unique; rejects `0`, negatives, decimals, `1-`, unknown characters, pages beyond the document, ranges over 20 000 pages; `5-3` is normalized (strict mode: error) |
| `assign_template` | plan fields only (`template`, optional `layer`); `template=None` = inherit `defaults.template` |
| `clear_override` | page `template` back to `None` and `layer` back to `defaults.layer` |
| `auto_map_by_number` | page N -> the template whose name starts with N (`^[^0-9]*(\d+)`); masters excluded; a number used by two templates is a `problem` and those pages are left untouched; unnumbered templates and numbers beyond the page count are reported, never guessed |
| `copy_mapping` / `paste_mapping` | clipboard = `template` + `layer` (+ `enabled` when asked, + the document `clear_layer` when asked); queue state, attempts, run ids, errors and outputs never enter it; destination = explicit pages or source pages + `offset`; pages beyond the destination document are reported (`skipped_pages`), unused targets and truncated clipboards too; nothing fits -> error, no silent no-op |
| presets | `JOB/CONFIG/presets/<name>.json`, schema version 1, entries are range strings (`{"pages": "6-20", "template": "...", "layer": "...", "enabled": true}`); `validate_preset` rejects unknown keys and every runtime key (`state`, `attempts`, `run_id`, `error_type`, `output`, `job_id`, `stats`, ...); `preset_preview` computes the changes and the conflicts (pages beyond the document, missing template files) before anything is replaced; `apply_preset` overlays, `replace_all=True` resets the pages the preset does not mention |

Every plan change goes through `AppController._mutate_config`:

    _plan_config()  ->  _before_mutation(reason)  ->  mutate(config)
                    ->  validate_config()  ->  save_config() (atomic)  ->  build_queue()

`_before_mutation` is the hook milestone 8 (snapshots / undo) fills in, and
`cfg.save_config` is called from exactly one place in the GUI layer, so the GUI can
never write `config.json` on its own.


## 7c. Production preflight and job reports (milestone 7)

**Preflight.** `core/preflight.run_preflight(project, adapter=..., check_illustrator=...)`
answers "can this project run now?" in one report. It aggregates the checks that
already exist (`core/validation.py`, `config.validate_config`, the project plan, the
state model) and adds the project wide ones; it does not duplicate them and it is
read-only (no `config.json`, `state.json` or output is written).

| Section | Checks |
| --- | --- |
| PROJECT | JOB root and all six folders, `config.json` valid, `state.json` loadable, CONFIG writable |
| PDF | every configured document (missing, `CONFIG STALE`, `PLAN ERROR`, page count), PDFs in the folder, how many documents are really runnable |
| TEMPLATES | templates on disk, **every template named in `config.json`** (a missing one would silently fall back to the default), the default template when pages need it, the effective per page templates |
| OUTPUT | AI_OUT writable, valid output names, duplicates per document and across documents (read from the config, so an invalid config cannot hide behind the automatic plan), outputs outside AI_OUT, existing outputs that would be `SKIP` |
| QUEUE | `state.json` valid, unique `job_id`s, items outside the plan, stale `RUNNING`, runnable count, the six state counts |
| ILLUSTRATOR | `worker.jsx`, `cleanup.jsx`, `runtime/` (the real package paths) and COM availability + version |
| SYSTEM | free disk space (`FREE_SPACE_WARNING_MB` 500 / `FREE_SPACE_ERROR_MB` 100), LOG writable, report folder creatable |

Severity is `OK` / `WARNING` / `ERROR` per check and `READY` / `NOT READY` for the
project. **Only a real `ERROR` blocks a run**: a missing or stale document next to a
healthy one is a warning (RUN ALL skips it), while the same finding as the only
document is an error. Illustrator is contacted only when the explicit action asks for
it (`check_illustrator=True`, one of the two GUI paths that may touch COM).

**Reports.** After every pass the queue calls `report.write_report`, which writes two
immutable files into `JOB/LOG/reports/`:

    report_<YYYYmmdd-HHMMSS>.json    canonical, structured
    report_<YYYYmmdd-HHMMSS>.txt     the same content, human readable

`JobReport` carries counts of all six states, per document rows, the `ERROR` and
`INTERRUPTED` entries (type, message, attempts), objects processed, retries, duration,
Illustrator version and the abort reason - built from `state.json` plus the pass
`BatchSummary`, so the JSON always matches what the queue shows. A name that already
exists is never reused (`-2`, `-3`, ...), both files are written atomically, and a
failing report write is logged as a warning instead of turning a finished batch into a
failure. `list_reports()` returns them newest first.

## 8. Logging and errors

| Where | What |
| --- | --- |
| `JOB/LOG/app.log` | every record, appended over sessions, UTF-8 |
| `JOB/LOG/batch_<timestamp>.log` | one file per run (same records) |
| `runtime/worker.log` | the JSX side trace, appended by the worker |
| console | same records (UTF-8; the Windows console code page is switched to 65001) |

Format: `2026-09-23 16:42:33 | INFO | message`.

Failure policy: one bad page never stops the batch. The page is reported as
`ERROR`, its partial output is removed and the loop continues (`CONTINUE` / state
handling arrives with the queue milestone).

## 9. Source of truth rules

1. **The cleanup algorithm exists exactly once**: `jsx/cleanup.jsx`. It is
   extracted from the reference script by `tools/migrate_extract_sections.ps1`
   and used by both entry points (the worker and the legacy app).
2. `src/` is the legacy ScriptUI application; it holds **no copy** of the cleanup
   engine - it includes `../jsx/cleanup.jsx`.
3. Python owns orchestration; the JSX worker owns Illustrator. The GUI adds no
   fourth copy of anything: it only calls the core (`gui/controller.py`).
4. Everything exchanged is JSON, defined in `pdf_ai_batch/core/contract.py` and
   mirrored by `jsx/cleanup.jsx` (`statsToContract`) and `jsx/worker.jsx`.

## 10. Related documents

| Document | Content |
| --- | --- |
| [docs/QUEUE_STATE.md](docs/QUEUE_STATE.md) | the persistent queue, state machine, CLI and recovery |
| [docs/GUI.md](docs/GUI.md) | the Tkinter GUI: layers, threading, tabs, validation, acceptance |
| [MIGRATION_PLAN.md](MIGRATION_PLAN.md) | the approved migration plan, its status and what is next |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | the legacy single-file JSX application (phase 1) |
| [docs/CODE_ANALYSIS.md](docs/CODE_ANALYSIS.md) | the original reference script, function by function |
| [docs/WORKFLOW.md](docs/WORKFLOW.md) | operating the legacy GUI application |
| [docs/TESTING.md](docs/TESTING.md) | every gate: JSX checks, Python tests, manual checklist |
| [tests/TEST_PLAN.md](tests/TEST_PLAN.md) | test strategy, levels, entry/exit criteria |
| [tools/README.md](tools/README.md) | every development tool and what it verifies |
| [legacy/README.md](legacy/README.md) | the frozen working baseline and its hash |
