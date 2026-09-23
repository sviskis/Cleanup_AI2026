"""Application entry point.

    python app.py                 -> the Tkinter GUI (Tabs: PROJECT / PDF / MAPPING / RUN)
    python app.py --gui           -> same, explicit
    python app.py --run-one --job "C:/JOB" --pdf manual.pdf --page 17
    python app.py --batch --job "C:/JOB" --run-all
    python app.py --diagnose | --health | --version

Opening the GUI never launches Illustrator: it is only contacted for an explicit
health check or a run (see docs/GUI.md).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, paths
from .adapters.illustrator import IllustratorAdapter, illustrator_process_running
from .batch import cli as batch_cli
from .logging_setup import configure_console, setup_logging
from .run_one import main as run_one_main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="app.py",
        description="Cleanup AI 2026 - Python orchestrator + Tkinter GUI for the Illustrator worker.",
    )
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    parser.add_argument("--diagnose", action="store_true", help="print environment and path information")
    parser.add_argument("--health", action="store_true", help="check that a job can run now (files, runtime, Illustrator via attach -> launch)")
    parser.add_argument("--gui", action="store_true", help="start the GUI (default when no action is given)")
    parser.add_argument("--run-one", action="store_true", help="run the one page milestone test")
    parser.add_argument("--batch", action="store_true", help="run the persistent batch queue (pdf_ai_batch/batch.py)")
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
    parser = build_parser()
    # parse_known_args: everything app.py does not define itself is forwarded to the
    # sub-command. argparse.REMAINDER cannot do this, because an option looking
    # argument like "--job" is reported as unrecognized before it is captured.
    args, forwarded = parser.parse_known_args(argv)
    forwarded = [arg for arg in forwarded if arg != "--"]
    configure_console()

    if args.version:
        print(__version__)
        return 0

    if args.diagnose:
        return print_diagnostics()

    if args.health:
        return print_health()

    if args.run_one:
        return run_one_main(forwarded)

    if args.batch:
        return batch_cli(forwarded)

    # default action (and --gui): the Tkinter GUI
    if args.gui or not forwarded:
        try:
            from .gui import run_gui
        except ImportError as exc:  # pragma: no cover - no Tk in this interpreter
            print(f"GUI nav pieejams: {exc}")
            print("Izmanto --batch (rinda) vai --run-one (viena lapa).")
            return 1
        return run_gui(forwarded)

    build_parser().print_help()
    print("")
    print(f"pdf_ai_batch {__version__} - nezināma darbība: {' '.join(forwarded)}")
    return 3


if __name__ == "__main__":
    sys.exit(main())
