# MIGRATION PLAN - JSX monolith -> Python orchestrator + JSX worker

> **Repository:** `sviskis/Cleanup_AI2026` · **Local folder:** `Cleanup_AI2026` ·
> **Display name:** Cleanup AI 2026

Status legend: **DONE** - implemented and verified, **NEXT** - the immediate next
step, **LATER** - agreed but not started.

This is the approved plan, including every change requested during approval
(single source of truth for the cleanup engine, frozen v10 baseline, json2.js,
pywin32 with attach-then-launch, file based handoff with job_id + run_id, Python
ownership of normal filesystem work, .ait conversion by Illustrator, venv +
recorded interpreter, PyMuPDF authoritative page count, snake_case stats, atomic
state with recovery, milestone-first order).

## 0. Immutable rules

| Rule | Status |
| --- | --- |
| The working cleanup algorithm is the source of truth and is not rewritten | **DONE** - `jsx/cleanup.jsx` is extracted verbatim by line range |
| Exactly ONE copy of the cleanup engine | **DONE** - `src/core/PdfCleanup.jsx` deleted, `src/Main.jsx` includes `../jsx/cleanup.jsx` |
| The current working JSX is frozen before changes | **DONE** - `legacy/current_working_v10.jsx` (2789 lines, SHA256 in `legacy/README.md`) |
| Python owns orchestration, JSX owns Illustrator | **DONE** - `ARCHITECTURE.md` §1 |
| JSON is the contract, no business data through COM | **DONE** - `runtime/current_job.json` / `runtime/current_result.json` |
| Never overwrite the MASTER template | **DONE** - read only; `.ai` copies are made by Python, `.ait` converted by Illustrator `saveAs` |
| Source PDF is always closed without saving | **DONE** - `PDFCleanup.safeClose(sourceDoc, DONOTSAVECHANGES)` |

## 1. Phase order and status

| # | Step | Status |
| --- | --- | --- |
| 1 | Freeze the current working JSX as `legacy/current_working_v10.jsx` | **DONE** |
| 2 | Move the canonical cleanup engine to `jsx/cleanup.jsx`, delete the duplicate, rewire `src/` | **DONE** |
| 3 | Add the JSON layer (`jsx/json2.js`) and lock the contract with shared fixtures | **DONE** |
| 4 | Write `jsx/worker.jsx` (one page per invocation) | **DONE** |
| 5 | Python core: project, pdf_info, naming, template_mapper, config, contract, validation | **DONE** |
| 6 | `adapters/illustrator.py` (pywin32, attach -> launch, file handoff, timeout) | **DONE** |
| 7 | First milestone: one page end to end (`run_one.py`) | **DONE** - two real Illustrator runs recorded in `STATUS.md` |
| 8 | Queue + state: `state.json`, WAITING/RUNNING/DONE/ERROR/SKIPPED, resume, continue, retry | **NEXT** |
| 9 | GUI: Tkinter notebook - PROJECT / PDF / MAPPING / RUN tabs | **LATER** |
| 10 | Batch policy: one bad page must not stop the batch, final summary | **NEXT** |
| 11 | Regression against the frozen baseline, then retire the legacy app | **LATER** |

## 2. What exists now (v0.2.0)

```text
jsx/cleanup.jsx      canonical Illustrator engine (cleanup + document helpers + stats contract)
jsx/json2.js         ES3 JSON polyfill (JSON.stringify / JSON.parse)
jsx/worker.jsx       one page worker: request -> cleanup -> template -> output AI -> result

pdf_ai_batch/
  app.py             CLI entry (--diagnose, --health, --run-one, --gui placeholder)
  run_one.py         the milestone command: one page, one request, one result
  paths.py           repo relative paths (jsx/, runtime/)
  logging_setup.py   LOG/app.log + batch log + UTF-8 console
  core/jsonio.py     atomic IO + wait_for_json (job_id/run_id matching, timeout)
  core/naming.py     manual__017.ai naming, job ids, collision detection
  core/pdf_info.py   discovery, natural sort, page count (PyMuPDF -> pypdf)
  core/template_mapper.py  positional mapping, master exclusion, default fallback
  core/project.py    JOB folders and paths
  core/config.py     config.json validation + atomic save
  core/contract.py   request/result schemas, stats mapping, summary counters
  core/validation.py preflight checks
  adapters/illustrator.py  the only COM code: attach/launch/run_job/close_documents
```

Verification gates (all green):

| Gate | Result |
| --- | --- |
| `tools/check_jsx.ps1` | 2 entry points resolve, ES3 compile OK, 0 errors / 0 warnings |
| `tools/run_tests.ps1` | 79 JSX unit tests + 44 JSON contract tests |
| `pytest` | 80 Python tests |
| `run_one --preflight-only` on a 14 page demo job | all checks OK, request JSON written |

