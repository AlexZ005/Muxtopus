# Plan: handovers and questions, visible in the dashboard

Status: PLAN for review, 2026-09-17, lane `handover-visibility`. Nothing here is
implemented. Line numbers are deliberately absent: locate by symbol.

Read before this: `deck_status.py` (`build_sched`, the `view == "sched"` branch of
`main()`, `handover_state`, `read_tree`, `live_windows`), `claude-watchdog.sh`
(`sched_dep_state`, the stranded check, `sched_compose`'s `{{QUESTIONS}}`),
`handover.sh`, `~/.code/schedules/README.md`, and `docs/plan-dashboard-menus.md`
(the sibling lane `dash-menus-settings`, called "the sibling" below).

## 0. What was measured while reading, that the brief did not have

1. **The arrows ARE free in the `s` view.** `main()`'s sched branch ends with
   `if key in ("LEFT", "RIGHT", "t"): continue` -- swallowed on purpose so they
   cannot fold a tree row nobody can see. Nothing else binds them there, and
   the submodes (prompt, confirm, picker, options, menu) are checked before the
   view and own the keyboard while open. The brief's claim holds; tabs are cheap.
2. **Unanswered questions are not just unsurfaced, the one panel that tries is
   looking in the wrong folder.** `build_sched` globs `QUESTIONS_DIR`
   (`MUXTOPUS_QUESTIONS_DIR`, default `~/.code/theprototype-app/core/plans`).
   That folder held ZERO `QUESTIONS-*.md` at 08:50 and ONE a few minutes later
   (`QUESTIONS-25-late.md`, a lane still on the old contract) -- so the legacy
   folder is LIVE, not dead, and must keep being read. The three others are in
   `~/.code/handovers/`, which is where `{{QUESTIONS}}` has pointed since the
   placeholders landed. Meanwhile `setup-schedules.py`'s `QUESTIONS_CONTRACT`
   still tells plan sessions `core/plans/QUESTIONS-<topic>.md`. Two conventions,
   the dashboard reads one of them.
3. **The dashboard and the watchdog disagree on a re-run lane.**
   `sched_dep_state` tests `done/STATUS-<slug>.md` FIRST (done wins, `after:`
   is satisfied); the stranded check needs open AND NOT done;
   `deck_status.handover_state` tests the open file first. A lane that ran,
   was marked done, and runs again has both files: the watchdog says finished,
   the dashboard says open. `handover.sh done` also stamps a second finish as
   `done/STATUS-<slug>-<YYYYmmdd-HHMMSS>.md`, a name nothing parses today.
4. **There is no convention for "answered".** Of the three QUESTIONS files one
   carries a hand-typed `**ANSWERED 2026-09-17: ...` line, one records
   "answer taken" per fork (provisional, never reviewed), one has nothing.
   `handover.sh done` moves STATUS only; QUESTIONS files stay forever.
5. **The schedule table has no viewport.** `done/` holds 13 files and grows by
   one per lane. A handover list with done shown will outgrow a 24-row pane
   within days; Rich crops a too-tall frame from the bottom, silently.
6. **The sibling is rewriting the same code right now**: `menu_open` becomes a
   `self.menu` dict with kinds, space in the `s` view opens a menu built from
   `_sched_sel()`, `muxsettings.py` and `menulayout.py` appear. This plan is
   written against the sibling's END state and its implementation must not
   start on `deck_status.py` before the sibling lands (§7).

## 1. The shape: tabs inside `s` (a). The brief's recommendation stands.

    ╭ schedules 6 │ ▸handovers 4 open · 3 ? ─────────────── ←→ tab ╮

LEFT/RIGHT in the `s` view switch `self.sched_tab` between `"sched"` and
`"hand"`; `s`/esc still leave to the main view. The strip is the panel TITLE of
whichever table is drawn, so it costs no rows, and it carries the counts on
BOTH tabs -- `3 ?` in yellow is visible from the schedules tab whatever the
filters say. `s` always opens on schedules (today's behaviour, no surprise);
the tab is remembered for the life of the process, not on disk.

Why it wins, tested rather than assumed:

* One lifecycle, one place: entry pending -> launched -> handover open ->
  questions -> done. The `s` view's launched-row WHY line ALREADY reads the
  handover (`handover_state`) -- the view is half a handover view today.
* It reuses what exists: the table look, the why panel slot, the footer, the
  notice line, `pending_edit`, `_submode_foot`, and the sibling's menu dict.
* The arrows are genuinely free (§0.1), so the switch costs two `if`s.

Why the others lost:

* **(b) a top-level key.** Every mnemonic is taken or about to be: `h` reads
  as help next to `?`, `q` is quit, `c` goes to the sibling's creator. It also
  needs its own view state, footer and help section for a list that is, row for
  row, the schedule list later in life. It would win only if the arrows had
  been taken; they are not.
* **(c) a toggle inside the current view.** In the main view it means handover
  rows interleaved with live sessions in a table that already carries sessions,
  lanes and extras on one cursor; 13+ done rows there is noise on the screen
  that is looked at most. In the `s` view a "toggle" between two tables IS
  tabs with worse affordance (no strip, no counts).

One thing (c) gets right is kept: the most actionable fact should not need a
view switch at all. §6 puts a `?` on the main view's session row.

## 2. The model: `muxhandovers.py` (new, pure)

`deck_status.py` is 3000 lines and the sibling is adding to it. The reader, the
state rules and the summariser are pure functions of a directory, so they live
in a new module with no Rich and no tmux, and are unit-tested without a
dashboard.

    scan(hdir: Path, legacy_qdir: Path | None) -> list[Row]
    lane_state(hdir, slug) -> (state, age)      # the ONE definition, replaces handover_state
    question_state(text) -> "unanswered" | "answered"
    summarise(text) -> (title, gist)
    forks(text) -> (count, first)               # for a QUESTIONS row
    visible(rows, show_done, show_questions) -> list[Row]
    slug_of(filename) -> (kind, slug, stamp)    # STATUS-x.md, STATUS-x-20260917-101500.md, QUESTIONS-x.md

A `Row` is a dict: `kind` (`status`|`questions`), `slug`, `state`, `path`,
`mtime`, `title`, `gist`, `stamp`, `legacy`, `shadowed`.

### 2.1 States -- the watchdog's definition, not a second one

    done        done/STATUS-<slug>.md exists            (checked FIRST, as sched_dep_state does)
    open        STATUS-<slug>.md exists, no done/ twin
    open+done   both exist: drawn `open`, flagged `shadowed` -- see below
    unanswered  a QUESTIONS file with no ANSWERED marker
    answered    a QUESTIONS file with one

`lane_state` mirrors `sched_dep_state` order exactly and `handover_state` in
`deck_status.py` becomes a call to it, so the WHY line, the new tab and
`after:` cannot disagree again. The both-files case (§0.3) is not hidden: the
row says `open` with a yellow `⚠ after: sees done`, and the detail panel says
in words that `done/STATUS-<slug>.md` from an earlier run satisfies every
`after: <slug>` right now. That is a real trap and showing it is the fix this
lane can make without changing the executor. A stamped file is a `done` row of
the same slug, labelled `(earlier run, <stamp>)`.

A mirror test (the sibling's pattern) greps `sched_dep_state` out of
`claude-watchdog.sh` and asserts the `done/` test precedes the open test, so
a future reorder on the shell side fails a Python test.

### 2.2 "Answered" (fork Q3)

RECOMMENDED: a marker line. A QUESTIONS file is answered iff some line matches
`^\W*ANSWERED\b` (so `**ANSWERED 2026-09-17: ...` -- what the user already
types by hand -- counts). `handover.sh answered <slug>` prepends
`**ANSWERED <date>** (marked from the dashboard)` under the first heading, if
no marker is there; `handover.sh unanswer <slug>` removes marker lines. The
file never moves while its lane is open, because `{{QUESTIONS}}` told the lane
that exact path and the lane reads its answers there. `handover.sh done <slug>`
additionally moves an ANSWERED `QUESTIONS-<slug>.md` to `done/` (same
never-clobber stamp); an unanswered one STAYS -- a finished lane's provisional
forks still want a look, which is precisely the `muxtopus-improvements` file
today. `answered` on a file whose lane is already done moves it at once.

The questions contract gains one sentence: adding a fork to a file already
marked ANSWERED means deleting the marker line.

### 2.3 What one row says

`summarise` takes the first non-blank line; a `#` heading is the TITLE (hashes
and `*` stripped). The GIST is the next non-blank line that is not a heading,
a fence, a rule or a table row, markdown emphasis stripped. Measured against
all 17 real files: the gist is the useful one where the title is boilerplate
(`# STATUS: dash-menus-settings` -> `Phase 0 done, stopped as instructed.`),
the title where it carries the verdict (`... — **COMPLETE**`). The row shows
the gist when the title, minus the slug and the words STATUS / Handoff /
Handover / Lane, has under 12 characters left; otherwise the title. No header
convention is imposed on lanes -- 17 files already exist without one.

For a QUESTIONS row: `N forks · <first fork's line>`, where a fork is a line
matching `^\s*(\d+\.|##\s)`. Tolerant by design: a miscount is cosmetic.

## 3. The handovers tab

    ╭ schedules 6 │ ▸handovers 4 open · 3 ? ─────────────────────── ←→ tab ╮
       STATE      AGE   LANE                    WINDOW   HOLDS  SAID
     ▸ ? ask      2h    handover-visibility     @31 ●    —      3 forks · 1. Filter persistence
       ? ask      1d    sched-options-table     exited   —      1 fork · 1. ESC in the create flow
       open       12m   dash-menus-settings     @24 ●    1      Phase 2 done; 36 captures green
       open ⚠     3d    27-hardening            —        —      Handoff — roadmaps 25-27 hardening
       done       1d    sched-options-core      exited   —      Finished. All six phases done
    ╰──────────────────────────────────────── done hidden: 13 · f shows ╯

* **Order**: unanswered questions, open (newest first), answered, done
  (newest first). The actionable end is the top; the cursor starts there.
* **WINDOW** joins `read_tree()[slug]` with `live_windows()` -- one fork, in
  this view only, which `build_sched` already pays. `—` when the tree never
  knew the slug (hand-named lanes).
* **HOLDS** is the `after:` interaction made visible: the number of PENDING
  entries in `read_schedules()` whose `after:` list (split as
  `sched_after_deps` splits it: commas or spaces) names this slug.
* **`open ⚠`** in red when the watchdog's state for the lane's window is
  `stranded` (status.tsv already carries it); yellow for the shadowed case.
* **Viewport** (§0.5): rows beyond the room scroll with `▲ N more`/`▼ N more`,
  using the sibling's `menulayout.menu_viewport` and the same
  `console.render_lines` measurement of the panels around it -- no second
  scrolling implementation. The schedules tab gets the same viewport for free.
* **The detail panel** replaces `why` on this tab: the path; title and gist;
  the next lines of the body up to what the measured room allows (min 3, max
  10); then the lifecycle facts: `window @24 open · parent sched-options ·
  launched from dash-menus-settings.md`; and `holds: release-1-12 (after:)`
  by name. For a questions row: the path and the first lines of the first fork.
* **Legacy questions** (§0.2): `scan` also globs `QUESTIONS_DIR`; such a row is
  tagged `legacy` and its detail names the folder. The old "awaiting your
  answers" panel is REMOVED -- the strip's `N ?` supersedes it.
* Cost: files are re-read only when `(mtime, size)` changed; the cache is a
  dict on the Dashboard. Nothing here runs in the main view except §6's count.

### Keys on this tab

    ↑↓ pick · ←→ tab · enter open/answer · e edit · E force-edit · space menu · f done · a asks · r reload · s/esc back

* **enter**: a QUESTIONS row opens the answer screen (§3b); `e` opens it in
  `$EDITOR`/nano through `pending_edit`. A STATUS row opens READ-ONLY in `$PAGER`/`less`
  through the same suspend path: a live lane rewrites its handover whenever
  it likes, and nano saving over that is how a handover is lost.
* **E** (capital, and `Edit anyway…` in the space menu) is the user's force
  edit of a STATUS row (Q5 as answered): a confirm first --
  `⚠ ➥<slug> may rewrite this file while you edit; whichever saves last wins.
  y edit  n view` -- worded for a live window; for a lane with no live window
  the confirm is skipped and the editor opens, because nothing can race it.
* **space** opens `self.menu = {"kind": "handover", "i": 0}` -- a fifth kind
  in the sibling's dict, built from the selected row and nothing else:

      STATUS, open     View · Edit anyway… · Open its window ➥slug (when live) ·
                       Mark done… (confirm NAMES the entries it releases)
      STATUS, done     View · Reopen (unstamped names only, as handover.sh allows)
      QUESTIONS        Answer… (§3b) · Edit the file · Mark answered / Mark unanswered ·
                       Tell ➥slug its answers are in (when its pane is live) ·
                       Show its handover (moves the cursor to the STATUS row)

  Every state change shells out to `handover.sh [--profile P] done|reopen|
  answered|unanswer <slug>` -- ONE implementation of never-clobber and of the
  marker. "Tell" is `tmux send-keys` to the tree's pane id of the line
  `Your questions are answered in <path> -- read it and continue.`, behind a
  confirm, reusing `_send`'s mechanics. It is the only thing here that touches
  a live window and it is never automatic.
* `c o l d` do nothing on this tab and say so (`d: schedules tab only`)
  rather than acting on a schedule row the person cannot see -- the same bug
  class the sibling's §4a fixes for space.

## 3b. Answering from the dashboard (added 2026-09-17, the user's request)

Seeing "awaiting your answers" with no way to answer is half a feature. On a
QUESTIONS row **enter opens the answer screen** (the editor moves to `e`, and
stays one key away on every screen of the flow -- the file is always the
escape hatch, because no parser will understand every lane's prose).

Pure, in `muxhandovers.py`:

    parse_forks(text) -> [Fork]      # id, title, span, options[{key, text, rec}], answer
    write_answer(text, fork_id, answer, date) -> text
    all_answered(forks) -> bool

A fork starts at a `## ` heading or a top-level `N.` item and ends at the
next. Options are `(a)` `(b)` ... wherever they occur in the fork -- as bullets
(`- **(a) RECOMMENDED: ...`) or inline (`Options: (a) ...; (b) ...`), both
shapes exist in real files. `rec` is the option whose text carries RECOMMENDED,
or the letter named by a `Recommendation...: (a)` line. A fork is answered when
it contains a line starting `**Answer`.

The screen is the existing picker, one fork at a time, title = the fork's
heading, the fork's full text in the detail panel above it:

    ▸ (a) the HOST's wall clock, transitively          ← recommended, preselected
      (b) a mesh median / consensus
      (c) true UTC via a time server
      type an answer…                                  the prompt submode
      skip this fork
      open the file in the editor  (e)

A fork with no parseable options offers `accept as written / as recommended`,
`type an answer…`, skip, editor. A chosen option may take a note: the prompt
opens prefilled empty, enter with nothing typed means no note. Each answer is
written AT ONCE as one line at the end of its fork:

    **Answer (user, 2026-09-17):** (a) — <note or the typed text>

atomically (`.tmp` + `os.replace`), and only if the file's `(mtime, size)` is
still what was parsed; if the lane wrote meanwhile, re-read, re-parse, re-apply
to the same fork id, and say so. When the last fork is answered the flow
offers `Mark answered` (the §2.2 marker, through `handover.sh answered`) and,
when the lane's pane is live, `Tell ➥slug its answers are in`. esc leaves at
any point; what was answered stays answered. Legacy-folder files answer the
same way (the marker is written by `muxhandovers` directly there, since
`handover.sh` does not own that folder).

On the SCHEDULES tab the old panel shrinks to one line --
`awaiting your answers: 2 · → to answer` -- so the message the user already
knows keeps pointing somewhere.

## 4. The filters, and where they live

Two, as asked: **done** (`f`) and **questions** (`a`, "asks").

| done | asks | shown |
|---|---|---|
| off | on | open + unanswered questions -- THE DEFAULT: what is owed |
| on | on | everything, answered questions included |
| off | off | open handovers only |
| on | off | open + done handovers, no question rows |

"Done" governs every finished thing (done handovers AND answered questions), so
two switches cover four kinds without a third key. A hidden count is always in
the panel subtitle (`done hidden: 13 · f shows`) and `N ?` stays in the strip,
so a filter can hide rows but never the fact that they exist.

**Persistence (fork Q2) -- RECOMMENDED: write-through to the sibling's store.**
Two new keys, appended after the sibling's eight in `muxsettings.DASHBOARD_KEYS`,
`muxconfig.KEYS` and `MUX_CONFIG_KEYS` (same order in all three; the sibling's
mirror test then covers them):

| key | values | default | read by |
|---|---|---|---|
| `DASHBOARD_HANDOVERS_DONE` | `on` `off` | `off` | the handovers tab: show finished rows |
| `DASHBOARD_HANDOVERS_QUESTIONS` | `on` `off` | `on` | the handovers tab: show QUESTIONS rows |

Both are kind `onoff`, so they appear in the sibling's Settings menu with no
extra code, and `f`/`a` call `muxsettings.put` (atomic, reread-verified). The
sibling refused to persist `t` and `f` of the main view ("a toggle key becomes
a disk write, and nobody asked"). Here somebody asked, and there is a measured
reason: `R` re-execs the dashboard and is "pressed a lot" (the code's own
comment), which resets every in-memory toggle; a done list that reappears on
each `R` would be switched off for good. No second mechanism: if
`muxsettings` is somehow absent the filters are session-only and say so.

## 5. `handover.sh`

`answered <slug>`, `unanswer <slug>`; `done` carries an answered QUESTIONS file
along (§2.2); `list` gains one line per QUESTIONS file with its state; `show`
unchanged. `slugfile` is generalised to take the prefix so the path-escape
guard is shared. The header comment and `--help` range grow with it.

## 6. The main view: one character

The session row whose lane slug (`lane_slug_of(window)`) has an unanswered
QUESTIONS file gets a yellow `?` beside its name, and the footer's `s` hint
reads `s schedules · 3 ?`. One `glob` plus the cached marker test, refreshed
at most every 5 s -- no fork, so the main frame's measured cost holds. This is
the part of shape (c) worth keeping (fork Q6).

## 7. Interaction with the sibling, the tree and `after:`

* **The sibling.** Phases 1-2 below touch no file the sibling or its two
  sub-lanes own. Phases 3+ edit `deck_status.py` and REQUIRE the sibling's
  `self.menu` dict, `muxsettings.py` and `menulayout.py`. The implementation
  entry therefore carries `after: dash-menus-settings` (fork Q4). Phase 7
  touches `setup-schedules.py` (owned by `dash-menus-wd-headers` until it is
  done) and checks that handover is in `done/` before editing.
* **The tree** is read, never written: WINDOW, parent and launch file in the
  detail panel; "Open its window" is the sibling's §4a row reused.
* **`after:`** is read, never reinterpreted: `lane_state` IS `sched_dep_state`'s
  order (mirror-tested), HOLDS shows who waits, and the Mark-done confirm says
  `releases: release-1-12, docs-1-12` before anything moves -- marking a
  handover done from a menu is launching those entries within 30 s, and the
  confirm has to say so.

## 8. Phases -- one commit each -- and each phase's test

Sandbox discipline is the sibling's §5, unchanged and mandatory: own `HOME`,
`XDG_CONFIG_HOME`, `XDG_STATE_HOME`, `MUXTOPUS_CONFIG`, `CLAUDE_CONFIG_DIR`;
a `tmux` wrapper pinned to `-L mxdash`; the fake `claude`; the dashboard driven
by `send-keys`, read by `capture-pane`; the sandbox daemon started with
`--daemon` and killed by pid, never `--reload`. NEVER the real `claude` tmux
session, `claude:0`, the real `~/.config/muxtopus`, the real
`~/.code/schedules` or `~/.code/handovers` (fixtures are COPIES, trimmed).

| # | commit subject | files | test |
|---|---|---|---|
| 1 | `[feat] muxhandovers: one reader for STATUS and QUESTIONS files` | `muxhandovers.py`, `tests/test_handovers.py`, `tests/fixtures/handovers/` | unit: every state incl. both-files and stamped names; `slug_of` round trip; `summarise` on trimmed copies of the 17 real shapes; `forks`; the four filter combinations; legacy dir; unreadable file kept as a row with the reason; the `sched_dep_state` order mirror |
| 2 | `[feat] handover.sh: answered / unanswer, and done takes answered questions along` | `handover.sh`, `tests/test_handover_sh.sh` | in a sandbox HOME: marker added once, idempotent, removed; `done` moves an answered QUESTIONS and leaves an unanswered one; never-clobber stamp on the second; `../` slug refused; `--profile` folder |
| 3 | `[feat] schedule view: a handovers tab on the arrows` | `deck_status.py` | sandbox captures at 24 and 40 rows: strip with counts on both tabs; ←→ switches; order; WINDOW `●` for a live fake window and `exited` after kill; HOLDS=1 for a fixture `after:`; shadowed row's `⚠`; viewport markers with 30 done fixtures and the bottom border present; `c`/`d` refuse on this tab; `handover_state` callers unchanged in output |
| 4 | `[feat] handovers tab: done and asks filters, persisted in dashboard.conf` | `deck_status.py`, `muxsettings.py`, `muxconfig.py`, `profile.sh` | the sibling's round-trip test extended to the two keys; key-list mirror test still green; in the sandbox: `f`, capture, `R`, capture -- filter survived; the file shows the line; Settings menu lists both rows |
| 5 | `[feat] handovers tab: enter opens, space acts` | `deck_status.py` | sandbox with `EDITOR`/`PAGER` set to recording stubs: QUESTIONS -> editor argv, STATUS -> pager argv, `E` -> the warning then editor argv (no warning when the window is dead); menu per row kind; Mark done: confirm names the fixture dependant, file lands in sandbox `done/`, sandbox daemon's next pass launches the dependant (`--check` says finished); Mark answered flips row and strip count; Tell: the fake `claude` pane receives the line |
| 5b | `[feat] handovers tab: answer a fork without leaving the dashboard` | `muxhandovers.py`, `deck_status.py`, `tests/test_handovers.py` | unit: `parse_forks` on trimmed copies of the four real QUESTIONS shapes (bulleted options, inline options, numbered, no options); `write_answer` idempotent per fork and byte-preserving elsewhere; the changed-underneath re-apply. Sandbox: answer two forks by send-keys, file shows both lines; a typed answer; skip; `e` reaches the editor stub from inside the flow; last fork offers Mark answered and the strip count drops |
| 6 | `[feat] main view: a ? on a lane with unanswered questions` | `deck_status.py` | capture shows `?` on the fixture lane's row and `s schedules · 1 ?`; gone after `answered`; `--once` timing before/after recorded in the handover |
| 7 | `[docs] handovers tab: README, help, the questions contract` | `README.md`, `deck_status.py` (HELP), `setup-schedules.py` | `QUESTIONS_CONTRACT` names `{{QUESTIONS}}` and the ANSWERED rule; generated README regenerated INTO THE SANDBOX and diffed; `--check` on every real entry still returns 0 (read only) |

`docs/dashboard.svg` is not regenerated, for the sibling's reason (it captures
the real `claude:0`). Owed to the user after their `R`, said in the handover.

## 9. Forks -- ANSWERED by the user, 2026-09-17

* **Q1 -- shape.** (a) tabs in `s`. *Answered: (a).* (b) own key; (c) toggle. §1.
* **Q2 -- filter persistence.** *Answered: (a)* write-through to `dashboard.conf`
  as the two `DASHBOARD_HANDOVERS_*` keys. Lost: (b) startup default only;
  (c) session-only.
* **Q3 -- what "answered" is.** *Answered: (a)* an `ANSWERED` marker line, the
  file stays put until its lane is done. Lost: (b) move to `done/`; (c) no state.
* **Q4 -- when the implementation starts.** *Answered: (a)* one entry, `model:
  opus`, held by `after:`. The user believed the sibling was done; checked at
  08:51 -- it is not (phases 1-2 of 6 committed, phase 3 uncommitted in
  `deck_status.py`), so the hold is real. The entry also waits on
  `dash-menus-wd-headers`, which owns `setup-schedules.py` (phase 7).
* **Q5 -- enter on a STATUS row.** *Answered: pager, PLUS a force edit behind a
  warning* -- `E` and a menu row, §3.
* **Q6 -- the main-view `?`.** *Answered: (a)* yes, phase 6.
