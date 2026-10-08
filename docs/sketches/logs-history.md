# Logs & Export: history, filters, export, archive and delete

Sketch for stage S02; used by stage S51. Frame and patterns: [frame-and-patterns.md](frame-and-patterns.md).

## Page and roles

Logs & Export (Data). All roles view; Engineer and Admin export and archive; only an Admin deletes
(ARCHITECTURE.md §5, REQ-LOG-003). Operators see the table, the filters and the preview; the export, archive and
delete buttons are not shown to them.

## Wireframe (1920 × 1080; at 1366 × 768 the preview collapses to a button)

```
Logs & Export
From [2026-09-24] To [2026-10-01]  Board model [All ▾]  Operator [All ▾]  Result [All ▾]  [▢ Include archived]  [■ Apply Filter]
┌──────────────────┬───────────┬────────┬────────┬─────────┬────────┬──────┬──────────┬──────────────┐ ┌──────────────┐
│ Time             │Board model│AI model│ Result │ Defects │Operator│ View │Recipe rev│ Image        │ │ overlay of   │
│ 2026-10-01 13:33 │ TBOX-A1   │ v1.2   │ ✗ NG   │ 1       │ park   │ Top  │ 4        │ ng_003.png   │ │ the selected │
│ 2026-10-01 13:32 │ TBOX-A1   │ v1.2   │ ▲ WARN │ 0       │ park   │ Top  │ 4        │ ok_118.png   │ │ row, stored  │
│ 2026-10-01 13:32 │ TBOX-A1   │ v1.2   │ ✓ OK   │ 0       │ park   │ Top  │ 4        │ ok_117.png   │ │ evidence     │
│ … 128 rows, every column sorts (REQ-LOG-001) …                                                       │ │[Open in Compare ›]│
└──────────────────┴───────────┴────────┴────────┴─────────┴────────┴──────┴──────────┴──────────────┘ └──────────────┘
128 records · 3 NG · 1 WARN · yield 97.7 % · archived records: 2,310 (older than 30 days)
[Export CSV…] [Export Overlays…]            [Archive Now]                    [Delete Records…] red, Admin
```

NG rows carry the red cross and WARN rows the amber triangle in the Result cell; whole rows are not coloured, so
the table stays readable at 14 pt. Filters combine; 100,000 records filter within 1 s (REQ-LOG-001). Archived
records stay searchable with "Include archived" (REQ-LOG-003).

## Controls

| Control | Label | Key | Size | Notes |
|---|---|---|---|---|
| Date range | From, To | — | F | Calendar pop-up; defaults to the last 7 days |
| Board model | Board model | — | F | All, or one |
| Operator | Operator | — | F | All, or one name |
| Result | Result | — | F | All, OK, NG, WARN |
| Include archived | Include archived | — | T (check box, 48 px row) | |
| Apply filter | Apply Filter | Enter | B | The page's one blue primary; busy indicator in the table over 1 s |
| Table | Time, Board model, AI model, Result, Defects, Operator, View, Recipe rev, Image | ↑ ↓, click header sorts | rows 48 px for Operators, 14 pt | Selecting a row shows its overlay within 300 ms |
| Open in Compare | Open in Compare › | Enter | T | Stored result with failing checks highlighted (REQ-INSP-009) |
| Export CSV | Export CSV… | — | B | Confirmation: "Export 128 records as CSV?"; UTF-8 with BOM; carries verdict, regions, metrics, thresholds, AI model version, recipe revision and view (REQ-INSP-012, REQ-INSP-010); audit entry with user, time, filter and count (REQ-LOG-002) |
| Export overlays | Export Overlays… | — | B | Confirmation names the count; same audit entry |
| Archive now | Archive Now | — | B | Archives records older than the retention days (Settings); nothing is deleted, so no confirmation; status bar reports the count |
| Delete records | Delete Records… | — | B | Red, Admin only, last in the row, never the default focus; confirmation names the count and asks for a reason; audit entry; archived evidence is deleted with the records |

## Empty state

Table with no match: "No inspections match these filters. Widen the dates or set a filter to All." with
[Reset Filters]. Workspace without inspections: "No inspections yet. Run boards on Inspection." with
[Open Inspection ›]. Preview with no row: "Select a row to see its overlay."

## Errors

| Code | What happened | Why | What to do |
|---|---|---|---|
| AOI-LOG-001 | The export failed | Disk full or folder not writable | Pick another folder; nothing was exported |
| AOI-LOG-002 | The filter took too long | More than 1 s at this record count | Narrow the dates; the last result stays shown |
| AOI-LOG-003 | The overlay is missing | The evidence file was removed from the workspace | The row shows "evidence missing"; the result data stays |
| AOI-LOG-004 | Deletion refused | Role is not Admin | Switch User |
| AOI-LOG-005 | Archiving failed | The database is locked or the disk is full | Try again; details in the log |

## Requirements served

REQ-LOG-001, -002, -003, -004 (audit entries), REQ-INSP-009, -010, -012, REQ-USR-001, REQ-SET-019, REQ-SET-021.

## Rules applied

Role first (Operators view only); verdict first (Result cell leads with colour, word and shape; one click to
Compare); one blue primary (Apply Filter); destructive Delete Records red, Admin only, never default focus;
confirmation only before exporting and deleting; no dead ends; glossary (Board model, AI model, Recipe, Verdict
OK/NG/WARN, Operator); sizes; every string through `self.tr()`.

## Questions for Jay

- Delete scope: the filtered records (proposed) or selected rows only?
- Should an Operator see other operators' records (proposed, since the filter exists), or only their own?
- Retention days: 30 as in GUI §4.4, changeable by an Admin in Settings (proposed)?
- Should Archive Now be a button at all, given it runs at start-up?
