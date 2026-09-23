# Current Status

Version: 0.9.0
Repository: `sviskis/Cleanup_AI2026` · local folder `Cleanup_AI2026` · display name Cleanup AI 2026
Status: **Milestones 8 and 9 done - the plan is recoverable (snapshots in `JOB/CONFIG/history/` with `[UNDO PLAN CHANGE]` / `[RESTORE SNAPSHOT]`) AND the application ships as a Windows desktop executable: `tools\build_release.ps1` builds `dist\Cleanup AI 2026\Cleanup AI 2026.exe` with one command (gates, PyInstaller, asset copy, verification, packaged `--diagnose` smoke test); a real packaged acceptance run processed 7 pages through Illustrator from the .exe, on a Latvian project path, with reports, preflight, the GUI, the shortcut tool and `Illustrator Documents.Count == 0`**

## Working

### New pipeline (Python + JSX worker)

* `jsx/cleanup.jsx` - the canonical Illustrator engine (cleanup v6 appearance safe
  + document helpers + stats contract). Exactly one copy in the project.
* `jsx/json2.js` - ES3 JSON polyfill (`stringify` / `parse`), used by the worker.
* `jsx/worker.jsx` - one page per invocation: reads `runtime/current_job.json`,
  validates it, opens the PDF page, runs the cleanup, prepares the output AI
  (`copy` or Illustrator `saveAs` for `.ait`), transfers the artwork into the target
  layer, saves, closes both documents and writes the result JSON.
* Python core: project model and JOB folders, PDF discovery, **PyMuPDF page count**
  (pypdf fallback), natural sorting, template mapping with master exclusion and
  default fallback, output naming, `config.json` validation and atomic save, the
  request/result contract, preflight validation, atomic JSON IO.
* `adapters/illustrator.py` - the only COM code: attach to a running Illustrator,
  launch when needed, write the request atomically, run the worker, accept a result
  only when `job_id` **and** `run_id` match, timeout with the worker log tail,
  scoped `close_documents`.
* `run_one.py` / `app.py` CLI: `--diagnose`, `--health`, `--run-one`,
  `--preflight-only`, `--dry-run`, `--skip-illustrator-check`.
* Logging: `JOB/LOG/app.log` (all sessions) + `JOB/LOG/batch_<timestamp>.log`,
  UTF-8, plus `runtime/worker.log` from the JSX side.
* Legacy ScriptUI application (`src/`) still works and now includes the shared
  engine from `jsx/cleanup.jsx` (no duplicate cleanup code).

### Queue + persistent state (milestone 2)

* `core/state.py` - `JOB/CONFIG/state.json`: `WAITING`, `RUNNING`, `DONE`, `ERROR`,
  `SKIPPED`, `INTERRUPTED`; atomic writes, attempt counting, timestamps, tolerant
  loading (a corrupt file is quarantined, never fatal), `RUNNING -> INTERRUPTED`
  recovery at startup.
* `core/queue.py` - `BatchQueue`: `build_queue`, `run_next`, `run_all_enabled`,
  `continue_queue`, `retry_errors`, `retry_interrupted`, `skip_item`, `reset_item`,
  `status_table`, `summary`. Adapter agnostic, no COM in the core.
* `core/pagejob.py` - one shared plan for `run_one` and the queue, the DONE rule
  (output exists and is not empty) and the output preparation
  (`copied` / `skipped` / `failed`).
* `batch.py` CLI - `--build`, `--status`, `--run-next`, `--run-all`, `--continue`,
  `--retry-errors`, `--retry-interrupted`, `--skip ID`, `--reset ID`, ...
* Rules in force: DONE needs `OK` **and** an output; finished pages never rerun
  without `--reset`; one bad page never stops the batch; only a COM failure aborts a
  pass; a failed attempt removes its partial output so retries really run.
* Details, schema and the real-run evidence: `docs/QUEUE_STATE.md`.

### Tkinter GUI (milestone 3)

* `pdf_ai_batch/gui/` - `main_window.py` (window, 4 tabs, 120 ms event pump, close
  safety), `project_tab.py`, `pdf_tab.py`, `mapping_tab.py`, `run_tab.py`,
  `controller.py` (all GUI logic, **no Tk, no COM**), `tasks.py` (worker thread +
  event queue + log handler), `context.py`.
* `python app.py` (or `--gui`, or `python -m pdf_ai_batch.gui`) opens the window;
  opening it never launches Illustrator. Illustrator is contacted only by an
  explicit HEALTH CHECK or a RUN (`adapters/illustrator.py`, the only COM code).
