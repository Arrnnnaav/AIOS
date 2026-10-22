# Install the built Orbyn app for the current user and add Start Menu + Desktop
# shortcuts, so Orbyn launches like any installed app instead of from dist\.
# No admin, no MSI tooling. Build first with tools\build_orbyn.ps1.
#
#   pwsh -File tools\Install-Orbyn.ps1            # install / update
#   pwsh -File tools\Install-Orbyn.ps1 -Uninstall # remove app + shortcuts
#
# NOTE: the exe is not code-signed yet, so the first launch may show a Windows
# SmartScreen prompt (More info -> Run anyway). Signing is an owner step.

param([switch]$Uninstall)
$ErrorActionPreference = 'Stop'

$AppName     = 'Orbyn'
$InstallDir  = Join-Path $env:LOCALAPPDATA "Programs\$AppName"
$StartMenuLnk = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\$AppName.lnk"
$DesktopLnk   = Join-Path ([Environment]::GetFolderPath('Desktop')) "$AppName.lnk"

function New-Shortcut([string]$Path, [string]$Target, [string]$WorkDir) {
    $shell = New-Object -ComObject WScript.Shell
    $s = $shell.CreateShortcut($Path)
    $s.TargetPath       = $Target
    $s.WorkingDirectory = $WorkDir
    $s.IconLocation     = $Target
    $s.Description       = 'Orbyn - local-first Windows desktop guide'
    $s.Save()
}

if ($Uninstall) {
    Remove-Item $StartMenuLnk, $DesktopLnk -Force -ErrorAction SilentlyContinue
    if (Test-Path $InstallDir) { Remove-Item $InstallDir -Recurse -Force }
    Write-Host "Orbyn uninstalled (install dir + shortcuts removed)."
    return
}

$RepoDist = Join-Path $PSScriptRoot '..\dist\Orbyn'
$BuiltExe = Join-Path $RepoDist 'Orbyn.exe'
if (-not (Test-Path $BuiltExe)) {
    throw "No build found at $BuiltExe. Build it first:  pwsh -File tools\build_orbyn.ps1"
}

# Don't copy over a running install.
Get-Process Orbyn -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item (Join-Path $RepoDist '*') $InstallDir -Recurse -Force
$InstalledExe = Join-Path $InstallDir 'Orbyn.exe'

New-Shortcut $StartMenuLnk $InstalledExe $InstallDir
New-Shortcut $DesktopLnk   $InstalledExe $InstallDir

Write-Host "Orbyn installed to: $InstallDir"
Write-Host "Shortcuts added: Start Menu and Desktop. Launch 'Orbyn' from either."
Write-Host "(Keep Ollama running for planning/Teach:  ollama serve)"
