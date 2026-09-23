# Runtime logs

Created and written by `src/services/LogService.jsx` and
`src/services/ErrorService.jsx` while the script runs in Illustrator.

| Path | Written by | Content |
| --- | --- | --- |
| `logs/project.log` | `LogService.flushSessionLog()` | append-only session log, one line per event: `2026-09-23 15:30:10 | INFO | Script started` |
| `logs/errors/<YYYY-MM-DD_HHMMSS>/error.txt` | `ErrorService.writeErrorReport()` | project, version, message, file, line, stack |
| `logs/errors/<YYYY-MM-DD_HHMMSS>/context.txt` | `ErrorService.writeErrorReport()` | active document, input file, output file, operation, effective CONFIG |

The folder is ignored by git (the `.gitkeep` file keeps it in the repository).
A future Python helper can add `screenshot.png` into the same
`logs/errors/<timestamp>/` folder, see `docs/ARCHITECTURE.md`.