* GUI -> controller -> core/adapter. The GUI never touches win32com, JSX or
  `state.json`: plan edits go to `CONFIG/config.json` and are merged into
  `state.json` by `BatchQueue.build_queue`; RESET/RETRY are core transitions.
* Threading: every long action runs in a `TaskRunner` worker thread; the Tk main
  thread only renders events (`queue.Queue` + `root.after`). While a task runs, the
  mutating buttons of PROJECT/PDF/MAPPING are disabled (the worker owns state.json).
* Validation = existing core checks only (`validation.preflight`,
  `validation.check_file`, `config.validate_config`), shown in the MAPPING tab and
  enforced before every RUN; no Illustrator call unless a health check asked for it.
* Progress ("Page 014 / 014", bar, DONE/WAITING/RUNNING/ERROR/SKIPPED/INTERRUPTED
  counts) derives from the queue state - the GUI keeps no counter of its own. The log
  panel is a view; `JOB/LOG/app.log` + `JOB/LOG/batch_<timestamp>.log` stay canonical.
* Details, tab reference and acceptance evidence: `docs/GUI.md`;
  screenshots `temp/gui_mapping.png`, `temp/gui_run.png`.

### Multi PDF project queue (milestone 4)

* `config.json` is version 2: `{version: 2, defaults, documents[]}` with one block
  per PDF (`pdf`, `page_count`, `enabled`, `pages[]`, `removed_pages[]`). A version 1
  file is migrated **in memory** on read, so every existing JOB keeps working; the
  file is rewritten as v2 on the next plan save.
* Identity is `pdf_id` (stable, derived from the file name, never `hash()`) plus
  page: `manualis_p001`, `appendix_p001` ... Page numbers alone are never used as
  identity, and a bare page number in a multi PDF JOB is reported as ambiguous.
* One plan per document (`core/pagejob.py`): `plan_project` orders documents by
  `documents[]` and then by page number; `plan_document` reports `OK`, `NEW`,
  `CONFIG STALE`, `MISSING PDF` or `PLAN ERROR` and **never rewrites** anything.
* Page count drift: `CONFIG STALE (stored: 42, current: 44)` until the operator
  runs an explicit RECONCILE - kept pages keep template/output/state, new pages
  become WAITING with the defaults, removed pages move to `removed_pages` (never
  deleted, restored when the page comes back).
* A missing PDF file is `MISSING PDF`: its plan and its queue states are kept and
  its items are disabled, so it is recoverable as soon as the file returns.
* Output naming stays PDF aware (`manualis__001.ai`, `appendix__001.ai`); the config
  validator and a `BatchQueue` guard both refuse a plan in which two documents would
  write the same AI (the pass aborts before the first Illustrator call).
* Queue semantics are unchanged per document: a failure in `manualis.pdf` page 17
  does not stop page 18 or `appendix.pdf`; only a global Illustrator/COM failure
  aborts a pass.
* GUI: the PDF tab lists the documents (`USE / PDF / PAGES / CONFIG STATUS /
  QUEUE STATUS`), MAPPING edits the active document only (it says which one), the
  RUN tab has the project actions and a per document progress list; screenshots
  `temp/gui_m4_pdf.png`, `temp/gui_m4_run.png`, `temp/gui_m4_reopen.png`.

### Visual page browser (milestone 5)

* `pdf_ai_batch/preview/` is the only renderer: `renderer.py` (PyMuPDF, one page at
  a time: thumbnail 160 px, preview 1000 px longest side, `page_geometry` in
  points/mm, `document_fingerprint`, `png_size`; aspect ratio preserved, scale
  clamped, every failure a `PreviewError`) and `cache.py` (disposable
  `JOB/.cache/preview`, the file name carries pdf + mtime + size + page + render
  size, `invalidate_pdf`, `clear`, `prune`, `stats`).
* `gui/preview_loader.py` renders on ONE worker thread with a priority queue
  (focused page first), request de-duplication and a generation token per document:
  a stale thumbnail can never be painted on another PDF, and switching documents
  drops the pending work instead of rendering it. Results travel through
  `tasks.EVENT_PREVIEW` into `MainWindow._pump`, so only the Tk thread touches
  widgets. No Tk, no COM, no Illustrator.
* The MAPPING tab shows `[thumbnails | large preview]` above the table, with the
  page info block (PDF, page / total, size, template, layer, output, state,
  attempts), the error/output detail line and the page actions; clicking a tile or a
  row keeps both views in sync (the Treeview stays the single selection source).
  Tiles print `001 WAITING` / `DONE` / `RUNNING` / `ERROR` / `PREVIEW ERROR`, so the
  state never depends on colour alone. `OPEN OUTPUT` opens a DONE page's AI with the
  OS default and refuses missing files or unfinished pages.
