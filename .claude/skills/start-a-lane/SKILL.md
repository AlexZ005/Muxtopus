---
name: start-a-lane
description: Set up a new lane in this repo — branch, worktree, venv symlink and changelog fragment — the way docs/contributing.md requires. Use when beginning any change that will become a pull request.
---

# Start a lane

`main` only ever fast-forwards, and nothing is developed in the main checkout.
Every change is a lane: one branch, one worktree, one pull request, one
`changes/<slug>.md` fragment.

## Do this first, before any edit

```bash
cd <main checkout>
git fetch origin
git worktree add -b <type>/<slug> ../wt/<slug> origin/main
ln -s "$PWD/.venv" ../wt/<slug>/.venv     # tests import rich; a worktree has no venv
cd ../wt/<slug>
```

`<type>` is `fix`, `feat`, `refactor`, `docs` or `release`. `<slug>` is what
the lane is about, and it is also the fragment's filename, so pick it once.

## While you work

Run the tests with the venv's Python. The system one has no `rich`, and a
`ModuleNotFoundError` piped through `tail` looks like a pass:

```bash
.venv/bin/python tests/test_*.py
```

Check `$?` of the python process itself, not of a pipeline.

## Before the pull request

1. **Write `changes/<slug>.md`** — a `##` heading and a few lines about what a
   *user* would notice. Not refactors, not test counts. A lane with no
   user-visible change should say exactly that.
2. **Never write the release number** anywhere but `VERSION` — not in a
   comment, a docstring or the fragment. `tests/test_version.py` enforces it.
   Say "the previous release" instead.
3. **Rebase on current `origin/main`** and re-run everything *after* the
   rebase. Two lanes that both add a step to `.github/workflows/tests.yml`
   conflict at the same anchor — expect it, resolve by keeping both.

## The pull request

```bash
git push -u origin <type>/<slug>
gh pr create --title "[area] what changed" --body "..."
```

Merge with a merge commit once CI is green (`gh pr merge <n> --merge`). A lane
is "done" only after the merge and the main checkout's `git pull --ff-only`.

`--delete-branch` fails while your worktree still holds the branch; remove the
worktree first (`git worktree remove ../wt/<slug>`) or delete the branch after.
