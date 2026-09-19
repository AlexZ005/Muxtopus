---
title: Install
nav_order: 2
---
{% raw %}
# Install

```bash
curl -fsSL https://github.com/AlexZ005/Muxtopus/releases/latest/download/get.sh | bash
```

That fetches the newest release's `get.sh`. It installs **that release's tag and nothing else**: it downloads the release's tarball, checks it against the sha256 stamped into `get.sh` when the release was built, unpacks it into `~/.local/lib/muxtopus` and runs its `install.sh`. It never follows `main`. To pin a version, put it in the URL (`releases/download/vX.Y.Z/get.sh`). The [releases page](https://github.com/AlexZ005/Muxtopus/releases) lists them.

This installs a background daemon that types into your terminals, so reading it first is a good habit:

```bash
curl -fsSLO https://github.com/AlexZ005/Muxtopus/releases/latest/download/get.sh
less get.sh
bash get.sh                   # options after it go to install.sh: bash get.sh --no-watchdog
```

Running `get.sh` again from a newer release upgrades in place and keeps the dashboard's venv. It will not touch `~/.local/lib/muxtopus` if something else put it there, such as a git checkout.

**From a git checkout** instead, if you want to follow `main` or send a patch:

```bash
git clone https://github.com/AlexZ005/Muxtopus.git ~/src/muxtopus
cd ~/src/muxtopus
./install.sh
```

Either way, `install.sh` does the same things. It symlinks `muxtopus` into `~/.local/bin`, writes a config file, seeds the data folders, builds the dashboard's venv and installs the watchdog. Nothing is written outside your home directory, and it prints every path before touching anything.

```bash
./install.sh --dry-run        # print what it would do and stop
./install.sh --home ~/.code   # put schedules/backups/handovers somewhere else
./install.sh --bin DIR        # where the `muxtopus` link goes (default ~/.local/bin)
./install.sh --no-watchdog    # skip the watchdog service
./install.sh --no-venv        # do not build .venv; the dashboard then uses a system python3 with rich, or its bash renderer
./install.sh --no-rc          # do not add the bin dir to PATH in your shell rc
```

If `~/.local/bin` is not on your `PATH`, the installer appends one line to `~/.profile` and `~/.bashrc`, or `~/.zshrc` under zsh, so the next shell finds `muxtopus`. A file that already mentions the directory is left alone, and a second install adds nothing. Under fish it prints the `fish_add_path` line instead. The shell you ran it from keeps its old `PATH`, so the installer prints the `export` line to paste there once.

**Requirements:** `bash`, `tmux` ≥ 3.2 (for `new-window -e`), `git`, `jq`, `python3` ≥ 3.10 with its `venv` module (on Debian and Ubuntu that is the `python3-venv` package), `curl` or `wget`, and the [Claude Code CLI](https://docs.claude.com/en/docs/claude-code). The installer builds the dashboard's [`rich`](https://github.com/Textualize/rich) venv itself. If it cannot, the dashboard falls back to a plain bash renderer instead of failing. `systemd --user` runs the watchdog where it is available; without it, the daemon is started as a plain background process.

On Arch (and SteamOS in desktop mode, which already has most of these):

```bash
sudo pacman -S --needed tmux git jq python curl
```

On Debian or Ubuntu:

```bash
sudo apt install tmux git jq python3 python3-venv curl
```

`muxtopus --version` says which release you are running.

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
