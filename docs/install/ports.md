# Ports and network use

The installation guide lists every port, protocol and direction the app uses (Engineering standard, "Offline and
least privilege", MUST). For this build the list is empty.

| Port | Protocol | Direction | Used by | On by default |
|---|---|---|---|---|
| none | none | none | none | n/a |

**The app opens no port and makes no connection, inbound or outbound, by default** (REQ-SET-003). It reads and writes
its workspace folder and the files and folders a user picks, and every function works with the network unplugged. A
station's firewall can block all inbound and outbound traffic for the app; it needs no rule.

## Network features

None in Stage 1: the app has no updates, MES or ERP link, telemetry or remote help. MES and ERP (Stage 4, through the
`aoi/hal` MES interface) and updates arrive in later stages, each off until an Admin switches it on in Settings; the
change that adds one lists it here with its port, protocol, direction and switch. Telemetry, when added, is off by
default and anonymous.

## How it is checked

- On every pull request, `tests/test_offline.py` starts the app, runs a scripted session (import samples, train an AI
  model, inspect boards, Compare, AI Model Test, export) and fails on any IPv4 or IPv6 connection, bind, listen, send
  or name lookup, and on Linux on any TCP or UDP socket the app holds after a step.
- On a station, `tools/check_offline.ps1` starts the app and, every 30 s for an hour, lists the TCP connections and UDP
  endpoints of its processes while the app is used as usual; it writes one CSV row per sample, prints PASS when every
  sample shows 0 listening ports and 0 connections, else FAIL with the samples that did not, and leaves the app
  running. The 1-hour run on the reference PC is recorded with stage S55.

```powershell
powershell -ExecutionPolicy Bypass -File tools\check_offline.ps1 -Out offline.csv `
    -Exe .\AOI-PoC-Inspector\AOI-PoC-Inspector.exe
powershell -ExecutionPolicy Bypass -File tools\check_offline.ps1 -Out offline.csv -Exe "python main.py"  # from source
```
