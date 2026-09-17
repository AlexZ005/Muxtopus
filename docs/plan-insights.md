# Plan: insights -- usage statistics that outlive the transcripts

Status: PLAN, 2026-09-17, written by lane `handover-visibility` at the user's
request; the three questionable points (§9) were ANSWERED interactively first.
Nothing here is implemented. Locate by symbol, not by line.

Read before this: the transcript-reading part of `claude-watchdog.sh` (the
`tokens/` cache, "every poll after it reads a few KB"), `claude-usage.sh`
(`usage.log`, `usage.tsv`), `deck_status.py` (`sparkline`, `human_tokens`,
`gauge`, the view switch in `build()` / `main()`), `muxconfig.py` (`mux_dir`,
profiles), `docs/plan-dashboard-menus.md` §1, §3, §5 and
`docs/plan-notify-telegram.md` §3b.

## 0. What was measured, because it decides the design

1. **The data is rich and it is already on disk.** Every assistant record in
   `$CLAUDE_CONFIG_DIR/projects/*/*.jsonl` carries `timestamp`, `sessionId`,
   `cwd`, `gitBranch`, `version`, `isSidechain`, `message.model` and
   `message.usage` (`input_tokens`, `output_tokens`, `cache_read_input_tokens`,
   `cache_creation_input_tokens` split 5m/1h, `thinking_tokens`, web search /
   fetch counts, `service_tier`, `speed`). `system` records carry
   `turn_duration` and `compact_boundary`. Subagents write their own files
   under `<session>/subagents/`.
2. **A naive sum is wrong by more than 2×.** One API message is written as one
   line PER CONTENT BLOCK, each repeating the same `usage`. Over the six
   largest transcripts: 438 messages appear once, 523 twice, 562 three times,
   up to nine. The ledger key is `(message.id, requestId)`, counted once. The
   first job of phase 1 is to check whether the watchdog's existing SPENT
   figure (`tokens/<sid>`) has this bug, and say so in the handover either way.
3. **The transcripts do not last.** Claude Code deletes them after
   `cleanupPeriodDays` (30 by default; unset here). 81 files today: 3 from
   August, 78 from September. "Everything to date" is impossible unless
   muxtopus keeps its own record -- hence a LEDGER, and it starts on install.
4. **Claude Code's own `stats-cache.json` is not a source.** It stopped at
   `lastComputedDate: 2026-08-31` with 3 sessions. It is used ONCE, as a
   coarse backfill for days older than the oldest surviving transcript
   (daily tokens by model only), flagged `coarse` and excluded from averages.
5. **The budget history exists**: `usage.log`, 369 samples since 09-04
   (`session=51% resets=12:10 week=26% Fable=27%`), and the watchdog `log`
   records limit hits, resumes, wind-downs and `stranded`. Lanes come from
   `tree.tsv`, schedule entries (`launched:`) and `handovers/done/` mtimes.
6. A second account has its own `projects/` (28 folders under
   `~/.claude-work`), so the ledger is per profile like everything else.

## 1. The ledger

`$XDG_STATE_HOME/muxtopus/stats[-<profile>]/`:

    ledger.tsv     one row per (day, session, model, sidechain):
                   day  session  project  lane  model  side  requests
                   in  out  cache_read  cache_w5m  cache_w1h  thinking
                   ctx_peak  ctx_sum  ctx_n  tools  web  turns  active_s
                   compactions  first_ts  last_ts
    offsets.tsv    file -> (inode, size, byte offset, last message key)
    budget.tsv     day  window_start  session_peak_pct  week_pct  limited_s  hits  resumes
    lanes.tsv      slug  parent  launched  done  questions_asked  questions_answered
    meta           schema version, collecting-since, last collect

* **Counts only.** No prompt, no reply, no tool input, no file name other than
  the project directory. That sentence goes in the README verbatim; it is what
  a public release has to be able to say.
* **Incremental and idempotent**: a file is read from its stored offset; a
  shrunken or re-inoded file is re-read from 0 and its day-rows REPLACED, not
  added. A day's rows are rewritten whole, atomically (`.tmp` + `os.replace`).
  Running `collect` twice changes nothing; the test proves it byte for byte.
