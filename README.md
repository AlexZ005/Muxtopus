# Muxtopus

**Run several Claude Code sessions side by side in tmux — one per account — and stop losing work to usage limits.**

![The dashboard](docs/dashboard.png)

One command opens a tmux session for an account, brings up that account's watchdog, and lands you on a live dashboard of every lane you have running. Everything on screen is read from local files and tmux panes: nothing here calls an API, and watching costs no tokens.

---

## Why this exists

`autoContinueAtUsageLimit` does not resume after the 5-hour session limit. Measured twice on the same machine, the second time under clean conditions: a session started fresh with the setting armed hit the limit at 09:42, the limit reset at 12:40, and it was still idle at 13:39.

The reason is visible in the transcript. The limit is written as a `<synthetic>` assistant message with `read=0` and the turn marked **done** — the CLI *ends* the turn rather than parking it, so there is nothing left for auto-continue to resume. `/loop` has the same hole from the other side: a refused turn never reaches the call that schedules the next wakeup, so one refusal kills the loop permanently.

So the only thing that reliably restarts the work is something **outside** Claude Code. That is the watchdog.

The second half of the problem is accounts. A personal and a work account on one machine want two of everything — two budgets, two reset times, two sets of sessions — and a single shared state directory will happily hand one account's reset time to the other account's window.

---

## Install

```bash
git clone https://github.com/AlexZ005/Muxtopus.git ~/src/muxtopus
cd ~/src/muxtopus
./install.sh
```

The installer symlinks `muxtopus` into `~/.local/bin`, writes a config file, creates the data folders and offers to install the watchdog. Nothing is written outside your home directory, and it prints every path before it touches anything.

```bash
./install.sh --dry-run        # print what it would do and stop
./install.sh --home ~/.code   # put schedules/backups/handovers somewhere else
```

> **One name on `PATH`, and it is `muxtopus`.** Not `mux`, which is already several other tools, and never `cc`: on any machine with a C toolchain that is the C compiler, and a `cc` link on `PATH` breaks every native build. Shorthands belong in your shell rc, where they reach an interactive prompt and nothing else:
>
> ```sh
> alias cc='muxtopus'
> alias cw='muxtopus --profile=work'
> ```

**One word per account, over SSH.** `muxtopus` reads the name it was invoked by, so a symlink named `muxtopus-acme` is `muxtopus --profile=acme` — which is what a `RemoteCommand` has room for. Aliases are not expanded in a non-interactive shell, so over SSH the command is spelled out:

```
ssh deck -t 'bash -lc muxtopus'                     # personal
ssh deck -t 'bash -lc "muxtopus --profile=work"'    # work
```

