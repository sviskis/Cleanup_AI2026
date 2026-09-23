"""Create a demo JOB folder for the first end to end test.

    .venv\\Scripts\\python.exe tools\\make_demo_job.py --root temp\\DEMO_JOB --pages 14

It produces

    temp/DEMO_JOB/
        PDF/calendar.pdf               (a real N page PDF, generated with PyMuPDF)
        TEMPLATE/MASTER_AI_TEMPLATE.ai (placeholder: replace it with your real template)
        TEMPLATE/001_cover.ai          (placeholder page template)
        TEMPLATE/002_intro.ai          (placeholder page template)
        (AI_OUT, LOG, CONFIG, ERROR are created by the orchestrator)

The two "template" files are NOT Illustrator files; they only exist so that the
planner, the naming and the preflight can be exercised. Replace them with real
.ai / .ait files (the MASTER must contain a layer named ARTWORK) before running
the Illustrator worker.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pdf_ai_batch.core import pdf_info  # noqa: E402
from pdf_ai_batch.core.project import JobProject  # noqa: E402


PLACEHOLDER_NOTE = (
    "PLACEHOLDER - replace with a real Illustrator template.\n"
    "The MASTER template must contain a layer named ARTWORK.\n"
)


def build_pdf(path: Path, pages: int) -> None:
    mupdf = pdf_info.load_pymupdf()

    document = mupdf.open()
    for index in range(pages):
        page = document.new_page(width=595, height=842)
        page.insert_text((60, 80), f"Demo PDF - page {index + 1} / {pages}", fontsize=16)
        page.draw_rect(mupdf.Rect(60, 120, 535, 782), color=(0.8, 0.8, 0.8), width=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(path))
    document.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a demo JOB folder for the first end to end test.")
    parser.add_argument("--root", default="temp/DEMO_JOB", help="where the JOB folder is created")
    parser.add_argument("--pages", type=int, default=14, help="pages in the generated PDF (default 14)")
    parser.add_argument("--pdf-name", default="calendar.pdf", help="PDF file name (default calendar.pdf)")
    parser.add_argument(
        "--no-page-templates",
        action="store_true",
        help="create only the MASTER template (test the default-template fallback)",
    )
    args = parser.parse_args(argv)

    project = JobProject.open(Path(args.root), create=True)
    pdf_path = project.pdf_dir / args.pdf_name
    build_pdf(pdf_path, max(1, args.pages))

    (project.template_dir / "MASTER_AI_TEMPLATE.ai").write_text(PLACEHOLDER_NOTE, encoding="utf-8")
    if not args.no_page_templates:
        for name in ("001_cover.ai", "002_intro.ai"):
            (project.template_dir / name).write_text(PLACEHOLDER_NOTE, encoding="utf-8")

    info = project.info()
    print(f"JOB        : {project.root}")
    print(f"PDF        : {pdf_path.name} ({args.pages} pages, generated)")
    print(f"Templates  : {', '.join(info['templates'])}")
    print(f"Default    : {info['default_template']}")
    print("")
    print("Next steps:")
    print(f"  .venv\\Scripts\\python.exe app.py --diagnose")
    print(
        "  .venv\\Scripts\\python.exe -m pdf_ai_batch.run_one "
        f'--job "{project.root}" --pdf {pdf_path.name} --page 3 --preflight-only --skip-illustrator-check'
    )
    print("  (then replace the placeholder templates with real .ai files and run without --preflight-only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
