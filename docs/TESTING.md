# Testing

Repository: `sviskis/Cleanup_AI2026` · display name: Cleanup AI 2026

There are **three** automated gates plus a manual Illustrator checklist.

| Gate | Command | What it proves | Needs Illustrator |
| --- | --- | --- | --- |
| JSX static + ES3 compile | `tools\check_jsx.ps1` | include graph, real ES3 compile, ES3 syntax scan, module API wiring, for **both** entry points (`src/Main.jsx`, `jsx/worker.jsx`) | no |
| JSX unit + contract tests | `tools\run_tests.ps1` | 79 unit tests (stubbed host) + 44 JSON contract tests against the shared fixtures | no |
| Python tests | `.venv\Scripts\python.exe -m pytest` | 215 tests: naming, natural sort, page count (PyMuPDF + pypdf fallback), mapping, config (v1 -> v2 migration), contract, atomic IO, preflight, adapter handshake, queue, multi PDF (identity, drift, reconcile, collisions), GUI controller/tasks/window | no |
| Manual | `docs/TESTING.md` §2 (below) | actual cleaning result, visual quality, error paths | yes |

All three automated gates must be green before a commit (`.clinerules`).

```powershell
powershell -ExecutionPolicy Bypass -File tools\check_jsx.ps1
powershell -ExecutionPolicy Bypass -File tools\run_tests.ps1
.venv\Scripts\python.exe -m pytest
```

## 0. The one page milestone (new pipeline)

```powershell
# a demo job with a real multi page PDF
.venv\Scripts\python.exe tools\make_demo_job.py --root temp\DEMO_JOB --pages 14

# dry checks (no Illustrator)
.venv\Scripts\python.exe -m pdf_ai_batch.run_one --job temp\DEMO_JOB --pdf calendar.pdf --page 3 --preflight-only --skip-illustrator-check
.venv\Scripts\python.exe -m pdf_ai_batch.run_one --job temp\DEMO_JOB --pdf calendar.pdf --page 3 --dry-run

# the real one page test
.venv\Scripts\python.exe -m pdf_ai_batch.run_one --job temp\DEMO_JOB --pdf calendar.pdf --page 3
```

Pass criteria: `Statuss : OK`, the statistics block, `Output : ir (...)`,
`MILESTONE OK`, and `runtime\current_result.json` carrying the same `job_id` and
`run_id` as `runtime\current_job.json`.

Before Illustrator is invoked, the run prints and logs the final request paths
(`--- galīgie pieprasījuma ceļi (absolūti) ---`). All three (`pdf`, `template`,
`output`) must be **absolute and forward slashed**, for example
`C:/Users/.../temp/REAL_TEST/PDF/mans_fails.pdf`. The worker runs with Illustrator's
own working directory, so a relative path can never resolve - `File(path).exists`
would be false and the job would end as `INVALID_REQUEST`. Python resolves the
paths; the worker only validates that they are absolute and that the files exist.

Run the same page once more with a job folder and a PDF name that contain spaces
and Latvian characters (for example `temp\Realitātes tests LV` with
`Māja Āčēģī.pdf`). The request JSON, the worker log and the result JSON must show
those names exactly, with no mojibake: `jsx/` sources are ASCII only (`\uXXXX`
escapes), because ExtendScript decodes a large BOM-less `.jsx` as ANSI.

See `MIGRATION_PLAN.md` §3 for the full procedure and what to replace first
(real templates with an `ARTWORK` layer).

## 0b. The batch queue (milestone 2)
```powershell
# 1. build the queue (JOB/CONFIG/state.json) for pages 1-4
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\DEMO_JOB --build --pages 1-4

# 2. what would run, without touching Illustrator
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\DEMO_JOB --run-all --dry-run --skip-illustrator-check

# 3. the real batch (one worker call per page)
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\DEMO_JOB --run-all

# 4. the per page report
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\DEMO_JOB --status

# 5. resume after a crash / Ctrl+C / a closed window
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\DEMO_JOB --continue

# 6. retry the failed pages, after fixing whatever was wrong
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\DEMO_JOB --retry-errors
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\DEMO_JOB --retry-interrupted

# 7. single items (id = job_id, page number or output file name)
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\DEMO_JOB --reset 3
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\DEMO_JOB --skip 5
```

