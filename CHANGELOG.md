# Changelog

What a user of muxtopus would notice, one entry per release, newest first.
Each entry is assembled from the `changes/*.md` fragments the lanes wrote;
how that is done is [docs/releasing.md](docs/releasing.md).

## v5.2.3 — 2026-09-22

A patch, and an apology for the last one. v5.2.2 taught the dashboard to wake
the watchdog so a new window appears in about a second; it woke it with a
signal that kills a watchdog which does not expect it, which is every watchdog
still running the previous release's script. Upgrade past it.

#### the nudge no longer kills an older watchdog

- The previous release made the dashboard wake the watchdog with SIGUSR1 so
  a new window appears in about a second. **SIGUSR1's default action is to terminate**, so
  the first `c` after upgrading killed any daemon still running the previous
  release's script — which is every daemon that had not been restarted yet.
  Where systemd manages the watchdog it came straight back and the only trace
  was a restart; on a machine without systemd, which is exactly what the
  faster `c` was written for, it stayed down until the next `muxtopus`.
- The nudge is now SIGCONT, whose default action on a running process is to
  do nothing, and which can still be trapped. An older daemon ignores the
  nudge and keeps polling as it always did; a current one wakes.
- The nudge is also only sent to a daemon whose pid file says it installed
  the handler, so it cannot reach a process that is not ours.

## v5.2.2 — 2026-09-22

A patch, and every line of it is a fix for something that did not work on a
fresh machine. Nothing was renamed, no setting changed meaning, and no file
moved, so the number moves in its last place.

Three failures found on one newly installed box, where the usage figures were
blank and `c` produced no window at all. They turned out to be unrelated:
Claude Code's trust dialog, a missing `jq`, and a watchdog that was running
but never armed. The fourth change is the one that made the others tiring to
find — the dashboard said "scheduled" whether or not anything was listening.

Upgrade by running the new release's `get.sh`, with `muxtopus update` from a
release install, or `git pull && ./install.sh` in a checkout.

### Usage and dependencies

#### usage: the numbers are read again, and jq is no longer required

- The usage probe now ANSWERS the trust dialog instead of stopping in front
  of it — the same Down/Enter on "Yes, I trust this folder" that the
  scheduler and the restore have always used for the windows they open. On a
  machine whose folder had never been accepted, every reading failed as
  "<account> has not trusted <folder>" while the launcher was quietly
  accepting the same dialog in the same folder all day.
- The probe also picks a folder it can actually enter. It used to choose any
  folder the account had accepted, which on one box was `/root` — left there
  by a `claude` run under sudo, and unreadable by the user who owns the
  session, so the probe fell back to home and hit the dialog anyway.
- **jq is optional.** It was a silent hard requirement at ~60 call sites and
  only three of them ever checked for it, so a machine without jq could not
  read `sessions/<pid>.json` at all: no sessions, no token counts, no model
  on the dashboard, reported as "0 session(s)". Muxtopus now reads JSON
  through `mux_json`, which uses the real jq when it is installed, libjq via
  the `jq` PyPI wheel when that is importable, and its own small reader
  otherwise. Installing jq is still worth it and the installer still says so
  — it just no longer decides whether the watchdog can see your sessions.

### Schedules

#### c: the window is actually created, and in about a second

- **New windows are opened again on machines without systemd.** `c` writes a
  schedule entry and the watchdog opens the window — but a disarmed watchdog
  drops every entry, and the no-systemd start path (a container, WSL, macOS,
  a bare login) never armed it: arming lived only in the systemd install
  branch. On one box the daemon had been running 39 minutes, an entry had
  been `pending` for 19 of them, and the log read "0 pending schedule(s)".
  The daemon now arms itself the first time it starts, records that the
  decision was made, and says so in its log — so disarming with `w` still
  sticks.
- **A window appears in about a second instead of up to thirty.** The
  dashboard used to write the entry and wait for the next poll, which read
  as the keypress having been ignored. It now nudges the watchdog, which
  takes its next pass immediately.
- **And when the watchdog cannot act, the form says so.** A disarmed
  watchdog used to get "scheduled ➥name" exactly as a working one did. The
  form now carries a warning row, and Create reports that the entry was
  written but nothing will open it until you press `w`.

### The dashboard

#### c: the name is typed in the Create row, and esc is instant again

