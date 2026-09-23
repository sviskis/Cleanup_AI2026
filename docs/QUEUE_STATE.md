# Queue and persistent state (milestones 2 and 4)

Repository: `sviskis/Cleanup_AI2026` · local folder `Cleanup_AI2026` · display name Cleanup AI 2026

Companion documents: `ARCHITECTURE.md` (the pipeline and the JSON contract),
`MIGRATION_PLAN.md` (phase order), `docs/TESTING.md` (how to run everything),
`STATUS.md` (current state).

## 1. What this milestone adds

The one page pipeline (`run_one`) is proven. Milestone 2 puts a **persistent queue**
on top of it:

* every page of a PDF becomes a queue item in `JOB/CONFIG/state.json`
* items move through `WAITING -> RUNNING -> DONE | ERROR | SKIPPED`, with
  `INTERRUPTED` as the recovery state after a crash
* a batch keeps running when one page fails, and reports a final summary
* a restart can always be resumed (`--continue`), errors can be retried
  (`--retry-errors`), and finished pages are never redone by accident

No GUI, no change to the cleanup algorithm, no change to the Python <-> JSX
contract. The queue only uses the proven `IllustratorAdapter.run_job()` path;
COM still lives exclusively in `pdf_ai_batch/adapters/illustrator.py`.

## 2. State model and state machine

| State | Meaning | Can be run again? |
| --- | --- | --- |
| `WAITING` | queued, will be picked up by `--run-all` / `--continue` | yes |
| `RUNNING` | a worker run is in flight (written **before** Illustrator is asked) | — |
| `DONE` | worker returned `OK` **and** the output AI exists | only via `--reset` |
| `ERROR` | the attempt failed (worker error, missing output, broken template, COM) | via `--retry-errors` |
| `SKIPPED` | deliberately not processed (output already there, manual `--skip`) | only via `--reset` |
| `INTERRUPTED` | was `RUNNING` when the session ended | via `--continue` / `--retry-interrupted` |

```text
                     ┌──────────────────────────── retry_errors ─────────────┐
                     │                    (ERROR -> WAITING)                  │
                     v                                                       │
   ┌─────────┐   run    ┌─────────┐   OK + output exists   ┌──────┐          │
   │ WAITING ├─────────>│ RUNNING ├───────────────────────>│ DONE │          │
   └────┬────┘          └─┬─┬─┬───┘                        └──────┘          │
        ^                │ │ │                                                │
        │   reset_item   │ │ └──── OK but no usable output ──> ┌───────┐     │
        ├────────────────┘ │                                    │ ERROR ├─────┘
        │                  │    worker ERROR / broken template  │       │
        │                  └───────────────────────────────────>└───┬───┘
        │                                                           │ reset_item
        │                  worker SKIP / output already there      │
        │                  ────────────────────────> ┌─────────┐   │
        ├──────────────────────────────────────────  │ SKIPPED │<──┘
        │                          reset_item        └─────────┘
        │
        │   retry_interrupted / continue
        │        ┌──────────────┐   session ends while RUNNING
        └────────┤ INTERRUPTED  │<──────────────── (startup recovery)
                 └──────────────┘
```

Rules that the tests freeze (`pdf_ai_batch/tests/test_state.py`,
`pdf_ai_batch/tests/test_queue.py`):

* **DONE needs both**: a matching worker result with `status == OK` **and** an
  existing, non-empty output file (`pagejob.output_ready`). "OK but no output"
  becomes `ERROR` with `error_type = OUTPUT_MISSING`.
* **A stale `RUNNING` is never `DONE`**: at startup it becomes `INTERRUPTED` and
  stays runnable.
* **An attempt is counted when a run really starts** (the `RUNNING` write), not on
  reset/skip/recovery.
* **`DONE` and `SKIPPED` are terminal**: only `--reset` (or `--build --reset-queue`)
  puts them back into the queue.

## 3. `state.json` schema

Path: `JOB/CONFIG/state.json`. Written with `core/jsonio.write_json_atomic`
(temp file + `os.replace`), UTF-8, LF. One item per page, in plan order.