Pass criteria:

* `--status` shows one `PAGE / STATE / OUTPUT` row per page plus a counts line;
* a second `--run-all` runs nothing (`DONE=0 SKIPPED=0 ERROR=0` in the pass summary);
* `JOB/CONFIG/state.json` carries the same states, with `started`/`finished`
  timestamps per page;
* killing the process during a page leaves exactly one `RUNNING` item; the next
  command (even `--status`) turns it into `INTERRUPTED`, and `--continue` finishes it;
* an existing output without `--overwrite` is `SKIPPED`, never silently replaced;
* a page level failure leaves the other pages running (`ERROR` + `DONE` in one pass);
* Illustrator has no documents open afterwards (`app.Documents.Count == 0`).

The full scenario (deliberate SKIP, lost per-page template, kill/continue cycle),
the state machine and the `state.json` schema are in `docs/QUEUE_STATE.md`. The
automated driver used for the evidence is `temp/run_queue_batch_test.py`; it writes
every CLI output to `temp/queue_test_logs/`.

## 0c. The GUI (milestone 3)

`python app.py` opens the GUI; it is a view over the same core (see `docs/GUI.md`).

Automated (no display needed except the window smoke test, which skips itself when
Tk cannot open):

```powershell
.venv\Scripts\python.exe -m pytest pdf_ai_batch/tests/test_gui_controller.py -q   # 17
.venv\Scripts\python.exe -m pytest pdf_ai_batch/tests/test_gui_tasks.py -q        # 6
.venv\Scripts\python.exe -m pytest pdf_ai_batch/tests/test_gui_smoke.py -q        # 7
.venv\Scripts\python.exe -m pytest pdf_ai_batch/tests/test_gui_multi_pdf.py -q    # 12
```

What they cover: project loading populates the model, PDF selection reports the page
count from `pdf_info`, mapping rows come from plan + state, enable/disable and
template assignment persist through `config.json`, DONE/SKIPPED are never rerun,
retry errors / retry interrupted call the queue, progress derives from the state, the
GUI sources contain no COM/JSX/state writes, worker events reach the log view and
`on_close` warns when a page is RUNNING.

Real acceptance (one Illustrator run, ~2 minutes, `temp/run_gui_acceptance.py`):

1. open the real `temp/QUEUE_JOB` from the PROJECT tab,
2. PDF tab: page count 14 (PyMuPDF), size, config status,
3. MAPPING: 14 rows with the persisted states,
4. RESET SELECTED on 3 pages + a manual template change on one page,
5. VALIDATE: 24 checks, 0 errors,
6. RUN SELECTED: watch `WAITING -> RUNNING -> DONE` for each page,
7. force an ERROR (hold the output file open) and press RETRY ERRORS: `ERROR ->
   WAITING -> RUNNING -> DONE`,
8. close the window, open a new one: states restored,
9. verify `Illustrator.Application.Documents.Count == 0`.

## 0d. Several PDFs in one JOB (milestone 4)

Automated (no Illustrator, no display):

```powershell
.venv\Scripts\python.exe -m pytest pdf_ai_batch/tests/test_multi_pdf.py -q        # 16
.venv\Scripts\python.exe -m pytest pdf_ai_batch/tests/test_gui_multi_pdf.py -q    # 10
```

What they cover: two PDFs with the same page numbers get unique `job_id`s, the queue
order is document order then page ascending, one PDF's error does not stop another
PDF (while a COM failure still aborts the pass), output collisions are a config
error and abort a run before Illustrator is called, version 1 configs migrate (and an
existing v1 JOB reopens with the same states), state files without `pdf_id` are
upgraded silently, page count drift is reported without rewriting anything, RECONCILE
adds / restores / archives pages and keeps DONE states, a missing PDF keeps its plan
and recovers, multi PDF continue/retry, per document summaries and the GUI's current
PDF filtering.

