---
title: Install
nav_order: 2
---
{% raw %}
# Install

```bash
git clone https://github.com/AlexZ005/Muxtopus.git ~/src/muxtopus
cd ~/src/muxtopus
./install.sh
```

The installer symlinks `muxtopus` into `~/.local/bin`, writes a config file, creates the data folders and offers to install the watchdog. Nothing is written outside your home directory, and it prints every path before it touches anything. There is no curl-pipe-sh on purpose: this thing installs a background daemon that types into your terminals, and that is not something anybody should run without having read it first.

```bash
./install.sh --dry-run        # print what it would do and stop
./install.sh --home ~/.code   # put schedules/backups/handovers somewhere else
./install.sh --bin DIR        # where the `muxtopus` link goes (default ~/.local/bin)
./install.sh --no-watchdog    # skip the watchdog service
```

**Requirements:** `bash`, `tmux` ≥ 3.2 (for `new-window -e`), `jq`, `git`, `python3` ≥ 3.9 with [`rich`](https://github.com/Textualize/rich) for the dashboard, and the `claude` CLI. `systemd --user` is used for the watchdog when present; without it the daemon is started as a plain background process instead.

## One name on `PATH`, and it is `muxtopus`

Not `mux`, which is already several other tools, and never `cc`: on any machine with a C toolchain that is the C compiler, and a `cc` link on `PATH` breaks every native build. Shorthands belong in your shell rc, where they reach an interactive prompt and nothing else:

```sh
alias cc='muxtopus'
alias cw='muxtopus --profile=work'
```

**One word per account, over SSH.** `muxtopus` reads the name it was invoked by, so a symlink named `muxtopus-acme` is `muxtopus --profile=acme` — which is what a `RemoteCommand` has room for. Aliases are not expanded in a non-interactive shell, so over SSH the command is spelled out:

```
ssh deck -t 'bash -lc muxtopus'                     # personal
ssh deck -t 'bash -lc "muxtopus --profile=work"'    # work
```

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
muxtopus stats [--week|--all]     # what was used, counts only (stats -h)
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

What an account owns, and where every one of its files lives, is [Accounts](accounts.md).

## After a reboot

The watchdogs come back on their own: each is an enabled user unit, and with lingering on (`apply-logind.sh`) the user manager starts at boot rather than at login. The tmux sessions do not come back — nothing recreates them, and `muxtopus` (or your `cc` / `cw` aliases) does that on demand (`-r` for the resume picker). Until a session exists the watchdog has nothing to watch, keeps the usage cache warm, and leaves a scheduled item that comes due **pending** rather than failing it; it launches on the first pass after the session is back.

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
{% endraw %}
