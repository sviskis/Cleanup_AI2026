<#
.SYNOPSIS
    Creates a desktop shortcut for an installed Cleanup AI 2026 build.

.DESCRIPTION
    Deliberately NOT automatic: nothing in the build or the application ever writes to
    the desktop. Run this once after building or installing, or skip it and start the
    .exe from its own folder.

    The shortcut targets "Cleanup AI 2026.exe" and starts in its own folder (the
    application derives every path from the executable, so the working directory does
    not matter - this only keeps Windows happy for file dialogs).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\create_shortcut.ps1
    powershell -ExecutionPolicy Bypass -File tools\create_shortcut.ps1 -Target "D:\Apps\Cleanup AI 2026"
    powershell -ExecutionPolicy Bypass -File tools\create_shortcut.ps1 -AllUsers -Name "Cleanup AI 2026"
#>
[CmdletBinding()]
param(
    [string]$Target = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..")).Path "dist\Cleanup AI 2026"),
    [string]$Name = "Cleanup AI 2026",
    [string]$ShortcutFolder = [Environment]::GetFolderPath("Desktop"),
    [switch]$AllUsers
)

$ErrorActionPreference = "Stop"

$exe = Join-Path $Target "Cleanup AI 2026.exe"
if (-not (Test-Path $exe)) {
    throw "Nav atrasts: $exe`nVispirms palaid tools\build_release.ps1 vai norādi -Target <instalācijas mape>"
}

if ($AllUsers) {
    $ShortcutFolder = Join-Path $env:PUBLIC "Desktop"
}
if (-not (Test-Path $ShortcutFolder)) {
    New-Item -ItemType Directory -Force -Path $ShortcutFolder | Out-Null
}

$link = Join-Path $ShortcutFolder "$Name.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = $exe
$shortcut.WorkingDirectory = $Target
$shortcut.Description = "Cleanup AI 2026 - PDF uz AI tīrīšana ar Illustrator"
$shortcut.IconLocation = "$exe,0"
$shortcut.Save()

Write-Host "Īsceļš izveidots: $link"
Write-Host "  mērķis : $exe"
Write-Host "  mape   : $Target"
Write-Host ""
Write-Host "Dzēst: Remove-Item '$link'"
