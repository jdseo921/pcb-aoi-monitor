# Input-file naming contract (REQ-INSP-020, ADR 0024 D26)

How a board image must be named and written so the station inspects it from its watched input folder
(`Settings.input_folder`) without an operator's action. No factory has agreed a contract yet (Jay, 2026-11-06), so the
station uses the capture name of the [Engineering standard](../standards/engineering.md) ("Capture", MUST) and the
imaging station that feeds the folder is set up to it. It is checked by `aoi/core/folder_watch.py` (`NAME`, `parse`); a
change to it is a change to that code and this page together, recorded in ADR 0024.

## The name

```
<board model>_<revision>_<serial>_<view>_<UTC time>.png
TBOX-A1_R3_0001_Top_20261106T103000Z.png
```

| Field | Rule | Example |
|---|---|---|
| Board model | The board model's name exactly as the station has it, `_` and all | `TBOX-A1` |
| Revision | The PCB revision: 1 to 16 letters, digits or `-` | `R3` |
| Serial | The board's serial, its board ID: 1 to 64 letters, digits or `-` | `0001` |
| View | `Top`, `Side` or `Bottom` (any case) | `Top` |
| UTC time | When the image was taken, in UTC: `YYYYMMDDTHHMMSSZ`, a real date and time | `20261106T103000Z` |
| Extension | `.png`, or `.jpg` or `.jpeg` for a customer's JPEG at quality 95 or more, in any case | `.png` |

Only the board model may hold `_`: the four fields after it never do, so the name is read from its end. The serial is
the board ID the result files give (`board_id` in `docs/schemas/result-file.schema.json`); the view is the one the
board is judged and recorded in, whatever the Inspection page's View box shows. The record names the file where it now
is, in `done/`, and keeps the SHA-256 of its bytes.

## How to write it

1. Write the file under a name that does not end in `.png`, `.jpg` or `.jpeg`, such as
   `TBOX-A1_R3_0001_Top_20261106T103000Z.png.part`, in the input folder itself (a move across folders or drives is a
   copy, not a rename).
2. Close it, then rename it to its name. The rename is what the station waits for.

A file written in place is taken once two looks of the folder, 0.25 s apart (`LOOK_S`), found the same size and
modification time and it has held them for 0.5 s (`SETTLE_S`), counted from the look that saw its last change. A
writer that pauses longer than that mid-file hands over half an image, which is then
usually refused with AOI-INSP-022. Files whose names start with `.` or `~`, and files with any other extension, are never touched.

## What the station does with it

| Outcome | Where the file goes | Alarm |
|---|---|---|
| Inspected and its record saved | `done/` | NG boards: AOI-INSP-003, as any board |
| Its name breaks the contract | `failed/` | AOI-INSP-020, with the reason |
| A file of its name is in `done/`, or a record already judged the same image (by SHA-256) under any name | `failed/` | AOI-INSP-021 |
| It cannot be read as an image, or is over the station's image limits | `failed/` | AOI-INSP-022, with the reader's reason |
| It names another board model than the line runs | stays in the input folder; the line pauses | AOI-INSP-024 |
| Its record could not be saved, or the inspection failed | back to the input folder; the line pauses and takes it again on Start | the save's or the inspection's own code |
| The input folder cannot be read (a share gone) | stays where it is | AOI-INSP-023, once until the folder answers |

- `working/`, `done/` and `failed/` are made inside the input folder; the input folder itself is never made, so a
  share that is not connected is never replaced by a folder on the station's own disk.
- Files are taken oldest first by modification time, then by name, one at a time.
- A name taken in `failed/` gets a short random tail (`TBOX-A1_R3_0001_Top_20261106T103000Z~1a2b3c4d.png`): no move
  replaces a file.
- Nothing is deleted: `done/` and `failed/` keep the originals until an Admin removes them (ADR 0024 D20). They are
  as large as the images (4.7 MB for a 5 MP board, measured); size the share for them.
- "Never inspected twice" holds by the name in `done/` and by the SHA-256 every record of a board the line took keeps
  (migration 0031), for every input folder the station has watched. One station per input folder.
- A station that stops during a board leaves its file in `working/`; the next look puts it back in the input folder,
  or moves it to `done/` when its record was saved before the stop.

## Not covered yet

- A lot or panel ID, a line or station ID, and more than one image per view: none is in the name. The standard's
  JSON record of the session set-up beside the images is not read.
- The revision is checked for its form only; the station does not yet keep a board model's revisions.
- Images from a camera the station drives (Stage 2) do not use this folder.
