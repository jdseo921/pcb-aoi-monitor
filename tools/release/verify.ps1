<#
.SYNOPSIS
Checks a release kit before its installer runs on a station (REQ-SET-027; docs/release/runbook.md). Windows
PowerShell 5.1 or PowerShell 7; no network needed.

.DESCRIPTION
Run it from the kit's folder, or pass -Kit:

    powershell -ExecutionPolicy Bypass -File .\verify.ps1

1. Hashes: every file SHA256SUMS.txt names is there with that SHA-256, and no other file is in the kit.
2. Signature: the installer's Authenticode status is Valid (a -pilot-signed installer, on a station that trusts
   pilot-ca.cer: docs/install/pilot-signing.md). An -unsigned installer is an internal test build and fails, unless
   -AllowUnsigned (CI's pull-request builds). The installed .exe, when there is one, is held to the same.
3. Provenance, when the kit holds provenance.sigstore.json: `gh attestation verify` with the kit's bundle and trusted
   root shows GitHub built the installer from this repository's build.yml. Without the GitHub CLI it says it was not
   checked and goes on.

Each check prints PASS or FAIL; exit 0 when none failed, 1 otherwise.
#>
param(
    [string]$Kit = $PSScriptRoot,
    [string]$Repository = "jdseo921/pcb-aoi-monitor",
    [string]$InstalledExe = (Join-Path $env:ProgramFiles "AOI PoC Inspector\AOI-PoC-Inspector.exe"),
    [switch]$AllowUnsigned
)
$ErrorActionPreference = "Stop"
$failed = 0
function Report([bool]$ok, [string]$what) {
    if ($ok) { "PASS  $what" } else { "FAIL  $what"; $script:failed++ }
}

$sums = Join-Path $Kit "SHA256SUMS.txt"
if (-not (Test-Path $sums)) { "FAIL  no SHA256SUMS.txt in $Kit"; exit 1 }
$listed = @{}
foreach ($line in Get-Content $sums) {
    if ($line -notmatch '^([0-9a-f]{64})  (.+)$') { continue }
    $listed[$Matches[2]] = $true
    $file = Join-Path $Kit $Matches[2]
    $hash = if (Test-Path $file) { (Get-FileHash $file -Algorithm SHA256).Hash.ToLower() } else { "missing" }
    Report ($hash -eq $Matches[1]) "SHA-256 of $($Matches[2])"
}
foreach ($extra in Get-ChildItem $Kit -File | Where-Object { $_.Name -ne "SHA256SUMS.txt" -and -not $listed[$_.Name] }) {
    Report $false "$($extra.Name) is in the kit but not in SHA256SUMS.txt"
}

$setup = @(Get-ChildItem $Kit -File -Filter "*-setup-x64-*.exe")
if ($setup.Count -ne 1) { Report $false "one installer in the kit ($($setup.Count) found)"; exit 1 }
$setup = $setup[0].FullName
$want = if ($setup -like "*-pilot-signed.exe") { "Valid" } elseif ($AllowUnsigned) { "NotSigned" } else { "Valid" }
foreach ($file in @($setup, $InstalledExe)) {
    if ($file -eq $InstalledExe -and -not (Test-Path $file)) { continue }
    $status = (Get-AuthenticodeSignature -LiteralPath $file).Status.ToString()
    Report ($status -eq $want) "Authenticode status of $(Split-Path $file -Leaf): $status (wanted $want)"
}

$bundle = Join-Path $Kit "provenance.sigstore.json"
if (Test-Path $bundle) {
    if (Get-Command gh -ErrorAction SilentlyContinue) {
        $root = Join-Path $Kit "trusted_root.jsonl"
        $extra = if (Test-Path $root) { @("--custom-trusted-root", $root) } else { @() }
        & gh attestation verify $setup -R $Repository --bundle $bundle @extra | Out-Host
        Report ($LASTEXITCODE -eq 0) "provenance: built by $Repository's build.yml"
    } else {
        "NOT CHECKED  provenance: the GitHub CLI (gh) is not installed here; check it on a PC that has it"
    }
}
if ($failed) { "$failed check(s) failed: do not install this kit."; exit 1 }
"All checks passed."