- **esc opens the menu straight away.** A lone Escape used to take the full
  250ms that a split escape sequence is allowed, because a bare ESC looks
  like the start of one — a quarter second of nothing on the key that leaves
  every view. The two waits are now separate: 100ms to tell Escape from an
  arrow, and the old generous budget once a sequence has actually begun.
  `MUXTOPUS_ESC_TIME` overrides it on a slow link.
- **No name modal.** `c` opens the form directly with the name already in
  the first row — `Create ➥[muxtopus-crane]` — and you type into that row.
  The field is padded, so nothing moves sideways as you type; the first
  character replaces the whole offer; a space becomes the hyphen a slug
  would have had anyway. `c enter` is now the whole gesture, one keystroke
  fewer than before.
- **Press `c` again and it offers a different name.** The suggestion used to
  be seeded from the folder alone, so the second look gave the same word —
  the only thing that moved it on was a name being *taken*, which one you
  just declined is not.
- **Model, Effort and Permission mode say what you will actually get.**
  Those rows read `(account default)`, which names the mechanism — no flag
  is passed — and never the outcome. They now read the value out of the
  settings.json that will apply (the project's `settings.local.json`, its
  `settings.json`, then the account's) and name it and the file. When
  nothing sets it anywhere the row says `unset`, which is a different and
  honest answer: the CLI's own built-in default applies.

## v5.2.1 — 2026-09-21

A patch. The interpreter v5.2.0 fetches when a machine has no `python3` >= 3.10
never got as far as being unpacked — it asked for a checksum file that does not
exist, so every download was refused and the machine quietly fell back to the
bash renderer. Nothing else changed.

Upgrade by running the new release's `get.sh`, with `muxtopus update` from a
release install, or `git pull && ./install.sh` in a checkout.

### Install

#### install: the fetched python actually arrives

Three bugs, all of them found by installing the published release in a clean
container rather than by reading the code:

- **The checksum was looked for in the wrong place.** python-build-standalone
  publishes one `SHA256SUMS` for the whole release, not a `.sha256` beside
  each asset — so every download was refused with `no published sha256` and
  every machine fell back to the bash renderer. The sum is now read from that
  file, by asset name.
- **It chose a release candidate.** The names carry the Python version and
  `3.15.0rc2` sorts above `3.14.7`, so the newest build in the list was a
  pre-release. Only released `3.x.y` builds are considered now, and the
  free-threaded variants — a different runtime offered under a name that
  sorts the same — are skipped.
- **The install hints named packages that do not exist**: `sudo pacman -S
  python3` (Arch calls it `python`) and `sudo pacman -S claude` (not a distro
  package at all — it now points at the Claude Code docs). On Debian and
  Ubuntu the python line asks for `python3-venv` too, which is what the
  dashboard's venv needs.

On a container with no `python3` at all, `./install.sh` now fetches CPython
3.14.7, checks it, builds the venv, and the Rich dashboard and `muxtopus
stats` both run.

## v5.2.0 — 2026-09-21

A minor release. muxtopus can now **keep itself current**, and **install a
Python for itself when the machine has none** — each adds settings and
command-line verbs, and nothing a user touches was renamed or moved. The one
behaviour that changes under your hands is `c`: it asks what to call the
window instead of choosing for you.

Upgrade by running the new release's `get.sh`, with `muxtopus update` from a
release install, or `git pull && ./install.sh` in a checkout.

### Keeping itself current

#### updates: muxtopus keeps itself current

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

### The dashboard

#### dashboard: `c` is one screen, and it asks what to call the window

- `c` opens **one screen** with every parameter on it — folder, model, effort,
  permission mode, where it goes, first prompt — each already filled in from
  the new-window defaults in Settings, and `Create` on the first row. It was
  seven pickers in a fixed order, so changing your mind about the second
  answer meant abandoning the flow and starting again. The form **stays open**
  while you change things: `esc` on a row leaves that row alone, `esc` on the
  form abandons the whole thing.
- **The name is asked first**, with an offer in the brackets:
  `name (the slug…): _ [repo-b-quail]`. The line starts empty, so typing a
  name of your own is typing it rather than backspacing over one, and `enter`
  on an empty line takes what is in the brackets. A window you have no
  particular opinion about is `c` `enter` `enter`.
- **The offer is the folder and one word** — `scripts-otter`, `repo-b-quail`
  — checked against every window and every pending entry before it is
  offered. The second window in a folder used to be `scripts-2` and the third
  `scripts-3`, and a digit tells you nothing about which of the three you are
  looking at, while a word can be said out loud. The same folder always offers
  the same word until that name is taken, and a folder like `~/.code` no
  longer suggests the hidden slug `.code`.
- **Two sub-window rows under `Create`**, whenever the cursor is on a live
  session: `empty, no prompt`, and `continues from its handover`, which pastes
  the brief `Schedule ➥resume` uses — read `STATUS-<parent>.md` and carry on
  from its *How to resume* section. Both make a `➥➥` child of that window, one
  `enter` each; the handover row is greyed with the reason until that lane has
  written one. `Create` still makes a top-level window.
- **It takes you to the window.** There is none to jump to when you press
  Create — the watchdog opens it a pass later — so the form remembers the
  slug, the key line reads `opening ➥name`, and the tmux client moves there
  the moment the window appears. `Ctrl-b 0` comes back to the dashboard.
- **A picker, a prompt or a confirm now goes where `Menu layout` says**, like
  the menu that opened it: centred on `modal` (the new default), under the
  cursor's panel on `table`, in the footer on `bottom`. `modal` used to give a
  centred menu and then a footer panel for the answers that menu was
  collecting.
- A permission mode of `(account default)` now writes **no**
  `permission-mode:` header at all, which is what the launcher already meant
  by an absent one: no `--permission-mode` flag, the account's own
  `defaultMode`.

#### dashboard: Page Up/Down and Home/End move a list instead of leaving it

- **pgup/pgdn** move the cursor one screenful and **home/end** jump to the
  first and last row, in the schedules table, the main dashboard list, the
  handovers tab, the insights breakdown, every menu, the options table and the
  pickers. A page is what that list is actually showing, so it is fewer rows on
  a short terminal, and both keys clamp: pgup at the top is the first row, not
  a wrap to the bottom
- those four keys used to decode to a bare Escape, which is the views' own
  "leave this screen" key — pressing End in the schedule view closed the
  schedule view, and Home on the dashboard opened the muxtopus menu. So did
  **F5, Insert, Delete and shift-Tab**, and an escape sequence the dashboard
  cannot name is now ignored instead. A real Escape is unchanged
- the key line on those screens lists the new keys, and `?` has a section on
  them

### Install

#### install: each tool once, and a python when the machine has none

- The check at the top of the install now reports **one line per tool**, with
  its version on it: `+ tmux 3.5a`, `+ python3 3.13.5`. It used to print the
  tool and then print it again from a second check — `+ tmux`, then
  `+ tmux 3.5` — which buried the line that matters under a copy of the one
  that does not. A missing tool now also carries the command that would
  install it on **this** machine (`sudo apt install jq`, `sudo pacman -S jq`…).
- **A `tmux` older than 3.2 is called out** with what it costs: `new-window
  -e` does not exist below it, so a window cannot be given its own account —
  and with the line that updates it.
- **No `python3` ≥ 3.10? The installer fetches one.** Debian 11, Ubuntu 20.04
  and a bare container ship 3.9 or nothing, and the Rich dashboard, the stats
  ledger, the notifications and the schedules view all need 3.10; that is most
  of the program, withheld for a reason you may not have root to fix. It now
  downloads a standalone CPython (astral-sh/python-build-standalone, the same
  builds `uv` installs) into `<data home>/python`, checks it against the
  `.sha256` published beside it, and builds the venv from it.
- **It is muxtopus's python, not the machine's.** Nothing is linked into
  `~/.local/bin`, nothing goes on `PATH`, no system package is touched — the
  only thing that ever runs it is muxtopus, through the new `MUXTOPUS_PYTHON`
  config key. One directory to delete to undo it, and
  `--no-embedded-python` never downloads anything.
- The watchdog, `muxtopus stats` and the notifications resolve their
  interpreter the same way, so stats and Telegram now work on a machine whose
  own `python3` is too old rather than being quietly skipped.

### Fixes

#### watchdog: a hard wind-down no longer stops a window for good

- a window told to wrap up and stop at the hard band is sent the continue
  message once its budget window comes back, instead of sitting idle until
  somebody notices. It never reached the usage-limit banner — it was told to
  stop before it got there — so nothing used to restart it
- only while its handover is still open: a lane whose handover is in `done/` is
  finished and is left alone, as is one that is working, one that is opted out
  of restarts or monitoring, and one whose budget window has not come back yet
- it is visible before it happens: the state reads **`resume due`** on the
  dashboard and in `--status`, and `--dry-run` says `WOULD-RESUME`.
  `WATCHDOG_WOUND_RESUME=off` turns it off

#### the usage probe recognises today's trust dialog

- `claude-usage.sh` matched only the old wordings, so in an untrusted folder it
  sat in front of the new "Is this a project you created or one you trust?"
  dialog for its full twenty seconds, typed `/usage` into it and pressed Enter
  — which on that screen confirms **No, exit**: the session died and took the
  capture file the error pointed at with it. It now says `<account> has not
  trusted <dir>` in a second or two, which is the dead end it was written to
  report. Found on a machine with 679 consecutive failed readings
- the installer writes the `PATH` line on its own merits instead of skipping it
  whenever this shell's `PATH` already has the directory — which is exactly
  when it was needed and never written: after a hand-typed `export`, or on a
  second install in the same shell as the first

## v5.1.0 — 2026-09-19

A minor release: window restore adds a command-line flag (`--restore`) and two
settings (`WATCHDOG_RESTORE`, `WATCHDOG_RESTORE_MAX_AGE`), and nothing a user
touches was renamed or moved. The rest are fixes found by installing v5.0.0 on
a fresh Ubuntu 25.04 machine.

Upgrade by running the new release's `get.sh`, or `git pull && ./install.sh`
in a checkout.

### Restore

#### muxtopus: the windows survive the tmux server dying

- the watchdog keeps a snapshot of every window in the session (name, folder, Claude session id, parent, model/effort/permission mode) and freezes the last one when the session disappears, saying so once in the log and on the phone
- `muxtopus` with no session and a fresh snapshot asks `restore K windows from <ts>? [Y/n]`; `muxtopus --restore` rebuilds them without asking, each running `claude --resume` on its session, in the saved order, names, folders and tree; `muxtopus -l` shows what is frozen; the dashboard's `esc` menu has the same action
- `WATCHDOG_RESTORE=auto|ask|off` and `WATCHDOG_RESTORE_MAX_AGE` (hours) decide what is offered; `auto` also has the watchdog relaunch `muxtopus -d` the moment the server is gone
- every tmux call names its server (`MUXTOPUS_TMUX_SOCKET`, default `default`), so a command typed inside a pane can no longer follow that pane's `$TMUX` to a server it did not mean; the identity lines every scheduled window is pasted say so too, and a repository test forbids a bare `tmux kill-server`

### Install

#### install: muxtopus is on PATH after install, and works under `su`

- the installer adds `~/.local/bin` to `PATH` in `~/.profile` and `~/.bashrc` (or `~/.zshrc`) when it is missing, so `muxtopus` is found in the next shell; `--no-rc` skips it
- under `su user`, which keeps root's `XDG_RUNTIME_DIR`, running `muxtopus` again no longer fails with "Permission denied" on the watchdog's pid file, and no longer starts a second watchdog each time
- the background watchdog started without systemd no longer inherits the `$TMUX` of the pane it was started from

### Relaunch

#### muxtopus: relaunching from inside tmux works

- after Quit, typing `muxtopus` at the prompt the dashboard window drops to starts the dashboard again, instead of failing with "sessions should be nested with care"
- `muxtopus` run from a window of another tmux session switches that client over rather than refusing to nest

## v5.0.0 — 2026-09-19

The first public release: the first tag, the first tarball, and the first
way to install muxtopus that is not a clone of the author's working tree.

### Install

```bash
curl -fsSL https://github.com/AlexZ005/Muxtopus/releases/download/v5.0.0/get.sh | bash
```

That installs **exactly v5.0.0**: `get.sh` downloads this release's tarball,
refuses it unless its sha256 is the one baked into `get.sh` when the release
was built, unpacks it into `~/.local/lib/muxtopus` and runs its `install.sh`.
Nothing outside your home directory, no sudo. Options pass through
(`| bash -s -- --no-watchdog`), and to read it before running it:
`curl -fsSLO <that url>; less get.sh; bash get.sh`. The tarball and a
`SHA256SUMS` are attached to the release as well, for anyone who would rather
unpack it by hand.

**Needs** `bash`, `tmux` ≥ 3.2, `git`, `jq`, `python3` ≥ 3.10 (with `venv`;
on Debian and Ubuntu that is the `python3-venv` package), `curl` or `wget`,
and the [Claude Code CLI](https://docs.claude.com/en/docs/claude-code). The
installer builds the dashboard's Rich venv itself; `systemd --user` runs the
watchdog where there is one.

**Upgrading from a git checkout** (the only way there was before this):
`git pull && ./install.sh` as always. If you switch to the release install
instead, `install.sh` now warns that your existing `~/.config/muxtopus/config`
still pins `MUXTOPUS_DIR` to the checkout, which would keep running the old
code; change that line to `~/.local/lib/muxtopus`.

### Why 5.0.0, and not 1.0.0

`VERSION` already said 4.9.0: it was bumped by hand on every commit through
4.1.0 … 4.9.0 while this was a private set of scripts (the last bump was
2026-09-05), and the dashboard has been printing it in its header ever since.
Starting over at 1.0.0 would make the first release look older than the
build every existing machine is showing, so the lineage continues.

It is a **major** rather than 4.10.0 because a good deal of what changed since
4.9.0 is incompatible with it: the command is now `muxtopus` (the installer
removes the old `mux`, `cc` and `cw` links), each account's schedules, backups
and handovers moved into folders of their own, handovers are no longer written
into the working tree, and the dashboard became a package. Under semantic
versioning that is a 5.

From here on the version is semver over what a user touches: the `muxtopus`
command line, the schedule-entry headers and placeholders, `handover.sh`'s
commands, and the files and formats under `~/.config/muxtopus` and
`MUXTOPUS_HOME`. `VERSION` is the one place the number is written; the
dashboard, `muxtopus --version`, the tarball's name and `get.sh` all read it,
and a test fails if a copy appears anywhere else.

### Release and install

- **`get.sh`**, a one-line installer attached to every release, pinned to that
  release's tag and checksum (above).
- **`install.sh` builds the dashboard's venv.** Before, a fresh machine got the
  plain bash renderer unless you followed a warning by hand; now it builds
  `.venv` with Rich (`--no-venv` to skip) and checks for Python ≥ 3.10, the
  real floor, measured: the Python half fails to import on 3.9.
- The dashboard also runs on a **system `python3` that has Rich** when there is
  no venv beside it, which is what a distribution package of Rich gives you.
- `install.sh` warns when your config pins `MUXTOPUS_DIR` to a different
  checkout than the one you are installing.
- **`muxtopus --version`** (`-V`).
- A scheduled work window used to be told to finish with
  `~/.code/scripts/handover.sh done <slug>` — a path that exists only on the
  machine this was written on. It now names the `handover.sh` of the install
  that launched it.
- `release.sh` builds a release from its tag: a reproducible tarball, `get.sh`
  and `SHA256SUMS`. `docs/releasing.md` is the whole procedure.

### Since 4.9.0, before there were fragments

The `changes/` convention arrived with the dashboard split on 2026-09-17.
What landed between 4.9.0 and then, from the commit log:

- **`muxtopus`, one command per account.** It opens the account's tmux session
  (window 0 the dashboard, 1 Claude) and brings up its watchdog.
  `--profile=NAME` or `-w` picks the account, a link named `muxtopus-NAME` is
  that account, `-l` lists accounts, sessions and watchdogs, `-c` prints an
  account's effective configuration, and naming an account that does not
  exist asks before creating it (`--create` for scripts).
- **One account, one of everything.** The account picks its Claude config dir,
  and every path follows it: session name, schedules, backups, handovers,
  watchdog state and usage cache. The account is exported into the tmux
  session, so every window opened later — by hand, by the dashboard or by the
  watchdog — inherits it instead of falling back to the default account.
- `Ctrl-b w` lists this account's windows only; `Ctrl-b W` lists every session.
- **Scheduled windows grew up.** `after: a, b` holds an entry until every named
  lane has finished; `parent:` draws a window under another, kept contiguous
  as a tree that `←` `→` folds; every pending entry says why it has not fired;
  `claude-watchdog.sh --check` resolves an entry without launching it.
  New headers `model:`, `effort:`, `permission-mode:`, `watchdog: off` and
  `monitor: off`, and placeholders such as `{{SLUG}}` and `{{HANDOVER}}`,
  resolved when the window opens.
- **The options table** (`~/.config/muxtopus/options.md`): a checkbox step
  between the template and the editor, reopened on a pending entry with `o`.
- A window nothing will ever resume is drawn **`stranded`**, and the watchdog
  writes a heartbeat so "is it alive" has an answer.
- **The esc menu and the settings store** (`dashboard.conf`); menus drawn as a
  table, a modal or a bottom sheet to fit the terminal; `space` opens a
  schedule entry's own menu; `c` starts a new Claude session as a due
  schedule entry.
- **Telegram that answers.** `claude-notify.sh --setup` walks you through it;
  a window waiting at a permission prompt can be answered from the phone, and
  the bot answers `/status` and `/pending`.
- **The usage ledger** and `muxtopus stats`, the report on the command line
  (the dashboard half is under Insights below).
- Fixes: the account's config dir reaches the tmux session, so each account's
  budget probe reads its own budget; a closed window leaves the table on the
  next redraw; handover paths are built from the slug, never from the
  window's display name.

### Dashboard

#### dashboard: a package, and a new view is one new file

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

#### dashboard: handovers and questions, where the schedules are

The `s` screen has a second tab. `←` `→` moves between them; the strip names
both and carries their counts, so from the schedules you can still see how
many handovers are open and how many question files are waiting on you.

- Every lane's STATUS and QUESTIONS file in one list, from BOTH folders,
  ordered by what is OWED: unanswered questions first, then open handovers,
  then everything finished. Each row says how old it is, which window the
  lane ran in and whether that window is still open, and how many pending
  schedule entries are waiting on it.
- **A fork can be answered without leaving the dashboard.** `enter` on a
  question file walks its forks one at a time, offers the lettered options as
  rows with the recommended one already picked, and writes your answer into
  the file the moment you give it — with the editor one key away on every
  screen, because no parser will understand every lane's prose.
- `space` acts on a row: view, edit anyway, open its window, mark done, mark
  answered, or tell that lane's window its answers are in. Marking a handover
  done launches everything held `after:` it, so the confirm names them.
- Two filters, `f` for finished rows and `a` for question rows, and both are
  remembered between runs — `R` no longer resets them. What a filter hides is
  always counted on the panel border.
- On the main view, a session whose lane has an unanswered question file
  carries a yellow `?`, and the key line says how many are waiting.
- `handover.sh` gains `answered` and `unanswer`; `done` now carries an
  answered question file into `done/` with its handover and leaves an
  unanswered one where it is, because a finished lane's open forks are still
  owed a look.
- Question files are read from both folders. The old panel looked only in the
  legacy one and therefore usually showed nothing at all.
- A lane that ran, was marked done and then ran again has two handover files,
  and `after:` has always treated it as finished. The row now says so, in
  yellow, instead of quietly disagreeing with the executor.

#### dashboard: insights on `i` — what was used, and what it would have cost

A new screen on `i` (also `ESC ▸ Insights`), drawn from muxtopus' own ledger,
which outlives the transcripts it was read from — Claude Code deletes those
after 30 days, so anything older than that only exists because muxtopus kept
its own record.

- Eight rows of figures — tokens, cache, API-equivalent cost, context,
  sessions, budget, lanes, rhythm — and one breakdown table under them.
- `←→` the period (today · this week · last 7 d · this month · last 30 d ·
  all), `g` the grouping, `enter` drills in (a project into its sessions, a
  session into its days) and backspace climbs back out, `f` filters by
  project, model, lane or main/subagent and `F` clears it, `a` merges every
  account's ledger, `e` exports the screen as `.md`, `.csv` and `.json`, `r`
  collects now.
- **Counts only.** The ledger holds numbers, model ids, tool names, session
  ids and working directories. No prompt, no reply and no tool input is ever
  read into it, and nothing is uploaded. `muxtopus stats --forget
  [--before DATE]` deletes what is there and stops it being counted again.
- The `$` figures are API-equivalent — what the same tokens would cost on the
  API at the list prices in `~/.config/muxtopus/prices.md`, a file the
  installer seeds once and never rewrites. A subscription paid none of it, and
  a model the file does not name shows `no price` rather than a guess.
- A figure that needs a distribution (a median, "vs previous", the month
  projection) says `— needs 7 days` until the ledger has them, so day one is a
  correct sparse screen rather than zeros dressed as findings.
- The watchdog now collects into the ledger every five minutes, so it accrues
  whether or not the dashboard is open. A collector that fails or hangs is
  logged and the pass carries on — restarting a limited window is the daemon's
  job, and counting tokens may never get in its way.

#### dashboard: fits a small terminal

- **The tab strip shrinks instead of spilling off the edge.** When the tabs
  do not fit, their labels get shorter first (full, then short, then an
  initial — the tab you are on keeps its name longest); only then do tabs
  past the first six scroll, with a `«N` / `N»` count of what is off each
  side and `←→ tab 7/9` saying where you are. `←` `→` still visit every tab,
  drawn or not.
- **The footer no longer falls off a short terminal.** On a 24-row client
  (or any small one) the lanes and claude tables give up rows and scroll,
  with `▲ N more` / `▼ N more` like a long menu, and the schedules table
  does the same. If there still is not room, the uncommitted panel and then
  the deck header step aside, and the claude title says so.
- On a narrow terminal the tables drop their least important columns
  instead of squeezing the window names out, and no row wraps onto two lines.
- **Choose which tabs exist:** esc ▸ Settings ▸ Tabs shows or hides each
  tab (saved as `DASHBOARD_TABS_HIDDEN` in `dashboard.conf`). A hidden tab
  leaves the strip and the `←` `→` cycle but nothing is lost: its marks on
  the session rows stay, `s` still gets you in, and the menu has an "Open
  … once" row for each hidden tab. When you hide one of the first six, the
  next shown tab takes its place among the six that never scroll away.
- Down to a 40-column terminal (a phone held upright): the tables keep the
  window names and states, and the handovers tab no longer pushes its
  footer off the screen.

### Notifications and schedules

#### notifications: the dashboard half

- **esc ▸ Settings ▸ Notifications ▸** is where the four things the watchdog
  can tell your phone are switched on and off, one by one: a window waiting
  at a permission prompt, a lane with questions, trouble, a lane finished.
  Two more switches: whether the phone may answer at all, and whether a
  waiting message is allowed to quote the prompt box (that text leaves the
  machine for Telegram's servers). `Set up…` opens the guide in a tmux window
  of its own, `Send a test` proves the phone hears this account, and the top
  row says which backend is configured and when it last sent.
- A window stuck on a permission prompt is drawn **`needs you`, in yellow**,
  instead of sitting in the list as `idle`.

#### notifications: the phone answers a fork

- **An unanswered question can be answered from Telegram.** Each fork arrives
  as its own message with a button per option (★ on the recommended one) and
  **✎ type**; a plain reply to the message works too. The answer is written
  into the QUESTIONS file as `**Answer (user via telegram, <date>):**`, into
  the right fork even if the lane rewrote the file meanwhile, and never over
  an answer given at the machine. The last answer marks the file ANSWERED and
  tells the lane, if its window is open and idle.
- `/questions` lists the unanswered files as buttons; `/pending` now sends
  the forks themselves; the watchdog's questions push carries the buttons too.

#### notifications: alerts when lanes silently stop

- **The phone now hears about the ways every lane can stop without a word**:
  a window whose claude session ended while the window stayed open, the
  account being logged out (the `/usage` probe, an auth error on screen, or
  the credentials file gone), a budget at its limit — which one, and when it
  resets — a schedule entry that cannot be judged (stalled), and a lane
  nothing will ever resume (stranded).
- Each is told **once**, and once more as **`cleared: …`** when it ends. Each
  is its own switch in `esc ▸ Settings ▸ Notifications`. All are on except
  **"A budget crossed a band"** (soft/hard %), which is off: it is a forecast
  the watchdog already acts on, not trouble. Under `/mute` they are recorded
  as sent, so `/unmute` does not replay them.
- Stalled and stranded moved from the "Trouble" switch to switches of their
  own; "Trouble" now means an entry marked error, a failed launch, or an
  entry blocked too long.

#### schedules: `rc: on|off`, and "Send /rc to a new window"

- A schedule entry may say `rc: on`: the launcher sends `/rc` (remote control)
  to the new window once it is ready, before pasting the body.
- `esc ▸ Settings ▸ Send /rc to a new window` (off) makes that the default for
  **every** new scheduled window, hand-written or made with `c`, unless the
  entry says `rc: off`. `claude-watchdog.sh --check` shows the resolved value
  and where it came from.

### Documentation

#### docs: a manual on GitHub Pages, and a README that is a README

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
