<#
.SYNOPSIS
Says which build of AOI PoC Inspector this station runs (REQ-SET-027; docs/release/runbook.md): for the station's
record, before and after an upgrade. Windows PowerShell 5.1 or PowerShell 7; reads only.

.DESCRIPTION
    powershell -ExecutionPolicy Bypass -File .\inventory.ps1 [-Json]

From the installer's uninstall entry: the name Installed apps shows (with "pilot, signed" or "internal, unsigned"),
the version, the folder and the install date; from that folder: BUILD-INFO.txt's first line (version, build number,
commit), the .exe's ProductVersion and its Authenticode status. Exit 0 when installed, 1 when not.
#>
param(
    [string]$Uninstall = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
    [switch]$Json
)
$ErrorActionPreference = "Stop"
$entry = Join-Path $Uninstall "{7D122A0A-06CC-4538-A441-BD5D560E2255}_is1"  # installer\aoi.iss's AppId
if (-not (Test-Path $entry)) { "AOI PoC Inspector is not installed on $env:COMPUTERNAME."; exit 1 }
$app = Get-ItemProperty $entry
$folder = $app.InstallLocation
$info = Join-Path $folder "BUILD-INFO.txt"
$exe = Join-Path $folder "AOI-PoC-Inspector.exe"
$found = [ordered]@{
    Computer = $env:COMPUTERNAME
    Name = $app.DisplayName
    Version = $app.DisplayVersion
    Installed = $app.InstallDate
    Folder = $folder
    Build = if (Test-Path $info) { (Get-Content $info -TotalCount 1) } else { $null }
    ExeVersion = if (Test-Path $exe) { (Get-Item $exe).VersionInfo.ProductVersion } else { $null }
    Signature = if (Test-Path $exe) { (Get-AuthenticodeSignature -LiteralPath $exe).Status.ToString() } else { $null }
}
if ($Json) { [pscustomobject]$found | ConvertTo-Json } else { [pscustomobject]$found | Format-List | Out-String }
