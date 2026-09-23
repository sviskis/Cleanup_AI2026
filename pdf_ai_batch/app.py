"""Application entry point.

Current stage (first milestone): the CLI proves one page end to end.
The Tkinter GUI (PROJECT / PDF / MAPPING / RUN tabs) is the next milestone and
will be launched from here as the default action.

    python app.py --diagnose
    python app.py --run-one --job "C:/JOB" --pdf manual.pdf --page 17
    python -m pdf_ai_batch.app --diagnose

    python app.py            -> GUI when it exists, otherwise prints this help
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, paths
from .adapters.illustrator import IllustratorAdapter, illustrator_process_running
from .logging_setup import configure_console, setup_logging
from .run_one import main as run_one_main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="app.py",
        description="Cleanup AI 2026 - Python orchestrator for the Illustrator worker.",
    )
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    parser.add_argument("--diagnose", action="store_true", help="print environment and path information")
    parser.add_argument("--health", action="store_true", help="check Illustrator/COM availability")
    parser.add_argument("--run-one", action="store_true", help="run the one page milestone test")
    parser.add_argument("--gui", action="store_true", help="start the GUI (next milestone)")
    parser.add_argument("rest", nargs=argparse.REMAINDER, help="arguments forwarded to --run-one")
    return parser


def print_diagnostics() -> int:
    print(f"pdf_ai_batch version : {__version__}")
    print(f"python               : {sys.version.split()[0]} ({sys.executable})")
    for key, value in paths.describe().items():
        exists = Path(value).exists()
        print(f"{key:<20} : {value}   {'[ok]' if exists else '[missing]'}")
    print(f"illustrator process  : {'running' if illustrator_process_running() else 'not detected'}")
    return 0


def print_health() -> int:
    """Check whether a job can run right now: files, runtime folder and COM.

    Uses the same connection strategy as a real run (attach to a running
    Illustrator, otherwise launch it through Dispatch), because GetActiveObject
    can fail even while Illustrator is running: the Running Object Table entry is
    not always visible (for example when the instance was started elevated),
    while Dispatch still connects.
    """
    setup_logging(None)
    adapter = IllustratorAdapter(paths.worker_jsx(), paths.runtime_dir(), timeout=5.0)

    connected_via = "none"
    if adapter.attach():
        connected_via = "attach (GetActiveObject)"
    elif adapter.launch():
        connected_via = "launch (Dispatch)"

    report = adapter.health_check()
    for key, value in report.items():
        print(f"{key:<20} : {value}")
    print(f"{'connected_via':<20} : {connected_via}")

    if not report["ok"]:
        print("")
        print("Illustrator nav sasniedzams (COM).")
        print("Pārbaudi, vai Illustrator ir palaists un nav atvērts modāls dialogs,")
        print("vai izmanto --run-one (tas izmanto to pašu attach -> launch ceļu).")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_console()

    if args.version:
        print(__version__)
        return 0

    if args.diagnose:
        return print_diagnostics()

    if args.health:
        return print_health()

    if args.run_one:
        forwarded = [arg for arg in args.rest if arg != "--"]
        return run_one_main(forwarded)

    if args.gui:
        print("GUI vēl nav ieviests (nākamais solis). Šobrīd izmanto --run-one vai --diagnose.")
        return 1

    build_parser().print_help()
    print("")
    print(f"pdf_ai_batch {__version__} - pirmais solis: --run-one (vienas lapas tests), --diagnose, --health")
    return 0


if __name__ == "__main__":
    sys.exit(main())
