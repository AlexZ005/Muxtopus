## dashboard: a package, and a new view is one new file

No user-visible change: every screen, key and menu draws exactly as it did,
proven against 148 golden screens taken before the split and reproduced by
every commit in it.

- `deck_status.py` is now the shell -- argv, the terminal, the main loop --
  and the dashboard proper lives in a `dashboard/` package.
- Views and menus are DISCOVERED, not listed: a file dropped into
  `dashboard/views/` appears as a view, a tab, an esc-menu row, a badge on a
  session, a help section, a settings key or a state style, with no other
  file edited. A module that fails to import is skipped with a red notice and
  the rest of the dashboard runs.
- `?` prints the help of whatever modules are loaded, in sections.
- `docs/dashboard-views.md` documents the protocol.
