# ============================================================================
#  Cleanup AI 2026 - line ending normaliser
# ----------------------------------------------------------------------------
#  Purpose:
#    The reference ExtendScript file uses LF line endings and UTF-8 without BOM.
#    Every project text file is kept the same way so that:
#      * Illustrator ExtendScript always reads the same bytes;
#      * git diffs stay free of whole-file "line ending changed" noise.
#
#  Usage:
#    powershell -ExecutionPolicy Bypass -File tools/normalize_eol.ps1
#    powershell -ExecutionPolicy Bypass -File tools/normalize_eol.ps1 -WhatIfOnly
#
#  A UTF-8 BOM is preserved when the file already had one (needed for the
#  PowerShell tools that contain Latvian text), it is never added.
# ============================================================================

[CmdletBinding()]
param(
    [string[]]$Path,
    [switch]$WhatIfOnly
)

$ErrorActionPreference = 'Stop'

$scriptDir = $MyInvocation.MyCommand.Path
# tools/normalize_eol.ps1 -> tools -> project root
$root = [System.IO.Path]::GetFullPath((Join-Path (Split-Path -Parent (Split-Path -Parent $scriptDir)) '.'))
if (-not $Path) { $Path = @($root) }

$extensions = @('.jsx', '.js', '.py', '.json', '.md', '.ps1', '.txt', '.gitignore', '.gitattributes', '.clinerules', '.yml', '.yaml', '.ini', '.toml')
$skipFolders = @('.git', '.venv', 'venv', 'archive\original', 'temp', 'logs', 'runtime', 'node_modules', '.pytest_cache', '__pycache__')

function Is-Skipped([string]$full) {
    foreach ($s in $skipFolders) {
        $marker = '\' + $s + '\'
        if ($full.IndexOf($marker) -ge 0) { return $true }
        if ($full.EndsWith('\' + $s)) { return $true }
    }
    if ($full.EndsWith('\.gitignore') -or $full.EndsWith('\.gitattributes')) { return $false }
    return $false
}

$changed = 0
$scanned = 0

foreach ($p in $Path) {
    $items = @()
    if (Test-Path -LiteralPath $p -PathType Container) {
        $items = Get-ChildItem -LiteralPath $p -Recurse -File -Force
    } else {
        $items = @(Get-Item -LiteralPath $p -Force)
    }

    foreach ($file in $items) {
        $full = $file.FullName
        if (Is-Skipped $full) { continue }

        $name = $file.Name
        $ext = [System.IO.Path]::GetExtension($name).ToLower()
        $isSpecial = ($name -eq '.gitignore' -or $name -eq '.gitattributes' -or $name -eq '.clinerules' -or $name -eq 'VERSION')
        if (-not $isSpecial -and ($extensions -notcontains $ext)) { continue }

        $scanned++
        $bytes = [System.IO.File]::ReadAllBytes($full)
        if ($bytes.Length -eq 0) { continue }

        $hasBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
        $offset = 0
        if ($hasBom) { $offset = 3 }

        $text = [System.Text.Encoding]::UTF8.GetString($bytes, $offset, $bytes.Length - $offset)
        $normalized = $text -replace "`r`n", "`n"
        $normalized = $normalized -replace "`r", "`n"

        if ($normalized -eq $text) { continue }

        if ($WhatIfOnly) {
            Write-Host ("WOULD NORMALISE " + $full)
            $changed++
            continue
        }

        $enc = New-Object System.Text.UTF8Encoding($hasBom)
        [System.IO.File]::WriteAllText($full, $normalized, $enc)
        Write-Host ("NORMALISED " + $full)
        $changed++
    }
}

Write-Host ""
Write-Host ("Files scanned: " + $scanned + " | files with CRLF: " + $changed)
