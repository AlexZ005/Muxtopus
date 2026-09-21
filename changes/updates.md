## updates: muxtopus keeps itself current

- It checks GitHub for a new release once a day and says so on the dashboard
  — a line in the footer, a row under `esc`, and the full story in
  `esc ▸ Settings ▸ Updates`. One request that follows the
  `releases/latest` redirect: no token, and nothing about your machine in it.
- Taking one swaps the install, keeps the release it replaced, and reloads
  every watchdog and the dashboard onto the new code. **Your claude windows
  keep running** — they are processes in panes and nothing touches them, so
  there is no "restart to apply".
- `muxtopus update --rollback` puts the kept release back, in one move, out
  of `~/.local/lib/muxtopus.prev`. Rolling forward again works too.
- Three settings, shared by every account: `MUXTOPUS_UPDATE_MODE`
  (`notify`, `download` or `off`), `MUXTOPUS_UPDATE_EVERY` and
  `MUXTOPUS_UPDATE_CHANNEL` (`stable` or `prerelease`). `off` means no
  request is made at all.
- A fourteenth notification switch, `MUXTOPUS_NOTIFY_UPDATE`, off by
  default: the phone hears about a release once per version, ever.
- It refuses to touch a git checkout (`git pull` is that one's update), and
  refuses to run an installer whose sha256 is not the one published beside
  it.
- On the command line: `muxtopus update`, `--check`, `--apply`,
  `--rollback`.

## dashboard: menus open centred by default

- `DASHBOARD_MENU_LAYOUT` now defaults to `modal`. `table` and `bottom` are
  unchanged and still one row away in `esc ▸ Settings`.