Real acceptance (two Illustrator runs of 3 + 3 pages, ~4 minutes,
`temp/run_gui_acceptance_m4.py`):

1. open the real `temp/MULTI_JOB` (two real PDFs + a real MASTER template),
2. PDF tab: both documents detected with pages and queue status,
3. AUTO ASSIGN TEMPLATES for both (config order `[manualis, appendix]`),
4. RUN CURRENT PDF: manualis `WAITING -> RUNNING -> DONE` x3, appendix stays
   `WAITING 3`,
5. RUN ALL ENABLED PDFs: appendix runs too,
6. append a page to `appendix.pdf`: `CONFIG STALE (stored 3, current 4)` and
   `config.json` unchanged, then RECONCILE -> page 004 `WAITING`,
7. hold `manualis__002.ai` open and RESET that page: `manualis#2 WAITING -> ERROR`
   **while** `appendix#4` runs to DONE,
8. RETRY PROJECT ERRORS: `manualis#2 ERROR -> RUNNING -> DONE`,
9. close/reopen the window: every state persisted, 7/7 outputs, MASTER SHA256
   unchanged, `Illustrator.Application.Documents.Count == 0`.

## 0e. PDF preview + thumbnail browser (milestone 5)

`pytest` (no Illustrator, no display needed for the first three files):

| Test file | What it proves |
| --- | --- |
| `tests/test_preview_renderer.py` (15) | one page renders to PNG, thumbnail is 160 px wide, aspect ratio preserved (portrait + landscape), preview fits the longest side, `page_geometry` reports points/mm/rotation/page count, zoom clamping, missing / corrupt / empty / out-of-range pages raise `PreviewError`, `document_fingerprint` changes with the file, Latvian and space containing file names, `png_size` |
| `tests/test_preview_cache.py` (15) | `JOB/.cache/preview` location + `.gitignore` marker, put/get round trip, same PDF+page+mtime hits the same file, a different render size is a different entry, two PDFs never collide, a modified PDF produces a new key and `invalidate_pdf(keep=...)` removes the old one (and leaves other documents alone), `clear`, `prune` by files and by bytes, disabled cache writes nothing, empty payload = miss, sanitised Latvian file names |
| `tests/test_preview_loader.py` (13) | requests without a document are ignored, thumbnail + preview results (with geometry), the second request comes from the cache, duplicate requests are queued once, the focused page's preview jumps ahead of thumbnails, a document switch drops pending work and never delivers a foreign page, a corrupt page does not stop the others, a render failure leaves `state.json` byte identical, `invalidate_document`, results through the `EventBus`, `stop()` is clean - plus the **performance case**: 120 pages open in < 1 s with 0 synchronous renders, thumbnails arrive progressively, stale results stop at the switch |
| `tests/test_gui_preview.py` (15) | MAPPING builds the pane for the active document, thumbnails render progressively and land in `JOB/.cache/preview`, clicking a tile selects the mapping row and previews that page, clicking a row moves the tile selection, Ctrl/Shift multi-selection, tile text comes from `state.json` (`WAITING -> DONE`), an ERROR page exposes its type/message/attempts, a PREVIEW ERROR marks only the tile and keeps `state.json`, switching PDF clears the old selection and thumbnails, reopening the JOB serves thumbnails from the cache, `FIT`/`100%`/`+`/`-` change the render size, OPEN OUTPUT uses the injected opener (and refuses a missing file or a page that is not DONE), the live RUNNING refresh, a **120 page JOB opens without rendering everything** and the architecture rule: `preview/*` has no Tk/COM, `gui/preview_*.py` has no PyMuPDF/COM and the panel never renders |

Performance report (no GUI, ~1 minute, writes `temp/preview_perf_m5.txt`):

```powershell
.venv\Scripts\python.exe temp\preview_perf.py
```

