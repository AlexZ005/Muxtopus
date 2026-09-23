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
answer. Write it into {{QUESTIONS}} -- that placeholder is replaced with the
real path when this window is launched, and it is the file the dashboard's
handovers tab reads -- and continue with your own recommendation, marking
that decision as provisional in the plan.

One fork per numbered item or `## ` heading, at the start of a line.
Options are lettered in brackets, the recommended one says so:

    1. **<the question, in a sentence>**
       - **(a) RECOMMENDED: <option>**  <one-line why>
       - (b) <option>
       - (c) <option>

The dashboard offers those options as rows with the recommended one already
picked, and writes the answer back as one line at the end of the fork:

    **Answer (user, <date>):** (a) - <note>

so a line starting `**Answer` is what "this fork is settled" looks like,
whoever wrote it. Free-text answers are always possible -- someone typing
one is the normal case, not a failure.

WHEN EVERY FORK IS ANSWERED the file gets a line matching `ANSWERED` (the
dashboard writes `**ANSWERED <date>**`, and a hand-typed one counts). That
marker is what tells `handover.sh done` the file may travel into done/ with
this lane's handover; without it the file stays put and keeps asking.

ADDING A FORK TO A FILE THAT IS ALREADY MARKED ANSWERED MEANS DELETING THE
MARKER LINE. The marker is a claim about the whole file, and a new fork
under an old marker is a question nobody will ever be shown.
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
user, record it in {{QUESTIONS}} with your recommended answer, in the format
the Questions contract describes, and proceed with the recommendation.
""",
    # THE FOUR ORCHESTRATOR TEMPLATES are `type: work` templates, unlike every
    # one above: a work entry gets the footer that runs `handover.sh done`, and
    # an orchestrator is finished only when that runs. They are TWO SHAPES, not
    # one text with a fork -- a wave owns lanes, a sweep owns nothing -- because
    # a fork in a paste is a sentence the model evaluates on every run at full
    # price, and a sweep that reads "if you are a wave, write one entry per
    # lane" is one bad turn from spawning lanes it does not own.
    #
    # EXECUTOR PLACEHOLDERS ONLY. Every {{NAME}} here is resolved by
    # sched_subst when the paste happens -- including {{HANDOVERS}} and
    # {{STATE}}, the two added beside these templates. resume-status.md above
    # carries {{STATUS_FILE}}, which only the Python writers fill; a template
    # used from a hand-written or self-written entry must never lean on that.
    #
    # WHAT RESOLVES WHEN. A {{NAME}} in orchestrate.md resolves in the
    # ORCHESTRATOR's paste, to the orchestrator's values -- so a lane's brief
    # cannot carry a {{SLUG}} meaning the lane. That is why step 3 has the
    # orchestrator spell the lane's own slug and paths out, built from
    # {{SLUG}}-<lane> and {{HANDOVERS}}, which ARE right in its paste. lane.md
    # and integrate.md are pasted into the lane's own window (`template: lane`),
    # so there {{SLUG}} and {{PARENT}} mean the lane and its orchestrator.
    "orchestrate.md": """\
You are a wave orchestrator: {{SLUG}}. You do no lane work in this window. You
work on this account only: its tmux session, its windows, {{SCHEDULES}} and
{{HANDOVERS}}.

1. Read the task below and the plan files it names. Decide the lanes: each an
   independent unit a fresh window can finish from its brief alone.
2. FIRST write {{HANDOVER}}: the lane list, each lane's slug, what it owns,
   what it depends on, and how to resume this plan if this window is gone.
   This file is the plan; the window is not.
3. One entry per lane, {{SCHEDULES}}/{{SLUG}}-<lane>.md: type: work, a past
   at:, slug: {{SLUG}}-<lane>, window: {{WINDOW}}, parent: {{SLUG}}, cwd:,
   permission-mode:, after: <the full slugs of the lanes it needs>,
   template: lane, and a brief that stands alone. Slugs start with {{SLUG}}-
   so no other orchestrator's lane can share a file or a handover. Every brief:
   - OPENS with its identity, spelled out, because a placeholder you write here
     resolves to YOUR values, not the lane's: "Read this brief and execute it
     end to end. Your slug is {{SLUG}}-<lane>; your handover is
     {{HANDOVERS}}/STATUS-{{SLUG}}-<lane>.md; your questions file is
     {{HANDOVERS}}/QUESTIONS-{{SLUG}}-<lane>.md."
   - carries a "Facts measured by the planner" section: what you already read,
     each with its receipt (a count, a file, a date), so no lane re-derives it.
   - cuts the work into phases sized S/M/L, each with the test that proves it.
   - ends with a Finish line that says exactly what done is for that lane:
     which tests are green, whether it pushes, a PR to which base, and whether
     it merges or never merges.
