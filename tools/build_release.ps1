<#
.SYNOPSIS
    Builds the Windows distribution of Cleanup AI 2026 ("Cleanup AI 2026.exe").

.DESCRIPTION
    One command that cleans old artifacts and produces a ready to run folder:

        dist/
          Cleanup AI 2026/
            Cleanup AI 2026.exe     the application (windowed, no console)
            program/               Python + libraries + the application package
            program/jsx/           the worker, bundled so the exe finds it anywhere
            jsx/                   worker.jsx, cleanup.jsx, json2.js (readable copies)
            config/                default_config.json
            logs/                  application diagnostics (JOB logs stay in JOB/LOG)
            docs/, README.md, VERSION

    Packaging uses PyInstaller (see tools/cleanup_ai.spec for why). Illustrator is
    never bundled: the .exe talks to the installed Illustrator through COM.

    Development is untouched: `python app.py` keeps working exactly as before.

.PARAMETER Configuration
    Release (default) or Debug (keeps the console for troubleshooting).

.PARAMETER SkipTests
    Skip the gate (check_jsx + run_tests + pytest) that normally runs first.

.PARAMETER Python
    Interpreter to build with (default: .venv\Scripts\python.exe, else "python").
#>
[CmdletBinding()]
param(
    [ValidateSet("Release", "Debug")]
    [string]$Configuration = "Release",
    [switch]$SkipTests,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repo

function Write-Step([string]$Text) {
    Write-Host ""
    Write-Host "=== $Text ===" -ForegroundColor Cyan
}

# ------------------------------------------------------------------ the interpreter
if (-not $Python) {
    $venvPython = Join-Path $repo ".venv\Scripts\python.exe"
    $Python = if (Test-Path $venvPython) { $venvPython } else { "python" }
}
if (-not (Test-Path $Python)) {
    throw "Python nav atrasts: $Python (izmanto -Python <ceļš>)"
}
Write-Host "Python : $Python"
$version = (& $Python -c "import sys; print(sys.version.split()[0])")
Write-Host "Versija: $version"

$appVersion = (Get-Content (Join-Path $repo "VERSION") -Raw).Trim()
Write-Host "Release: $appVersion ($Configuration)"

# ---------------------------------------------------------------------------- gates
if (-not $SkipTests) {
    Write-Step "Gate 1/3 tools\check_jsx.ps1"
    & powershell -ExecutionPolicy Bypass -File (Join-Path $repo "tools\check_jsx.ps1") | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "check_jsx.ps1 neizturēja" }
    Write-Step "Gate 2/3 tools\run_tests.ps1"
    & powershell -ExecutionPolicy Bypass -File (Join-Path $repo "tools\run_tests.ps1") | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "run_tests.ps1 neizturēja" }
    Write-Step "Gate 3/3 pytest"
    & $Python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "pytest neizturēja" }
} else {
    Write-Host "Gate izlaists (-SkipTests)"
}

# ------------------------------------------------------------------------ cleaning
Write-Step "Tīru vecos artefaktus"
foreach ($folder in @("build", "dist")) {
    $path = Join-Path $repo $folder
    if (Test-Path $path) {
        Remove-Item -Recurse -Force $path
        Write-Host "  dzēsts $folder"
    }
}

# -------------------------------------------------------------------------- building
Write-Step "PyInstaller ($Configuration)"
if ($Configuration -eq "Debug") {
    # a debug build keeps the console so a traceback is visible
    $env:CLEANUP_AI_DEBUG = "1"
}
& $Python -m PyInstaller --noconfirm --clean --distpath (Join-Path $repo "dist") --workpath (Join-Path $repo "build") (Join-Path $repo "tools\cleanup_ai.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller neizturēja" }

$distApp = Join-Path $repo "dist\Cleanup AI 2026"
if (-not (Test-Path $distApp)) { throw "Nav izveidota mape: $distApp" }

# ------------------------------------------------- assets next to the exe (readable)
Write-Step "Kopēju resursus blakus .exe"
$inner = Join-Path $distApp "program"
foreach ($folder in @("jsx", "config", "docs")) {
    $source = Join-Path $repo $folder
    if (-not (Test-Path $source)) { continue }
    $target = Join-Path $distApp $folder
    if (Test-Path $target) { Remove-Item -Recurse -Force $target }
    Copy-Item -Recurse -Force $source $target
    Write-Host "  $folder"
}
foreach ($folder in @("jsx", "config")) {
    $source = Join-Path $repo $folder
    if (-not (Test-Path $source)) { continue }
    Copy-Item -Recurse -Force $source (Join-Path $inner $folder)
}
foreach ($file in @("README.md", "VERSION", "CHANGELOG.md", "ARCHITECTURE.md", "STATUS.md")) {
    $source = Join-Path $repo $file
    if (Test-Path $source) { Copy-Item -Force $source (Join-Path $distApp $file) }
}
New-Item -ItemType Directory -Force -Path (Join-Path $distApp "logs") | Out-Null

# ---------------------------------------------------------------------- verification
Write-Step "Pārbaudu distribūciju"
$exe = Join-Path $distApp "Cleanup AI 2026.exe"
if (-not (Test-Path $exe)) { throw "Trūkst Cleanup AI 2026.exe" }
$required = @(
    "jsx\worker.jsx",
    "jsx\cleanup.jsx",
    "jsx\json2.js",
    "config\default_config.json",
    "VERSION",
    "program\jsx\worker.jsx",
    "program\config\default_config.json"
)
foreach ($relative in $required) {
    $path = Join-Path $distApp $relative
    if (-not (Test-Path $path)) { throw "Trūkst resursa: $relative" }
    Write-Host "  [ok] $relative"
}
if (Test-Path (Join-Path $distApp "program\Illustrator.exe")) {
    throw "Illustrator nedrīkst būt iekļauts distribūcijā"
}

# ---------------------------------------------------------------- production smoke
Write-Step "Dūmu tests: --diagnose no .exe"
New-Item -ItemType Directory -Force -Path (Join-Path $repo "temp") | Out-Null
$outFile = Join-Path $repo "temp\build_diagnose.txt"
Remove-Item -Force $outFile -ErrorAction SilentlyContinue
$process = Start-Process -FilePath $exe -ArgumentList "--diagnose" -Wait -PassThru -NoNewWindow -RedirectStandardOutput $outFile
if (Test-Path $outFile) { Get-Content $outFile -Encoding UTF8 | ForEach-Object { Write-Host "  $_" } }
if ($process.ExitCode -ne 0) {
    Write-Warning "Diagnose atgrieza kodu $($process.ExitCode) - skatīt temp\build_diagnose.txt"
} else {
    Write-Host "Diagnose: OK (kod 0)"
}

Write-Step "Gatavs"
$size = [math]::Round((Get-ChildItem -Recurse $distApp | Measure-Object -Property Length -Sum).Sum / 1MB, 1)
Write-Host "Distribūcija: $distApp"
Write-Host "Izmērs      : $size MB"
Write-Host "Palaid      : `"$exe`""
Write-Host ""
Write-Host "Īsceļu darbvirsmā var izveidot ar:"
Write-Host "  powershell -ExecutionPolicy Bypass -File tools\create_shortcut.ps1"
