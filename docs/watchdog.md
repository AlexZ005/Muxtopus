---
title: The watchdog
nav_order: 7
---
{% raw %}
# The watchdog

Poll loop, 30 s (`WATCHDOG_INTERVAL`), one daemon per account. It notices a window that stopped at a usage limit, waits for the reset, and types the continue prompt into that pane. Between passes it publishes what it saw — one row per session, a verdict per pending schedule entry, the window tree, the usage reading, a heartbeat — into its state directory, and the dashboard only reads.

```bash
claude-watchdog.sh --status            # the table it publishes
claude-watchdog.sh --dry-run           # one pass, act on nothing
claude-watchdog.sh --once              # one pass, for real
claude-watchdog.sh --check [name]      # resolve schedule entries, launch nothing
claude-watchdog.sh --check <slug>-     # ...every entry of a wave (a prefix ending in -)
claude-watchdog.sh --tree              # the window tree it keeps
claude-watchdog.sh --profile work ...  # any account
claude-watchdog.sh --on | --off        # arm / disarm (or `w` on the dashboard)
claude-watchdog.sh --reload            # re-read the config now
```

It is a `systemd --user` unit where systemd exists (`claude-watchdog.service`, `claude-watchdog-work.service`), otherwise a plain background process. That process's pid file is `muxtopus-wd.pid` in `$XDG_RUNTIME_DIR` when that directory is yours, and in a private `/tmp/muxtopus-<uid>/` otherwise, which is what `su user` needs, since it keeps root's runtime dir. With lingering on it starts at boot; see [After a reboot](install.md#after-a-reboot).

## What a pass does

1. Reads every session file Claude Code keeps for this account and pairs each with its tmux pane, so every row knows its window, its context, what it spent and how long it has been idle.
2. Captures every **idle** pane once and reads the text: a usage-limit banner makes the window `limited` with its reset time; a permission or trust prompt seen on two consecutive passes makes it `waiting` (`needs you` on the dashboard, a message on the phone).
3. When armed, prompts a `due` window — one whose reset time has passed — with the continue message, once per limit. It never types into a window that is working.
4. Judges every pending [schedule entry](schedules.md) and launches the due ones: the trust dialog, the readiness wait, one bracketed paste, a row in the tree, a log line naming which gate fired.
5. Writes the **window snapshot** — one row per window of the session, with its Claude session id, cwd, parent and launch flags — or, when the session is gone, freezes the last one instead of overwriting it, and says so once (log and phone). [Restore after a lost server](restore.md) is what that buys.
6. Publishes the rows, the verdicts, the tree and the heartbeat; refreshes the usage reading when it is older than `WATCHDOG_USAGE_EVERY` minutes; every five minutes collects into [the stats ledger](stats.md); once a day asks whether there is a [newer muxtopus](updates.md); and sends what changed to [the phone](notifications.md).

Every action is logged with the reading that decided it. Disarmed, the panel still reports; nothing is sent to any pane.

## Limits

An `idle` window that hit a limit is prompted to continue once its reset time passes, once per limit. Measured twice: `autoContinueAtUsageLimit` does not resume after the 5-hour session limit, and `/loop` dies on its first refused wakeup — see [why this exists](index.md#why-this-exists).

> **Honest limitation.** Detecting a limit means reading the TUI's own banner out of the pane. That text is not an API, and a redesign upstream can change it. It has been wrong once already in a way worth knowing about: a limit resetting on the hour prints `resets 7pm` with no `:00`, and a pattern that required `H:MM` left every on-the-hour limit parked for hours while off-hour ones resumed correctly. The parser handles both now, and `--dry-run` will tell you what it currently sees.

`space` on a dashboard row excludes one session (the checkmark becomes a dot); `--optout <id>` does the same from the shell, and a schedule entry's `watchdog: off` does it at launch. The choice lives in the watchdog's own file, so it holds whether or not the dashboard is open.

## Session monitoring: the wind-down bands

**Session monitoring** is a separate power with its own switch (`m`, `--monitor-on` / `--monitor-off`), off by default. The watchdog *restarts* a window that already stopped, which cannot lose anything. Monitoring speaks to a window that is still **working**, asking it to commit and write a handoff before the budget runs out — so it is opt-in on its own.

It is delivered through a `PostToolUse` hook (`claude-winddown-hook.sh`), so it reaches a session mid-turn without typing into a pane that is busy composing. Two bands, as a share of the session budget:

| band | default | what the session is told |
|---|---|---|
| soft | past `WATCHDOG_SOFT_PCT` (65 %) | stop spawning subagents |
| hard | past `WATCHDOG_HARD_PCT` (85 %) | checkpoint: commit what you have, write the handoff, and stop |

**The hard band only fires when it buys something** — a context bigger than `WATCHDOG_FRESH_CTX` (150,000 tokens), so restarting fresh from a handoff beats carrying on, or a weekly budget above `WATCHDOG_LOWPRI_WEEK` (40 %) so `/low-priority` cannot carry the session through. Otherwise the window is left to reach the limit banner, which costs nothing.

The session is never told *why*. It receives an instruction, not a budget negotiation; the reasoning is logged instead: the dashboard's WOUND column says when a window was last asked to wrap up, and the log carries the reading that decided it. `monitor: off` on a schedule entry, or the second switch in a row's menu, exempts one session.

### Resuming a wind-down

A hard wind-down is an instruction to **stop**, and for a long time nothing started the window again. The restart path above fires only for a pane whose text says `hit your session limit`, and a window that stopped *because it was told to*, before it ever reached the limit, never prints that banner; the wind-down writes no schedule entry either. The one mechanism that would resume it keyed off a condition its own directive guaranteed would never occur.

Measured on 2026-09-20: window `muxtopus-updates` was wound down at band 2 at 12:25 for the budget window resetting at 12:45, stopped at 12:32 with an open handover saying "Resume after the session reset", and was still idle at 13:10 with nothing due to touch it. `stranded` would eventually have *reported* it after two hours; reporting is not resuming.

So the hard band now arms its own resume. A session gets the same continue message the limit path sends — once, under the same `prompted` ledger — when **all** of these hold:

- it was wound down at **band 2** (band 1 is a note about style; the window keeps working through it);
- it is **idle** now, with a pane to type into — never one that is working, and never a background job;
- the **budget window recorded with the wind-down has come back** (`now ≥ epoch + 20 s`, the epoch being the quantized `session_reset_at` the directive named);
- its **handover is still open** — `STATUS-<slug>.md` exists and is not in `done/`. The directive told the worker to write that file and then stop, so an open one is the window saying there is more to do and a `done` one is `handover.sh done` having been run. A finished lane is never poked;
- it has not already been prompted for that budget window. The two paths key the window differently — the limit path by the epoch in the banner, this one by `session_reset_at` rounded to a quarter hour — so they are compared with a quarter hour of tolerance. Real limit windows are five hours apart, so the two can never both fire for one reset.

`--optout`, a **monitoring** opt-out taken since (the wind-down was the monitor's doing; taking the window out of its hands afterwards reads as "leave this one alone") and the global `w` switch all stop it, exactly as they stop the limit path.

**It is visible before it fires.** The state reads `resume due` on the dashboard and in `--status` from the moment the epoch passes, and `--dry-run` prints `WOULD-RESUME` in the action column. `WATCHDOG_WOUND_RESUME=off` turns the whole thing back into the old behaviour.

## Scheduled windows

The daemon is the only launcher: the dashboard's `c` flow, a hand-written entry and a `Schedule resume` from a row's menu all write a file into the schedules folder and the next pass opens it. The format, the fields and the verdicts are on [Scheduled windows](schedules.md); the two things the daemon decides are here.

### `at: reset` is two gates

An entry fires on whichever comes first:

1. **the budget reads fresh** — `session_pct <= 10`. A rolling five-hour window that has just rolled has no reset time at all, so a barely-touched budget is due on its own.
2. **the window rolled over** — `now >= session_reset_at + 20s`, whatever the budget then reads.

The launch line names which one fired. A budget *reading* older than `WATCHDOG_USAGE_STALE` (default 180 min) cannot fire gate 1 — the bucket refills over five hours, so a three-hour-old percentage says nothing about now. The reset *epoch* is exempt: it is an absolute moment. An entry that cannot be judged at all — no usable reading — is `stalled`, drawn red, and the daemon asks for a fresh `/usage` probe (at most one per quarter hour) to clear it.

### `stranded`

Not a field: a **state** the watchdog publishes for a window, beside `working`, `idle`, `limited`, `waiting` and `due`. A lane is called `stranded` instead of `idle` when all of these are true:

- it is idle — not mid-turn;
- it has been idle for at least `WATCHDOG_STRANDED` minutes (default 120);
- it has an **open** handover — `handovers/STATUS-<slug>.md`, not one in `done/`, so there is unfinished work;
- and **no** pending entry in the schedules folder names it: not its slug, not the `resume-<slug>.md` the dashboard's "Schedule resume" writes, not an `after:` waiting on it, nor a `window:` or `parent:` that will open under it. A wave orchestrator that has ended its turn with its lanes and its integrate entry still pending under it is waiting for them, not stranded.

`idle` is a fact about the last turn — the same word for a lane that finished ten minutes ago and for one that stopped mid-phase three days ago with its handover half-written. Measured: four lanes sat at `idle 3d` with open handovers, nothing pending named any of them, and nothing anywhere said so.

**It is a fact shown to a human, never a trigger.** It is derived only from `idle`, and the restart path only ever acts on `due`, so a stranded window is never prompted by it; the cure is to write an entry for it (or mark the handover done). `WATCHDOG_STRANDED=0` turns it off. One log line when a window becomes stranded and one when it stops being stranded — not one per pass. It is also one of the things [the phone is told](notifications.md).

## The window snapshot

Every pass the session is there, `windows.tsv` is rewritten: one row per window of the account's tmux session, in index order, with the window's name, cwd, pane, the Claude session id in it, its parent slug from the tree, and the model, effort and permission mode it was launched with (read from the claude process's own command line, else from the schedule entry that opened it).

A pass that finds **no session** never writes an empty snapshot. The live file becomes `windows.last.tsv`, headed with the time the loss was noticed and the time the session was last seen; one log line says so; one alert goes to the phone under `MUXTOPUS_NOTIFY_SESSION`, keyed on the last-seen time so it is said once per loss and "cleared" when a session is back. `WATCHDOG_RESTORE=auto` makes the daemon run `muxtopus -d` there and then, which restores the windows. Everything else — the offer at start, `muxtopus --restore`, what a window comes back as — is on [Restore after a lost server](restore.md).

## The usage probe

Claude Code has no usage subcommand and no file holding live limit state, so `claude-usage.sh` starts a throwaway session on the account, sends `/usage`, scrapes the pane and kills it — about four seconds, no turn taken, no completion tokens. The watchdog runs it every `WATCHDOG_USAGE_EVERY` minutes (60) and on a `stalled` verdict; the dashboard's `u` runs it when the reading is older than `CLAUDE_USAGE_MAX_AGE` (20). Every reading is stamped with the time it was taken and appended to `usage.log`, and a failed read leaves the last good numbers alone and says `stale`.

The probe is a tmux session, and a tmux session does not inherit the environment of whatever created it, so the account is handed in explicitly — the [one rule](accounts.md) every launcher here follows.

## What it publishes

All of it in `~/.local/state/claude-watchdog[-<account>]/`, read by the dashboard and by nothing else that forks:

| file | |
|---|---|
| `status.tsv` | one row per session: id, window, pane, context, state, reset, what was spent, model, idle seconds, cwd, wound-at, opt-outs, pid |
| `sched-why.tsv` | one verdict per pending entry: `due` · `waiting` · `blocked` · `stalled`, with its sentence |
| `tree.tsv` | the window tree: slug, parent, window id, pane id, launched-at, entry file |
| `windows.tsv` | the window snapshot, rewritten every pass the session is there; `windows.last.tsv` is the frozen one after a loss, `windows.restored.tsv` / `windows.declined.tsv` what became of it |
| `usage.tsv` | the last usage reading and when it was taken |
| `repos.tsv` | the dirty working trees it swept |
| `heartbeat` | proof of life; the dashboard calls it "watchdog not running" past 75 s |
| `enabled`, `monitor` | the two switches |
| `optout`, `monitor-optout` | the session ids excluded from each |
| `prompted`, `wound` | which limit each session was last prompted for, and when each was last asked to wrap up |
| `notify/` | what the phone has already been told, so nothing is said twice |
| `log`, `usage.log`, `notify.log` | the record: every action with the reading that decided it |

The [release check](updates.md) is the one thing on that list it does **not** keep here: there is a single installed tree, so its answer lives in `~/.local/state/muxtopus-update/` with no account suffix, and whichever account's daemon gets there first does the asking.
{% endraw %}
