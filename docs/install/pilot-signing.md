# Trusting the pilot build on a Stage 1 station (for the customer's IT)

AOI PoC Inspector builds for the Stage 1 pilot are signed with a private pilot certificate, not a public one
(ADR 0011, decision 2). Windows trusts them only on a station whose IT has chosen to trust the pilot's certificate
authority (CA). Do this on the pilot stations only, and undo it when the pilot ends.

## What you receive

- `pilot-ca.cer`: the pilot CA's public certificate (from the repository's `installer/` folder). It holds no key.
- The installer, `AOI-PoC-Inspector-<version>-setup-x64-unsigned.exe` (the file name keeps "unsigned": it has no
  public signature), and the build's `SHA256SUMS.txt`.

## 1. Check the installer is ours before trusting anything

On any machine with the GitHub CLI:

```
gh attestation verify AOI-PoC-Inspector-<version>-setup-x64-unsigned.exe -R jdseo921/pcb-aoi-monitor
```

It must report a verified build of `jdseo921/pcb-aoi-monitor` from `.github/workflows/build.yml`. Without the CLI,
compare `Get-FileHash <installer> -Algorithm SHA256` with the hash we send you by a second channel.

## 2. Trust the pilot CA on the pilot stations

Either by Group Policy, for several stations: Computer Configuration → Policies → Windows Settings → Security Settings
→ Public Key Policies → import `pilot-ca.cer` into **Trusted Root Certification Authorities**; and, so Windows does not
ask about the publisher, into **Trusted Publishers** too.

Or on one station, as an administrator in PowerShell:

```
Import-Certificate -FilePath .\pilot-ca.cer -CertStoreLocation Cert:\LocalMachine\Root
Import-Certificate -FilePath .\pilot-ca.cer -CertStoreLocation Cert:\LocalMachine\TrustedPublisher
```

Then `Get-AuthenticodeSignature <installer>` reports `Valid`, signed by "AOI PoC Inspector pilot", timestamped.

## 3. When the pilot ends

Remove the certificate from both stores (Group Policy, or `certlm.msc` → find "AOI PoC Inspector pilot root CA" →
Delete). Builds after the pilot carry a public signature and need nothing from this page.

## Limits

The pilot CA can only vouch for builds it signed. Its private key never leaves our release engineer's machine; the
signing certificate is held in our CI's encrypted secrets and renewed yearly. If either is ever exposed, we tell you
and you remove the CA as in step 3.
