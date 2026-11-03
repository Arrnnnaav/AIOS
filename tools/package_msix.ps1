param(
    [string]$SourceDir = 'dist\Orbyn',
    [string]$Output = 'dist\Orbyn.msix',
    [string]$Version = '1.0.0.0',
    # Must equal the Subject of the signing certificate, e.g. 'CN=Example Ltd, O=Example Ltd, C=GB'.
    [string]$Publisher = 'CN=Orbyn Unsigned',
    [string]$PublisherDisplayName = 'Orbyn',
    # A code-signing .pfx. Without one the package is built unsigned and
    # Windows will not install it until it is signed.
    [string]$CertPath,
    [string]$CertPassword,
    [string]$TimestampUrl = 'http://timestamp.digicert.com'
)
# Package the built app (tools/build_orbyn.ps1) as an MSIX that Intune, SCCM or
# winget can deploy per machine. Run from the repo root:
#   pwsh -File tools/package_msix.ps1 -Publisher 'CN=...' -CertPath code.pfx -CertPassword ...
# File and registry write virtualization are off, so user data stays in
# %LOCALAPPDATA%\GhostCursor exactly as for the plain install (the console
# tools and the audit log read it there).
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')

$kit = Get-ChildItem 'C:\Program Files (x86)\Windows Kits\10\bin' -Directory |
    Where-Object { Test-Path (Join-Path $_.FullName 'x64\makeappx.exe') } |
    Sort-Object Name -Descending | Select-Object -First 1
if (-not $kit) { throw 'makeappx.exe not found: install the Windows 10/11 SDK.' }
$makeappx = Join-Path $kit.FullName 'x64\makeappx.exe'
$signtool = Join-Path $kit.FullName 'x64\signtool.exe'

$SourceDir = [IO.Path]::GetFullPath($SourceDir)
if (-not (Test-Path -LiteralPath (Join-Path $SourceDir 'Orbyn.exe'))) {
    throw "No build at $SourceDir. Build it first: pwsh -File tools\build_orbyn.ps1"
}
$stage = Join-Path ([IO.Path]::GetTempPath()) ("orbyn-msix-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $stage | Out-Null
try {
    Copy-Item -Path (Join-Path $SourceDir '*') -Destination $stage -Recurse -Force
    $assets = Join-Path $stage 'Assets'
    New-Item -ItemType Directory -Force -Path $assets | Out-Null
    # Plain tiles; replace with the brand artwork when there is some.
    & py -3.12 -c "import sys;from PIL import Image;[Image.new('RGBA',(s,s),(24,24,28,255)).save(f'{sys.argv[1]}/Logo{s}.png') for s in (44,50,150)]" $assets
    if ($LASTEXITCODE -ne 0) { throw 'Could not make the tile images (needs Pillow).' }

    $manifest = @"
<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
  xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
  xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
  xmlns:desktop6="http://schemas.microsoft.com/appx/manifest/desktop/windows10/6"
  IgnorableNamespaces="uap rescap desktop6">
  <Identity Name="Orbyn.Desktop" Publisher="$([Security.SecurityElement]::Escape($Publisher))" Version="$Version" ProcessorArchitecture="x64" />
  <Properties>
    <DisplayName>Orbyn</DisplayName>
    <PublisherDisplayName>$([Security.SecurityElement]::Escape($PublisherDisplayName))</PublisherDisplayName>
    <Logo>Assets\Logo50.png</Logo>
    <desktop6:FileSystemWriteVirtualization>disabled</desktop6:FileSystemWriteVirtualization>
    <desktop6:RegistryWriteVirtualization>disabled</desktop6:RegistryWriteVirtualization>
  </Properties>
  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.19041.0" MaxVersionTested="10.0.26100.0" />
  </Dependencies>
  <Resources><Resource Language="en-us" /></Resources>
  <Applications>
    <Application Id="Orbyn" Executable="Orbyn.exe" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements DisplayName="Orbyn" Description="Local-first Windows desktop guide"
        BackgroundColor="transparent" Square150x150Logo="Assets\Logo150.png" Square44x44Logo="Assets\Logo44.png" />
    </Application>
  </Applications>
  <Capabilities>
    <rescap:Capability Name="runFullTrust" />
    <rescap:Capability Name="unvirtualizedResources" />
  </Capabilities>
</Package>
"@
    Set-Content -LiteralPath (Join-Path $stage 'AppxManifest.xml') -Value $manifest -Encoding utf8
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent ([IO.Path]::GetFullPath($Output))) | Out-Null
    & $makeappx pack /o /d $stage /p $Output
    if ($LASTEXITCODE -ne 0) { throw 'makeappx failed.' }
} finally {
    Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
}

if ($CertPath) {
    $sign = @('sign', '/fd', 'SHA256', '/f', $CertPath, '/tr', $TimestampUrl, '/td', 'SHA256')
    if ($CertPassword) { $sign += @('/p', $CertPassword) }
    & $signtool @sign $Output
    if ($LASTEXITCODE -ne 0) { throw 'signtool failed: the certificate Subject must equal -Publisher.' }
    Write-Host "Built and signed $Output"
} else {
    Write-Host "Built $Output UNSIGNED. Sign it before deploying: signtool sign /fd SHA256 /f <code-signing.pfx> $Output"
}
