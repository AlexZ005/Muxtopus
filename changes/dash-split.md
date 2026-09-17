## dashboard: a package, and a new view is one new file

No user-visible change: every screen, key, menu and help section draws
exactly as it did, proven against 148 golden screens taken from the untouched
code before the split and reproduced byte for byte by every commit in it.

- `deck_status.py` is now the shell -- argv, the terminal, the main loop --
  at 298 lines instead of 3768, and the dashboard proper lives in a
  `dashboard/` package.
- Views and menus are DISCOVERED, not listed: a file dropped into
  `dashboard/views/` appears as a view or a tab, and can add an esc-menu row,
  a badge on a session, a note in the footer, a help section, a setting and a
  state style, with no other file edited. Proven by dropping one in
  (`tests/sandbox/onefile.sh`, 21 checks).
- A module that fails to import is skipped with a red notice naming it, and
  the rest of the dashboard runs.
- `?` is assembled from what the loaded modules say about themselves, so it
  describes the dashboard you are actually looking at.
- `docs/dashboard-views.md` documents the protocol, the registries, the key
  routing rule and what may cross a view boundary.
