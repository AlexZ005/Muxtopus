## dashboard: one state, and tags for everything else

- A window used to be `working`, `idle` or `stranded`, and `idle` hid most of what mattered. It now reads one of:
  - `background`: the turn ended, but its tests, CI watch or poller still run. Such a lane is never marked `stranded`.
  - `handed off`: stopped at a checkpoint with an open handover.
  - `orchestrating`: idle on purpose while its lanes are pending.
  - `done`: its handover is in `done/`, so the window is safe to close.
  - `error`: the turn ended on an API error.
  - `paused`: the watchdog cooled it down before the limit.
  - `queued`: waiting for its resume wave.
- `limited` now reads **limit hit**: the window stopped abruptly at the banner.
- A new **TAGS** column beside STATE shows everything true at the same time, comma separated:
  - `e2e` / `e2e-wait`: holding an e2e slot, or waiting for one;
  - `test`, `ci`, `sleep`, `job:<script>`: what a background job is doing;
  - `serve:<port>`: a dev server the lane owns;
  - `session` / `week` / `model`: which limit stopped it;
  - `asking`: an unanswered question;
  - the lane's priority class;
  - `compacting`.

  Hide the column and the first tag is shown after the state. The phone's `/windows` lists the tags too.
- A new opt-in alert, `MUXTOPUS_NOTIFY_TAGS` (Settings ▸ Notifications), tells you when a lane has waited over 30 minutes for an e2e slot, or when a finished lane still has its dev server running.
