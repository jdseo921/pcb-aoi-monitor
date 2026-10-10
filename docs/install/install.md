# Installing the internal build (unsigned)

**For our own tests only.** The installer CI builds is not signed and is not a release: it must never go to a
customer, onto a customer's station or into a customer demo (Engineering standard, "Signing"; Customers & Launch,
"Demos"). A release is a signed installer built by CI from a tagged commit after two approvals, and it does not exist
yet (REQ-SET-012 stays Partial; the certificate is plan item J6). Because the installer is unsigned, Windows
SmartScreen warns about it and the User Account Control prompt names no publisher. See ADR 0007 for how it is built.

## What you need

The station PC, as Customers & Launch publishes it ("One published PC spec"):

| Part | Supported |
|---|---|
| Windows (64-bit) | Windows 11 IoT Enterprise LTSC 2024 (recommended); Windows 11 Enterprise LTSC 2024; Windows 10 IoT Enterprise LTSC 2021 on existing PCs; Windows 11 Pro or Enterprise yearly versions while Microsoft still patches them. Windows 10 Home and Pro are not supported |
| Graphics | An NVIDIA card with CUDA speeds up training; without one the app trains and inspects on the processor, more slowly |
| Disk | An SSD of 1 TB or more, 2 TB recommended |
| Processor and memory | Not published yet: the reference PC is an open decision in the Charter |

- The installer itself starts on 64-bit Windows 10 from version 21H2 (build 19044) or Windows 11 and refuses older
  Windows; a Windows it starts on is not supported unless the table names it.
- An administrator account: the app installs once per PC, into `C:\Program Files\AOI PoC Inspector`, and then runs
  as a standard user. Python is not needed.
- About 700 MB of free disk for the program, plus the workspace.

## Get the installer from CI

1. On GitHub, open **Actions → Windows build** and pick a green run: the latest on `main`, or the run of a `v*` tag.
   **Run workflow** builds any branch.
2. Under **Artifacts**, download `AOI-PoC-Inspector-<version or tag>-g<commit>-windows-x64-unsigned-installer`
   and unzip it: it holds `AOI-PoC-Inspector-<version>-setup-x64-unsigned.exe`. Artifacts are kept for 30 days.
3. A green run means CI installed this installer silently on a clean Windows runner, ran the installed app's
   `--self-test` (one synthetic board, the expected verdict) and uninstalled it, and the workspace stayed untouched
   (`tools/check_installer.py`). The `…-windows-x64-unsigned` artifact beside it is the same build as a folder, with
   no installer.

## Install

1. Start the setup file. If SmartScreen shows **Windows protected your PC**, choose **More info → Run anyway**. The
   User Account Control prompt shows *Unknown publisher*: choose **Yes**. Any publisher name there means the file is
   not ours; stop.
2. The welcome page says it is an internal test build, not signed. Keep the folder offered, tick **Create a desktop
   shortcut** if you want one (off by default), then **Install** and **Finish**.

An install over an earlier build replaces its program files and keeps the workspace. For a script, from an
administrator prompt: `AOI-PoC-Inspector-<version>-setup-x64-unsigned.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART`,
with `/TASKS=desktopicon` for the desktop shortcut.

## Start the app

| Shortcut (Start menu) | Opens |
|---|---|
| **AOI PoC Inspector** | The station's workspace. The first start of a new workspace opens as `admin`. |
| **AOI PoC Inspector (Demo)** | The demo workspace (`AOI-PoC-Inspector.exe --demo`, REQ-SET-007), loaded first if it is not there yet: the board model DEMO-TBOX-A1 with its AI model, recipe and 10 boards. It is for rehearsing on our own PCs; a customer demo runs on a release build only. |

The optional desktop shortcut opens the station's workspace, like the first one.

## Where the files are