## 3. The one page milestone - how to finish it

The Python half is proven automatically (request written atomically, stale result
deleted, matching job_id/run_id accepted, timeout handling, statistics parsed).
The Illustrator half needs one real run:

```powershell
# 1. a demo job with a real 14 page PDF (placeholder templates)
.venv\Scripts\python.exe tools\make_demo_job.py --root temp\DEMO_JOB --pages 14

# 2. replace temp\DEMO_JOB\TEMPLATE\*.ai with real templates
#    (MASTER_AI_TEMPLATE.ai must contain a layer named ARTWORK)

# 3. validate only (no Illustrator needed)
.venv\Scripts\python.exe -m pdf_ai_batch.run_one --job temp\DEMO_JOB ^
    --pdf calendar.pdf --page 3 --preflight-only --skip-illustrator-check

# 4. the real thing (attaches to Illustrator, launches it when needed)
.venv\Scripts\python.exe -m pdf_ai_batch.run_one --job temp\DEMO_JOB --pdf calendar.pdf --page 3
```

Expected: `Statuss    : OK`, a statistics block, `Output     : ir (...)`, and
`MILESTONE OK`, plus `runtime\current_result.json` carrying the same `job_id` and
`run_id` as the request.

**Status: DONE.** Run on 2026-09-23 against `temp\REAL_TEST` (page 3 of a 14 page
PDF) and against a job folder with a Latvian name (`temp\Realitātes tests LV`,
PDF `Māja Āčēģī.pdf`); both returned `Statuss : OK` and `MILESTONE OK`.

Two contract rules the run proved and that every later milestone must keep (see
`ARCHITECTURE.md` §2 "Paths on the wire" and `docs/TESTING.md` §0):

* the request carries **absolute, forward slash** paths for `pdf`, `template` and
  `output` - Python resolves them, the worker never does, because Illustrator has
  its own current working directory;
* `jsx/` sources are **ASCII only** (`\uXXXX` escapes) - a large BOM-less UTF-8
  `.jsx` is decoded as ANSI by ExtendScript, which turned the worker's Latvian
  literals into mojibake in `runtime/current_result.json`.

## 4. Agreed behaviours not in the code yet

| Requirement | Where it lands |
| --- | --- |
| `state.json` with atomic writes | `pdf_ai_batch/core/state.py` (NEXT) |
| A page left in `RUNNING` after a restart becomes `INTERRUPTED` / `ERROR_RECOVERABLE` and can be retried | `core/state.py` + run tab (NEXT) |
| `DONE` only when the worker returned a matching OK **and** the output AI exists | queue milestone (the rule is already used by `run_one`) |
| CONTINUE after restart, retry errors, stop after the current page | queue + GUI milestones |
| Mapping table (PAGE / USE / TEMPLATE / LAYER / OUTPUT / STATUS) with select all/none/invert, auto assign, manual assign, move up/down, refresh, validate | `gui/mapping_tab.py` |
| Batch summary DONE / SKIPPED / ERROR at the end | queue milestone (`logging_setup` already writes the batch log) |
| Multi PDF queue (several PDFs, each with its own page plan) | queue milestone (one PDF per config, many PDFs per JOB) |

## 5. Non-goals (kept out on purpose)

* No rewrite of the cleanup heuristics - extraction only.
* No Illustrator probing for page counts.
* No monthly / calendar assumptions: generic multi page PDF processing.
* No GUI before the one page milestone passes in Illustrator.
* The legacy ScriptUI app is not deleted until the regression comparison (R1-R5 in
  `docs/TESTING.md`) passes.

## 6. File inventory of the migration

| File | Role |
| --- | --- |
| `legacy/current_working_v10.jsx` | frozen baseline (generated by `tools/freeze_legacy.ps1`) |
| `legacy/README.md` | provenance + hash of the baseline |
| `jsx/cleanup.jsx` | canonical engine (generated by `tools/migrate_extract_sections.ps1`) |
| `jsx/json2.js`, `jsx/worker.jsx` | JSON layer and the one page worker |
| `src/**` | legacy ScriptUI application (kept, includes `../jsx/cleanup.jsx`) |
| `tools/freeze_legacy.ps1` | builds the frozen baseline from `src/` |
| `tools/make_demo_job.py` | builds a demo JOB with a real PDF |
| `tests/fixtures/*.json` | the shared contract fixtures |
| `tests/jscript/test_json_contract.js` | JSX side contract verification |
| `pdf_ai_batch/tests/*` | Python tests (including the adapter handshake) |