4. ONE more entry, {{SCHEDULES}}/{{SLUG}}-integrate.md: type: work, a past at:,
   slug: {{SLUG}}-integrate, after: <every lane>, window: {{WINDOW}},
   parent: {{SLUG}}, template: integrate.
5. `claude-watchdog.sh --check {{SLUG}}-` and fix every warning. Then END
   YOUR TURN. Do not wait, poll or monitor. The footer below says to run
   `handover.sh done {{SLUG}}` when the whole item is finished: the whole
   item is finished when the integrate window says so, and it runs that.

ROUND 2 IS A NEW WAVE, NOT A RESUME. When the owner answers a preview with
fixes, write a new wave -- new lane slugs, new entries -- whose rules file
names the owner's feedback as its acceptance test, and every brief names it.
Do not resume the old lanes.

## Task
""",
    "lane.md": """\
You are lane {{SLUG}} under orchestrator {{PARENT}}. The brief below is the
whole of your job; nothing outside it is yours. Do not push, do not open a
PR, do not touch another lane's files. Keep {{HANDOVER}} current with a
"For the orchestrator" section: what the docs and changelog should say.
Where the brief below says otherwise -- a wave whose lanes push and open
PRs -- the brief wins.

""",
    "integrate.md": """\
You are the integrate step of orchestrator {{PARENT}}. If an earlier
integrate window worked this wave -- {{HANDOVER}} exists, or the plan names
one -- read its handover first and take over its worktree rather than
starting a second one. Then read {{HANDOVERS}}/STATUS-{{PARENT}}.md for the
plan, then every lane handover it lists (done/ first, then open). Merge in the plan's order, run the
verification each lane says it ran, and write what CLAUDE.md, CHANGELOG.md
and the docs should say from each lane's "For the orchestrator" section. A
lane that is open and stranded is not resumed: say so, and mark this item
done with that lane listed as OWED. Never type into an idle window that is
holding a gate (waiting for the owner's word): its wait is the point. When
done, also run `handover.sh done {{PARENT}}`.

""",
    "sweep.md": """\
You are a sweep: {{SLUG}}. You own no lanes and implement nothing. Every fact
you act on comes from a file; you never read a pane and never type into one.
You work on this account only: every path below is its own.

1. CENSUS, from files only, in this order, before deciding anything:
   - `handover.sh list` (the script the footer below names): what is owed.
   - {{STATE}}/status.tsv: every session's window, state, idle time and SAID
     (the last thing it said).
   - {{STATE}}/repos.tsv: checkouts that are dirty or ahead of their upstream.
   - {{STATE}}/tree.tsv and every pending entry in {{SCHEDULES}}: what is
     scheduled, and under which window.
   - {{STATE}}/sched-why.tsv: why each pending entry has not fired.
   If all of that says nothing is finished, nothing is unpushed, nothing is
   stranded and no question is unanswered, skip to step 6.

2. THE TRAP. Text after a `❯` in a window is Claude Code's dimmed placeholder
   hint, not a message someone typed. On 2026-09-20 twelve such lines each
   looked like pending input; one read "close the PR and delete the remote
   branch" for a PR that had been merged. Judge what a window owes from its
   handover and its repo, never from its prompt line, and never re-send one.

3. ACT on what is finished, in this order, and only this:
   - a checkout that is ahead: push it. Then `gh pr list` in THAT repo only;
     if the branch has no PR and its lane's handover says it is done, open one
     with the handover's summary as the body and say so in the table.
   - a PR whose checks are green and whose lane is done: merge it, unless it
     is a release PR (release/*, or one that bumps VERSION) -- those are the
     owner's. Never run release.sh, never tag, never publish.
   - a lane whose handover is open and whose window is gone, or is `stranded`:
     do not resume it. List it under "for you" with its handover's next step.
   - an unanswered QUESTIONS file: list its first fork under "for you".
     Do not answer it.
   repos.tsv only sees this machine: a PR opened from another machine on a
   branch this box has not fetched is missed. If the owner asked for it, run
   `gh pr list` over every repo with a remote (about ten seconds) as well.

4. CONTINUE what asked to be continued: a handover whose "next" section names
   a resumable step, and whose worktree and branch still exist, gets ONE entry
   in {{SCHEDULES}} (type: work, at: a past time, window: {{WINDOW}}, cwd: that
   worktree, template: resume-status is NOT usable from here -- write the two
   sentences yourself). A handover naming a worktree or branch that no longer
   exists is not resumable: say so under "for you" and do not guess.

5. CLOSE a window only when ALL of these hold:
   - its slug's STATUS-<slug>.md is in {{HANDOVERS}}/done/;
   - it is not the window holding an unreleased release;
   - it is not a dashboard, a plain shell, or {{WINDOW}};
   - no pending entry names it in window:, parent: or after:.
   Close by window id from tree.tsv (`tmux kill-window -t @N`), never by name:
   names repeat. An unanswered QUESTIONS file does not block closing; the
   file outlives the window and `handover.sh list` keeps showing it.

6. REPORT. One table -- window | state | owes | done here | for you -- then
   `claude-notify.sh "sweep {{SLUG}}" "<three lines: acted / for you / next>"`.
   If changes/ in the muxtopus checkout has unreleased fragments, say how many
   and stop there: the owner decides releases.

7. NEXT. If nothing is open anywhere -- no open handover, no pending entry,
   repos.tsv empty -- write NO next entry: say so in the table, in the phone
   line and in {{HANDOVER}}, and end the chain; the owner starts the next one
   with `c`. Otherwise write {{SCHEDULES}}/sweep-<MMDD>.md, today's date, with
   -b, -c ... added when that slug is {{SLUG}} or already has an entry or a
   handover: type: work, kind: sweep, template: sweep, slug: the same name,
   cwd: {{CWD}}, at: the cadence an option below gives, or `reset` when none does -- NEVER
   sooner -- and the model:, effort:, permission-mode: and options: lines of
   the entry that launched you. Its body is that entry FILE's `## Options` section,
   copied from the file, not from this paste: the file still holds its
   placeholders, and this paste has your own paths in their place. Then end
   your turn.

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
    template: resume-status        (optional; a file in templates/, pasted before the body)
    model: opus                    (optional: fable | opus | sonnet | full id; default from settings.json)
    effort: high                   (optional: low | medium | high | xhigh | max -> claude --effort)
    permission-mode: bypassPermissions   (optional -> claude --permission-mode)
    watchdog: off                  (optional: opt this session out of the watchdog's restarts)
    monitor: off                   (optional: opt this session out of wind-downs)
    rc: on                         (optional: send /rc once the window is ready; default from Settings)
    options: questions, phases     (written by the dashboard's options table; see below)
    kind: sweep                    (written by the dashboard's c ▸ orchestrate; see below)
    status: pending                (the executor rewrites this)
    created: 2026-09-06 09:55
    launched:
    ---
    the prompt body that gets pasted into the new window

The launched window is named with a leading arrow and appears right after
`window:` when that window exists.

A template is pasted first, then the body, then (for work) the handover
footer -- for either type. resume-status is still a PLAN template in practice:
its {{STATUS_FILE}} is filled in by the dashboard when it writes the entry, not
by the executor, so an entry that names it by hand pastes that placeholder
literally (and is warned about it).

## Placeholders, resolved when the body is PASTED

The body is not a literal string. Nine names are substituted the moment the
window opens, over the template, the body and the work footer -- never over the
`[muxtopus]` identity lines at the top, which are built from the resolved values
already:

    {{SLUG}}       27-storage
    {{WINDOW}}     the tmux window name: 27-storage
    {{HANDOVER}}   <handovers>/STATUS-27-storage.md
    {{HANDOVERS}}  <handovers>, the folder every lane's handover is in
    {{QUESTIONS}}  <handovers>/QUESTIONS-27-storage.md
    {{SCHEDULES}}  this folder
    {{STATE}}      the watchdog's state folder: status.tsv, repos.tsv, tree.tsv, sched-why.tsv
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

`kind: wave` or `kind: sweep` is the same kind of line: written by the form's
third pick (`c` > orchestrate), read by the form (`o` offers the orchestrate
options again), ignored by the executor. The entry is still `type: work`.

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

## `watchdog: off` and `monitor: off` -- applied by the launcher

The same two opt-outs as the dashboard's space menu (`--optout`,
`--monitor-optout`), for a window that should never be restarted or wound
down. Only `off` means anything (any case); any other value, or no line, is
the default: covered.

They are header fields rather than something written at create time because
the opt-out files are keyed by SESSION ID, and a session id does not exist
before launch -- claude mints it at startup. So the launcher applies them:
once the prompt is up it finds the session file naming its own pane, appends
the id, and logs `session <id> opted out of the watchdog|monitor`. If no
session file names the pane within ~5s it logs that and leaves the window
watched. `--check` prints both as `covered (default)` or `opted out at launch`.

## `rc: on` / `rc: off` -- also applied by the launcher

`rc: on` sends `/rc` (remote control) to the new window once it is ready, so
the session can be reached from claude.ai or the phone without anyone typing
it. It is the same shape as the two opt-outs above, and applied by the
launcher for the same reason: there is no session before launch to send
anything to. The launcher waits for the prompt (answering the trust dialog on
the way), sends `/rc` BEFORE pasting the body -- after the paste the window is
working, and a `/rc` typed then is queued as a message to the model instead of
run -- closes anything `/rc` leaves holding the keyboard with Escape (logged),
and only then pastes.

Unlike `watchdog:`/`monitor:`, BOTH values mean something, because there is a
default to override: `DASHBOARD_NEW_RC` (esc ▸ Settings ▸ `Send /rc to a new
window`, off unless set). With it on, EVERY new scheduled window gets `/rc`
-- hand-written entries and the dashboard's `c` alike -- except one whose
entry says `rc: off`. Any other value is ignored and the default applies.
`claude-watchdog.sh --check <entry>` prints the resolved value and where it
came from; the launch line in the log ends in `rc=on` when it was sent.

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

    schedule lane-27-storage.md: launched 27-storage (pane %401) type=work
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

A LANE THAT RAN, WAS MARKED DONE AND RAN AGAIN has BOTH files, and the order
above is why that reads as finished: `done/STATUS-<slug>.md` is tested first,
so every `after: <slug>` is satisfied the moment the earlier run's record
exists, whatever the open file says. That is not a bug to work around -- it is
what "done" has always meant here -- but it is a trap, so the dashboard's
handovers tab draws such a row `open` with a yellow warning and says in words
which file is doing the releasing. `handover.sh reopen <slug>` moves the old
record back out if the hold was supposed to still be in force.

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
`idle`, `limited` and `due`. A scheduled window (one the tree knows) is
called `stranded` instead of `idle` when all five of these are true:

  * it is idle -- not mid-turn;
  * it has been idle for at least `WATCHDOG_STRANDED` minutes (default 120);
  * it has an OPEN handover -- `handovers/STATUS-<slug>.md`, not one in `done/`,
    so there is unfinished work;
  * and NO pending entry in this folder names it: not its slug, not the
    `resume-<slug>.md` the dashboard's "Schedule resume" writes, and not an
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
(the tree's own parent column, drawn by `t`), and a child is inserted after the LAST
window of its parent subtree, so a family stays contiguous as siblings arrive.

    claude-watchdog.sh --tree     what the tree currently holds

Check one entry, or all of them, without launching anything:

    claude-watchdog.sh --check                 every entry
    claude-watchdog.sh --check lane-27-storage one entry, resolved in full

## templates/ -- prompt bodies, seeded once and then yours

    roadmap-plan.md     plan  an autonomous roadmap, forks to the questions file
    hardening-audit.md  plan  an audit that writes findings and a roadmap
    blank-plan.md       plan  the two contracts and nothing else
    resume-status.md    plan  continue from a STATUS file
    orchestrate.md      work  a wave: plan, one entry per lane, one integrate
                              entry, then end the turn
    lane.md             work  a lane a wave spawned (the wave names it with
                              `template: lane`)
    integrate.md        work  the wave's integrate step: every lane handover,
                              merged in order, then the orchestrator marked done
    sweep.md            work  the recurring sweep: a census from state files,
                              act on what is finished, report, write its own
                              next entry

THE LAST FOUR ARE `type: work` TEMPLATES. An orchestrator is finished only
when `handover.sh done` runs, and only a work entry carries the footer that
says so. They use the executor's placeholders only -- `{{HANDOVERS}}` (the
handovers folder) and `{{STATE}}` (this account's watchdog state directory)
among them -- never resume-status.md's `{{STATUS_FILE}}`, which only the
dashboard fills. The dashboard's create form copies a template into the body;
a work entry can also name one with `template:` (the sweep's next entry does).

This script writes a template only when its file is ABSENT: edit them freely.
Delete one to get the shipped text back on the next run.

## The slug is the lane's name, in four places at once

The slug names the tmux window, the handover file, the `handover.sh done <slug>`
the worker is told to run, and the entry in the scheduler's tree. It is derived
from `title:` by replacing everything outside `A-Za-z0-9._-` with `-` and cutting
to 32 characters -- so a title that reads like a sentence becomes a slug that
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
scheduled window is called <slug>, and a window from an older release still
carries ➥ markers -- building a path from the display name
would ask for STATUS-➥lane.md while the same window's own footer told the worker
STATUS-lane.md. Two accounts working one repo would otherwise
overwrite each other's STATUS file without a word.
""")
made.append("README.md")

print("schedules dir:", BASE)
print("created:", ", ".join(made) if made else "(nothing - all files already present)")
