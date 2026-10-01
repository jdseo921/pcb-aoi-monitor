# Settings: workspace, device, limits, demo and presenter theme

Sketch for stage S02; used by stages S53 and S54. Frame and patterns:
[frame-and-patterns.md](frame-and-patterns.md). Users and roles, sign-in and the first-run wizard get their own
sketches (ADR 0002); the Users group is only placed here.

## Page and roles

Settings (System). Admin only. The presenter theme, once on, hides this page; the header's "Exit presenter
theme" brings it back for an Admin.

## Wireframe (1920 × 1080; two columns; at 1366 × 768 one column, groups stacked)

```
Settings   v0.3.0 · schema 3 · station AOI-01
┌ Workspace ───────────────────────────────────┐ ┌ Demo ──────────────────────────────────────────────┐
│ Folder  [D:\AOI_Workspace          ] [Browse…]│ │ Demo workspace: not loaded                          │
│ 2.1 GB used · 41 % of disk · paths relative   │ │ [Load Demo Workspace]  loads TBOX-A1 with its       │
│ [Move Workspace…] (copies, then switches)     │ │   AI model, recipe and 12 test boards; production   │
├ AI ───────────────────────────────────────────┤ │   data is not touched                                │
│ Device (● Auto: CUDA found, GeForce RTX 3060) │ │ [Reset Demo] red · under 10 s · confirmation         │
│        ( CPU) ( CUDA)                         │ │ Scripted run pace  1 s [───●──────] 10 s  = 3 s     │
│ Input size [256 ▾]  Epochs [60]               │ │ [Play Scripted Run ›] opens Inspection on the demo   │
├ Input limits ─────────────────────────────────┤ ├ Presenter theme ────────────────────────────────────┤
│ Max image [50] MP   Max file [200] MB         │ │ [▢ Presenter theme] light, text 18 pt, Admin pages  │
├ Logs ─────────────────────────────────────────┤ │   hidden; leave it from the header                   │
│ Retention [30] days   Language [English ▾]    │ ├ Users & roles (own sketch, ADR 0002) ───────────────┤
│                                               │ │ Name │ Role │ Status                               │
│ [■ Save Settings]  blue primary               │ │ [Add User…] [Disable] [Reset Password…]             │
└───────────────────────────────────────────────┘ └─────────────────────────────────────────────────────┘
```

The demo workspace is a second workspace folder beside production (`<workspace>\demo`), loaded in one click and
reset in under 10 s by copying the bundled files back; production hashes are unchanged (REQ-SET-007). The
scripted run plays mixed OK and NG boards at the set pace from the demo workspace (REQ-SET-009); the same run at
3 s per board for 8 h is the stability test (REQ-INSP-011).

## Controls

| Control | Label | Key | Size | Notes |
|---|---|---|---|---|
| Workspace folder | Folder, Browse… | — | F, B | Shown with disk use; stored paths are relative to it (REQ-SET-001) |
| Move workspace | Move Workspace… | — | B | Inline sheet: copies with progress, time left and Cancel, then switches; the old folder is left in place |
| AI device | Auto / CPU / CUDA | — | T (radio) | Auto shows what it found; CUDA without a GPU is refused (REQ-SET-002) |
| Input size, Epochs | as named | — | F | Training defaults |
| Input limits | Max image MP, Max file MB | — | F | Used by Inspection, Training and AI Model Test refusals (REQ-INSP-001) |
| Retention | Retention days | — | F | Archive threshold for Logs & Export |
| Language | Language | — | F | English; Korean at 1.0 (REQ-SET-006) |
| Save Settings | Save Settings | Ctrl+S | B | The page's one blue primary; a changed workspace takes effect at once, no restart |
| Load demo workspace | Load Demo Workspace | — | B | One click; busy indicator; the header's board model switches to the demo board model with a "Demo" badge |
| Reset demo | Reset Demo | — | B | Red; deletes demo results and restores the bundle; confirmation names what is removed; finishes within 10 s |
| Scripted run pace | Scripted run pace | ← → | slider, 48 px knob | 1 to 10 s per board, default 3 s |
| Play scripted run | Play Scripted Run › | — | B | Opens Inspection with the demo queue and Start pressed |
| Presenter theme | Presenter theme | — | T (check box) | Light theme, text ≥ 18 pt, verdict 48 pt, Admin pages hidden (REQ-SET-008) |
| Exit presenter theme | Exit presenter theme | — | T (header) | Admin only |

## Empty state

Demo group before the first load: "Demo workspace not loaded. Load Demo Workspace to show TBOX-A1 with its AI
model, recipe and 12 test boards." with the button. No GPU: the Auto line reads "Auto: no GPU found, using CPU".

## Errors

| Code | What happened | Why | What to do |
|---|---|---|---|
| AOI-SET-001 | The workspace folder cannot be used | Not writable, or not found | Pick another folder; the old one stays in use |
| AOI-SET-002 | CUDA cannot be used | No NVIDIA GPU or driver found | CPU is used; pick Auto or CPU |
| AOI-SET-003 | The demo bundle cannot be loaded | Missing, or its hash does not match | Reinstall the app; nothing in production was changed |
| AOI-SET-004 | The demo reset did not finish | It took longer than 10 s, or a file is locked | Close Inspection and try again |
| AOI-SET-005 | Settings were reset to defaults | settings.json could not be read | Check the values and save |
| AOI-SET-006 | The move was stopped | Target folder is inside the current workspace, or the disk is full | Pick another target |
| AOI-SET-007 | A limit was not saved | Outside 1 to 200 MP or 1 to 2,000 MB (proposed) | Enter a value in range |

## Requirements served

REQ-SET-001, -002, -007, -008, -009, REQ-INSP-001, REQ-INSP-011, REQ-SET-019, REQ-SET-021, REQ-SET-018.

## Rules applied

Role first (Admin only); one blue primary (Save Settings); destructive Reset Demo red, last, never default
focus, with confirmation; progress with Cancel for the move; no dialog over a dialog; no dead ends; glossary
(Workspace, Station, Board model, AI model, Recipe); sizes; every string through `self.tr()`.

## Questions for Jay

- Presenter theme for an Engineer presenting without an Admin: a header switch for Engineers too, or Admin only
  (proposed)?
- Demo workspace location: beside production inside the workspace (proposed) or a separate folder chosen at
  install?
- Default limits 50 MP and 200 MB are proposed; do the customer's cameras ever exceed them?
- Should changing the language take effect at once (proposed) or at the next start?
