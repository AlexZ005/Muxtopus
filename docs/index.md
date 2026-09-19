---
title: Muxtopus
nav_order: 1
---
{% raw %}
# Muxtopus

**Run several Claude Code sessions side by side in tmux — one per account — and stop losing work to usage limits.**

![The dashboard](dashboard.png)

One command opens a tmux session for an account, brings up that account's watchdog, and lands you on a live dashboard of every lane you have running. Everything on screen is read from local files and tmux panes: nothing here calls an API, and watching costs no tokens.

This is the manual. The [README](https://github.com/AlexZ005/Muxtopus#readme) is the short version; every page here is a `.md` file in the repository's `docs/` folder, in the same commit as the code it describes.

## Why this exists

`autoContinueAtUsageLimit` does not resume after the 5-hour session limit. Measured twice on the same machine, the second time under clean conditions: a session started fresh with the setting armed hit the limit at 09:42, the limit reset at 12:40, and it was still idle at 13:39.

The reason is visible in the transcript. The limit is written as a `<synthetic>` assistant message with `read=0` and the turn marked **done** — the CLI *ends* the turn rather than parking it, so there is nothing left for auto-continue to resume. `/loop` has the same hole from the other side: a refused turn never reaches the call that schedules the next wakeup, so one refusal kills the loop permanently.

So the only thing that reliably restarts the work is something **outside** Claude Code. That is [the watchdog](watchdog.md).

The second half of the problem is accounts. A personal and a work account on one machine want two of everything — two budgets, two reset times, two sets of sessions — and a single shared state directory will happily hand one account's reset time to the other account's window. So [one account gets one of everything](accounts.md).

## Where to start

| you want to… | read |
|---|---|
| put it on a machine | [Install](install.md) |
| understand what `--profile` does and where files go | [Accounts](accounts.md) |
| know every key on the screen | [The dashboard](dashboard.md) |
| open a window later, or under another one, or after another lane finishes | [Scheduled windows](schedules.md) |
| hand work from one window to the next, and answer a lane's questions | [Handovers and questions](handovers.md) |
| know what the daemon does and when it types into a pane | [The watchdog](watchdog.md) |
| get the windows back after the tmux server died | [Restore after a lost server](restore.md) |
| be told on your phone, and answer from it | [Notifications](notifications.md) |
| see what was used and what it would have cost | [Insights and `muxtopus stats`](stats.md) |
| change a default | [Configuration](configuration.md) |
| change the code | [For contributors](contributing.md) |

## How the pieces fit

```
muxtopus                open a session for an account, bring up its watchdog
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
deck_status.py          the dashboard's SHELL: the terminal, the main loop
dashboard/              the dashboard itself, one file per screen or menu;
                        a view is one new file (dashboard-views.md)
deck-status.sh          launcher (venv python, with a bash fallback)
setup-schedules.py      seed an account's schedules + templates
make-screenshot.py      regenerate the screenshot from mocked fixtures
```

`claude-usage.sh` deserves one note: Claude Code has no usage subcommand and no file holding live limit state, so reading your budget means starting a throwaway session, sending `/usage`, scraping the pane and killing it — about four seconds, no turn taken, no completion tokens. That is why it is on demand and why every reading is stamped with the time it was taken: a stale number must not pass for a current one.

## License

MIT — see [LICENSE](https://github.com/AlexZ005/Muxtopus/blob/main/LICENSE).
{% endraw %}
