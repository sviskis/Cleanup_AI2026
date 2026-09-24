@echo off
REM ============================================================================
REM  Cleanup AI 2026 - GUI launcher (double-click this file)
REM ----------------------------------------------------------------------------
REM  Starts the Tkinter GUI of the source checkout with the repository virtual
REM  environment:   .venv\Scripts\pythonw.exe app.py
REM
REM  * every path is derived from this file (%~dp0), so the launcher works from
REM    any current working directory and from a shortcut in any folder;
REM  * pythonw.exe is the windowed interpreter: no cmd window stays open;
REM  * app.py resolves the repository itself (pdf_ai_batch/paths.py never uses
REM    the current working directory), so the working folder only has to be
REM    valid - "%ROOT%" is passed explicitly to make that true everywhere;
REM  * the messages are plain ASCII on purpose (a batch file is decoded with the
REM    console code page, so non-ASCII text would arrive as mojibake).
REM ============================================================================

setlocal
set "ROOT=%~dp0"

if not exist "%ROOT%.venv\Scripts\pythonw.exe" (
    echo.
    echo ERROR: pythonw.exe nav atrasts.
    echo        Meklets: "%ROOT%.venv\Scripts\pythonw.exe"
    echo.
    echo Izveidojiet virtualo vidi:
    echo     py -3 -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    endlocal
    exit /b 1
)

if not exist "%ROOT%app.py" (
    echo.
    echo ERROR: app.py nav atrasts.
    echo        Meklets: "%ROOT%app.py"
    echo        Palaisiet so failu no repozitorija saknes mapes.
    echo.
    pause
    endlocal
    exit /b 1
)

start "" /d "%ROOT%" "%ROOT%.venv\Scripts\pythonw.exe" "%ROOT%app.py"
endlocal
exit /b 0
