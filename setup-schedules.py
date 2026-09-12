#!/usr/bin/env python3
"""Create an account's schedules/ folder and its templates.

    setup-schedules.py                seed the default account
    setup-schedules.py work           seed the work account's folders
    CLAUDE_CONFIG_DIR=~/.claude-work setup-schedules.py

A schedule item is one hand-editable .md per window-to-open; templates are
plain prompt bodies. Existing files are never overwritten, so re-running this
after the user edits a template is safe.

PER ACCOUNT, because a scheduled window opens a Claude session and therefore
spends one account's budget. The default account keeps the unsuffixed folder it
has always had; a second one gets a sibling beside it.
"""
import pathlib, sys

from muxconfig import mux_dir, profile_of

HOME = pathlib.Path.home()
PROFILE = sys.argv[1].lstrip("-_") if len(sys.argv) > 1 else profile_of()

BASE = mux_dir("schedules", PROFILE)
TPL = BASE / "templates"
TPL.mkdir(parents=True, exist_ok=True)
# The handover folder is seeded here too: it is written to by a wind-down,
# which is the worst possible moment to discover a missing directory.
(mux_dir("handovers", PROFILE) / "done").mkdir(parents=True, exist_ok=True)
mux_dir("backups", PROFILE).mkdir(parents=True, exist_ok=True)

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

## One folder per account

Everything here belongs to ONE Claude account, because launching a window
spends that account's budget. The account is the suffix on the config dir, and
the default account takes none:

    ~/.claude        ->  $MUXTOPUS_HOME/schedules      backups      handovers
    ~/.claude-work   ->  $MUXTOPUS_HOME/schedules-work backups-work handovers-work

An account can also be given a home of its own by setting MUXTOPUS_HOME in
~/.config/muxtopus/profiles/<name>.conf, in which case its three folders live
there UNSUFFIXED (the suffix only keeps siblings apart in a shared home):

    profiles/work.conf:  MUXTOPUS_HOME="$HOME/.code/work/.muxtopus"
    ~/.claude-work   ->  ~/.code/work/.muxtopus/schedules  backups  handovers

`muxtopus -c -P <name>` prints where an account's folders are and every setting.

    tmux session     ->  claude / claude-work
    watchdog state   ->  ~/.local/state/claude-watchdog[-work]

Open a session on an account with `muxtopus` (personal) or `muxtopus
--profile=work`; it puts the account into the tmux SESSION, so every window
opened inside it -- including
one the watchdog launches from this folder -- runs on that account. A tmux
session does not inherit the environment of whatever created it, which is why
this is passed in rather than exported and hoped for.

Handoffs are NOT written into the working tree any more: a wind-down writes
STATUS-<window>.md into the account's handovers/, and `handover.sh done <window>`
moves a finished one into done/. Two accounts working one repo would otherwise
overwrite each other's STATUS file without a word.
""")
    made.append("README.md")

print("schedules dir:", BASE)
print("created:", ", ".join(made) if made else "(nothing - all files already present)")
