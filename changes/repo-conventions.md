## the design plans leave the repo, and the conventions arrive

- `docs/plan-*.md` are **gone**. They were the notes each feature was designed
  from, kept beside the manual and hidden from the site. They went stale
  faster than the code they described — which is the argument against shipping
  them at all. What was worth keeping is already in the manual and in the long
  *why* comments at the top of every file, both of which stay true because
  they travel with the code. Every reference to a plan now points at the
  manual page that covers the same ground.
- **`CLAUDE.md`** and **`SKILLS.md`** are new, for anyone contributing with an
  agent. `CLAUDE.md` is the short list of things that are easy to get wrong
  here and expensive when you do — the release number lives in one file, the
  tests need the venv's Python, `jq` is never called directly, a bare `tmux`
  command reaches the real server. `.claude/skills/` carries the two
  procedures worth repeating exactly: starting a lane, and cutting a release.
