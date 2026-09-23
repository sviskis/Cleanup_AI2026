"""One page end to end - the first milestone of the migration.

    python -m pdf_ai_batch.run_one --job "C:/JOB" --pdf manual.pdf --page 17

What it proves (python -> request JSON -> Illustrator worker -> cleanup engine ->
template -> output AI -> matching result JSON -> python receives OK):

  1. JobProject creates/opens the JOB folders
  2. PyMuPDF counts the pages of the PDF (Python is authoritative)
  3. the template for that page is resolved (positional mapping + default)
  4. the output name is generated and the AI copy is prepared by Python
  5. a single request is written atomically to runtime/current_job.json
  6. jsx/worker.jsx runs inside Illustrator and writes the result
  7. the result is accepted only when job_id AND run_id match
  8. the output file is verified and the statistics are reported

Useful flags:
    --preflight-only     validate everything, touch nothing, do not start Illustrator
    --dry-run            write the request JSON and print it, do not run Illustrator
    --overwrite          allow replacing an existing output AI
    --template-mode      auto (default) | copy | saveas
    --timeout            seconds to wait for the worker result (default 900)
"""

from __future__ import annotations

import argparse
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path

from . import paths
from .adapters.illustrator import IllustratorAdapter, IllustratorError, illustrator_process_running
from .core import jsonio
from .core.config import template_mode_for
from .core.contract import (
    STATUS_OK,
    STATUS_SKIP,
    TEMPLATE_MODE_COPY,
    TEMPLATE_MODE_SAVEAS,
    build_request,
    validate_request,
)
from .core.naming import job_id_for, output_name_for
from .core.pdf_info import PdfPageCountError, count_pages
from .core.project import JobProject, ProjectError
from .core.template_mapper import default_template, page_template_pool, resolve_template
from .core.validation import format_report, has_failures, preflight
from .logging_setup import configure_console, setup_logging

EXIT_OK = 0
EXIT_JOB_FAILED = 1
EXIT_PREFLIGHT_FAILED = 2
EXIT_USAGE = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pdf_ai_batch.run_one",
        description="Process exactly one PDF page through Illustrator (first milestone test).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--job", required=True, help="JOB folder (created when missing)")
    parser.add_argument("--pdf", required=True, help="PDF file name inside JOB/PDF (or an absolute path)")
    parser.add_argument("--page", required=True, type=int, help="1 based page number")
    parser.add_argument("--template", help="template file name in JOB/TEMPLATE (default: auto mapping)")
    parser.add_argument("--layer", default="ARTWORK", help="target layer in the AI (default ARTWORK)")
    parser.add_argument("--no-clear", action="store_true", help="do not clear the target layer first")
    parser.add_argument("--overwrite", action="store_true", help="allow replacing an existing output AI")
    parser.add_argument(
        "--template-mode",
        choices=("auto", TEMPLATE_MODE_COPY, TEMPLATE_MODE_SAVEAS),
        default="auto",
        help="copy = Python copies the template; saveas = Illustrator converts .ait",
    )
    parser.add_argument("--preflight-only", action="store_true", help="validate and stop")
    parser.add_argument("--dry-run", action="store_true", help="write the request JSON, do not run Illustrator")
    parser.add_argument("--timeout", type=float, default=900.0, help="seconds to wait for the worker (default 900)")
    parser.add_argument("--poll", type=float, default=0.5, help="result poll interval in seconds")
    parser.add_argument("--skip-illustrator-check", action="store_true", help="do not attach to Illustrator")
    parser.add_argument("--quiet", action="store_true", help="no console logging (log files only)")
    return parser


def new_run_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


def print_line(text: str = "") -> None:
    print(text, flush=True)