It builds a 160 page PDF, measures "open + queue every thumbnail" (must stay in the
millisecond range and render nothing synchronously), the time to the first
thumbnail, the progressive counter, the total render time, the cache size and a
fully cached pass, the memory per result and a document switch in the middle of
rendering (pending requests dropped, zero foreign pages delivered). It also
measures a real photo PDF (`temp/QUEUE_JOB/PDF/mans_fails.pdf`) for a realistic
per-thumbnail number.

Real acceptance (one Illustrator run of 3 pages + an error page + a retry, ~4
minutes, `temp/run_gui_acceptance_m5.py`): the 20 milestone 5 steps - thumbnails,
click page 1/3, mapping row follows, Ctrl+click assignment of `section_blue.ai`,
switch to `appendix.pdf` and back (cached), run 3 selected pages with
`WAITING -> RUNNING -> DONE` **on the tiles**, a locked output -> `ERROR` with its
detail and attempts on the selected thumbnail, retry -> `DONE`, close/reopen (tile
text == `state.json`), MASTER SHA256 unchanged, `Documents.Count == 0`.

```powershell
$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe temp\run_gui_acceptance_m5.py
```

## 0f. Bulk mapping + presets (milestone 6)

The whole mapping decision layer is `pdf_ai_batch/core/mapping_rules.py`, so it is
tested directly (no files, no display, no Illustrator) and again through the GUI
controller:

| Test file | What it proves |
| --- | --- |
| `tests/test_mapping_rules.py` (48) | range syntax (`1`, `2-5`, `1,3,5`, `1-5,8,10-14`, `*`, duplicates collapse, `5-3` normalized or rejected in strict mode) and every rejection (`0`, `-3`, `1--5`, `1.5`, `1-`, `a`, `1,,2`, empty, a page past the document, an oversized range); `format_pages` compression; bulk assignment / `use_default_template` / `clear_override` / `set_layer` / `set_enabled` incl. template extension and page validation and the untouched other document; numbered mapping (leading number, natural sort `1,2,10`, MASTER and `master*` excluded, ambiguous number reported and **not** applied, unnumbered and out-of-range reported, zero page count rejected); copy/paste (plan-data-only payload, within one PDF, source pages when no target is given, cross PDF with an offset, no write past the destination page count, unused targets when the clipboard runs out, `enabled` and `clear_layer` opt-in, "nothing fits" raises); presets (range compression `1 / 2-5 / 6-35 / 36 / 37-40`, round trip through a Latvian file name, schema validation of version/name/entries/unknown keys/`source`, **runtime keys rejected** - `state`, `attempts`, `run_id`, `error_type`, `output`, `job_id`, `stats`, apply overlay, `replace_all` reset, a preview that writes nothing, and an unreadable file listed instead of crashing) |
| `tests/test_gui_bulk_mapping.py` (17) | the MAPPING actions through `AppController`: `parse_pages` with the document's page count, `assign_template_to_range` persisted in `config.json` and merged into the queue, the run history (ERROR + attempts) surviving a bulk edit, unknown page / bad extension rejected, `clear_pages` / `use_default_template`, positional `auto_assign_templates` still intact, `auto_map_by_template_number` (normal + ambiguity where the page keeps its manual override), copy/paste inside one PDF and across documents, paste beyond the document errors, paste without a clipboard errors, `save_preset` + `presets()` + `preset_preview` + `apply_preset` (`replace_all` variant, unknown preset errors, a larger preset applied to a smaller document with `skipped_pages`), the **mutation funnel counter** (8 plan mutations -> 8 `_before_mutation` calls, while `parse_pages`, `copy_mapping` and `save_preset` announce nothing) and the architecture guard: `controller.py` imports `core.mapping_rules`, has no regex range parser, no `json.dump` and exactly one `cfg.save_config` call |