* While a batch runs the rows and tiles are re-read every 0.5 s, so the page being
  processed is visibly `RUNNING` (a progress event alone only arrives afterwards).
* A page that cannot be rendered shows `PREVIEW ERROR`; the plan, the table and
  `state.json` are untouched - preview failure is never a processing state.
* Performance: a 160 page PDF opens instantly (1.3 ms to queue every thumbnail, 0
  synchronous renders), the first thumbnail appears after 0.03 s, all 160 render in
  2.2 s, a fully cached pass takes 0.04 s and the cache is 0.2 MB for the whole
  document (`temp/preview_perf_m5.txt`).

### Bulk mapping + reusable presets (milestone 6)

* `core/mapping_rules.py` - **the only place that decides mapping**:
  * `parse_pages` (`1`, `1-5`, `1,3,5`, `1-5,8,10-14`, `*`) with strict validation
    (no `0`, no negatives, no decimals, no `1-`, no page beyond the document, no
    oversized range) and `format_pages` for the reverse direction. The GUI has no
    parser of its own.
  * Bulk assignment (`assign_template` with an optional layer, `use_default_template`,
    `clear_override`, `set_layer`, `set_enabled`) that only ever touches plan fields.
  * `auto_map_by_number` - page N gets the template whose name starts with N
    (`001_cover.ai`); natural sort, MASTER templates excluded, an ambiguous number is a
    reported problem and those pages are left alone, a number beyond the page count is
    informational. Deterministic - no fuzzy or AI matching anywhere.
  * `copy_mapping` / `paste_mapping` - a clipboard with plan data only (template,
    layer, enabled on request); works inside one PDF and across PDFs, never writes
    beyond the destination page count and reports `skipped_pages`, `unused_pages`,
    `truncated`.
  * Presets (`JOB/CONFIG/presets/<name>.json`, schema version 1): the current mapping
    compressed into ranges, saved/loaded/validated, with `preset_preview` (changes and
    conflicts) and `apply_preset` (overlay or `replace_all`). Runtime fields are
    rejected by the schema, so a preset is mapping intent only.
* `gui/bulk_dialogs.py` - `RangeAssignDialog` (range + template + layer + enable, its
  validation comes from `AppController.parse_pages`), `SavePresetDialog`,
  `PresetDialog` (list, conflict preview, "also replace the other pages").
* MAPPING action bar (three rows): SELECT ALL / NONE, ENABLE / DISABLE / RESET
  SELECTED, VALIDATE, ASSIGN TO SELECTED, ASSIGN TO RANGE, USE DEFAULT,
  CLEAR OVERRIDE, AUTO MAP BY NUMBER, REFRESH, COPY MAPPING, PASTE MAPPING,
  SAVE PRESET, LOAD / APPLY PRESET, AUTO ASSIGN TEMPLATES, RECONCILE PDF.
* One mutation funnel: `AppController._mutate_config` -> `_before_mutation` (the hook
  milestone 8 will snapshot in) -> `validate_config` -> atomic `save_config` ->
  `BatchQueue.build_queue`. `cfg.save_config` is called from exactly one place in the
  GUI layer, and `_mapping_mutation` turns core `MappingError` / `PresetError` into
  `ControllerError` for the widgets.
* Details and the real evidence: `docs/GUI.md` §Bulk mapping and
  `temp/gui_acceptance_m6.txt`.

### Production preflight + job reports (milestone 7)

* `core/preflight.py` - `run_preflight(project, adapter=..., check_illustrator=...)`
  returns one `PreflightReport` with sections `PROJECT`, `PDF`, `TEMPLATES`, `OUTPUT`,
  `QUEUE`, `ILLUSTRATOR`, `SYSTEM`; every check carries `OK` / `WARNING` / `ERROR`, the
  report carries `READY` / `NOT READY`, `problems`, `warnings`, `facts`,
  `summary_rows()` (the compact layout), `to_text()` and `to_dict()`.
  * It **aggregates** `core/validation.py`, `config.validate_config`, the project plan
    and the state model instead of duplicating them.
  * `RUN` is blocked by a real `ERROR` only (`can_run`), never by a warning: a missing
    PDF or a stale page count is a warning while another document can still run, and an
    ERROR when nothing is left to run.
  * Illustrator is contacted **only** for this explicit action, through the same
    adapter as a run - opening the GUI still never touches COM.
  * The check is read-only (unit tested: config.json, state.json and AI_OUT unchanged).
