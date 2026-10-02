# Error codes

Generated from `aoi/errors.py` by `python -m aoi.errors`; do not edit. Every error a user can see carries one
of these codes with what happened and what to do (REQ-LOG-004, REQ-SET-019). Areas follow the requirement
register; `{braces}` are filled in when the error is raised.

| Code | Title | What happened | What to do |
|---|---|---|---|
| AOI-CMP-001 | Result has no stored heatmaps | The result of {file} was saved without its difference and AI maps, or they were deleted after the retention period of {days} days. | The decision table is the stored one; use Side by side or Boxes only, or inspect the board again on Inspection to see its heatmaps. |
| AOI-CMP-002 | Result has no stored decision table | Record {id} ({file}) has no stored decision table: it was saved before migration 0006, or no record has that number or UUID. | Inspect the board again on Inspection; Compare then opens the new result. |
| AOI-CMP-003 | Stored map cannot be read | The stored map {file} could not be read: {reason}. | The stored verdict and decision table still stand. Close any program that has the file open and open the result again; if the file is damaged, inspect the board again on Inspection. |
| AOI-CMP-004 | Result cannot be judged again | The result of {file} cannot be judged again with other thresholds: what it was judged on is no longer stored ({missing}). | Its stored verdict and decision table still stand. Inspect the board again on Inspection, then try the thresholds on the new result. The maps of OK results are deleted {days} days after inspection; NG and WARN maps are kept. |
| AOI-CMP-005 | Thresholds of another board model | The thresholds tried are board model {tried}'s, but the result of {file} was judged for board model {judged}. | Nothing was judged. Open the result on Compare with its own board model picked, then try the thresholds again. |
| AOI-INSP-001 | Image cannot be read | The file {path} could not be opened as an image. | Check that the file exists and is a PNG, JPG, BMP or TIFF image. |
| AOI-INSP-002 | Image cannot be written | The image {path} could not be encoded for writing. | Check the file name's extension (.png or .jpg) and try again. |
| AOI-INSP-003 | Board failed inspection | Board {board} failed inspection with {defects} defect(s). | Review the result on the Compare page before the board moves on. |
| AOI-INSP-004 | File format not supported | The file {path} does not hold a PNG, JPG, BMP or TIFF image; the format is read from the file's content, not its name. | Save the image as PNG, JPG, BMP or TIFF with an image tool and load that file. |
| AOI-INSP-005 | Image over the size limit | The image {path} is {size}, over the limit of {limit}. | Use a smaller image, or ask an Admin to raise the limit: max_image_megapixels or max_image_megabytes in settings.json, in the default workspace folder. |
| AOI-INSP-006 | Image file cannot be decoded | The {kind} image {path} could not be decoded: {reason}. | Copy the file again from the camera or its source; if it fails again, save it as PNG or JPG with an image tool and load that file. |
| AOI-INSP-007 | Image side too long | The image {path} is {width} × {height} px; a side over {limit} px is beyond what this app decodes. | Crop or scale the image so that no side is over {limit} px; this limit is the decoder's and cannot be raised. |
| AOI-INSP-008 | Result not saved | The result of {file} was shown but could not be saved, so it is not in Logs & Export. | Check the free disk space and that the workspace folder can be written, then press Next Board to carry on and inspect {file} again later. |
| AOI-SET-001 | Workspace from version 0.1 | This workspace was created by AOI PoC Inspector 0.1 and cannot be upgraded. | Choose a new workspace folder in the window that opens next; Cancel there closes the app. |
| AOI-SET-002 | Workspace newer than the app | The workspace database was written by a newer build of the app: it records migration {migration}, which this build does not have. | Update the app, or choose another workspace folder in the window that opens next; Cancel there closes the app. |
| AOI-SET-003 | Migration file changed | Migration {file} differs from the one recorded in the workspace database; a shipped migration is never edited. | Reinstall the app to restore the file, or choose another workspace folder in the window that opens next; Cancel there closes the app. |
| AOI-SET-004 | Migration failed | Migration {file} failed and was rolled back: {error}. | Restart the app; if it happens again, report it with the log file. |
| AOI-SET-005 | Workspace folder cannot hold the database | The workspace folder does not support the database's write-ahead log (is it on a network drive?). | Choose a folder on this computer in the window that opens next; Cancel there closes the app. |
| AOI-SET-006 | Migration files invalid | The app's migration files are not valid: {problem}. | Reinstall the app and report it; this is a defect in the build. |
| AOI-SET-007 | Unexpected error | An unexpected error ({error_type}) stopped the last action{context}. | Try again; if it happens again, restart the app and send the log file (the workspace's logs folder) to support. |
| AOI-SET-008 | Setting invalid | The setting {name} in settings.json is {value}; it must be {expected}. | Fix or remove that line in settings.json, in the default workspace folder, and start the app again. |
| AOI-SET-009 | Backup before upgrade failed | The workspace database could not be copied to {file} before this version upgrades it: {error}. Nothing was changed. | Free disk space on the workspace folder's drive and check that the folder can be written, then start the app again. |
| AOI-TRN-001 | AI model file refused | AI model file refused: {path} could not be loaded as a weights-only model file this app wrote ({reason}). | Train the board model again, or import a model file exported by this app. |
| AOI-TRN-002 | Not enough good boards to train | Training needs at least 2 OK (good board) images; {found} found. | Upload more OK images for this board model, then train again. |
| AOI-TRN-003 | No trained AI model | Board model {board} has no trained AI model, so only the golden-board comparison runs. | Train a model on the Training page when the AI checks are needed. |
| AOI-USR-001 | Not allowed for this role | {what} needs the {roles} role. | Sign in as a user with that role, or ask one to do it. |