| What | Where | Removed by the uninstaller |
|---|---|---|
| The program: `AOI-PoC-Inspector.exe`, `_internal\`, `THIRD_PARTY_NOTICES.txt`, `sbom.cdx.json`, `BUILD-INFO.txt`, `SHA256SUMS.txt`, `unins000.exe` | `C:\Program Files\AOI PoC Inspector` | Yes |
| Shortcuts | Start menu (all users), and the public desktop if chosen | Yes |
| The workspace: database, images, models, recipes, results, exports and logs | `%USERPROFILE%\AOI_Workspace` for each Windows user, or the folder `AOI_WORKSPACE` names, or the folder chosen in Settings | No |
| `settings.json` | In the default workspace folder above (`%USERPROFILE%\AOI_Workspace\settings.json`) | No |
| The demo workspace | Beside the workspace, its name with `-Demo`: `%USERPROFILE%\AOI_Workspace-Demo` | No |
| Dataset store keys | Windows Credential Manager, generic credentials named `AOI/dataset-store/<UUID>` | No |

The app opens no port and makes no network connection ([ports.md](ports.md)).

## Antivirus, AppLocker and App Control

The app is built to run beside Microsoft Defender with real-time scanning on, with no exclusion: it opens no port
([ports.md](ports.md)), starts no other process, and writes only to its workspace folder, the files a user picks and the
dataset store keys in Windows Credential Manager (and, while the demo is loaded, the demo's folder beside the workspace,
`<workspace>-Demo`). If a site's scanner slows inspection (Inspection shows each board's time; the budget is 1 s), the
one exclusion to consider is the workspace folder, for real-time scanning only. Neither the scan nor the exclusion has
been tried on the reference PC yet. Never exclude the app's folder: it is the part an attacker would change.

Under AppLocker, the default rules allow apps in `C:\Program Files`, where the installer puts the app. Under App
Control for Business, an unsigned build is blocked unless the policy allows it by path or hash; the signed release
(not built yet, plan item J6) is meant to be allowed by its publisher.

## Backup and restore

There is no one-click backup yet. To back up a station:

1. Close the app (a copy taken while it runs can miss the last records).
2. Copy the whole workspace folder (`%USERPROFILE%\AOI_Workspace`, or the folder Settings names) to the backup drive:
   it holds the database, images, AI models, recipes, results, exports and logs. When Settings names another folder,
   copy `settings.json` from `%USERPROFILE%\AOI_Workspace` too.
3. Keep each dataset store's recovery sheet apart from the backup. The stores' keys are not in the folder: a copy
   opens as it is on the same PC and Windows account, and elsewhere only with the sheet printed when the store was
   made (Settings › Dataset stores, New Store…).

To restore, close the app, put the folder back where it was (or anywhere, and point Settings at it), and start the
app. On a new PC or another Windows account, an Admin types each store's recovery sheet into Settings › Dataset
stores › Restore Key…. A restore onto a newer build upgrades the database, keeping a copy of it first ("Going back to
an earlier build", below). Neither step has been tried on the reference PC yet.

## Uninstall

Open **Settings → Apps** (**Installed apps** on Windows 11, **Apps & features** on Windows 10), find **AOI PoC
Inspector <version> (internal, unsigned)** and choose **Uninstall**; or, from an administrator prompt,
`"C:\Program Files\AOI PoC Inspector\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART`.

The uninstaller removes the program files and the shortcuts only, and says so before and after. **The workspace, the
demo workspace, `settings.json` and the keys in Credential Manager stay**, so a later install opens the same records.
To remove them too, back up what you need, then delete `AOI_Workspace` and `AOI_Workspace-Demo` from your user folder
yourself, and the `AOI/dataset-store/…` entries in Credential Manager (without a key, a dataset store's images cannot
be read again).

## Going back to an earlier build

Uninstall, then install the earlier build's installer. Before a newer build changes the database, the app copies it
beside itself (`aoi.sqlite.bak-<old>-to-<new>-<UTC time>`); an earlier build refuses a database a newer one changed
(AOI-SET-002). To use the earlier build on that workspace, close the app and put the copy back as `aoi.sqlite`;
records saved since the copy are then lost. One-step rollback is not built yet.
