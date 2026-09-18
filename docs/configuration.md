---
title: Configuration
nav_order: 10
---
{% raw %}
# Configuration

Four layers of plain shell, all optional — two you write, two the dashboard writes. `profile.sh` sources them and `muxconfig.py` parses them against the same key list, so the shell half and the Python dashboard cannot disagree about where anything lives or what a knob is set to.

```
~/.config/muxtopus/config                           every account: paths and defaults
~/.config/muxtopus/dashboard.conf                   every account, written by the dashboard's Settings menu
~/.config/muxtopus/profiles/<name>.conf             one named account's overrides
~/.config/muxtopus/profiles/<name>.dashboard.conf   one account, written by that account's dashboard
```

The same keys mean the same thing in all of them; the per-account files only narrow the scope. Precedence, lowest first: built-in default, environment, `config`, `dashboard.conf`, `profiles/<name>.conf`, `profiles/<name>.dashboard.conf`. The dashboard-written file sits **above** the hand-written one at the same scope — the menu is where a value was set most recently and most explicitly, and what it writes must be what is read next — and **below** the account's own hand-written file, the existing rule. It is a separate file because `config` is yours and full of your comments, and a program that rewrote it would eventually eat them; the dashboard rewrites its own file whole, atomically, and only reports a setting as saved once it has read it back from disk. **There is no registry of profiles** — an account exists because `~/.claude-<name>` does, and its `.conf` describes it rather than creating it; a second list would only ever drift from the first. The default account has no name and no `.conf`: the shared file *is* its configuration, and named accounts layer on top.

## Every key

