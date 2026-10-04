## restore: a restored window comes back idle

- `muxtopus --restore` (and `WATCHDOG_RESTORE=auto`) no longer pastes
  `[muxtopus] restored …; carry on` into every resumed window. Each session
  comes back at its prompt, where it stopped, and does nothing until you type.
- Why: that line is a prompt. After a reboot every restored session took it as
  an instruction and started working, including windows that had been idle or
  stalled for days. One nine-window restore spent 9% of the account's session
  limit that way.
