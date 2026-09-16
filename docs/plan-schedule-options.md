# Plan: schedule options (checkboxes) and the orchestrator question

Status: DRAFT for review, 2026-09-16. Nothing here is implemented. The one
artefact that exists is the prepopulated settings file at
`~/.config/muxtopus/options.md`, which nothing reads yet.

## 0. The question first: should muxtopus contain "such an orchestrator"?

The orchestrator that ran the v1.13 lanes (`v113-orchestrator`) is a Claude
window doing two different jobs:

1. **Judgment** — split a plan into lanes, write their briefs, lock forks,
   integrate the handovers, write the CHANGELOG. This needs a model.
2. **Liveness** — notice a lane stopped, resume it after a reset, pause it
   before the weekly limit, wake up when everything is done. This needs a
   clock and a file watcher.

It did job 2 with a persistent `Monitor` shell loop that emits only on a
STATE CHANGE. Measured on 2026-09-16: the four lanes settled into one state at
15:44 on Sep 12 and stayed there, so the loop emitted nothing for 3½ days; the
first change it saw (a footer redraw) woke the orchestrator, which broadcast a
PAUSE to four lanes — four turns, 12% of the weekly Fable budget, for a message
that said "do nothing".

**Verdict: put job 2 in muxtopus, keep job 1 in a Claude window, and make the
window STOP between the two.** Muxtopus already has most of the liveness
primitives — `after:`, `parent:`, the tree, open/done handovers, wind-down
directives, `--check`, a heartbeat — and it is a deterministic 30-second loop
that costs no tokens. What it lacks is three small things:

| Gap | Fix | Size |
|---|---|---|
| `after:` takes one slug | accept a comma list; "all of them done" | S |
| a lane the watchdog wound down is never resumed by anything | when a lane is idle with an OPEN handover, was wound down by the watchdog (band 2 in `wound`), and the budget is back, write `resume-<slug>.md` for it — exactly what the menu's "Schedule ➥resume" does by hand (`act_schedule_resume`), driven from the daemon; opt-in (`WATCHDOG_AUTO_RESUME=1`), one per lane per reset | M |
| the dashboard says `idle 3d` where it should say *nothing will ever touch this* | STATE `stranded` (red) for a ➥ lane idle > N with an open handover and no pending entry naming it | S |

With those, the orchestrator pattern becomes a **prompt sentence** (the
`orchestrate` checkbox below): *write one schedule entry per lane with
`window:` = this window, write one more entry with `after: <every lane>` whose
body says "integrate", then END YOUR TURN.* The window spends zero tokens
waiting, cannot miss a wake, and the resume is a scheduler launch with a log
line — not a Monitor event nobody can see. So: yes, useful, but as a
**pattern muxtopus enforces**, not as a Claude process living inside muxtopus.

## 1. The feature: an options table when creating a schedule

Today `c` in the `s` view goes: type → (template) → editor. Add one step:

    type → template → OPTIONS TABLE → editor

The table is a submode like the space menu (`menu_entries` / `menu_move` /
`menu_activate` in `deck_status.py`): `↑↓` pick, `space` toggle, `enter`
continue into the editor, `esc` continue with nothing ticked. An option that
`ask`s for a value opens the existing text prompt (`self.prompt`) on toggle;
one with `choices` opens the existing picker (`self.picker`). Nothing new in
the input layer.

```
╭─ options · work-20260916-0612 ──────────────────────── space toggle · enter continue · esc skip ─╮
│  CONTRACT                                                                                        │
│ ▸[x] questions go to a file        nobody is watching: QUESTIONS-{{SLUG}}.md, recommended answer │
│  [x] one commit per phase          [feat] <phase>: summary + body + attribution trailer          │
│  [x] no push, no PR                the orchestrator integrates                                   │
│  [x] /low-priority on a limit      spends the WEEKLY budget instead of parking                   │
│  [x] verify by firing it           reasoned-about is not verified                                │
│  [ ] act as the expert             the professional in the relevant role                         │
│  WINDOWS                                                                                         │
│  [x] spawn sub-windows             schedule entries under this window, never a monitor loop      │
│  [ ] parallel lanes: —             asks for a number                                              │
│  [x] orchestrate, don't babysit    spawn, end the turn, get resumed by after:                     │
│  MODEL                                                                                           │
│  [ ] model: (account default)      header field → claude --model                                 │
│  [ ] effort: (auto)                header field → claude --effort                                │
│  [ ] route subtasks by model       a cheaper model for mechanical steps                           │
│  OUTPUT                                                                                          │
│  [ ] publish an Artifact           the report as a claude.ai page, link in the handover          │
│  [x] session link in PRs           https://claude.ai/code/session_… in every PR body             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

Each ticked option does ONE of two things:

* **a line** — one sentence appended to the prompt body, one per line, under a
  `## Options` heading, in the order of the file; or
