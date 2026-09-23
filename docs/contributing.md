---
title: For contributors
nav_order: 13
has_children: true
---
{% raw %}
# For contributors

The repository is a checkout that runs in place: `muxtopus` is a symlink to it, the dashboard imports `dashboard/` from beside itself, and nothing is installed anywhere else. `git pull` is the upgrade.

## The shape of the code

```
muxtopus                the entry point: an account's session and watchdog
profile.sh              account -> every path; sourced by every shell script
muxconfig.py            the same resolver for Python; KEYS is the one key list
muxsettings.py          the dashboard's settings store, and the one settings.json write
claude-watchdog.sh      the daemon
claude-usage.sh         the /usage probe
claude-winddown-hook.sh the PostToolUse hook the daemon arms
claude-notify.sh        one message out; --setup
mux-update.sh           new releases: check, stage, apply, roll back
muxtelegram.py          buttons and commands in
muxhandovers.py         STATUS and QUESTIONS files as data; lane_state
muxstats.py             the ledger and the report
handover.sh             the handoff folder
deck_status.py          the dashboard's shell
dashboard/              the dashboard: core, data, schedules, app, views/, menus/
tests/                  what CI runs, and the sandbox that runs locally
seeds/                  options.md and prices.md, copied once by install.sh
docs/                   this manual, and the design plans beside it
changes/                one changelog fragment per lane
```

A dashboard screen is one new file under `dashboard/views/`, discovered rather than listed; the protocol, the registries and the key routing are on [A dashboard view is one new file](dashboard-views.md).

## Tests

```
.venv/bin/python tests/test_*.py      # every Python test; what CI runs
bash tests/test_handover_sh.sh        # handover.sh
bash tests/test_update.sh             # the self-updater, end to end
bash tests/test_notify_*.sh           # the notify half, against a fake Telegram
```

| what | where | runs in CI |
|---|---|---|
| the App: routing, registration, ordering, failure | `tests/test_dashboard_app.py` | yes |
| every name the code mentions is reachable | `tests/test_names.py` | yes |
| the settings store and both halves of the key list | `tests/test_settings.py` | yes |
| what a ticked box does to an entry | `tests/test_entry_options.py` | yes |
| `c ▸ orchestrate ▸ wave / sweep`: the entry it writes, inert to the executor, and `o` on it | `tests/test_create_orchestrate.py` | yes |
| the menu layout engine | `tests/test_menulayout.py` | yes |
| the options file parser | `tests/test_options.py` | yes |
| the templates `setup-schedules.py` seeds: all eight written, an edited one kept, executor placeholders only | `tests/test_templates.py` | yes |
| the ledger and every figure | `tests/test_stats.py` | yes |
| the handover reader, the states and the fork parser | `tests/test_handovers.py` | yes |
| the slug limit: one number in `claude-watchdog.sh`, `dashboard/naming.py` and `muxstats.py`, and what the rule does at it | `tests/test_slug_limit.py` | yes |
| the repo sweep: dirty-or-ahead rows, `-` when unknowable, and the dashboard's reader and `↑n` | `tests/test_repos_sweep.py` | yes |
| `handover.sh`: the marker, and what `done` carries with it | `tests/test_handover_sh.sh` | yes |
| this manual: front matter, links, Liquid-safe bodies, nothing lost from the README | `tests/test_manual.py` | yes |
| the self-updater, installed and rolled back for real | `tests/test_update.sh` | no — local |
| `install.sh`: the PATH line in the shell rc, once | `tests/test_install_path.sh` | no — local |
| `install.sh`: the closing block repeats what stops muxtopus running, and the PATH line; `muxtopus` refuses without `claude` | `tests/test_install_done.sh` | yes |
| the window's identity on `--append-system-prompt-file`, the paste without it, and nothing pasted for an empty plan | `tests/test_identity.sh` | no — local |
| what is pasted: a `template:` on either type, then the body, then the footer; every placeholder resolved | `tests/test_sched_template.sh` | no — local |
| `install.sh`: one line per tool, and the fetched python (checked, unpacked, never on PATH) | `tests/test_install_python.sh` | no — local |
| where the no-systemd watchdog's pid file goes, under `su` | `tests/test_run_dir.sh` | no — local |
| the notify shell: setup, pull, inbound, forks, the watchdog's pushes | `tests/test_notify_*.sh`, `tests/test_stats_watchdog.sh` | no — local |
| the picture, 148 golden screens | `tests/sandbox/goldens.sh` | no — local |
| the rows that WRITE something | `tests/sandbox/actions.sh` | no — local |
| Settings ▸ Notifications, fired | `tests/sandbox/notify.sh` | no — local |
| a view is one new file | `tests/sandbox/onefile.sh` | no — local |
| the insights view, every key | `tests/sandbox/insights.sh` | no — local |
| the handovers tab, row by row | `tests/sandbox/handovers.sh` | no — local |

The Python tests are pure: a temporary HOME, no terminal, no daemon, so they run anywhere. The notify shell tests drive tmux and jq in their own sandbox against `tests/fake_telegram.py`, never the real bot.

### The sandbox

`tests/sandbox/` is a whole fake machine for the dashboard: its own HOME, XDG dirs, muxtopus config, watchdog state and tmux server, so the dashboard can be started, typed at and photographed without touching the real one. It exists because the dashboard is a full-screen program whose output is a picture, and there is no other way to prove that a change draws the same picture: you take the picture first.

