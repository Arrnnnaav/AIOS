param([string]$OutputDir = 'dist', [string]$Python = 'py -3.12')
# Build the packaged Orbyn desktop app -> dist/Orbyn/Orbyn.exe (onedir, windowed).
# Run from the repo root:  pwsh -File tools/build_orbyn.ps1
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')

$py = $Python.Split(' ', 2)
& $py[0] $py[1] -m pip show pyinstaller *> $null
if ($LASTEXITCODE -ne 0) { & $py[0] $py[1] -m pip install pyinstaller }

# UI Automation COM wrapper must exist before the build so PyInstaller bundles it.
& $py[0] $py[1] -c "import comtypes.client; comtypes.client.GetModule('UIAutomationCore.dll')"
if ($LASTEXITCODE -ne 0) { throw 'UI Automation setup failed.' }

& $py[0] $py[1] -m PyInstaller --noconfirm --distpath $OutputDir tools/orbyn.spec
if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }

$bundle = Join-Path $OutputDir 'Orbyn'
Copy-Item -LiteralPath 'README.md' -Destination (Join-Path $bundle 'README.md') -Force -ErrorAction SilentlyContinue
Write-Host "Built $bundle\Orbyn.exe  (double-click to open the workspace island)"
