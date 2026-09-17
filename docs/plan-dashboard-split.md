# Plan: split the dashboard into a shell and view modules

Status: PLAN, 2026-09-17, lane `handover-visibility`. Approved in principle by
the user ("plan the split only"); nothing here is implemented, and the three
lanes it unblocks stay HELD behind it (§7). Locate by symbol, not by line.

Read before this: `deck_status.py` as it stands when you start (NOT as quoted
here), `menulayout.py`, `muxsettings.py`, `docs/plan-dashboard-menus.md`,
`~/.code/handovers/done/STATUS-dash-menus-settings.md`, and the three plans
whose lanes wait on this: `plan-handover-visibility.md`,
`plan-notify-telegram.md`, `plan-insights.md`.

## 0. The problem, measured

`deck_status.py` is 3768 lines; `class Dashboard` alone is 2141, `build()` 398,
`main()` 211. Every dashboard feature is a method on that one class plus a
branch in `main()`'s key chain plus an `if kind ==` in `menu_entries()`. So
every lane that adds anything must hold the same file, and lanes hold it in
turn: dash-menus-settings -> handover-vis-impl -> notify-dash -> insights-dash.
The last of those would wait on roughly twenty phases of other people's work
to add one view that shares no code with any of them.

What each held lane actually needs from the file is small and of six kinds:

| need | handover-vis-impl | notify-dash | insights-dash |
|---|---|---|---|
| a new view / tab with its own keys and footer | the handovers tab | -- | the `i` view |
| a new menu kind | `handover` | `notify` (settings submenu) | -- |
| a row in an existing menu | -- | Settings ▸ Notifications | ESC ▸ Insights |
| a mark on a main-view session row / footer hint | the yellow `?`, `s · 3 ?` | -- | -- |
| how a session STATE is drawn | -- | `waiting` as yellow `needs you` (today an unknown state is drawn dim under its own name -- notify-core checked) | -- |
| settings keys, a HELP section | 2 keys, help | 7 keys, help | help |

None of the three lanes needs to READ another lane's code. They collide only because
there is no place to put any of them except the middle of one class. The split
is therefore a SEAM first and a tidy-up second: a handful of registration points, and
the existing views moved behind them to prove the seam carries real weight.

## 1. Where the split starts: against dash-menus-settings' END state

That lane is live in `deck_status.py` now: phases 1-4 committed (`e3193e4`,
`47b4f84`, `303fbfb`, `70e7535`), phase 5 (options table: esc cancels, action
rows) UNCOMMITTED in the tree at the time of writing (+74/-22), phase 6 (docs)
edits `HELP` inside the same file. **Both must be committed before the split
starts** -- phase 5 rewrites `options_key` / `option_rows`, which move in §4,
and phase 6 edits the `HELP` string that §3 breaks into per-module sections.
Splitting under either is the two-windows-one-file loss this plan exists to
end. So the entry is `after: dash-menus-settings`: the lane's own
`handover.sh done` is the signal, not a commit count.

What that lane lands, and the split builds on rather than redesigns: the
`self.menu = {"kind", "i"}` state and `menu_entries()` dispatch; `place_menu`
with `sections: [(name, panel)]` and the measured room; `menulayout.py`;
`muxsettings.py`; `pending_reload / pending_quit / pending_report /
pending_edit` (requests the main loop honours); the `c` flow (`_ns_*`); the
sandbox harness (`env.sh`, `start.sh`, `k.sh`, `type.sh`, `cap.sh`,
`assert_menu.py`) -- which lives in a `/tmp` scratchpad and is promoted into
the repo by phase 0 here, before `/tmp` eats it.

## 2. The modules

A `dashboard/` package (Q1, the user's choice: the repo root already carries a
dozen `.py` files and is about to be looked at on GitHub). The scripts run in
place from the checkout (`SCRIPTS = Path(__file__).resolve().parent`, which
Python puts on `sys.path` for the entry script), so `import dashboard` needs no
install step and no path hack. `menulayout.py` is dashboard-only and moves in
as `dashboard/menulayout.py` in phase 1 (one test import follows it). The
`mux*.py` modules are shared with the watchdog, the CLI and the bot and STAY
at the root; folding them into a `muxtopus/` library package is the natural
next step and is NOT this lane's.

