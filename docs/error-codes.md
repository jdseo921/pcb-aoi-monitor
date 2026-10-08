# Error codes

Generated from `aoi/errors.py` by `python -m aoi.errors`; do not edit. Every error a user can see carries one
of these codes with what happened and what to do (REQ-LOG-004, REQ-SET-019). Areas follow the requirement
register; `{braces}` are filled in when the error is raised.

| Code | Title | What happened | What to do |
|---|---|---|---|
| AOI-INSP-001 | Image cannot be read | The file {path} could not be opened as an image. | Check that the file exists and is a PNG, JPG, BMP or TIFF image. |
| AOI-INSP-002 | Image cannot be written | The image {path} could not be encoded for writing. | Check the file name's extension (.png or .jpg) and try again. |
| AOI-SET-001 | Workspace from version 0.1 | This workspace was created by AOI PoC Inspector 0.1 and cannot be upgraded. | Choose a new workspace folder in Settings. |
| AOI-SET-002 | Workspace newer than the app | The workspace database was written by a newer build of the app: it records migration {migration}, which this build does not have. | Update the app, or choose another workspace folder in Settings. |
| AOI-SET-003 | Migration file changed | Migration {file} differs from the one recorded in the workspace database; a shipped migration is never edited. | Reinstall the app to restore the file, or choose another workspace folder in Settings. |
| AOI-SET-004 | Migration failed | Migration {file} failed and was rolled back: {error}. | Restart the app; if it happens again, report it with the log file. |
| AOI-SET-005 | Workspace folder cannot hold the database | The workspace folder does not support the database's write-ahead log (is it on a network drive?). | Choose a folder on this computer in Settings. |
| AOI-SET-006 | Migration files invalid | The app's migration files are not valid: {problem}. | Reinstall the app and report it; this is a defect in the build. |
| AOI-TRN-001 | AI model file refused | AI model file refused: {path} is not a weights-only model file this app wrote ({reason}). | Train the board model again, or import a model file exported by this app. |
| AOI-TRN-002 | Not enough good boards to train | Training needs at least 2 OK (good board) images; {found} found. | Upload more OK images for this board model, then train again. |
