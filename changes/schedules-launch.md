## c: the window is actually created, and in about a second

- **New windows are opened again on machines without systemd.** `c` writes a
  schedule entry and the watchdog opens the window — but a disarmed watchdog
  drops every entry, and the no-systemd start path (a container, WSL, macOS,
  a bare login) never armed it: arming lived only in the systemd install
  branch. On one box the daemon had been running 39 minutes, an entry had
  been `pending` for 19 of them, and the log read "0 pending schedule(s)".
  The daemon now arms itself the first time it starts, records that the
  decision was made, and says so in its log — so disarming with `w` still
  sticks.
- **A window appears in about a second instead of up to thirty.** The
  dashboard used to write the entry and wait for the next poll, which read
  as the keypress having been ignored. It now nudges the watchdog, which
  takes its next pass immediately.
- **And when the watchdog cannot act, the form says so.** A disarmed
  watchdog used to get "scheduled ➥name" exactly as a working one did. The
  form now carries a warning row, and Create reports that the entry was
  written but nothing will open it until you press `w`.
