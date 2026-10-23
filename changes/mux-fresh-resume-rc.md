## watchdog: a fresh resume keeps the remote control the old window had

- When a lane over `WATCHDOG_BUDGET_FRESH_CTX` resumes fresh from its handover after a limit, its old window is closed, and a `/rc` turned on there by hand went with it: the new window started without remote control. Now, when the old session has remote control on (Claude Code's `sessions/<pid>.json` carries a `bridgeSessionId`), the `<slug>-resume.md` entry says `rc: on` and the new window gets `/rc`. An `rc:` in the original entry still wins, `rc: off` included.