* `core/report.py` - immutable reports of every pass:
  `JOB/LOG/reports/report_<YYYYmmdd-HHMMSS>.json` (canonical) + `.txt` (readable),
  written atomically and never overwritten (`-2` suffix on a collision). `JobReport`
  holds counts of all six states, per-document rows, the ERROR/INTERRUPTED entries with
  type/message/attempts, objects processed, retries, duration, Illustrator version and
  the abort reason. `build_report()` reads the queue state, `list_reports()` /
  `read_report()` read them back.
* `core/queue.py` - `finish_pass()` ends every pass with a report (RUN ALL ENABLED,
  RUN CURRENT PDF, RUN SELECTED, CONTINUE, RETRY ERRORS, RETRY INTERRUPTED, and a pass
  that could not even start); a failed report write is a warning, never a failed batch.
* GUI `[PREFLIGHT PROJECT]` (RUN tab) + the summary block in the progress panel;
  CLI `batch.py --preflight-project [--no-illustrator]`.
* Details and the real evidence: `docs/GUI.md` §Production preflight, `docs/TESTING.md`
  §0g and `temp/gui_acceptance_m7.txt`.

### Plan snapshots, undo and restore (milestone 8)

* `core/history.py` - the plan history of a JOB, in `JOB/CONFIG/history/`:
  * one file per snapshot (`<YYYY-MM-DD_HHMMSS>.json`) holding the exact plan plus
    metadata (version, created, kind, reason, job, app version, document/page counts,
    pinned, config version). **Plan data only**: no state, attempts, run ids or errors.
  * `snapshot()` writes atomically (a failed write raises `HistoryError` and leaves
    nothing behind), `load_snapshot()` validates version + plan so a corrupt copy can
    never be applied, `list_snapshots()` sorts newest first (mtime, so a `-2` copy from
    the same second is newer), an unreadable file is listed but never restored.
  * `undo_last()` restores the newest snapshot whose plan differs from the current one;
    `restore_snapshot()` snapshots the CURRENT plan first ("recovery copy") and then
    writes the restored plan atomically, so **a restore is reversible too**.
  * retention `DEFAULT_RETENTION` = 100 snapshots per JOB; a `pinned: true` snapshot is
    never pruned (the hook for manually named snapshots later). No database.
* One funnel: `AppController._mutate_config` -> `_plan_is_on_disk` (a no-op edit is not
  saved and not snapshotted) -> `_before_mutation(reason, kind)` (the snapshot) ->
  `validate_config` -> atomic save -> queue rebuild. Kinds: `bulk-assign`, `preset`,
  `auto-map`, `reconcile`, `undo`, `restore`, `plan`.
* MAPPING tab: `[UNDO PLAN CHANGE]` (one step back) and `[RESTORE SNAPSHOT]`
  (`bulk_dialogs.SnapshotDialog` lists timestamp, reason, `n PDF, m lapas` and marks
  pinned copies).
* Demonstration and evidence: `docs/GUI.md` §Plan history and
  `temp/gui_acceptance_m8.txt`.

### Windows desktop application (milestone 9)

* `tools/build_release.ps1` - **one command** for the production build:
  `dist/Cleanup AI 2026/` with `Cleanup AI 2026.exe` (windowed, no console),
  `program/` (Python + libraries + the application), `jsx/`, `config/`, `logs/`,
  `docs/`. It runs the three gates first, cleans `build/` and `dist/`, runs PyInstaller
  with `tools/cleanup_ai.spec`, copies the assets (next to the exe and into `program/`),
  verifies them and runs the packaged `--diagnose` as a smoke test.
* `tools/cleanup_ai.spec` - PyInstaller spec: hidden imports for `tkinter`, `pywin32`
  COM and PyMuPDF, whole `jsx/`, `config/`, `docs/` folders as data, a version resource
  from `VERSION`, no Illustrator. Release is `console=False`, `-Configuration Debug`
  keeps the console.
* `pdf_ai_batch/diagnostics.py` + `app.py --diagnose` - production diagnostics
  (version, frozen/source, Python + architecture, PyInstaller bundle, pywin32, JSX
  assets with paths, default config, writable runtime/log folders, Illustrator
  installed without launching it, reachable only with `--with-illustrator`); a packaged
  start shows a message box with the reason when a resource is missing.
* Paths: everything is derived from the executable (`pdf_ai_batch/paths.py`), never from
  the current working directory; a read only install keeps its writable data in
  `%LOCALAPPDATA%/Cleanup AI 2026/`.