**Requirements:** `bash`, `tmux` ≥ 3.2 (for `new-window -e`), `jq`, `git`, `python3` ≥ 3.9 with [`rich`](https://github.com/Textualize/rich) for the dashboard, and the `claude` CLI. `systemd --user` is used for the watchdog when present; without it the daemon is started as a plain background process instead.

---

## Quick start

```bash
muxtopus                          # personal account, session "claude"
muxtopus --profile=work           # work account   (~/.claude-work)
muxtopus -w                       # the same, shorter
muxtopus --profile=acme           # any account    (~/.claude-acme)
muxtopus infra ~/src/infra        # a named session in a directory
muxtopus -w infra ~/src/infra     # both
muxtopus -r                       # start Claude with the resume picker
muxtopus -d --profile=acme        # create it and return, for scripts
muxtopus --create --profile=acme  # a new account, without being asked first
muxtopus -l                       # list accounts, sessions and watchdogs
muxtopus -c [--profile=acme]      # the effective configuration of an account
```

A new session gets two windows: **0** is the dashboard, **1** is Claude. You land on 0, so the state of the machine is the first thing you see; `Ctrl-b 1` switches to Claude and `Ctrl-b 0` comes back. Re-attaching returns you to whichever window you left.

**`Ctrl-b w` lists this account's windows only.** Both accounts share one tmux server, and the stock binding lists every session on it — reading the work account's windows off the personal session is exactly the confusion the suffix exists to prevent. The shipped `tmux.conf` filters the chooser to the session you pressed the key in; `Ctrl-b W` is the unfiltered tree, and `f` inside the chooser edits the filter live (empty it to see everything). A filter hides rows; it does not stop you acting on the other account. If the accounts must never be able to touch each other, run them on separate servers with `tmux -L` instead.

`muxtopus -l` is the one-glance answer to "what is running":

```
ACCOUNT      SESSION                  LOGGED-IN  WATCHDOG
personal     claude (6w)              yes        running
work         claude-work (2w)         no         running (disarmed)
```

### Adding an account

Creating the directory is the entire opt-in — nothing has to be registered anywhere. Naming an account that does not exist yet **asks first**, because a typo in `--profile` used to silently create a config dir, three folders and a systemd unit:

```bash
$ muxtopus --profile=acme
muxtopus: there is no account 'acme' (~/.claude-acme).
          accounts on this machine: personal work
create it? ~/.claude-acme, ~/.code/{schedules,backups,handovers} and a disarmed watchdog [y/N] y
```

Without a terminal (a script, an SSH `RemoteCommand`) the answer is no unless `--create` is passed. Once created, log in inside window 1.

The watchdog for a brand-new account is installed **disarmed** and stays that way until the account logs in. Arming it earlier would have it restart windows into a login screen, and its usage probe would start a doomed session every hour.

---

## One account, one of everything

A profile is the suffix on the Claude config dir. **The default account takes no suffix**, which is the whole migration story: a single-account machine sees no change at all.

| | personal | work |
|---|---|---|
| Claude config | `~/.claude` | `~/.claude-work` |
| tmux session | `claude` | `claude-work` |
| schedules | `$MUXTOPUS_HOME/schedules` | `…/schedules-work` |
| backups | `$MUXTOPUS_HOME/backups` | `…/backups-work` |
| handovers | `$MUXTOPUS_HOME/handovers` | `…/handovers-work` |
| …or, with its own `MUXTOPUS_HOME` in `profiles/work.conf` | | `<that home>/{schedules,backups,handovers}` |
| watchdog state + usage cache | `~/.local/state/claude-watchdog` | `…-work` |
| systemd unit | `claude-watchdog.service` | `claude-watchdog-work.service` |

`muxtopus` puts `CLAUDE_CONFIG_DIR` into the tmux **session** with `-e`, not merely into its own process. **A tmux session does not inherit the environment of whatever created it** — it starts from the server's, which belongs to whichever account happened to start the server first. Exporting is therefore not enough, and anything that opens a `claude` under tmux has to hand the account in explicitly: `muxtopus` for its windows, the watchdog for a restarted one, `claude-usage.sh` for its throwaway probe.

**The default account is the variable being absent**, not the variable pointing at `~/.claude`. Claude Code keeps the default account's onboarding and auth state in `~/.claude.json`; set `CLAUDE_CONFIG_DIR` and it looks for `<dir>/.claude.json` instead, which does not exist — so "helpfully" naming the path that account already uses shows a fully logged-in machine the theme picker and the login menu. Named accounts have no such history and always carry the variable.

**One watchdog per account, not one that watches both.** Every figure it judges a session against — session budget, weekly budget, reset time — belongs to a single account. A shared daemon would have to carry two of everything anyway, and could still hand one account's reset to the other account's window.

---

## The dashboard

`Ctrl-b 0`. Everything is read from local files; the process never forks per frame.

**The lanes table is this account's by default.** A dev server belongs to the account whose session started it, read off `CLAUDE_CONFIG_DIR` in its environment — which it keeps even after the window that started it is gone, so a daemonised server is still attributed correctly. The panel title says how many servers belong to other accounts; `f` shows them all, each labelled.

| key | |
|---|---|
| `↑` `↓` | pick a session, a lane above them, or the extras row below |
| `enter` | open that session's window (`Ctrl-b 0` comes back) |
| `space` | menu for the session under the cursor |
| `esc` | the muxtopus menu: Settings, the watchdog and monitor switches, disconnect, reload, quit |
| `c` | a new claude session — folder, model, effort, permission mode, where, name, first prompt |
| `f` | lanes: this account only / every account (enter on a lane row does the same) |
| `s` | scheduled windows — and, on `←`/`→`, the handovers beside them |
| `i` | insights: what was used, and what it would have cost |
| `w` | arm / disarm the watchdog |
| `m` | session monitoring (wind-downs) on / off |
| `u` | read usage limits (refreshes if older than 20 min) |
| `U` | force a usage read now |
| `r` / `R` | redraw / reload the script |
| `p` | btop |
| `?` | help |
| `q` | quit |

The **menu** (`space`) carries two per-session switches and then everything you can do to that window: open, rename, wind it down now, resume it now, continue it at low priority, schedule a resume at the next reset, or close it.

The **muxtopus menu** (`esc`) is what is not about one row: **Settings**, the watchdog and monitor switches by their full names (`w` and `m` stay the fast path), **Disconnect** (`tmux detach-client`; the dashboard and every window keep running, `muxtopus` attaches again), **Reload** (what `R` does) and **Quit**. Settings are written to `~/.config/muxtopus/dashboard.conf` (`profiles/<name>.dashboard.conf` for a named account), a file the dashboard owns — see [Configuration](#configuration) — and every one is read back from disk before it is reported as saved: the menu layout, the permission mode, model and effort preselected for a new window, whether such a window is watched and monitored, the working folder offered first, and which `settings.json` "make it the default" writes to.

**Menus are never clipped.** The room under the panels is measured from the terminal (what Rich will actually draw, not a row count) and the menu scrolls inside it with `▲ N more` / `▼ N more` markers. The `table` layout (default) keeps the panel the cursor is in and draws the menu right under it, dropping what is below while it is open; `modal` centres the menu alone; `bottom` is the old position, capped. With fewer than six lines left, a frame degrades to modal for that one open and the title says so.

**A new claude session** (`c`) asks seven things through the picker and the prompt — the working folder (it must exist), the model as a CLI *alias* (`opus`, `fable`, `sonnet`…: `--model opus-5`, the MODEL column's spelling, is refused by the CLI and kills the window after it has eaten the paste), the effort, the permission mode (preselected from Settings, or nothing preselected when that says `ask` — a default, never a lock), where it goes (a top-level window, or under a live one as `➥➥name`, inserted after that parent's subtree), the name (the slug), and an optional first prompt — and then **writes a schedule entry** with `at:` already past. It opens no window itself: the watchdog's next pass does the trust dialog, the readiness wait, the bracketed paste, the tree row and the log line, exactly as for any entry. The entry carries `model:`, `effort:`, `permission-mode:`, `cwd:`, `parent:`/`window:`, and `watchdog: off` / `monitor: off` when Settings says a new window is not watched or monitored. An empty prompt writes a `plan` entry: the session receives its identity line and nothing invented.

Choosing `bypassPermissions` also offers *…and make it the default*. A confirm names the exact `settings.json` (the project's `<cwd>/.claude/settings.json` or the account's, per Settings) and what changes — **every future Claude session there skips permission prompts, including ones nothing is watching**. The write merges `permissions.defaultMode` into the existing JSON (nested, where Claude Code reads it), keeps every other key in place, backs the old file up beside itself, and refuses a file that is not valid JSON. It lives in one place, `muxsettings.py`, whoever asks for it.

### Panels

- **deck** — memory, swap, CPU, and the usage limits top right.
- **lanes** — dev servers by port, with age and whether the tree is dirty.
- **claude** — one row per session: context used, tokens spent, idle time, state, when it was last wound down and when it was last resumed. The account name appears in the title once you have more than one. A scheduled window that has been idle past `WATCHDOG_STRANDED` (default 120 min) with an open handover and nothing pending that names it reads **`stranded`** rather than `idle` — see below.
- **uncommitted** — its own table rather than a column, because dirty trees and sessions do not line up: a repo can be dirty with no session and no dev server near it, and that is the copy most likely to be lost.

### Handovers and questions (`s`, then `→`)

The `s` screen has two tabs and the arrows move between them. The strip names
both and carries their counts, so from the schedules you can still see how
many handovers are open and how many question files are waiting on you.

    ╭ schedules 6 │ ▸handovers 4 open · 3 ? ─────────────────── ←→ tab ╮
       STATE      AGE   LANE                    WINDOW   HOLDS  SAID
     ▸ ? ask      2h    handover-visibility     @31 ●    —      3 forks · 1. Filter persistence
       open       12m   dash-menus-settings     @24 ●    1      Phase 2 done; 36 captures green
       open ⚠     3d    27-hardening            —        —      Handoff — roadmaps 25-27 hardening
       done       1d    sched-options-core      exited   —      Finished. All six phases done

The rows are every `STATUS-*.md` and `QUESTIONS-*.md` of this account, from
both folders, in the order of **what is owed**: unanswered questions first,
then open handovers, then everything finished. The cursor starts at the top,
which is the actionable end.

| column | |
|---|---|
| `STATE` | `? ask` a question file with no ANSWERED marker · `? done` one that has · `open` a handover its lane has not marked done · `done` one it has |
| `open ⚠` | **red**: the watchdog calls that window `stranded`. **yellow**: a `done/` twin of this file from an earlier run already satisfies every `after: <slug>` — the lane ran, was marked done, and is running again. The detail panel says which file, in words |
| `WINDOW` | the window the lane was launched in, `●` while it is still open |
| `HOLDS` | how many PENDING entries are waiting on this lane. The entry always knew; the lane never did |
| `SAID` | the handover's first useful line, or `N forks · <the first one>` |

| key | |
|---|---|
| `enter` | on a question file: **the answer screen**. On a handover: read-only, in the pager |
| `e` | edit a question file |
| `E` | edit a handover *anyway* — behind a warning when its lane's window is still open and whichever of you saves last would win |
| `space` | the row's menu: view, edit anyway, open its window, mark done, mark answered, tell that window its answers are in, show its handover |
| `f` / `a` | show or hide everything finished / the question rows. Both are remembered — `R` re-execs the dashboard and would otherwise reset them every time |
| `r` | re-read the folder |
| `←` `→` | back to the schedules |

**Marking a handover done from here launches things.** Every entry held
`after:` that lane fires within 30 seconds, so the confirm names them:
`Mark dash-split done?  releases: handover-vis-impl, notify-dash`. Every
state change shells out to `handover.sh`, so never-clobber and the ANSWERED
marker have one implementation and not two.

**Answering a fork without leaving the dashboard.** `enter` on a question
file opens its forks one at a time — the lettered options as rows with the
recommended one already picked, the fork's full text above them, and the
editor one key away on every screen, because no parser will understand every
lane's prose and the file is always the escape hatch. A chosen option may
take a note; enter with nothing typed means no note. Each answer is written
the moment you give it, as one line at the end of its own fork:

    **Answer (user, 2026-09-18):** (a) — because it reads left to right

atomically, and onto the file that was parsed: if the lane rewrote it
meanwhile the answer is re-applied to the same fork and the screen says so.
`esc` leaves at any point and what was answered stays answered. When the last
fork is answered it offers to mark the file ANSWERED and, if that lane's pane
is live, to tell it so.

**On the main view**, a session whose lane has an unanswered question file
carries a yellow `?` beside its name and the key line says how many are
waiting in all. That reads the same two folders, at most once every five
seconds, so the main frame pays a glob and no fork.

### Insights (`i`)

What was used, from a ledger muxtopus keeps itself. Claude Code deletes a
transcript after `cleanupPeriodDays` (30 by default), so "everything to date"
only exists because something read it first: the watchdog collects into the
ledger every five minutes, and the view collects again when you open it.

Eight rows of figures — **tokens** (total, in/out/cache, thinking share, per
active hour), **cache** (share served from cache, 5 m vs 1 h writes, what it
saved), **cost**, **context** (average per request, average session peak as a
share of the window, sessions past 80 %, compactions), **sessions** (count,
median and longest *active* time, turns, subagent share, tool calls and the
top five tools), **budget** (5-hour limit hits, time spent limited, resumes,
wind-downs, week % at each weekly reset), **lanes** (launched, done, median
launch-to-done, deepest tree, forks asked and answered, stranded) and
**rhythm** (by weekday and by hour, busiest day and hour, active-day streak,
this period against the last one) — and one breakdown table under them.

| key | |
|---|---|
| `←` `→` | the period: today · this week · last 7 d · this month · last 30 d · all |
| `g` `G` | what the table is grouped by: project, model, lane, day, week, month, session, main/subagent |
| `↑` `↓` | pick a row |
| `enter` | drill in — a project into its sessions, a session into its days |
| `⌫` | climb back out |
| `f` / `F` | filter by project, model, lane or main/subagent, and clear it |
| `a` | this account / every account's ledger merged |
| `e` | export this exact screen as `.md`, `.csv` and `.json` |
| `r` | collect now |
| `i` / `esc` | back |

The same report on the command line, with the same numbers: `muxtopus stats
-h`.

**Honest about thin data.** The title always says *collecting since &lt;date&gt;*, and
a figure that needs a distribution — a median, "vs previous", the month
projection — reads `— needs 7 days` until the ledger has seven. Days
backfilled coarsely from Claude Code's own cache count toward totals only. A
new install shows a correct sparse screen on day one, not zeros dressed up as
findings.

**`$` figures are API-equivalent, never money spent.** They are what the same
tokens would cost on the Claude API at the list prices in
`~/.config/muxtopus/prices.md` — a subscription paid none of it. That file is
yours: the installer copies `seeds/prices.md` into place **only if it is
missing** and never rewrites it, one block per model with the date the numbers
were copied at the top, shown beside every figure. A model the file does not
name shows `no price` rather than a guess, and with no file at all the view
shows tokens only.

#### What the ledger stores, and how to forget it

**Counts only. No prompt, no reply, no tool input, and no file name other than
the project directory is ever written to it.** A row is a day, a session id, a
project directory, a lane slug, a model id, main-or-subagent, and numbers:
requests, tokens in and out, cache reads and writes, thinking tokens, context
totals, tool-call counts, tool *names*, web searches, turns, active seconds
and compactions. Beside it: one row per 5-hour budget window, one per weekly
reset, one per lane, and an index of truncated hashes that is how a message
split over nine lines is counted once.

It lives in `~/.local/state/muxtopus/stats/` (`stats-<account>` for a named
account), it is **local and forever**, and **nothing is ever uploaded**. To
stop that:

```
muxtopus stats --forget                     # drop everything recorded so far
muxtopus stats --forget --before 2026-01-01 # drop everything before that date
```

Both record the cutoff, so a later collect will not count the same days again.
Your transcripts are not touched either way. Deleting the directory by hand
works too — the next collect starts a new ledger from whatever transcripts
still exist.

---

## The watchdog

Poll loop, 30 s. It notices a window that stopped at a usage limit, waits for the reset, and types the continue prompt into that pane.

```bash
claude-watchdog.sh --status            # the table it publishes
claude-watchdog.sh --dry-run           # one pass, act on nothing
claude-watchdog.sh --check [name]      # resolve schedule entries, launch nothing
claude-watchdog.sh --profile work ...  # any account
claude-watchdog.sh --on | --off        # arm / disarm (or `w` on the dashboard)
```

**Session monitoring** is a separate power with its own switch, off by default. The watchdog *restarts* a window that already stopped, which cannot lose anything. Monitoring speaks to a window that is still **working**, asking it to commit and write a handoff before the budget runs out — so it is opt-in on its own.

It is delivered through a `PostToolUse` hook, so it reaches a session mid-turn without typing into a pane that is busy composing. Two bands: past 65% of the session budget the window is asked to stop spawning subagents; past 85% to checkpoint and stop. **The hard band only fires when it buys something** — a context big enough to be worth restarting fresh, or a weekly budget too spent for `/low-priority` to carry the session through. Otherwise the window is left to reach the limit banner, which costs nothing.

The session is never told *why*. It receives an instruction, not a budget negotiation; the reasoning is logged instead.

> **Honest limitation.** Detecting a limit means reading the TUI's own banner out of the pane. That text is not an API, and a redesign upstream can change it. It has been wrong once already in a way worth knowing about: a limit resetting on the hour prints `resets 7pm` with no `:00`, and a pattern that required `H:MM` left every on-the-hour limit parked for hours while off-hour ones resumed correctly. The parser handles both now, and `--dry-run` will tell you what it currently sees.

---

## Scheduled windows

One hand-editable `.md` per window to open later. The daemon launches due items and the dashboard's `s` view lists them.

```
type: work
at: reset
title: resume the checkout refactor
slug: checkout-refactor       # optional: pins the lane name
window: api-cleanup           # optional: insert the new window after this one
after: api-cleanup, db-migrate # optional: hold until ALL of those have finished
parent: api-cleanup           # optional: draw this window under that one
cwd: /home/you/src/checkout
model: opus                   # optional: claude --model
effort: high                  # optional: claude --effort
permission-mode: bypassPermissions   # optional: claude --permission-mode
watchdog: off                 # optional: never restart this session after a limit
monitor: off                  # optional: never wind this session down
options: questions, phases, lanes=3, model=opus[1m]   # written by the options table
status: pending
created: 2026-09-06 09:55
launched:
---
the prompt body that gets pasted into the new window
```

The new window opens right after its `window:` target, named with a leading `➥`, and the prompt lands as **one bracketed paste** — never `send-keys`, which submits at every newline. A file the view cannot parse is shown as corrupted with the reason and never launches.

### `permission-mode:`, the one setting that cannot be fixed after launch

A scheduled window is unattended by definition. Without this field the launcher passes no mode, so the window inherits `defaultMode` from settings.json — and a window in `auto` that reaches a decision it will not take on its own simply **stops**, silently, with no prompt anyone is there to answer. Measured 2026-09-16: that is how four lanes sat idle for three days.

Nor can it be corrected once the window is open: shift+tab cycles auto → manual → accept edits → plan → auto, and `bypassPermissions` is **not** in that cycle. The launch command is the only way in.

Accepted values are whatever `claude --permission-mode` takes at the installed version — today `acceptEdits`, `auto`, `bypassPermissions`, `manual`, `dontAsk`, `plan`. Case is folded to the CLI's spelling and the fold is logged; anything else is dropped with a log line and no flag, because `claude` exits 1 on an invalid mode and the window would then never reach a prompt. **Absent means absent** — no flag, the account's own setting — and that stays the default, because an unattended window that skips every permission check is a choice the entry should have to make out loud.

### `watchdog: off` and `monitor: off`

The dashboard's per-session opt-outs, for a window that should start out exempt. Only `off` (any case) opts out; anything else, or no line, is the default: covered. They are header fields the **launcher** applies, not something the dashboard writes at create time, because the opt-out files are keyed by session id and a session id does not exist before launch. Once the prompt is up the launcher finds the `sessions/*.json` whose `.tmux` names its pane, appends that id exactly as `--optout` / `--monitor-optout` do, and logs it; if none turns up within ~5s the window is left watched and the log says so. `--check` prints both.

### The schedule view's menu

`space` on an entry opens **that entry's** menu, drawn by the same never-clipped engine: the executor's *why* sentence first when the entry is blocked, waiting or stalled; edit; options (the table, pre-ticked from the header); launch now; duplicate as a new pending entry (a `-copy` title, a pinned `slug:` dropped so two entries never share a window name and a handover, then the editor); check (the `--check --body` report, full screen); open its window when it has one; delete. A corrupted entry gets its reason and only delete. Nothing in it acts on a claude session.

### The options table

Five sentences go into nearly every brief anyone writes — *don't ask questions, nobody is watching*; *one commit per phase*; *don't push*; *`/low-priority` on a limit*; *a change you never ran is not verified*. `c` now offers them as checkboxes between the template and the editor, and `o` reopens the table on a pending entry.

They come from `~/.config/muxtopus/options.md`, which is **yours**: one block per option, blank-line separated, the same `key: value` syntax as a schedule header, `#` comments anywhere. The comment block at the top of the file is the format spec. `install.sh` copies it from `seeds/options.md` in this checkout if it is missing, and never rewrites it after that; `profiles/<name>.options.md` overrides or adds to it **field by field** for one account.

```
key: questions            # the id in `options:`, [a-z0-9-]+, unique
group: contract           # the table's section heading
label: questions go to a file
hint: nobody is watching: QUESTIONS-{{SLUG}}.md, recommended answer
default: on               # ticked when the table opens
types: work               # optional: only offered for this type
line: Nobody is watching this window: do not ask questions. …
```

A tick writes one of two things: a **sentence**, appended to the body under a `## Options` heading at the end of it, or a **header field** — `set: model` with `choices:` opens the picker and writes `model:`, which the launcher passes as `claude --model`. `ask: number` (or `text`) collects a value on toggle and substitutes it into `{{VALUE}}`.

The actions are **rows** at the bottom of the table: *check all*, *uncheck all*, *continue* (save what is ticked, then the editor; *save* on a reopen) and, on create only, *skip* (continue with nothing ticked). `space` or `enter` ticks an option row; `enter` on an action row does that thing. **`esc` cancels** on create and on reopen alike: on create no entry file is written at all, on reopen the file is untouched.

The header also records `options: questions, phases, lanes=3`, and **that is the source of truth**. `o` reopens the table from it and regenerates the section, so a sentence edited by hand in that section is overwritten on the next save — move it above the heading (everything above is preserved byte for byte) or edit it in `options.md` where it came from.

Every other placeholder — `{{SLUG}}`, `{{WINDOW}}`, `{{HANDOVER}}`, `{{QUESTIONS}}`, `{{SCHEDULES}}`, `{{CWD}}`, `{{PARENT}}` — is written out **literally** and resolved when the prompt is pasted, because the slug does not exist while the table is open.

A block the reader cannot make sense of is shown greyed with its reason and cannot be ticked, exactly as a corrupted schedule entry is — it is never silently dropped. `python3 muxconfig.py --options` prints the same verdicts without a dashboard.

### The slug is the lane's name in four places

It names the window, the handover file, the `handover.sh done <slug>` the worker is told to run, and the entry in the window tree. It is derived from the title by replacing everything outside `A-Za-z0-9._-` with `-` and cutting to 22 characters, which is how `title: 27-storage wave 2` once became the slug `27-storage-wave-2` while the lane's own brief said `27-storage` — two handover files for one lane, nothing watching the one that was written, and no warning anywhere.

So `slug:` pins it and wins over the title; a title that does not survive the derivation unchanged is **warned about** in the log, in `--check` and on the dashboard row; and the resolved slug and full handover path are rendered **into the pasted body**, above everything else, saying they win over anything the brief names. A brief and the tooling can no longer disagree.

### `at: reset` is two gates

An entry fires on whichever comes first:

1. **the budget reads fresh** — `session_pct <= 10`. A rolling window that has just rolled has no reset time at all, so a barely-touched budget is due on its own.
2. **the window rolled over** — `now >= session_reset_at + 20s`, whatever the budget then reads.

The launch line names which one fired. An absolute time (`2026-09-06 14:30`, or anything `date -d` accepts) fires when it passes.

A budget *reading* older than `WATCHDOG_USAGE_STALE` (default 180 min) cannot fire gate 1 — the bucket refills over five hours, so a three-hour-old percentage says nothing about now. The reset *epoch* is exempt: it is an absolute moment.

### Every pending entry says why it has not fired

`due` · `waiting` · `blocked` · `stalled`, each with the sentence that explains it, republished every pass and rendered under the table in the `s` view.

`stalled` means it cannot be judged at all. That case used to be **silent and permanent**: an empty `session_pct` was coerced to 100 (failing gate 1) and an empty `session_reset_at` failed gate 2, so an unreadable usage cache made every `at: reset` entry undue *forever*, with no log line and no error. Now it is named, it turns the row red, and the watchdog asks for a fresh `/usage` probe to clear it.

```bash
claude-watchdog.sh --check                    # every entry
claude-watchdog.sh --check 27-storage         # one, by file, basename or slug
claude-watchdog.sh --check 27-storage --body  # ...and the exact paste
```

`--check` resolves an entry without launching anything: the parsed fields, the slug and where it came from, the window name, the handover path, the insert target resolved against the live session, the size of the paste, and the due verdict with its reason.

### A tree of windows

**tmux has no window hierarchy.** Its windows are a flat, indexed list per session — there is no parent to set and nothing to collapse. So the tree is *data* the scheduler keeps (`tree.tsv`: slug, parent, window id, pane id, launched-at) and the dashboard is the *view*.

Parentage fills itself in: `parent:` wins, and otherwise it is derived from `window:` whenever that names a live window — hand-made orchestrators included, which is how most lanes are actually launched. The named window is adopted as a root so the child has something to hang from, and a lane already recorded as a root is re-parented from its entry on the next pass, so an existing tree fills in without being rewritten. What the flat list *can* honour, it does — the depth rides on the name (`➥lane`, `➥➥child`) and a child is inserted after the last window of its parent's subtree, so a family stays contiguous.

In the dashboard, `←` folds a subtree (the parent shows `+N`), `→` unfolds it, `t` turns the ordering off. With nothing parented the table is exactly what it always was, sessions by context. `claude-watchdog.sh --tree` prints the tree from the shell.

### Placeholders in the body

Seven names are resolved when the body is *pasted*, over the template, the body and the work footer — never over the `[muxtopus]` identity lines, which are built from the resolved values already:

```
{{SLUG}}  {{WINDOW}}  {{HANDOVER}}  {{QUESTIONS}}  {{SCHEDULES}}  {{CWD}}  {{PARENT}}
```

The slug is not knowable when a body is *written* — least of all in a template shared by twenty entries — so a sentence that needs it carries a placeholder and the executor resolves it as the window opens. A name outside that table is left in the paste as literal text and warned about, in `--check`, in the log and on the dashboard row. `--check <entry> --body` shows the substituted paste.

### `model:` and `effort:`

`model: opus` becomes `claude --model opus`, `effort: high` becomes `claude --effort high` (`low` · `medium` · `high` · `xhigh` · `max`). Absent means the account default from `settings.json`; a value the CLI would reject is logged and dropped rather than passed through, because `claude` exits on a bad flag and the window would never reach a prompt.

### `after: <slug>[, <slug>…]`

Holds an entry until *every* named lane is done — each one's handover marked done by `handover.sh done`, or a window the tree knows about having exited without leaving an open handover. The verdict names the first lane still holding and how many are left (`blocked: waiting for 2 of 3 — next: 24-stars, handover open 31m ago`); `--check` prints the per-lane breakdown. A slug naming the entry's own lane is refused from any position. No timeout: a dependency that gives up and runs anyway is worse than one that waits, and the wait is visible with its reason.

### `stranded`, and why the orchestrator is a pattern rather than a process

An orchestrator doing two jobs at once — splitting a plan into lanes and writing their briefs, which needs a model, and noticing when a lane stops, which needs a clock — spends tokens on the second. Measured: four lanes settled into one state and stayed there for 3½ days, and the first change the watching loop saw woke the orchestrator to broadcast a pause to four windows, four turns for a message that said "do nothing". **So the liveness half belongs here, in a deterministic loop that costs nothing, and the judgment half belongs in a Claude window that stops between the two** — the window writes one entry per lane and one more with `after:` naming all of them, then ends its turn.

That needs the scheduler to say when a lane has gone quiet for good, which is what `stranded` is: a `➥` window, idle past `WATCHDOG_STRANDED` minutes, with an **open** handover, and no pending entry naming it — not its slug, not its `resume-` entry, not an `after:` waiting on it. `idle` is a fact about the last turn; `stranded` is a fact about the future, and it is shown to a human rather than acted on. Nothing automatically resumes a stranded lane: an unrequested turn is still a turn.

In the `s` view: `enter`/`e` edit · `c` create · `o` reopen the options table on the selected pending entry · `l` launch now · `d` delete · `r` reload · `s`/`esc` back.

---

## Handovers

When a window is asked to wrap up, it writes a handoff so the *next* window can start from three paragraphs instead of carrying a quarter-million tokens of context forward.

```bash
handover.sh list              # what is open, what is asked, how much is done
handover.sh show <name>
handover.sh done <name>       # finished: moves it to done/
handover.sh reopen <name>
handover.sh answered <name>   # that lane's QUESTIONS file is settled
handover.sh unanswer <name>   # ...it is not, after all
handover.sh --profile work list
```

A lane's **questions** live beside its handover, as `QUESTIONS-<slug>.md` in
the same folder — the path the `{{QUESTIONS}}` placeholder resolves to when
the window is launched, so the lane is told where to write them and the
dashboard knows where to look. A file is **answered** when some line of it
matches `ANSWERED`, which is what was already being typed by hand before
anything read it.

The file does **not** move when it is marked: `{{QUESTIONS}}` told that lane
that exact path and the lane reads its answers there. It travels with its
handover instead — `done` carries an answered one into `done/` and **leaves
an unanswered one**, because a finished lane's unanswered forks are still
owed a look. Adding a fork to a file that is already marked means deleting
the marker line; a new question under an old marker is one nobody will be
shown.

Three decisions worth stating, because all three were bugs first:

- **They do not live in the working tree.** A `STATUS-<window>.md` in the repo is scratch state under version control — and once a second account works the same repo, two windows of the same name overwrite each other's handoff without a word.
- **`done` moves, it does not delete.** A finished handoff is the record of what a lane actually did and costs nothing to keep. Moving it is also what makes `list` mean something: what is left in the folder is what is still owed. A repeated window name gets a timestamped second copy rather than erasing the first.
- **There is one definition of "open" and "done", and it is the executor's.** `after: <slug>` is satisfied by `done/STATUS-<slug>.md`, tested *before* the open file — so a lane that ran, was marked done and ran again is finished as far as every held entry is concerned, whatever its open handover says. The watchdog, the dashboard's WHY line and the handovers tab all call the same function now (`muxhandovers.lane_state`), and a test greps that order out of `claude-watchdog.sh` so the shell side cannot drift away from it. The tab draws that lane `open ⚠` and says which file is doing the releasing, because it is a real trap and hiding it was how it stayed one.

---

## Notifications, and answering from the phone

Three lanes once waited fifty-five minutes behind one window sitting on
`Do you want to proceed?`. The watchdog already captures every idle pane on
every pass, so noticing costs nothing; the only thing missing was somewhere
to say it. `claude-notify.sh` sends through **Telegram**, ntfy or Pushbullet,
and with Telegram the message carries buttons, so the answer can come back.

```bash
claude-notify.sh --setup      # the guide: backend, token, and your first START
claude-notify.sh --status     # which backend is configured, and when it last sent
claude-notify.sh --test
```

`--setup` is also `esc ▸ Settings ▸ Notifications ▸ Set up…` in the
dashboard, which opens it in a tmux window of its own because it waits for
you to press START in Telegram. It writes `~/.config/claude-notify.conf`
(`0600`; it holds a token, keeps the old file as a `.bak-<stamp>`), and that
file is per machine. What you are *told* is per account, in the settings
store, on the seven `MUXTOPUS_NOTIFY_*` keys above — the same menu writes
those.

**Four things, each its own switch, and each said once per occurrence rather
than once per pass:** a window waiting at a prompt (`needs you`, drawn yellow
on the dashboard too), a lane with unanswered questions, trouble (stalled,
errored, stranded, failed to launch, blocked too long), and a lane finished.
Every title starts with the account's label, so two accounts on one phone are
told apart.

**The phone can answer.** A waiting message carries **Yes · No · More**: Yes
sends `1`, No sends Escape, More sends the lines above the prompt box. The
pane is re-captured first and the keys are only sent if the *same* prompt is
still there, so an answer that arrived after you answered at the machine edits
itself to say so instead. `Yes, and don't ask again` is never offered from a
phone: approving one action is not the same as changing a policy.

**Or ask it, with every push switched off.** A push can be missed, muted or
dismissed, and a dismissed message takes its buttons with it — so the bot
also answers commands, registered in Telegram's own menu button:

| | |
|---|---|
| `/status` | per account: sessions by state, budget and reset, pending/blocked/stalled entries, open handovers, unanswered questions, watchdog heartbeat |
| `/pending` | everything actionable, **re-issued with fresh buttons**. The "I dismissed it" command |
| `/questions` | the unanswered QUESTIONS files and how many forks each has |
| `/blocked` | each entry that is not launching, with the scheduler's own why |
| `/windows` | one line per session; a `needs you` row brings its buttons |
| `/stats` | the usage ledger's totals; the buttons switch week / month / all |
| `/mute 2h`, `/unmute` | pushes off for a while; asking keeps working |

Re-issuing retires the old buttons and edits that message to `superseded`, so
a stale button can never fire twice. Only the configured chat is ever obeyed;
anything else is logged and dropped. There is **no webhook and no open port** —
the watchdog polls `getUpdates` once a pass, so an answer lands within about
30 seconds — and the two accounts' daemons share one lock, so one update is
handled exactly once.

Two honest limits. Pane text leaves your machine for the backend's servers
when `MUXTOPUS_NOTIFY_PANE_TEXT` is on, which is what that switch is for; and
nothing typed on a phone is ever run as a shell — a prompt answer is one of
two keys and nothing else. Answering a *fork* from the phone is the one piece
still to land: today a questions message tells you which file is waiting, and
you answer it in the dashboard.

---

## Configuration

Four layers of plain shell, all optional — two you write, two the dashboard writes. `profile.sh` sources them and `muxconfig.py` parses them against the same key list, so the shell half and the Python dashboard cannot disagree about where anything lives or what a knob is set to.

```
~/.config/muxtopus/config                           every account: paths and defaults
~/.config/muxtopus/dashboard.conf                   every account, written by the dashboard's Settings menu
~/.config/muxtopus/profiles/<name>.conf             one named account's overrides
~/.config/muxtopus/profiles/<name>.dashboard.conf   one account, written by that account's dashboard
```

The same keys mean the same thing in all of them; the per-account files only narrow the scope. Precedence, lowest first: built-in default, environment, `config`, `dashboard.conf`, `profiles/<name>.conf`, `profiles/<name>.dashboard.conf`. The dashboard-written file sits **above** the hand-written one at the same scope — the menu is where a value was set most recently and most explicitly, and what it writes must be what is read next — and **below** the account's own hand-written file, the existing rule. It is a separate file because `config` is yours and full of your comments, and a program that rewrote it would eventually eat them; the dashboard rewrites its own file whole, atomically, and only reports a setting as saved once it has read it back from disk. **There is no registry of profiles** — an account exists because `~/.claude-<name>` does, and its `.conf` describes it rather than creating it; a second list would only ever drift from the first. The default account has no name and no `.conf`: the shared file *is* its configuration, and named accounts layer on top.

| key | default | |
|---|---|---|
| `MUXTOPUS_HOME` | `${XDG_DATA_HOME:-~/.local/share}/muxtopus` | where schedules/, backups/ and handovers/ live. In a profile file: that account's **own** home, with the three folders unsuffixed inside it |
| `MUXTOPUS_DIR` | the checkout `muxtopus` resolves to | only needed when `muxtopus` was copied rather than symlinked |
| `MUXTOPUS_SESSION_PREFIX` | `claude` | tmux session name, suffixed per account |
| `MUXTOPUS_QUESTIONS_DIR` | | where autonomous plan sessions park their questions (dashboard) |
| `WATCHDOG_INTERVAL` | `30` | seconds between watchdog passes |
| `WATCHDOG_SOFT_PCT` / `WATCHDOG_HARD_PCT` | `65` / `85` | wind-down bands, as % of the session budget |
| `WATCHDOG_FRESH_CTX` | `150000` | context above which restarting from a handoff beats carrying on |
| `WATCHDOG_LOWPRI_WEEK` | `40` | weekly % below which `/low-priority` is offered |
| `WATCHDOG_USAGE_EVERY` | `60` | minutes between the watchdog's `/usage` probes |
| `WATCHDOG_STRANDED` | `120` | minutes a `➥` lane may sit idle with an open handover and nothing pending naming it before its state reads `stranded`; `0` turns it off |
| `CLAUDE_USAGE_MAX_AGE` | `20` | minutes; the dashboard's `u` and `R` refresh only past this age |
| `CLAUDE_USAGE_MODEL` | from `settings.json` | which model's limit line the probe reads |
| `CLAUDE_CONTEXT_WINDOW` | `1000000` | what the dashboard draws the context bar against |
| `MUXTOPUS_NOTIFY_WAITING` | `on` | tell the phone when a window sits at a permission or trust prompt |
| `MUXTOPUS_NOTIFY_QUESTIONS` | `on` | tell it when a QUESTIONS file is new or has a new unanswered fork |
| `MUXTOPUS_NOTIFY_TROUBLE` | `on` | tell it about stalled verdicts, errored entries, stranded lanes, failed launches and long-blocked entries |
| `MUXTOPUS_NOTIFY_BLOCKED_AFTER` | `120` | minutes an entry may be blocked before that counts as trouble; `0` never says it |
| `MUXTOPUS_NOTIFY_DONE` | `on` | tell it when a handover reaches `done/` |
| `MUXTOPUS_NOTIFY_INBOUND` | `on` | attach buttons and obey what comes back, and answer the bot's commands |
| `MUXTOPUS_NOTIFY_PANE_TEXT` | `on` | a waiting message may quote the prompt box — that text leaves the machine |
| `DASHBOARD_MENU_LAYOUT` | `table` | how a context menu is drawn: `table` (under the panel the cursor is in), `modal` (centred), `bottom` (the footer, scrolling) |
| `DASHBOARD_NEW_PERMISSION_MODE` | `ask` | the mode preselected when `c` creates a window; `ask` preselects nothing |
| `DASHBOARD_PERMANENT_MODE_SCOPE` | `project` | which `settings.json` *make it the default* writes: `project` (`<cwd>/.claude/`) or `account` (`~/.claude/`) |
| `DASHBOARD_NEW_WATCHDOG` | `on` | `off`: a window `c` creates carries `watchdog: off` and is never restarted after a limit |
| `DASHBOARD_NEW_MONITOR` | `on` | `off`: it carries `monitor: off` and is never wound down |
| `DASHBOARD_NEW_MODEL` | | model alias preselected for a new window; empty is the account default |
| `DASHBOARD_NEW_EFFORT` | | effort preselected for a new window; empty is the account default |
| `DASHBOARD_NEW_CWD` | | working folder offered first by `c` and used by the schedule create flow when the cursor's session has none |

```sh
# ~/.config/muxtopus/config
MUXTOPUS_HOME="$HOME/.code"
WATCHDOG_SOFT_PCT=70

# ~/.config/muxtopus/profiles/work.conf
MUXTOPUS_HOME="$HOME/.code/work/.muxtopus"   # its own home
WATCHDOG_SOFT_PCT=60
```

`muxtopus -c` prints the effective configuration of an account (`muxtopus -c --profile=work` for another), every value with the layer it came from — `dashboard` and `profile-dashboard` for the two dashboard-written files.

Every file this tool writes — the installer's `config`, and the `profiles/<name>.conf` that creating an account seeds — lists **every key, commented out at its default**, with a line on what it does. Uncomment one to set it; leave it and a future default still applies.

**Taking effect.** The watchdog re-reads by re-executing itself: on its own within one interval of either file changing, or right now on `claude-watchdog.sh [--profile work] --reload` (also `systemctl --user reload claude-watchdog[-work]`). The dashboard re-reads on `R`. Claude windows hold no setting and need nothing. Moving an account's folders is therefore a config edit plus a `mv`.

---

## After a reboot

The watchdogs come back on their own: each is an enabled user unit, and with lingering on (`apply-logind.sh`) the user manager starts at boot rather than at login. The tmux sessions do not come back — nothing recreates them, and `muxtopus` (or your `cc` / `cw` aliases) does that on demand (`-r` for the resume picker). Until a session exists the watchdog has nothing to watch, keeps the usage cache warm, and leaves a scheduled item that comes due **pending** rather than failing it; it launches on the first pass after the session is back.

---

## Steam Deck extras

This was built on a Steam Deck in desktop mode, and the setup scripts that make SteamOS a workable dev box are included. They are **not** required by anything above; ignore the whole section on a normal Linux machine.

| script | |
|---|---|
| `setup-deck.sh` | the whole box from scratch: shell env, node, `gh`, the Claude CLI, tmux config, repos, SSH, Playwright, the dashboard venv, the watchdog |
| `after-update.sh` | health check after a SteamOS update, which resets parts of the OS image |
| `apply-sudo.sh` | passwordless sudo |
| `apply-logind.sh` | lingering, so user services survive logout — without it the watchdog dies with your session |
| `apply-hosts.sh` | `/etc/hosts` entries for e2e suites |
| `deck-ram.sh` | where the RAM went |
| `clone-org.sh` | clone every repo in a GitHub org |
| `claude-notify.sh` | phone notifications via ntfy, Pushbullet or Telegram |

SteamOS has an immutable base image: an update can reset system files and your account password. `after-update.sh` checks the things that actually break, including whether each account's credentials survived.

---

## How the pieces fit

```
muxtopus                     open a session for an account, bring up its watchdog
profile.sh              the one resolver: account -> every path it owns
muxconfig.py            the same answers for the Python half
claude-watchdog.sh      the daemon: limits, wind-downs, scheduled windows
claude-usage.sh         reads /usage from a throwaway session, per account
muxstats.py             the ledger: what was used, counted once, and the
                        report the `i` view and `muxtopus stats` both draw
claude-winddown-hook.sh PostToolUse hook: delivers a directive mid-turn
handover.sh             the handoff folder
claude-notify.sh        one message to a phone: ntfy, Pushbullet, Telegram
muxtelegram.py          the phone's half: buttons in, commands answered
muxstats.py             the usage ledger, and every figure it can answer
deck_status.py          the dashboard's SHELL: the terminal, the main loop
dashboard/              the dashboard itself, one file per screen or menu;
                        a view is one new file (docs/dashboard-views.md)
deck-status.sh          launcher (venv python, with a bash fallback)
setup-schedules.py      seed an account's schedules + templates
make-screenshot.py      regenerate the screenshot in this README
```

`claude-usage.sh` deserves one note: Claude Code has no usage subcommand and no file holding live limit state, so reading your budget means starting a throwaway session, sending `/usage`, scraping the pane and killing it — about four seconds, no turn taken, no completion tokens. That is why it is on demand and why every reading is stamped with the time it was taken: a stale number must not pass for a current one.

---

## License

MIT — see [LICENSE](LICENSE).
