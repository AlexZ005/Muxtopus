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

None of the five needs to READ another lane's code. They collide only because
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

Flat files beside `deck_status.py`, the repo's existing style (`muxconfig.py`,
`menulayout.py`, `muxstats.py`); the scripts run in place from the checkout
(`SCRIPTS = Path(__file__).resolve().parent`), so nothing about install
changes. (Fork Q1: flat files vs a package.)

| file | owns | from today's symbols |
|---|---|---|
| `deck_status.py` | THE SHELL. argv, the console, `Live`, termios, the main loop, the full-screen hand-offs (editor, pager, btop, help, reload/quit), module discovery. ~250 lines. Still the entry point: `deck-status.sh` and `R`'s re-exec are unchanged | `main`, `read_key`, `decode_key`, `_complete_key` |
| `dash_core.py` | palette and style constants, paths and `knob`/`PROFILE`, the formatters, and the state-style table | `DIM FRAME RED…`, `human_*`, `when`, `gauge`, `sparkline`, `pressure`, `read` |
| `dash_data.py` | every reader of the machine and of the watchdog's files; no Rich | `meminfo`, `Cpu`, `processes`, `ports_for`, `claude_sessions`, `drop_dead`, `usage_*`, `refresh_usage`, `dirty_*`, `monitor_*`, `heartbeat_age`, `sched_why`, `read_tree`, `live_windows`, `handover_state`, `lane_*` |
| `sched_data.py` | schedule entries as data: parse, validate, slugs, the options line/section/rewrite; no Rich | `read_schedules`, `validate_schedule`, `resolve_slug`, `sanitise_slug`, `slug_warning`, `options_*`, `parse_options_line`, `asked_value`, `rewrite_options` |
| `dash_app.py` | `class App`: the notice, the console, the SUBMODES (prompt, confirm, picker and their footer), the MENU ENGINE (state, move, activate, title, hint, `place_menu`), the six registries of §3, key routing | `say`, `prompt_key`, `confirm_key`, `picker_key`, `_submode_foot`, `open_menu`, `menu_move`, `menu_activate`, `menu_title`, `menu_hint`, `place_menu` |
| `view_main.py` | the deck / lanes / claude / uncommitted / system frame, the row cursor, the tree, the session menu and its actions | `build` (minus the sched branch), `move`, `open_selected`, `tree_*`, `toggle_*`, `session_menu_entries`, `act_*`, `_send`, `_do_*` |
| `view_sched.py` | the schedules table and why panel, create flow, options table, the entry menu and its actions | `build_sched`, `sched_*`, `request_edit_selected`, `reopen_options`, `_write_options`, `start_create`, `_create_*`, `open_options`, `option*`, `launch_selected_now`, `confirm_delete_selected`, `duplicate_selected`, `check_selected`, `goto_window`, `act_schedule_resume` |
| `view_newsession.py` | the `c` flow | `start_new_session`, `_ns_*`, `model_choices` |
| `menu_mux.py` | the ESC menu and its Settings submenu | `mux_menu_entries`, `settings_menu_entries`, `_setting_*`, `act_disconnect/reload/quit`, `toggle_watchdog`, `run_deck_ram` |

Then, by the three lanes and nobody else: `view_handovers.py`,
`view_insights.py`, `menu_notify.py`.

**Compatibility.** `tests/test_entry_options.py` does `import deck_status as d`
and calls `d.rewrite_options`, `d.read_options`, `d.parse_options_line`,
`d.options_*`. The shell re-exports exactly those names from `sched_data`
with a comment saying why, and the test passes UNCHANGED -- it is one of the
behaviour proofs. `make-screenshot.py` captures a pane and imports nothing.

## 3. The seam: six registries on `App`

A module is discovered, not listed: the shell imports every
`view_*.py` and `menu_*.py` beside it, sorted by name, and calls its
`register(app)`. **No list anywhere names the modules** -- a list is a line
three lanes would all have to edit, which is the queue again in miniature. A
module that fails to import is skipped with a red notice
(`view_insights failed to load: <error>`) and the dashboard runs without it:
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
   tab is a new file, not an edit to `view_sched.py`), `build(app) ->
   [(name, panel)]` (sections, so `place_menu` works for every view, which it
   does not today: the sched view needed its own fix), `on_key(app, key) ->
   bool`, `footer(app) -> Text`, optional `on_open/on_close`.
2. **Menu kind** -- replaces the `if kind ==` chain. `esc_to` names the parent
   kind, which generalises the one hard-coded "settings goes back to mux".
3. **Rows into a menu** -- how `ESC ▸ Insights` and `Settings ▸
   Notifications ▸` arrive without touching `menu_mux.py`. `order` places them;
   ties sort by label, so the result never depends on import order.
4. **Badges and hints** -- how the `?` lands on a session row and `· 3 ?` in
   the footer without touching `view_main.py`. A badge function gets the
   session and returns a short `Text` or nothing; it must not fork (the main
   frame is measured in forks per second) -- stated in the docstring, and a
   badge that raises is dropped for the session with one notice.
