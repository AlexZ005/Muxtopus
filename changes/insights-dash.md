## dashboard: insights on `i` — what was used, and what it would have cost

A new screen on `i` (also `ESC ▸ Insights`), drawn from muxtopus' own ledger,
which outlives the transcripts it was read from — Claude Code deletes those
after 30 days, so anything older than that only exists because muxtopus kept
its own record.

- Eight rows of figures — tokens, cache, API-equivalent cost, context,
  sessions, budget, lanes, rhythm — and one breakdown table under them.
- `←→` the period (today · this week · last 7 d · this month · last 30 d ·
  all), `g` the grouping, `enter` drills in (a project into its sessions, a
  session into its days) and backspace climbs back out, `f` filters by
  project, model, lane or main/subagent and `F` clears it, `a` merges every
  account's ledger, `e` exports the screen as `.md`, `.csv` and `.json`, `r`
  collects now.
- **Counts only.** The ledger holds numbers, model ids, tool names, session
  ids and working directories. No prompt, no reply and no tool input is ever
  read into it, and nothing is uploaded. `muxtopus stats --forget
  [--before DATE]` deletes what is there and stops it being counted again.
- The `$` figures are API-equivalent — what the same tokens would cost on the
  API at the list prices in `~/.config/muxtopus/prices.md`, a file the
  installer seeds once and never rewrites. A subscription paid none of it, and
  a model the file does not name shows `no price` rather than a guess.
- A figure that needs a distribution (a median, "vs previous", the month
  projection) says `— needs 7 days` until the ledger has them, so day one is a
  correct sparse screen rather than zeros dressed as findings.