Real acceptance (one Illustrator run of 5 pages, ~3 minutes,
`temp/run_gui_acceptance_m6.py`, evidence `temp/gui_acceptance_m6.txt`): the 16
milestone 6 steps on a real 36 page JOB - the real `RangeAssignDialog` rejecting `0`
and `99` with the core messages and accepting `2-5`, the range assignments, the
`CLEAR OVERRIDE` range, COPY 2-5 -> PASTE 22-25, SAVE PRESET (6 range rules, no
runtime key), AUTO MAP BY NUMBER (MASTER never used), reset all pages -> preset
preview with the conflicts -> reapply (plan byte-identical), VALIDATE (30 checks, 0
errors), 5 real pages processed, **every output proven against its template** (marker
text + artboard read back with PyMuPDF: `COVER-TEMPLATE` 520x720, `INTRO-TEMPLATE`
460x620 on page 2 *and* on the pasted page 22, MASTER 411x397, `SEP-TEMPLATE`
460x520), MASTER SHA256 unchanged and `Illustrator atvērti dokumenti: 0`.

Environment note (not a product bug): on CPython 3.14 a `tkinter` variable collected
by a worker thread can run `Variable.__del__` outside the main loop and invalidate Tk
widgets. Running a *subset* of the GUI test files can therefore abort with
`Windows fatal exception` or an invalid widget name, at the accepted milestone 5
baseline (`dac46e8`) as well. Always judge the suite with the project gate
(`.venv\Scripts\python.exe -m pytest`), which passes; the acceptance driver keeps its
dialog objects alive for the same reason.

## 0g. Production preflight (milestone 7)

```powershell
# the whole project in one report, Illustrator included (exit 1 when NOT READY)
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\PREFLIGHT_JOB --preflight-project

# without touching Illustrator (files, plan, queue, disk only)
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\PREFLIGHT_JOB --preflight-project --no-illustrator
```

| Test file | What it proves |
| --- | --- |
| `tests/test_preflight.py` (25) | a clean project is `READY` with all seven sections `OK`; the check writes nothing (`config.json`, `state.json`, AI_OUT byte identical); Illustrator is contacted **only** with `check_illustrator=True`; an unavailable or broken COM is an `ERROR`; a missing document is a warning while another document can run and an `ERROR` as the only document; `CONFIG STALE` (warning next to a healthy document, `ERROR` alone, with the RECONCILE hint); a template named in `config.json` but missing on disk is an `ERROR` (and the `Missing templates` fact counts it); a missing default template while a page inherits it is an `ERROR`; an empty template folder is an `ERROR`; an unwritable AI_OUT, duplicate outputs inside one document and across documents are `ERROR`s; an existing output for a runnable page is a `SKIP` warning; a stale `RUNNING` item and an item outside the plan are warnings; a corrupt `state.json` is a warning and still allows a run; the disk thresholds (warning / error / unreadable drive); `to_text()` and `to_dict()` agree |

Real acceptance: `temp/run_gui_acceptance_m7.py` (13 steps, real GUI + Illustrator,
evidence `temp/gui_acceptance_m7.txt`) - `[PREFLIGHT PROJECT]` -> `Overall READY`
(Illustrator READY 29.8.3), remove `001_cover.ai` -> `NOT READY`
(`[TEMPLATES] Konfigurētie template: trūkst: 001_cover.ai`) and RUN blocked, restore ->
`READY`.

## 0h. Job reports (milestone 7)

Every pass of the queue writes `JOB/LOG/reports/report_<YYYYmmdd-HHMMSS>.json` and
`.txt` (immutable; a second report in the same second gets `-2`). `BatchQueue` exposes
`last_report` / `last_report_paths`, the CLI prints the paths, and the GUI logs them.

| Test file | What it proves |
| --- | --- |
| `tests/test_report.py` (16) | duration formatting (`21m 42s`); counts match `state.json` for all six states; objects processed and retries counted; `ERROR`/`INTERRUPTED` rows carry type, message and attempts; a report can be built from disk without a pass summary; JSON + TXT land in `JOB/LOG/reports` and agree line by line; reports are immutable (`report_<stamp>-2.json` appears next to the first, which stays byte identical); writing touches neither `config.json` nor `state.json`; UTF-8 Latvian job/document names without mojibake; a broken report file is handled; every pass writes one (RUN ALL, RUN SELECTED, an empty pass); an aborted pass names its reason; report counts stay in sync after a retry; a failing report write never breaks a finished pass |

