# ============================================================================
#  PDF Deep Cleanup AI 2026 - freeze the current working JSX application
# ----------------------------------------------------------------------------
#  Builds ONE standalone, runnable .jsx from the current multi-module app in
#  src/ by inlining every #include in order. The result is the frozen reference
#  of the working version:
#
#      legacy/current_working_v10.jsx
#
#  It is the behavioural baseline for the Python + JSX worker migration:
#  run it in Illustrator exactly like before, and compare the new pipeline
#  against it.
#
#  The frozen file is NEVER edited by hand. Re-run this tool only to freeze a
#  newer version (and then update the hash in legacy/README.md).
#
#  Usage:
#      powershell -ExecutionPolicy Bypass -File tools\freeze_legacy.ps1
# ============================================================================

[CmdletBinding()]
param(
    [string]$Entry      = 'src\Main.jsx',
    [string]$OutFile    = 'legacy\current_working_v10.jsx',
    [string]$ReadmeFile = 'legacy\README.md'
)

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = [System.IO.Path]::GetFullPath((Join-Path $scriptDir '..'))
$utf8 = New-Object System.Text.UTF8Encoding($false)

$entryFull = Join-Path $root $Entry
if (-not (Test-Path -LiteralPath $entryFull)) { throw "entry point not found: $Entry" }

function Resolve-Includes {
    param([string]$path, [System.Collections.ArrayList]$seen, [System.Collections.ArrayList]$ordered, [int]$depth = 0)
    if ($depth -gt 16) { throw "include nesting too deep at $path" }
    $full = [System.IO.Path]::GetFullPath($path)
    if ($seen.Contains($full)) { return }
    [void]$seen.Add($full)
    $text = [System.IO.File]::ReadAllText($full)
    $dir = Split-Path -Parent $full
    foreach ($m in [regex]::Matches($text, '(?m)^\s*#include\s+"([^"]+)"')) {
        $inc = Join-Path $dir $m.Groups[1].Value
        if (-not (Test-Path -LiteralPath $inc)) { throw ("missing include: " + $m.Groups[1].Value + " from " + $full) }
        Resolve-Includes -path $inc -seen $seen -ordered $ordered -depth ($depth + 1)
    }
    [void]$ordered.Add($full)
}

$seen = New-Object System.Collections.ArrayList
$ordered = New-Object System.Collections.ArrayList
Resolve-Includes -path $entryFull -seen $seen -ordered $ordered

$commit = (& git -C $root rev-parse --short HEAD 2>&1 | Out-String).Trim()
$date = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')

$bodyParts = New-Object System.Collections.ArrayList
$fileRows = New-Object System.Collections.ArrayList

