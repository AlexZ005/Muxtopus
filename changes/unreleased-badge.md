## the header says when you are running a checkout, not a release

- On a machine that develops muxtopus, `~/.local/bin/muxtopus` is a symlink into the
  checkout, so the dashboard runs `main` — and between a merge and a tag `VERSION`
  still names the last release while the code is something else.
- The header now adds `(unreleased · <sha> · N changes)` beside the version: the
  commit it is actually running, and how many `changes/*.md` fragments are waiting
  for a number. That is the same list the CHANGELOG entry is assembled from, so the
  header and the release ritual cannot disagree about how much is pending.
- Dim, not yellow: "a newer release is out" is something to act on, this is
  something to know. And silent whenever the question does not arise — an installed
  release has no `.git`, and on the day of a release `HEAD` is the tag.
