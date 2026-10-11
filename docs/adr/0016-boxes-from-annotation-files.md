# ADR 0016: Defect boxes from a dataset's annotation files

- Status: Proposed under Jay's instruction of 2026-10-11 ("Make it flawlessly function through stage 1 demonstration
  and usage of any training data to detect defects at proficient accuracy"; decisions follow industry norms). Jay's
  merge of this record accepts it.
- Date: 2026-10-11
- Decides: the product owner (Jay), until a tech lead joins
- Related: REQ-TRN-019 (new, SHOULD G1), REQ-TRN-001, REQ-TRN-003, REQ-TRN-018, `aoi/core/annotation_files.py`,
  `AppContext.import_files`, `AppContext.import_samples` (new keyword `added`), `ImportFile.box_types`,
  `ImportReport.boxes`

## Context

Training's import sheet labels an image by its folders (`ok/`, `ng/<defect type>/`), and its defect boxes are then
drawn one by one in the label editor. A labelled dataset, whether a customer's or a public one such as PKU-Market-PCB,
arrives with its boxes already drawn, in an annotation file beside each image: Pascal VOC XML (LabelImg, CVAT, PKU) or
YOLO text (Roboflow, Ultralytics, most exports today). Without reading them, 693 PKU images and their 2,953 boxes would
have to be drawn again by hand, and a folder such as `images/Open_circuit/` lands as "unsorted: pick a label". The
boxes are what the comparison's thresholds learn from (REQ-TRN-018) and what a validation counts as found or missed.

## Decision

1. **Both common formats, found where datasets keep them.** An image's annotation file is `<stem>.xml` or
   `<stem>.txt` beside it, else the same relative name under an `Annotations` (VOC) or `labels` (YOLO) folder that
   mirrors the folder the images are in, searched up to the folder picked. YOLO class names come from `classes.txt`,
   `obj.names` or the `names` of a `data.yaml` nearby.
2. **Classes map to the classification table's types.** A class named as a type (any case, `_` or `-` for spaces) or
   by a bare-board name public sets use (`mouse_bite`, `missing_hole`, `spurious_copper`, `open`, `short`) takes that
   type. A box of any other class is left out and named, never guessed, as a person names a defect (REQ-TRN-003).
3. **The sheet labels and types the image; the import stores the boxes.** An image with boxes of known types is NG
   when its folder gave no label, with its boxes' most common type when none was given; an image whose annotation
   holds no box is OK when its folder gave no label, as annotation tools mark a good image. A label or type the folder
   gave stays, and the user can still change any row. The import stores the boxes through `set_boxes`, at the size of
   the image as decoded, so each is audited as `label.set` like a box drawn by hand.
4. **Annotation files are untrusted inputs.** One over 1 MB is not read, a VOC file with a document type (where XML
   entities are declared) is refused before parsing, a VOC file made for an image of another size gives no box, and
   boxes are cut to the image. The image still comes in with its label and type, and its row says why no box came.

## Consequences

- A labelled dataset in either format comes in, boxes and all, in one Import Folder…, ready to freeze, to learn the
  comparison's thresholds from and to validate on. No verdict changes: boxes are labels, which no inspection reads.
- The service API grows backward-compatibly: `import_samples(..., added=[...])` gives each new sample's UUID, and
  `ImportReport.boxes` counts each NG file's boxes stored with why any were not.
- Reading annotation files happens while the sheet lists the folder, on the UI thread, as the folder's listing does:
  a few stat calls and one small file per image (693 PKU images took well under a second here). A folder of tens of
  thousands of images would need the listing moved to the pool.
- Not done: DeepPCB's own `<group>_not/` text format, COCO JSON (one file for a whole dataset) and polygon masks.
  Each is a follow-up if a customer's data comes that way.
