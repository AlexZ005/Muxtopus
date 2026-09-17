# QUESTIONS — open-lane

Forks taken while planning. Nothing here blocked me.

1. **What `esc` does when the table is reopened.** The brief specifies esc for
   the CREATE flow: "continue with nothing ticked". On reopen the entry
   already exists, so the same rule would silently untick everything.
   - **(a) RECOMMENDED: esc cancels on reopen, changes nothing; enter saves.**
     Why: esc means "back out" everywhere else in this dashboard.
   - (b) esc saves with nothing ticked, the same as in the create flow.
   Implemented as (a), provisionally.

2. **Where the count goes.** The strip has room for one figure per tab.
   - (a) the number of rows
   - **(b) RECOMMENDED: what is still owed**
   **Answer taken:** (b) — the figure nobody has to act on is not worth a line.

3. **Whether the arrows are free in this view.** Measured: they are swallowed
   on purpose so they cannot fold a tree row nobody can see.
   - (a) take them for the tabs
   - (b) find another key