* `ctx` of a request = `input + cache_read + cache_creation` (what the model
  actually saw). `ctx_peak` per session-day; "average context" is the mean of
  per-request context, and "average peak" the mean of per-session peaks --
  both shown, because they answer different questions. The window size for a
  percentage comes from the model table in the price file (§3), not a constant.
* `active_s` = the sum of `turn_duration`, so an idle window open for three
  days is not a three-day session. `lane` joins `sessionId` -> pane -> tree slug
  at collect time (from `status.tsv`), and is empty for a plain window.
* **Forever, local only** (answered). `muxtopus stats --forget [--before DATE]`
  is the off switch. Nothing is uploaded; `/stats` on Telegram sends totals.
* **Who collects**: `muxstats.py collect`, run by the watchdog at most every
  5 minutes (a stamp file, not a timer) so it accrues with the dashboard
  closed; the view also collects on open. First run backfills every surviving
  transcript, then the coarse days.

## 2. The statistics (fourteen, in seven rows)

| row | figures |
|---|---|
| TOKENS | total; input / output / cache read / cache write; thinking share of output; tokens per active hour |
| CACHE | share of input served from cache; 5m vs 1h writes; the $ it saved against uncached input |
| COST | API-equivalent $ (§3), per day average, projected month at this pace |
| CONTEXT | average context per request; average session peak as % of the window; sessions past 80%; compactions |
| SESSIONS | count; median and longest ACTIVE time; turns per session; subagent share of tokens; tool calls and the top five tools; web searches |
| BUDGET | 5h-limit hits; time spent limited; watchdog resumes and wind-downs; average peak of a 5h window; week % at each weekly reset |
| LANES | launched, done, median launch-to-done; deepest tree; forks asked / answered; stranded count |
| RHYTHM | sparkline by weekday and by hour; busiest day and hour; active-day streak; tokens this period vs the previous one (▲ 18%) |

