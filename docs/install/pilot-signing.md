# Trusting the pilot build on a Stage 1 station (for the customer's IT)

AOI PoC Inspector builds for the Stage 1 pilot are signed with a private pilot certificate, not a public one
(ADR 0011, decision 2). Windows trusts them only on a station whose IT has chosen to trust the pilot's certificate
authority (CA). Do this on the pilot stations only, and undo it when the pilot ends.

## What you receive

- `pilot-ca.cer`: the pilot CA's public certificate (from the repository's `installer/` folder). It holds no key.
- The installer, `AOI-PoC-Inspector-<version>-setup-x64-pilot-signed.exe` (signed with the pilot certificate only,
  not a public one; its welcome page says "Pilot build, signed with the … pilot certificate"), and the build's
  `SHA256SUMS.txt`. A file named `…-unsigned.exe` is an internal test build: it must not reach a station.

## 1. Check the installer is ours before trusting anything

On any machine with the GitHub CLI:

```
gh attestation verify AOI-PoC-Inspector-<version>-setup-x64-pilot-signed.exe -R jdseo921/pcb-aoi-monitor
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

## For us: the keys, their renewal, and a lost CA

This part is for the release engineer, not the customer's IT. The pilot has two keys (`tools/new_pilot_signing.ps1`):

| Key | Where it is | Valid | Made |
|---|---|---|---|
| The pilot root CA's private key | The release engineer's Windows account, `Cert:\CurrentUser\My`, **not exportable** | 5 years: to 2031-10-11 (`installer/pilot-ca.cer`, thumbprint `3C45CCCB725E4611954743024C16E30F6E8483EF`) | 2026-10-11 |
| The signing certificate and its key | The repository's Actions secrets `PILOT_SIGNING_PFX` and `PILOT_SIGNING_PASSWORD` only | 13 months from when it was made | With the CA |

Only the two signing steps of `.github/workflows/build.yml` and the one step of `signing-expiry.yml` are given the
secrets; no other step, script or log sees them (REQ-SET-012). `tools/pilot_sign.ps1` writes the PFX to the runner's
temporary folder for the signing only and deletes it after.

### Backing up the CA key

The CA key is made **not exportable**, so it cannot be copied off the machine, and no backup of it exists by design: a
stolen backup would let anyone sign builds the pilot stations trust. What is backed up is the means to replace it:

1. The public certificate, `installer/pilot-ca.cer`, is in the repository.
2. This page's recovery steps below, which make a new CA in about an hour.
3. The release engineer's machine is backed up as usual; restoring it to the **same** machine may bring the key back
   (Windows binds a non-exportable key to the account and machine), and is tried first.

Keeping an exportable copy on offline media instead (an encrypted PFX on two USB drives kept apart, its password in the
company's password manager) was considered and declined: Jay chose no backup, as built, on 2026-11-02 (1.8 pull request).

### Renewal

The signing certificate was made with the CA on 2026-10-11, so it expires about **2027-11-11**; every signing step
prints its exact date, and that of the CA, in the build's log. Renew it by **2027-10-11**: run
`tools/new_pilot_signing.ps1` on the release engineer's machine. It reuses the CA, so the stations need nothing new,
and replaces the two secrets; builds signed before keep their signatures, which are timestamped.

The reminders, three of them so that one failing to arrive is not the end of it:

- The **Pilot signing expiry** workflow runs on the first of each month and fails when the signing certificate or the
  CA ends within 60 days. GitHub mails a failed scheduled run to the person who last changed its `cron` line, and turns
  a scheduled workflow off after 60 days without activity in a public repository; whoever owns releases makes the
  last change to that line, and re-enables the workflow from the Actions tab if GitHub turned it off.
- Each signed build shows a warning in its summary within those 60 days, and stops once the certificate has expired.
- The release engineer keeps a calendar entry for **2027-10-11**, "Renew the AOI pilot signing certificate", with a
  link to this section; each renewal moves it to 30 days before the new certificate's 13th month.

### When the CA is lost or exposed

**Lost** (the machine or the account is gone, nothing leaked): builds signed so far stay trusted on the stations.

1. On the release engineer's new machine, run `tools/new_pilot_signing.ps1 -NewCa`: a new CA, a new signing
   certificate, both secrets replaced, and a new `installer/pilot-ca.cer`.
2. Commit the new `pilot-ca.cer` in a pull request that also updates the table above; the next build of `main` is
   signed by the new CA.
3. Send the customer's IT the new `pilot-ca.cer` with the next release kit, to trust as in step 2 of this page, beside
   the old one. Once every station runs a build signed by the new CA, they remove the old CA as in step 3.

**Exposed** (the CA key or the signing secret may have been copied): treat every build it could sign as untrusted.

1. Tell the customer's IT the same day, and have them remove the old CA from both stores (step 3 of this page). From
   then on the stations refuse the old builds' signatures; the installed app keeps running.
2. Replace the secrets at once: for the signing secret alone, `tools/new_pilot_signing.ps1`; for the CA key,
   `tools/new_pilot_signing.ps1 -NewCa`, then steps 2 and 3 of "Lost" above.
3. Build and send a new release kit signed by the new CA; the stations trust the new `pilot-ca.cer` and install it.
4. Record what happened, when, and which builds were signed meanwhile, in the release note's first section.
