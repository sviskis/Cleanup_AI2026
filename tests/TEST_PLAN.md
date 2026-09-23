# Test plan

Companion documents: `docs/TESTING.md` (how to execute every case),
`tools/README.md` (what the automation does), `docs/CODE_ANALYSIS.md` (why the
project is shaped this way).

## 1. Goal

Keep the proven behaviour of the reference script
(`archive/original/PDF_Deep_Cleanup_AI_Template_BATCH.jsx`) while making the code
maintainable. A change is acceptable only if:

* the automated gate is green (`check_jsx.ps1`, `run_tests.ps1`), **and**
* the manual cases below that touch the changed area pass on a test JOB.

## 2. Scope

| In scope | Out of scope |
| --- | --- |
| naming, folder detection, page counting, cleanup switches, template handling, batch loop, logging, error reports, GUI behaviour | redesigning the cleanup heuristics, new cleanup features, the 12 month pipeline (see `TODO.md` P2) |

## 3. Levels and environments

| Level | Environment | Documented in |
| --- | --- | --- |
| L1 static | PowerShell 5.1, WSH JScript 5.8 | `docs/TESTING.md` §1 |
| L2 unit | same, with `tests/jscript/stubs.js` | `docs/TESTING.md` §1 |
| L3 manual smoke / functional | Illustrator on Windows, test JOB folder | `docs/TESTING.md` §2 (S1-S5, F1-F10) |
| L4 manual error handling | Illustrator on Windows, deliberately broken inputs | `docs/TESTING.md` §2 (E1-E8) |
| L5 regression vs reference | Illustrator + reference script | `docs/TESTING.md` §2 (R1-R5) |

## 4. Case index

| Group | Cases | Must pass |
| --- | --- | --- |
| Static + unit | `tools/check_jsx.ps1`, `tools/run_tests.ps1` (79 assertions) | before **every** commit |
| Smoke | S1-S5 | before every release |
| Functional | F1-F10 | after any change in `core/` or `ui/` |
| Error handling | E1-E8 | after any change in `services/` or the batch loop |
| Regression | R1-R5 | after any change that can alter document handling |

## 5. Entry / exit criteria

**Entry:** a test JOB exists (3 page PDF, 12 page PDF, Latvian-named PDF, MASTER
template with an `ARTWORK` layer), Illustrator is on the machine, the repository
is at the revision under test.

**Exit (release):**

* L1 + L2 green, no warnings that were not there before;
* all smoke cases pass;
* functional cases pass for any changed area;
* error cases produce a `logs/errors/<timestamp>/` report and the batch keeps
  running;
* R1-R5 compared against the reference on the same JOB, differences explained in
  `CHANGELOG.md`.

## 6. Reference comparison protocol

1. Check out `archive/original/PDF_Deep_Cleanup_AI_Template_BATCH.jsx` (or use it
   directly, it is a complete script).
2. Copy the test JOB to two names: `JOB_REF` and `JOB_NEW`, identical PDFs and
   template.
3. Run the reference script on `JOB_REF`, tick every page, note the log lines.
4. Run `src/Main.jsx` on `JOB_NEW`, tick the same pages.
5. Compare R1-R5 (`docs/TESTING.md` §2).
6. Keep both log files next to the test JOB as evidence.

## 7. Risk based priorities

| Risk | Test focus |
| --- | --- |
| The cleanup engine could destroy real artwork | F3, F4, R2, R3 - always visual |
| The MASTER template could be modified | check the template timestamp/hash after every run |
| Outputs could be overwritten silently | F5, F6, E7 |
| A batch could stop halfway on one bad PDF | E3, E4, E5, E8 |
| The log/report could disappear on a hard failure | E3-E5 plus the session log check in S2 |
| Encoding problems with Latvian names | F9 |

## 8. What this plan deliberately does not do

No pixel comparison of AI output (Illustrator rendering is not deterministic
enough for a naive diff), no performance benchmarks (batch speed depends on the
documents), no automated Illustrator DOM tests until a COM harness exists
(`docs/TESTING.md` §4).
