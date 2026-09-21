## dashboard: `c` is a form, and `c` `enter` is a window

- `c` now opens **one screen** with every parameter on it — name, folder,
  model, effort, permission mode, where it goes, first prompt — each already
  filled in from the new-window defaults in Settings, and `Create` on the
  first row. So a window you have no particular opinion about is `c` `enter`,
  and one you do is arrowing to that row and pressing enter on it.
- The form **stays open** while you change things: set the effort, think
  again about the folder, set it back. `esc` on a row leaves that row alone;
  `esc` on the form abandons the whole thing. It was seven pickers in a fixed
  order, so changing your mind about the second answer meant starting again.
- **It takes you to the window.** There is none to jump to when you press
  Create — the watchdog opens it a pass later — so the form remembers the
  slug, the key line reads `opening ➥name`, and the tmux client moves there
  the moment the window appears. `Ctrl-b 0` comes back to the dashboard.
- The offered name is made unique *before* it is offered, so the second
  `c` `enter` of the day works as well as the first, and a folder like
  `~/.code` no longer suggests the hidden slug `.code`.
- A permission mode of `(account default)` now writes **no**
  `permission-mode:` header at all, which is what the launcher already meant
  by an absent one: no `--permission-mode` flag, the account's own
  `defaultMode`.
