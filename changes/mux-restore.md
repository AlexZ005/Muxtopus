## muxtopus: the windows survive the tmux server dying

- the watchdog keeps a snapshot of every window in the session (name, folder, Claude session id, parent, model/effort/permission mode) and freezes the last one when the session disappears, saying so once in the log and on the phone
- `muxtopus` with no session and a fresh snapshot asks `restore K windows from <ts>? [Y/n]`; `muxtopus --restore` rebuilds them without asking, each running `claude --resume` on its session, in the saved order, names, folders and tree; `muxtopus -l` shows what is frozen; the dashboard's `esc` menu has the same action
- `WATCHDOG_RESTORE=auto|ask|off` and `WATCHDOG_RESTORE_MAX_AGE` (hours) decide what is offered; `auto` also has the watchdog relaunch `muxtopus -d` the moment the server is gone
- every tmux call names its server (`MUXTOPUS_TMUX_SOCKET`, default `default`), so a command typed inside a pane can no longer follow that pane's `$TMUX` to a server it did not mean; the identity lines every scheduled window is pasted say so too, and a repository test forbids a bare `tmux kill-server`
