# Plan: muxtopus survives its tmux server dying

Status: PLAN, 2026-09-19, lane `mux-restore`. Executed phase by phase below,
one commit per phase, on `feat/mux-restore`. Locate by symbol, not by line.

Read before this: `docs/plan-dashboard-split.md` (the codebase shape),
`docs/schedules.md` and `docs/watchdog.md` (what is extended),
`claude-watchdog.sh` around `launch_schedule`, `tree_record`,
`sched_pane_sid` and `tree_adopt`.

## 0. The incident, and what it says about the design

2026-09-19 09:04. A Claude session in the ➥scripts window ran
`TMUX_TMPDIR=$SB/sock tmux kill-server` to clean a test sandbox. Inside a
pane `$TMUX` is set, and tmux takes its socket from `$TMUX` whenever neither
`-S` nor `-L` is given; `TMUX_TMPDIR` is ignored. It killed the real default
server: the dashboard, every ➥ lane window and five Claude sessions, in one
second (journal: every tmux-spawn scope ended 09:04:12; no OOM, no reboot).
Three sandbox watchdogs it had nohup'd survived, one carrying the real
`$TMUX`. The user relaunched `muxtopus` by hand and dug session ids out of
`~/.claude/projects` to resume. Nothing in muxtopus noticed, said anything,
or could put the windows back.

Three separate failures, three separate fixes, in the order that matters:

