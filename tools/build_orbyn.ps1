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

# Code signing: set ORBYN_SIGN_THUMBPRINT to the thumbprint of a code-signing
# certificate in Cert:\CurrentUser\My (or LocalMachine\My). Without it the
# build is unsigned and Windows SmartScreen warns before it runs.
$exe = Join-Path $bundle 'Orbyn.exe'
$thumb = $env:ORBYN_SIGN_THUMBPRINT
if ($thumb) {
    $cert = Get-ChildItem Cert:\CurrentUser\My, Cert:\LocalMachine\My -CodeSigningCert -ErrorAction SilentlyContinue |
        Where-Object { $_.Thumbprint -eq $thumb } | Select-Object -First 1
    if (-not $cert) { throw "No code-signing certificate with thumbprint $thumb." }
    $stamp = if ($env:ORBYN_TIMESTAMP_URL) { $env:ORBYN_TIMESTAMP_URL } else { 'http://timestamp.digicert.com' }
    $result = Set-AuthenticodeSignature -FilePath $exe -Certificate $cert -HashAlgorithm SHA256 -TimestampServer $stamp
    if ($result.Status -notin 'Valid', 'UnknownError') { throw "Signing failed: $($result.StatusMessage)" }
    Write-Host "Signed $exe ($($result.Status): $($result.StatusMessage))"
} else {
    Write-Host "Not signed: set ORBYN_SIGN_THUMBPRINT to sign the build."
}
Write-Host "Built $bundle\Orbyn.exe  (double-click to open the workspace island)"