| file | owns | from today's symbols |
|---|---|---|
| `deck_status.py` | THE SHELL. argv, the console, `Live`, termios, the main loop, the full-screen hand-offs (editor, pager, btop, help, reload/quit), module discovery. ~250 lines. Still the entry point: `deck-status.sh` and `R`'s re-exec are unchanged | `main`, `read_key`, `decode_key`, `_complete_key` |
| `dashboard/core.py` | palette and style constants, paths and `knob`/`PROFILE`, the formatters, and the state-style table | `DIM FRAME RED…`, `human_*`, `when`, `gauge`, `sparkline`, `pressure`, `read` |
| `dashboard/data.py` | every reader of the machine and of the watchdog's files; no Rich | `meminfo`, `Cpu`, `processes`, `ports_for`, `claude_sessions`, `drop_dead`, `usage_*`, `refresh_usage`, `dirty_*`, `monitor_*`, `heartbeat_age`, `sched_why`, `read_tree`, `live_windows`, `handover_state`, `lane_*` |
| `dashboard/schedules.py` | schedule entries as data: parse, validate, slugs, the options line/section/rewrite; no Rich | `read_schedules`, `validate_schedule`, `resolve_slug`, `sanitise_slug`, `slug_warning`, `options_*`, `parse_options_line`, `asked_value`, `rewrite_options` |
| `dashboard/app.py` | `class App`: the notice, the console, the SUBMODES (prompt, confirm, picker and their footer), the MENU ENGINE (state, move, activate, title, hint, `place_menu`), the six registries of §3, key routing | `say`, `prompt_key`, `confirm_key`, `picker_key`, `_submode_foot`, `open_menu`, `menu_move`, `menu_activate`, `menu_title`, `menu_hint`, `place_menu` |
| `dashboard/views/main.py` | the deck / lanes / claude / uncommitted / system frame, the row cursor, the tree, the session menu and its actions | `build` (minus the sched branch), `move`, `open_selected`, `tree_*`, `toggle_*`, `session_menu_entries`, `act_*`, `_send`, `_do_*` |
| `dashboard/views/schedules.py` | the schedules table and why panel, create flow, options table, the entry menu and its actions | `build_sched`, `sched_*`, `request_edit_selected`, `reopen_options`, `_write_options`, `start_create`, `_create_*`, `open_options`, `option*`, `launch_selected_now`, `confirm_delete_selected`, `duplicate_selected`, `check_selected`, `goto_window`, `act_schedule_resume` |
| `dashboard/views/newsession.py` | the `c` flow | `start_new_session`, `_ns_*`, `model_choices` |
| `dashboard/menus/mux.py` | the ESC menu and its Settings submenu | `mux_menu_entries`, `settings_menu_entries`, `_setting_*`, `act_disconnect/reload/quit`, `toggle_watchdog`, `run_deck_ram` |

Then, by the three lanes and nobody else: `dashboard/views/handovers.py`,
`dashboard/views/insights.py`, `dashboard/menus/notify.py`.

**Compatibility.** `tests/test_entry_options.py` does `import deck_status as d`
and calls `d.rewrite_options`, `d.read_options`, `d.parse_options_line`,
`d.options_*`. The shell re-exports exactly those names from `dashboard.schedules`
with a comment saying why, and the test passes UNCHANGED -- it is one of the
behaviour proofs. `make-screenshot.py` captures a pane and imports nothing.

## 3. The seam: six registries on `App`

A module is discovered, not listed: the shell walks `dashboard.views` and
`dashboard.menus` with `pkgutil.iter_modules`, sorted by name, imports each
and calls its `register(app)`. **No list anywhere names the modules** -- a list is a line
three lanes would all have to edit, which is the queue again in miniature. A
module that fails to import is skipped with a red notice
(`views.insights failed to load: <error>`) and the dashboard runs without it:
one lane's bad commit cannot take down the screen the others are tested in,
and it is the behaviour a public plugin story will want.

    app.add_view(View)                 1  a screen or a tab
    app.add_menu(kind, entries_fn, title_fn=None, hint_fn=None, esc_to=None)   2
    app.add_rows(menu_kind, rows_fn, order=50)     3  rows INTO someone else's menu
    app.add_badge(fn, order=50)        4  fn(app, session) -> Text | None, and
    app.add_hint(fn)                      fn(app) -> Text | None for the main footer
    app.add_help(title, text, order=50)            5  one HELP section
    app.add_state(name, label, style)  6  how the STATE column draws a watchdog state
    muxsettings.register({key: spec})  +  settings keys, declared by their module

