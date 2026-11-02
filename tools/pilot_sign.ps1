<#
.SYNOPSIS
Signs files with the Stage 1 pilot certificate in CI, timestamped, and checks each signature chains to
installer\pilot-ca.cer (ADR 0011, decision 2; tools/new_pilot_signing.ps1 makes the certificate).

.DESCRIPTION
Reads the certificate from the environment variables PILOT_SIGNING_PFX (base64) and PILOT_SIGNING_PASSWORD, which
build.yml fills from the repository's Actions secrets. Authenticode, SHA-256, with an RFC 3161 timestamp, so a
signature stays valid after the certificate expires. The runner trusts the pilot CA for the check only; a station
trusts it through its IT (docs/install/pilot-signing.md).

Before signing it prints the signing certificate's expiry and that of installer\pilot-ca.cer, warns in the run's
summary when either ends within RENEW_DAYS, and stops when the signing certificate has expired. -CheckOnly does only
that, and fails within RENEW_DAYS too: the monthly signing-expiry workflow runs it, so GitHub mails the repository's
owner a failed run in time to renew (docs/install/pilot-signing.md, "Renewal").
#>
param([switch]$CheckOnly, [Parameter(ValueFromRemainingArguments)][string[]]$Files)
$ErrorActionPreference = "Stop"
$RenewDays = 60

$kits = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
$signtool = Get-ChildItem $kits -Recurse -Filter signtool.exe | Where-Object { $_.FullName -like "*\x64\*" } |
    Sort-Object FullName -Descending | Select-Object -First 1
if (-not $signtool) { throw "No signtool.exe under $kits" }
if (-not $env:PILOT_SIGNING_PFX) { throw "PILOT_SIGNING_PFX is empty: run tools/new_pilot_signing.ps1 first" }
if (-not $CheckOnly -and -not $Files) { throw "Name the files to sign, or pass -CheckOnly" }

$pfx = Join-Path $env:RUNNER_TEMP "pilot-signing.pfx"
[IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:PILOT_SIGNING_PFX))
try {
    $leaf = [Security.Cryptography.X509Certificates.X509Certificate2]::new($pfx, $env:PILOT_SIGNING_PASSWORD)
    $ca = [Security.Cryptography.X509Certificates.X509Certificate2]::new((Resolve-Path "installer\pilot-ca.cer").Path)
    $soon = @()
    foreach ($cert in @(@("signing certificate", $leaf), @("pilot CA", $ca))) {
        $left = ($cert[1].NotAfter - (Get-Date)).Days
        "The pilot $($cert[0]) $($cert[1].Thumbprint) is valid to $($cert[1].NotAfter.ToString('yyyy-MM-dd')): $left days."
        if ($left -lt $RenewDays) { $soon += "the pilot $($cert[0]) expires in $left days" }
    }
    if ($leaf.NotAfter -lt (Get-Date)) { throw "The pilot signing certificate has expired: run tools/new_pilot_signing.ps1" }
    foreach ($line in $soon) { "::warning::Renew now ($line): docs/install/pilot-signing.md, Renewal" }
    if ($CheckOnly) {
        if ($soon) { throw "Renew now: $($soon -join '; ')" }
        return
    }
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