* `tools/create_shortcut.ps1` - opt-in desktop shortcut (never automatic).
* Details, layout and limitations: `docs/PACKAGING.md`; evidence:
  `temp/packaged_acceptance_m9.txt` and `temp/gui_m9_window.png`.

### Frozen baseline

* `legacy/current_working_v10.jsx` - 2789 lines, SHA256
  `CF325565484D715DE5AA2B91D785FE5052950FC631C18D4C974E82476AC9A20F`, generated by
  `tools/freeze_legacy.ps1` from the verified `src/` application.
* `archive/original/` - the three predecessor scripts, byte identical, hashed.

## Verified

| Check | Result |
| --- | --- |
| `tools/check_jsx.ps1` | 0 errors, 0 warnings (2 entry points, ES3 compile, ES3 scan, API wiring, `jsx/` ASCII only + no BOM + LF) |
| `tools/run_tests.ps1` | 79 JSX unit tests + 44 JSON contract tests |
| `pytest` | 273 tests (Python 3.14 venv): contract, absolute paths, encoding, state, queue, multi PDF queue (identity, drift, reconcile, collisions), GUI controller/tasks/window, GUI multi PDF, PDF preview (renderer, cache, background loader, thumbnail browser) |
| `app.py --diagnose` | paths and interpreter reported |
| `run_one --preflight-only` (14 page demo PDF) | 17 checks OK, request JSON written to `runtime/current_job.json` |
| `run_one --dry-run` | valid contract request produced |
| **`run_one --job temp\REAL_TEST --pdf mans_fails.pdf --page 3`** | **MILESTONE OK**: absolute forward slash request paths, `Statuss : OK`, `Objekti : 3`, real output AI, MASTER template untouched, 0 documents left open |
| **Same run with a Latvian job folder** (`temp\Realitātes tests LV`, PDF `Māja Āčēģī.pdf`) | **MILESTONE OK**: Latvian characters survive request JSON, worker log and result JSON without mojibake |
| **Batch queue, real Illustrator** (`temp\QUEUE_JOB`, `temp/run_queue_batch_test.py`) | `--run-all` -> 001 DONE / 002 SKIPPED / 003 DONE / 004 DONE; second pass reruns nothing; lost per-page template -> 003 ERROR + 004 DONE; `--retry-errors` -> 003 DONE; process killed during page 4 -> `--status` shows 004 INTERRUPTED -> `--continue` -> 004 DONE |
| **13 page pass** of the same PDF through the queue | `DONE=13 SKIPPED=1`, `state.json` written after every page, 0 documents left open |
| **GUI acceptance, real Illustrator** (`temp/run_gui_acceptance.py`, `temp/gui_acceptance.txt`) | Open JOB -> PDF shows 14 pages (PyMuPDF) -> 14 mapping rows with the persisted states -> RESET SELECTED + manual template change -> VALIDATE 24 checks / 0 errors -> RUN SELECTED: live `WAITING -> RUNNING -> DONE` x3 -> forced ERROR (`OUTPUT_PREP_FAILED`, locked output) -> RETRY ERRORS: `ERROR -> WAITING -> RUNNING -> DONE` -> window closed and reopened: states restored -> 0 Illustrator documents open. Screenshots: `temp/gui_mapping.png`, `temp/gui_run.png` |
| **GUI acceptance, TWO PDFs in one JOB** (`temp/run_gui_acceptance_m4.py`, `temp/gui_acceptance_m4.txt`) | Both PDFs detected (3 + 3 pages, `WAITING 3` each) -> both configured, config order `[manualis, appendix]` -> RUN CURRENT PDF: manualis `WAITING -> RUNNING -> DONE` x3 while appendix stays `WAITING 3` -> RUN ALL ENABLED PDFs: appendix DONE x3 -> appendix grew to 4 pages: `CONFIG STALE (stored: 3, current: 4)` with `config.json` unchanged -> RECONCILE: page 004 WAITING, states kept -> locked output + RESET in manualis: `manualis.pdf#2 WAITING -> ERROR` **while** `appendix.pdf#4` ran to DONE -> RETRY PROJECT ERRORS: `ERROR -> RUNNING -> DONE` -> closed/reopened: every state persisted, 7/7 outputs (`manualis__001..003.ai`, `appendix__001..004.ai`) -> MASTER SHA256 unchanged -> 0 Illustrator documents open. Screenshots: `temp/gui_m4_pdf.png`, `temp/gui_m4_run.png`, `temp/gui_m4_reopen.png` |
| **GUI acceptance, visual page browser** (`temp/run_gui_acceptance_m5.py`, `temp/gui_acceptance_m5.txt`) | Thumbnails for `manualis.pdf` (3 pages, states printed on each tile) -> click 001 / 003: preview + page info (322 x 447 mm) follow, the mapping row follows too -> Ctrl+click 002+003 and `ASSIGN TEMPLATE TO SELECTED` -> `section_blue.ai` in `config.json` -> switch to `appendix.pdf` (its thumbnails) and back (cached, 0.33 s) -> RUN SELECTED x3: tiles `WAITING -> RUNNING -> DONE`, `state.json` identical -> locked output + RESET: tile `ERROR` with `OUTPUT_PREP_FAILED: ... WinError 32 ...` and attempts -> RETRY: `ERROR -> RUNNING -> DONE` -> close/reopen: tile text == `state.json`, config untouched -> MASTER SHA256 unchanged -> 0 Illustrator documents open. Screenshots: `temp/gui_m5_a_thumbnails.png`, `gui_m5_b_assigned.png`, `gui_m5_c_pdf_b.png`, `gui_m5_d_error.png`, `gui_m5_e_reopen.png` |
| **Preview performance, 160 pages** (`temp/preview_perf.py`, `temp/preview_perf_m5.txt`) | open + queue 160 thumbnails = 1.3 ms with 0 synchronous renders -> first thumbnail after 0.03 s -> progressive (2 s: 152) -> all 160 + 1 preview in 2.2 s (14 ms each) -> cache 161 files / 0.2 MB -> fully cached pass 0.04 s (0.3 ms each) -> document switch mid-render: 131 pending requests dropped, 0 foreign pages delivered; a real photo PDF renders ~110 ms per thumbnail |
| Adapter handshake (fake Illustrator) | stale result deleted, matching result accepted, mismatching result rejected + logged, late result picked up, timeout with log tail, COM error as `ERROR` result |
| Bulk mapping, real GUI + Illustrator, 36 page JOB (`temp/run_gui_acceptance_m6.py`, `temp/gui_acceptance_m6.txt`) | PASS, 16 steps: range dialog rejects `0` and `99` with the core messages; ASSIGN 1 / 2-5 / 6-20 (USE DEFAULT) / 21 land in `config.json`; COPY 2-5 -> PASTE 22-25; SAVE PRESET -> 6 range rules (`1`, `2-5`, `6-20`, `21`, `22-25`, `26-36`); AUTO MAP BY NUMBER picks 1/2/21 and never MASTER; reset all pages -> preset preview ("Mainīsies 10 lapas", "Konfliktu nav") -> reapply restores the plan byte for byte; VALIDATE 30 checks / 0 errors; 5 real pages processed (DONE) and every output proven by its template: page 1 `COVER-TEMPLATE` 520x720, page 2 `INTRO-TEMPLATE` 460x620, page 6 MASTER 411x397, page 21 `SEP-TEMPLATE` 460x520, page 22 (pasted range) `INTRO-TEMPLATE` 460x620; MASTER SHA256 unchanged; Illustrator documents 0 |
| Mapping rules (unit) | 48 tests: range syntax and its rejections, bulk assignment/enable/layer, numbered mapping (natural sort, MASTER excluded, ambiguity reported, unnumbered/out-of-range), copy/paste (cross PDF, page-count mismatch, offsets, enabled opt-in, no runtime fields), presets (schema, round trip, conflicts, replace_all, UTF-8 names) |
| Mapping through the GUI controller | 17 tests: every MAPPING action through `AppController` into `config.json` + queue, run history survives a bulk edit, cross-document paste, preset preview/apply, mutation-funnel counter (8 mutations -> 8 hook calls) and a guard that the controller owns no mapping rule |
| Production preflight + reports, real GUI + Illustrator, 2 PDFs / 9 pages (`temp/run_gui_acceptance_m7.py`, `temp/gui_acceptance_m7.txt`) | PASS, 13 steps: `[PREFLIGHT PROJECT]` on the real GUI -> `Overall READY` (PDF OK, Pages 9, Templates OK, Missing templates 0, Duplicate outputs 0, Output writable YES, Illustrator READY 29.8.3, Disk space OK (97 GB), Queue READY); template `001_cover.ai` removed -> `NOT READY` with `[TEMPLATES] Konfigurētie template: trūkst: 001_cover.ai` and RUN blocked; restored -> `READY`; real run of 9 pages with a locked output + overwrite -> exactly one `ERROR` (magazine l.2); the pass wrote `report_20260923-214637.txt/.json` (`RUN ALL ENABLED`, DONE=8 ERROR=1, error row for page 2); RETRY ERRORS -> 9 DONE with `report_20260923-214644.txt/.json` (`RETRY ERRORS`, ERROR=0, `retries=1`); report counts `WAITING/RUNNING/DONE/ERROR/SKIPPED/INTERRUPTED` == state.json (0/0/9/0/0/0); both reports still on disk (immutable); 9 outputs; MASTER SHA256 unchanged; Illustrator documents 0 |
| Preflight (unit) | 25 tests: clean project READY with all seven sections OK; read-only (config/state/AI_OUT untouched); Illustrator contacted only when asked; unavailable/broken COM is an ERROR; missing PDF (warning with another document, ERROR as the only one); CONFIG STALE (warning next to a healthy document, ERROR alone, RECONCILE hint); template named in config but missing (ERROR); missing default template (ERROR); empty template folder (ERROR); unwritable AI_OUT (ERROR); duplicate outputs inside a document and across documents (ERROR); existing output -> SKIP warning; stale RUNNING / item outside the plan (warnings); corrupt state.json (warning, still READY); disk thresholds (warning / error / unreadable drive); TXT and JSON agree |
| Job reports (unit) | 16 tests: duration formatting; counts match state.json; objects processed and retries; ERROR/INTERRUPTED rows with type, message and attempts; report from disk without a summary; JSON + TXT written into `JOB/LOG/reports`; TXT/JSON consistency for every state; immutable (`report_<stamp>-2.json` beside the first, first untouched); writing touches neither config nor state; UTF-8 Latvian job/document names without mojibake; broken report file handled; a report per pass (RUN ALL / RUN SELECTED / empty pass); an aborted pass names the reason; report counts stay in sync after a retry; a failed report write never breaks a pass |
| Plan snapshots + undo, real GUI, 36 page JOB (`temp/run_gui_acceptance_m8.py`, `temp/gui_acceptance_m8.txt`) | PASS, 11 steps: AUTO ASSIGN TEMPLATES materialises the plan (0 snapshots before it); ASSIGN TO RANGE 6-35 -> `002_intro.ai` creates snapshot 1 whose content is byte-equal to the previous plan (meta: 1 PDF / 36 pages, no `state`/`attempts` key); `[UNDO PLAN CHANGE]` restores the original mapping and adds the recovery copy (`kind=restore`); a second range edit + APPLIED PRESET produce snapshots 2-4; `[RESTORE SNAPSHOT]` of an older copy puts that plan back and keeps the pre-restore plan; after a GUI reopen the same 5 snapshots are listed and the plan persists; `state.json` counts unchanged (`WAITING 36`) and all 36 `job_id`s identical; every history file is plan-only; Illustrator documents 0 |
| Plan history (unit) | 17 tests: snapshot before a bulk mutation keeps the previous plan (with documents/pages/config version metadata), plan-data-only payload, timestamp names never reused (`-2`), no snapshot without a plan, undo restores the exact previous config (and is itself undoable), undo with nothing to undo returns None, undo survives a corrupt snapshot, restore snapshots the current plan first and refuses a corrupt/wrong-version file, retention keeps the newest and never a pinned copy, `keep=0` disables pruning, a failed write leaves no file and no config change, history never touches state.json or outputs, v1 config is snapshotted as v2, multi-PDF plans with UTF-8 names round trip without mojibake, human readable summaries |
| Plan history through the GUI | 13 tests: a bulk edit snapshots the plan before the change (reason + `bulk-assign` kind), every mutation kind is recorded (`bulk-assign`, `preset`, `auto-map`, `plan`), a no-op edit creates no snapshot, an unwritable snapshot blocks the mutation, UNDO restores the previous plan and keeps the queue states (ERROR stays ERROR with its attempts), undo is itself undoable, undo without history reports nothing, RESTORE puts an older plan back (recovery copy listed), restore accepts a path and rejects an unknown name, a corrupt snapshot is refused without touching the plan, the list survives a corrupt file, and the history survives a GUI reopen |
| Packaged application, real Illustrator, 2 PDFs / 7 pages (`temp/run_packaged_acceptance_m9.py`, `temp/packaged_acceptance_m9.txt`) | PASS, 10 steps: layout (`Cleanup AI 2026.exe`, `program/python314.dll`, `program/base_library.zip`, `jsx/*`, `config/default_config.json`, `VERSION`, `logs/`, no `Illustrator.exe`), 70.2 MB, PE subsystem 2 (GUI, no console) and ProductVersion 0.9.0, `--version` and `--diagnose` from a different working directory (paths come from the exe, no `[FAIL]`), packaged `--preflight-project` READY on a Latvian project path, `--run-all` -> 7 DONE in Illustrator with `state.json` and an immutable report (`app_version` 0.9.0, `pdfs` 2), AI_OUT 7 files with Latvian names, GUI window opened (screenshot) + `<install>/logs/app.log` startup record + closed with code 0, shortcut tool created only the explicit `.lnk` (desktop untouched), `Illustrator Documents.Count == 0` |
| Packaging contract (unit) | 22 tests: source layout uses the repository, `PDF_AI_BATCH_ROOT`/`PDF_AI_BATCH_HOME` overrides, a simulated frozen build derives app root + jsx + config + runtime + logs from the .exe, works from any working directory, falls back to the PyInstaller bundle and then the repository for the JSX assets, uses `%LOCALAPPDATA%` when the install folder is read only; diagnostics in source and in a broken install (missing JSX/config are `[FAIL]`, JSON serialisable), Illustrator is contacted only with `check_illustrator=True`, unreachable Illustrator is reported, a windowed build still gets a stream (console or file); `VERSION` == `pdf_ai_batch.__version__`, the spec covers the assets/COM libraries/no Illustrator/`COLLECT`/windowed-vs-debug, the build script runs the gates + verifies + smoke tests, the shortcut tool exists and is opt-in, `build/`+`dist/` are ignored, and no module outside the adapter imports win32com |
| Frozen baseline | generated, ES3 compile verified, hash recorded |

