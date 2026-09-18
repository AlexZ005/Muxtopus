## notifications: alerts when lanes silently stop

- **The phone now hears about the ways every lane can stop without a word**:
  a window whose claude session ended while the window stayed open, the
  account being logged out (the `/usage` probe, an auth error on screen, or
  the credentials file gone), a budget at its limit — which one, and when it
  resets — a schedule entry that cannot be judged (stalled), and a lane
  nothing will ever resume (stranded).
- Each is told **once**, and once more as **`cleared: …`** when it ends. Each
  is its own switch in `esc ▸ Settings ▸ Notifications`. All are on except
  **"A budget crossed a band"** (soft/hard %), which is off: it is a forecast
  the watchdog already acts on, not trouble. Under `/mute` they are recorded
  as sent, so `/unmute` does not replay them.
- Stalled and stranded moved from the "Trouble" switch to switches of their
  own; "Trouble" now means an entry marked error, a failed launch, or an
  entry blocked too long.

## schedules: `rc: on|off`, and "Send /rc to a new window"

- A schedule entry may say `rc: on`: the launcher sends `/rc` (remote control)
  to the new window once it is ready, before pasting the body.
- `esc ▸ Settings ▸ Send /rc to a new window` (off) makes that the default for
  **every** new scheduled window, hand-written or made with `c`, unless the
  entry says `rc: off`. `claude-watchdog.sh --check` shows the resolved value
  and where it came from.
