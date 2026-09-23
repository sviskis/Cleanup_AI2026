"""The JOB project: folder structure and the paths Python owns.

    JOB/
      PDF/       input PDFs
      TEMPLATE/  MASTER + page templates
      CONFIG/    config.json, state.json (later), handoff files
      AI_OUT/    results
      LOG/       app.log, batch_<timestamp>.log
      ERROR/     reserved (kept for layout compatibility)

Python creates every missing folder. The worker never creates project folders -
it only touches the files it is told to.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .pdf_info import discover_pdfs, pdf_info, PdfInfo
from .template_mapper import default_template, list_templates, page_template_pool


class ProjectError(RuntimeError):
    """Raised when a JOB folder cannot be opened or prepared."""


FOLDER_NAMES = ("PDF", "TEMPLATE", "CONFIG", "AI_OUT", "LOG", "ERROR")
CONFIG_FILE_NAME = "config.json"
STATE_FILE_NAME = "state.json"


@dataclass
class JobProject:
    """A JOB folder with all derived paths."""

    root: Path

    # ---------------------------------------------------------------- opening

    @classmethod
    def open(cls, root: str | Path, create: bool = True) -> "JobProject":
        """Open (and optionally create) a JOB folder.

        The root is resolved to an absolute path, so everything derived from it
        (PDF/, TEMPLATE/, AI_OUT/, ...) is absolute as well. The request JSON must
        never depend on the current working directory: the worker runs inside
        Illustrator, which has its own cwd.
        """
        project = cls(Path(root).expanduser().resolve())
        if create:
            project.ensure_structure()
        elif not project.root.is_dir():
            raise ProjectError(f"JOB mape nav atrasta: {project.root}")
        return project

    def ensure_structure(self) -> list[Path]:
        """Create every missing JOB sub folder and return what was created."""
        created: list[Path] = []
        for path in [self.root, *[self.root / name for name in FOLDER_NAMES]]:
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
                created.append(path)
        return created

    # ---------------------------------------------------------------- paths

    @property
    def pdf_dir(self) -> Path:
        return self.root / "PDF"

    @property
    def template_dir(self) -> Path:
        return self.root / "TEMPLATE"

    @property
    def config_dir(self) -> Path:
        return self.root / "CONFIG"

    @property
    def output_dir(self) -> Path:
        return self.root / "AI_OUT"

    @property
    def log_dir(self) -> Path:
        return self.root / "LOG"

    @property
    def error_dir(self) -> Path:
        return self.root / "ERROR"

    @property
    def config_path(self) -> Path:
        return self.config_dir / CONFIG_FILE_NAME

    @property
    def state_path(self) -> Path:
        return self.config_dir / STATE_FILE_NAME

    def as_dict(self) -> dict[str, str]:
        return {
            "root": str(self.root),
            "pdf": str(self.pdf_dir),
            "template": str(self.template_dir),
            "config": str(self.config_dir),
            "output": str(self.output_dir),
            "log": str(self.log_dir),
            "error": str(self.error_dir),
        }

    # ---------------------------------------------------------------- content

    def find_pdfs(self, recursive: bool = True) -> list[Path]:
        """PDFs inside JOB/PDF (recursive, bookkeeping folders skipped)."""
        return discover_pdfs(self.pdf_dir, recursive=recursive)

    def resolve_pdf(self, pdf: str | Path) -> Path:
        """Accept a file name (resolved against JOB/PDF) or an absolute path."""
        candidate = Path(str(pdf))
        if candidate.is_absolute() and candidate.is_file():
            return candidate
        in_pdf_dir = self.pdf_dir / candidate.name
        if in_pdf_dir.is_file():
            return in_pdf_dir
        raise ProjectError(f"PDF nav atrasts: {pdf} (meklēts {in_pdf_dir})")

    def pdf_info(self, pdf: str | Path) -> PdfInfo:
        return pdf_info(self.resolve_pdf(pdf))

    def list_templates(self) -> list[Path]:
        return list_templates(self.template_dir)

    def page_template_pool(self) -> list[Path]:
        return page_template_pool(self.template_dir)

    def default_template(self, configured: str | None = None) -> Path | None:
        return default_template(self.template_dir, configured)

    def resolve_output(self, output: str | Path) -> Path:
        """Output paths always live in AI_OUT; only file names are accepted."""
        candidate = Path(str(output))
        if candidate.is_absolute():
            return candidate
        return self.output_dir / candidate.name

    def info(self) -> dict:
        """Summary used by the GUI and by the CLI status output."""
        pdfs = self.find_pdfs()
        templates = self.list_templates()
        return {
            "root": str(self.root),
            "pdf_count": len(pdfs),
            "pdfs": [p.name for p in pdfs],
            "template_count": len(templates),
            "templates": [p.name for p in templates],
            "default_template": (self.default_template().name if self.default_template() else None),
        }