Real acceptance (same script): a locked output -> one `ERROR` page, `report ...txt`
with `DONE=8 ERROR=1` and the error row; `RETRY PROJECT ERRORS` -> `report ...txt` with
`DONE=9`, `ERROR=0`, `retries=1`; the report counts equal `state.json`
(`WAITING/RUNNING/DONE/ERROR/SKIPPED/INTERRUPTED`); both reports still on disk.

## 0i. Plan history: snapshots, undo, restore (milestone 8)

`JOB/CONFIG/history/<YYYY-MM-DD_HHMMSS>.json` holds the plan that a real change
replaced; `[UNDO PLAN CHANGE]` and `[RESTORE SNAPSHOT]` put an older plan back and
always keep the plan they replace first.

| Test file | What it proves |
| --- | --- |
| `tests/test_history.py` (17) | the snapshot before a bulk mutation holds the previous plan (with documents/pages/config-version metadata); the payload is plan data only (no `state`, `attempts`, `run_id`, `error_type`); names are timestamps and are never reused (`-2`); no plan -> no snapshot (and an empty dict is refused); undo restores the exact previous config and is itself undoable; nothing to undo returns `None`; undo skips a corrupt snapshot; restore snapshots the current plan first (kind `restore`); a corrupt or wrong-version snapshot is refused and the plan stays untouched; retention keeps the newest and never a pinned copy; `keep=0` disables pruning; a failing write leaves no file and no config change; `state.json` and the outputs stay byte identical; a v1 config is snapshotted as v2; a two-document UTF-8 plan round trips without mojibake; human readable summaries; newest first ordering by modification time |
| `tests/test_gui_history.py` (13) | the controller funnel snapshots before the change (`bulk-assign`, `preset`, `auto-map`, `plan` kinds all recorded); a no-op edit creates no snapshot; an unwritable snapshot blocks the mutation; UNDO restores the previous plan and keeps the queue (ERROR + attempts survive, defaults resolve again); a second UNDO brings the undone state back; nothing to undo is reported; RESTORE puts an older plan back and adds the recovery copy; restore accepts a name or a path and rejects an unknown one; a corrupt snapshot is refused without touching the plan; the list survives a corrupt file; the history and the restored plan survive a GUI reopen |

Real acceptance: `temp/run_gui_acceptance_m8.py` (11 steps, evidence
`temp/gui_acceptance_m8.txt`) - AUTO ASSIGN materialises the plan (no snapshot yet),
`ASSIGN TO RANGE 6-35` creates a snapshot equal to the previous plan, `UNDO` restores
it and adds the recovery copy, a second edit + preset + `RESTORE SNAPSHOT` keep the
plan they replace, the reopened GUI lists the same snapshots, `state.json` counts and
all 36 `job_id`s are unchanged, every history file is plan-only and Illustrator was
never touched.

### Windows desktop application (milestone 9)

```powershell
# one command: gates, clean, PyInstaller, assets, verification, packaged smoke test
powershell -ExecutionPolicy Bypass -File tools\build_release.ps1

# run it
"dist\Cleanup AI 2026\Cleanup AI 2026.exe"
"dist\Cleanup AI 2026\Cleanup AI 2026.exe" --diagnose
```

`docs/PACKAGING.md` explains the layout, why PyInstaller, paths (everything from the
executable, never the working directory), the version resource, the production log
location and the limitations. Illustrator is never bundled - the .exe talks to the
installed Illustrator through COM.

| Test file | What it proves |
| --- | --- |
| `tests/test_packaging.py` (22) | path resolution in both layouts (source, frozen, `PDF_AI_BATCH_HOME`/`ROOT`, PyInstaller bundle fallback, `%LOCALAPPDATA%` fallback for read only installs, no cwd dependency); diagnostics in source and in a broken install (missing JSX/config are failures, JSON serialisable, Illustrator contacted only on request, a windowed build still gets an output stream); and the packaging contract (`VERSION` == `__version__`, the spec covers assets + COM libraries + no Illustrator + windowed/debug, the build script runs the gates and verifies its own result, the shortcut tool is opt-in, `build/`/`dist/` ignored, win32com only in the adapter) |

