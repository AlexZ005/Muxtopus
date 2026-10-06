---
title: The budget guard
parent: The watchdog
nav_order: 1
---
{% raw %}
# The budget guard

The [memory guard](watchdog.md#the-memory-guard) holds new windows while the machine is short of memory. The budget guard is its twin for the **usage budget**. It holds a launch that would overspend the account. After a reset it brings stopped windows back a few at a time, most important first.

**Why it exists.** On 2026-10-06 a Max 5x account had nineteen lanes start together after a reset. They spent **61 % of the 5-hour window in about fifteen minutes**, and every one of them then stopped at the limit. Resuming them after the next reset re-read every context uncached, which made it worse. The measurement below explains the number: a lane's first quarter hour costs a median 3.5 % of a Max 5x window, and 19 × 3.5 % is 66 %.

It costs no tokens to watch. Everything is the watchdog reading files it already keeps. A `/usage` probe starts a throwaway claude and takes no turn.

## What it holds

A schedule entry that is due is **held**, not launched, when any of these is true. They are asked in this order, and a held entry names the first one in its way:

1. **The cap.** `WATCHDOG_BUDGET_LANES` windows are already working (state `working`, plus anything started since the last scan). The entry starts when one stops.
2. **The wave.** It is an `at: reset` entry or a resume, and `WATCHDOG_BUDGET_WAVE` of those have started in the last `WATCHDOG_BUDGET_WAVE_MIN` minutes.
3. **The session line.** The 5-hour window is at or over `WATCHDOG_BUDGET_HOLD_PCT`, moved by the entry's [priority class](#priority-classes).
4. **The checkpoint.** A window started now would run out of budget in less than `WATCHDOG_BUDGET_CHECKPOINT_MIN` minutes, and before the reset refills it. Such a lane would stop mid-step with nothing committed: the start would buy only the resume it then needs.
5. **The week's pace.** The week is ahead of `WATCHDOG_BUDGET_DAY_PCT` a day, with one day in hand. p2 and ops entries wait as soon as the week is ahead of the pace, p1 entries only when it is two days ahead. **A release entry is never held by the week.**

A week that reads **100 %** holds every class, release too: a window started into a spent week stops on its first turn. It lifts with the first reading that shows room again.

A held entry reads `held: budget -- …` in the schedules tab and in `--check`. It launches **by itself** on the first pass where nothing is in its way. One log line is written when the guard starts holding and one when it stops.

When several entries are due at once, they are judged **in priority order**: release, p1, ops, p2. Within a class they go in file order. When only two may start, the two that start are the two that matter most.

## The estimate

A `/usage` reading is taken every `WATCHDOG_USAGE_EVERY` minutes (60), and the storm above crossed every line inside fifteen. So the guard does not judge the last reading. It judges an **estimate**:

    the last reading + (now − reading) × the faster of
        · the rate observed between the last two readings (same window, ≥ 10 min apart)
        · working windows × WATCHDOG_BUDGET_LANE_PCT

The second rate reacts the moment more windows start, before any reading can. It is deliberately conservative: it holds early rather than late. While anything is working, the guard also reads the usage every `WATCHDOG_BUDGET_PROBE_MIN` minutes (15) instead of hourly.

If the reset has passed since the reading, the estimate starts again from zero at the reset. A reading older than `WATCHDOG_USAGE_STALE` is **blind**. A blind guard draws no line and holds on the cap and the waves only, and it says so.

The same estimate drives the [wind-down](watchdog.md#session-monitoring-the-wind-down-bands) bands while the guard is on.

## Priority classes

An entry's `priority:` header field sets its class. The dashboard's options table offers it under *priority class*.

| class | held at (with the default 70) | wound down at (default 85) | week pace | resumed |
|---|---|---|---|---|
| `release` | 80 % | 95 % | never held | first |
| `p1` (or no field) | 70 % | 85 % | two days ahead | second |
| `ops` | 65 % | 80 % | ahead | third |
| `p2` | 60 % | 75 % | ahead | last |

One shift table moves both lines: release +10, p1 0, ops −5, p2 −10. A **p2 or ops lane is told to checkpoint whatever its context**. Pausing it is what leaves the rest of the window to the p1 and release lanes, so the checkpoint turn is worth paying. A p1 or release lane keeps the old rule: it is wound down hard only when the resume will be fresh or `/low-priority` is not available.

A window opened by hand has no entry, so its class is p1.

## After a limit

### What counts as stopped

The watchdog used to recognise one banner, `You've hit your session limit`. Across this machine's transcripts it also found 18 × `You've hit your weekly limit · resets Oct 10, 5pm` and 7 × `You've reached your Fable limit`. A window stopped by either read as **idle**, and nothing restarted it. Lanes whose turn *ended* with their own words, "the usage limit was reached" (a subagent had hit it), were idle in the same way. All of these now read as **limited**:

| stop | its reset |
|---|---|
| the session banner | the time on it (as before) |
| the weekly banner | the date and time on it |
| a model limit | `model_reset` from the usage reading |
| a turn that **said** it hit a limit | the week's reset if the week reads 100 %, else the session's |

The last row counts only when `usage.log` **corroborates** it: a reading at 100 % (session or week) within the hour around the stop. A model talking *about* limits is not a model stopped by one, and the watchdog types into this window.

A stop is **due** at its reset. It is due earlier if a reading taken *after* the stop shows room again, which is what a manual or early reset looks like from here.

### Waves

Under the guard, a due window is not typed into during the scan. It is **queued** (ACTION `queued`) and served after the scan, in priority order, through the same gate as a launch:

- at most `WATCHDOG_BUDGET_WAVE` per `WATCHDOG_BUDGET_WAVE_MIN` minutes;
- under the cap and the lines.

Whatever does not fit stays due and is asked again next pass. Nothing is dropped. Windows a [hard wind-down](watchdog.md#session-monitoring-the-wind-down-bands) stopped are served the same way.

### Fresh, not resumed

A stopped window can be **restarted from its handover** instead of resumed. That happens when its context is over `WATCHDOG_BUDGET_FRESH_CTX` tokens (250 000) and it has an open handover. The guard writes `<slug>-resume.md`:

- **the header:** the original entry's header (cwd, model, effort, permission mode, template, window, parent, priority), with `at:` set to now, `resume: fresh`, and `replaces: <pane> <session>`;
- **the body:** "You are lane X, resuming in a FRESH session … read your handover first", then the original brief.

The entry is launched in the same pass. A window opened by hand has no entry, so its model, effort and mode come from its own command line.

The **slug is the lane's own**, so the handover, `handover.sh done` and the tree row stay the lane's. The old window is closed once the new one is up, unless somebody has typed into it since. Its session stays on disk, and the log line names it for `claude --resume`.

A big window **without** a handover is resumed in place: a fresh session would have nothing to start from.

## Manual resets

The claude.ai reset button empties the week without moving its reset date. A week that reads 33 % after one press has really used **133 %** of a week's allowance, and pacing against the 33 would let it end on Tuesday again.

So the guard counts each manual reset as a **week already spent**. It reads them out of `usage.log`: the week % falling by 40 points or more between two readings whose reset date is the same. A natural reset moves the date. It measured this one on 2026-10-06 at 07:19: week 100 % → 5 %, "resets Oct 10" on both sides.

A reset pressed and used up between two readings cannot be seen in the log. Record it by hand:

    claude-watchdog.sh --budget-reset-spent "pressed on the phone"

Counted literally, one manual reset holds every non-release launch until the week resets. To loosen that, raise `WATCHDOG_BUDGET_DAY_PCT`, or give the lanes that must run `priority: release`.

## The presets

`WATCHDOG_BUDGET_PLAN=auto` (the default) reads the account's `rateLimitTier` from `.credentials.json`. The tier says what the limits are; `subscriptionType` says only what is billed. A Team seat with the `max_5x` tier gets the Max 5x preset. Each knob left empty takes the preset's number, and each one set overrides just that number.

| knob | Pro | **Max 5x** | Max 20x | Team | |
|---|---|---|---|---|---|
| `WATCHDOG_BUDGET_LANES` | 1 | **4** | 12 | 4 | most windows working at once |
| `WATCHDOG_BUDGET_HOLD_PCT` | 60 | **70** | 80 | 70 | p1's session line |
| `WATCHDOG_BUDGET_LANE_PCT` | 40 | **8** | 2 | 8 | session % one working lane burns an hour |
| `WATCHDOG_BUDGET_START_PCT` | 17 | **4** | 1 | 4 | session % a start costs |
| `WATCHDOG_BUDGET_DAY_PCT` | 14 | **14** | 14 | 14 | the week's pace, % a day |
| `WATCHDOG_BUDGET_WAVE` | 1 | **2** | 6 | 2 | resumes per wave |

These do not change with the plan:

| knob | default | |
|---|---|---|
| `WATCHDOG_BUDGET` | `on` | `off` holds nothing and leaves every wind-down exactly as it was before the guard |
| `WATCHDOG_BUDGET_CHECKPOINT_MIN` | `30` | minutes a lane needs to reach a checkpoint |
| `WATCHDOG_BUDGET_WAVE_MIN` | `10` | minutes between waves |
| `WATCHDOG_BUDGET_FRESH_CTX` | `250000` | a bigger stopped window restarts from its handover |
| `WATCHDOG_BUDGET_PROBE_MIN` | `15` | minutes between usage readings while anything works |
| `WATCHDOG_HARD_PCT` / `WATCHDOG_SOFT_PCT` | `85` / `65` | the wind-down lines (p1's; the class shift applies) |
| `MUXTOPUS_E2E_SLOTS` | `2` | how many `e2e-slot` runs the machine takes at once; shared by every account |

### Where the numbers come from

**Max 5x is measured** on the machine this was written on, over the eight days to 2026-10-06:

- the data: 25 027 API messages, each counted once by message id and request id (as [`muxstats`](stats.md) counts them), subagents included;
- the price: each message priced API-equivalent from `prices.md`;
- the calibration: against the hourly `usage.log` readings, Δ% against the dollars spent between two readings in the same window (45 pairs for the session, 41 for the week).

| figure | value |
|---|---|
| 1 % of the 5-hour window | $2.19 API-equivalent, so a window is about $219 |
| 1 % of the week | $16.3, so a week is about $1 630, **about 7.5 windows** |
| one active lane-hour (Opus 5.5) | median $13.9 (**6.3 %** of a window), mean $18.0 (**8.2 %**), p90 $27.2 (12.4 %) |
| … as a share of the week | about **1.1 %**, so about 90 lane-hours a week |
| a fresh lane's first 15 minutes | median $7.6, **3.5 %** of a window (p90 4.9 %) |
| a cold resume's first turn | 1.4 % at 250–500 k context, 2.1 % above 500 k |
| one lane-hour by context | 3.5 %/h at 150–250 k, 5.4 %/h at 250–400 k, 6.5 %/h at 400–600 k, 6.7 %/h above |
| subagents' share | 3 % |

The Max 5x preset follows from those figures:

- **four working windows** burn about 25 %/h, so a window lasts about four hours at the cap;
- **holding at 70 %** leaves about an hour of that for what is already running;
- **a wave of two** cold starts is about 7 %;
- **250 k** is where an hour of a lane starts costing half again as much.

**The others are scaled, not measured.** They use the session multipliers Anthropic publishes (Pro 1, Max 5x 5, Max 20x 20). Team is taken as Max 5x because the one Team account measured here carries the `max_5x` tier. `custom` starts from the Max 5x numbers and expects its knobs to be set. Correct a preset by setting its knobs. The `b` screen shows the rate the guard is using and the rate it observed, side by side.

## Seeing it

- **`b`** on the dashboard draws the session estimate and how it was made, the reset, and when the window runs out at the current rate. It shows the week (read, manual resets, effective) against its pace. It counts the windows running, limited, queued, paused and held, with the first reason for each. Last is a table of every window and held entry with its class.
- **esc ▸ Settings ▸ Budget ▸** has every knob. A blank knob shows the preset number the daemon last used. Typing a number pins it; an empty line gives it back to the plan. The daemon re-reads its config within one pass.
- **The main footer** says `budget: 2 held, 1 queued (b)` while something is held or queued, and nothing on an ordinary day.
- **`claude-watchdog.sh --budget`** prints the same picture, then what each class's launch would get right now. It is read-only.
- **`claude-watchdog.sh --check <entry>`** prints the entry's priority, and `HELD -- … held: budget -- …` when the guard would hold it.

The verdict is `budget` in the watchdog's state folder, one `key <TAB> value` per line in the shape of `usage.tsv`. The guard also keeps `budget-starts` (every start it let through, for the cap and the waves) and `week-resets` (manual resets recorded by hand).
{% endraw %}