5. **Help** -- `HELP` stops being one string; `?` prints the sections in order.
6. **State** -- the STATE column's name -> (label, style) table becomes data in
   `dash_core`, seeded with today's states; an unregistered state keeps
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
* `R` safety: the user's real dashboard on `claude:0` runs the old process
  until `R`. Each phase leaves a tree where `deck_status.py` starts; the tag
  is the one-command way back (`git checkout dash-pre-split -- .` is the
  USER's call, never the lane's).

## 5. What runs in parallel afterwards -- the point of the exercise

All three, from the moment `dash-split` is marked done. After the split:

| lane | owns (writes) | reads only |
|---|---|---|
| **handover-vis-impl** | `muxhandovers.py`, `view_handovers.py`, `handover.sh`, its tests and fixtures; ONE deletion in `view_sched.py` (the legacy questions panel becomes the one-line pointer); two keys in `muxconfig.py` + `profile.sh`; `setup-schedules.py` (questions contract) | `dash_app`, `dash_core`, `dash_data`, `sched_data` |
| **notify-dash** | `muxtelegram.py` (fork answers, AND `/stats` -- moved here from insights-dash so one lane owns the file; `muxstats.py` has already landed), `menu_notify.py`, its tests | `muxhandovers`, `muxstats`, `dash_app` |
| **insights-dash** | `view_insights.py`, the five-minute collect hook in `claude-watchdog.sh`, `install.sh` (seed `prices.md`), its tests | `muxstats`, `dash_app`, `menulayout` |

No file appears twice in the middle column. The shell, `dash_app.py`,
`view_main.py` and `menu_mux.py` appear in NONE: if a lane finds it must edit
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
* **`README.md` is the last shared file.** Each lane documents in its own
  `docs/<feature>.md` and adds its few README lines in its final commit.

**The shared-tree commit rule** (three lanes committing in one checkout at
once -- true today as well, and it has been luck): never `git add -A` / `git
commit -a`; always `git commit -m … -- <own paths>`, which commits exactly
those paths whatever else is staged; for a shared file (`README.md`,
`muxconfig.py`, `profile.sh`) `git diff -- <file>` must show only your own
hunks first, else wait a minute and look again; retry once on `index.lock`.
(Fork Q2: this, or a git worktree per lane.)

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
| 0 | `[test] dashboard: the sandbox harness and goldens of every screen, before the split` | the route of §4 on the UNTOUCHED code, run twice -> identical normalised captures (proves the masks); tag `dash-pre-split` |
| 1 | `[refactor] dashboard: data and formatting out of deck_status.py` | `dash_core` / `dash_data` / `sched_data`; goldens identical; `test_entry_options`, `test_options`, `test_settings`, `test_menulayout` unchanged and green; `python -c 'import sched_data, dash_data'` works WITHOUT rich installed |
| 2 | `[refactor] dashboard: App, the menu engine and the six registries` | `dash_app.py`; views still methods, reached through adapters; goldens identical; `tests/test_dash_app.py`: key-routing order, duplicate key = start-up error, `add_rows` ordering is import-order independent, a raising badge is dropped once |
| 3 | `[refactor] dashboard: the schedule view as a module` | `view_sched.py`; goldens identical incl. every entry-menu, create-flow and options-table capture |
| 4 | `[refactor] dashboard: the main view, the new-session flow and the esc menu as modules` | `view_main.py`, `view_newsession.py`, `menu_mux.py`; goldens identical at 24/40/58 × 3 layouts; `deck_status.py` under 300 lines |
| 5 | `[feat] dashboard: tabs, discovery and per-module help -- a view is one new file` | `tests/fixtures/view_demo.py` dropped beside a COPY of the scripts in the sandbox: appears as a tab of `s` with its label, takes ←→, contributes an ESC-menu row, a badge, a hint, a state style, a setting and a help section -- with `git status` showing no other file modified; a `view_broken.py` that raises on import -> red notice, everything else works; HELP golden re-reviewed; `docs/dashboard-views.md` (the protocol, the accessors, the no-fork rule for badges, the commit rule) |

## 7. Ordering that enforces itself

* `dash-split`: `after: dash-menus-settings`, `model: opus`.
* `handover-vis-impl`, `notify-dash`, `insights-dash`: each `after: dash-split`
  -- set at 10:4x today, before this plan was written, so nothing could slip
  out while it was. Their earlier holds are all satisfied or implied
  (notify-core and insights-core are done; dash-menus-settings precedes the
  split). Their bodies are amended to the ownership table of §5.

## 8. Forks (put to the user; answers in QUESTIONS-handover-visibility.md)

* **Q1 -- layout.** (a) RECOMMENDED flat `dash_*.py` / `view_*.py` /
  `menu_*.py` beside the script, the repo's style, discovery by glob;
  (b) a `dashboard/` package with `views/` inside.
* **Q2 -- three lanes in one checkout.** (a) RECOMMENDED stay in the shared
  tree with the path-scoped commit rule; (b) a git worktree and branch per
  lane, merged by the parent window.
* **Q3 -- how much moves.** (a) RECOMMENDED everything in §2, six phases;
  (b) the seam only (phases 0, 2, 5): new views become files, the existing
  2000 lines stay in `deck_status.py` behind adapters.