* **a header field** — `model:`, `effort:` — which the launcher already (or
  will) pass as `claude --model` / `claude --effort`. `model:` exists since
  65cde72; `effort:` is the same three lines next to it.

The header also records `options: questions, phases, lanes=3, …` so the table
can be reopened on an existing pending entry (`o` in the `s` view) with its
boxes pre-ticked. **Source of truth for the table is the header; the
`## Options` section is regenerated from it on save and the rest of the body
is never touched.** A hand-edited sentence in that section is overwritten on
the next table save — the escape hatch is to move the sentence above the
heading, or to edit the sentence in `options.md` where it came from.

## 2. Placeholders: resolved at PASTE time, not at create time

The slug is not known when the table is shown (the title is empty until the
editor). So the sentences are written with placeholders and `sched_compose`
(the one function that renders the paste, shared with `--check --body`)
substitutes them over the WHOLE body:

    {{SLUG}}       27-storage
    {{WINDOW}}     ➥27-storage
    {{HANDOVER}}   /home/deck/.code/handovers/STATUS-27-storage.md
    {{QUESTIONS}}  /home/deck/.code/handovers/QUESTIONS-27-storage.md
    {{SCHEDULES}}  /home/deck/.code/schedules
    {{CWD}}        the entry's cwd
    {{PARENT}}     the entry's parent slug, or empty
    {{VALUE}}      the value an `ask:` option collected (only inside that line)

A side benefit: hand-written bodies get the same placeholders, which is the
style `_rules.md` already uses (`{{PORT}}`, `{{SLUG}}`, `{{BRANCH}}`).
`--check --body` shows the substituted paste, so a wrong placeholder is
visible before anything launches.

## 3. The settings file

