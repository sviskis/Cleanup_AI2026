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
  |  core/jsonio.py          atomic read/write, wait for a matching result           |
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

## 4. JOB layout

```text
JOB/
  PDF/       input PDFs (recursive scan, bookkeeping folders skipped)
  TEMPLATE/  MASTER_AI_TEMPLATE.ai (default) + page templates 001_cover.ai, ...
  CONFIG/    config.json, state.json (next milestone)
  AI_OUT/    results: calendar__003.ai
  LOG/       app.log (all sessions) + batch_<timestamp>.log (one per run)
  ERROR/     reserved (layout compatibility)
```

Python creates missing folders (`JobProject.ensure_structure`); the worker never
creates project folders.

## 5. Naming

Python owns output names (`core/naming.py`):

| Input | Output |
| --- | --- |
| `manual.pdf`, page 1 of 42 | `manual__001.ai` |
| `manual.pdf`, page 17 of 42 | `manual__017.ai` |
| `big.pdf`, page 7 of 1000 | `big__0007.ai` |

Width is `max(3, digits(page_count))`; the job id is `manual_p017`. The older
scheme (`manual_p03.ai`) exists only inside the frozen baseline
(`legacy/current_working_v10.jsx`).

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
3. Python owns orchestration; the JSX worker owns Illustrator.
4. Everything exchanged is JSON, defined in `pdf_ai_batch/core/contract.py` and
   mirrored by `jsx/cleanup.jsx` (`statsToContract`) and `jsx/worker.jsx`.

## 10. Related documents

| Document | Content |
| --- | --- |
| [MIGRATION_PLAN.md](MIGRATION_PLAN.md) | the approved migration plan, its status and what is next |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | the legacy single-file JSX application (phase 1) |
| [docs/CODE_ANALYSIS.md](docs/CODE_ANALYSIS.md) | the original reference script, function by function |
| [docs/WORKFLOW.md](docs/WORKFLOW.md) | operating the legacy GUI application |
| [docs/TESTING.md](docs/TESTING.md) | every gate: JSX checks, Python tests, manual checklist |
| [tests/TEST_PLAN.md](tests/TEST_PLAN.md) | test strategy, levels, entry/exit criteria |
| [tools/README.md](tools/README.md) | every development tool and what it verifies |
| [legacy/README.md](legacy/README.md) | the frozen working baseline and its hash |
