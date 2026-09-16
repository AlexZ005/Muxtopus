# Plan: the dashboard's menus, its settings, the schedule menu and the session creator

Status: PLAN for review, 2026-09-16, lane `dash-menus-settings`. Nothing here is
implemented. Every line number is deliberately absent: locate by symbol.

Read before this: `deck_status.py` end to end, `muxconfig.py`, `profile.sh`,
`claude-watchdog.sh`'s `launch_schedule` / `sched_parent` / `SCHED_PERM_MODES`,
`~/.config/muxtopus/options.md`, `docs/plan-schedule-options.md`, and the twelve
commits since `cb1b5a5`. The three `sched-options-*` handovers in
`~/.code/handovers/done/` describe the sandbox this lane reuses.

## 0. What was measured while reading, that the brief did not have

These change the design, so they come first.

1. **`defaultMode` is nested.** `~/.claude/settings.json` on this machine is
   `{"permissions": {"defaultMode": "bypassPermissions"}, ...}` -- the key lives
   under `permissions`, not at the top level as the brief's warning text writes
   it. The write in §4b sets `permissions.defaultMode` and the warning names
   the nested key, or it would write a key Claude Code never reads and the
   confirm would be a lie. The account file already carries bypass, so on this
   machine the "make it permanent" write is a no-op for the account scope and
   a real change only for a project scope.
2. **A session id does not exist before launch.** The watchdog's opt-out files
   are keyed by session id (`optout`, `monitor-optout`, one id per line), and
   the id is minted by `claude` itself and published in
   `$MUX_CONFIG_DIR/sessions/<pid>.json` with a `.tmux` field ending in the
   pane id. So the "auto-enable watchdog / monitor for a new window" settings
   cannot be applied by the dashboard when it writes the entry: they become two
   header fields, `watchdog: off` / `monitor: off`, and the LAUNCHER applies
   them right after the readiness wait by mapping its own pane id to the
   session file. One launcher, whoever asked -- exactly the brief's rule for
   the window itself.
3. **The height problem is real and exact.** Rich's `Live(screen=True)` crops a
   Group taller than the terminal from the bottom, and the space menu is the
   last element. The longest menu today is 15 rows plus 3 of chrome
   (11 entries, 2 separators, 2 "off globally" lines). `Console.render_lines`
   returns the exact rendered height of any renderable (verified in the venv:
   a 3-line Panel renders as 5 lines), so the room left under the panels can be
   MEASURED per frame rather than estimated from row counts.
4. **`menu_activate` already has a "stay open" path** for items keyed
   `watchdog` / `monitor`, and nothing produces those keys any more. The ESC
   menu's global toggles will, so that dead branch becomes live rather than
   being reinvented.
5. **`_create_write` hard-codes a fallback cwd** (`~/.code/theprototype-app/core`)
   when the cursor's session has none. That is a setting wearing a constant's
   clothes; it becomes `DASHBOARD_NEW_CWD` (§2) and the `c` flow's folder
   picker reads it.
6. **The brief's `c` flow has no screen for the name.** The slug names the
   window, the handover and `handover.sh done`; with no title the slug falls
   back to the filename stem (`new-20260916-101500`). A name screen is added
   (§4b, fork Q1).
7. **An empty first prompt is a stalled entry** if the type is `work`: the
   executor refuses "a work item with an empty prompt body". A `plan` entry may
   be empty and pastes only its `[muxtopus]` identity lines. See fork Q2.