Real acceptance: `temp/run_packaged_acceptance_m9.py` (10 steps, evidence
`temp/packaged_acceptance_m9.txt`, screenshot `temp/gui_m9_window.png`) - distribution
layout, PE subsystem 2 (GUI, no console), ProductVersion 0.9.0, `--version` and
`--diagnose` from another working directory, packaged `--preflight-project` READY on a
Latvian path, `--run-all` of 7 real pages with `state.json` + an immutable report from
the packaged app, the GUI opening/closing cleanly with its startup record in
`<install>/logs/app.log`, the shortcut tool, and `Illustrator Documents.Count == 0`.

## 1. Automated checks
```powershell
powershell -ExecutionPolicy Bypass -File tools\check_jsx.ps1
powershell -ExecutionPolicy Bypass -File tools\run_tests.ps1
```

### `tools/check_jsx.ps1`

| Check | What it proves |
| --- | --- |
| include resolution | every `#include` in `src/Main.jsx` exists, every `src` module is reachable, no orphan module |
| bundle compile | the concatenated bundle (`temp/verify_bundle.js`) is compiled by the **WSH JScript 5.8 engine**, the same ES3 syntax family as ExtendScript |
| ES3 scan | no `let`, `const`, arrow functions, `async`/`await`, `class`, `import`/`export`, `Promise`, template literals, spread/rest, optional chaining. Comments and string literals are ignored, so documentation text about those keywords does not trigger it |
| ES5+ helpers (warning) | flags `forEach`, `map`, `filter`, `reduce`, `Object.keys`, `JSON.*`, `String.trim`, `startsWith`, `endsWith`, `includes` if they ever appear |
| API wiring | every `PDC.<Module>.<member>` reference in the project must exist in that module's exported API |

Exit code 0 = green. This is the gate described in `.clinerules`.

### `tools/run_tests.ps1`

Builds `temp/test_bundle.js` from `tests/jscript/stubs.js` (a fake `File`,
`Folder`, `app`, `$` host with an in-memory filesystem), all `src` modules except
the entry point, and `tests/jscript/run_tests.js`. It runs with
`cscript //E:JScript`, which also re-proves ES3 syntax of the tested code.

Current result: **79 passed, 0 failed**. Coverage:

| Area | Examples |
| --- | --- |
| module wiring | 12 modules registered, `EXPECTED_MODULES` all present |
| config defaults | `dryRun`/`debug`/`overwriteExisting` false, `ARTWORK`, 9 rows, depth 8, 40 ungroup passes, excluded folder list |
| naming | `baseNameNoExt` edge cases, `padPageNumber` (1/1, 3/9, 3/12, 12/120), `makePageOutputName` (`a.ai`, `a_p03.ai`, `a_p007.ai`), `pageJobKey` |
| scan rules | excluded folders (`log`, `ai_out`, `errors`) vs kept (`pdf`, `artwork`), write test on a missing folder |
| text IO | `writeTextFile` / `readTextFile` / `appendTextFile` round trip |
| logging | level format `| INFO |`, warning, error always written, debug suppressed when `debug = false` |
| errors | `error.txt` content, `context.txt` content, dialog text, `errorMessage(null)` |
| diagnostics | all checks have `name`/`value`/`ok`, report text |
| cleanup stats | `summaryLine()` counters and reset, `run(null)` raises |
| template | `templateScore` ranking, empty folder returns `null` |
| paths | project root, config/logs/errors folders, JOB folder layout, no hard coded suggestion |

What the automated level **cannot** cover: Illustrator DOM behaviour
(`app.open`, `executeMenuCommand`, `duplicate`, artboard geometry), real PDF page
counting, and the visual result of the cleanup.

## 2. Manual checklist in Illustrator

Run this after any change to `core/`, and at least once per release. Keep a
throwaway JOB folder with 1 PDF (2-3 pages) and 1 template.

### Smoke

