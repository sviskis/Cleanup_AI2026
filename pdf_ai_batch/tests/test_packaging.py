"""Packaging tests (milestone 9): path resolution, diagnostics and the build contract.

The packaged application must find its own files wherever it is installed, must be
able to say what is wrong in plain language, and must never require the repository or
the current working directory. These tests run without PyInstaller: they simulate a
frozen build (`sys.frozen` + `sys.executable`), check the asset search order, the user
writable fallbacks and the packaging contract of the build tooling.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from pdf_ai_batch import __version__, diagnostics, paths
from pdf_ai_batch.logging_setup import _attach_streams

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def install(tmp_path, monkeypatch) -> Path:
    """A fake installed application folder (like dist/Cleanup AI 2026)."""
    folder = tmp_path / "Cleanup AI 2026"
    (folder / "jsx").mkdir(parents=True)
    (folder / "config").mkdir(parents=True)
    for name in ("worker.jsx", "cleanup.jsx", "json2.js"):
        (folder / "jsx" / name).write_text("// stub\n", encoding="utf-8")
    (folder / "config" / "default_config.json").write_text("{}\n", encoding="utf-8")
    (folder / "program").mkdir()
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(paths.sys, "executable", str(folder / "Cleanup AI 2026.exe"))
    monkeypatch.delenv(paths.ROOT_ENV_VAR, raising=False)
    monkeypatch.delenv(paths.HOME_ENV_VAR, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    return folder


# ------------------------------------------------------------------- path resolution


def test_source_layout_uses_the_repository(monkeypatch):
    monkeypatch.delenv(paths.ROOT_ENV_VAR, raising=False)
    monkeypatch.delenv(paths.HOME_ENV_VAR, raising=False)

    assert paths.is_frozen() is False
    assert paths.app_root() == REPO_ROOT
    assert paths.jsx_dir() == REPO_ROOT / "jsx"
    assert paths.worker_jsx().name == "worker.jsx"
    assert paths.runtime_dir() == REPO_ROOT / "runtime"
    assert paths.log_dir() == REPO_ROOT / "logs"
    assert paths.describe()["layout"] == "source"


def test_root_env_var_still_overrides_for_tests(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ROOT_ENV_VAR, str(tmp_path))

    assert paths.app_root() == tmp_path.resolve()
    assert paths.jsx_dir() == tmp_path.resolve() / "jsx"


def test_frozen_layout_derives_everything_from_the_exe(install):
    assert paths.app_root() == install
    assert paths.install_jsx_dir() == install / "jsx"
    assert paths.jsx_dir() == install / "jsx"
    assert paths.worker_jsx() == install / "jsx" / "worker.jsx"
    assert paths.cleanup_jsx().is_file()
    assert paths.json_polyfill_jsx().is_file()
    assert paths.config_dir() == install / "config"
    assert paths.default_config_file().is_file()
    assert paths.runtime_dir() == install / "runtime"
    assert paths.log_dir() == install / "logs"
    assert paths.describe()["layout"] == "installed"


def test_frozen_build_never_needs_the_current_directory(install, monkeypatch, tmp_path):
    elsewhere = tmp_path / "cwd"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert paths.app_root() == install
    assert paths.jsx_dir() == install / "jsx"
    assert paths.runtime_dir().parent == install


def test_home_override_wins_over_the_repository(tmp_path, monkeypatch):
    home = tmp_path / "portable"
    (home / "jsx").mkdir(parents=True)
    (home / "jsx" / "worker.jsx").write_text("// stub\n", encoding="utf-8")
    monkeypatch.setenv(paths.HOME_ENV_VAR, str(home))

    assert paths.app_root() == home.resolve()
    assert paths.jsx_dir() == home.resolve() / "jsx"


def test_jsx_dir_survives_a_read_only_install(install, monkeypatch):
    """A missing install folder still falls back to the bundle, then the repository."""
    bundled = install / "program" / "jsx"
    bundled.mkdir(parents=True)
    for name in ("worker.jsx", "cleanup.jsx", "json2.js"):
        (bundled / name).write_text("// stub\n", encoding="utf-8")
    monkeypatch.setattr(paths, "bundle_dir", lambda: install / "program")
    (install / "jsx" / "worker.jsx").unlink()
    (install / "jsx" / "cleanup.jsx").unlink()
    (install / "jsx" / "json2.js").unlink()
    (install / "jsx").rmdir()

    assert paths.jsx_dir() == bundled


def test_read_only_install_uses_the_user_folder(install, monkeypatch, tmp_path):
    local = tmp_path / "LocalAppData" / "Cleanup AI 2026"
    real_writable = paths._writable

    def only_user_folders(folder: Path) -> bool:
        return real_writable(folder) if str(folder).startswith(str(local)) else False

    monkeypatch.setattr(paths, "_writable", only_user_folders)

    assert paths.runtime_dir() == local / "runtime"
    assert paths.log_dir() == local / "logs"
    assert paths.runtime_dir().is_dir()  # created, never a Program Files path


def test_user_data_dir_uses_local_appdata(install, monkeypatch):
    assert paths.user_data_dir() == Path(paths.os.environ["LOCALAPPDATA"]) / paths.APP_FOLDER_NAME


# ------------------------------------------------------------------------ diagnostics


class FakeAdapter:
    """Counts health checks, so 'explicit only' can be proven."""

    def __init__(self, *, ok: bool = True, version: str = "29.8.3") -> None:
        self.ok = ok
        self.version = version
        self.health_calls = 0

    def health_check(self) -> dict:
        self.health_calls += 1
        return {"ok": self.ok, "illustrator": {"version": self.version} if self.ok else {}}


def test_diagnostics_in_source_layout_are_clean(monkeypatch):
    monkeypatch.delenv(paths.HOME_ENV_VAR, raising=False)

    report = diagnostics.run_diagnostics(check_illustrator=False)

    assert report.ok is True
    assert report.facts["version"] == __version__
    assert report.facts["frozen"] is False
    assert report.facts["layout"] == "source"
    names = [item.name for item in report.items]
    assert "JSX worker.jsx" in names and "JSX cleanup.jsx" in names and "JSX json2.js" in names
    assert all(item.ok for item in report.items if item.name.startswith("JSX"))
    assert report.facts["illustrator_installed"] in (True, False)
    text = report.to_text()
    assert "rezultāts:" in text and "\r\r" not in text


def test_diagnostics_never_touch_illustrator_unless_asked(monkeypatch):
    monkeypatch.delenv(paths.HOME_ENV_VAR, raising=False)
    adapter = FakeAdapter()

    quiet = diagnostics.run_diagnostics(adapter=adapter)

    assert adapter.health_calls == 0
    assert quiet.facts.get("illustrator_reachable") is None
    assert any(item.warning and "nav pārbaudīts" in item.detail for item in quiet.items)

    loud = diagnostics.run_diagnostics(check_illustrator=True, adapter=adapter)

    assert adapter.health_calls == 1
    assert loud.facts["illustrator_reachable"] is True
    assert loud.ok is True


def test_diagnostics_report_unreachable_illustrator(monkeypatch):
    monkeypatch.delenv(paths.HOME_ENV_VAR, raising=False)

    report = diagnostics.run_diagnostics(check_illustrator=True, adapter=FakeAdapter(ok=False))

    assert report.facts["illustrator_reachable"] is False
    assert any("Illustrator" in error for error in report.errors)
    assert report.ok is False


def test_diagnostics_flag_missing_assets_in_a_broken_install(install, monkeypatch):
    (install / "jsx" / "cleanup.jsx").unlink()
    (install / "config" / "default_config.json").unlink()
    monkeypatch.setattr(paths, "bundle_dir", lambda: None)

    report = diagnostics.run_diagnostics()

    assert report.ok is False
    assert any("cleanup.jsx" in error for error in report.errors)
    assert not [item for item in report.items if item.name == "Noklusētais config" and item.ok]
    payload = report.as_dict()
    assert payload["ok"] is False
    assert payload["facts"]["layout"] == "installed"
    assert json.dumps(payload)  # JSON serialisable for the production log


def test_diagnostics_find_the_bundled_assets_when_the_install_folder_lacks_them(install, monkeypatch):
    bundled = install / "program" / "jsx"
    bundled.mkdir(parents=True)
    for name in ("worker.jsx", "cleanup.jsx", "json2.js"):
        (bundled / name).write_text("// stub\n", encoding="utf-8")
    monkeypatch.setattr(paths, "bundle_dir", lambda: install / "program")
    for name in ("worker.jsx", "cleanup.jsx", "json2.js"):
        (install / "jsx" / name).unlink()
    (install / "jsx").rmdir()

    report = diagnostics.run_diagnostics()

    assert report.ok is True
    assert all(item.ok for item in report.items if item.name.startswith("JSX"))


def test_configure_console_gives_a_stream_in_a_windowed_build(monkeypatch, tmp_path):
    from pdf_ai_batch import logging_setup, paths as package_paths

    monkeypatch.setattr(package_paths, "log_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    _attach_streams()

    assert sys.stdout is not None and sys.stderr is not None
    stream = sys.stdout
    stream.write("windowed build output\n")
    stream.flush()
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__
    stream.close()
    text = (tmp_path / "logs" / logging_setup.CONSOLE_LOG_NAME).read_text(encoding="utf-8")
    assert "windowed build output" in text


# ------------------------------------------------------------------ packaging contract


def test_version_has_a_single_source_of_truth():
    version_file = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()

    assert version_file == __version__
    parts = version_file.split(".")
    assert len(parts) == 3 and all(part.isdigit() for part in parts)


def test_pyinstaller_spec_covers_the_application_assets():
    spec = (REPO_ROOT / "tools" / "cleanup_ai.spec").read_text(encoding="utf-8")

    assert "Cleanup AI 2026" in spec
    assert "app.py" in spec  # the entry script
    for folder in ('"jsx"', '"config"', '"docs"'):
        assert folder in spec, folder
    for name in ("worker.jsx", "cleanup.jsx", "json2.js"):
        assert name in spec, name
    # COM and PDF libraries must be importable inside the build
    for module in ("win32com.client", "pythoncom", "pywintypes", "pymupdf", "pypdf", "tkinter.ttk"):
        assert f'"{module}"' in spec, module
    assert "console=CONSOLE" in spec  # windowed in Release, console in Debug
    assert "COLLECT(" in spec  # a folder distribution, not a one file build
    # Illustrator must never be bundled
    assert "Illustrator.exe" not in spec


def test_build_script_is_one_command_and_checks_its_own_result():
    script = (REPO_ROOT / "tools" / "build_release.ps1").read_text(encoding="utf-8")

    assert "cleanup_ai.spec" in script
    assert "PyInstaller" in script
    for folder in ("build", "dist"):
        assert folder in script
    # it verifies the distribution it just built and never bundles Illustrator
    assert "jsx\\worker.jsx" in script and "config\\default_config.json" in script
    assert "Illustrator nedrīkst būt iekļauts" in script
    # and it runs the packaged executable once (--diagnose) before claiming success
    assert "--diagnose" in script
    # the real gates run first unless they are skipped on purpose
    assert "check_jsx.ps1" in script and "run_tests.ps1" in script and "pytest" in script
    assert "SkipTests" in script


def test_shortcut_tool_exists_and_never_touches_a_desktop_by_itself():
    script = (REPO_ROOT / "tools" / "create_shortcut.ps1").read_text(encoding="utf-8")

    assert "Cleanup AI 2026.exe" in script
    assert "WScript.Shell" in script
    assert "Desktop" in script
    # nothing in the application or the build may create a shortcut automatically
    assert "create_shortcut" in (REPO_ROOT / "tools" / "build_release.ps1").read_text(encoding="utf-8")


def test_packaging_requirements_document_the_choice():
    text = (REPO_ROOT / "requirements-packaging.txt").read_text(encoding="utf-8")
    spec = (REPO_ROOT / "tools" / "cleanup_ai.spec").read_text(encoding="utf-8")

    assert "PyInstaller" in text
    assert "cx_Freeze" in text and "Nuitka" in text  # alternatives, and why not
    assert "PyInstaller is used because" in spec  # the reason next to the code


def test_build_artifacts_are_ignored_by_git():
    ignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "build/" in ignore
    assert "dist/" in ignore


def test_the_app_never_imports_win32com_outside_the_adapter():
    """Packaging must not tempt anyone into a second COM entry point."""
    package = REPO_ROOT / "pdf_ai_batch"
    offenders = []
    for path in package.rglob("*.py"):
        if path.parts[-2] in ("adapters", "tests"):
            continue
        if path.name in ("diagnostics.py",):  # the diagnostic import is guarded
            continue
        text = path.read_text(encoding="utf-8")
        if "win32com" in text and "import win32com" in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []


