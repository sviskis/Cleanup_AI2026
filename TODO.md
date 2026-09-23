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
- [x] `DONE` only when the worker returned a matching `OK` **and** the output AI
  exists (enforced by `core/pagejob.output_ready` for both `run_one` and the queue).
- [x] Batch summary at the end: DONE / SKIPPED / ERROR / INTERRUPTED counts plus
  aggregated statistics, written to the batch log.
- [ ] Multi PDF queue in one run (each PDF with its own page plan).
- [ ] "Stop after the current page" (now: Ctrl+C leaves a recoverable `RUNNING`
  item for `--continue`).

## P2 - Improvements

- [ ] Escape non-ASCII text in the legacy GUI modules (`src/**/*.jsx`) the same way
      as in `jsx/` (`\uXXXX`), so the ScriptUI labels cannot be mis-decoded either.
      Deliberately out of scope for the contract milestone: `src/` is loaded by the
      GUI entry point, not by the Python worker.
- [ ] Tkinter GUI (`pdf_ai_batch/gui/`): PROJECT, PDF, MAPPING (ttk.Treeview with
      PAGE / USE / TEMPLATE / LAYER / OUTPUT / STATUS), RUN tabs with progress and
      live log.
- [ ] Mapping actions: select all / none / invert, enable / disable selected,
      auto assign templates, assign template manually, move up / down, refresh,
      validate config, run selected, run all enabled.
- [ ] Richer `config.json` workflow: save/load per JOB, remember the last job,
      "add PDF", "add templates" buttons.
- [ ] Preflight report inside the GUI before RUN (same checks as
      `core/validation.py`).
- [ ] Worker heartbeat / progress for very slow pages (optional status file).

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

