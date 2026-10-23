## watchdog: a fresh resume keeps the remote control the old window had

- When a lane over `WATCHDOG_BUDGET_FRESH_CTX` resumes fresh from its handover after a limit, its old window is closed, and a `/rc` turned on there by hand went with it: the new window started without remote control. Now, when the old session has remote control on (Claude Code's `sessions/<pid>.json` carries a `bridgeSessionId`), the `<slug>-resume.md` entry says `rc: on` and the new window gets `/rc`. An `rc:` in the original entry still wins, `rc: off` included.

## watchdog, dashboard: a newly installed release is picked up without a reload

- However a release is installed — `muxtopus update`, `get.sh`, `install.sh` or a `git pull` — each running watchdog notices `VERSION` change and reloads onto it one pass later, logging `reloading: muxtopus <old> -> <new> installed`. A script that does not parse yet (an install still being written) is waited out. The dashboard presses R for you after a minute with no key, on the main view with nothing open.

## watchdog: `--health` no longer prints "integer expected"

- An e2e run whose command is a multi-line script (`e2e-slot -- bash -c '…'`) was read as one slot holder per line of its script, and every line after the first had no held time. It is one row now. A holder that no window owns shows `-` for its window instead of a slice of its command line.
