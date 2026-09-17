# A dashboard view is one new file

`deck_status.py` is the shell: argv, the terminal, Rich's `Live`, the key
reader, the main loop and the four full-screen hand-offs. Everything that
draws is a module under `dashboard/`, and **no file anywhere names the
modules** — the shell walks `dashboard.views` and `dashboard.menus` with
`pkgutil` and calls each module's `register(app)`.

That is the whole point of the split. Three lanes were queued on one
3768-line file for features that share no code with each other; now each of
them adds a file and none of them opens anybody else's.

    deck_status.py          the shell
    dashboard/app.py        the App: shared state, the menu engine, the
                            registries below
    dashboard/core.py       palette, account profile, every path, the knobs,
                            the formatters, the STATE table. The ONE door to
                            muxconfig.
    dashboard/data.py       every reader of /proc and of the watchdog's
                            files. NO RICH.
    dashboard/schedules.py  a schedule entry as data. NO RICH.
    dashboard/menulayout.py a menu panel drawn at an exact height. Pure.
    dashboard/help.py       the shell's own two slices of `?`
    dashboard/views/*.py    one screen each
    dashboard/menus/*.py    one menu kind each

## The shortest possible view

`tests/fixtures/demo_view.py` is a working one that uses every registry
exactly once; `tests/sandbox/onefile.sh` drops it into a copy of the checkout
and proves each part arrives, with `git status` showing one added file and no
modified one. Start there. The rest of this page is the reference.

```python
from dashboard.app import View

class ThingView(View):
    name, key, group, order = "thing", "g", None, 40

    def __init__(self, app):
        self.app = app

    def build(self, app):
        return [("thing", Panel(...))]

def register(app):
    app.add_view(ThingView(app))
```

## The View protocol

| attribute | what it is |
|---|---|
| `name` | unique; how other modules ask for it (`app.view_of("main")`) |
| `key` | opens it from the main view. `None` for the main view, and for a tab — a tab is reached through its group |
| `group` | views sharing a group are TABS of one screen; `None` is a screen of its own |
| `order` | position within the group and among the view keys |

| method | what it must do |
|---|---|
| `tab_label(app)` | the strip's text for this tab, **with its count** — the count is why the strip earns its line |
| `build(app)` | `-> [(section name, panel)]`, top to bottom. NOT a finished Group: App places an open menu among the sections, so every view gets the placer the schedule view once needed a copy of |
| `menu_anchor(app)` | which section index an open menu hangs under. Default 0 |
| `footer(app)` | `-> Text`, the key line when no submode owns the footer |
| `on_key(app, key)` | `-> True` if the key was this view's |
| `on_open(app)` / `on_close(app)` | optional |

A view may hold whatever state it likes on itself. It takes the app in its
constructor and is also handed it by every protocol method — the same object
either way; the argument is there so a view can be written with no
constructor at all.

## The six registries

```python
app.add_view(view)                              a screen, or a tab of one
app.add_menu(kind, entries_fn, title_fn=None, hint_fn=None, esc_to=None)
app.add_rows(menu_kind, rows_fn, order=50)      a row in someone else's menu
app.add_badge(fn, order=50)                     fn(app, session) -> Text|None
app.add_hint(fn)                                fn(app) -> Text|None
app.add_help(title, text, order=50)             one section of `?`
app.add_state(name, label, style, with_reset=False)
muxsettings.register({KEY: {label, kind, hint, choices?}})
```

**Menus.** `esc_to` names the parent kind esc goes back to, which is how
Settings returns to the esc menu without the main loop knowing either name.

**Rows into a menu.** A menu's own rows take the positional orders 10, 20,
30 … unless a row names its own `order`, so `order=35` lands between the
third and the fourth. **Ties sort by label, never by registration**, so two
modules adding rows at one order produce the same menu whichever of them
Python imported first. `dashboard/views/schedules.py` uses this for real:
`Schedule ➥resume of <window>` is a row in the main view's session menu, at
`order=85`.

**Badges.** `fn(app, session) -> Text | None`, drawn after the window name.
**It must not fork.** The main frame is 12.9 ms and 2 forks, and a badge runs
once per session per frame: read a file, or read something already cached. A
badge that RAISES is dropped — not for that row, for good — and said once.

**Help.** Each section is the whole block including its own dim heading;
`?` concatenates them in order. `order` ties sort by title.

**State.** `add_state` teaches the STATE column how to draw one watchdog
state. An unregistered state keeps the fallback it has always had: dim, under
its own name — which is what an unknown state from a newer watchdog must do.

**Settings.** A key must already be in `muxconfig.KEYS`. That list and
`profile.sh`'s `MUX_CONFIG_KEYS` are the shell half and the python half of
one contract, and `tests/test_settings.py` compares them name for name; a key
in only one of them is a value the menu writes and the shell never reads. So
those two stay shared files and a new setting is three lines in each — a
conflict two lanes resolve, not a queue they wait in.

## Key routing, one rule

    a submode (prompt, confirm, picker, or a view's own modal)
      -> an open menu
        -> ←→, when the active view is in a group of two or more
          -> the active view's on_key
            -> the shell's own: q R ? p u U w m f
              -> the keys that open a view

A submode owns the keyboard while it is open, **q included**: typing a window
name with a "q" in it must not quit the dashboard. Two views claiming one key
is a `RegistrationError` at start-up naming both, not last-one-wins.

`f` is in the shell's list and arguably should not be — it filters the main
view's lanes table. It is there because it was reachable from the schedule
view before the split and the split was not the place to change that. Whoever
adds the third view gets to settle it.

## A view's own modal

`app.modal` is a dict carrying at least `{"key": fn(key), "panel": fn()}`
plus whatever the view keeps in it. App routes keys to one and draws the
footer with the other and knows nothing else about it. It is checked AFTER
prompt, confirm and picker, so a value one of those is collecting FOR the
modal still owns the keys while it is up. The options table is the one today.

## What crosses a view boundary

Five accessors on the main view, and nothing else:

```python
app.view_of("main").cursor_sid()         "" on a lane row and on extras
app.view_of("main").cursor_window()      the tmux name, ➥ markers and all
app.view_of("main").cursor_cwd()
app.view_of("main").listed_sessions()    (sid, window, pane, cwd) as drawn
app.view_of("main").known_windows()      collapsed subtrees included
```

`dashboard/views/schedules.py` uses the first three ("schedule a resume of
THIS window"), `dashboard/views/newsession.py` the last three. Anything
further is a gap in the seam: **stop and write it in QUESTIONS rather than
reach in.** A gap here is this design's bug and gets fixed once, for
everyone.

The one view-to-view name: the `c` flow registers itself as `app.newsession`
and the main view asks for it by that name, saying so if it is not there.

## A module that fails to import

…is skipped with a red notice naming it and the reason, and the dashboard
runs without it. One lane's bad commit must not take down the screen the
others are tested in, and a dashboard that refuses to start is worse than one
missing a tab. `tests/sandbox/onefile.sh` fires this too.

## How the dashboard is tested

| what | where | runs in CI |
|---|---|---|
| the picture, 148 screens | `tests/sandbox/goldens.sh` | no — local |
| the rows that WRITE something | `tests/sandbox/actions.sh` | no — local |
| a view is one new file | `tests/sandbox/onefile.sh` | no — local |
| where every pre-split definition went | `tests/sandbox/moved.py` | no — local |
| the App: routing, registration, ordering, failure | `tests/test_dashboard_app.py` | yes |
| every name the code mentions is reachable | `tests/test_names.py` | yes |
| the settings store and both halves of the key list | `tests/test_settings.py` | yes |
| what a ticked box does to an entry | `tests/test_entry_options.py` | yes |
| the menu layout engine | `tests/test_menulayout.py` | yes |

The sandbox ones stay local because they compare a rendered terminal frame
against a fake machine, and a golden that fails for the runner's locale,
Rich version or hostname teaches nobody anything. `tests/sandbox/README.md`
is how to run them; `tests/sandbox/normalise.py` documents, once, every mask
the goldens apply and why.

## Branches, pull requests and the changelog

From `docs/plan-dashboard-split.md` §5b, and it applies to every lane:

* **`main` is the trunk and always runs.** Nothing is developed in the main
  checkout; it only fast-forwards. The user's `R` then only ever re-execs
  merged, tested code.
* **One branch and one worktree per lane**, made first thing:
  `git fetch && git worktree add ~/.code/worktrees/scripts-<slug> -b
  <type>/<slug> origin/main`. Removed after the merge.
* **One pull request per lane**, per-phase commits kept, opened as a DRAFT
  after the first phase, merged with a merge commit
  (`gh pr merge --merge --delete-branch`).
* **The lane merges, behind a gate**: rebased on current `origin/main`, every
  test and every golden green AFTER the rebase, CI green. If the merge is
  refused the lane leaves the PR open, writes its handover and leaves it
  OPEN. The gate fails closed.
* **A handover is done only after the merge** and the main checkout's
  `git pull --ff-only`. "Done" then means "on main".
* **One changelog fragment per lane**, `changes/<slug>.md`. A single
  CHANGELOG.md is a guaranteed conflict between parallel lanes.