| # | Step | Expected |
| --- | --- | --- |
| S1 | File > Scripts > Other Script... > `src/Main.jsx` | window opens, log shows `PDF Deep Cleanup → AI Template Batch v0.1.0` and the project path |
| S2 | press **Aizvērt** right away | window closes, `logs/project.log` was appended |
| S3 | press **Diagnostika** | report opens, `logs/` and `temp/` are `[OK]`, the template line names the template file |
| S4 | press **Izvēlēties...** and cancel the dialog | nothing changes, no error, window still usable |
| S5 | press **START BATCH** with no JOB folder chosen | nothing happens (no crash) |

### Functional

| # | Step | Expected |
| --- | --- | --- |
| F1 | choose the test JOB folder | log block, PDF count, page list filled, status line with template `OK` |
| F2 | tick one page, **START BATCH** | `OK` line with `obj=`, `ungrp=`, `masks=`, `crop=`; `AI_OUT` contains the named AI file |
| F3 | open the produced AI | template elements intact, PDF artwork inside layer `ARTWORK` |
| F4 | compare the AI with the PDF visually | no missing shapes, no shifted objects, no leftover crop marks |
| F5 | run the same page again | `SKIP`, file untouched |
| F6 | tick "Pārrakstīt esošos AI", run again | `OK`, file replaced |
| F7 | untick "Iztīrīt template slāni ARTWORK", process a fresh page | old layer content stays, new artwork is added |
| F8 | 12 page PDF | output names `_p01` ... `_p12`, count matches the Illustrator page count |
| F9 | PDF with Latvian characters and spaces in the name | same name in `AI_OUT`, no mojibake in the log |
| F10 | **Pārbaudīt / pārlasīt PDF** | page counts and tick state are preserved |

### Error handling

| # | Step | Expected |
| --- | --- | --- |
| E1 | empty `PDF` folder | `! PDF nav atrasts.`, START BATCH disabled |
| E2 | no template in `TEMPLATE` | `! Template nav atrasts...`, START BATCH disabled |
| E3 | password protected PDF | `ERROR` for that page, batch continues, report in `logs/errors/<ts>/` |
| E4 | 0 byte PDF file | `ERROR` (or the 1 page fallback), batch continues |
| E5 | read-only `AI_OUT` folder | the page fails with a clear error, batch continues, report written |
| E6 | try to close the window during a run | not possible, the button is disabled |
| E7 | `CONFIG.dryRun = true`, run 3 pages | three `PLĀNS` lines, `AI_OUT` unchanged, final dialog says `DRY RUN` |
| E8 | after E3..E5 | Illustrator still shows normal dialogs, the window is usable, **Aizvērt** works |

### Regression against the reference script

`archive/original/PDF_Deep_Cleanup_AI_Template_BATCH.jsx` must produce the same
result as `src/Main.jsx` for the same JOB and the same ticked pages. Run both and
compare:

| # | Compare | How |
| --- | --- | --- |
| R1 | output file names | directory listing of `AI_OUT` |
| R2 | cleanup statistics | `ungrp=`, `masks=`, `crop=` values in the log lines |
| R3 | artwork placement | overlay both AI files in Illustrator and check the bounding box |
| R4 | page count detection | same `lapas=<n> | <method>` lines |
| R5 | skip behaviour | same `SKIP` lines |

If R1-R5 match, the refactor is behaviour neutral. Any difference must be recorded
in `CHANGELOG.md` with a reason.

## 3. Regression test assets

Keep them outside the repository (they are real work files and `.gitignore` blocks
`*.pdf`): a JOB folder with a 3 page PDF, a 12 page PDF, a PDF with Latvian
characters in the name, and a MASTER template containing an `ARTWORK` layer with
placeholder objects.

## 4. Future automation ideas

* Extend `tests/jscript/stubs.js` with a fake document model to unit test
  `duplicateSourceLayersIntoArtwork` layer ordering.
* Python + win32com harness: open a test PDF in Illustrator through COM, run
  `src/Main.jsx` with `dryRun = true`, then assert on `logs/project.log` - this
  would let the batch loop be tested end to end automatically.
* Golden file comparison of `AI_OUT` bounding boxes through COM.
