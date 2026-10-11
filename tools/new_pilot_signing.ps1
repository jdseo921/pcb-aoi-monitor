#Requires -Version 7
<#
.SYNOPSIS
Creates the Stage 1 pilot's private code-signing CA and the certificate CI signs builds with (ADR 0011, decision 2).

.DESCRIPTION
Run once, by the release engineer, on their own Windows machine, from the repository's root, signed in to the GitHub CLI
(`gh auth status`). It:

1. creates the pilot root CA in the current user's certificate store, its private key not exportable, so it never
   leaves this machine;
2. issues a code-signing certificate from that CA, valid 13 months, with a random password, and stores it, base64,
   as the repository's Actions secrets PILOT_SIGNING_PFX and PILOT_SIGNING_PASSWORD; nothing is written to disk but
   in a temporary file that is deleted;
3. writes the CA's public certificate to installer/pilot-ca.cer, which the pilot station's IT trusts
   (docs/install/pilot-signing.md) and which is committed.

Run it again to renew the signing certificate before it expires: the same CA is reused, so the stations need nothing
new. -NewCa makes a new CA as well, after which every station must trust the new installer/pilot-ca.cer.

The pilot CA is private trust for supervised pilot stations only. It is not a public code-signing certificate and
must never be used to sign a build that goes to anyone else.
#>
[CmdletBinding()]
param(
    [string]$Repository = "jdseo921/pcb-aoi-monitor",
    [string]$Publisher = "AOI PoC Inspector pilot",
    [switch]$NewCa
)
$ErrorActionPreference = "Stop"

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw "The GitHub CLI (gh) is needed: winget install GitHub.cli" }
gh auth status 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Sign in to the GitHub CLI first: gh auth login" }
if (-not (Test-Path "installer")) { throw "Run this from the repository's root folder." }

$caSubject = "CN=$Publisher root CA"
$ca = Get-ChildItem Cert:\CurrentUser\My | Where-Object { $_.Subject -eq $caSubject -and $_.NotAfter -gt (Get-Date) } |
    Sort-Object NotAfter -Descending | Select-Object -First 1
if ($NewCa -or -not $ca) {
    $ca = New-SelfSignedCertificate -Subject $caSubject -CertStoreLocation Cert:\CurrentUser\My `
        -KeyUsage CertSign, CRLSign, DigitalSignature -KeyExportPolicy NonExportable -KeyAlgorithm RSA -KeyLength 3072 `
        -HashAlgorithm SHA256 -NotAfter (Get-Date).AddYears(5) `
        -TextExtension @("2.5.29.19={critical}{text}ca=true&pathlength=0")
    Write-Host "Created the pilot root CA $($ca.Thumbprint), valid to $($ca.NotAfter.ToString('yyyy-MM-dd'))."
} else {
    Write-Host "Reusing the pilot root CA $($ca.Thumbprint), valid to $($ca.NotAfter.ToString('yyyy-MM-dd'))."
}
Export-Certificate -Cert $ca -FilePath "installer\pilot-ca.cer" -Type CERT | Out-Null

$signing = New-SelfSignedCertificate -Subject "CN=$Publisher" -Signer $ca -Type CodeSigningCert `
    -CertStoreLocation Cert:\CurrentUser\My -KeyExportPolicy Exportable -KeyAlgorithm RSA -KeyLength 3072 `
    -HashAlgorithm SHA256 -NotAfter (Get-Date).AddMonths(13)
$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
$password = [Convert]::ToBase64String($bytes)
$secure = ConvertTo-SecureString $password -AsPlainText -Force
$pfx = Join-Path ([IO.Path]::GetTempPath()) ("pilot-signing-" + [guid]::NewGuid() + ".pfx")
try {
    Export-PfxCertificate -Cert $signing -FilePath $pfx -Password $secure -CryptoAlgorithmOption AES256_SHA256 | Out-Null
    [Convert]::ToBase64String([IO.File]::ReadAllBytes($pfx)) | gh secret set PILOT_SIGNING_PFX -R $Repository
    if ($LASTEXITCODE -ne 0) { throw "gh secret set PILOT_SIGNING_PFX failed" }
    $password | gh secret set PILOT_SIGNING_PASSWORD -R $Repository
    if ($LASTEXITCODE -ne 0) { throw "gh secret set PILOT_SIGNING_PASSWORD failed" }
} finally {
    if (Test-Path $pfx) { Remove-Item $pfx -Force }
    Remove-Item "Cert:\CurrentUser\My\$($signing.Thumbprint)" -DeleteKey  # the key now lives only in the secret
}
Write-Host "Stored the signing certificate $($signing.Thumbprint), valid to $($signing.NotAfter.ToString('yyyy-MM-dd')),"
Write-Host "as the Actions secrets of $Repository. Commit installer\pilot-ca.cer; the next build of main or a tag is signed."
