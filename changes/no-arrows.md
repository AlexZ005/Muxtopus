## lanes are named for their slug — the ➥ markers are gone

- A lane's tmux window is now called `checkout-refactor`, not
  `➥checkout-refactor`, and a sub-window is `cart-api`, not `➥➥cart-api`. The
  markers said two things, and both already had better homes: *this is a lane*
  is recorded in `tree.tsv` and in the schedules and handovers on disk, and
  the *depth* is `tree.tsv`'s parent column — which is what `t` on the
  dashboard has always drawn its indented tree from. The arrows were a second
  copy, visible in tmux and read by nothing.
- **Windows opened by an older release are renamed once**, on the first start
  after upgrading, and every rename is logged. Only lanes are touched, never
  onto a name another window already has, and `claude-watchdog.sh
  --migrate-names --dry-run` shows what it would do first.
- **A window you open by hand is still not a lane.** It is not listed, not
  watched, and not adopted into the tree until a claude session is running in
  it — and even then only if a schedule entry or a handover names it. That
  behaviour was previously a side effect of the arrow being absent; it is now
  a test of its own (`tests/test_lane_names.sh`), because removing the arrow
  is exactly the change that could have broken it.
- The dashboard, the manual and the screenshot all say the plain name now.
