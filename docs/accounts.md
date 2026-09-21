---
title: Accounts
nav_order: 3
---
{% raw %}
# Accounts

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
| stats ledger | `~/.local/state/muxtopus/stats` | `…/stats-work` |
| systemd unit | `claude-watchdog.service` | `claude-watchdog-work.service` |

`muxtopus` puts `CLAUDE_CONFIG_DIR` into the tmux **session** with `-e`, not merely into its own process. **A tmux session does not inherit the environment of whatever created it** — it starts from the server's, which belongs to whichever account happened to start the server first. Exporting is therefore not enough, and anything that opens a `claude` under tmux has to hand the account in explicitly: `muxtopus` for its windows, the watchdog for a restarted one, `claude-usage.sh` for its throwaway probe.

**The default account is the variable being absent**, not the variable pointing at `~/.claude`. Claude Code keeps the default account's onboarding and auth state in `~/.claude.json`; set `CLAUDE_CONFIG_DIR` and it looks for `<dir>/.claude.json` instead, which does not exist — so "helpfully" naming the path that account already uses shows a fully logged-in machine the theme picker and the login menu. Named accounts have no such history and always carry the variable.

**One watchdog per account, not one that watches both.** Every figure it judges a session against — session budget, weekly budget, reset time — belongs to a single account. A shared daemon would have to carry two of everything anyway, and could still hand one account's reset to the other account's window.

**There is no registry of profiles.** An account exists because `~/.claude-<name>` does, and its `profiles/<name>.conf` describes it rather than creating it; a second list would only ever drift from the first. The default account has no name and no `.conf`: the shared config file *is* its configuration, and named accounts layer on top. See [Configuration](configuration.md).

## One folder per account

Everything in a schedules folder belongs to **one** Claude account, because launching a window spends that account's budget. The account is the suffix on the config dir, and the default account takes none:

```
~/.claude        ->  $MUXTOPUS_HOME/schedules      backups      handovers
~/.claude-work   ->  $MUXTOPUS_HOME/schedules-work backups-work handovers-work
```

An account can also be given a home of its own by setting `MUXTOPUS_HOME` in `~/.config/muxtopus/profiles/<name>.conf`, in which case its three folders live there **unsuffixed** (the suffix only keeps siblings apart in a shared home):

```
profiles/work.conf:  MUXTOPUS_HOME="$HOME/.code/work/.muxtopus"
~/.claude-work   ->  ~/.code/work/.muxtopus/schedules  backups  handovers
```

`muxtopus -c --profile=<name>` prints where an account's folders are and every setting, each with the layer it came from.

```
tmux session     ->  claude / claude-work
watchdog state   ->  ~/.local/state/claude-watchdog[-work]
```

Open a session on an account with `muxtopus` (personal) or `muxtopus --profile=work`; it puts the account into the tmux **session**, so every window opened inside it — including one the watchdog launches from the schedules folder — runs on that account.

Handoffs are **not** written into the working tree: a wind-down writes `STATUS-<slug>.md` into the account's `handovers/`, and `handover.sh done <slug>` moves a finished one into `done/`. The *slug*, never the tmux display name: a window opened by an older release still carries `➥` markers, and building a path from the display name would ask for `STATUS-➥lane.md` while the same window's own footer told the worker `STATUS-lane.md`. Two accounts working one repo would otherwise overwrite each other's STATUS file without a word. See [Handovers](handovers.md).

## Which account a thing belongs to

- **A tmux window** belongs to the session it is in, and the session carries `CLAUDE_CONFIG_DIR`.
- **A dev server** belongs to the account whose session started it, read off `CLAUDE_CONFIG_DIR` in its environment — which it keeps even after the window that started it is gone, so a daemonised server is still attributed correctly. The dashboard's lanes table shows this account's by default and says how many belong to others; `f` shows them all, each labelled.
- **A usage reading** belongs to the account whose probe took it. The probe is a tmux session, and a tmux session does not inherit the environment of whatever created it — so the account has to be handed in explicitly, and for a while it was not: every account's probe read the same budget and filed it under its own name. If two dashboards ever show identical figures again, that is the shape of the bug.
- **A notification** starts with the account's label, so two accounts on one phone are told apart. The Telegram bot itself is per machine, because `getUpdates` has a single consumer; see [Notifications](notifications.md).
{% endraw %}
