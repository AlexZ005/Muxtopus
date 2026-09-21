# Working in this repository

Read [`docs/contributing.md`](docs/contributing.md) first — the shape of the
code, the test matrix, the sandbox and the branch rules all live there and are
not repeated here. This file is the short list of things that are easy to get
wrong and expensive to get wrong, most of them learned by getting them wrong.

## The rules that bite

**`VERSION` is the only file that may contain the release number.**
`tests/test_version.py` fails on a number written anywhere else — including a
*comment*, a docstring or a `changes/` fragment. Write "the previous release"
or "since this was added", never `v5.2.2`. `CHANGELOG.md` is the one exemption,
because it is a history of numbers rather than a source of one.

**Run the tests with the venv's Python, not the system one.** The dashboard
tests import `rich`. `python3 tests/test_foo.py` will print a
`ModuleNotFoundError` and, if you check `$?` after a pipe, *look like it
passed*. Use `.venv/bin/python tests/test_*.py`.

**Never call `jq` directly.** Use `mux_json` (`profile.sh`). jq is optional —
a machine without it falls back to `muxjson.py`, and a bare `jq` call is a
silent empty answer on that machine rather than an error. See
[`muxjson.py`](muxjson.py) for what the fallback does and does not implement;
it refuses filters it does not know rather than guessing, so extending it is a
test failure away, never a wrong number.

**Never run a bare `tmux` command.** Inside a pane, `$TMUX` beats
`TMUX_TMPDIR`, so a sandbox command without `-S`/`-L` drives the *real* server.
A bare `tmux kill-server` once took out a whole live session. `unset TMUX` or
pass the socket explicitly; in the sandbox, `bin/tmux` already does.

**Never `pkill`/`pgrep` by pattern.** Two accounts run two daemons from the
same script path, and other work may be running on the same machine. Signal a
pid you recorded, and check `ps -o args=` before you signal it (`daemon_pid()`
is the pattern).

**Think about the default action before sending a signal.** SIGUSR1's default
action is *terminate*, so signalling a process that predates your handler kills
it. This is not hypothetical — it shipped. SIGCONT is the safe wake-up: its
default action on a running process is nothing, and it can still be trapped.

**Never screenshot a real session.** `docs/dashboard.png` is built by
`make-screenshot.py` from the mocked fixtures in `tests/fixtures/screenshot/`.

## What a change costs

The scripts here run unattended, on other people's machines, and they type into
terminals. So:

- **A fresh machine is the hard case, not the edge case.** The last three
  releases were all fixes for things that only failed on a newly installed box:
  a missing `jq`, a watchdog that was running but never armed, and a trust
  dialog nobody answered. Before assuming a dependency, ask what happens when
  it is absent — and prefer "muxtopus carries it" over "the user installs it",
  which is why there is a bundled Python and a bundled JSON reader.
- **Degrade honestly.** If something cannot be done, say which thing and what
  to press. The worst bug in this repo's history was not a crash; it was the
  dashboard reporting "scheduled" for windows that nothing was ever going to
  open.
- **A guess is worse than a refusal** anywhere a number is reported. A wrong
  token count with nothing saying so is worse than a missing one.

## Comments

The comments here explain *why*, at length, and usually name the measurement
that settled it ("measured on this box", "679 consecutive readings failed").
Match that. A comment restating the code is noise; a comment recording the bug
that the code's odd shape prevents is the most valuable line in the file.

## Lanes

One branch, one worktree, one PR, one `changes/<slug>.md` fragment. `main` only
fast-forwards. The fragment says what a *user* would notice — not what was
refactored. Full rules in [`docs/contributing.md`](docs/contributing.md) and
[`docs/releasing.md`](docs/releasing.md).

A fresh worktree needs the venv symlinked in:

```bash
git worktree add ../mux-lane-<slug> -b <type>/<slug> origin/main
ln -s /path/to/main/checkout/.venv ../mux-lane-<slug>/.venv
```
