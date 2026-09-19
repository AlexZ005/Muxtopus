## install: muxtopus is on PATH after install, and works under `su`

- the installer adds `~/.local/bin` to `PATH` in `~/.profile` and `~/.bashrc` (or `~/.zshrc`) when it is missing, so `muxtopus` is found in the next shell; `--no-rc` skips it
- under `su user`, which keeps root's `XDG_RUNTIME_DIR`, running `muxtopus` again no longer fails with "Permission denied" on the watchdog's pid file, and no longer starts a second watchdog each time
- the background watchdog started without systemd no longer inherits the `$TMUX` of the pane it was started from
