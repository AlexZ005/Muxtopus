## dashboard: Page Up/Down and Home/End move a list instead of leaving it

- **pgup/pgdn** move the cursor one screenful and **home/end** jump to the
  first and last row, in the schedules table, the main dashboard list, the
  handovers tab, the insights breakdown, every menu, the options table and the
  pickers. A page is what that list is actually showing, so it is fewer rows on
  a short terminal, and both keys clamp: pgup at the top is the first row, not
  a wrap to the bottom
- those four keys used to decode to a bare Escape, which is the views' own
  "leave this screen" key — pressing End in the schedule view closed the
  schedule view, and Home on the dashboard opened the muxtopus menu. So did
  **F5, Insert, Delete and shift-Tab**, and an escape sequence the dashboard
  cannot name is now ignored instead. A real Escape is unchanged
- the key line on those screens lists the new keys, and `?` has a section on
  them

## watchdog: a hard wind-down no longer stops a window for good

- a window told to wrap up and stop at the hard band is sent the continue
  message once its budget window comes back, instead of sitting idle until
  somebody notices. It never reached the usage-limit banner — it was told to
  stop before it got there — so nothing used to restart it
- only while its handover is still open: a lane whose handover is in `done/` is
  finished and is left alone, as is one that is working, one that is opted out
  of restarts or monitoring, and one whose budget window has not come back yet
- it is visible before it happens: the state reads **`resume due`** on the
  dashboard and in `--status`, and `--dry-run` says `WOULD-RESUME`.
  `WATCHDOG_WOUND_RESUME=off` turns it off