`~/.config/muxtopus/options.md` — one block per option, blank-line separated,
the same `key: value` header syntax as a schedule file, `#` comments allowed.
Per account: `~/.config/muxtopus/profiles/<name>.options.md` is read AFTER it
and overrides or adds by `key`. Seeded by `install.sh` the way templates are
(only if missing — it is the user's file, never rewritten).

    key: questions            # the id: in `options:` and in the log
    group: contract           # table section
    label: questions go to a file
    hint: nobody is watching: QUESTIONS-{{SLUG}}.md, recommended answer
    default: on               # ticked when the table opens
    line: Nobody is watching this window: do not ask questions. …

Variants:

    set: model                # writes a header field instead of a line
    choices: opus-5, fable-5-1, sonnet-5, haiku-4-5
    ask: number               # collects {{VALUE}} on toggle (number | text)
    types: work               # only offered for this type (plan | work)

Rules the reader enforces (and `--check` reports): `key` unique and
`[a-z0-9-]+`; exactly one of `line:` / `set:`; `set:` needs `choices:`;
an `ask:` line must contain `{{VALUE}}`. A broken block is shown in the
table greyed with its reason, never silently dropped — the schedule view's own
rule for corrupted entries.

The prepopulated file is at `~/.config/muxtopus/options.md`. Its sentences
are lifted from what you actually write: `core/plans/lanes/_rules.md`, the
four lane briefs, `lane-27-storage.md`, `release-1-11-0.md`, the
`muxtopus-improvements` brief, the plan templates, and your typed prompts
from Sep 5–16 ("start opus agents where it can handle", "spawn sub windows
from this one", "force low-priority if hitting session limits", "do as a
professional would", "verify with a real scheduled entry end to end").

## 4. Worth it? Per checkbox

| Option | Kind | Worth | Why |
|---|---|---|---|
| questions → file | line, default on | HIGH | in every brief you write; already the plan-template contract, this makes it universal |
| one commit per phase | line, default on | HIGH | `sched_compose` hardcodes a version of it for `work`; moving it here makes it editable and the hardcoded footer can go |
| no push, no PR | line, default on | HIGH | every lane brief says it; the one entry that must push (`release-1-11-0`) unticks it |
| /low-priority on a limit | line, default on | HIGH | asked twice; encodes the account's answer to a banner |
| verify by firing it | line, default on | HIGH | your own words in the muxtopus brief |
| act as the expert | line | MED | said often in interactive prompts, rarely in briefs |
| spawn sub-windows | line, default on | HIGH | asked three times; the sentence names the MECHANISM (write a schedule entry) so the window does not invent a monitor loop |
| parallel lanes: N | ask, line | MED | only meaningful with sub-windows; cheap |
| orchestrate, don't babysit | line | HIGH | the fix for the 12%; useless without the `after:` list (§0) |
| model | header → `--model` | HIGH | exists; the table just surfaces it |
| effort | header → `--effort` | HIGH | three lines in the launcher; `effortLevel` is already in settings.json so the flag is real |
| route subtasks by model | line | MED | a session cannot switch models mid-turn; this is about subagents and `claude -p --model` calls, which the sentence says |
| publish an Artifact | line, off | LOW-MED | fine for reports and audits; noise for a lane |
| session link in PRs | line, default on | LOW cost | one line; the harness already prints the URL in its attribution reminder |
| measure the base (theprototype) | line, off | project | kept as the example of a PROJECT line — shows the file is yours to extend |
| stop at a time | ask, line | MED | "work until the weekly reset then pause" — your Sep 12 brief |

Overall: **worth building**, mostly because five of these you retype into
every brief and one of them (orchestrate) prevents the failure we had this
week. The cost is one submode in the dashboard, a reader for one file, a
placeholder pass in `sched_compose`, and `effort:`. What is NOT worth
building: a new input layer, a GUI editor for the sentences (it is a text
file), or any option whose sentence a Claude window cannot act on (e.g. "use
account X" — the account is the tmux session, not the prompt).

## 5. Implementation, one commit per phase

1. **options reader** — `muxconfig.py`: `options(profile) -> list[dict]`,
   validated as in §3; `claude-watchdog.sh --options` prints them (for a
   reader with no dashboard, and for the sandbox tests).
2. **placeholders in `sched_compose`** — the §2 table, applied once over the
   composed paste; `--check --body` shows the result. `{{SLUG}}` etc. in the
   existing `[muxtopus]` header lines stay literal text (they are already
   resolved). Sandbox test: an entry with every placeholder, compared byte
   for byte.
3. **`effort:` header** — beside `model:` in the launcher and in `--check`.
   Validate against what `claude --effort` accepts at that version
   (`low|medium|high|max` today; "auto" = omit the flag).
4. **the table** — `deck_status.py`: `self.options` submode; `_create_tpl`
   → `_create_options` → `_create_write` writes the header fields, the
   `options:` line, and the `## Options` section; `o` in the `s` view reopens
   it on the selected pending entry and regenerates only that section.
5. **`after:` list** and **`stranded`** — the two liveness gaps from §0.
   `after: a, b` = all done. `stranded` = ➥ lane, idle > `WATCHDOG_STRANDED`
   (default 120 min), open handover, no pending entry whose `after:`/slug
   names it.
6. **auto-resume (opt-in)** — `WATCHDOG_AUTO_RESUME=1`: for a `stranded` lane
   the watchdog itself wound down (band 2 in `wound`), write
   `resume-<slug>.md` (`resume-status` template, `window:` = the lane's
   parent, `after:` empty) once per lane per reset epoch, recorded in
   `resumed.tsv`. A line per launch in the log. Default OFF — an automatic
   resume is a turn, and this week showed what four unrequested turns cost.
7. **seed + docs** — `install.sh` seeds `options.md` if missing;
   `setup-schedules.py` documents `options:`/`effort:` in the schedules
   README; main README gets the §0 verdict in three sentences.

Verify the way the muxtopus brief demanded: create an entry through the
table, `--check --body` it, let the daemon fire it into a sandbox tmux
session, read the paste in the pane, delete it. Phase 6 gets the same with a
wound lane faked by a `wound` row.

## 6. Forks, with the answer I would take

1. **Regenerate the `## Options` section vs never touch the body after
   create.** Regenerate (header is the truth). Otherwise reopening the table
   is a lie: it shows boxes that no longer match the text.
2. **Default-on options for `plan` entries too?** Yes for `questions`, no
   for the git ones (`types: work` on those). A plan writes files, not
   commits.
3. **Where the section goes: top or bottom of the body?** Bottom. The body
   starts with the task, as every brief does; the contract follows.
   `sched_compose`'s own footer then becomes redundant and is dropped when
   `phases` is on (phase 4 keeps it when the option is off, for old entries).
4. **Auto-resume default.** Off. See phase 6.

## 7. Not doing

* Moving windows into a parked tmux session to hide a subtree — still a
  separate decision (QUESTIONS-muxtopus-improvements §3).
* A Claude process owned by muxtopus. The dashboard and daemon stay
  token-free; a model is only ever spent by a window the user scheduled.
* Account routing ("run this lane on work"). The account is the tmux session
  the entry lives in; that is what the per-account schedules folder is for.
