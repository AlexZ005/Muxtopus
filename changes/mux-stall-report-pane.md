## watchdog: a report never lands in a window that only inherited its parent's pane id

- After a tmux server restart, pane ids start again from `%0`, and the tree can still name a parent by a pane id that now belongs to some other lane's window. The watchdog now types a report into the parent only when that pane's window is still the parent's; otherwise it treats the parent as gone and the phone hears instead.