foreach ($f in $ordered) {
    $rel = $f.Substring($root.Length + 1) -replace '\\', '/'
    $text = [System.IO.File]::ReadAllText($f)
    $text = $text -replace "`r`n", "`n"
    # drop ExtendScript preprocessor lines; the frozen file has one #target at the top
    $text = [regex]::Replace($text, '(?m)^[ \t]*#(target|targetengine|include|script)\b[^\n]*\n?', '')
    $sha = (Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash
    $lines = ($text -split "`n").Count
    [void]$fileRows.Add("| ``$rel`` | $lines | $sha |")
    [void]$bodyParts.Add("// ---------------------------------------------------------------------------")
    [void]$bodyParts.Add("// FROZEN FROM: $rel")
    [void]$bodyParts.Add("// ---------------------------------------------------------------------------")
    [void]$bodyParts.Add($text.TrimEnd("`n"))
    [void]$bodyParts.Add("")
}

$banner = New-Object System.Collections.ArrayList
[void]$banner.Add("/*")
[void]$banner.Add("    PDF DEEP CLEANUP AI 2026 - FROZEN WORKING VERSION (v10 baseline)")
[void]$banner.Add("")
[void]$banner.Add("    This single file was generated automatically by tools/freeze_legacy.ps1.")
[void]$banner.Add("    It is the frozen, runnable snapshot of the current working Illustrator")
[void]$banner.Add("    application (the multi module app under src/), inlined in include order.")
[void]$banner.Add("")
[void]$banner.Add("    Generated : $date")
[void]$banner.Add("    From      : $Entry")
[void]$banner.Add("    Git commit: $commit")
[void]$banner.Add("    Modules   : " + $ordered.Count)
[void]$banner.Add("")
[void]$banner.Add("    DO NOT EDIT. Edit src/ and regenerate, or edit nothing and compare against it.")
[void]$banner.Add("    Run: Illustrator -> File -> Scripts -> Other Script... -> this file")
[void]$banner.Add("*/")
[void]$banner.Add("")
[void]$banner.Add("#target illustrator")
[void]$banner.Add("")

$content = ($banner -join "`n") + "`n" + ($bodyParts -join "`n")
if ($content -notmatch "`n$") { $content = $content + "`n" }

$outFull = Join-Path $root $OutFile
$outDir = Split-Path -Parent $outFull
if (-not (Test-Path -LiteralPath $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
[System.IO.File]::WriteAllText($outFull, $content, $utf8)

$hash = (Get-FileHash -LiteralPath $outFull -Algorithm SHA256).Hash
$lineCount = (Get-Content -LiteralPath $outFull).Count
Write-Host ("FROZEN  " + $OutFile)
Write-Host ("  lines   : " + $lineCount)
Write-Host ("  bytes   : " + (Get-Item -LiteralPath $outFull).Length)
Write-Host ("  sha256  : " + $hash)
Write-Host ("  modules : " + $ordered.Count)

# ---------------------------------------------------------------- verify
$parse = & cscript //nologo //E:JScript (Join-Path $scriptDir 'jscript_parse.js') $outFull 2>&1
$parseText = ($parse | Out-String).Trim()
Write-Host ("  syntax  : " + $parseText)
if ($parseText -notmatch 'PARSE_OK') { throw "frozen file does not compile - aborting" }

# ---------------------------------------------------------------- readme
$readme = New-Object System.Collections.ArrayList
[void]$readme.Add("# Legacy - frozen working version")
[void]$readme.Add("")
[void]$readme.Add("\`current_working_v10.jsx\` is the **frozen, standalone snapshot of the working")
[void]$readme.Add("Illustrator application** (the multi module app under \`src/\`), generated by")
[void]$readme.Add("\`tools/freeze_legacy.ps1\`, which inlines every \`#include\` in order.")
[void]$readme.Add("")
[void]$readme.Add("It is the behavioural baseline for the Python + JSX worker migration: run it in")
[void]$readme.Add("Illustrator exactly as before, and compare the new pipeline against it.")
[void]$readme.Add("")
[void]$readme.Add("| Property | Value |")
[void]$readme.Add("| --- | --- |")
[void]$readme.Add("| Generated | $date |")
[void]$readme.Add("| Source entry point | \`$Entry\` |")
[void]$readme.Add("| Git commit | \`$commit\` |")
[void]$readme.Add("| Modules inlined | $($ordered.Count) |")
[void]$readme.Add("| Lines | $lineCount |")
[void]$readme.Add("| SHA256 | \`$hash\` |")
[void]$readme.Add("")
[void]$readme.Add("## How to run")
[void]$readme.Add("")
[void]$readme.Add('```text')
[void]$readme.Add("Illustrator -> File -> Scripts -> Other Script... -> legacy\current_working_v10.jsx")
[void]$readme.Add('```')
[void]$readme.Add("")
[void]$readme.Add("## Rules")
[void]$readme.Add("")
[void]$readme.Add("* **Do not edit this file.** It is generated; edit \`src/\` and re-freeze.")
[void]$readme.Add("* Do not delete it: it is the regression baseline (cases R1-R5 in \`docs/TESTING.md\`).")
[void]$readme.Add("* The older monoliths stay in \`archive/original/\` (read only, hashes in")
[void]$readme.Add("  \`archive/original/ARCHIVE_MANIFEST.md\`). They are predecessors, not the baseline.")
[void]$readme.Add("")
[void]$readme.Add("## Inlined modules")
[void]$readme.Add("")
[void]$readme.Add("| Module | Lines | SHA256 |")
[void]$readme.Add("| --- | --- | --- |")
[void]$readme.AddRange($fileRows)
[void]$readme.Add("")
[System.IO.File]::WriteAllText((Join-Path $root $ReadmeFile), (($readme -join "`n") + "`n"), $utf8)
Write-Host ("WROTE   " + $ReadmeFile)
