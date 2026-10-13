# ADR 0021: A customer's first board model makes the customer's dataset store

- Status: Proposed under Jay's instruction of 2026-10-13 06:06 UTC, item B2 of the business-readiness brief (decision
  D2, findings F2 and F13): "creating a customer's first board model creates that customer's encrypted store and
  places the board model in it, in the same dialog; the recovery key is shown once with Save to file… and Print… and a
  confirmation the user cannot skip. On a platform where keys live in memory only, refuse store creation with a plain
  message that says why, or document the limit in the install guide if refusal would break tests on Linux CI; say which
  you chose. 'Key id', 'Shred Store' and 'Restore Key' stay available to an Admin but move out of the plain flow." Jay's
  merge of this record accepts it.
- Date: 2026-10-13
- Decides: the product owner (Jay), until a tech lead joins
- Related: REQ-TRN-017, ADR 0010 (customer dataset encryption), ADR 0020 (Trial versions, B1), Jay's ADR "Stage 1 for
  one person" (see ADR 0020, Numbering), AOI-TRN-053 (new), AOI-TRN-044, AOI-LOG-002

**Numbering.** As for ADR 0020: Jay's decision record is not in the repository, and this record says how B2 is built.
Where Jay's record decides otherwise, Jay's record wins and this one is changed to match.

## Context

ADR 0010 gave each customer an encrypted dataset store, and the Datasets stage built its steps under Settings › Dataset
stores, each its own step: New Store…, then Move Board Model In…, before the first import, as the engineer manual's
"Creating a board model" says. A person alone, as the business starts, had to know to take those steps in that order,
and the panel put the key ids, Restore Key… and Shred Store…, a step that deletes a customer's data for good, beside
them (F2, F13). ADR 0010's "As built in S38" left "picking the store at a board model's first import" in the sketch.

## Decision

1. **The New board model dialog names the customer.** + New, in the header and on Home and the empty pages, opens a
   dialog with the board model's name and a Customer list: empty by default (an in-house or demo board model, in no
   store, as + New made before), the customers whose stores are not shredded, or a new customer typed. A line under it
   says what Create does with what is typed. The Customer list is an Admin's, as every store step is: for an Engineer
   it is greyed, saying an Admin makes a customer's board model, and Create makes one in no store.
2. **A customer's first board model makes its store, in one transaction.** `AppContext.create_customer_board_model`
   makes the board model as `ensure_board_model` does, the customer's store as `create_store` does when the customer
   has none (its name compared in any case, as `create_store` compares it), and puts the board model in it as
   `move_in` does, with no file to move: `board_model.create`, `recipe.default`, `store.create` and `store.move_in`, all
   or none. A new store's key leaves the key store again if the rest is not stored. A customer with a store gets the
   board model in it and no key is shown; a board model that exists in that store is returned as it is, so + New with a
   name that exists selects it, as before. A board model that exists in no store, or in another customer's, is refused
   (AOI-TRN-044): an Admin moves the first in on Settings, and the second never leaves its store (ADR 0010).
3. **The recovery key is shown once, and cannot be left unread.** The dialog then shows the key in the form's place,
   as Settings' New Store… shows it (`RecoveryKey`, `aoi/ui/pages/recovery_key.py`): its 13 groups of four, the store
   and key id, **Save to File…** and **Print…**, and the tick "I have saved or printed the key and will keep it apart
   from the station", which is off until the key was saved or printed. **Done** is off until the tick; Esc, Cancel and
   the window's close do nothing until then. The key is forgotten as the dialog closes. Save to File… writes the sheet
   as UTF-8 text, offered in Documents under the customer's name, through `AppContext.save_recovery_sheet`, audited as
   `store.sheet_saved` with where it went and never the key; a file that cannot be written is AOI-LOG-002, and so is
   one in the workspace, whose copies and backups hold the files the key opens. Settings' New Store… gets Save to
   File… too, and the same tick.
4. **Memory-only keys: refused.** On any system but Windows, the key store keeps keys in this process's memory
   (`credentials.MEMORY`), so a store's key would be gone when the app closes. `create_store`, and so a customer's
   first board model, is refused there with AOI-TRN-053, which says why and that nothing was made. The refusal reads a
   flag of the key store (`MemoryCredentials(forgets=True)`, `credentials.forgets`), which only the station's own
   memory key store sets: the tests', the screenshots' and the demo bundle's key stores, which keep or write out their
   keys themselves, do not, so Linux CI is unaffected. Refusal was chosen over a line in the install guide because a
   store whose key is lost loses the customer's images; the install guide says so too.
5. **The advanced steps move under a tick.** Settings › Dataset stores shows the customer, created, board models and
   shredded columns, New Store… and Move Board Model In…; the **Advanced: key ids, Restore Key… and Shred Store…** tick
   shows the key id column, Restore Key… and Shred Store…, an Admin's still, as the whole page is. A sign-in turns it
   off.

## Consequences

- ADR 0010's "As built in S38" item "picking the store at a board model's first import stays in the sketch" is now
  built, at the board model's creation rather than its first import: its images are encrypted from the first.
- The manual's step "an Admin moves the new board model into that customer's dataset store … before the first import"
  is now part of + New. A board model made with no customer still needs Move Board Model In… before it can be frozen
  (AOI-TRN-027), as before.
- A key saved to a file is a copy the app cannot see, as a printed one or one printed to PDF is (threat model,
  Information disclosure): the note says to save it on a USB drive kept apart from the station.
- No verdict changes, and no migration: the dialog makes rows the store steps made before.
