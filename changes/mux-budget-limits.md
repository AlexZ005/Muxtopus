## watchdog: a budget guard for parallel lanes

- A schedule entry that would overspend the account is now **held**, the way the memory guard holds one on a full machine. It is held past a cap of working windows, past a session line, when it could not reach a checkpoint before the budget runs out, or when the week is ahead of its pace. It launches by itself once nothing is in the way, and `held: budget -- …` says what it is waiting for.
- The numbers come from your plan, read from the account's `rateLimitTier`: Pro, Max 5x, Max 20x or Team/Enterprise. Every one is adjustable in esc ▸ Settings ▸ Budget ▸. The Max 5x defaults were measured: a working lane costs about 8 % of the 5-hour window an hour, and a fresh lane's first fifteen minutes about 3.5 %.
- `priority: release | p1 | ops | p2` in an entry decides who goes first. p2 is held and asked to checkpoint ten points earlier, release ten points later. When only some may start, release starts first. A release entry is never held by the week's pace.
- A manual weekly reset (the claude.ai button) counts as a week already spent, so the week cannot end on Tuesday twice. It is read from the usage log; `claude-watchdog.sh --budget-reset-spent` records one the log missed.
- After a reset, stopped windows come back in **waves** (two every ten minutes on Max 5x), release first, instead of all at once.
- A stopped window with more than 250 000 tokens of context and an open handover is restarted **fresh** from its handover (`<slug>-resume.md`, written for you) instead of re-reading the whole conversation. The old window is closed once the new one is up.
- Windows stopped by the **weekly** limit, a **model** limit, or a turn that ended saying the limit was reached used to read as `idle` and were never restarted. They now read `limited` and are resumed when the limit lifts, including early, after a manual reset.
- `b` on the dashboard shows the budget:
  - the session estimate and when it runs out;
  - the week against its pace;
  - every window that is running, limited, queued, paused or held, with its class.
  `claude-watchdog.sh --budget` prints the same.
- `e2e-slot` takes `MUXTOPUS_E2E_SLOTS` runs at once (still 2 by default).
