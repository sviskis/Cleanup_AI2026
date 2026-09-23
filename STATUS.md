# Current Status

Version: 0.5.0
Repository: `sviskis/Cleanup_AI2026` · local folder `Cleanup_AI2026` · display name Cleanup AI 2026
Status: **Milestone 4 done - one JOB now holds several PDFs (each with its own plan, outputs and persistent states); the GUI drives them with RUN CURRENT PDF / RUN ALL ENABLED PDFs / CONTINUE PROJECT / RETRY PROJECT ERRORS, shows CONFIG STALE / MISSING PDF and reconciles explicitly; a real two PDF Illustrator run passed**

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
| `pytest` | 215 tests (Python 3.14 venv): contract, absolute paths, encoding, state, queue, multi PDF queue (identity, drift, reconcile, collisions), GUI controller/tasks/window, GUI multi PDF |
| `app.py --diagnose` | paths and interpreter reported |
| `run_one --preflight-only` (14 page demo PDF) | 17 checks OK, request JSON written to `runtime/current_job.json` |
| `run_one --dry-run` | valid contract request produced |
| **`run_one --job temp\REAL_TEST --pdf mans_fails.pdf --page 3`** | **MILESTONE OK**: absolute forward slash request paths, `Statuss : OK`, `Objekti : 3`, real output AI, MASTER template untouched, 0 documents left open |
| **Same run with a Latvian job folder** (`temp\Realitātes tests LV`, PDF `Māja Āčēģī.pdf`) | **MILESTONE OK**: Latvian characters survive request JSON, worker log and result JSON without mojibake |
| **Batch queue, real Illustrator** (`temp\QUEUE_JOB`, `temp/run_queue_batch_test.py`) | `--run-all` -> 001 DONE / 002 SKIPPED / 003 DONE / 004 DONE; second pass reruns nothing; lost per-page template -> 003 ERROR + 004 DONE; `--retry-errors` -> 003 DONE; process killed during page 4 -> `--status` shows 004 INTERRUPTED -> `--continue` -> 004 DONE |
| **13 page pass** of the same PDF through the queue | `DONE=13 SKIPPED=1`, `state.json` written after every page, 0 documents left open |
| **GUI acceptance, real Illustrator** (`temp/run_gui_acceptance.py`, `temp/gui_acceptance.txt`) | Open JOB -> PDF shows 14 pages (PyMuPDF) -> 14 mapping rows with the persisted states -> RESET SELECTED + manual template change -> VALIDATE 24 checks / 0 errors -> RUN SELECTED: live `WAITING -> RUNNING -> DONE` x3 -> forced ERROR (`OUTPUT_PREP_FAILED`, locked output) -> RETRY ERRORS: `ERROR -> WAITING -> RUNNING -> DONE` -> window closed and reopened: states restored -> 0 Illustrator documents open. Screenshots: `temp/gui_mapping.png`, `temp/gui_run.png` |
| **GUI acceptance, TWO PDFs in one JOB** (`temp/run_gui_acceptance_m4.py`, `temp/gui_acceptance_m4.txt`) | Both PDFs detected (3 + 3 pages, `WAITING 3` each) -> both configured, config order `[manualis, appendix]` -> RUN CURRENT PDF: manualis `WAITING -> RUNNING -> DONE` x3 while appendix stays `WAITING 3` -> RUN ALL ENABLED PDFs: appendix DONE x3 -> appendix grew to 4 pages: `CONFIG STALE (stored: 3, current: 4)` with `config.json` unchanged -> RECONCILE: page 004 WAITING, states kept -> locked output + RESET in manualis: `manualis.pdf#2 WAITING -> ERROR` **while** `appendix.pdf#4` ran to DONE -> RETRY PROJECT ERRORS: `ERROR -> RUNNING -> DONE` -> closed/reopened: every state persisted, 7/7 outputs (`manualis__001..003.ai`, `appendix__001..004.ai`) -> MASTER SHA256 unchanged -> 0 Illustrator documents open. Screenshots: `temp/gui_m4_pdf.png`, `temp/gui_m4_run.png`, `temp/gui_m4_reopen.png` |
| Adapter handshake (fake Illustrator) | stale result deleted, matching result accepted, mismatching result rejected + logged, late result picked up, timeout with log tail, COM error as `ERROR` result |
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

## Known bugs / open issues

* The Windows console code page is switched to 65001 for UTF-8; in an old
  PowerShell host captured output can still look garbled (the log files are always
  correct UTF-8).
* Carried over from the reference implementation and kept deliberately: empty
  `catch {}` blocks around Illustrator calls, the two unused "preserve" switches,
  and the `JOB\ERROR` folder that is created but not written to (project level
  error reports go to `logs/errors/<timestamp>/` for the legacy app).

## Next milestone

1. Regression R1-R5 against `legacy/current_working_v10.jsx` on the same job, and a
   real `.ait` template run (`template_mode = "saveas"`).
2. "Stop after the current page" for the batch loop (now: close the window and
   `CONTINUE PROJECT`, or Ctrl+C plus `--continue`).
3. Remember the last JOB (and its active document) between GUI sessions.
4. Escape non-ASCII in the legacy `src/**/*.jsx` modules (GUI only, not the worker).
5. Optional: per document RECONCILE report in the log file, and a "RECONCILE ALL"
   action for a JOB whose PDFs were all replaced.
