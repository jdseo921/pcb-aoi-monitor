<#
.SYNOPSIS
Signs files with the Stage 1 pilot certificate in CI, timestamped, and checks each signature chains to
installer\pilot-ca.cer (ADR 0011, decision 2; tools/new_pilot_signing.ps1 makes the certificate).

.DESCRIPTION
Reads the certificate from the environment variables PILOT_SIGNING_PFX (base64) and PILOT_SIGNING_PASSWORD, which
build.yml fills from the repository's Actions secrets. Authenticode, SHA-256, with an RFC 3161 timestamp, so a
signature stays valid after the certificate expires. The runner trusts the pilot CA for the check only; a station
trusts it through its IT (docs/install/pilot-signing.md).
#>
param([Parameter(Mandatory, ValueFromRemainingArguments)][string[]]$Files)
$ErrorActionPreference = "Stop"

$kits = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
$signtool = Get-ChildItem $kits -Recurse -Filter signtool.exe | Where-Object { $_.FullName -like "*\x64\*" } |
    Sort-Object FullName -Descending | Select-Object -First 1
if (-not $signtool) { throw "No signtool.exe under $kits" }
if (-not $env:PILOT_SIGNING_PFX) { throw "PILOT_SIGNING_PFX is empty: run tools/new_pilot_signing.ps1 first" }

$pfx = Join-Path $env:RUNNER_TEMP "pilot-signing.pfx"
[IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:PILOT_SIGNING_PFX))
try {
    foreach ($file in $Files) {
        if (-not (Test-Path $file)) { throw "No file to sign: $file" }
        & $signtool.FullName sign /fd SHA256 /f $pfx /p $env:PILOT_SIGNING_PASSWORD `
            /tr http://timestamp.digicert.com /td SHA256 /d "AOI PoC Inspector (pilot)" $file
        if ($LASTEXITCODE -ne 0) { throw "signtool sign failed on $file" }
    }
} finally {
    Remove-Item $pfx -Force -ErrorAction SilentlyContinue
}

Import-Certificate -FilePath "installer\pilot-ca.cer" -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
foreach ($file in $Files) {
    & $signtool.FullName verify /pa /tw $file
    if ($LASTEXITCODE -ne 0) { throw "The signature of $file does not chain to installer\pilot-ca.cer" }
}
