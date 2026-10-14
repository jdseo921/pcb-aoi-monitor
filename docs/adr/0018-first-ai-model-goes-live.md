# ADR 0018: A board model's first AI model goes live when its training ends

- Status: Proposed under Jay's instruction of 2026-10-11 18:23 UTC, item A3 of the business-readiness brief (decision
  D3, finding F5): "the first AI model of a board model activates when training ends, with an audit entry and a status
  line that says so; later models install inactive as today". Jay's merge of this record accepts it.
- Date: 2026-10-11
- Decides: the product owner (Jay), until a tech lead joins
- Related: REQ-TRN-010, REQ-TRN-012, REQ-TRN-011, ADR 0014 (shift check), Engineering standard "Go-live gate" and
  "Change control", `AppContext.train`, `_first_live`, `inactive_model`, AOI-TRN-051 (new), `INACTIVE_AI_NOTE`

## Context

Since S43 every AI model version installs inactive, and an Engineer activates it with its card on Training; the
Engineering standard's go-live gate (MUST) says a new or retrained version "installs inactive, the customer's engineer
activates it", and REQ-TRN-012's acceptance says the same. For a board model's first version that step keeps nothing:
there is no version in use to protect, and Roll Back has nothing to go back to. Until an Engineer found Activate
Selected, the line ran on the Golden board comparison alone, and Inspection's alarm log, Home and AI Model Test said
"No AI model … yet" of a board model that had one. The brief names this F5 and decides D3; I could not read the brief,
so its words are taken from Jay's message.

## Decision

1. **The first version goes live.** When `train` registers a board model's first version (no version of any use
   registered before it), trained for the customer's own AI models (`use` "own", the only use Training offers), it is
   made active with its Golden board in a transaction
   of its own, after the version's (`_first_live`). It goes through `_switch_to`, as Activate Selected does: refused
   without its card (AOI-TRN-049) or a readable Golden board (AOI-TRN-048), and audited as `model.activate` with the
   version and Golden board before and after, under the Engineer who started the run, with the reason "the first AI
   model of its board model, which goes live when its training ends". The status bar and the run's log say so.
2. **Every later version installs inactive,** as before, and so does a first version trained for shared improvement or
   demos, which is not the line's own; after one, the board model has no first version left to go live, and its own
   versions are named with Activate (decision 4). Only tools and tests train for those uses today.
3. **A first version that cannot go live stays inactive and says why.** `train` returns the error in `not_live`;
   Training shows it as any error (its code, what happened, what to do, and an alarm) and its status line says the
   version is not active.
4. **A trained version is never called "no AI model".** While a board model has one trained and none active
   (`inactive_model`: trained before this release, refused, or for another use), Inspection names it on a line with
   Activate <version> (Engineer and Admin, greyed for an Operator with the reason) and its alarm is AOI-TRN-051; Home's
   Train AI model card, AI Model Test and Compare's "why" box name it too; AOI-INSP-010 says "no AI model is active".

## Consequences

- **A departure from a MUST, approved.** The go-live gate's "installs inactive" no longer holds for a board model's
  first version. Jay approved it in the message quoted above; the Engineering standard's go-live gate text needs the
  same exception, which this change does not edit. The gate's comparison with the live version (REQ-TRN-012, release
  1.0) has no live version to compare a first one with, so this decides nothing about it.
- **Verdicts change at training's end.** From then on the AI check judges the board model's boards, adding NG and WARN
  calls to the Golden board comparison's, and boards are compared with the Golden board training built (the median of
  the frozen OK images), which replaces one set with Set Reference. This is a verdict-changing change: the release
  note's first section says so, and customers re-validate (Change control). A run in progress moves (AOI-INSP-013),
  even with the AI check off, as the Golden board changes; where Shift Check is on, the board model needs a shift
  check with the new version before its next board (ADR 0014).
- **No Roll Back from a first version.** Roll Back stays off, as after a first manual activation. The way back is the
  recipe's "Use the self-trained AI model" tick, off and saved as a recipe revision, and Set Reference for the Golden
  board; both are audited.
- **Accepted risk.** A poisoned first dataset reaches the line without an Engineer's second look at the version. What
  stands against it: the label checks, the agreement check and the freeze a Validated version had to pass, the AI check
  adding calls rather than removing them, the audit entry, and the shift check where it is on (threat model, page 2).
  A Trial first version passed neither check; ADR 0020 (decision 4) accepts that risk apart.
- **Upgrade.** Nothing changes at the upgrade: a version trained before stays inactive and is named with Activate. No
  schema change. The synthetic regression set runs with no AI model, so its `expected.json` is unchanged.
- **Tools.** `tools/render_screens.py`, `tools/soak.py` and `tools/make_demo_bundle.py` activate a version only when
  training did not.
- Not done: the go-live gate's comparison (REQ-TRN-012, release 1.0); a setting that keeps first versions inactive for
  a customer whose change control asks for it.

## Customer notice (draft, for Jay to send)

> **Subject: the first AI model of a new board model now goes live when its training ends**
>
> From the next release, when your engineer trains the first AI model of a board model, it starts judging that board
> model's boards as soon as training ends, together with the Golden board comparison, and boards are compared with the
> Golden board that training built. Until now it waited until your engineer pressed Activate Selected on the Training
> page. Verdicts of that board model can change from then on: the AI check can add NG and WARN calls, and the new
> Golden board can change what the comparison finds.
>
> What does not change: every later version installs inactive and goes live only when your engineer activates it, and
> Roll Back returns to the version before in one click; every activation, this one included, is in the audit trail with
> who did it and why; nothing changes when you upgrade, and a version trained before stays as it is.
>
> What we ask: train a board model's first AI model before its production run, then test it on AI Model Test on the
> locked validation set before you rely on its verdicts. To stop it judging boards, untick "Use the self-trained AI
> model" in the Recipe Editor and save the recipe. Where Shift Check is on, the board model needs a shift check with
> the new AI model before its next board.
