#!/usr/bin/env python3
"""Create ~/.code/schedules/ and its templates.

A schedule item is one hand-editable .md per window-to-open; templates are
plain prompt bodies. Existing files are never overwritten, so re-running this
after the user edits a template is safe.
"""
import pathlib

BASE = pathlib.Path.home() / ".code/schedules"
TPL = BASE / "templates"
TPL.mkdir(parents=True, exist_ok=True)

OUTPUT_CONTRACT = """\
## Output contract
- Write the plan into core/plans/: one roadmap file plus batch files (phases
  sized S/M/L, riskiest last), and keep core/plans/00-overview.md in sync.
- Do NOT implement anything in this session; plans only.
- FINISH by writing a ready-to-paste prompt for the next session into
  core/plans/NEXT-<topic>.md -- the exact text a fresh window needs to start
  executing this plan with no other context.
"""

QUESTIONS_CONTRACT = """\
## Questions contract (nobody is watching this window)
Any fork you would normally raise with AskUserQuestion: do NOT wait for an
answer. Write it into core/plans/QUESTIONS-<topic>.md and continue with your
own recommendation, marking that decision as provisional in the plan.
Format so it can be answered later by replying in plain text:

    ## Q1: <the question>
    - a) <option>   <- RECOMMENDED: <one-line why>
    - b) <option>
    - c) <option>
    Answer: (reply "Q1: a" / "Q1: b" or write a custom answer in free text)

One numbered question per fork, recommended option always marked, custom
answers always possible.
"""

TEMPLATES = {
    "roadmap-plan.md": f"""\
You are generating a roadmap plan autonomously.

1. Map the workspace first: the repos, core/plans and its 00-overview.md,
   recent commits, and any STATUS-*.md handoffs that touch this topic.
2. Identify every fork a user would normally decide, and apply the Questions
   contract below instead of asking.
3. Write the roadmap and its batch files per the Output contract.

{OUTPUT_CONTRACT}
{QUESTIONS_CONTRACT}
## Topic / notes
(paste your notes below)

""",
    "hardening-audit.md": f"""\
You are running a hardening audit autonomously.

1. Audit the subsystem named below: read the code paths end to end and record
   findings with file:line references, each with severity and a one-line
   failure scenario. Findings go in core/plans/hardening-audit-<date>.md.
2. Turn the findings into a numbered roadmap per the Output contract; forks go
   through the Questions contract.
3. Change nothing; this session reads and writes plans only.

{OUTPUT_CONTRACT}
{QUESTIONS_CONTRACT}
## Subsystem / scope
(paste the scope below)

""",
    "blank-plan.md": f"""\
{OUTPUT_CONTRACT}
{QUESTIONS_CONTRACT}
## Task
(paste the task below)

""",
    "resume-status.md": """\
Read {{STATUS_FILE}} and continue from its "How to resume" section.
Work in phases, one commit per phase. Update {{STATUS_FILE}} before stopping
so the next session can resume the same way. If a fork genuinely needs the
user, record it in core/plans/QUESTIONS-<topic>.md with your recommended
answer and proceed with the recommendation.
""",
}

made = []
for name, body in TEMPLATES.items():
    p = TPL / name
    if not p.exists():
        p.write_text(body)
        made.append(name)

readme = BASE / "README.md"
if not readme.exists():
    readme.write_text("""\
# schedules

One .md per window to open later. The watchdog daemon launches due items;
the dashboard's `s` view lists them (and marks unparseable ones corrupted).

Format:

    type: plan | work
    at: reset | 2026-09-06 14:30
    title: Resume 24-C2 row identity
    window: plan1-fixes            (optional: insert the new window after this one)
    cwd: /home/deck/.code/theprototype-app/core
    template: resume-status        (plan only, optional; a file in templates/)
    status: pending                (the executor rewrites this)
    created: 2026-09-06 09:55
    launched:
    ---
    the prompt body that gets pasted into the new window

`at: reset` = when the session limit resets (or the budget reads fresh).
The launched window is named with a leading arrow and appears right after
`window:` when that window exists.
""")
    made.append("README.md")

print("schedules dir:", BASE)
print("created:", ", ".join(made) if made else "(nothing - all files already present)")
