# TODO

## P0 - Critical

- [ ] Run the smoke cases S1-S5 and functional cases F1-F10 (`docs/TESTING.md`) in
      Illustrator on a test JOB. The automated level is green, but the new module
      split has never been executed by Illustrator yet.
- [ ] Run the reference comparison R1-R5 against
      `archive/original/PDF_Deep_Cleanup_AI_Template_BATCH.jsx` and record the
      result in `STATUS.md` / `CHANGELOG.md`.
- [ ] Confirm that the MASTER template file is untouched after a batch (hash or
      modification time before/after).

## P1 - Important

- [ ] Add a `TODO`-driven cleanup of the loose legacy files in the project root
      (`PDF_Deep_Cleanup_AI_Template_BATCH.jsx`, `PDF_Deep_Cleanup_AI_Template_BATCH\`)
      once the archived copies are confirmed sufficient. They are currently
      git-ignored but kept on disk.
- [ ] Verify the tile/stacking order after `duplicateSourceLayersIntoArtwork` on a
      complex PDF (F4/R3) and document the expected order.
- [ ] Add a `services/ArchiveService.jsx` that zips `AI_OUT` after a run (handoff).
- [ ] Unit test `isSafeToUngroup` / `isSafeVectorClippingGroup` decision tables by
      extending `tests/jscript/stubs.js` with a fake item model.

## P2 - Improvements

- [ ] Migrate the 12 month calendar pipeline of
      `archive/original/PDF_Deep_Cleanup_12_MENESI_GUI_v6.jsx`: template modes
      (one template / template per month / layer per month), month checkboxes,
      `config\project_info.json`, "SAKĀRTOT JOB SAKNI".
- [ ] Python + win32com helper: launch Illustrator, run `src/Main.jsx` headless
      with `dryRun = true`, collect `logs/project.log`, attach `screenshot.png`
      into the error report folder.
- [ ] Optional JSON config input: a small ExtendScript `JsonReader` so
      `config/default_config.json` can override `Config.jsx`.
- [ ] Diagnostics: optionally write the report to `logs/diagnostics_<ts>.txt`.
- [ ] Page count: remember the last used PDF folder per project (small state file
      in `logs/`).

## P3 - Future ideas

- [ ] SQLite (via a Python helper) history of every processed page: input, output,
      cleanup counters, duration.
- [ ] Batch resume: skip already existing outputs automatically on a second pass
      (today they are reported as `SKIP`, which is already close).
- [ ] Profile presets ("conservative" / "aggressive" cleanup) as
      `config/profiles/*.jsx`.
- [ ] InDesign handoff: place the produced AI files into an INDD layout through an
      `indd_bridge` style COM script.
- [ ] Localisation of the GUI (LV/EN) through a small string table.
