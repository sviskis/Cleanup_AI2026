# TODO

Repository: `sviskis/Cleanup_AI2026` · local folder `Cleanup_AI2026` · display name Cleanup AI 2026

## P0 - Critical

- [x] Run the one page milestone in Illustrator (`MIGRATION_PLAN.md` §3) and
      record the outcome in `STATUS.md`.
      Done: `temp\REAL_TEST` (14 page PDF, page 3) and a Latvian job folder both
      returned `Statuss : OK` / `MILESTONE OK`.
- [ ] Test a real `.ait` template end to end (`template_mode = "saveas"`), so the
      Illustrator side conversion path is proven, not just implemented.
- [ ] Regression R1-R5 (`docs/TESTING.md` §2) against
      `legacy/current_working_v10.jsx` on the same job.

## P1 - Important

- [x] Queue + state (`pdf_ai_batch/core/state.py`, `core/queue.py`, `batch.py`):
  `state.json` with atomic writes, WAITING / RUNNING / DONE / ERROR / SKIPPED /
  INTERRUPTED, `RUNNING` recovered to `INTERRUPTED` after a restart, CONTINUE,
  retry errors, retry interrupted, skip/reset, per pass and per queue summaries.
  See `docs/QUEUE_STATE.md`.
- [x] Tkinter GUI (`pdf_ai_batch/gui/`): PROJECT, PDF, MAPPING (ttk.Treeview with
  USE / PAGE / TEMPLATE / LAYER / OUTPUT / STATUS), RUN / LOG with progress and the
  live log, worker thread execution, close safety. See `docs/GUI.md`.
- [x] Mapping actions: select all / none, enable / disable selected, auto assign
  templates, assign template manually (double click or button), use default
  template, refresh, reset selected, validate, run selected, run all enabled.
- [x] Preflight report inside the GUI before RUN (same checks as
  `core/validation.py`, shown in the MAPPING tab and enforced before every run).
- [x] "Add PDF" and "Add templates" buttons + a template chooser that copies an
  outside template into `JOB/TEMPLATE`.
- [x] `DONE` only when the worker returned a matching `OK` **and** the output AI
  exists (enforced by `core/pagejob.output_ready` for both `run_one` and the queue).
- [x] Batch summary at the end: DONE / SKIPPED / ERROR / INTERRUPTED counts plus
  aggregated statistics, written to the batch log.
- [x] Multi PDF queue in one run (each PDF with its own page plan).
      Done: config v2 `documents[]`, `pdf_id` + page identity, per document plans
      and states, `plan_project` / `run_documents`, cross document output collision
      guard, explicit RECONCILE, MISSING PDF handling, PDF/MAPPING/RUN GUI updates
      and a real two PDF Illustrator acceptance (`temp/gui_acceptance_m4.txt`).
      See `docs/QUEUE_STATE.md` and `docs/GUI.md`.
- [x] PDF preview + thumbnail page browser (milestone 5).
- [x] Bulk page mapping + reusable presets (milestone 6): range parsing
      (`1-5,8,10-14`, `*`), ASSIGN TO RANGE, numbered auto mapping (`001_cover.ai` ->
      page 1, MASTER excluded, ambiguity reported), COPY/PASTE MAPPING within and
      across PDFs, USE DEFAULT, CLEAR OVERRIDE, presets in `JOB/CONFIG/presets/` with a
      conflict preview, and one mutation funnel for every plan change. All rules live
      in `pdf_ai_batch/core/mapping_rules.py`; the GUI only collects input
      (`gui/bulk_dialogs.py`). See `docs/GUI.md` §Bulk mapping.
      Done: `pdf_ai_batch/preview/` (PyMuPDF renderer + disposable
      `JOB/.cache/preview` keyed on pdf + mtime + size + page + render size),
      `gui/preview_loader.py` (one worker thread, priority queue, generations, event
      bus), `gui/preview_panel.py` (thumbnail grid with per tile states, large preview
      with FIT / 100% / + / -, page info, error detail, OPEN OUTPUT) and the two way
      synchronisation with the MAPPING Treeview. See `docs/GUI.md`,
      `ARCHITECTURE.md` §3c and `temp/gui_acceptance_m5.txt` (20 step real run).
- [ ] "Stop after the current page" (now: close the GUI and press CONTINUE, or
  Ctrl+C leaves a recoverable `RUNNING` item for `--continue`).
- [ ] Remember the last JOB (and its active PDF) between GUI sessions.

## P2 - Improvements

- [ ] Thumbnail size preference (small / medium / large) and a "CLEAR PREVIEW CACHE"
      button in the GUI (the cache is already bounded and gitignored).
- [ ] Preview the assigned template next to the page preview (`.ai` rasterising is
      not available without Illustrator, so this needs a different source, e.g. a
      stored template thumbnail or a PDF preview export).

- [ ] Escape non-ASCII text in the legacy GUI modules (`src/**/*.jsx`) the same way
      as in `jsx/` (`\uXXXX`), so the ScriptUI labels cannot be mis-decoded either.
      Deliberately out of scope for the contract milestone: `src/` is loaded by the
      GUI entry point, not by the Python worker.
- [ ] Move / up-down buttons for page rows in the MAPPING tab (currently: per page
  template assignment only; layer and output come from the plan/config).
- [ ] Worker heartbeat / progress for very slow pages (optional status file), so the
  GUI can show intra page progress instead of "RUNNING".
- [ ] Show the `JOB/ERROR` folder contents (project level error reports) in the GUI.

## P3 - Future ideas

- [ ] SQLite history of every processed page (input, output, statistics, duration)
      through a small Python layer.
- [ ] ZIP handoff of `AI_OUT` after a batch.
- [ ] Cleanup profiles ("conservative" / "aggressive") read from
      `config/profiles/*.json`.
- [ ] Error screenshot helper (win32com + Pillow) writing `screenshot.png` into the
      legacy `logs/errors/<timestamp>/` folder.
- [ ] Migrate the 12 month calendar pipeline of
      `archive/original/PDF_Deep_Cleanup_12_MENESI_GUI_v6.jsx` as an optional mode.