```json
{
  "version": 1,
  "session_id": "20260923-180046-a33417",
  "job_root": "C:/Users/libri/OneDrive/Dokumenti/CLINE/Cleanup_AI2026/temp/QUEUE_JOB",
  "created": "2026-09-23 18:00:46",
  "updated": "2026-09-23 18:01:21",
  "items": [
    {
      "pdf_id": "mans_fails",
      "job_id": "mans_fails_p001",
      "page": 1,
      "state": "DONE",
      "enabled": true,
      "pdf": "C:/.../QUEUE_JOB/PDF/mans_fails.pdf",
      "template": "C:/.../QUEUE_JOB/TEMPLATE/MASTER_AI_TEMPLATE.ai",
      "output": "C:/.../QUEUE_JOB/AI_OUT/mans_fails__001.ai",
      "layer": "ARTWORK",
      "template_mode": "copy",
      "clear_layer": true,
      "overwrite": false,
      "last_run_id": "20260923-180047-a81347",
      "error_type": "",
      "error_message": "",
      "attempts": 1,
      "created": "2026-09-23 18:00:46",
      "updated": "2026-09-23 18:00:52",
      "started": "2026-09-23 18:00:47",
      "finished": "2026-09-23 18:00:52"
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `version` | schema version (`1`); a different version is reported, not trusted blindly |
| `session_id` | id of the session that wrote the file last (`new_run_id()` format) |
| `job_root`, `created`, `updated` | JOB folder and document timestamps |
| `pdf_id` | document identity: the PDF stem (`manualis`, `appendix`); written since milestone 4, derived from `pdf` when an older file is read |
| `job_id` | `<pdf_id>_p<page:03d>` — stable identity, also used as the worker `job_id` |
| `page` | 1 based page number |
| `state` | one of the six states above |
| `enabled` | `false` = planned but not to be run (used by `config.json` and `set_enabled`) |
| `pdf`, `template`, `output` | **absolute, forward slashed** paths, exactly like the contract |
| `layer`, `template_mode`, `clear_layer`, `overwrite` | what the next request will carry |
| `last_run_id` | run id of the last attempt (matches `runtime/current_job.json`) |
| `error_type`, `error_message` | the CURRENT failure reason (truncated to 1500 chars) |
| `attempts` | real runs started for this page (incremented only on `RUNNING`) |
| `created`, `updated`, `started`, `finished` | `YYYY-MM-DD HH:MM:SS` timestamps, same format as the logs |

Everything needed to rebuild a request is in the file: `pdf`, `page`, `template`,
`output`, `layer`, `clear_layer`, `overwrite`, `template_mode`, `job_id`.

### Corrupted state

`state.load_state()` never raises. It reports problems (bad JSON, wrong shape,
unknown state, relative path, duplicate `job_id`) and keeps every item it could
read. `BatchQueue.open()` logs each problem and copies the file aside as
`CONFIG/state.corrupt-<timestamp>.json` before the queue is used; with no readable
item the operator can simply rebuild (`--run-all` or `--build`).

## 4. Queue API (`pdf_ai_batch/core/queue.py`)

| Function | Behaviour |
| --- | --- |
| `BatchQueue.open(project, adapter=...)` | load `state.json`, quarantine a broken file, `RUNNING -> INTERRUPTED` |
| `build_queue(pdf=..., pdfs=...)` | plan the pages of the JOB (all documents by default, `pdf`/`pdfs` narrow it) and merge them into state: new pages become `WAITING`, existing items keep state/attempts/errors, plan fields are refreshed, pages outside the plan are disabled (never deleted) |
| `run_documents([...])` | run the backlog of specific documents (the GUI's RUN CURRENT PDF); the whole project plan is refreshed first |
| `reconcile_document(pdf)` | explicit RECONCILE after a page count change (`core/pagejob.apply_reconcile`) |
| `duplicate_outputs()` | output file names that more than one item would write (the pass aborts before the first Illustrator call) |
| `document_progress()` | per document counts + processed pages, in queue order |
| `run_next()` | run the first runnable item (`WAITING`/`INTERRUPTED`) |
| `run_all_enabled(rebuild=True)` | refresh the plan, then run every enabled runnable item of every document |
| `continue_queue()` | resume: `WAITING` + `INTERRUPTED` only, never `DONE`/`SKIPPED`/`ERROR` |
| `retry_errors(run=True)` | `ERROR -> WAITING` and run them (all documents) |
| `retry_interrupted(run=True)` | `INTERRUPTED -> WAITING` and run them |
| `skip_item(id)` | mark one item `SKIPPED` (`DONE` must be reset first) |
| `reset_item(id)` | back to `WAITING`, works on `DONE`/`SKIPPED` too |
| `set_enabled(id, bool)` | enable/disable an item without touching its state |
| `status_rows()` / `status_table()` | the compact `PDF / PAGE / STATE / OUTPUT` table plus the per document summary |
| `summary()` | counts per state, per document rows + the statistics of the last pass |
| `find(id, pdf=...)` | by `job_id`, page number or output name; a bare page number is ambiguous in a multi PDF JOB and raises a clear error |

`build_queue` refreshes **plan fields** only (`template`, `output`, `layer`,
`template_mode`, `clear_layer`, `overwrite`, `enabled`). Run history
(`state`, `attempts`, `last_run_id`, `error_*`, timestamps) is never lost by a
rebuild. Important consequence: `--run-all` re-applies the plan, while
`--continue` uses the paths stored in `state.json` (that is why a hand-tuned or
temporarily broken template stays broken under `--continue` and is repaired by the
next `--run-all`).

Since milestone 4 the queue is **per document**: `JOB/CONFIG/config.json` version 2
holds one plan per PDF, items carry `pdf_id`, and the order is document order (from
`documents[]`) followed by page number. A document that is disabled, missing or
cannot be planned has its items disabled - never reset - so its mapping and its
history survive until the file is back.

## 5. CLI (`pdf_ai_batch/batch.py`)

```powershell
# create / refresh the queue of the WHOLE project (every configured PDF)
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\QUEUE_JOB --build --pages 1-4

