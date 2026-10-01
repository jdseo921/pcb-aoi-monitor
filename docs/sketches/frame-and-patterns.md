# Frame and shared patterns

Sketch for stage S02; used by stages S14, S17, S18 and S54. Every later sketch in this folder inherits this one
and repeats only what differs.

## Page and roles

Every page, every role. The frame is the same for Operator, Engineer and Admin; only the sidebar entries differ
(ARCHITECTURE.md §5): Operators see Home, Inspection, Compare and Logs & Export (view only); Engineers add
Training, AI Model Test, Recipe Editor and 3D Profile; Admins add Settings. A hidden entry stays in the list,
greyed, with the tooltip "Requires Engineer" or "Requires Admin"; the service layer refuses the write anyway
(REQ-USR-001).

## Wireframe (1920 × 1080; checked at 1366 × 768, where the sidebar narrows to 200 px)

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ AOI PoC Inspector   Board model [TBOX-A1 ▾] [+ New]          ⟳ Training 42 %   Kim · Engineer [Switch User] │
├────────────┬─────────────────────────────────────────────────────────────────────────────┤
│ Home       │ Page title                                   subtitle, 14 pt, muted         │
│ PRODUCTION │                                                                             │
│  Inspection│  page content: image left, verdict and lists right, controls at the foot   │
│  Compare   │                                                                             │
│ ENGINEERING│                                                                             │
│  Training  │                                                                             │
│  AI Model Test                                                                           │
│  Recipe Editor                                                                           │
│  3D Profile│                                                                             │
│ DATA       │                                                                             │
│  Logs & Export                                                                           │
│ SYSTEM     │                                   [Secondary]  [■ Primary (blue #1E88E5)]   │
│  Settings  │                                                                             │
├────────────┴─────────────────────────────────────────────────────────────────────────────┤
│ status bar: last message with its code · workspace D:\AOI_Workspace · v0.3.0             │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

## Controls and size classes

Size classes used by every sketch: **B** button ≥ 120 × 40 px; **T** operator touch target ≥ 48 px tall and
≥ 120 px wide; **T+** run control 56 px tall, ≥ 240 px wide (proposed); **F** field ≥ 40 px tall; **V** verdict
banner, 40 pt. All text ≥ 14 pt, tables included (v0.1 tables are 12 pt and change). Contrast ≥ 4.5:1: white on
green #43A047 and on red #E53935, dark #1F2A36 on amber #FDD835.

| Control | Label | Key | Size | Notes |
|---|---|---|---|---|
| Board model picker | Board model | Alt+B | T | Chosen once; every page follows it |
| New board model | + New | — | T | Opens an inline sheet, not a dialog; asks for the name and board revision |
| Training indicator | Training 42 % · 3 min left | — | text | Shown on every page while training runs; click opens Training (S40) |
| User and role | Kim · Engineer | — | text | Name and role, never an email |
| Switch user | Switch User | Alt+U | T | Operator picks a name; Engineer and Admin sign in (ADR 0002, own sketch later) |
| Sidebar entry | page name | Alt+1 … Alt+9 | T | 48 px tall so an operator in gloves can hit it |
| Primary button | names the action, e.g. Next Board, Save Recipe | per page | B or T | Exactly one blue #1E88E5 button per page |
| Destructive button | Delete …, Remove …, Reset Demo | — | B | Red #E53935, placed last, never the default focus; confirmation before deleting data |
| Dialog buttons | Close, Copy Details, one action | Esc closes | B | A dialog never opens over a dialog; longer forms are inline sheets |

## Empty state (pattern, REQ-SET-019)

```
┌───────────────────────────────────────────────┐
│   No AI model for TBOX-A1 yet                 │  heading 16 pt
│   Train one from at least 20 OK boards.       │  one sentence, 14 pt
│   [Open Training ›]                           │  one link button (B) to the page that fixes it
└───────────────────────────────────────────────┘
```

Every empty list, image area and card uses this block: what is missing, what to do, one link. An Operator who
cannot open the linked page sees "Ask an Engineer to …" instead of the link.

## Errors (dialog pattern, REQ-SET-019, REQ-LOG-005)

```
┌──────────────────────────────────────────────────────────┐
│ The image could not be loaded                            │  what happened, 16 pt
│ ng_003.png is 62 MP; the limit is 50 MP.                 │  why, 14 pt
│ Resize the image or raise the limit in Settings.         │  what to do
│ Code AOI-INSP-002 · 2026-10-01 13:33:24                  │  code and time, 14 pt
│                       [Copy Details]   [Open Settings]   [Close] │
└──────────────────────────────────────────────────────────┘
```

Three lines, a code and at most one action button; Close has the focus. Copy Details puts code, time, build
version and the log line on the clipboard; the stack trace goes only to the log. Errors in a running inspection go
to the alarm log instead of a dialog, so the line is never blocked. An unhandled error shows this dialog with
code AOI-SET-0xx, is logged with the build version, and the app reopens on the same page (REQ-LOG-005).

| Code | What happened | What to do |
|---|---|---|
| AOI-SET-0xx | Something went wrong and the app must restart | Copy Details for support; the app reopens on this page |
| AOI-SET-0xx | The workspace folder cannot be opened | Check the folder in Settings, or the disk |
| AOI-USR-0xx | This action needs the Engineer (or Admin) role | Switch User |

## Busy, progress and Cancel pattern (REQ-SET-021, REQ-TRN-008)

- Work over 1 s: a busy indicator (spinner and a verb, "Inspecting…") **where the result will appear**: in the
  verdict banner, the table or the image area, never in a dialog. Controls that would start a second job disable.
- Work over 10 s: a progress bar with the step name, "n of N", percent, time left updated at least every 10 s, and
  a Cancel button (B) beside it. Cancel stops within 10 s and leaves what was active before (the active AI model
  stays active, a half-finished import keeps the files already copied and lists the rest).
- Long work continues when the user changes page; the header indicator and the Home card show it.

```
Training TBOX-A1 · Aligning images 12 of 50   [██████░░░░░░░░░░] 24 % · about 4 min left   [Cancel]
```

## Presenter theme (REQ-SET-008)

Switched on in Settings (Admin) and left with "Exit presenter theme" in the header. Light background #FAFAFA,
text ≥ 18 pt, verdict 48 pt, the same verdict colours and shapes, the Settings entry hidden, the sidebar collapsed
to icons with labels. Colours come only from `aoi/ui/theme.py`; every string goes through `self.tr()`.

## Requirements served

REQ-SET-018, REQ-SET-019, REQ-LOG-005, REQ-SET-021, REQ-TRN-008, REQ-SET-008, REQ-SET-004, REQ-SET-005,
REQ-USR-001.

## Rules applied

Role first, verdict first (banner leads on every page that shows a result), one frame, at most 2 clicks from
Home (Home card → page → action), no dialog over a dialog, confirmation only before deleting data, overwriting a
recipe or exporting, every empty state and error says what to do, sizes as above, touch and keyboard for every
operator action, glossary words only, every string translatable.

## Questions for Jay

- Is "AOI PoC Inspector" the name to show in the header for the G1 build, or the product name from the Customers &
  Launch standard?
- Presenter theme text at 18 pt (proposed): is 20 pt better for a projector at 1366 × 768?
- At 1366 × 768 the sidebar narrows to 200 px and the subtitle hides; should it collapse to icons instead?
- Should the header show the station name (Station) beside the user for sites with several stations?