def prepare_output_copy(template: Path, output: Path, overwrite: bool, logger) -> tuple[bool, str]:
    """Copy the template to the output (Python owns this for .ai templates)."""
    if output.exists():
        if not overwrite:
            return False, "output jau eksistē un overwrite nav atļauts"
        try:
            output.unlink()
        except OSError as exc:
            return False, f"nevar izdzēst esošo output: {exc}"
    try:
        shutil.copy2(template, output)
    except OSError as exc:
        return False, f"nevar nokopēt template uz output: {exc}"
    logger.info("Nokopēju template %s -> %s", template.name, output.name)
    return True, ""


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    configure_console()

    if args.page < 1:
        print_line("Kļūda: --page jābūt >= 1")
        return EXIT_USAGE

    # ---------------------------------------------------------------- project
    try:
        project = JobProject.open(args.job, create=True)
    except (ProjectError, OSError) as exc:
        print_line(f"Kļūda: nevar atvērt JOB mapi: {exc}")
        return EXIT_USAGE

    logger = setup_logging(project.log_dir, console=not args.quiet, batch_log=True)
    logger.info("run_one START | job=%s pdf=%s page=%s", project.root, args.pdf, args.page)
    print_line(f"JOB        : {project.root}")
    print_line(f"PDF mape   : {project.pdf_dir}")
    print_line(f"TEMPLATE   : {project.template_dir}")
    print_line(f"AI_OUT     : {project.output_dir}")
    print_line(f"LOG        : {project.log_dir}")
    print_line("")

    # ---------------------------------------------------------------- pdf
    try:
        pdf_path = project.resolve_pdf(args.pdf)
    except ProjectError as exc:
        print_line(f"Kļūda: {exc}")
        return EXIT_USAGE

    try:
        page_count, count_method = count_pages(pdf_path)
    except PdfPageCountError as exc:
        print_line(f"Kļūda: {exc}")
        logger.error("Nevar noteikt lappušu skaitu: %s", exc)
        return EXIT_USAGE

    if args.page > page_count:
        print_line(f"Kļūda: lapa {args.page} pārsniedz PDF lappušu skaitu {page_count}")
        return EXIT_USAGE

    print_line(f"PDF        : {pdf_path.name}")
    print_line(f"Lapas      : {page_count} ({count_method})")
    print_line(f"Apstrādā   : lapa {args.page}")
    print_line("")

    # ---------------------------------------------------------------- template
    pool = project.page_template_pool()
    fallback = default_template(project.template_dir)

    if args.template:
        template = resolve_template(args.template, project.template_dir, fallback)
        if template is None:
            print_line(f"Kļūda: template nav atrasts: {args.template}")
            return EXIT_USAGE
    elif args.page - 1 < len(pool):
        template = pool[args.page - 1]
    else:
        template = fallback

    if template is None:
        print_line("Kļūda: nav neviena template un nav noklusētā (MASTER_*) template")
        return EXIT_USAGE

    print_line("Templates  : " + (", ".join(t.name for t in pool) if pool else "(nav lapu template)"))
    print_line(f"Default    : {fallback.name if fallback else '(nav)'}")
    print_line(f"Šai lapai  : {template.name}")

    # ---------------------------------------------------------------- output
    output_name = output_name_for(pdf_path, args.page, page_count)
    output_path = project.output_dir / output_name
    job_id = job_id_for(pdf_path, args.page)
    run_id = new_run_id()
    mode = args.template_mode if args.template_mode != "auto" else template_mode_for(template)

    print_line(f"Output     : {output_name}")
    print_line(f"Template režīms: {mode}")
    print_line(f"job_id     : {job_id}")
    print_line(f"run_id     : {run_id}")
    print_line("")

    # ---------------------------------------------------------------- handoff
    adapter = IllustratorAdapter(
        worker_jsx=paths.worker_jsx(),
        runtime_dir=paths.runtime_dir(),
        timeout=args.timeout,
        poll_interval=args.poll,
        logger=logger,
    )
    # Python owns the handoff folder: create it before the preflight so the checks
    # can also verify that it is writable.
    try:
        adapter.ensure_runtime_dir()
    except OSError as exc:
        print_line(f"Kļūda: nevar izveidot runtime mapi: {exc}")
        return EXIT_USAGE

    illustrator_ready: bool | None = None
    if not args.skip_illustrator_check and not args.preflight_only and not args.dry_run:
        illustrator_ready = adapter.ensure_app()
    elif args.skip_illustrator_check and illustrator_process_running():
        illustrator_ready = None

    checks = preflight(
        project,
        pdf=pdf_path,
        page=args.page,
        page_count=page_count,
        template=template,
        output=output_path,
        worker_jsx=paths.worker_jsx(),
        cleanup_jsx=paths.cleanup_jsx(),
        runtime_dir=paths.runtime_dir(),
        illustrator_available=illustrator_ready,
    )
    print_line("--- pirmsstarta pārbaudes ---")
    print_line(format_report(checks))
    print_line("")
    if has_failures(checks):
        logger.error("Preflight neizdevās, darbs netiek sākts")
        return EXIT_PREFLIGHT_FAILED

    # ---------------------------------------------------------------- request
    overwrite = bool(args.overwrite)

    if mode == TEMPLATE_MODE_COPY and not args.dry_run and not args.preflight_only:
        copied, reason = prepare_output_copy(template, output_path, overwrite, logger)
        if not copied:
            logger.info("SKIP: %s", reason)
            print_line(f"SKIP: {reason}")
            return EXIT_OK

    request = build_request(
        run_id=run_id,
        job_id=job_id,
        pdf=str(pdf_path),
        page=args.page,
        template=str(template),
        output=str(output_path),
        layer=args.layer,
        clear_layer=not args.no_clear,
        overwrite=overwrite,
        template_mode=mode,
    )

    problems = validate_request(request)
    if problems:
        print_line("Kļūda: nederīgs pieprasījums: " + "; ".join(problems))
        return EXIT_USAGE

    # ------------------------------------------------- report the final paths
    # The worker runs inside Illustrator with its own working directory, so it
    # only ever sees what is written here: absolute, forward slash paths. Print
    # them before Illustrator is invoked, so a run is auditable.
    print_line("--- galīgie pieprasījuma ceļi (absolūti) ---")
    for key in ("pdf", "template", "output"):
        print_line(f"{key:<9}: {request[key]}")
    logger.info(
        "Pieprasījums: pdf=%s | template=%s | output=%s",
        request["pdf"],
        request["template"],
        request["output"],
    )
    print_line("")

    if args.dry_run or args.preflight_only:
        jsonio.write_json_atomic(adapter.request_path, request)
        print_line(f"--- pieprasījums ({'dry-run' if args.dry_run else 'preflight-only'}) ---")
        print_line(jsonio.read_text(adapter.request_path).strip())
        logger.info("Sagatavots pieprasījums: %s", adapter.request_path)
        return EXIT_OK

    # ---------------------------------------------------------------- run
    print_line("Sūtu darbu uz Illustrator ...")
    try:
        result = adapter.run_job(request)
    except IllustratorError as exc:
        print_line(f"Kļūda: {exc}")
        logger.error("COM kļūda: %s", exc)
        return EXIT_JOB_FAILED

    handshake = adapter.last_handshake
    if handshake:
        print_line(
            f"Handshake  : invoked={handshake.invoked} waited={handshake.waited_seconds:.1f}s "
            f"rejected={handshake.rejected_results}"
        )

    print_line(f"Statuss    : {result.status}")
    if result.status == STATUS_OK:
        print_line(f"Objekti    : {result.objects_copied}")
        for key in sorted(result.stats or {}):
            print_line(f"   {key:<26} {result.stats[key]}")
    if result.message:
        print_line(f"Ziņa       : {result.message}")
    if result.error_type:
        print_line(f"Kļūdas tips: {result.error_type}")

    output_exists = output_path.exists()
    size = output_path.stat().st_size if output_exists else 0
    print_line(f"Output     : {'ir' if output_exists else 'NAV'} ({output_path}) {size} bytes")
    print_line("")

    if result.status == STATUS_OK and output_exists:
        logger.info("OK %s | objects=%s | %s", output_path.name, result.objects_copied, result.stats or {})
        print_line("MILESTONE OK: viena lapa apstrādāta un rezultāts saņemts.")
        return EXIT_OK

    if result.status == STATUS_SKIP:
        logger.info("SKIP %s", output_path.name)
        print_line("SKIP: lapa netika apstrādāta (output jau eksistē).")
        return EXIT_OK

    logger.error("ERROR %s | %s | %s", output_path.name, result.error_type, result.message)
    print_line("MILESTONE FAILED: skatīt LOG/app.log un runtime/worker.log")
    return EXIT_JOB_FAILED


def cli(argv: list[str] | None = None) -> int:
    """Entry point used by app.py."""
    try:
        return main(argv)
    except KeyboardInterrupt:
        print_line("Pārtraukts ar Ctrl+C")
        return EXIT_JOB_FAILED


if __name__ == "__main__":
    sys.exit(main())
