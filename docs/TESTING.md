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
