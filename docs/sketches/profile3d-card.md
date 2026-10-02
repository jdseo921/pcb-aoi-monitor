# 3D Profile: the "Coming in Stage 2" card

Sketch for stage S02; used by stage S54. Frame and patterns: [frame-and-patterns.md](frame-and-patterns.md).

## Page and roles

3D Profile (Engineering). Engineer and Admin, as ARCHITECTURE.md §5 lists it. The sidebar entry stays, with a
"Stage 2" badge after the name, so the Stage 2 layout is reserved and nobody looks for the page elsewhere.
Operators do not see it. In the presenter theme the entry is hidden, so a demo never shows it (C&L Demos rules).

## Wireframe (1920 × 1080; the card is centred and 720 px wide; at 1366 × 768 it is 600 px wide)

```
3D Profile   Stage 2

                     ┌──────────────────────────────────────────────────────────┐
                     │                                                          │
                     │   Coming in Stage 2                                      │  20 pt
                     │                                                          │
                     │   This page needs the 3D camera of Stage 2. It will show │  14 pt
                     │   the height map of a board, the four AOI checks that    │
                     │   need height data (Shield Can Gap, Connector Pin Height,│
                     │   3D Coplanarity, Solder Volume), and Accept / Reject    │
                     │   for each height defect.                                │
                     │                                                          │
                     │   Until then, Height Min / Max and Volume Min / Max can  │
                     │   be entered per ROI in the Recipe Editor; they are      │
                     │   stored now and checked from Stage 2.                   │
                     │                                                          │
                     │   [Open Recipe Editor ›]           [Back to Home]        │
                     │                                                          │
                     └──────────────────────────────────────────────────────────┘
```

Nothing else is drawn: no image area, no table, no Accept or Reject button, no disabled control. v0.1's empty
table and disabled buttons go, because a disabled control still looks usable (REQ-P3D-001). The card uses the
empty-state pattern: what is missing, why, what to do, and a link.

## Controls

| Control | Label | Key | Size | Notes |
|---|---|---|---|---|
| Open Recipe Editor | Open Recipe Editor › | Enter | B | The page's one blue primary; the only action the card offers |
| Back to Home | Back to Home | Esc | B | Secondary |
| Sidebar badge | Stage 2 | — | text 14 pt | Beside the entry name; tooltip "Available with the 3D camera in Stage 2" |

## Empty state

The card is the empty state; it has no other state in Stage 1.

## Errors

None in Stage 1: the page reads nothing and writes nothing. AOI-P3D-001 ("No 3D data for this board") is
reserved for Stage 2.

## Requirements served

REQ-P3D-001 (no control looks usable before Stage 2), REQ-SET-019 (the empty state says what to do and links
there), REQ-SET-018 (one frame, one primary button), REQ-RCP-002 (Height and Volume fields stored now).

## Rules applied

Role first; one blue primary; short paths (Home → sidebar → Recipe Editor stays within 2 clicks); no dead ends;
glossary (ROI, Recipe, the four AOI check names from DCT §4); sizes (card text 14 pt, heading 20 pt, buttons B);
every string through `self.tr()`.

## Decisions (2026-10-02)

- Q9: Keep the entry in the sidebar with a "Stage 2" badge. Reason: The sketch's proposal; #99 built the card, and the badge follows with S54.
- Q10: No date on the card. Reason: The Charter's open question on re-baselining the schedule means a date on screen could become wrong.
- Q11: Hidden in the presenter theme only; Engineers see it at a customer validation. Reason: The card offers no 3D control and claims nothing (REQ-P3D-001), so it cannot mislead.
