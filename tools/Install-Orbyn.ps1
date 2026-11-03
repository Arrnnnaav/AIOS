# Install or update the built Orbyn app for the current user. User data lives
# outside this directory in %LOCALAPPDATA%\GhostCursor.
#
#   pwsh -File tools\Install-Orbyn.ps1
#   pwsh -File tools\Install-Orbyn.ps1 -Uninstall
#   pwsh -File tools\Install-Orbyn.ps1 -AllUsers   # per machine, as admin (Intune/SCCM)
param(
    [switch]$Uninstall,
    # Per machine: Program Files, the all-users Start Menu and Public Desktop,
    # and the Explorer verb under HKEY_LOCAL_MACHINE. Needs an elevated shell.
    [switch]$AllUsers,
    [string]$SourceDir,
    [string]$InstallDir,
    [string]$StartMenuLnk,
    [string]$DesktopLnk,
    # Explorer's "Ask Orbyn about this file" verb (HKCU, or HKLM with -AllUsers).
    [string]$VerbKey = 'Software\Classes\*\shell\Orbyn.AskFile'
)
$ErrorActionPreference = 'Stop'

if ($AllUsers) {
    $principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'A per-machine install (-AllUsers) needs an elevated shell.'
    }
    $Hive = [Microsoft.Win32.Registry]::LocalMachine
    if (-not $InstallDir) { $InstallDir = Join-Path $env:ProgramFiles 'Orbyn' }
    if (-not $StartMenuLnk) { $StartMenuLnk = Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\Orbyn.lnk' }
    if (-not $DesktopLnk) { $DesktopLnk = Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) 'Orbyn.lnk' }
} else {
    $Hive = [Microsoft.Win32.Registry]::CurrentUser
}
if (-not $SourceDir) { $SourceDir = Join-Path $PSScriptRoot '..\dist\Orbyn' }
if (-not $InstallDir) { $InstallDir = Join-Path $env:LOCALAPPDATA 'Programs\Orbyn' }
if (-not $StartMenuLnk) { $StartMenuLnk = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Orbyn.lnk' }
if (-not $DesktopLnk) { $DesktopLnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Orbyn.lnk' }

$InstallDir = [IO.Path]::GetFullPath($InstallDir)
if ([IO.Path]::GetFileName($InstallDir) -ne 'Orbyn') { throw 'Install directory must end in Orbyn.' }
$ProgramRoot = [IO.Path]::GetDirectoryName($InstallDir)
$StageDir = Join-Path $ProgramRoot 'Orbyn.staging'
$BackupDir = Join-Path $ProgramRoot 'Orbyn.previous'
$CompleteMarker = Join-Path $InstallDir '.install-complete'
foreach ($target in @($StageDir, $BackupDir)) {
    if (-not ([IO.Path]::GetFullPath($target)).StartsWith($ProgramRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Installer transaction path escaped its parent directory.'
    }
}

function Set-AskVerb([string]$Exe) {
    # .NET, not the registry provider: '*' in a provider path is a wildcard.
    $key = $Hive.CreateSubKey($VerbKey)
    try {
        $key.SetValue('MUIVerb', 'Ask Orbyn about this file')
        $key.SetValue('Icon', "`"$Exe`"")
        $command = $key.CreateSubKey('command')
        try { $command.SetValue('', "`"$Exe`" --ask-file `"%1`"") } finally { $command.Dispose() }
    } finally { $key.Dispose() }
}

function Remove-AskVerb {
    $Hive.DeleteSubKeyTree($VerbKey, $false)
}

function New-Shortcut([string]$Path, [string]$Target, [string]$WorkDir) {
    $shell = New-Object -ComObject WScript.Shell
    $s = $shell.CreateShortcut($Path)
    $s.TargetPath = $Target
    $s.WorkingDirectory = $WorkDir
    $s.IconLocation = $Target
    $s.Description = 'Orbyn - local-first Windows desktop guide'
    $s.Save()
}

New-Item -ItemType Directory -Force -Path $ProgramRoot | Out-Null
$lock = [IO.File]::Open((Join-Path $ProgramRoot '.orbyn-installer.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
try {
    if (Get-Process Orbyn -ErrorAction SilentlyContinue) {
        throw 'Close Orbyn before installing, updating, or uninstalling it.'
    }
    # Restore the last complete install if a previous update was interrupted.
    if (Test-Path -LiteralPath $BackupDir) {
        if (Test-Path -LiteralPath $InstallDir) {
            if (Test-Path -LiteralPath $CompleteMarker) {
                Remove-Item -LiteralPath $BackupDir -Recurse -Force
            } else {
                Remove-Item -LiteralPath $InstallDir -Recurse -Force
                Move-Item -LiteralPath $BackupDir -Destination $InstallDir
            }
        } else {
            Move-Item -LiteralPath $BackupDir -Destination $InstallDir
        }
    }
    if (Test-Path -LiteralPath $StageDir) { Remove-Item -LiteralPath $StageDir -Recurse -Force }

    if ($Uninstall) {
        Remove-Item -LiteralPath $StartMenuLnk, $DesktopLnk -Force -ErrorAction SilentlyContinue
        Remove-AskVerb
        if (Test-Path -LiteralPath $InstallDir) { Remove-Item -LiteralPath $InstallDir -Recurse -Force }
        Write-Host 'Orbyn uninstalled; local workspace data was kept.'
        return
    }

    $SourceDir = [IO.Path]::GetFullPath($SourceDir)
    if (-not (Test-Path -LiteralPath (Join-Path $SourceDir 'Orbyn.exe'))) {
        throw "No build found at $SourceDir. Build it first: pwsh -File tools\build_orbyn.ps1"
    }
    New-Item -ItemType Directory -Path $StageDir | Out-Null
    try {
        Get-ChildItem -LiteralPath $SourceDir -Force | Copy-Item -Destination $StageDir -Recurse -Force
        if (-not (Test-Path -LiteralPath (Join-Path $StageDir 'Orbyn.exe'))) { throw 'Staged build is incomplete.' }
        Remove-Item -LiteralPath (Join-Path $StageDir '.install-complete') -Force -ErrorAction SilentlyContinue
        $hadInstall = Test-Path -LiteralPath $InstallDir
        if ($hadInstall) { Move-Item -LiteralPath $InstallDir -Destination $BackupDir }
        try {
            Move-Item -LiteralPath $StageDir -Destination $InstallDir
            $installedExe = Join-Path $InstallDir 'Orbyn.exe'
            New-Shortcut $StartMenuLnk $installedExe $InstallDir
            New-Shortcut $DesktopLnk $installedExe $InstallDir
            Set-AskVerb $installedExe
            Set-Content -LiteralPath $CompleteMarker -Value 'complete' -NoNewline
        } catch {
            if (Test-Path -LiteralPath $InstallDir) { Remove-Item -LiteralPath $InstallDir -Recurse -Force }
            if ($hadInstall -and (Test-Path -LiteralPath $BackupDir)) {
                Move-Item -LiteralPath $BackupDir -Destination $InstallDir
            } else {
                Remove-Item -LiteralPath $StartMenuLnk, $DesktopLnk -Force -ErrorAction SilentlyContinue
                Remove-AskVerb
            }
            throw
        }
        if ($hadInstall) { Remove-Item -LiteralPath $BackupDir -Recurse -Force }
    } finally {
        if (Test-Path -LiteralPath $StageDir) { Remove-Item -LiteralPath $StageDir -Recurse -Force }
    }
    Write-Host "Orbyn installed to: $InstallDir"
    Write-Host 'Start Menu and Desktop shortcuts point to this install; right-click a text file for "Ask Orbyn about this file".'
    Write-Host 'The app is not yet code-signed; Windows may show a SmartScreen prompt.'
} finally {
    $lock.Dispose()
}