1. **View** -- `name`, `key` (opens it from the main view; `None` for main),
   `group` and `tab_label(app)` (views sharing a `group` are TABS: the shell
   draws the strip in the panel title and ←→ cycles them -- so the handovers
   tab is a new file, not an edit to `dashboard/views/schedules.py`), `build(app) ->
   [(name, panel)]` (sections, so `place_menu` works for every view, which it
   does not today: the sched view needed its own fix), `on_key(app, key) ->
   bool`, `footer(app) -> Text`, optional `on_open/on_close`.
2. **Menu kind** -- replaces the `if kind ==` chain. `esc_to` names the parent
   kind, which generalises the one hard-coded "settings goes back to mux".
3. **Rows into a menu** -- how `ESC ▸ Insights` and `Settings ▸
   Notifications ▸` arrive without touching `dashboard/menus/mux.py`. `order` places them;
   ties sort by label, so the result never depends on import order.
4. **Badges and hints** -- how the `?` lands on a session row and `· 3 ?` in
   the footer without touching `dashboard/views/main.py`. A badge function gets the
   session and returns a short `Text` or nothing; it must not fork (the main
   frame is measured in forks per second) -- stated in the docstring, and a
   badge that raises is dropped for the session with one notice.
5. **Help** -- `HELP` stops being one string; `?` prints the sections in order.
6. **State** -- the STATE column's name -> (label, style) table becomes data in
   `dashboard.core`, seeded with today's states; an unregistered state keeps
   today's fallback (dim, under its own name).

`muxsettings.register` lets a module declare its keys; `DASHBOARD_KEYS` keeps
the core eight. The mirror test compares the UNION against `muxconfig.KEYS`
and `MUX_CONFIG_KEYS`. Those two lists are still shared files -- but after
notify-core (its seven are in already) only handover-vis-impl adds to them.

**Key routing, one rule:** submode (prompt/confirm/picker/a view's own modal
such as the options table, via `app.modal`) -> open menu -> the active view's
`on_key` -> the shell's globals (`q R ? p`) -> view-opening keys. Today's
order exactly, including that a submode swallows `q`. A key two views claim
is a registration ERROR at start-up naming both, not last-one-wins.

**State.** `App` holds what is shared (notice, console, menu, submodes,
pending requests, the active view). Each view object holds its own
(`sched_i`, `collapsed`, `tree_mode`, `ns`, ...). Cross-view reads that exist
today -- the `c` flow reads the main cursor's cwd, the sched menu's "open its
window" uses the tree -- go through `app.view("main")` accessors, listed in
`docs/dashboard-views.md` so the coupling is visible instead of being
`self.cursor` from anywhere.

## 4. Moving the existing views without changing behaviour

The move is mechanical and is PROVEN, not reviewed:

* **Goldens first (phase 0).** The harness is committed as `tests/sandbox/`
  and a script drives the PRE-split dashboard through a fixed route on a
  fixture HOME: main view; space, esc-menu, settings and each layout at 24 /
  40 / 58 rows; `s`, the entry menu on each fixture kind, the create flow to
  the options table and esc, the `c` flow to its last screen and esc, `?`,
  `t`, `f`, ←/→ on the tree. Each capture is NORMALISED (clock, cpu/ram
  figures, ages, pids, temperatures masked by regex -- the masks are part of
  the test, reviewed once) and stored. `git tag dash-pre-split`.
* **Every later phase must reproduce every golden byte for byte**, run the
  existing tests, and `--once` must
  render ("the existing tests" = everything in `tests/` at the start commit,
listed in the phase 0 commit body). A diff is a bug in the move, never a golden to regenerate; the only
  allowed golden change is the HELP screen in phase 5, reviewed by eye and
  said so in the commit.
* **Move, do not improve.** Bodies are cut and pasted with `self.` rebound to
  `app.`/`view.`; no renames of user-visible text, no "while I am here".
  Things noticed on the way go in the handover's list, not in the diff.
* `R` safety: under §5b the work happens on a branch in its own worktree, so
  the user's real dashboard on `claude:0` cannot load any of it until the PR
  is merged. Each phase still leaves a tree where `deck_status.py` starts; the
  tag `dash-pre-split` is the reference point, and reverting the merge commit
  is the way back -- the USER's call, never the lane's.

## 5. What runs in parallel afterwards -- the point of the exercise

All three, from the moment `dash-split` is marked done. After the split:

