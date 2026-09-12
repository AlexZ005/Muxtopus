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
| `f` | lanes: this account only / every account (enter on a lane row does the same) |
| `s` | scheduled windows |
| `w` | arm / disarm the watchdog |
| `m` | session monitoring (wind-downs) on / off |
| `u` | read usage limits (refreshes if older than 20 min) |
| `U` | force a usage read now |
| `r` / `R` | redraw / reload the script |
| `p` | btop |
| `?` | help |
| `q` | quit |

The **menu** (`space`) carries two per-session switches and then everything you can do to that window: open, rename, wind it down now, resume it now, continue it at low priority, schedule a resume at the next reset, or close it.

### Panels

- **deck** — memory, swap, CPU, and the usage limits top right.
- **lanes** — dev servers by port, with age and whether the tree is dirty.
- **claude** — one row per session: context used, tokens spent, idle time, state, when it was last wound down and when it was last resumed. The account name appears in the title once you have more than one.
- **uncommitted** — its own table rather than a column, because dirty trees and sessions do not line up: a repo can be dirty with no session and no dev server near it, and that is the copy most likely to be lost.

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
window: api-cleanup
cwd: /home/you/src/checkout
status: pending
created: 2026-09-06 09:55
launched:
---
the prompt body that gets pasted into the new window
```

`at: reset` fires when the session limit resets — or when the budget simply reads fresh, because a brand-new rolling window has no reset time at all. An absolute time (`2026-09-06 14:30`, or anything `date -d` accepts) fires when it passes.

The new window opens right after its `window:` target, named with a leading `➥`, and the prompt lands as **one bracketed paste** — never `send-keys`, which submits at every newline. A file the view cannot parse is shown as corrupted with the reason and never launches.

In the `s` view: `enter`/`e` edit · `c` create · `l` launch now · `d` delete · `r` reload · `s`/`esc` back.

---

## Handovers

When a window is asked to wrap up, it writes a handoff so the *next* window can start from three paragraphs instead of carrying a quarter-million tokens of context forward.

```bash
handover.sh list              # what is open, and how much is done
handover.sh show <name>
handover.sh done <name>       # finished: moves it to done/
handover.sh reopen <name>
handover.sh --profile work list
```

Two decisions worth stating, because both were bugs first:

- **They do not live in the working tree.** A `STATUS-<window>.md` in the repo is scratch state under version control — and once a second account works the same repo, two windows of the same name overwrite each other's handoff without a word.
- **`done` moves, it does not delete.** A finished handoff is the record of what a lane actually did and costs nothing to keep. Moving it is also what makes `list` mean something: what is left in the folder is what is still owed. A repeated window name gets a timestamped second copy rather than erasing the first.

---

## Configuration

Two layers of plain shell, both optional. `profile.sh` sources them and `muxconfig.py` parses them against the same key list, so the shell half and the Python dashboard cannot disagree about where anything lives or what a knob is set to.

```
~/.config/muxtopus/config                  every account: paths and defaults
~/.config/muxtopus/profiles/<name>.conf    one named account's overrides
```

The same keys mean the same thing in both files; the per-account file only narrows the scope. Precedence, lowest first: built-in default, environment, `config`, `profiles/<name>.conf`. **There is no registry of profiles** — an account exists because `~/.claude-<name>` does, and its `.conf` describes it rather than creating it; a second list would only ever drift from the first. The default account has no name and no `.conf`: the shared file *is* its configuration, and named accounts layer on top.

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
| `CLAUDE_USAGE_MAX_AGE` | `20` | minutes; the dashboard's `u` and `R` refresh only past this age |
| `CLAUDE_USAGE_MODEL` | from `settings.json` | which model's limit line the probe reads |
| `CLAUDE_CONTEXT_WINDOW` | `1000000` | what the dashboard draws the context bar against |

```sh
# ~/.config/muxtopus/config
MUXTOPUS_HOME="$HOME/.code"
WATCHDOG_SOFT_PCT=70

# ~/.config/muxtopus/profiles/work.conf
MUXTOPUS_HOME="$HOME/.code/work/.muxtopus"   # its own home
WATCHDOG_SOFT_PCT=60
```

`muxtopus -c` prints the effective configuration of an account (`muxtopus -c --profile=work` for another), every value with the layer it came from.

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
claude-winddown-hook.sh PostToolUse hook: delivers a directive mid-turn
handover.sh             the handoff folder
deck_status.py          the dashboard
deck-status.sh          launcher (venv python, with a bash fallback)
setup-schedules.py      seed an account's schedules + templates
make-screenshot.py      regenerate the screenshot in this README
```

`claude-usage.sh` deserves one note: Claude Code has no usage subcommand and no file holding live limit state, so reading your budget means starting a throwaway session, sending `/usage`, scraping the pane and killing it — about four seconds, no turn taken, no completion tokens. That is why it is on demand and why every reading is stamped with the time it was taken: a stale number must not pass for a current one.

---

## License

MIT — see [LICENSE](LICENSE).
