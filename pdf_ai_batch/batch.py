"""Batch queue CLI - the operator interface (no GUI needed).

    python -m pdf_ai_batch.batch --job <JOB> --build --pages 1-4
    python -m pdf_ai_batch.batch --job <JOB> --run-all
    python -m pdf_ai_batch.batch --job <JOB> --pdf appendix.pdf --run-all
    python -m pdf_ai_batch.batch --job <JOB> --continue
    python -m pdf_ai_batch.batch --job <JOB> --retry-errors
    python -m pdf_ai_batch.batch --job <JOB> --retry-interrupted
    python -m pdf_ai_batch.batch --job <JOB> --run-next
    python -m pdf_ai_batch.batch --job <JOB> --status
    python -m pdf_ai_batch.batch --job <JOB> --pdf appendix.pdf --reconcile
    python -m pdf_ai_batch.batch --job <JOB> --reset appendix_p003
    python -m pdf_ai_batch.batch --job <JOB> --skip manualis_p002

Action semantics (see pdf_ai_batch/core/queue.py for the full rules):

    --build              plan the pages and merge them into state.json; without
                         --pdf every configured PDF of the JOB is planned
    --run-all            rebuild the plan, then run all enabled WAITING/INTERRUPTED
                         (with --pdf: only the pages of that PDF)
    --continue           resume after a restart (WAITING + INTERRUPTED, recovered
                         RUNNING items included); DONE/SKIPPED/ERROR stay as they are
    --retry-errors       ERROR -> WAITING and run them (every PDF of the JOB)
    --retry-interrupted  INTERRUPTED -> WAITING and run them
    --run-next           run exactly one runnable item
    --reconcile          reconcile ONE PDF after its page count changed (--pdf required)
    --status             print the PDF / PAGE / STATE / OUTPUT table, touch nothing
    --skip ID            mark one item SKIPPED
    --reset ID           put one item back to WAITING (works on DONE too)

Documents are planned and run in the order of `documents[]` in config.json, then by
page number; `--pdf NAME` narrows a build, a run or an ID lookup to one document.

Exit codes: 0 = no ERROR/INTERRUPTED left in the queue, 1 = at least one is left
(also for `--status`), 2 = usage or setup problem.
"""

from __future__ import annotations

import argparse
import sys
from itertools import count
from pathlib import Path

from . import __version__, paths
from .adapters.illustrator import IllustratorAdapter
from .core import jsonio
from .core import queue as queue_mod
from .core.naming import pdf_id_for
from .core.pagejob import PagePlanError
from .core.pdf_info import PdfPageCountError
from .core.project import JobProject, ProjectError
from .logging_setup import configure_console, setup_logging

EXIT_OK = 0
EXIT_QUEUE_FAILED = 1
EXIT_USAGE = 2

ACTION_FLAGS = (
    "build",
    "reconcile",
    "status",
    "run_next",
    "run_all",
    "continue_queue",
    "retry_errors",
    "retry_interrupted",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pdf_ai_batch.batch",
        description="Persistent batch queue: state.json in JOB/CONFIG, one Illustrator worker call per page.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "IDs for --skip/--reset: job_id (manualis_p003, works across every PDF),\n"
            "page number scoped with --pdf (--pdf manualis.pdf 3) or the output file\n"
            "name (manualis__003.ai). Without --pdf a bare page number in a multi PDF\n"
            "JOB is ambiguous and is reported as an error.\n"
        ),
    )
    parser.add_argument("--job", required=True, help="JOB folder (created when missing)")

    parser.add_argument("--build", action="store_true", help="plan the pages and write state.json")
    parser.add_argument("--reconcile", action="store_true", help="reconcile ONE PDF after a page count change (needs --pdf)")
    parser.add_argument("--status", action="store_true", help="print the PDF/PAGE/STATE/OUTPUT table")
    parser.add_argument("--run-next", action="store_true", help="run one runnable item")
    parser.add_argument("--run-all", action="store_true", help="rebuild the plan and run the backlog")
    parser.add_argument("--continue", dest="continue_queue", action="store_true", help="resume: WAITING + INTERRUPTED")
    parser.add_argument("--retry-errors", action="store_true", help="ERROR -> WAITING, then run")
    parser.add_argument("--retry-interrupted", action="store_true", help="INTERRUPTED -> WAITING, then run")
    parser.add_argument("--skip", action="append", default=[], metavar="ID", help="mark one item SKIPPED (repeatable)")
    parser.add_argument("--reset", action="append", default=[], metavar="ID", help="put one item back to WAITING (repeatable)")

    parser.add_argument(
        "--pdf",
        help="one document inside JOB/PDF (default: every configured document)",
    )
    parser.add_argument("--pages", help='pages to plan, e.g. "1-3,5" (default: all)')
    parser.add_argument("--template", help="template file name in JOB/TEMPLATE (overrides the mapping)")
    parser.add_argument("--layer", help="target layer in the AI (default ARTWORK)")
    parser.add_argument("--overwrite", action="store_true", help="allow replacing existing output AIs")
    parser.add_argument(
        "--template-mode",
        choices=("auto", "copy", "saveas"),
        default="auto",
        help="copy = Python copies the template; saveas = Illustrator converts .ait",
    )
    parser.add_argument("--reset-queue", action="store_true", help="with --build: make every planned page WAITING again")
    parser.add_argument("--no-build", action="store_true", help="with --run-all: do not refresh the plan first")

    parser.add_argument("--timeout", type=float, default=900.0, help="seconds to wait for one worker result")
    parser.add_argument("--poll", type=float, default=0.5, help="result poll interval in seconds")
    parser.add_argument("--max-items", type=int, help="stop the pass after N items")
    parser.add_argument("--skip-illustrator-check", action="store_true", help="do not attach to Illustrator (dry runs)")
    parser.add_argument("--dry-run", action="store_true", help="print what would run, call no Illustrator")
    parser.add_argument("--quiet", action="store_true", help="no console logging (log files only)")
    parser.add_argument("--json", dest="json_report", help="write the batch summary to this JSON file")
    return parser


