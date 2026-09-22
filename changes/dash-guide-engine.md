## the menus explain themselves, and stopped being as wide as the screen

- **A row's explanation is on a line of its own.** Where a menu row used to
  read `Check now  ask GitHub for the newest release, ignoring the clock`,
  the row is now `Check now` and the sentence appears dim at the bottom of
  the panel, just above the `↑↓ pick` line, while the cursor is on it. The
  line is there for the whole time the menu is open and blank on a row with
  nothing to say, so nothing moves under your eyes as you arrow down the
  list. A sentence too long for it wraps once and is then cut with `…`
  rather than pushing the menu taller.
- **A submenu says what it is for once you are in it.** `Settings` opens
  with `menu layout, defaults for a new window, where a mode is made
  permanent` under its title, instead of carrying that sentence on the row
  you passed to get there.
- **esc comes back to the row you came from.** `Settings ▸ Tabs ▸`, then esc,
  used to land on the first Settings row; it now lands on `Tabs ▸`, and it
  still finds it on a day when a row has appeared or disappeared above it.
  The `Back` row at the foot of a submenu does the same thing. Opening a menu
  fresh with esc, space or `c` still starts at the top.
- **A centred menu is no wider than 78 columns.** The `modal` layout drew a
  panel as wide as its widest row, which was a band right across a wide
  terminal. It is capped now — and a menu of short rows is narrower still —
  so a menu is a box you read rather than a line you track across the screen.
  The pickers and prompts a menu opens are capped the same way. The `table`
  and `bottom` layouts are unchanged.
- This lane split the esc menu's rows and the Settings rows; the rest of the
  menus keep their glued-on explanations until the lane that sweeps them all
  lands, and they look exactly as they did.
