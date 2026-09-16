#!/usr/bin/env python3
"""Create an account's schedules/ folder and its templates.

    setup-schedules.py                seed the default account
    setup-schedules.py work           seed the work account's folders
    CLAUDE_CONFIG_DIR=~/.claude-work setup-schedules.py

A schedule item is one hand-editable .md per window-to-open; templates are
plain prompt bodies. Templates are never overwritten, so re-running this after
the user edits one is safe. README.md IS rewritten: it is generated
documentation of the executor's format, and one that stops tracking the
executor is worse than none.

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

# THE README IS GENERATED DOCUMENTATION, not a file the user owns, so unlike the
# templates it is rewritten every run: a format doc that stops tracking the
# executor is worse than no doc at all, and "never overwrite" froze it at
# whatever the folder was seeded with. Templates are still never touched.
readme = BASE / "README.md"
readme.write_text("""\
# schedules

One .md per window to open later. The watchdog daemon launches due items;
the dashboard's `s` view lists them (and marks unparseable ones corrupted).

Format:

    type: plan | work
    at: reset | 2026-09-06 14:30
    title: Resume 24-C2 row identity
    slug: 24-c2-rows                (optional: pins the lane name -- see below)
    after: 24-c1-schema, 24-c2-rows (optional: hold until ALL of those have finished)
    parent: 24-c1-schema            (optional: draw this window under that one)
    window: plan1-fixes            (optional: insert the new window after this one)
    cwd: /home/deck/.code/theprototype-app/core
    template: resume-status        (plan only, optional; a file in templates/)
    model: opus                    (optional: fable | opus | sonnet | full id; default from settings.json)
    effort: high                   (optional: low | medium | high | xhigh | max -> claude --effort)
    permission-mode: bypassPermissions   (optional -> claude --permission-mode)
    options: questions, phases     (written by the dashboard's options table; see below)
    status: pending                (the executor rewrites this)
    created: 2026-09-06 09:55
    launched:
    ---
    the prompt body that gets pasted into the new window

The launched window is named with a leading arrow and appears right after
`window:` when that window exists.

## Placeholders, resolved when the body is PASTED

The body is not a literal string. Seven names are substituted the moment the
window opens, over the template, the body and the work footer -- never over the
`[muxtopus]` identity lines at the top, which are built from the resolved values
already:

    {{SLUG}}       27-storage
    {{WINDOW}}     the tmux window name, arrows included: ➥27-storage
    {{HANDOVER}}   <handovers>/STATUS-27-storage.md
    {{QUESTIONS}}  <handovers>/QUESTIONS-27-storage.md
    {{SCHEDULES}}  this folder
    {{CWD}}        the entry's cwd: field
    {{PARENT}}     the entry's parent slug, or empty for a root window

They exist because the slug is not knowable when the body is WRITTEN -- least of
all in a template shared by twenty entries -- so a sentence that needs it can
only carry a placeholder and have the executor resolve it at paste time. One
function does the substitution, shared by the launcher and by `--check --body`,
so the report and the paste cannot drift apart.

A `{{NAME}}` that is not in that table is left in the paste as LITERAL TEXT and
warned about -- in `claude-watchdog.sh --check`, in the log at launch, and as a
yellow note on the dashboard row, the same way a derived slug is. It is never
blanked: a body that meant to say `{{PORT}}` still says it.

`claude-watchdog.sh --check <entry> --body` prints the substituted paste, so a
wrong placeholder is visible before anything launches.

## `options:` -- what the create-time options table ticked

The dashboard's `c` flow offers a table of checkboxes and records what was
ticked as one header line:

    options: questions, phases, lanes=3

That line is the source of truth for reopening the table (`o` in the `s` view),
which regenerates the `## Options` section at the bottom of the body from it.
THE EXECUTOR PARSES NOTHING FROM IT. The sentences those options produce are
ordinary body text by the time this folder is read, and the header fields they
set (`model:`, `effort:`, `permission-mode:`) are ordinary header fields. Deleting the line changes
nothing about how the entry runs -- only what the table shows when reopened.

## `permission-mode:` -- the one setting that cannot be fixed after launch

A scheduled window is UNATTENDED by definition. Without this field the launcher
passes no mode, so the window inherits `defaultMode` from settings.json, and a
window in `auto` that reaches a decision it will not take on its own simply
STOPS -- silently, with no prompt anyone will answer. Measured 2026-09-16: that
is how four lanes sat idle for three days.

It cannot be corrected once the window is open, either. shift+tab cycles
auto -> manual -> accept edits -> plan -> auto, and `bypassPermissions` is NOT
in that cycle. The only way in is the launch command:

    permission-mode: bypassPermissions

Accepted: whatever `claude --permission-mode` accepts at the installed version,
which today is `acceptEdits auto bypassPermissions manual dontAsk plan`. Case
is folded to the CLI's own spelling (`bypasspermissions` works) and the fold is
logged. Anything else is DROPPED with a log line and no flag is passed, because
`claude` exits 1 on an invalid mode and the window would never reach a prompt --
an optional field's typo must not cost the entry its run.

ABSENT MEANS ABSENT: no flag, and the account's own setting applies. That is
the default and it is deliberately unchanged -- an unattended window that skips
every permission check is a choice the entry has to make out loud.

`claude-watchdog.sh --check <entry>` reports the resolved mode beside `model`
and `effort`, and the launch line in the log records it as `perm=<mode>`.

## `at: reset` is TWO gates, not one

They fire on materially different events, and an entry is launched by whichever
comes first:

  1. THE BUDGET READS FRESH -- `session_pct <= 10`. A rolling five-hour window
     that has just rolled has no reset time at all, so a barely-touched budget
     counts as due on its own. This gate fires on a quiet account whether or not
     anything ever hit a limit.
  2. THE WINDOW ROLLED OVER -- `now >= session_reset_at + 20s`. This fires when
     the five hours are up, whatever the budget then reads.

Both of the entries run on 2026-09-12 took a different gate: the first fired on
the reset epoch (10:10 had passed), the second on a 4% budget. The log now says
WHICH, so a launch can be explained after the fact:

    schedule lane-27-storage.md: launched ➥27-storage (pane %401) type=work
      slug=27-storage -- due: the session window rolled over at 10:10

A budget reading older than WATCHDOG_USAGE_STALE minutes (default 180) cannot
fire gate 1 -- the bucket refills over five hours, so a three-hour-old
percentage says nothing about now. The reset EPOCH is exempt: it is an absolute
moment and stays true however old the row carrying it is.

## Every pending entry says why it has not fired

The watchdog writes a verdict per pending entry every pass, to
`~/.local/state/claude-watchdog[-suffix]/sched-why.tsv`:

    due | waiting | blocked | stalled   +   the sentence that explains it

`stalled` means it cannot be judged at all and will not resolve on its own.
That case used to be SILENT and PERMANENT: an empty `session_pct` was coerced to
100 (failing gate 1) and an empty `session_reset_at` failed gate 2, so an
unreadable usage cache made every `at: reset` entry undue forever, with no log
line and no error. Now it is named, it turns the row red in the dashboard's `s`
view, the reason is printed under the table, and the watchdog asks for a fresh
`/usage` probe (at most one per quarter hour) to clear it.

## `after: <slug>[, <slug>...]` -- run this one only when those have finished

    after: 27-storage
    after: 24-c1-schema, 24-c2-rows, 24-c3-ui     (comma or space separated)

The entry is held until EVERY named lane is done. "Done" means, in order:

  * its handover has been marked done -- moved into `handovers/done/` by
    `handover.sh done <slug>`, which is the lane saying so itself; or
  * a window the tree knows about has EXITED without leaving an open handover:
    the work is over whether or not it went well.

An OPEN handover means the lane is still running -- that file is written early
and lives until it is marked done. A dependency nothing has ever launched holds
the entry too, and says so.

The list is what an orchestrator needs: "integrate the four lanes" is ONE entry
waiting on four, not four entries in a chain -- and a chain would also serialise
work that ran in parallel. The verdict names the first lane still holding and
how many are left, because that is the one to act on:

    blocked: waiting for 2 of 3 -- next: 24-stars, handover open 31m ago,
    not marked done (handover.sh done 24-stars)

`claude-watchdog.sh --check` prints the per-lane breakdown underneath when there
is more than one. A slug naming the entry's OWN lane is refused from any
position: it can never finish first.

There is deliberately NO TIMEOUT. A dependency that gives up and runs anyway is
worse than one that waits, and a wait is visible in three places: `--check`, the
WHY line under the dashboard table, and one log line when the verdict changes.
Editing or deleting the entry is the escape hatch.

## `stranded` -- nothing is ever going to touch that window

Not a field: a STATE the watchdog publishes for a window, beside `working`,
`idle`, `limited` and `due`. A scheduled window (its name starts with `➥`) is
called `stranded` instead of `idle` when all five of these are true:

  * it is idle -- not mid-turn;
  * it has been idle for at least `WATCHDOG_STRANDED` minutes (default 120);
  * it has an OPEN handover -- `handovers/STATUS-<slug>.md`, not one in `done/`,
    so there is unfinished work;
  * and NO pending entry in this folder names it: not its slug, not the
    `resume-<slug>.md` the dashboard's "Schedule ➥resume" writes, and not an
    `after:` waiting on it.

`idle` is a fact about the last turn -- the same word for a lane that finished
ten minutes ago and for one that stopped mid-phase three days ago with its
handover half-written. MEASURED: four lanes sat at `idle 3d` with open handovers,
nothing pending named any of them, and nothing anywhere said so.

IT IS A FACT SHOWN TO A HUMAN, NEVER A TRIGGER. It is derived only from `idle`,
and the restart path only ever acts on `due`, so a stranded window is never
prompted by it; the cure is to write an entry for it (or mark the handover done).
`WATCHDOG_STRANDED=0` turns it off. One log line when a window becomes stranded
and one when it stops being stranded -- not one per pass.

## `parent: <slug>` -- draw this window under that one

tmux has no window hierarchy: windows are a flat indexed list, with no parent to
set and nothing to collapse. So the tree is DATA (the scheduler keeps
`tree.tsv`) plus a VIEW (the dashboard renders it, and `t` there collapses a
subtree).

`parent:` is usually unnecessary. It is DERIVED from `window:` when that names a
window the scheduler itself opened, because the window a new one is inserted
after is in practice the window it was launched from. `window: Plan4` -- a
hand-made window -- leaves the new entry a root, as before.

What the flat list can honour, it does: the depth is carried by the name
(`➥lane`, `➥➥child`, `➥➥➥` below that), and a child is inserted after the LAST
window of its parent subtree, so a family stays contiguous as siblings arrive.

    claude-watchdog.sh --tree     what the tree currently holds

Check one entry, or all of them, without launching anything:

    claude-watchdog.sh --check                 every entry
    claude-watchdog.sh --check lane-27-storage one entry, resolved in full

## The slug is the lane's name, in four places at once

The slug names the tmux window, the handover file, the `handover.sh done <slug>`
the worker is told to run, and the entry in the scheduler's tree. It is derived
from `title:` by replacing everything outside `A-Za-z0-9._-` with `-` and cutting
to 22 characters -- so a title that reads like a sentence becomes a slug that
does not look like the lane you had in mind:

    title: 27-storage wave 2   ->   slug 27-storage-wave-2

That happened. The lane's own brief said `handover.sh path 27-storage`, the
footer the scheduler appended said `27-storage-wave-2`, and the result was two
handover files for one lane with nothing watching the one that was written.

So: set `slug:` explicitly whenever the title is not already a slug. It wins over
the title. The scheduler also

  * WARNS when a title does not survive the derivation unchanged -- in the log,
    in `claude-watchdog.sh --check`, and as a yellow note on the row in the
    dashboard's `s` view (the SLUG column shows the resolved answer); and
  * renders the resolved slug and the full handover path INTO the pasted body,
    above everything else, stating that it wins over anything the brief says.

A brief and the tooling can no longer disagree about what a lane is called.

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
STATUS-<slug>.md into the account's handovers/, and `handover.sh done <slug>`
moves a finished one into done/. The SLUG, never the tmux display name: a
scheduled window is called ➥<slug>, and building a path from the display name
would ask for STATUS-➥lane.md while the same window's own footer told the worker
STATUS-lane.md. Two accounts working one repo would otherwise
overwrite each other's STATUS file without a word.
""")
made.append("README.md")

print("schedules dir:", BASE)
print("created:", ", ".join(made) if made else "(nothing - all files already present)")