1. **Nothing remembered the windows.** The watchdog outlives the server (a
   systemd unit, or a nohup'd process) and already walks every session and
   every window each pass. It is the thing that should keep the record.
2. **Nothing could rebuild them.** The launcher already knows the recipe for
   getting a window to a prompt and handing it text; it only ever applied it
   to new schedule entries. The same recipe with `--resume <sid>` is a
   restore.
3. **Nothing stopped the kill.** Every tmux call in the repo relied on the
   environment to find the server. One helper that always names the socket
   makes the sandbox's server and the real server two different arguments
   rather than two different environments.

## 1. The snapshot (watchdog)

### 1a. The file

`$MUX_STATE/windows.tsv`, rewritten atomically (`.tmp` + `mv`) once per
pass, one row per window of `$MUX_TMUX`:

    #seen <TAB> <epoch>
    window-id <TAB> index <TAB> name <TAB> cwd <TAB> pane-id <TAB> session-id
      <TAB> parent-slug <TAB> model <TAB> effort <TAB> permission-mode
      <TAB> source <TAB> claude-pid

- `window-id`, `index`, `name`, `pane-id`: from one `list-windows` call on
  `$MUX_TMUX` (`#{window_id} #{window_index} #{window_name}
  #{pane_current_path} #{pane_id}`), in index order.
- `cwd`: the claude session's `cwd` from `sessions/<pid>.json` when the pane
  carries one, else `#{pane_current_path}` (a plain shell window).
- `session-id`, `claude-pid`: the pass loop already pairs every live session
  file with its pane (`.tmux` ends in the pane id); it fills two associative
  arrays on the way past, so the snapshot costs no extra fork per window.
  `-` when the pane carries no session.
- `parent-slug`: column 2 of `tree.tsv` for the row whose window id matches;
  `-` for a root or a window the tree does not know.
- `model`, `effort`, `permission-mode`: from `/proc/<pid>/cmdline` of the
  claude process first (it is what actually ran: `--model fable --effort
  high --permission-mode bypassPermissions` is there verbatim on this
  machine for every scheduled window), else from the schedule entry that
  launched it (`tree.tsv` column 6 → `$MUX_SCHEDULES/<file>` → `sched_field`).
  A window launched by hand as bare `claude` has neither, and `-` is right.
- `source`: the entry file basename from `tree.tsv`, `(adopted)`,
  `(restored)`, or `-`.

**Why TSV.** Every file the watchdog publishes is TSV (`status.tsv`,
`tree.tsv`, `sched-why.tsv`): awk and bash builtins read it, the dashboard's
`data.py` splits it, and a row is one `printf`. A json file would need `jq`
on the writing side of a 30-second loop for no reader that wants it. Tabs
and newlines are stripped from names and paths on the way in.

**Why a header line.** The freeze (1b) has to carry two times, and a second
file for two numbers is one more thing to keep in step. Readers skip `#`.

### 1b. The crux: a pass that finds no session must not write an empty one

`snapshot_windows` runs after the session loop, once per pass:

- session present → write `windows.tsv`; remove `windows.lost` marker if any.
- session absent and `windows.tsv` exists → **freeze**: rewrite it as
  `windows.last.tsv` with the header `#lost <TAB> <now> <TAB> <last seen
  epoch>` (the live file's `#seen`), delete `windows.tsv`, one log line
  (`tmux session 'claude' is gone: froze K windows last seen at <ts> into
  windows.last.tsv`), and one alert through the existing path:
  `notify_alert "server:lost" "<last-seen-epoch>" "$MUXTOPUS_NOTIFY_SESSION"
  ...`. The fingerprint is the last-seen epoch, so the dedupe in `sent.tsv`
  sends it once per loss, not every 30 s; when the session is back the key
  ends and the phone gets "cleared", as every alert does.
- session absent and no `windows.tsv` → nothing (already frozen, or never
  seen). The alert key stays alive while `windows.last.tsv` exists and the
  session is absent, so a daemon restart re-sends nothing.

`WATCHDOG_RESTORE=auto` adds one step to the freeze: run `muxtopus -d`
(profile carried) which, under `auto`, restores from the frozen file
(§2c). Synchronous inside the pass, so two passes cannot restore twice.

### 1c. What survives a restore

A successful restore renames `windows.last.tsv` to `windows.restored.tsv`
(the record of what was put back; overwritten by the next one). A declined
offer (§2b) renames it to `windows.declined.tsv`: it is not offered again,
`muxtopus -l` says `declined`, and `muxtopus --restore <path>` still takes it.

## 2. Restore

### 2a. The shared recipe (watchdog)

`launch_schedule` holds the only working recipe for "open a window running
claude and hand it text": `new-window -d -P`, poll `capture-pane` for the
trust dialog (Down, Enter) and then for `❯`, `load-buffer` +
`paste-buffer -p`, Enter. It is factored into two functions used by both
the launcher and the restore, not copied:

    pane_ready PANE [TRIES]      -> 0 once ❯ is on screen; answers the trust
                                    dialog once on the way; sets PANE_TRUSTED
    pane_paste PANE FILE         -> bracketed paste of FILE, one Enter

`launch_schedule` calls them and behaves byte-for-byte as before
(`tests/test_sched_rc.sh` and `test_notify_*.sh` are the proof).

### 2b. `claude-watchdog.sh --restore [FILE]`

A new MODE beside `--tree` and `--check`. FILE defaults to
`$MUX_STATE/windows.last.tsv`. Requires the session (`muxtopus` makes it);
for each row in file order, skipping `status` (muxtopus recreates the
dashboard) and any row whose session id is already live in this account:

1. `new-window -d -P -t "$MUX_TMUX:<index>"` when that index is free, else
   appended -- saved order either way, saved indices when possible, so a
   subtree stays contiguous. `-n <name> -c <cwd>`; a cwd that no longer
   exists falls back to `$HOME` with a log line.
2. The command: `claude --resume <sid> [--model] [--effort]
   [--permission-mode]; exec bash` when the session id has a transcript
   (`transcript_of`), else `exec bash` -- the window comes back as a plain
   shell in the right cwd and the log says `no transcript for <sid>`.
3. For a claude window: `pane_ready`, then `pane_paste` of one line,
   `[muxtopus] restored after the tmux server was lost at <ts>; carry on`.
   A window that never reaches a prompt is logged and left as it is (claude
   exited to the shell, or is still starting).
4. `tree_record <slug> <parent> <wid> <pane> "(restored)"` for every ➥
   window (slug = name minus the arrows), parents included, in file order,
   so `tree.tsv` has the same links it had.
5. One summary log line: restored K, plain P, skipped S, and the file is
   renamed `windows.restored.tsv`.

### 2c. `muxtopus`

- `muxtopus --restore [FILE]`: make the session with the `status` window only
  (no default `claude` window: the snapshot has the real one, with its
  session id), run `claude-watchdog.sh --restore`, then attach (or print the
  session name under `-d`).
- plain `muxtopus` that finds **no session** and a `windows.last.tsv`
  younger than `WATCHDOG_RESTORE_MAX_AGE` hours (default 24): under
  `WATCHDOG_RESTORE=ask` (default) it asks `restore K windows from <ts>?
  [Y/n]` at the terminal; `auto` restores without asking; `off` never
  offers. `n` renames the file `windows.declined.tsv` and the session is
  made as before.
- `muxtopus -d` never asks: `auto` restores, `ask`/`off` do not.
- `muxtopus -l` gains a SNAPSHOT column: `K windows, live`, `K windows,
  frozen at <ts>`, `K windows, declined`, or `-`.

### 2d. The dashboard

`dashboard/menus/mux.py`: a row `Restore K windows from <ts>` in the esc
menu, present only while `windows.last.tsv` exists (so the goldens, taken
with none, are unchanged), behind a confirm; it runs
`claude-watchdog.sh --restore` detached, and the notice says where the log
is. `data.py` gets `frozen_snapshot()`; the HELP section gains a paragraph.

## 3. The guard

- **(a) one helper.** `profile.sh` gains `mux_tmux()`: `command tmux
  "${MUX_TMUX_SOCK[@]}" "$@"`, where `MUX_TMUX_SOCK` is `-L <name>` or `-S
  <path>` from the new key `MUXTOPUS_TMUX_SOCKET` (default `default`, which
  is the socket the bare command resolves to when `$TMUX` is unset:
  `$TMUX_TMPDIR/tmux-<uid>/default`). With `-L` or `-S` given, tmux ignores
  `$TMUX`, so a call from inside a pane reaches the named server and no
  other. Every tmux call in `muxtopus`, `profile.sh`, `claude-watchdog.sh`,
  `claude-usage.sh` and `tests/sandbox/*.sh` goes through it; the sandboxes
  export `MUXTOPUS_TMUX_SOCKET=$SANDBOX_SOCKET` (their `bin/tmux` wrapper
  stays for the direct calls tests make). The daemon also unsets `TMUX` and
  `TMUX_PANE` at start: it never needs them.
- **(b) the identity lines.** `sched_compose` gains one sentence: inside
  this window `$TMUX` overrides `TMUX_TMPDIR`, so a sandboxed tmux needs
  `-S`/`-L` or `env -u TMUX`, and a bare `tmux kill-server` kills THIS
  server.
- **(c) the test.** `tests/test_tmux_guard.py` (pure python, in CI): fails
  on any `tmux kill-server` / `tmux kill-session` in command position that
  is not `mux_tmux` or `tmux -L`/`-S`, in every `.sh`, `.py`, `muxtopus` and
  test file; and on any bare `tmux` in command position at all in the five
  files of (a).
- **(d) no inherited `$TMUX`.** `watchdog_up` starts the nohup'd daemon
  under `env -u TMUX -u TMUX_PANE` (the scripts lane's commit `03ac570` does
  this; taken as given on rebase) and the daemon unsets them itself.

## 4. Config keys

| key | default | |
|---|---|---|
| `WATCHDOG_RESTORE` | `ask` | `ask`: `muxtopus` offers a frozen snapshot at a terminal; `auto`: restore without asking, and the watchdog relaunches `muxtopus -d` when the server disappears; `off`: never offer, `--restore` still works |
| `WATCHDOG_RESTORE_MAX_AGE` | `24` | hours; a frozen snapshot older than this is not offered (`--restore` still takes it) |
| `MUXTOPUS_TMUX_SOCKET` | `default` | the tmux server every muxtopus command talks to: a `-L` name, or an absolute path for `-S` |

Added to `MUX_CONFIG_KEYS`, `muxconfig.KEYS`, `mux_key_help`, and
`docs/configuration.md`; `tests/test_settings.py` mirrors them.

## 5. Phases, file by file

| phase | files | proof |
|---|---|---|
| 0 | `docs/plan-restore.md` | this |
| 1 guard | `profile.sh` (`mux_tmux`, key, help), `muxtopus`, `claude-watchdog.sh` (every call, `unset TMUX`, identity sentence), `claude-usage.sh`, `tests/sandbox/env.sh` `stop.sh` `start.sh` `k.sh` `type.sh` `cap.sh` `notify.sh` `handovers.sh` `insights.sh`, `tests/notify_sandbox.sh`, `muxconfig.py`, `tests/test_tmux_guard.py`, `.github/workflows/tests.yml`, `docs/configuration.md` | the guard test; `test_settings.py`; `test_sched_rc.sh` unchanged and green |
| 2 snapshot | `claude-watchdog.sh` (`snapshot_windows`, the freeze, the alert, `auto`), `tests/test_restore.sh` (§1), `docs/watchdog.md` | a pass writes the rows; the server killed (by `-L`) freezes, does not clobber, logs once, notifies once across two passes |
| 3 restore | `claude-watchdog.sh` (`pane_ready`, `pane_paste`, `--restore`), `muxtopus` (`--restore`, the offer, `-d` + `WATCHDOG_RESTORE`, `-l`), `tests/test_restore.sh` (§2) | order, names, cwds, parents, the flags on the fake claude's argv, the note in its keys, the plain window for a dead sid, `-d` under each mode |
| 4 dashboard + docs | `dashboard/menus/mux.py`, `dashboard/data.py`, `tests/test_dashboard_app.py` or a new small test, `docs/restore.md`, `docs/index.md`, `docs/watchdog.md`, `docs/configuration.md`, `changes/mux-restore.md` | `test_names.py`, `test_manual.py`, goldens identical |

## 6. Out of scope

- The dashboard's own tmux calls (`data.live_windows`, Disconnect, close
  window): it runs inside a pane of the real session, where `$TMUX` is
  exactly the right server. `muxtelegram.py`'s `send-keys` likewise runs
  from the daemon with no `$TMUX`. Both keep the sandbox wrapper for tests.
- Restoring pane splits, scrollback, or a window's shell history: a window
  is one pane running claude, and the transcript is the state.
- Restoring `cc-usage` probe sessions or a second account's session from one
  daemon: one watchdog, one account, one file.
- A snapshot of windows in sessions other than `$MUX_TMUX`.
