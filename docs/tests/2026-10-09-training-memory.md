# Training memory and time, 2026-10-09

Stage S39 changed how a training run holds its images (REQ-TRN-007): it reads one image at the camera's resolution at a
time, keeps its tensor at the network's input size, and works out the Golden board's median a band of rows at a time,
reading the OK images again for each later band. This record measures the run's peak memory and time against the
requirement's budget (50 OK images train in at most 10 min on a CPU, using at most 8 GB of memory at the customer's
resolution) and against the [resolution test](2026-10-01-resolution-test.md), which measured v0.1 holding every image
at once.

**Synthetic boards only.** These numbers describe memory and time. They are not accuracy and are never quoted as
accuracy.

## Set-up

- Code: branch feat/REQ-TRN-007-train-from-frozen-version (S39), through `AppContext.train` as the Training page
  calls it, from a frozen version in a customer's dataset store, so every file is decrypted in memory and its SHA-256
  checked against the one frozen.
- Machine: the same kind of cloud VM as the resolution test, not the reference PC, which is still open: 4 virtual CPUs
  (Intel Xeon, 2.1 GHz), 16 GB of memory, no GPU; Python 3.11.15, PyTorch 2.14.1 on the CPU, OpenCV 5.0.0, NumPy
  2.4.6.
- Boards: `tests/training_memory_worker.py` draws 50 OK and 3 NG boards with `tools/make_synthetic_dataset.py` at
  640 × 480, with a fixture's variation, scales each up with cubic interpolation to 5 MP (2592 × 1944), 12 MP
  (4000 × 3000) or 20 MP (5184 × 3888) and writes it as a PNG file, one at a time. It imports them, freezes a version
  with all 53 in its training set (`tools/trainable.py`) and trains 60 epochs at 256 px, the defaults, with the Golden
  board's band as shipped (`golden.BAND_BYTES`, 1 GiB).
- Each size runs in a process of its own. Peak memory is the process's peak resident size, in decimal GB; it includes
  drawing and importing the boards before the run, which stay under 0.6 GB, so it is an upper bound on the run's. The
  resolution test's boards were varied after scaling rather than before, and its bench trained outside `AppContext`
  from plain files.

## Results

| Size | Boards decoded | Bands | Training time | Peak memory | v0.1, resolution test |
|---|---|---|---|---|---|
| 5 MP | 0.80 GB | 1 | 104 s | 1.86 GB | 97 s, 3.1 GB |
| 12 MP | 1.91 GB | 2 | 144 s | 2.28 GB | 126 s, 6.4 GB |
| 20 MP | 3.20 GB | 3 | 229 s | 2.40 GB | 169 s, 10.4 GB |

- Memory: about 0.57 GB before the run (the app and PyTorch loaded), then at most one band of 1 GiB, one board at
  its resolution and the tensors. At 5 MP the 50 OK boards fit in one band, so that run still holds them all once.
  Every size stays under the 8 GB budget, and so would 50 boards of any size, the band being fixed.
- Time: every size is under the 10 min budget. Each band after the first reads, decrypts, decodes and warps the 50 OK
  files again: at 20 MP that is two more reads of each, most of the 60 s the run takes beyond v0.1's. A JPEG decodes
  about 5 times faster than a PNG of the same size (resolution test), so JPEG boards cost less.
- `tests/test_training_memory.py::test_req_trn_007_peak_memory_under_budget` runs this worker on 20 and on 50 OK boards
  at 5 MP, 1 epoch at 64 px, with a 200 MB band: on this VM both runs grew 509 MB above their start, within 1 MB of each
  other, where the 30 boards more take 453 MB decoded.

## Where it led

The customer's resolution is not known yet, so the requirement's budget is quoted at 5, 12 and 20 MP. Requirement row
REQ-TRN-007 quotes this record. The reference PC, once chosen, gets the same run, and a GPU run measures the 2 min
budget.
