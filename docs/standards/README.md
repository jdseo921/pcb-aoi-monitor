# AOI Standards in the repository

The four AOI Standards bind every change to this repository (`CLAUDE.md`, "Read first"). Jay keeps editing them as
Claude Docs; these files are copies of record, so that a session, a reviewer or the company reads exactly the
text a change was held to, at the commit it was made. A change to a source is re-exported here in a pull request
whose title cites the Standard and its new revision; if a copy and its source differ, the source wins until then.

| File | Source (Claude Docs) | Revision exported | Exported |
|---|---|---|---|
| [charter.md](charter.md) | [AOI Standards – Charter](https://claude.ai/code/artifact/cdb76b42-fd68-42e9-8c59-25abdf86b114) | 24 | 2026-11-01 |
| [engineering.md](engineering.md) | [AOI Standards – Engineering](https://claude.ai/code/artifact/346f0966-33e4-4134-9fa6-c0ddad0758db) | 11 | 2026-11-01 |
| [customers-and-launch.md](customers-and-launch.md) | [AOI Standards – Customers & Launch](https://claude.ai/code/artifact/af8143f9-f8c3-4f2f-bb40-9646d588c860) | 11 | 2026-11-01 |
| [legal-and-compliance.md](legal-and-compliance.md) | [AOI Standards – Legal & Compliance](https://claude.ai/code/artifact/e99c8a5f-ee90-4fdf-a308-745d4c4edd87) | 11 | 2026-11-01 |

`tests/test_standards_in_repo.py` fails when `CLAUDE.md` cites a Standard that has no file here, when a file here
lost its source link, or when an ADR or the register names a Standard without linking its file.

## What the export changed

Each file is the Claude Docs Markdown export of its source, whole and in order, with three kinds of change and no
others (`diff` against the raw export shows only these lines):

1. **A provenance line** under the title: the source link, the revision and the export date.
2. **Links between the Standards.** In the source, a mention of another Standard is a link to it; the export keeps
   only its name. Each such name is linked to its file here, with the words unchanged: 9 in the Charter, 2 in
   Engineering, 5 in Customers & Launch, 4 in Legal & Compliance.
3. **Drawings as text.** Three sections hold a drawing that the export leaves out, keeping only a placeholder line.
   Each placeholder is replaced by the drawing's title, subtitle, every label and its footnote, as a table, marked as
   transcribed: the stage gates in the Charter ("Stage gates"), the engine layers in Engineering ("Architecture and
   code") and the launch phases in Customers & Launch ("Launch"). Arrows become words ("Gate before the next
   stage", "calls only go down"); colour, the highlighted box (shown in bold) and the dashed boxes (named *later*)
   carry no rule of their own.

Kept as the export writes them: the date and author line under each title (date and mention chips in the source),
the source's own wording where it is out of date in this repository (the Charter's "`docs/ARCHITECTURE.md` in the
shared `pcb-aoi-app` folder" and its open question about moving the code to GitHub; the Engineering standard's
"Known v0.1 gaps"), and the Charter's comment thread on "GPU or CPU-only stations for release 1.0", which is a comment
and not part of the text.

Checked on export: every text run of the Charter, Engineering and Customers & Launch sources (read as the document's
structure, not its export) appears in its file, 0 missing; for Legal & Compliance, which has no drawing, the export's
own report lists only the date, author and link changes above.
