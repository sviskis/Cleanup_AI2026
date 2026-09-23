# ============================================================================
#  PDF Deep Cleanup AI 2026 - static project checks
# ----------------------------------------------------------------------------
#  What it verifies (no Illustrator needed):
#    1. #include resolution   - every include in src/Main.jsx exists, the bundle
#                               can be built, and no module is orphaned.
#    2. ExtendScript syntax   - the bundle is compiled by the WSH JScript engine
#                               (ES3), see tools/jscript_parse.js.
#    3. ES3 safety scan       - no let/const/arrow/async/await/class/import/
#                               export/Promise/template literals, and no ES5+
#                               array or string helpers.
#    4. Module API wiring     - every PDC.<Module>.<member> reference used by the
#                               code exists in that module's public API.
#
#  Usage:
#     powershell -ExecutionPolicy Bypass -File tools/check_jsx.ps1
#     powershell -ExecutionPolicy Bypass -File tools/check_jsx.ps1 -SkipParse
#
#  Exit code 0 = all checks passed, 1 = at least one ERROR.
# ============================================================================

[CmdletBinding()]
param(
    [string[]]$Entry = @('src\Main.jsx', 'jsx\worker.jsx'),
    [switch]$SkipParse
)

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = [System.IO.Path]::GetFullPath((Join-Path $scriptDir '..'))
$tempDir = Join-Path $root 'temp'
if (-not (Test-Path -LiteralPath $tempDir)) { New-Item -ItemType Directory -Path $tempDir -Force | Out-Null }

$errors = 0
$warnings = 0

function Fail([string]$msg) { Write-Host ("[FAIL] " + $msg); $script:errors++ }
function Warn([string]$msg) { Write-Host ("[WARN] " + $msg); $script:warnings++ }
function Pass([string]$msg) { Write-Host ("[OK]   " + $msg) }

# ---------------------------------------------------------------- 1. includes
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
        if (-not (Test-Path -LiteralPath $inc)) {
            Fail ("missing include: " + $m.Groups[1].Value + "  (from " + [System.IO.Path]::GetFileName($full) + ")")
            continue
        }
        Resolve-Includes -path $inc -seen $seen -ordered $ordered -depth ($depth + 1)
    }
    [void]$ordered.Add($full)
}

Write-Host "=== 1. include resolution ==="

$scanRoots = @((Join-Path $root 'src'), (Join-Path $root 'jsx'))
$scanFiles = @()
foreach ($r in $scanRoots) {
    if (Test-Path -LiteralPath $r) { $scanFiles += @(Get-ChildItem -LiteralPath $r -Recurse -Filter *.jsx) }
}

$seen = New-Object System.Collections.ArrayList
$entryBundles = @()
foreach ($e in $Entry) {
    $entryFull = [System.IO.Path]::GetFullPath((Join-Path $root $e))
    if (-not (Test-Path -LiteralPath $entryFull)) { Warn ("entry point not found, skipped: " + $e); continue }
    $ordered = New-Object System.Collections.ArrayList
    Resolve-Includes -path $entryFull -seen $seen -ordered $ordered
    Pass ("includes resolved: " + $e + " -> " + ($ordered.Count - 1) + " modules + entry point")
    $entryBundles += ,@{ name = $e; files = $ordered }
}
if ($entryBundles.Count -eq 0) { Fail "no entry point could be resolved"; exit 1 }

foreach ($f in $scanFiles) {
    if (-not $seen.Contains($f.FullName)) { Fail ("jsx module is never included: " + $f.FullName.Substring($root.Length + 1)) }
}
if ($errors -eq 0) { Pass ("all " + $scanFiles.Count + " jsx modules are reachable from an entry point") }

# ---------------------------------------------------------------- 2. bundle
Write-Host ""
Write-Host "=== 2. bundle + ExtendScript syntax ==="

function Strip-CommentsAndStrings([string]$text) {
    $t = Strip-Comments $text
    $t = [regex]::Replace($t, '"(?:[^"\\\n]|\\.)*"', '""')
    $t = [regex]::Replace($t, "'(?:[^'\\\n]|\\.)*'", "''")
    $t = [regex]::Replace($t, '/(?:[^/\\\n\[]|\\.|\[(?:[^\]\\]|\\.)*\])+/[gimsx]*', ' REX ')
    return $t
}

function Strip-Comments([string]$text) {
    $t = $text
    $t = [regex]::Replace($t, '(?s)/\*.*?\*/', ' ')
    $t = [regex]::Replace($t, '(?m)//[^\n]*', ' ')
    return $t
}

