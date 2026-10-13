-- REQ-TRN-004, REQ-TRN-016 (business-readiness B1, decision D1; ADR 0020): a frozen dataset version is Validated, frozen
-- with every NG label and 10 % of the OK labels checked by a second user and a labeller agreement check that reached
-- its targets, as every version frozen before this migration was; or Trial, frozen by one person without them. A Trial
-- version names no agreement check (agreement_check_uuid is empty), and it and every AI model trained from it are
-- marked Trial wherever they are named. Like the rest of a version's row, the column never changes (ADR 0009).

ALTER TABLE datasets ADD COLUMN assurance TEXT NOT NULL DEFAULT 'Validated' CHECK(assurance IN ('Validated', 'Trial'));
