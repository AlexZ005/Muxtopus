## choose, pin and scroll the main view's columns; hide its panels

- **A narrow terminal no longer squeezes every column to an ellipsis.** A
  column is drawn at its full width or it is not drawn at all. At 80 columns
  the claude table used to cut SPENT, IDLE and DIRTY to `…` and lose MON and
  WINDOW outright; it now draws five whole columns and says on the panel's
  bottom border that six more are to the right.
- **`Shift-←` and `Shift-→` scroll a table sideways**, through the columns
  that are not pinned. They move the table the cursor is in — a lane row
  scrolls the lanes table, a session or the desktop-extras row scrolls the
  claude table. Plain `←` `→` still fold the window tree, and the footer
  names the new pair beside them.
- **Pinned columns never scroll off and are never squeezed.** Until you
  change it that is the column that names each row — LANE and WINDOW —
  because a table scrolled sideways with its name column gone is a grid of
  numbers about nothing.
- **The panel's bottom border counts what is off each side**: `◀ 2 more ·
  3 more ▶ · shift-←→`, the same place and the same voice the tab strip
  already uses for `←→ tab 7/9`. Nothing is written there when every column
  fits. If the columns you pinned do not fit by themselves, it says that in
  words rather than offering a key that cannot move.
- **`esc ▸ Settings ▸ Columns`** lists every column of both tables and
  `enter` cycles it shown → pinned → hidden. Each row says what is true of
  the screen behind the menu, including which side an off-screen column is
  on — which is where "where did RESUMED go" is answered, since a panel
  title cannot hold nine column names. ACCOUNT is always listed, even though
  the lanes table only shows it under `f`.
- **`esc ▸ Settings ▸ Panels`** leaves a whole section out: the deck header,
  the lanes table, the uncommitted trees or the system line. That is your
  choice and not the short-terminal rule, so the `hidden: short terminal`
  note never names a panel you hid. Hiding the system line moves the desktop
  extras action into that menu, so it stays one `enter` away instead of
  disappearing with the line it sat on. The claude table is the screen
  itself and cannot be hidden.
- **Nothing you hide can lose you anything.** A hidden column keeps its data
  — the row, the session menu and `enter` never read one — a hidden lanes
  table leaves `f` and the uncommitted panel, and every hidden column is
  named in the menu that hid it.