def _actions(args: argparse.Namespace) -> list[str]:
    actions = [name for name in ACTION_FLAGS if getattr(args, name)]
    if args.skip:
        actions.append("skip")
    if args.reset:
        actions.append("reset")
    return actions


def _make_adapter(args: argparse.Namespace, logger) -> IllustratorAdapter:
    return IllustratorAdapter(
        worker_jsx=paths.worker_jsx(),
        runtime_dir=paths.runtime_dir(),
        timeout=args.timeout,
        poll_interval=args.poll,
        logger=logger,
    )


def _progress_printer():
    counter = count(1)

    def progress(outcome: queue_mod.RunOutcome) -> None:
        print(f"[{next(counter)}] {outcome.line()}", flush=True)

    return progress


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_console()

    actions = _actions(args)
    if not actions:
        parser.print_help()
        print("")
        print(
            "Nepieciešama darbība: --build | --status | --run-next | --run-all | --continue "
            "| --retry-errors | --retry-interrupted | --skip ID | --reset ID"
        )
        return EXIT_USAGE

    try:
        project = JobProject.open(args.job, create=True)
    except (ProjectError, OSError) as exc:
        print(f"Kļūda: nevar atvērt JOB mapi: {exc}")
        return EXIT_USAGE

    logger = setup_logging(project.log_dir, console=not args.quiet, batch_log=True)
    logger.info("batch %s | job=%s | darbības=%s", __version__, project.root, ",".join(actions))
    print(f"JOB        : {project.root}")
    print(f"state.json : {project.state_path}")
    print("")

    # opening the queue recovers a stale RUNNING item and quarantines a broken file
    batch = queue_mod.BatchQueue.open(project, logger=logger)
    for problem in batch.problems():
        print(f"Brīdinājums: {problem}")
    if batch.problems():
        print("")

    build_kwargs = {
        "pdf": args.pdf,
        "pages": args.pages,
        "template": args.template,
        "layer": args.layer,
        "overwrite": bool(args.overwrite),
        "template_mode": args.template_mode,
    }

    exit_code = EXIT_OK
    summary: queue_mod.BatchSummary | None = None

    # ---------------------------------------------------------------- state only
    for item_id in args.reset:
        try:
            item = batch.reset_item(item_id, pdf=args.pdf)
        except queue_mod.QueueError as exc:
            print(f"Kļūda: {exc}")
            exit_code = EXIT_USAGE
            continue
        print(f"RESET {item.job_id} -> WAITING")
    for item_id in args.skip:
        try:
            item = batch.skip_item(item_id, pdf=args.pdf)
        except queue_mod.QueueError as exc:
            print(f"Kļūda: {exc}")
            exit_code = EXIT_USAGE
            continue
        print(f"SKIP  {item.job_id}")

    if args.reconcile:
        if not args.pdf:
            print("Kļūda: --reconcile prasa --pdf (vienam dokumentam)")
            return EXIT_USAGE
        try:
            report = batch.reconcile_document(args.pdf)
        except (PagePlanError, ProjectError, PdfPageCountError, OSError) as exc:
            print(f"Kļūda: {exc}")
            logger.error("reconcile neizdevās: %s", exc)
            return EXIT_USAGE
        print(
            f"RECONCILE {report.get('pdf')}: stored {report.get('stored')} -> "
            f"current {report.get('current')} | saglabātas {report.get('kept')} | "
            f"pievienotas {report.get('added')} | noņemtas {report.get('removed')} | "
            f"atjaunotas {report.get('restored')}"
        )
        print("")

    if args.build:
        try:
            items = batch.build_queue(reset=bool(args.reset_queue), **build_kwargs)
        except (PagePlanError, ProjectError, PdfPageCountError, OSError) as exc:
            print(f"Kļūda: {exc}")
            logger.error("build_queue neizdevās: %s", exc)
            return EXIT_USAGE
        print(f"Queue izveidota: {len(items)} elementi ({batch.counts()['runnable']} rindā)")
        print("")

    if args.status:
        print(batch.status_table())
        print("")

    # ------------------------------------------------------------- run actions
    run_actions = [
        name
        for name in ("run_next", "run_all", "continue_queue", "retry_errors", "retry_interrupted")
        if getattr(args, name)
    ]
    if run_actions:
        if args.dry_run:
            runnable = batch.document.runnable()
            if args.pdf:
                wanted = pdf_id_for(args.pdf)
                runnable = [item for item in runnable if item.document == wanted]
            print("--- dry-run: elementi, kas tiktu izpildīti ---")
            for item in runnable:
                print(f"{item.document:<16} {item.page:03d} {item.state:<11} {item.output}")
            print(f"Kopā: {len(runnable)}")
            return EXIT_OK

        adapter = _make_adapter(args, logger)
        if not args.skip_illustrator_check and not adapter.ensure_app():
            print("Kļūda: Illustrator nav sasniedzams (COM). Skatīt app.py --health.")
            logger.error("Illustrator nav sasniedzams, nekas netiek palaists")
            return EXIT_QUEUE_FAILED
        batch.adapter = adapter

        progress = None if args.quiet else _progress_printer()
        for name in run_actions:
            if name == "run_next":
                outcome = batch.run_next(progress=progress)
                if outcome is None:
                    print("Nav izpildāmu elementu")
                summary = batch.summary(outcomes=[outcome] if outcome else [])
            elif name == "run_all":
                if args.pdf:
                    # --pdf narrows the pass to one document (RUN CURRENT PDF)
                    summary = batch.run_documents(
                        [args.pdf],
                        progress=progress,
                        rebuild=not args.no_build,
                        build_kwargs=build_kwargs,
                    )
                else:
                    summary = batch.run_all_enabled(
                        progress=progress,
                        rebuild=not args.no_build,
                        build_kwargs=build_kwargs,
                    )
            elif name == "continue_queue":
                summary = batch.continue_queue(
                    progress=progress, limit=args.max_items, build_kwargs=build_kwargs
                )
            elif name == "retry_errors":
                result = batch.retry_errors(run=True, progress=progress)
                print(result.format())
                summary = result.summary or batch.summary()
            else:
                result = batch.retry_interrupted(run=True, progress=progress)
                print(result.format())
                summary = result.summary or batch.summary()
        print("")
        logger.info("batch END | %s", (summary.counts if summary else batch.counts()))

    # ------------------------------------------------------------------- report
    if summary is not None:
        print("--- kopsavilkums ---")
        print(summary.format())
        print("")
        print(batch.status_table())
        print("")
        if args.json_report:
            jsonio.write_json_atomic(Path(args.json_report), summary.as_dict())
            print(f"JSON atskaite: {args.json_report}")

    counts = batch.counts()
    if counts.get("ERROR", 0) or counts.get("INTERRUPTED", 0):
        return EXIT_QUEUE_FAILED
    return exit_code


def cli(argv: list[str] | None = None) -> int:
    """Entry point used by app.py."""
    try:
        return main(argv)
    except KeyboardInterrupt:
        print("")
        print("Pārtraukts ar Ctrl+C. Kas palika RUNNING, nākamajā palaišanā kļūs INTERRUPTED;")
        print("turpini ar --continue vai --retry-interrupted.")
        return EXIT_QUEUE_FAILED


if __name__ == "__main__":
    sys.exit(cli())