| lane | owns (writes) | reads only |
|---|---|---|
| **handover-vis-impl** | `muxhandovers.py`, `dashboard/views/handovers.py`, `handover.sh`, its tests and fixtures; ONE deletion in `dashboard/views/schedules.py` (the legacy questions panel becomes the one-line pointer); two keys in `muxconfig.py` + `profile.sh`; `setup-schedules.py` (questions contract) | `dashboard.app`, `.core`, `.data`, `.schedules` |
| **notify-dash** | `muxtelegram.py` (fork answers, AND `/stats` -- moved here from insights-dash so one lane owns the file; `muxstats.py` has already landed), `dashboard/menus/notify.py`, its tests | `muxhandovers`, `muxstats`, `dashboard.app` |
| **insights-dash** | `dashboard/views/insights.py`, the five-minute collect hook in `claude-watchdog.sh`, `install.sh` (seed `prices.md`), its tests | `muxstats`, `dashboard.app`, `dashboard.menulayout` |

No file appears twice in the middle column. The shell, `dashboard/app.py`,
`dashboard/views/main.py` and `dashboard/menus/mux.py` appear in NONE: if a lane finds it must edit
one of them, the seam is missing a hook, and the rule is to stop and write
that in QUESTIONS rather than reach in -- a gap in the seam is this plan's bug
and gets fixed once, for everyone.

Two honest exceptions to "fully parallel":

* **One ordering edge survives.** notify-dash's "the phone answers a fork"
  calls `muxhandovers.parse_forks` / `write_answer`. handover-vis-impl's entry
  is amended to build those in its FIRST commit (they are pure functions; its
  plan had them in phase 5b), and notify-dash is told to do its Settings menu
  first and the fork phase second, checking the import. That is one function
  signature to agree on, written into both entries, not a queue.
* **`README.md` and the two key lists stay shared files**, and under the
  branch model below that stops mattering: the second lane to touch one
  rebases and resolves a three-line conflict, as any project does.

### 5b. Branches, worktrees and pull requests (Q2 -- the user left it to this plan)

Until now every lane committed straight to `main` in ONE checkout, side by
side, and the user's live dashboard re-execs from that same checkout on `R` --
so `R` could load another lane's half-finished edit, and one lane's `git
commit` could sweep up another's staged file. It has been luck. With three
lanes about to run at once and a public repository coming, the model becomes
the ordinary one for a small open-source tool:

* **`main` is the trunk and always runs.** Nothing is developed in the main
  checkout any more; it only fast-forwards. The user's `R` then only ever
  loads merged, tested code.
* **One branch and one git worktree per lane**, made by the lane as its first
  act: `git fetch && git worktree add ~/.code/worktrees/scripts-<slug> -b
  <type>/<slug> origin/main` (`refactor/dashboard-split`,
  `feat/handover-visibility`, `feat/notify-dashboard`, `feat/insights-view`).
  Real isolation: own index, own files, own sandbox. Removed after the merge.
* **One pull request per lane**, per-phase commits kept, merged with a MERGE
  COMMIT (`gh pr merge --merge --delete-branch`), so GitHub's history reads
  "PR #12 Insights view" over its reviewable commits. The PR body is the
  handover's summary and the tests run. Opened as a DRAFT after the first
  phase so progress is visible; marked ready at the end.
* **Who merges: the lane, behind a gate** -- rebased on current `origin/main`,
  every test and every golden green AFTER the rebase, CI green, PR mergeable.
  That keeps the ordering self-enforcing with nobody awake. The day the user
  wants review first, a branch-protection rule on `main` is the whole change:
  `gh pr merge` is refused, the lane says so and leaves its handover OPEN, and
  everything held `after:` it stays held. The gate fails closed.
* **A handover is marked done only after the PR is merged and the main
  checkout fast-forwarded** (`git -C <main> pull --ff-only`; if that checkout
  is dirty the lane says so and leaves it alone). "Done" then means "on
  main", which is what every `after:` actually wants to know.
* **Pushing.** A lane pushes its own branch; it never force-pushes anything
  shared and never pushes `main` -- with ONE stated exception for the first
  lane under this model: `main` is ahead of `origin/main` today (3 commits at
  the time of writing, plus these plans), and a PR cut from it would show
  other lanes' commits as its own. So `dash-split` fast-forward-pushes `main`
  once before branching: committed, finished work only, refused if it is not
  a fast-forward or if the main checkout is dirty.
* **CI**, because a green tick is what a visitor reads first:
  `.github/workflows/tests.yml` runs the Python tests and those shell tests
  that pass in a clean container (`tmux`, `jq` from apt; `rich` from pip).
  Tests that need the full sandbox stay local and are listed as such in
  `docs/dashboard-views.md`. Phase 0 adds it; the merge gate includes it.
