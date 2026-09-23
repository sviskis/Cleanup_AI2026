# Python environment

Recorded so that a future session (or another machine) knows exactly what the
project was developed and tested against.

## Interpreter

| Item | Value |
| --- | --- |
| Version | **3.14.0** (`tags/v3.14.0:ebf955d, Oct 7 2025, 10:15:03 [MSC v.1944 64 bit (AMD64)]`) |
| Executable | `<repo>\.venv\Scripts\python.exe` |
| System base | `C:\Python314\python.exe` (Python 3.13 is also installed as `py -3.13`) |
| Platform | `Windows-10-10.0.19045-SP0` |
| Virtual environment | `<repo>\.venv` (git ignored) |

### Create / recreate the venv

```powershell
cd <repo>
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Installed packages (`pip freeze`)

```text
colorama==0.4.6
iniconfig==2.3.0
packaging==26.3
pluggy==1.6.0
Pygments==2.21.0
pymupdf==1.28.2
pypdf==6.19.0
pytest==9.1.1
pywin32==312
```

| Package | Role |
| --- | --- |
| `pymupdf` (PyMuPDF) | authoritative PDF page count and page geometry |
| `pypdf` | pure Python fallback for the page count |
| `pywin32` | the only COM bridge, used exclusively by `pdf_ai_batch/adapters/illustrator.py` |
| `pytest` | the Python test suite (`colorama`, `iniconfig`, `packaging`, `pluggy`, `Pygments` are its dependencies) |

`requirements.txt` pins the minimum versions; the freeze above is the exact set
used for the verification runs recorded in `STATUS.md` and `MIGRATION_PLAN.md`.

## Verified commands

```powershell
# Python tests (80)
.venv\Scripts\python.exe -m pytest

# environment / path report
.venv\Scripts\python.exe app.py --diagnose

# Illustrator availability (attach only)
.venv\Scripts\python.exe app.py --health
```

## Notes

* PyMuPDF 1.24+ is imported as `pymupdf`; older releases expose only `fitz`.
  `pdf_ai_batch.core.pdf_info.load_pymupdf()` accepts both, so the code works on
  either generation without a deprecation warning.
* The console code page is switched to UTF-8 (65001) by
  `logging_setup.configure_console()`; otherwise Latvian text raises
  `UnicodeEncodeError` in a default Windows console. In older PowerShell hosts the
  captured output can still look garbled - the log files are always correct UTF-8.
* `pywin32` is installed with its post-install step handled by pip; no manual
  `pywin32_postinstall.py` run was needed for this project.
