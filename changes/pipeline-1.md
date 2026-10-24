## lanes: long runs that wake their lane, a send that checks, pre-flight on write

- `mux-done run <label> -- <command>` leaves one summary line when a long run ends; if the lane's task notification is lost, the watchdog types that line into the window once it has been idle since the run ended (`WATCHDOG_DONE_NUDGE`, default 5 minutes, `off`)
- `mux-send <window> <text>` types into a Claude window the way that works — the text, then Enter on its own, then a look — and presses Enter again while the text is still in the box; exit 1 if it stays unsent
- writing a schedule entry or `profile.sh` from a session now checks it on the spot (`mux-lint`, run by the PostToolUse hook): an entry that starts with a YAML `---` line is fixed instead of silently never launching, and a comment on a `KEY=` line or a syntax error is said in the same turn; the watchdog also drops that `---` line from an entry nobody linted
- `e2e-slot --pc-first SECS` waits for a pc slot before taking one on this machine, and stops waiting the moment the pc host is found asleep
