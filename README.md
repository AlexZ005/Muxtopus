# Muxtopus

**Run several Claude Code sessions side by side in tmux — one per account — and stop losing work to usage limits.**

![The dashboard: a tree of lanes three levels deep in every state, and the handovers tab beside the schedules](docs/dashboard.png)

One command opens a tmux session for an account, brings up that account's watchdog, and lands you on a live dashboard of every lane you have running. Everything on screen is read from local files and tmux panes: nothing here calls an API, and watching costs no tokens.

The watchdog notices a window that stopped at a usage limit and types the continue prompt in once the limit resets — because `autoContinueAtUsageLimit` does not, and `/loop` dies on its first refused wakeup. It opens windows you scheduled, under the window that asked for them, after the lanes they depend on have finished; it asks a window that is about to run out of budget to commit and write a handoff; and it can tell your phone when a lane is waiting on you, with buttons that answer. A second account is a second folder of everything, so two budgets never get confused for one.

## Install

```bash
curl -fsSL https://github.com/AlexZ005/Muxtopus/releases/latest/download/get.sh | bash
```

This installs the newest [release](https://github.com/AlexZ005/Muxtopus/releases), pinned to its tag and checked against its sha256, into `~/.local/lib/muxtopus`. It never follows `main`. To read it before running it, or to install from a git checkout instead, see [Install](https://alexz005.github.io/Muxtopus/install.html).

Needs `bash`, `tmux` ≥ 3.2, `git`, `jq`, `python3` ≥ 3.10 and the `claude` CLI. The installer symlinks `muxtopus` into `~/.local/bin`, writes a config file, creates the data folders, builds the dashboard's venv and installs the watchdog as a user service. Nothing is written outside your home directory, and `install.sh --dry-run` prints every path first.

## Quick start

```bash
muxtopus                     # the personal account: window 0 is the dashboard, 1 is Claude
muxtopus --profile=work      # a second account, with its own budget, sessions and watchdog
muxtopus -l                  # what is running, per account
muxtopus stats               # what was used this week, counts only, never uploaded
Ctrl-b 0                     # back to the dashboard; ? there lists every key
```

## The manual

**[alexz005.github.io/Muxtopus](https://alexz005.github.io/Muxtopus/)** — install, the accounts model, every key on the dashboard, scheduled windows and the full header reference, handovers and the questions contract, the watchdog's bands and gates, Telegram notifications, `muxtopus stats`, configuration, and how to contribute. It is the `docs/` folder of this repository, so it is as current as the commit you are reading.

## License

MIT — see [LICENSE](LICENSE).
