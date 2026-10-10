# AOI PoC Inspector: what you saw, and Stage 1 with your boards

A one-page handout for the customer, given at the end of every demo.

## What you saw

- An inspection station for photos of your boards. Each board gets a verdict, OK or NG, with the time it took,
  and the run stops at an NG board so a person looks at it.
- Every verdict explains itself. **Compare shows the board beside the Golden board, the good board it is compared
  with, every check with its value and threshold, and why the board is NG in plain words.
- An AI model that learns from photos of your good boards, and two checks that judge each board independently:
  the difference to the Golden board, and the AI model.
- Results you keep. Every board is recorded with its time, verdict, the AI model and the thresholds that judged
  it; the CSV and the pictures on your USB stick are yours.

The boards in the demo are drawn by our own tool. They show how the station works, not how well it finds defects on
your boards. We measure that on your boards, and we always give it as counts.

## How we report results on your boards

Two numbers matter on a line, and we give both as counts on boards the AI model has never seen:

| | Example |
|---|---|
| Missed defects: boards with a known defect called OK | 0 of 30 |
| False calls: good boards called NG | 2 of 100 |

Each count comes with the worst case it still allows (95 % upper bound). With 0 missed of 11 boards the worst case is
23.8 %; with 0 of 30 it is 9.5 %; with 0 of 60 it is 4.9 %. More boards with known defects give you a smaller worst
case.

## What Stage 1 needs from you

1. Photos of good boards: at least 70 of one board model, from the same camera position. 50 of them are kept apart
   to check the AI model and never used to train it; more is better.
2. Photos of boards with known defects: as many as you have, each with its defect type. We keep them apart and
   use them only to check the AI model, never to train it.
3. An engineer of yours for about an hour, to check how the photos are labelled.
4. A PC for the station** (see below).

## What you get

- The station set up for your board model, trained on your good boards.
- A report with the counts above, measured on your boards with known defects.
- The demo again, on your own boards.

## Your data

- Your photos stay on the station PC. The app opens no network port and makes no connection; it works with the
  network cable out.
- Training photos are kept in an encrypted store for your company; the key is held by Windows on that PC.
- Nothing leaves your site unless you agree in writing. What we keep, and for how long, is agreed with you in
  writing before the trial.

## The station PC

- 64-bit Windows: Windows 11 IoT Enterprise LTSC 2024 recommended; Windows 11 Enterprise LTSC 2024; Windows 10 IoT
  Enterprise LTSC 2021 on existing PCs; Windows 11 Pro or Enterprise while their version is still patched. Windows 10
  Home and Pro are not supported.
- An SSD of 1 TB or more, 2 TB recommended.
- An NVIDIA graphics card with CUDA speeds up training. The station also trains and inspects without one, more slowly.

Questions after the demo: write to the person who showed it to you.