## Partially working / not yet verified

* **Physical folder rename pending.** The repository identity is already
  `sviskis/Cleanup_AI2026` / display name *Cleanup AI 2026* (see
  `CHANGELOG.md`, commit `chore: rename project to Cleanup_AI2026`), but the local
  folder is still `PDF_Cleanup_AI2026` because Windows refuses to rename a folder
  that an editor has open (VS Code holds the workspace root). Close the folder in
  VS Code, then from a plain PowerShell:

  ```powershell
  Set-Location 'C:\Users\libri\OneDrive\Dokumenti\CLINE'
  Rename-Item -LiteralPath 'PDF_Cleanup_AI2026' -NewName 'Cleanup_AI2026'
  ```

  Nothing else has to change: every runtime path is derived from its own location,
  git does not store the folder name and `origin` already points at the new
  repository. `.venv\Scripts\python.exe` keeps working; only the unused
  `activate.ps1` / `activate.bat` keep the old path (`docs/PYTHON_ENV.md`).
* `template_mode = "saveas"` (real `.ait` templates) is implemented in the worker
  but has not been exercised with a real `.ait` file.
* The visual result of the shared cleanup engine in the new pipeline is covered
  only by the manual checklist (`docs/TESTING.md` §2).
* The preview pane has no per page text extraction, no OCR and no content based
  template suggestion - by design (`docs/GUI.md` "Not in this milestone"). The
  preview cache is never cleaned automatically inside the GUI; delete
  `JOB/.cache` by hand or let `prune()` keep it bounded (200 MB / 4000 files).

