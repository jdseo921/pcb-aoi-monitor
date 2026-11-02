<#
.SYNOPSIS
Checks a release kit before its installer runs on a station (REQ-SET-027; docs/release/runbook.md). Windows
PowerShell 5.1 or PowerShell 7; no network needed.

.DESCRIPTION
Run it from the kit's folder, or pass -Kit:

    powershell -ExecutionPolicy Bypass -File .\verify.ps1

1. Hashes: every file SHA256SUMS.txt names is there with that SHA-256, and no other file is in the kit.
2. Signature: the installer's Authenticode status is Valid and its chain ends at the pilot CA whose thumbprint is
   written below (-CaThumbprint), as does the kit's pilot-ca.cer: a kit whose CA was swapped fails even when its
   hashes agree. Check the thumbprint this prints against the one we send by a second channel. An -unsigned installer
   is an internal test build and fails, unless -AllowUnsigned (CI's builds before the certificate exists).
   -InstalledExe, after the install, holds the installed .exe to the same.
3. Provenance: a -pilot-signed kit must hold provenance.sigstore.jsonl, and `gh attestation verify` with the kit's
   bundle and trusted root must show the installer was built by this repository's build.yml. Where the GitHub CLI is
   not installed, as on a station, pass -SkipProvenance after checking the same kit on a PC that has it.

Each check prints PASS or FAIL; exit 0 when none failed, 1 otherwise.
#>
param(
    [string]$Kit = $PSScriptRoot,
    [string]$Repository = "jdseo921/pcb-aoi-monitor",
    [string]$InstalledExe = "",
    [string]$CaThumbprint = "3C45CCCB725E4611954743024C16E30F6E8483EF",  # installer\pilot-ca.cer, to 2031-10-11
    [switch]$AllowUnsigned,
    [switch]$SkipProvenance
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
$pilot = $setup -like "*-pilot-signed.exe"
$want = if ($pilot -or -not $AllowUnsigned) { "Valid" } else { "NotSigned" }
$ca = Join-Path $Kit "pilot-ca.cer"
$kitCa = if (Test-Path $ca) { (New-Object Security.Cryptography.X509Certificates.X509Certificate2 $ca).Thumbprint }
Report ($kitCa -eq $CaThumbprint) "pilot-ca.cer is the pilot CA $CaThumbprint (found $kitCa)"
foreach ($file in @($setup, $InstalledExe)) {
    if (-not $file) { continue }
    $sig = Get-AuthenticodeSignature -LiteralPath $file
    $status = $sig.Status.ToString()
    Report ($status -eq $want) "Authenticode status of $(Split-Path $file -Leaf): $status (wanted $want)"
    if ($status -eq "Valid") {
        $chain = New-Object Security.Cryptography.X509Certificates.X509Chain
        [void]$chain.Build($sig.SignerCertificate)
        $root = $chain.ChainElements[$chain.ChainElements.Count - 1].Certificate.Thumbprint
        Report ($root -eq $CaThumbprint) "$(Split-Path $file -Leaf) is signed under the pilot CA (root $root)"
    }
}

$bundle = Join-Path $Kit "provenance.sigstore.jsonl"
$workflow = "$Repository/.github/workflows/build.yml"
if ($SkipProvenance) {
    "NOT CHECKED  provenance (-SkipProvenance): check this kit with verify.ps1 on a PC with the GitHub CLI"
} elseif (-not (Test-Path $bundle)) {
    Report (-not $pilot) "provenance: a pilot-signed kit holds provenance.sigstore.jsonl"
} elseif (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Report $false "provenance: the GitHub CLI (gh) is not installed here; use a PC that has it, or -SkipProvenance"
} else {
    $root = Join-Path $Kit "trusted_root.jsonl"
    $extra = if (Test-Path $root) { @("--custom-trusted-root", $root) } else { @() }
    & gh attestation verify $setup -R $Repository --signer-workflow $workflow --bundle $bundle @extra | Out-Host
    Report ($LASTEXITCODE -eq 0) "provenance: built by $workflow"
}
if ($failed) { "$failed check(s) failed: do not install this kit."; exit 1 }
"All checks passed."
