---
title: Insights and stats
nav_order: 9
---
{% raw %}
# Insights (`i`) and `muxtopus stats`

What was used, from a ledger muxtopus keeps itself. Claude Code deletes a transcript after `cleanupPeriodDays` (30 by default), so "everything to date" only exists because something read it first: the watchdog collects into the ledger every five minutes, and the view collects again when you open it. The same report is on the command line, with the same numbers.

## The `i` view

Eight rows of figures — **tokens** (total, in/out/cache, thinking share, per active hour), **cache** (share served from cache, 5 m vs 1 h writes, what it saved), **cost**, **context** (average per request, average session peak as a share of the window, sessions past 80 %, compactions), **sessions** (count, median and longest *active* time, turns, subagent share, tool calls and the top five tools), **budget** (5-hour limit hits, time spent limited, resumes, wind-downs, week % at each weekly reset), **lanes** (launched, done, median launch-to-done, deepest tree, forks asked and answered, stranded) and **rhythm** (by weekday and by hour, busiest day and hour, active-day streak, this period against the last one) — and one breakdown table under them.

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

It is also `esc ▸ Insights` from the main view.

**Honest about thin data.** The title always says *collecting since &lt;date&gt;*, and a figure that needs a distribution — a median, "vs previous", the month projection — reads `— needs 7 days` until the ledger has seven. Days backfilled coarsely from Claude Code's own cache count toward totals only. A new install shows a correct sparse screen on day one, not zeros dressed up as findings.

**`$` figures are API-equivalent, never money spent.** They are what the same tokens would cost on the Claude API at the list prices in `~/.config/muxtopus/prices.md` — a subscription paid none of it. That file is yours: the installer copies `seeds/prices.md` into place **only if it is missing** and never rewrites it, one block per model with the date the numbers were copied at the top, shown beside every figure. A model the file does not name shows `no price` rather than a guess, and with no file at all the view shows tokens only.

## `muxtopus stats`

```
muxtopus stats -- what was used, from the ledger (counts only)

  --today | --week | --last7 | --month | --last30 | --all     period (default --week)
  --project P  --model M  --lane L  --side main|sub           filter; repeat to OR
  --by project|model|lane|day|week|month|session|side          the breakdown (default project)
  --json | --csv | --md                                        output (default text)
  --prices FILE      price table (default ~/.config/muxtopus/prices.md)
  --no-collect       report the ledger as it is, without reading new transcripts
  --all-accounts     merge every account's ledger
  --forget [--before YYYY-MM-DD]   drop what is recorded (before that date, else
                     everything) and never count it again; transcripts are untouched
```

`muxtopus stats --profile=work …` reads another account's ledger. The phone's `/stats` command draws the same totals ([Notifications](notifications.md)).

## What the ledger stores, and how to forget it

**Counts only. No prompt, no reply, no tool input, and no file name other than the project directory is ever written to it.** A row is a day, a session id, a project directory, a lane slug, a model id, main-or-subagent, and numbers: requests, tokens in and out, cache reads and writes, thinking tokens, context totals, tool-call counts, tool *names*, web searches, turns, active seconds and compactions. Beside it: one row per 5-hour budget window, one per weekly reset, one per lane, and an index of truncated hashes that is how a message split over nine lines is counted once.

It lives in `~/.local/state/muxtopus/stats/` (`stats-<account>` for a named account), it is **local and forever**, and **nothing is ever uploaded**. To stop that:

```
muxtopus stats --forget                     # drop everything recorded so far
muxtopus stats --forget --before 2026-01-01 # drop everything before that date
```

Both record the cutoff, so a later collect will not count the same days again. Your transcripts are not touched either way. Deleting the directory by hand works too — the next collect starts a new ledger from whatever transcripts still exist.

A collector that fails or hangs is logged and the watchdog's pass carries on — restarting a limited window is the daemon's job, and counting tokens may never get in its way.
{% endraw %}
