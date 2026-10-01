# Resolution test, 2026-10-01

Planning item 6 of #9. Before real board photos arrive (#10), it measures how v0.1's pipeline scales with camera
resolution: time per board against REQ-INSP-007, training time and memory against REQ-TRN-007, and the smallest
defect found against REQ-INSP-014.

**Synthetic boards only.** These numbers describe speed, memory and pixel sizes. They are not accuracy and are
never quoted as accuracy.

## Set-up

- Code: v0.1 at commit 364d2c2, unchanged. A bench script trains as `AppContext.train` does (align every image to
  the first, take their median as the golden board, train the AI model) and times `Inspector.inspect` with the
  default recipe, stage by stage.
- Machine: a cloud VM (KVM) with 4 virtual CPUs (Intel Xeon, 2.1 GHz), 16.9 GB of memory and no GPU; Python
  3.11.15, PyTorch 2.14.1 on the CPU, OpenCV 5.0.0, NumPy 2.4.6. It is not the reference PC, which is still open.
- Boards: `tools/make_synthetic_dataset.py` draws its 640 × 480 layout, scaled up with cubic interpolation, then
  varied as a fixture would (up to 1° of rotation, a shift, ±5 % gain, noise). The frame is assumed to span a
  150 mm wide board: 4.27 px/mm at 0.3 MP (640 × 480), 17.28 at 5 MP (2592 × 1944), 26.67 at 12 MP
  (4000 × 3000) and 34.56 at 20 MP (5184 × 3888).
- Training: 50 OK and 3 NG boards, 60 epochs at 256 px.
- Inspection: 4 clean boards, then the same boards each with one round blob in the generator's solder-ball colour,
  on a bare spot at least 2.3 mm from any part, in 7 sizes from 0.1 to 1.0 mm (4 sizes up to 0.3 mm at 20 MP):
  32 inspections per size, 20 at 20 MP. Each blob is drawn with its true area. A first run drew them with
  OpenCV's anti-aliased circle, which inks a 1.7 px blob about three times over, so its small-blob results are
  not used.

## Time per board

Medians, with the 95th percentile in brackets, for `Inspector.inspect` alone:

| Size | Boards | v0.1 | Compare step's share of the median | With the compare step rewritten (#12), estimated |
|---|---|---|---|---|
| 0.3 MP | 32 | 0.41 s (0.44 s) | 90 % | 0.09 s (0.10 s) |
| 5 MP | 32 | 6.96 s (7.22 s) | 97 % | 0.52 s (0.55 s) |
| 12 MP | 32 | 22.8 s (24.6 s) | 98 % | 1.26 s (1.42 s) |
| 20 MP | 20 | 42.3 s (45.8 s) | 99 % | 2.09 s (2.30 s) |

- The estimate replaces v0.1's measured compare time on each board with the prototype's, measured on the same
  board. The prototype matched v0.1's difference map, mask and regions bit for bit on all 116 boards, and its
  SSIM score within 7e-7.
- Decoding the file is extra: a PNG takes 0.12 s at 5 MP, 0.27 s at 12 MP and 0.48 s at 20 MP, a JPEG 0.03,
  0.06 and 0.10 s.
- On one thread the prototype took about as long as on four (0.35 s against 0.36 s at 5 MP), so on this
  machine extra cores did not make it faster.

## Training

| Size | Align | Golden board | AI model | Total | Peak memory |
|---|---|---|---|---|---|
| 0.3 MP | 1.1 s | 0.9 s | 66 s | 68 s | 1.1 GB |
| 5 MP | 5.9 s | 13.2 s | 78 s | 97 s | 3.1 GB |
| 12 MP | 12.7 s | 30.9 s | 82 s | 126 s | 6.4 GB |
| 20 MP | 20.2 s | 55.9 s | 93 s | 169 s | 10.4 GB |

Peak memory is the process's peak resident size, in decimal GB, with all 53 images held at once as v0.1 does.
The first run, at 0.3 to 12 MP, agreed within 5 s and used the same memory.

## Smallest blob found

Each cell gives the blob's width in pixels and, for 4 boards, how often it made the board NG, got a WARN region
of its own, or was missed. Bare board is the easiest place to see a defect, so these are best cases.

| Blob | 0.3 MP | 5 MP | 12 MP | 20 MP |
|---|---|---|---|---|
| 0.1 mm | 0.4 px: missed | 1.7 px: missed | 2.7 px: missed | 3.5 px: missed |
| 0.15 mm | 0.6 px: missed | 2.6 px: missed | 4.0 px: missed | 5.2 px: missed |
| 0.2 mm | 0.9 px: missed | 3.5 px: missed | 5.3 px: missed | 6.9 px: NG 3/4, missed 1/4 |
| 0.3 mm | 1.3 px: WARN 4/4 | 5.2 px: WARN 4/4 | 8.0 px: NG 4/4 | 10.4 px: NG 4/4 |
| 0.4 mm | 1.7 px: WARN 4/4 | 6.9 px: NG 2/4, WARN 2/4 | 10.7 px: NG 4/4 | not run |
| 0.5 mm | 2.1 px: WARN 4/4 | 8.6 px: NG 4/4 | 13.3 px: NG 4/4 | not run |
| 1.0 mm | 4.3 px: NG 4/4 | 17.3 px: NG 4/4 | 26.7 px: NG 4/4 | not run |

- The compare step found all 28 blobs 8 px or more across, 5 of 8 at 6.9 px and none smaller. Its smallest
  region, 40 px of area, is set in pixels.
- The AI model sees a 256 × 256 copy of the board, so a blob shrinks before it gets there: it gave NG for a
  4.3 px blob at 0.3 MP and found no blob at 20 MP.
- One of the four clean 5 MP boards was already WARN before any blob was added.

## Where it led

Requirement rows REQ-INSP-007, REQ-INSP-014, REQ-TRN-007 and REQ-RCP-006 quote this test, and the compare rewrite
is #12. The bench, the prototype, the table scripts and every raw result are in the project's shared folder,
`feasibility/`; #12 brings the timing into this repository as a performance test.
