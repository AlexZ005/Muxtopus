## install: the last thing printed is the thing to act on

- The report now ends with what actually stops muxtopus from running, if anything: a `tmux` older than 3.2 or no `claude` is repeated under `Done, but muxtopus cannot run yet`, with what to do and the path of `install.sh` to run again. Before, those warnings sat in step 1 of 7 and the report still ended `Done. Start with: muxtopus`.
- The `export PATH=...` line for the shell you ran the installer from is printed at the end, right above `Start with: muxtopus`, instead of in the middle of step 4.
- A `claude` that is installed but not on your shell's `PATH` (its own installer puts it in `~/.local/bin`) is named as such, not reported missing.
- On a distro whose repository only has an old `tmux`, the advice no longer amounts to "reinstall the version you have"; it says the newer one has to come from elsewhere.
- The data folders are seeded after the Python step, with the Python it settled on, and a failure to seed them is reported. On a machine with only Python 3.8 they were silently not seeded.
- `muxtopus` refuses to open a session when `claude` is not installed, with one line saying so, rather than opening a window that says "command not found".
- "Start with" lists one command; the second account, named sessions and `-l` are under `muxtopus -h`.