* **Versions.** `VERSION` exists (4.9.0); there are no tags and no changelog.
  A `CHANGELOG.md` edited by every PR is a guaranteed conflict among parallel
  lanes, so each PR adds ONE fragment, `changes/<slug>.md` (a heading and a
  few user-facing lines); a release concatenates them into `CHANGELOG.md`,
  bumps `VERSION` and tags `vX.Y.Z`. This lane creates `changes/README.md`
  saying so, and its own fragment. Cutting the first release is the user's
  decision and is not planned here.

Estimated effect: serial was dash-menus -> 8 phases -> 3 -> 3. After: split
(6 phases, below), then max(8, 3, 3) side by side. The split pays for itself
if it costs less than the six phases it lets overlap -- and every later
dashboard feature, from any lane or outside contributor, starts as a new file.

## 6. Phases of `dash-split`, one commit each, and each test

Sandbox discipline as `docs/plan-dashboard-menus.md` §5 (`tmux -L mxsplit`),
never the real `claude` session, `claude:0`, real config, schedules or
handovers other than the lane's own files.

| # | commit | test |
|---|---|---|
| 0 | `[test] dashboard: the sandbox harness, goldens of every screen before the split, and CI` | the route of §4 on the UNTOUCHED code, run twice -> identical normalised captures (proves the masks); tag `dash-pre-split`; `.github/workflows/tests.yml` green on the draft PR; `changes/README.md` |
| 1 | `[refactor] dashboard: data and formatting out of deck_status.py` | `dashboard.core` / `dashboard.data` / `dashboard.schedules`; goldens identical; `test_entry_options`, `test_options`, `test_settings`, `test_menulayout` unchanged and green; `python -c 'import dashboard.schedules, dashboard.data'` works WITHOUT rich installed |
| 2 | `[refactor] dashboard: App, the menu engine and the six registries` | `dashboard/app.py`; views still methods, reached through adapters; goldens identical; `tests/test_dashboard_app.py`: key-routing order, duplicate key = start-up error, `add_rows` ordering is import-order independent, a raising badge is dropped once |
| 3 | `[refactor] dashboard: the schedule view as a module` | `dashboard/views/schedules.py`; goldens identical incl. every entry-menu, create-flow and options-table capture |
| 4 | `[refactor] dashboard: the main view, the new-session flow and the esc menu as modules` | `dashboard/views/main.py`, `dashboard/views/newsession.py`, `dashboard/menus/mux.py`; goldens identical at 24/40/58 × 3 layouts; `deck_status.py` under 300 lines |
| 5 | `[feat] dashboard: tabs, discovery and per-module help -- a view is one new file` | `tests/fixtures/demo_view.py` dropped into `dashboard/views/` of a COPY of the scripts in the sandbox: appears as a tab of `s` with its label, takes ←→, contributes an ESC-menu row, a badge, a hint, a state style, a setting and a help section -- with `git status` showing no other file modified; a `views/broken.py` that raises on import -> red notice, everything else works; HELP golden re-reviewed; `docs/dashboard-views.md` (the protocol, the accessors, the no-fork rule for badges, the branch / PR / changes-fragment rules of §5b) |

## 7. Ordering that enforces itself

* `dash-split`: `after: dash-menus-settings`, `model: opus`.
* `handover-vis-impl`, `notify-dash`, `insights-dash`: each `after: dash-split`
  -- set at 10:4x today, before this plan was written, so nothing could slip
  out while it was. Their earlier holds are all satisfied or implied
  (notify-core and insights-core are done; dash-menus-settings precedes the
  split). Their bodies are amended to the ownership table of §5.

## 8. Forks -- ANSWERED by the user, 2026-09-17

* **Q1 -- layout.** Recommended was flat files; **the user chose a
  `dashboard/` package.** §2 and §3 are written for the package.
* **Q2 -- three lanes at once.** Recommended was the shared tree with
  path-scoped commits; **the user left it to this plan and named what matters:
  how the project reads on GitHub, versions to come, no fixed roadmap, best
  practice.** Decided: a branch + worktree + PR per lane, merged by the lane
  behind a test gate that fails closed, CI, changelog fragments -- §5b. The
  recommendation was wrong for where the project is going: it optimised for
  today's habit, and the habit was the hazard.
* **Q3 -- how much moves.** **Everything, six phases** (the user deferred to
  the recommendation in the light of Q2): a public repo should not ship half
  a split.