# the whole backlog, or only one document
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\QUEUE_JOB --run-all
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\MULTI_JOB --pdf appendix.pdf --run-all

# resume after a crash / a Ctrl+C / a closed window (every document)
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\QUEUE_JOB --continue

# failed pages only
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\QUEUE_JOB --retry-errors
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\QUEUE_JOB --retry-interrupted

# page count changed? reconcile ONE document explicitly
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\MULTI_JOB --pdf appendix.pdf --reconcile

# one page, or the report
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\QUEUE_JOB --run-next
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\QUEUE_JOB --status

# single items (id = job_id, page number scoped with --pdf, or output file name)
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\MULTI_JOB --reset appendix_p003
.venv\Scripts\python.exe -m pdf_ai_batch.batch --job temp\MULTI_JOB --pdf manualis.pdf --skip 2
```

Extras used by the tests: `--dry-run`, `--max-items`, `--no-build`, `--overwrite`,
`--pages "1-3,5"`, `--template`, `--layer`, `--template-mode`, `--timeout`,
`--json report.json`, `--quiet`, `--skip-illustrator-check`.

`--status` prints the table asked for in the milestone (PDF column since M4):

```text
PDF       PAGE  STATE         OUTPUT
manualis  001   DONE          C:/JOB/AI_OUT/manualis__001.ai
manualis  002   SKIPPED       C:/JOB/AI_OUT/manualis__002.ai
manualis  003   DONE          C:/JOB/AI_OUT/manualis__003.ai
appendix  001   DONE          C:/JOB/AI_OUT/appendix__001.ai

PDFs: 2 | Lapas kopā: 4
  manualis.pdf: 2/3 apstrādātas | WAITING=1 DONE=2 ...
Kopā: WAITING=1 RUNNING=0 DONE=3 ERROR=0 SKIPPED=1 INTERRUPTED=0 (kopā 4, iespējoti 4, rindā 1)
```

Exit codes: `0` no `ERROR`/`INTERRUPTED` left in the queue, `1` at least one is
left, `2` usage/setup problem. `app.py --batch ...` forwards to the same CLI.

## 6. Failure policy

* **A page level failure never stops the batch.** Every item runs inside its own
  try/except; the failure is recorded and the next item starts.
* **Only an adapter/COM failure aborts the pass** (the environment is broken, not
  the page): the item becomes `ERROR` with `error_type = COM`, the pass stops, and
  the remaining items stay `WAITING`, so a later `--continue` picks them up.
* **`--overwrite` decides about existing outputs.** Without it an existing output
  is `SKIPPED` (never silently replaced); with it the file is replaced.
* **A failed attempt cleans up after itself**: the template copy (or a partial AI
  the worker left behind) is deleted, so `--retry-errors` really re-runs the page
  instead of skipping it because of a leftover file.
* **A missing template or an unwritable output is `ERROR`**
  (`error_type = OUTPUT_PREP_FAILED`), never `SKIPPED`.

## 7. Start-up recovery and CONTINUE

1. Every item writes `RUNNING` (and saves `state.json`) **before** Illustrator is
   asked to do anything.
2. If the process dies (crash, power loss, Ctrl+C, closed window), the file keeps
   that one page as `RUNNING`.
3. The next command that opens the queue turns it into `INTERRUPTED` and saves the
   file. It is never `DONE`, it is never left `RUNNING`, and it stays runnable.
4. `--continue` runs `WAITING` + `INTERRUPTED` (the recovered page included), skips
   `DONE`/`SKIPPED` and leaves `ERROR` for `--retry-errors`.
5. A leftover document inside `AI_OUT` (from a killed run) is closed before the
   pass starts (`close_documents(under_dir=AI_OUT)`), so Illustrator is clean.

## 8. Tests

Without Illustrator (`pytest`):

* `pdf_ai_batch/tests/test_state.py` - model, atomic write, UTF-8, corrupt file,
  duplicate ids, unknown states, recovery, transitions, attempt counting, summary.
* `pdf_ai_batch/tests/test_queue.py` - the whole queue against a fake adapter:
  `WAITING -> RUNNING -> DONE`, `-> ERROR`, `RUNNING -> INTERRUPTED`, retry/continue
  semantics, "DONE/SKIPPED does not rerun", "one ERROR does not stop the queue",
  "OK without output is ERROR", `state.json` written after every item, corrupted
  state quarantine, attempts, summary counts, skip/reset, overwrite, the
  missing-template error, and the COM rule (the core modules contain no COM).

With Illustrator: `temp/run_queue_batch_test.py` runs the scenario of section 9 and
writes every CLI output to `temp/queue_test_logs/`.

### 8b. Fake-adapter batch (no Illustrator, runnable example)

The queue only needs an object with `run_job(request) -> JobResult`, so a whole
batch can be exercised without Illustrator (this is exactly what the tests do):

```python
from pdf_ai_batch.core.project import JobProject
from pdf_ai_batch.core.queue import BatchQueue
from pdf_ai_batch.tests.fakes import FakeIllustrator