foreach ($b in $entryBundles) {
    $bundleParts = New-Object System.Collections.ArrayList
    foreach ($f in $b.files) {
        $rel = $f.Substring($root.Length + 1)
        [void]$bundleParts.Add("/* ================= " + $rel + " ================= */")
        [void]$bundleParts.Add([System.IO.File]::ReadAllText($f))
    }
    $bundle = (($bundleParts -join "`n") -replace "`r`n", "`n")
    $bundleName = 'verify_' + ([System.IO.Path]::GetFileNameWithoutExtension($b.name)) + '.js'
    $bundleFile = Join-Path $tempDir $bundleName
    [System.IO.File]::WriteAllText($bundleFile, $bundle, (New-Object System.Text.UTF8Encoding($false)))
    Pass ("bundle written: temp\" + $bundleName + "  (" + $bundle.Length + " chars)")

    if (-not $SkipParse) {
        $parse = & cscript //nologo //E:JScript (Join-Path $scriptDir 'jscript_parse.js') $bundleFile 2>&1
        $parseText = ($parse | Out-String)
        if ($parseText -match 'PARSE_OK') {
            Pass ("ExtendScript/JScript parse OK: " + $b.name)
        } else {
            Fail ("parse failed for " + $b.name + ": " + $parseText.Trim())
        }
    }
}
if ($SkipParse) { Warn "parse skipped (-SkipParse)" }

# ---------------------------------------------------------------- 3. ES3 scan
Write-Host ""
Write-Host "=== 3. ES3 safety scan ==="

$hardPatterns = @{
    '\blet\s+[A-Za-z_$]'    = 'let declaration'
    '\bconst\s+[A-Za-z_$]'  = 'const declaration'
    '=>'                    = 'arrow function'
    '\basync\s+function'    = 'async function'
    '\bawait\s+[A-Za-z_$(]' = 'await'
    '(?m)^\s*class\s+[A-Za-z_$]' = 'class declaration'
    '(?m)^\s*import\s+'     = 'import statement'
    '(?m)^\s*export\s+'     = 'export statement'
    '\bnew\s+Promise\s*\('  = 'Promise'
    '`'                     = 'template literal'
    '\?\?\s'                = 'nullish coalescing'
    '\?\.'                  = 'optional chaining'
    '\.\.\.'                = 'spread / rest'
}
$softPatterns = @{
    '\.forEach\s*\('   = 'Array.forEach (ES5)'
    '\.map\s*\('       = 'Array.map (ES5)'
    '\.filter\s*\('    = 'Array.filter (ES5)'
    '\.reduce\s*\('    = 'Array.reduce (ES5)'
    'Object\.keys\s*\(' = 'Object.keys (ES5)'
    'Object\.assign\s*\(' = 'Object.assign (ES6)'
    'JSON\.(stringify|parse)\s*\(' = 'JSON (ES5)'
    '\.trim\s*\('      = 'String.trim (ES5)'
    '\.startsWith\s*\(' = 'String.startsWith (ES6)'
    '\.endsWith\s*\('  = 'String.endsWith (ES6)'
    '\.includes\s*\('  = 'String.includes (ES6)'
}

$scannedFiles = @($scanFiles)
$hardHits = 0
$softHits = 0

# JSON is an ES5 global, but this project ships its own polyfill (jsx/json2.js).
# When the polyfill is part of a bundle, JSON.* in the worker is expected.
$jsonProvided = $false
foreach ($b in $entryBundles) {
    foreach ($bf in $b.files) {
        if ([System.IO.Path]::GetFileName($bf) -eq 'json2.js') { $jsonProvided = $true }
    }
}

foreach ($f in $scannedFiles) {
    $rel = $f.FullName.Substring($root.Length + 1)
    $code = Strip-CommentsAndStrings ([System.IO.File]::ReadAllText($f.FullName))
    foreach ($p in $hardPatterns.Keys) {
        if ($code -match $p) {
            Fail ($rel + ": forbidden syntax -> " + $hardPatterns[$p])
            $hardHits++
        }
    }
    foreach ($p in $softPatterns.Keys) {
        if ($code -match $p) {
            if ($jsonProvided -and $softPatterns[$p] -like 'JSON*') { continue }
            Warn ($rel + ": verify support in ExtendScript -> " + $softPatterns[$p])
            $softHits++
        }
    }
}
if ($hardHits -eq 0) { Pass ("no forbidden ES5+/ES6 syntax in " + $scannedFiles.Count + " files") }
if ($softHits -eq 0) { Pass "no unexpected ES5+ array/string helpers found" }
if ($jsonProvided) { Pass "JSON.* is available: jsx/json2.js polyfill is part of the worker bundle" }

# ---------------------------------------------------------------- 4. PDC wiring
Write-Host ""
Write-Host "=== 4. module API wiring (PDC.<Module>.<member>) ==="

$moduleApi = @{}
foreach ($f in $scanFiles) {
    $text = Strip-Comments ([System.IO.File]::ReadAllText($f.FullName))
    $m = [regex]::Match($text, 'registerModule\(\s*"([^"]+)"')
    if (-not $m.Success) { continue }
    $name = $m.Groups[1].Value
    $members = New-Object System.Collections.Generic.List[string]
    # every "name: value" entry in the file counts as public API
    foreach ($mm in [regex]::Matches($text, '(?m)^\s*([A-Za-z_$][A-Za-z0-9_$]*)\s*:')) {
        if (-not $members.Contains($mm.Groups[1].Value)) { [void]$members.Add($mm.Groups[1].Value) }
    }
    $moduleApi[$name] = $members
}

$builtinRoots = @('CONFIG', 'MODULES', 'registerModule', 'moduleList')
$refErrors = 0
foreach ($f in $scannedFiles) {
    $rel = $f.FullName.Substring($root.Length + 1)
    $code = Strip-CommentsAndStrings ([System.IO.File]::ReadAllText($f.FullName))
    foreach ($m in [regex]::Matches($code, 'PDC\.([A-Za-z_$][A-Za-z0-9_$]*)\.([A-Za-z_$][A-Za-z0-9_$]*)')) {
        $mod = $m.Groups[1].Value
        $member = $m.Groups[2].Value
        if ($builtinRoots -contains $mod) { continue }
        if (-not $moduleApi.ContainsKey($mod)) {
            Fail ($rel + ": PDC." + $mod + " is not a registered module")
            $refErrors++
            continue
        }
        if (-not $moduleApi[$mod].Contains($member)) {
            Fail ($rel + ": PDC." + $mod + "." + $member + " is not exported by " + $mod)
            $refErrors++
        }
    }
}
if ($refErrors -eq 0) { Pass "all PDC module references resolve to exported members" }

# ---------------------------------------------------------------- summary
Write-Host ""
Write-Host "========================================"
Write-Host ("ERRORS: " + $errors + " | WARNINGS: " + $warnings)
Write-Host "========================================"
if ($errors -gt 0) { exit 1 }
exit 0