```
tests/sandbox/setup.sh              # build the fixture machine from tests/fixtures/dashboard/
tests/sandbox/goldens.sh            # drive the route, compare against tests/goldens/
tests/sandbox/goldens.sh --bless    # rewrite the goldens (only when the picture SHOULD change)
tests/sandbox/actions.sh            # the rows that write something
tests/sandbox/handovers.sh          # the handovers tab
tests/sandbox/insights.sh           # the i view
```

The rules it enforces:

- `bin/tmux` is `tmux -L "$SANDBOX_SOCKET"` and it is first on PATH. Nothing in it can reach the real server, `claude:0`, or any window you are working in.
- `bin/claude` is a fake that writes a session file and sleeps.
- `CLAUDE_CONFIG_DIR` names a sandbox-only account, so the dashboard's account suffix, its tmux session name and its watchdog state directory are all ones nothing else uses — and the lanes table, which reads the real `/proc`, finds no dev server belonging to this account. That is what makes the frame reproducible on a machine with servers running.
- Every deletion lives in `clean.sh` and goes through `"${SB:?}"`. Never `rm $VAR/...` inline.
- `SB`, `SANDBOX_SOCKET`, `SANDBOX_SESSION`, `SANDBOX_ACCOUNT` and `SANDBOX_FIXTURES` move the fake machine, its tmux server, its account and its fixture set, so two lanes — or the screenshot — can drive the harness at the same time. A lane that sets its own `SB` must give it the same length as the default (21 characters), or the goldens differ on every line that names it.

The goldens stay out of CI because they compare a rendered terminal frame against a fake machine, and a golden that fails for the runner's locale, Rich version or hostname teaches nobody anything. `tests/sandbox/normalise.py` documents, once, every mask they apply and why. `tests/sandbox/actions.sh` and the others navigate a menu by *looking* for the row they want, never by counting Downs — the pattern to copy.

### The screenshot

`docs/dashboard.png` is not a photograph of anybody's machine. `make-screenshot.py` builds a fake machine from `tests/fixtures/screenshot/` — a tree of mocked lanes three levels deep, in every state the STATE column can show, with schedules, handovers and questions to match — drives the real dashboard in the sandbox, captures the main view and the handovers tab with their colours, and writes the SVG and the PNG. After a UI change, run it again:

```
.venv/bin/python make-screenshot.py           # docs/dashboard.{svg,png} and docs/screens/
```

The fixture is the only place the story lives; edit it there. Anything that looks like a home path in the capture is replaced, width-preserved, and the script refuses to write a frame whose width changed.

## Branches, pull requests and the changelog

This applies to every lane:

- **`main` is the trunk and always runs.** Nothing is developed in the main checkout; it only fast-forwards. The user's `R` then only ever re-execs merged, tested code.
- **One branch and one worktree per lane**, made first thing: `git fetch && git worktree add ../mux-lane-<slug> -b <type>/<slug> origin/main`. A fresh worktree needs the `.venv` symlinked in. Removed after the merge.
- **One pull request per lane**, per-phase commits kept, merged with a merge commit (`gh pr merge --merge --delete-branch`).
- **The lane merges, behind a gate**: rebased on current `origin/main`, every test and every golden green *after* the rebase, CI green. If the merge is refused the lane leaves the PR open and writes its handover. The gate fails closed.
- **A handover is done only after the merge** and the main checkout's `git pull --ff-only`. "Done" then means "on main".
- **One changelog fragment per lane**, `changes/<slug>.md`: a heading and a few lines about what a *user* would notice. A release concatenates them into `CHANGELOG.md`, bumps `VERSION` and tags `vX.Y.Z`. A single `CHANGELOG.md` is a guaranteed conflict between parallel lanes; a new file per lane never conflicts with anything.

## This manual

The manual is `docs/` on `main`, served by GitHub Pages as it is: Markdown with three lines of front matter, built by the stock Jekyll that GitHub runs for every repository, with the [just-the-docs](https://just-the-docs.com/) theme fetched remotely. No branch, no generated tree, no workflow — a change to a key and the page that describes it travel in one commit, which is the only way a manual stays true.

To add a page: create `docs/<name>.md` with three lines of front matter —

```
---
title: The words in the sidebar
nav_order: 13
---
```

— then the body, wrapped in the same two Liquid tags every existing page starts and ends with (copy the line after the front matter and the last line of any page). Nothing else needs editing: the nav is built from the front matter, and `parent: For contributors` makes a page a sub-page of this one. The wrapping tags are there so that `{{SLUG}}` and its kind survive Liquid; `tests/test_manual.py` refuses a page that mentions a placeholder outside them, a page without a title, and a relative link to a file that does not exist.

To see it rendered before pushing, `docs/build-local.sh` runs the same container GitHub uses (`ghcr.io/actions/jekyll-build-pages`) and writes `docs/_site/`; it needs `podman` or `docker`, nothing else.

## Design notes

The plans each feature was built from are **not** in the repository. They
recorded what was measured before designing, the forks and how they were
answered, and what was deliberately not done — useful while the work was in
flight, and steadily less true afterwards as the code moved on without them.
A reader wants the manual and the code's own comments, both of which are kept
current; a plan that is eighteen months stale is a confident description of
software that no longer exists.

They are kept outside the repo by the author. What survived them on purpose is
here: the manual, and the long *why* comments at the top of every file, which
is where the reasoning belongs when it has to stay true.
{% endraw %}
