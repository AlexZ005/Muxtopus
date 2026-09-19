---
title: Restore after a lost server
nav_order: 8
---
{% raw %}
# Restore after a lost server

A tmux server can die: a reboot, an out-of-memory kill, or — measured here on 2026-09-19 — a `tmux kill-server` typed inside a pane by a session that meant a test sandbox and hit the real server, because inside a pane `$TMUX` names the server and `TMUX_TMPDIR` is ignored. Every lane window and every Claude session in them went in one second. The transcripts survived; the *arrangement* did not: which window ran which session, in which folder, with which flags, under which parent.

The watchdog outlives the server (a `systemd --user` unit, or a nohup'd process), so it is the thing that remembers. Every pass it writes a snapshot of the session's windows; when the session disappears, the last snapshot is frozen rather than overwritten; and `muxtopus` can rebuild the windows from it, each one running `claude --resume` on the session it had.

```bash
muxtopus                          # no session, a fresh snapshot: "restore K windows from <ts>? [Y/n]"
muxtopus --restore                # rebuild from the frozen snapshot, then attach
muxtopus --restore FILE           # from a particular snapshot (a declined one, an older copy)
muxtopus -l                       # ...SNAPSHOT column: "K windows, frozen at <ts>"
claude-watchdog.sh --restore      # the same, into a session that already exists
```

## The snapshot

`~/.local/state/claude-watchdog[-<account>]/windows.tsv`, rewritten atomically once per pass, one row per window of the account's session in index order:

```
#seen   <epoch>
window-id  index  name  cwd  pane-id  session-id  parent  model  effort  permission-mode  source  pid
```

- **cwd** is the Claude session's own working folder when the pane carries one, else the shell's.
- **session-id** and **pid** come from the session files Claude Code keeps (`sessions/<pid>.json`, whose `tmux` field names the pane); `-` for a window with no session.
- **parent** is the window's parent slug from [the window tree](schedules.md#the-window-tree), `-` for a root.
- **model**, **effort**, **permission-mode** are read from the claude process's own command line (`/proc/<pid>/cmdline`, where a scheduled window's `--model fable --effort high --permission-mode bypassPermissions` sits verbatim), and failing that from the schedule entry that launched the window. A window opened by hand as bare `claude` has neither, and `-` is right: it comes back the same way.
- **source** is the entry file that launched it, `(adopted)`, `(restored)`, or `-`.

## The freeze

A pass that finds **no session** does not write an empty snapshot. If `windows.tsv` exists it becomes `windows.last.tsv`, headed `#lost <noticed> <last-seen>`, and the live file is removed. One log line says so, and one alert goes to [the phone](notifications.md) under the `MUXTOPUS_NOTIFY_SESSION` switch — once per loss, not once per pass, and "cleared" when the session is back. A reboot looks the same as a kill from here, and is offered the same way.

`WATCHDOG_RESTORE=auto` goes one further: the moment the session is found missing, the daemon runs `muxtopus -d` for the account, which (under `auto`) restores every window before returning.

## The restore

For each row, in saved order:

1. A window at the saved index when that index is free, else appended — so the order holds either way and a subtree stays contiguous. The saved name; the saved cwd, or `$HOME` with a log line when the folder is gone.
2. `claude --resume <session-id>` with the saved model, effort and permission mode when the session's transcript still exists; otherwise a plain shell in the right folder, and the log says which session had no transcript.
3. The launcher's own recipe — answer the trust dialog, wait for `❯`, one bracketed paste — hands each resumed session one line: `[muxtopus] restored after the tmux server was lost at <ts>; carry on`.
4. Every `➥` window is recorded in `tree.tsv` with its saved parent, so the dashboard's tree is what it was.

The `status` window is skipped (`muxtopus` makes the dashboard itself), and so is any row whose session is already live in this account, so running a restore twice cannot resume a session twice. On success the frozen file becomes `windows.restored.tsv`; the log holds one line per window and a summary.

## The offer

Plain `muxtopus` (no `-d`) that finds no session and a `windows.last.tsv` younger than `WATCHDOG_RESTORE_MAX_AGE` hours (24) asks at the terminal. `n` renames the file `windows.declined.tsv`: it is not asked about again, `muxtopus -l` says `declined`, and `muxtopus --restore <path>` still takes it. `muxtopus -d` never asks: it obeys `WATCHDOG_RESTORE` — `auto` restores, `ask` and `off` make the session as before. The dashboard's `esc` menu shows `Restore K windows from <ts>` while a frozen snapshot exists.

| key | default | |
|---|---|---|
| `WATCHDOG_RESTORE` | `ask` | `ask` · `auto` · `off` — see [Configuration](configuration.md) |
| `WATCHDOG_RESTORE_MAX_AGE` | `24` | hours a frozen snapshot is offered for |

## So it does not happen again

- **Every tmux call names its server.** `profile.sh`'s `mux_tmux` passes `-L <name>` (or `-S <path>`) from `MUXTOPUS_TMUX_SOCKET` on every call `muxtopus`, the watchdog, the usage probe and the test sandbox make. With `-L` or `-S` given, tmux does not consult `$TMUX`, so a sandbox's server and the real one are two different arguments rather than two different environments. The default, `default`, is the socket a bare `tmux` uses outside tmux; nothing changes for anyone who never set the key.
- **Every lane is told.** The identity lines pasted into a `➥` window gain a sentence: inside this window `$TMUX` overrides `TMUX_TMPDIR`, a sandboxed tmux needs `-S`/`-L` or `env -u TMUX`, and a bare `tmux kill-server` kills *this* server.
- **A test forbids it.** `tests/test_tmux_guard.py` fails the suite on a `tmux kill-server` or `kill-session` anywhere in the repository that is not `mux_tmux` or an explicit `-L`/`-S`, on any bare `tmux` at all in the files that drive the real server, and on a test sandbox that wraps `tmux` without also naming its socket to the scripts.
- **A daemon never inherits a pane's `$TMUX`.** `muxtopus` starts a nohup'd watchdog under `env -u TMUX`, and the daemon drops the variable itself at start.

## What is not restored

Pane splits, scrollback and shell history: a window here is one pane running claude, and the transcript is the state. Windows of other sessions on the same server. A second account's windows from one daemon — one watchdog, one account, one snapshot.
{% endraw %}
