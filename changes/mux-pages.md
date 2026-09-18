## docs: a manual on GitHub Pages, and a README that is a README

- The manual lives at https://alexz005.github.io/Muxtopus/ — the `docs/`
  folder of the repository, so it is as current as the commit you are
  reading: install, the accounts model, every key on the dashboard,
  scheduled windows with the full header field reference, handovers and the
  questions contract, the watchdog's bands and gates, notifications,
  `muxtopus stats`, configuration, and how to contribute.
- The README is what a README is for: what this is, the screenshot, install,
  a five-line quick start, the manual, the licence. Nothing was deleted; every
  section moved into the manual, and a test says so.
- The screenshot is of a mocked machine, not the author's: a tree of lanes
  three levels deep in every state the dashboard can show, with the schedules
  and the handovers tab beside it. `make-screenshot.py` regenerates it from
  `tests/fixtures/screenshot/`, so it can be refreshed after any UI change.
- `?` in the dashboard names the manual.
