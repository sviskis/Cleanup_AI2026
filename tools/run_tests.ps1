# ============================================================================
#  Cleanup AI 2026 - unit test runner
# ----------------------------------------------------------------------------
#  Builds a test bundle from the src modules (entry point excluded, because it
#  opens the GUI) and runs it with the Windows Script Host JScript engine:
#
#      tests/jscript/stubs.js          - fake File/Folder/app host
#      src/**/*.jsx                    - real project code, in include order
#      tests/jscript/run_tests.js      - assertions
#
#  Usage:
#      powershell -ExecutionPolicy Bypass -File tools/run_tests.ps1
#
#  Exit code 0 = all tests passed.
# ============================================================================

[CmdletBinding()]
param(
    [switch]$ShowBundle
)

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = [System.IO.Path]::GetFullPath((Join-Path $scriptDir '..'))
$tempDir = Join-Path $root 'temp'
if (-not (Test-Path -LiteralPath $tempDir)) { New-Item -ItemType Directory -Path $tempDir -Force | Out-Null }

# module order = include order from src/Main.jsx, without Main.jsx itself
$modules = @(
    'src\utils\Namespace.jsx',
    'src\config\Config.jsx',
    'src\utils\TextUtils.jsx',
    'src\services\FileService.jsx',
    'src\utils\Paths.jsx',
    'src\services\LogService.jsx',
    'src\services\ErrorService.jsx',
    'jsx\cleanup.jsx',
    'src\core\PdfPageCount.jsx',
    'src\core\TemplateManager.jsx',
    'src\core\OutputManager.jsx',
    'src\core\BatchRunner.jsx',
    'src\core\Diagnostics.jsx',
    'src\ui\BatchWindow.jsx'
)

$parts = New-Object System.Collections.ArrayList

function Add-Part {
    param([string]$relative, [string]$banner)
    $full = Join-Path $root $relative
    if (-not (Test-Path -LiteralPath $full)) { throw "missing test input: $relative" }
    [void]$parts.Add("/* ================= " + $banner + " ================= */")
    [void]$parts.Add([System.IO.File]::ReadAllText($full))
    Write-Host ("  + " + $relative)
}

Write-Host "building test bundle:"
Add-Part 'tests\jscript\stubs.js' 'test host stubs'
foreach ($m in $modules) { Add-Part $m $m }
Add-Part 'tests\jscript\run_tests.js' 'test suite'

$bundle = ($parts -join "`n") -replace "`r`n", "`n"
$bundleFile = Join-Path $tempDir 'test_bundle.js'
[System.IO.File]::WriteAllText($bundleFile, $bundle, (New-Object System.Text.UTF8Encoding($false)))

if ($ShowBundle) { Write-Host ("bundle: " + $bundleFile + " (" + $bundle.Length + " chars)") }

Write-Host ""
Write-Host "running tests (cscript //E:JScript) ..."
$output = & cscript //nologo //E:JScript $bundleFile 2>&1
$text = ($output | Out-String)
$text = $text -replace "`r`n", "`n"
Write-Host $text.TrimEnd()

Write-Host ""
if ($LASTEXITCODE -eq 0 -and $text -match 'ALL TESTS PASSED') {
    Write-Host "RESULT: unit tests PASSED"
} else {
    Write-Host "RESULT: unit tests FAILED (exit code $LASTEXITCODE)"
    exit 1
}

# ---------------------------------------------------------------- JSON contract
Write-Host ""
Write-Host "running JSON contract test (jsx/json2.js + tests/fixtures) ..."
$jsonTest = Join-Path $scriptDir '..\tests\jscript\test_json_contract.js'
$jsonOut = & cscript //nologo //E:JScript $jsonTest 2>&1
$jsonText = ($jsonOut | Out-String) -replace "`r`n", "`n"
Write-Host $jsonText.TrimEnd()

Write-Host ""
if ($LASTEXITCODE -eq 0 -and $jsonText -match 'JSON CONTRACT TESTS PASSED') {
    Write-Host "RESULT: JSON contract tests PASSED"
    exit 0
}
Write-Host "RESULT: JSON contract tests FAILED (exit code $LASTEXITCODE)"
exit 1
