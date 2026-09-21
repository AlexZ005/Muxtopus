## install: each tool once, and a python when the machine has none

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