8. **`--reload` is not sandboxable** (the verify lane's finding, still open):
   it resolves the daemon from systemd. This lane never calls `--reload`; the
   sandbox daemon is started with `--daemon` on its own state dir and killed
   by pid.

## 1. The ESC menu (phase 1)

ESC in the main view -- unbound today -- opens the muxtopus menu. The menu
state generalises from `menu_open: bool` + `menu_i: int` to ONE dict, so the
three menus share the mover, the activator and the layout engine:

    self.menu: dict | None   # {"kind": "session"|"sched"|"mux"|"settings", "i": int}

`menu_entries()` dispatches on `kind`; `menu_move` and `menu_activate` are
unchanged in shape. An item may carry `"stay": True` (the menu survives its
activation -- the toggles) and `"sub": "settings"` (opens another kind at
index 0). ESC closes whichever is open; from the settings submenu ESC goes
BACK to the mux menu rather than closing everything, because that is what a
submenu's ESC means everywhere else.

Entries, top to bottom:

    Settings ▸                                       sub
    ·······
    Watchdog: ON  restart a limited window after its reset    stay, toggle_watchdog()
    Monitor: off  ask a working window to wind down near the limit   stay, act_monitor()
    ·······
    Disconnect  detach this tmux client; every window keeps running   tmux detach-client
    Reload the dashboard  (R)                        sets pending_reload
    Quit                                             sets pending_quit

Disconnect runs `tmux detach-client` with no target: inside a pane `TMUX` is
set and tmux resolves the current client from it. With no `TMUX` in the
environment the row is disabled with "not inside tmux". Reload and Quit set
flags the main loop honours, because both must run in `main()` where the
terminal state and `Live` are (the R path stops Live, restores termios and
execs; a method on the Dashboard cannot do that).

The footer keys line gains `esc menu`; HELP and the README key table gain the
row. Space keeps opening the per-row menu.

## 2. Settings, persisted (phase 1, with §1)

### 2.1 The fork: where they live

The brief recommends a second file the dashboard owns. **Agreed, and taken as
recommended**, with one refinement on precedence argued below.

    ~/.config/muxtopus/dashboard.conf                    default account
    ~/.config/muxtopus/profiles/<name>.dashboard.conf    one named account

Same `KEY="value"` shell syntax, so `muxconfig._read` and a `.`-source in
`profile.sh` read it unchanged. Written atomically (write `.tmp` beside it,
`os.replace`). The file starts with a two-line comment saying the dashboard
writes it and hand edits belong in `config` -- because that is the whole
reason it is a separate file: `config` is the user's, full of their comments,
and a program that rewrites it will eventually eat them.

Precedence, lowest first:

    built-in default
    environment
    config                              hand-written, every account
    dashboard.conf                      dashboard-written, every account
    profiles/<name>.conf                hand-written, one account
    profiles/<name>.dashboard.conf      dashboard-written, one account

Why the dashboard file sits ABOVE the hand-written one at each scope: the
menu is where a value was set most recently and most explicitly, and the
round-trip rule ("set in the menu, reread from disk, same value") can only
hold if the file the dashboard writes for an account is the top layer for
that account. Why the account's hand-written file still beats the shared
dashboard file: that is the existing rule (a profile file narrows the scope)
and breaking it for one file would be the surprise. Both halves apply it:
`muxconfig.settings()` reads the two extra files in that order; `profile.sh`'s
`mux_load_config` sources them at the same two points, `mux_show_config`
learns the two extra source labels (`dashboard`, `profile-dashboard`).

Keys go in `muxconfig.KEYS` AND `MUX_CONFIG_KEYS`, in the same order, as the
verify lane established (`knob()` asserts on an unknown key -- a key in one
list only is a crash). A test parses both lists out of their files and
compares the sequences. A side effect worth stating: `mux_config_template`
will list the new keys, commented at their defaults, in every `config` and
`profiles/<name>.conf` it writes from now on. That is right -- a hand CAN set
them there -- and the comment says the menu writes elsewhere.

### 2.2 The keys

| key | values | default | read by |
|---|---|---|---|
| `DASHBOARD_MENU_LAYOUT` | `table` `modal` `bottom` | `table` | the layout engine, §3 |
| `DASHBOARD_NEW_PERMISSION_MODE` | `ask` or one of `SCHED_PERM_MODES` | `ask` | `c`, screen 4 |
| `DASHBOARD_PERMANENT_MODE_SCOPE` | `project` `account` | `project` | the JSON write, §4b |
| `DASHBOARD_NEW_WATCHDOG` | `on` `off` | `on` | `c`: writes `watchdog: off` when off |
| `DASHBOARD_NEW_MONITOR` | `on` `off` | `on` | `c`: writes `monitor: off` when off |
| `DASHBOARD_NEW_MODEL` | empty (account default) or a CLI alias | empty | `c`, screen 2 preselect |
| `DASHBOARD_NEW_EFFORT` | empty or `low medium high xhigh max` | empty | `c`, screen 3 preselect |
| `DASHBOARD_NEW_CWD` | a directory, or empty | empty | `c` screen 1 and `_create_write`'s fallback (§0.5) |

`DASHBOARD_NEW_PERMISSION_MODE` offers the whole of `SCHED_PERM_MODES`
(`acceptEdits auto bypassPermissions manual dontAsk plan`), not the brief's
five: the list is mirrored from the launcher and a subset would be a third
list. `ask` is the "always ask" value. The defaults for watchdog/monitor are
`on` because that is what a session gets today (absent from the opt-out file
means covered), so a machine that never opens Settings changes nothing.

Considered and NOT added, with why: the frame interval (already `--int` on
the command line), the tree ordering and the lanes filter (session toggles on
`t` and `f`; persisting them makes a toggle key a disk write, and nobody
asked), a default template for `c` in the schedule view (that flow has a
picker already). "Do not invent settings nothing reads" is the rule applied.

### 2.3 The module: `muxsettings.py` (new file)

`muxconfig.py` is a READER by its own charter and stays one. The writer is a
new module beside it, imported by the dashboard:

    DASHBOARD_KEYS      # key -> {label, choices|None, kind: "choice"|"onoff"|"text"}
    get(key, profile)   -> str            # via muxconfig.knob
    put(key, value, profile) -> str       # validate, write atomically, REREAD,
                                          # return "" or the complaint
    dashboard_conf_path(profile) -> Path
    settings_json_path(scope, cwd) -> Path      # project: <cwd>/.claude/settings.json
    set_default_mode(path, mode) -> (msg, err)  # the ONE JSON write, §4b
    PERM_MODES = ("acceptEdits", "auto", "bypassPermissions", "manual", "dontAsk", "plan")

`put` rewrites the whole dashboard file from the dict it read plus the one
change (the file is the dashboard's, so a full rewrite loses nothing), then
calls `muxconfig.settings(profile)` afresh and refuses to report success unless
the value read back is the value written. `PERM_MODES` is mirrored from
`SCHED_PERM_MODES`, and the same test that compares the key lists compares
this one against the shell.

### 2.4 The Settings menu (kind `settings`)

One row per key, label and current value, e.g. `Menu layout: table`. Enter on
a choice row opens the existing picker (preselected on the current value; the
empty value is shown as `(account default)`); on an on/off row it toggles in
place. Either way the row is `stay`, the value goes through `put`, and the
notice says what was written and where (`menu layout = modal  ·
dashboard.conf`). A disabled last-but-one row names the file being written;
the last row is `Back`. The layout setting takes effect on the next frame, so
you can see the three layouts by cycling the row with the menu open.

## 3. Three menu layouts (phase 2)

### 3.1 The engine

One renderer for every menu kind, split so the hard part is pure:

    menu_viewport(n_items, cur, rows) -> (top, show_up, show_down)
    menu_panel(items, cur, title, rows) -> Panel      # rows = TOTAL height incl. border

`menu_viewport` keeps `cur` inside a window of `rows - chrome` item lines and
reserves one line for `▲ N more` at the top when `top > 0` and one for
`▼ N more` at the bottom when items remain -- the markers are inside the
budget, never on top of it. Separators and disabled rows count as lines. The
cursor never lands on a marker (`menu_move` already skips separators and
disabled rows; the markers are drawn, not items). `menu_panel` is the drawing
of today's footer menu with the viewport applied and the title carrying the
row it is about (`menu · ➥➥dash-menus-settings`, `menu · work-2026….md`,
`muxtopus`, `settings`).

### 3.2 How the room is computed

`build()` composes the frame as today into a list of panels, then, ONLY when
a menu is open (the normal frame keeps its measured cost):

    used   = len(console.render_lines(Group(*kept), console.options))
    room   = console.size.height - used
    rows   = min(room, needed)          # needed = len(items) + 2 (border) + 1 (hint)

Nothing is estimated from row counts; what Rich will draw is what is
measured. The `Console` is created in `main()`; the Dashboard gets it at
construction (`--once` and the non-tty path pass the same one).

Which panels are `kept` depends on the layout:

* **`table`** (default) -- the panel the cursor is in stays, the menu goes
  directly under it, everything below is dropped while it is open. Cursor on a
  session: deck, lanes, claude, MENU. Cursor on a lane row: deck, lanes, MENU.
  Cursor on the extras row: deck, lanes, claude, uncommitted, system, MENU.
  Schedule view: the schedules table, MENU (the why panel and the questions
  panel are dropped -- the why sentence is IN the menu, §4a). The mux and
  settings menus are drawn under whatever panel the cursor is in.
* **`modal`** -- the whole frame is replaced by the menu centred
  (`Align.center(..., vertical="middle")`), its width the longest label plus
  chrome, capped to the console width. `room` is the full height.
* **`bottom`** -- today's position: the whole frame, the menu in place of the
  keys footer, capped to `room`.

### 3.3 The rule that makes "never clipped" true

    MENU_MIN = 6                        # border, ▲, one item, ▼, hint, border

If `room < MENU_MIN` under `table` or `bottom` -- a 24-row terminal with a
tall claude table -- that frame degrades to `modal`, which always has the full
height. If even the full height is under `needed`, the viewport scrolls; a
menu is never cut. The degrade is per frame and silent except for a dim
`(modal: no room below)` in the panel title, so the person learns why the
setting was not honoured this once.

### 3.4 Proof

Unit: `tests/test_menulayout.py` renders `menu_panel` for the 18-line session
menu and the schedule menu at every `rows` from 6 to 30 through a
`Console(width=120, height=rows)` and asserts the rendered line count equals
`rows`, the last line is a bottom border, the cursor line is present, and
the markers appear exactly when the maths says they should.

In the sandbox: a detached tmux server with `-x 160 -y 24`, then `-y 40`,
then `-y 58` (`tmux resize-window -y N` between runs), the dashboard driven
by `send-keys` only, and for each of the 3 layouts × 3 heights: open the
session menu on a row (the longest menu, with watchdog and monitor both OFF
so the two global lines are present), `capture-pane`, and a script asserts
the menu's `╰` border is in the capture, the `▸` line is in the capture, and
no line of the capture is a panel edge without its closing pair. Then the
same for the schedule menu on a blocked entry (the why line makes it the
longest). Eighteen captures for the session menu, eighteen for the schedule
menu, all kept in the scratchpad and named in the handover.

## 4a. Space in the schedule view (phase 3)

The bug, measured: the `view == "sched"` branch in `main()` has no `" "`
case, so space falls through to the global handler and opens
`menu_entries()` for the CLAUDE window under `self.cursor` over the schedule
view. Fix: `" "` in that branch opens `self.menu = {"kind": "sched", "i": 0}`;
`menu_entries()` for that kind is `sched_menu_entries()`, built from
`self._sched_sel()` and nothing else -- it never reads `self.cursor`, so
nothing in it can act on a session.

For a normal entry `r`:

    [disabled] <why sentence>                 only when verdict is blocked / waiting / stalled
    Edit <file>                               request_edit_selected  (e)
    Options <file>                            reopen_options (o); disabled "only a pending entry" otherwise
    Launch now                                launch_selected_now (l); disabled unless pending
    Duplicate as a new pending entry          new
    Check: resolve it and show the report     new: runs --check --body, shown full screen
    Open its window ➥<slug>                   only when launched and the tree's window id is live
    ·······
    Delete <file>                             confirm_delete_selected (d), danger

For a corrupted entry (`r["bad"]`): the reason as a disabled row, a
separator, and Delete. Nothing else -- as decided. (`e` on the keyboard still
opens the editor, which is how you fix one; the menu does not offer it.)

**Duplicate** copies the file to `<stem>-copy.md` (then `-copy2` and so on),
sets `status: pending`, clears `launched:`, stamps `created:`, appends
` copy` to the title so the derived slug differs from the original's, and
REMOVES a pinned `slug:` line for the same reason -- two entries with one slug
are one window and one handover. The notice says the slug line was dropped,
and the editor opens on the copy so the title can be fixed at once.

**Check** runs `claude-watchdog.sh [--profile P] --check <file> --body`
(timeout 10 s) and hands the text to the main loop through `pending_report`,
shown exactly the way HELP is: `live.stop()`, clear, print, `read_key(120)`,
`live.start()`. It is the `k` idea from the improvements handover, on a menu
row instead of a key.

**Open its window** resolves `read_tree()[slug]["wid"]` and runs
`tmux select-window -t <wid>`; the row is absent when there is no live window
rather than disabled, because "open" of a window that exited is not a thing
the row can promise.

The why panel under the table stays as it is; the sentence is duplicated
into the menu because that is the question in front of the row.

## 4b. `c` in the main view: a new claude session (phase 4)

`c` is free in the main view. `start_new_session()` chains the existing
picker and prompt submodes -- nothing new in the input layer except one
picker extension, `"none": True`, which starts the cursor off the list (drawn
with no `▸`) and makes Enter say `pick one` until an arrow has moved it. That
is what "nothing preselected" means for an arrow-driven list.

The screens, in order, each a method `_ns_<n>` that stores its answer in
`self.ns` (a dict) and opens the next:

1. **Working folder** -- picker. Candidates, deduplicated, in this order: the
   cursor session's cwd, `DASHBOARD_NEW_CWD`, every live session's cwd, every
   path in `repos.tsv` (the dirty trees the watchdog publishes), the
   immediate subdirectories of `MUXTOPUS_HOME`'s parent that contain `.git`
   (one `scandir`, once per open), and `other… (type a path)`, which opens the
   prompt. Any answer is checked with `is_dir()`; a miss says
   `not a directory: <path>` and reopens the prompt with the text kept.
2. **Model** -- picker: `(account default)` then the `choices:` of
   `options.md`'s `model` block (CLI aliases -- `--model opus-5` is refused by
   the CLI and kills the window after the paste, measured today); the five
   aliases are the fallback if the block is missing or broken. Preselected
   from `DASHBOARD_NEW_MODEL`.
3. **Effort** -- picker: `(account default)` then the `effort` block's
   choices, fallback `low medium high xhigh max`. Preselected from the setting.
4. **Permission mode** -- picker over `PERM_MODES`, preselected from
   `DASHBOARD_NEW_PERMISSION_MODE`, or `"none": True` when it is `ask`. If
   the choice is `bypassPermissions`, a second picker:
   `this window only` / `…and make it the default (writes settings.json)`.
   The second opens the confirm below.
5. **Where** -- picker: `a top-level window`, then one row per live session
   with a pane, `under <window name>`. A parent writes
   `window: <tmux name>` and `parent: <lane slug>` (`lane_slug_of`), which is
   what the launcher's `subtree_last_index` and `tree_wname` turn into the
   `➥➥<slug>` window inserted after the parent's subtree and drawn indented.
6. **Name** (added, fork Q1) -- prompt, prefilled with the folder's basename;
   sanitised with `sanitise_slug`, refused if empty or if a pending or
   launched entry already resolves to that slug (`resolve_slug` over
   `read_schedules()`), because two entries with one slug share a window
   name and a handover.
7. **First prompt** -- prompt, may be empty.

Then `_ns_write()` writes ONE file, `SCHEDULES_DIR/new-<slug>.md`:

    type: work                    (plan when the prompt is empty -- fork Q2)
    at: 2026-09-16 10:15          now, to the minute: already past, as `l` does it
    title: <name>
    slug: <slug>                  pinned, so the window is named what was typed
    window: <parent tmux name>    only with a parent
    parent: <parent slug>         only with a parent
    cwd: <folder>
    model: <alias>                only when chosen
    effort: <level>               only when chosen
    permission-mode: <mode>       only when chosen
    watchdog: off                 only when DASHBOARD_NEW_WATCHDOG is off
    monitor: off                  only when DASHBOARD_NEW_MONITOR is off
    status: pending
    created: 2026-09-16 10:15
    launched:
    ---
    <first prompt>

The dashboard calls no `tmux new-window`. The watchdog's next pass (≤30 s)
does the trust dialog, the readiness wait, the bracketed paste, the tree row,
the footer and the log line -- none of it reimplemented here. The notice says
`scheduled ➥<slug> — the watchdog opens it within ~30s`, and the schedule
view shows it as `due` until then.

### The two new headers, on the launcher's side

`watchdog: off` and `monitor: off` are read by `launch_schedule` after the
readiness loop: the pane id is known, `$MUX_CONFIG_DIR/sessions/*.json`
carries `.tmux` ending in that pane id, so the session id is one `jq` away;
it is appended to `optout` / `monitor-optout` exactly as `--optout` and
`--monitor-optout` do it, and logged (`schedule x: session abcd1234 opted out
of the watchdog`). If no session file names the pane within a few seconds the
launcher logs that it could not and moves on -- the window is open and
watched, which is today's default. `--check` prints both fields. This is the
one piece of work in another file (see §7).

### The bypass warning and the ONE write

Choosing `…and make it the default` opens the confirm:

    ⚠ writes  "permissions": { "defaultMode": "bypassPermissions" }  to <exact path>
      EVERY future Claude session there skips permission prompts,
      including ones nothing is watching.      y write   n this window only

`<exact path>` is `settings_json_path(DASHBOARD_PERMANENT_MODE_SCOPE, folder)`:
`<folder>/.claude/settings.json` or `~/.claude/settings.json` (the account's
`CONFIG_DIR`, so a named account writes its own). `y` calls
`muxsettings.set_default_mode(path, "bypassPermissions")` -- the ONE
implementation, which the Settings menu does not expose separately but which
is where any second entrance goes. `n` continues with the window-only mode.

`set_default_mode`: read the file if it exists; if it exists and is not valid
JSON, refuse with `not valid JSON, not touched: <path>: <error>`; otherwise
set only `permissions.defaultMode` (creating `permissions` if absent), write
to `<path>.tmp` with 2-space indent and a trailing newline, copy the old file
to `<path>.bak-<YYYYmmdd-HHMMSS>` beside it, `os.replace`. Every other key is
preserved byte-for-byte in value (a JSON round trip may reorder nothing: keys
are written in the order read). If the file did not exist, the directory is
created and there is no backup to make, and the message says `created`.
The Settings menu's `where "make it permanent" writes` row is the only knob.

## 4c. The options table's keys (phase 5)

The user's decision supersedes QUESTIONS-sched-options-table §1, and the file
gets the answer recorded under the question.

* **ESC cancels everywhere.** `open_options` loses its `esc` parameter. In
  the create flow ESC now calls nothing: `_create_write` is what writes the
  file and it is not reached, so no entry exists -- `cancelled, nothing
  written`. On reopen: `unchanged`.
* **Action rows at the bottom**, after a dim `ACTIONS` heading, in this order:
  `check all` · `uncheck all` · `continue — save what is ticked` (`save` on a
  reopen) · `skip — continue with nothing ticked` (create flow only: on a
  reopen "nothing ticked" is `uncheck all` then `save`, and a row that means
  "save an empty set" beside a row that means "save" would be the trap the
  user just removed). `option_rows` appends them as `{"act": ...}` rows;
  `options_move` treats them as selectable; Enter on one does it.
* **Enter on an option row toggles** (fork Q3), since `continue` is now a
  row. Space still toggles.
* Footer: `↑↓ pick · space toggle · enter choose · esc cancel`. HELP's table
  section and the README's options subsection say the same.

## 5. Verification

Everything runs in a sandbox shaped exactly as the three previous lanes':
own `HOME`, `XDG_CONFIG_HOME`, `XDG_STATE_HOME`, `MUXTOPUS_CONFIG` (whose file
pins `MUXTOPUS_HOME` under the sandbox), `CLAUDE_CONFIG_DIR` under the sandbox
home, a `tmux` wrapper on `PATH` pinned to `-L mxdash`, and a fake `claude` on
the sandbox `PATH` that records its argv, prints a `❯` prompt, and -- new --
writes `$CLAUDE_CONFIG_DIR/sessions/<pid>.json` with `sessionId`, `pid`,
`cwd`, `version`, `status` and `tmux` (the pane id from `$TMUX_PANE`), so the
sandbox watchdog lists it in `status.tsv` and the opt-out mapping can be
proven. The sandbox dashboard runs in the sandbox tmux session and is driven
only by `send-keys`, read only by `capture-pane`. Nothing touches tmux
session `claude`, `claude:0` is never sent a key and R is never pressed on it.

Per phase:

1. Settings round trip: for every key, `put` then a fresh `muxconfig.settings`
   and the shell's `mux_load_config` both read the written value; a bad value
   is refused with the complaint and the file is unchanged; the `.tmp` never
   survives; `profiles/<name>.dashboard.conf` wins over `dashboard.conf` for a
   named account and the hand-written `profiles/<name>.conf` wins over the
   shared `dashboard.conf`. The key-list and `PERM_MODES` mirror tests. In the
   sandbox dashboard: ESC opens the menu (capture shows `muxtopus`), the two
   toggles flip the state files and the row labels, Settings changes the
   layout and the capture shows the file's new line, Disconnect is verified
   with an attached sandbox client (`tmux -L mxdash attach` in a background
   `script` pty) that is gone afterwards while the windows are not, Reload
   re-execs (a marker in the sandbox copy of the script proves the new code is
   running), Quit exits.
2. §3.4 -- 36 captures, asserted by script, plus the unit test.
3. Space on a schedule row shows `menu · <file>` and no session name; every
   row fires: duplicate produces the copy with the dropped `slug:` line and
   the editor opens on it; check shows the report full screen; open-its-window
   moves the sandbox client; delete confirms and removes; the corrupted entry
   shows the reason and only delete; a blocked entry shows the why sentence
   greyed.
4. The `c` flow end to end: seven screens by `send-keys`; a non-directory
   refused; the written entry byte-compared against the expected header; the
   sandbox `--daemon` opens `➥➥<slug>` after the chosen parent's subtree with
   the fake `claude` recording `--model opus --effort high --permission-mode
   bypassPermissions`; with `DASHBOARD_NEW_WATCHDOG=off` the sandbox `optout`
   gains the fake session's id and `status.tsv` shows the dot. The JSON
   write: against a project file with three other keys (preserved, `.bak`
   beside it, `permissions.defaultMode` set), against a missing file
   (created), against a file containing `{not json` (refused, untouched,
   message names the path). `ask` leaves the mode picker with no `▸`.
5. ESC on the create table leaves `schedules/` without a new file; the four
   action rows each do what they say; `tests/test_entry_options.py` still
   passes.
6. `--check` on every real entry of both accounts still returns 0 with no new
   warning (reading only). README, HELP, `setup-schedules.py`'s generated
   schedules README (the two new headers, owned by the sub-lane).
   `docs/dashboard.svg` is NOT regenerated by this lane: `make-screenshot.py`
   captures the real `claude:0`, which runs the pre-change script until the
   user presses R, and a screenshot of the sandbox would show fake data. Owed
   to the user after their R, and said so in the handover.

## 6. Forks taken (recorded in QUESTIONS-dash-menus-settings.md, provisional)

* **Q1 -- a name screen in `c`.** (a) RECOMMENDED: ask, prefilled with the
  folder's basename, refused on collision. (b) derive silently from the
  folder. Why (a): the slug is the window name, the handover file and the
  argument to `handover.sh done`; a second window in the same folder under (b)
  would collide and the person would only find out in the schedule view.
* **Q2 -- an empty first prompt.** (a) RECOMMENDED: write `type: plan` with
  no template, which the executor accepts and which pastes only the identity
  line, so the session knows its lane and spends one trivial turn. (b) refuse
  an empty prompt. (c) write `type: work` with a one-line placeholder body.
  Why (a): "may be empty" is in the brief, the executor's rule for `work` is
  older and right, and (c) invents text the person did not write.
* **Q3 -- Enter on an option row.** (a) RECOMMENDED: toggles, now that
  `continue` is a row. (b) keeps meaning continue. Why (a): one key, one
  meaning per row; the footer says it.
* **Q4 -- the dashboard file's precedence** (§2.1): above the hand-written
  file at the same scope, below the account's hand-written file. Stated with
  the reasoning; the brief said "the existing precedence", which does not
  place a new layer, so this is the one interpretation that makes the round
  trip hold.

## 7. Phases, commits, and the sub-windows

One commit per phase, `[feat] <phase>: …`, body bullets on what, why and what
was run.

| phase | commit subject (lowercase summary) | files |
|---|---|---|
| 1 | `esc menu + settings store: dashboard.conf, round-tripped` | `deck_status.py`, `muxsettings.py` (new), `muxconfig.py`, `profile.sh`, `tests/test_settings.py` (new) |
| 2 | `menu layouts: table, modal, bottom, measured against the terminal` | `deck_status.py`, `menulayout.py` (new, from the sub-window), `tests/test_menulayout.py` |
| 3 | `schedule view: space opens the entry's own menu` | `deck_status.py` |
| 4 | `c: a new claude session, written as a due schedule entry` | `deck_status.py`, `muxsettings.py` |
| 5 | `options table: esc cancels, continue/skip/check all as rows` | `deck_status.py`, `~/.code/handovers/QUESTIONS-sched-options-table.md` |
| 6 | `[docs] dashboard menus: README, help, schedules README` | `README.md`, `deck_status.py` (HELP) |

**Sub-windows.** Two windows editing `deck_status.py` is the one thing to
avoid, so every phase that touches it stays here, and the sub-windows own
files this lane never opens for writing:

* `➥➥➥dash-menus-layout-engine` -- **`model: opus`**. Owns `menulayout.py`
  and `tests/test_menulayout.py`: `menu_viewport`, `menu_panel`, the
  `MENU_MIN` rule, and the height proof over `Console(height=N)` for N in
  6..30 with the two longest menus as fixtures. This is the one genuinely
  hard design in the brief -- the viewport with markers inside the budget,
  the exact-height contract, and the degrade rule -- and it is pure, so it
  can be built and proven without the dashboard. Phase 2 here is then wiring
  plus the 36 sandbox captures. Spawned at the start of phase 1; phase 2
  waits on it via `after:` if it has not landed.
* `➥➥➥dash-menus-wd-headers` -- default model (mechanical, not hard). Owns
  `claude-watchdog.sh` (the `watchdog:`/`monitor:` headers in
  `launch_schedule`, the `--check` lines), `setup-schedules.py` (the
  generated schedules README) and the README's schedule field block. Verified
  in its own sandbox with the session-file-writing fake `claude`. Phase 4 here
  writes the headers regardless; the end-to-end opt-out proof waits on this
  lane landing, and is listed as owed if it has not.

Everything else -- the settings store, the JSON write, the schedule menu, the
`c` flow, the options-table rows -- is either in `deck_status.py` or is a
small module with a contract that has to match the dashboard's calls exactly,
and stays in this window.