| key | default | |
|---|---|---|
| `MUXTOPUS_HOME` | `${XDG_DATA_HOME:-~/.local/share}/muxtopus` | where schedules/, backups/ and handovers/ live. In a profile file: that account's **own** home, with the three folders unsuffixed inside it |
| `MUXTOPUS_DIR` | the checkout `muxtopus` resolves to | only needed when `muxtopus` was copied rather than symlinked |
| `MUXTOPUS_SESSION_PREFIX` | `claude` | tmux session name, suffixed per account |
| `MUXTOPUS_QUESTIONS_DIR` | | a legacy folder where plan sessions parked their questions; still read by the handovers tab beside the account's own folder |
| `WATCHDOG_INTERVAL` | `30` | seconds between watchdog passes |
| `WATCHDOG_SOFT_PCT` / `WATCHDOG_HARD_PCT` | `65` / `85` | wind-down bands, as % of the session budget |
| `WATCHDOG_FRESH_CTX` | `150000` | context above which restarting from a handoff beats carrying on |
| `WATCHDOG_LOWPRI_WEEK` | `40` | weekly % below which `/low-priority` is offered |
| `WATCHDOG_USAGE_EVERY` | `60` | minutes between the watchdog's `/usage` probes |
| `WATCHDOG_USAGE_STALE` | `180` | minutes after which a budget *reading* is too old to fire `at: reset`'s first gate |
| `WATCHDOG_HEARTBEAT_LOG` | `60` | minutes between the daemon's "still here" log lines |
| `WATCHDOG_STRANDED` | `120` | minutes a `➥` lane may sit idle with an open handover and nothing pending naming it before its state reads `stranded`; `0` turns it off |
| `CLAUDE_USAGE_MAX_AGE` | `20` | minutes; the dashboard's `u` and `R` refresh only past this age |
| `CLAUDE_USAGE_MODEL` | from `settings.json` | which model's limit line the probe reads |
| `CLAUDE_CONTEXT_WINDOW` | `1000000` | what the dashboard draws the context bar against |
| `MUXTOPUS_NOTIFY_WAITING` | `on` | tell the phone when a window sits at a permission or trust prompt |
| `MUXTOPUS_NOTIFY_QUESTIONS` | `on` | tell it when a QUESTIONS file is new or has a new unanswered fork |
| `MUXTOPUS_NOTIFY_TROUBLE` | `on` | tell it about errored entries, failed launches and long-blocked entries (stalled and stranded have their own switches) |
| `MUXTOPUS_NOTIFY_BLOCKED_AFTER` | `120` | minutes an entry may be blocked before that counts as trouble; `0` never says it |
| `MUXTOPUS_NOTIFY_DONE` | `on` | tell it when a handover reaches `done/` |
| `MUXTOPUS_NOTIFY_INBOUND` | `on` | attach buttons and obey what comes back, and answer the bot's commands |
| `MUXTOPUS_NOTIFY_PANE_TEXT` | `on` | a waiting message may quote the prompt box — that text leaves the machine |
| `MUXTOPUS_NOTIFY_SESSION` | `on` | alert when a window's claude session ends while the window stays open |
| `MUXTOPUS_NOTIFY_AUTH` | `on` | alert when the account is no longer logged in |
| `MUXTOPUS_NOTIFY_LIMIT` | `on` | alert when a budget is at its limit, with which one and when it resets |
| `MUXTOPUS_NOTIFY_LIMIT_BANDS` | `off` | also alert when a budget crosses the soft or hard band |
| `MUXTOPUS_NOTIFY_STALLED` | `on` | alert when an entry cannot be judged at all |
| `MUXTOPUS_NOTIFY_STRANDED` | `on` | alert when a lane is stranded |
| `DASHBOARD_MENU_LAYOUT` | `table` | how a context menu is drawn: `table` (under the panel the cursor is in), `modal` (centred), `bottom` (the footer, scrolling) |
| `DASHBOARD_NEW_PERMISSION_MODE` | `ask` | the mode preselected when `c` creates a window; `ask` preselects nothing |
| `DASHBOARD_PERMANENT_MODE_SCOPE` | `project` | which `settings.json` *make it the default* writes: `project` (`<cwd>/.claude/`) or `account` (`~/.claude/`) |
| `DASHBOARD_NEW_WATCHDOG` | `on` | `off`: a window `c` creates carries `watchdog: off` and is never restarted after a limit |
| `DASHBOARD_NEW_MONITOR` | `on` | `off`: it carries `monitor: off` and is never wound down |
| `DASHBOARD_NEW_MODEL` | | model alias preselected for a new window; empty is the account default |
| `DASHBOARD_NEW_EFFORT` | | effort preselected for a new window; empty is the account default |
| `DASHBOARD_NEW_CWD` | | working folder offered first by `c` and used by the schedule create flow when the cursor's session has none |
| `DASHBOARD_NEW_RC` | `off` | `on`: the launcher sends `/rc` to every new scheduled window unless its entry says `rc: off` |
| `DASHBOARD_HANDOVERS_DONE` | `off` | the handovers tab's `f`: show finished rows |
| `DASHBOARD_HANDOVERS_QUESTIONS` | `on` | the handovers tab's `a`: show the question rows |

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

## Taking effect

The watchdog re-reads by re-executing itself: on its own within one interval of either file changing, or right now on `claude-watchdog.sh [--profile work] --reload` (also `systemctl --user reload claude-watchdog[-work]`). The dashboard re-reads on `R`. Claude windows hold no setting and need nothing. Moving an account's folders is therefore a config edit plus a `mv`.

## The other files

Three more files are yours, seeded once by the installer and never rewritten:

| file | |
|---|---|
| `~/.config/muxtopus/options.md` | [the options table](schedules.md#the-options-table): the checkboxes `c` offers. `profiles/<name>.options.md` overrides it field by field for one account |
| `~/.config/muxtopus/prices.md` | the list prices [the insights view](stats.md) prices tokens at, one block per model, dated |
| `~/.config/claude-notify.conf` | the phone's backend and token, per machine, written by `claude-notify.sh --setup` ([Notifications](notifications.md)) |
{% endraw %}