project = JobProject.open("temp/QUEUE_FAKE")          # needs PDF/ and TEMPLATE/
adapter = FakeIllustrator(state_path=project.state_path)
queue = BatchQueue.open(project, adapter=adapter)

queue.build_queue(pages="1-3")
summary = queue.run_all_enabled(build_kwargs={"pages": "1-3"})

print(summary.format())
print(queue.status_table())
print("Illustrator calls:", adapter.pages_run())
```

Verified output (`temp/run_fake_queue_example.py`):

```text
Kopsavilkums: WAITING=0 RUNNING=0 DONE=3 ERROR=0 SKIPPED=0 INTERRUPTED=0 (kopā 3, iespējoti 3)
Šajā piegājienā: DONE=3 SKIPPED=0 ERROR=0 objekti=9

PAGE  STATE         OUTPUT
001   DONE          C:/.../temp/QUEUE_FAKE/AI_OUT/mans_fails__001.ai
002   DONE          C:/.../temp/QUEUE_FAKE/AI_OUT/mans_fails__002.ai
003   DONE          C:/.../temp/QUEUE_FAKE/AI_OUT/mans_fails__003.ai

Illustrator calls: [1, 2, 3]
```

## 9. Real Illustrator run (evidence)

Run on 2026-09-23 against `temp/QUEUE_JOB` (14 page PDF, page 3 pinned to its own
template through `config.json`), driven by `temp/run_queue_batch_test.py`:

| Step | Command | Result |
| --- | --- | --- |
| 1 | `--build --pages 1-4` | 4 items `WAITING` |
| 2 | stale `AI_OUT/mans_fails__002.ai` created | - |
| 3 | `--run-all` | `001 DONE`, `002 SKIPPED`, `003 DONE`, `004 DONE` |
| 4 | `--status` | the table above |
| 5 | `--run-all --pages 1-4` again | nothing reruns (`DONE=0 SKIPPED=0 ERROR=0` in the pass summary) |
| 6 | `TEMPLATE/003_pagina.ai` removed, `--reset 3 --reset 4 --run-all --overwrite` | `003 ERROR` (`OUTPUT_PREP_FAILED`), **11 further pages `DONE` in the same pass** (`DONE=11 ERROR=1`, 43 objects) - one bad page did not stop the queue |
| 7 | template restored, `--retry-errors` | `Pārliku uz WAITING: mans_fails_p003` -> `003 DONE` (attempts 1 -> 2 -> 3 across the scenario) |
| 8 | `--reset 4`, `--run-all --pages 1-4 --overwrite` killed while page 4 was `RUNNING` | on disk `004 RUNNING`; `--status` -> `WARNING Atjaunoju pārtrauktos elementus (mans_fails_p004) -> INTERRUPTED`, exit 1; `--continue` -> `[1] 004 DONE` |

Verified in the same run: `state.json` changed after every page (per item
`started`/`finished` timestamps and `attempts`), Illustrator had **0 documents open**
afterwards, the outputs are real AI files (20-60 MB each) and the MASTER template
was never modified. Final counts of the 14 page job: `DONE=13 SKIPPED=1`.

## 10. Deliberate limitations

* One PDF per queue (multi PDF jobs are a later milestone; `state.json` already
  carries `pdf` per item, so the format does not have to change).
* No per page time estimate or heartbeat - `started` plus the log timestamps are
  all there is.
* `--max-items` limits a pass; there is no "stop after the current page" switch in
  the CLI yet (Ctrl+C leaves a recoverable `RUNNING` item, which is the important
  part).
* `state.json` keeps the current error only; the full history is in
  `JOB/LOG/app.log` and `JOB/LOG/batch_<timestamp>.log`.
* The queue does not verify the *content* of the output AI (the worker reports the
  statistics); the DONE rule is "exists and is not empty".
* `--run-all` re-applies the plan, so a hand-edited `state.json` template is
  repaired by the next rebuild (use `--continue` to keep it).

