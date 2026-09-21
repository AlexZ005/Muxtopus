## notifications and the wind-down hook no longer need jq without saying so

- The last scripts that called `jq` directly — `claude-notify.sh` and
  `claude-winddown-hook.sh` — go through `mux_json` like everything else.
- **The wind-down hook now works with no jq at all.** It reads a session id
  out of the hook payload and JSON-escapes the directive; without jq it used
  to exit quietly, so wind-down directives were never delivered on a machine
  that had none. Its fast path is unchanged: nothing is sourced and nothing
  is forked until a directive is actually being delivered.
- **Telegram says what it needs, instead of failing silently.** Its API
  replies use filters muxtopus's own JSON reader deliberately does not
  implement, so that backend genuinely needs the real `jq` or the `jq` python
  wheel. It now names that, once, with the two commands that fix it — where
  before it simply did nothing, on a machine where nothing said why.