## Known bugs / open issues

* The Windows console code page is switched to 65001 for UTF-8; in an old
  PowerShell host captured output can still look garbled (the log files are always
  correct UTF-8).
* Carried over from the reference implementation and kept deliberately: empty
  `catch {}` blocks around Illustrator calls, the two unused "preserve" switches,
  and the `JOB\ERROR` folder that is created but not written to (project level
  error reports go to `logs/errors/<timestamp>/` for the legacy app).

## Next milestone

1. Milestone 10 - production hardening to v1.0.0: the full test matrix (page counts
   1 / 14 / 100 / 300+, 1 and 10 PDFs, spaces / Latvian / long / OneDrive paths,
   Illustrator running or not, restart during recovery, missing or corrupt files,
   locked or existing outputs, ERROR/INTERRUPTED/retry/skip/reset, config migration and
   reconcile, 100+ page lazy previews), a soak test on 100+ real pages, then the
   documentation freeze and the v1.0.0 tag.
2. Regression R1-R5 against `legacy/current_working_v10.jsx` on the same job, and a
   real `.ait` template run (`template_mode = "saveas"`).
3. "Stop after the current page" for the batch loop (now: close the window and
   `CONTINUE PROJECT`, or Ctrl+C plus `--continue`).
4. Remember the last JOB (and its active document) between GUI sessions.
5. Escape non-ASCII in the legacy `src/**/*.jsx` modules (GUI only, not the worker).
6. Optional: a thumbnail size preference, "CLEAR PREVIEW CACHE" in the GUI, a preview
   of the assigned template next to the page preview, per document RECONCILE report and
   "RECONCILE ALL", a report browser inside the GUI, manually named/pinned snapshots,
   an application icon (`assets/app.ico`) and an installer.

