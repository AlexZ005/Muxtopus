## the nudge no longer kills an older watchdog

- v5.2.2 made the dashboard wake the watchdog with SIGUSR1 so a new window
  appears in about a second. **SIGUSR1's default action is to terminate**, so
  the first `c` after upgrading killed any daemon still running the previous
  release's script — which is every daemon that had not been restarted yet.
  Where systemd manages the watchdog it came straight back and the only trace
  was a restart; on a machine without systemd, which is exactly what the
  faster `c` was written for, it stayed down until the next `muxtopus`.
- The nudge is now SIGCONT, whose default action on a running process is to
  do nothing, and which can still be trapped. An older daemon ignores the
  nudge and keeps polling as it always did; a current one wakes.
- The nudge is also only sent to a daemon whose pid file says it installed
  the handler, so it cannot reach a process that is not ours.
