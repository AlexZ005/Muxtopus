## watchdog: new windows wait while memory is low

- While the machine is short of memory, a schedule entry that is due is **held** instead of launched. Short means less than 4 GB available, or more than 80 % of swap used. The entry reads `held` in red in the schedules tab, with the reading and the setting behind it. The deck panel carries a red `MEMORY LOW · new windows held` badge, and the phone is told once. Held entries launch by themselves once memory recovers, at 0.5 GB above the line and 2 points under it, so a machine on the edge does not let one more window through every pass. `c` on the dashboard is held too.
- New settings: `WATCHDOG_MEM_GUARD` (`on`), `WATCHDOG_MEM_MIN_GB` (`4`), `WATCHDOG_SWAP_MAX_PCT` (`80`; `100` turns the swap half off). `WATCHDOG_MEM_STOP_DEV` (`0`) can also ask the N newest lanes still running a dev server to stop it, once per episode, through the same hook as the wind-down.

## lanes: `lane-dev`, a dev server that stops itself

- `lane-dev start <dir> <port>` starts a folder's dev server in a session of its own and returns once it listens. `lane-dev status` lists the servers with their memory use. `lane-dev stop <port|dir>` takes the whole process group down. A server nothing has used for 15 minutes (`--idle`, `LANE_DEV_IDLE`) is stopped by its watcher.
- `e2e-slot` is now part of muxtopus. Its new `--dev <dir> <port>` starts the server for one e2e run and stops it afterwards. `install.sh` links both into `~/.local/bin`, but never over a file of your own.