Below the rows, ONE breakdown table, grouped by `g`: project, model, lane,
day (week / month for the all-time period). Columns: tokens, share, sessions,
avg ctx, cache %, $. `enter` on a row drills in (a project -> its sessions ->
one session's days); `backspace`/esc climbs out.

**Honest about thin data.** The title always says `collecting since <date>`.
A figure needing a distribution (medians, "vs previous", projection) shows
`— needs 7 days` until it has them; coarse backfill days count toward totals
only. A new user sees a correct, sparse screen on day one, not zeros dressed
as findings.

## 3. Price and model table -- `~/.config/muxtopus/prices.md` (seed)

Shipped as a seed and copied only if missing (the `options.md` pattern,
commit c7e3f8c). One block per model id prefix: `input`, `output`,
`cache_read`, `cache_write_5m`, `cache_write_1h` per million tokens, `window`,
and ONE `as of: <date>` line at the top, shown dim beside every $ figure. The
implementer takes the numbers from Anthropic's published pricing at build
time (the `claude-api` skill), never from memory. A model missing from the
file shows tokens and `— no price` rather than a guess. Always labelled
`API-equiv`, never "spent": a subscription user paid none of it.

## 4. The view -- key `i`, and a row in the ESC menu

    ╭ insights · ◂ this week ▸ · all projects · all models ── collecting since Aug 25 ╮

* `←→` period: today · this week · last 7 d · this month · last 30 d · all.
* `f` filter (the existing picker, multi-step): project, model, lane,
  main/subagent; the active filter is in the title and `F` clears it.
* `a` this account / all accounts (reads the other profiles' ledgers).
* `g` group-by, `enter` drill, `e` export the current view (`.md`, `.csv`,
  `.json` into `$MUXTOPUS_HOME/exports/`, path in the notice), `r` recollect,
  `i`/esc back. The breakdown table scrolls through
  `menulayout.menu_viewport`; Rich only, `sparkline()` reused.
* Same module, three faces: the view; `muxtopus stats [--week|--month|--all]
  [--project P] [--model M] [--lane L] [--by project|model|lane|day]
  [--json|--csv|--md]`; and `/stats` in the Telegram bot (totals for a period,
  buttons week · month · all) -- a fourth command for plan-notify §3b's menu.

## 5. `muxstats.py` (new, pure, stdlib only)

    collect(config_dir, state_dir, now) -> CollectReport
    load(state_dir) -> Ledger
    query(ledger, period, filters, group_by) -> Report     # every figure of §2
    render_text(report) / to_json / to_csv / to_md
    prices(path) -> PriceTable ; cost(row, table) -> float | None

`query` is a pure function of rows, so every statistic is unit-tested against
a fixture ledger with hand-computed answers. `deck_status.py` only draws a
`Report`.

## 6. Interaction with the other lanes

`deck_status.py` has a queue: dash-menus-settings -> handover-vis-impl ->
notify-dash. `claude-watchdog.sh` and `muxtelegram.py` belong to notify-core /
notify-dash. So, two entries again:

* **`insights-core`** -- starts now, opus. Owns ONLY new files: `muxstats.py`,
  `seeds/prices.md`, `tests/test_stats.py`, `tests/fixtures/transcripts/`, and
  the `stats` subcommand in the `muxtopus` launcher script (check `git status`
  first; if another lane has it open, leave the subcommand to insights-dash).
  Phases 1-3.
* **`insights-dash`** -- `after: insights-core, notify-dash`. The `i` view, the
  ESC menu row, the watchdog's collect hook, `/stats`, `install.sh` seeding,
  docs. Phases 4-6.

## 7. Phases, one commit each, and each test

Sandbox discipline as `docs/plan-dashboard-menus.md` §5. The collector is run
against FIXTURE transcripts and a sandbox state dir. Reading the real
`~/.claude/projects` is allowed ONCE per phase as a read-only smoke test whose
ledger goes to the scratchpad, never to the real state dir; no content from a
real transcript is copied into a fixture, a commit or a handover -- fixtures
are synthetic, with the real record SHAPE.

| # | lane | commit | test |
|---|---|---|---|
| 1 | core | `[feat] muxstats: a ledger of what was used, counted once` | fixture with a message split over 1, 3 and 9 lines -> counted once; subagent file -> `side`; resumed session; truncated last line tolerated; collect twice -> byte-identical ledger; shrunken file -> day replaced not doubled; coarse backfill flagged; smoke: real totals vs a naive sum, ratio reported; the watchdog-SPENT check of §0.2 |
| 2 | core | `[feat] muxstats: every figure, from rows` | fixture ledger with hand-computed answers for all of §2; period edges (week starts Monday, local time, DST day); filters compose; thin-data markers; `budget.tsv` from a fixture `usage.log` + watchdog log; `lanes.tsv` from fixture tree / entries / done |
| 3 | core | `[feat] muxtopus stats: the report on the command line, and prices` | golden text / json / csv / md outputs; unknown model -> `no price`; missing price file -> tokens only, exit 0; `--forget --before` |
| 4 | dash | `[feat] dashboard: insights on i` | sandbox captures at 24 / 40 / 58 rows: periods cycle, filter in the title, group-by, drill and climb, export file exists and parses, `a` merges a second fixture profile, the day-one sparse screen |
| 5 | dash | `[feat] watchdog + telegram: collect every five minutes, /stats` | sandbox daemon: stamp honoured (2 collects in 11 faked minutes), a collector crash never fails a pass; fake Bot API: `/stats` totals equal `muxtopus stats --json` |
| 6 | dash | `[docs] insights: README, help, what is stored and how to forget it` | install into a sandbox HOME seeds `prices.md` once and never overwrites; `--check` on real entries still 0 |

## 8. Not doing

Reading prompt or reply text for any purpose (no "top topics"); uploading
anything; per-repo git statistics (tokens per commit is a vanity ratio that
punishes careful work); charts beyond sparklines and bars -- a terminal view,
and the export is there for anyone who wants a spreadsheet.

## 9. Forks, as answered by the user 2026-09-17

* API-equivalent cost in $: **yes, from an editable seed price file.**
* Placement: **own key `i` plus a row in the ESC menu.**
* Retention: **forever, local only**, with `--forget`.
* Decided without asking (great-to-have goes in, per the user): per-account by
  default with `a` for all; export; the CLI and `/stats` faces; period
  comparison and month projection; the thin-data markers.
