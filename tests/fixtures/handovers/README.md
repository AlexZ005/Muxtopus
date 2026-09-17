# tests/fixtures/handovers -- every shape a real handover has

TRIMMED COPIES, never the real files: the folder they were measured in is
`~/.code/handovers`, which holds the user's actual work and which no test may
read, write or move anything in. Each file here keeps the SHAPE of one real
file -- where its title is, whether the title says anything, how its forks
are numbered, how its options are written -- and none of its content.

    hdir/           the account's handovers folder
    hdir/done/      what handover.sh done moved, stamped names included
    legacy/         MUXTOPUS_QUESTIONS_DIR, the older contract's folder,
                    which is still LIVE: lanes are writing into it today

The shapes, and the real file each was taken from:

| fixture | the shape it stands for |
|---|---|
| `STATUS-open-lane.md` | a lane still working; title says nothing, gist does |
| `STATUS-verdict-lane.md` | the title carries the verdict (`— **COMPLETE**`) |
| `STATUS-prose-lane.md` | no heading at all; the file opens with a paragraph |
| `STATUS-shadow-lane.md` | ALSO in done/ -- ran, was finished, ran again |
| `STATUS-fenced-lane.md` | a fence and a table before the first prose line |
| `done/STATUS-done-lane.md` | finished |
| `done/STATUS-rerun-lane-20260917-101500.md` | a SECOND finish, stamped |
| `QUESTIONS-open-lane.md` | numbered forks, bulleted options, one answered |
| `QUESTIONS-inline-lane.md` | options inline on the fork's own line |
| `QUESTIONS-prose-lane.md` | `## N.` headings, no options, `**Answer taken:**` |
| `QUESTIONS-marked-lane.md` | carries the ANSWERED marker |
| `legacy/QUESTIONS-legacy-lane.md` | the same, in the older folder |
| `notes.md`, `24-stars-drafts/` | NOT handovers; a reader must ignore both |
