"""dashboard.menus.columns -- Settings ▸ Columns and Settings ▸ Panels.

Two menus over the main view's shape: which of its table columns are shown,
pinned or hidden, and which of its whole sections are drawn at all. Written
through muxsettings into dashboard.conf as DASHBOARD_COLUMNS_HIDDEN,
DASHBOARD_COLUMNS_PINNED and DASHBOARD_PANELS_HIDDEN; the parsing, the
validation and the cached reading are dashboard/columns.py's, which the
main view reads through as well, so the menu and the table can never
disagree about what the file says.

EVERY ROW SAYS WHAT IS TRUE THIS FRAME, not what the file holds. The state
comes from MainView.column_plans() -- what the LAST BUILD's horizontal
window actually did -- so a row reads "shown · off-screen right (shift-→)"
because that column is off the right of the table behind this menu, at this
terminal's width. A menu that recomputed it from the settings would have to
guess at the width and would be wrong at the two widths that matter.

HIDDEN WINS OVER PINNED, which is why enter cycles shown → pinned → hidden
→ shown in that order: every state is two presses from every other, and the
one impossible combination -- pinned AND hidden, a heading with no cell
under it -- cannot be reached by pressing enter at all.

NOTHING HERE CAN MAKE DATA UNREACHABLE. The argument, in full, because it
is the reason this menu is allowed to exist:

  * A HIDDEN COLUMN is a display choice and nothing else. The row keeps its
    cell, `listed_sessions()` keeps the session, the session menu (space)
    and enter act on the row under the cursor and have never read a column.
    Hiding DIRTY does not stop the dirty count being computed, being on the
    uncommitted panel, or reaching the watchdog.
  * A COLUMN OFF THE SIDE is still one shift-→ away, the panel's subtitle
    counts it and names the key, and this menu names it by name -- a title
    cannot hold nine column names at 80 columns, so the menu is where
    "where did RESUMED go" is answered.
  * A HIDDEN LANES TABLE leaves `f` working (it is a key, not a row) and
    leaves the uncommitted panel, which is the one that shows a dirty tree
    with no server in it -- the copy most likely to be lost. The lane rows
    leave the cursor walk because there is nothing on screen to light up.
  * A HIDDEN SYSTEM LINE takes the desktop-extras row with it, because that
    row rides the system line. That action would be unreachable, so THIS
    MENU GROWS A ROW FOR IT while the line is hidden -- the one piece of
    behaviour in this file that exists purely so the answer to "can I still
    do it" stays yes.
  * THE CLAUDE TABLE CANNOT BE HIDDEN and neither can the marker column the
    cursor is drawn in; dashboard/columns.py refuses both by name.

This file registers everything it needs -- the three keys, two menus, two
Settings rows and its help -- so it is one of the "a feature is one file"
kind, the way dashboard/menus/tabs.py is.
"""
from __future__ import annotations

import muxsettings
from dashboard import columns as columnsmod
from dashboard.core import DIM, EXTRA_HINTS, PROFILE, human_mb
from dashboard.data import processes, uptime_seconds

# THE COLUMNS EACH TABLE HAS, in the order dashboard/views/main.py lists
# them, less the unnamed marker column -- which is never listed because it
# is never a choice: it is where the cursor and the "▼ N more" markers are
# drawn, and column_window refuses to drop it.
#
# DUPLICATED FROM THE VIEW ON PURPOSE, and tests/test_columns_menu.py holds
# the two together: the menu has to list a column the frame does not
# currently have (ACCOUNT, below), so it cannot simply read the view's spec
# and be done. The test walks a wide frame and fails if any other name here
# is missing from it, which is the drift this would otherwise grow.
COLUMNS = {
    "lanes": ("PORT", "RAM", "AGE", "LANE", "ACCOUNT", "DIRTY", "STATE"),
    "claude": ("MON", "WINDOW", "MODEL", "CONTEXT", "SPENT", "IDLE",
               "STATE", "DIRTY", "WOUND", "RESUMED"),
}

# ACCOUNT is in the lanes table only while `f` shows every account. It is
# listed here ALWAYS: hiding it while it is on screen and then pressing `f`
# twice must not lose the choice, and a row that vanished from this menu
# with the column would be a setting the user could never take back.
ONLY_WITH_F = {("lanes", "ACCOUNT")}

# What each panel actually holds, said in the row, because "system" is not
# a thing anybody has a picture of until you say what is on it.
PANEL_HOLDS = {
    "deck": "the memory, swap and cpu header and the usage limits",
    "lanes": "the dev-server table (f, and the lane rows the cursor walks)",
    "uncommitted": "the dirty working trees, including ones with no server",
    "system": "the claude/playwright/home/extras line",
}


class ColumnsMenu:
    def __init__(self, app) -> None:
        self.app = app

    # ------------------------------------------------------------- reading
    def plans(self) -> dict:
        """What the last build decided, or {} before the first one."""
        view = self.app.view_of("main")
        return view.column_plans() if view is not None else {}

    def state_of(self, table: str, name: str) -> tuple[str, str]:
        """(state, note) for one column: what it is, and where it is."""
        hidden = columnsmod.hidden_columns(PROFILE).get(table, set())
        pinned = columnsmod.pinned_columns(PROFILE).get(table, set())
        if name in hidden:
            return "hidden", "not drawn; its data is unchanged"
        plan = self.plans().get(table)
        keep, left, right = (plan[0], plan[1], plan[2]) if plan else ([], [], [])
        if name in pinned:
            return "pinned", "always drawn, never squeezed, never scrolls off"
        if name in left:
            return "shown", "off-screen left (shift-←)"
        if name in right:
            return "shown", "off-screen right (shift-→)"
        if name in keep:
            return "shown", "on screen"
        # In neither list and not hidden: the frame does not have this
        # column at all, which today is ACCOUNT under a filtered lanes
        # table. Say which, rather than leaving a row with no state.
        if (table, name) in ONLY_WITH_F:
            return "shown", "only with f: all accounts"
        return "shown", "not in this frame"

    def counts(self) -> tuple[int, int]:
        hidden = columnsmod.hidden_columns(PROFILE)
        pinned = columnsmod.pinned_columns(PROFILE)
        n = sum(len(hidden.get(t, ())) for t in columnsmod.TABLES)
        m = sum(len(pinned.get(t, ()) - hidden.get(t, set()))
                for t in columnsmod.TABLES)
        return n, m

    # ------------------------------------------------------------ the rows
    def entries(self) -> list[dict]:
        items: list[dict] = []
        for table in columnsmod.TABLES:
            if items:
                items.append({"sep": True})
            for name in COLUMNS[table]:
                state, note = self.state_of(table, name)
                items.append({
                    "label": "%s · %-8s %s · %s" % (table, name, state, note),
                    # `on` is the green/dim marker every toggle row uses.
                    # SHOWN AND PINNED ARE BOTH ON: the question the colour
                    # answers is "is this column in the table", and pinned
                    # is the most in it a column can be.
                    "on": state != "hidden", "stay": True,
                    "act": (lambda t=table, n=name: self.cycle(t, n))})
        items.append({"sep": True})
        items.append({"label": "Back", "sub": "settings"})
        return items

    def cycle(self, table: str, name: str) -> str:
        """shown → pinned → hidden → shown, written to BOTH keys.

        Both, every time, because the two lists are one answer: a column
        that becomes hidden has to leave the pinned list in the same
        breath, or the file holds the one combination that cannot be drawn
        and the window has to rescue it on every frame afterwards.
        """
        hidden = {t: set(v) for t, v in columnsmod.hidden_columns(PROFILE).items()}
        pinned = {t: set(v) for t, v in columnsmod.pinned_columns(PROFILE).items()}
        if name in hidden.get(table, ()):
            hidden[table].discard(name)             # hidden -> shown
            pinned[table].discard(name)
            now = "shown"
        elif name in pinned.get(table, ()):
            pinned[table].discard(name)             # pinned -> hidden
            hidden[table].add(name)
            now = "hidden"
        else:
            pinned[table].add(name)                 # shown -> pinned
            now = "pinned"
        # NONE, not "": muxsettings.put deletes a key written empty, and an
        # absent pinned key means the DEFAULT rather than nothing -- so
        # unpinning the last column would quietly pin it again.
        for key, value in ((columnsmod.HIDDEN_KEY, columnsmod.unparse(hidden)),
                           (columnsmod.PINNED_KEY,
                            columnsmod.unparse(pinned) or columnsmod.NONE)):
            err = muxsettings.put(key, value, PROFILE)
            if err:
                columnsmod.forget()
                return "columns: not saved -- %s" % err
        columnsmod.forget()
        return "%s · %s %s  · %s" % (table, name, now,
                                     muxsettings.dashboard_conf_path(PROFILE).name)

    def title(self) -> str:
        n, m = self.counts()
        return "columns[/] [%s]· %d hidden · %d pinned" % (DIM, n, m)

    def hint(self) -> str:
        return ("enter shown → pinned → hidden · pinned never scrolls · "
                "hidden wins · esc back")


class PanelsMenu:
    def __init__(self, app) -> None:
        self.app = app

    def entries(self) -> list[dict]:
        off = columnsmod.hidden_panels(PROFILE)
        items: list[dict] = []
        for name in columnsmod.PANELS:
            shown = name not in off
            items.append({
                "label": "%-12s %s  %s" % (name, "shown" if shown else "hidden",
                                           PANEL_HOLDS[name]),
                "on": shown, "stay": True,
                "act": (lambda n=name: self.toggle(n))})
        if "system" in off:
            # THE EXTRAS ACTION, WITH ITS ROW GONE. It lives on the system
            # line, and the cursor cannot reach a line that is not drawn, so
            # hiding the panel would take the action with it. It comes here
            # instead -- the same call the main view's enter makes -- and
            # the label says why it is here.
            items.append({"sep": True})
            items.append({"label": self.extras_label(),
                          "act": self.extras, "stay": True})
        items.append({"sep": True})
        items.append({"label": "Back", "sub": "settings"})
        return items

    def extras_mb(self) -> float:
        # The same /proc walk the main frame does for this figure. It costs
        # what one frame costs and only while this menu is open, which is
        # the only time anybody is reading the number.
        procs = processes(uptime_seconds())
        return sum(p.rss_mb for p in procs
                   if any(h in p.cmdline for h in EXTRA_HINTS))

    def extras_label(self) -> str:
        mb = self.extras_mb()
        if mb:
            return ("Desktop extras: reclaim (%s)   the system line is hidden, "
                    "so the action is here" % human_mb(mb))
        return ("Desktop extras: start   the system line is hidden, "
                "so the action is here")

    def extras(self) -> str:
        view = self.app.view_of("main")
        if view is None:
            return "the main view is not loaded"
        return view.toggle_extras()

    def toggle(self, name: str) -> str:
        off = set(columnsmod.hidden_panels(PROFILE))
        off ^= {name}
        err = muxsettings.put(columnsmod.PANELS_KEY,
                              ",".join(n for n in columnsmod.PANELS if n in off),
                              PROFILE)
        columnsmod.forget()
        if err:
            return "panels: not saved -- %s" % err
        return "%s %s  · %s" % (name, "hidden" if name in off else "shown",
                                muxsettings.dashboard_conf_path(PROFILE).name)

    def title(self) -> str:
        n = len(columnsmod.hidden_panels(PROFILE))
        return "panels[/] [%s]· %d hidden · %s" % (DIM, n, columnsmod.PANELS_KEY)

    def hint(self) -> str:
        return ("enter show/hide · the claude table is the view and stays · "
                "esc back")


HELP_COLUMNS = f"""
  [{DIM}]COLUMNS AND PANELS (esc ▸ Settings ▸ Columns │ Panels)[/]
    The lanes and claude tables draw their columns through a HORIZONTAL
    WINDOW. Nothing is ever squeezed: a column is drawn at its full width or
    it is not drawn, so a narrow terminal loses whole columns instead of
    cutting every one of them to an ellipsis. [bold]shift-←[/] and [bold]shift-→[/] scroll the
    window over the table the cursor is in -- a lane row scrolls the lanes,
    a session or the extras row scrolls the claude -- and the panel's bottom
    border counts what is off each side ("◀ 2 more · 3 more ▶ · shift-←→").
    The plain [bold]←→[/] still fold the window tree.

    PINNED COLUMNS NEVER SCROLL OFF and are never squeezed. Unset, that is
    the column that names each row (LANE and WINDOW), because a table
    scrolled sideways with its name column gone is a grid of numbers about
    nothing. The unnamed first column -- the cursor's [bold]▸[/] and the
    "▼ N more" markers -- is always there and is not in the menu: it is not
    a choice.

    Settings ▸ Columns lists every column of both tables and enter cycles it
    shown → pinned → hidden. Each row says what is true of the frame behind
    the menu, including which side an off-screen column is on, which is
    where "where did RESUMED go" is answered -- a panel title cannot hold
    nine names at 80 columns. HIDDEN WINS OVER PINNED. ACCOUNT is always
    listed even though the lanes table only has it under [bold]f[/].

    Settings ▸ Panels leaves a whole section out: the deck header, the lanes
    table, the uncommitted trees or the system line. That is a CHOICE and is
    made before the short-terminal rule runs, so the "hidden: short
    terminal" note never names a panel you hid. A hidden panel's rows leave
    the cursor walk too -- and because the desktop-extras action rides the
    system line, hiding that line puts the action in the Panels menu rather
    than out of reach. The claude table is the view itself and cannot be
    hidden.

    All three are written to dashboard.conf: DASHBOARD_COLUMNS_HIDDEN,
    DASHBOARD_COLUMNS_PINNED and DASHBOARD_PANELS_HIDDEN, by NAME with the
    table in front ({columnsmod.DEFAULT_PINNED}) -- never by index, because
    STATE and DIRTY are in both tables and ACCOUNT comes and goes with [bold]f[/].
"""


def register(app) -> None:
    columnsmod.register_keys()
    cols, panels = ColumnsMenu(app), PanelsMenu(app)
    app.add_menu("columns", cols.entries, title_fn=cols.title,
                 hint_fn=cols.hint, esc_to="settings")
    app.add_menu("panels", panels.entries, title_fn=panels.title,
                 hint_fn=panels.hint, esc_to="settings")
    # UNDER Tabs ▸ (+5) AND Update ▸ (+6), which were already taken on main
    # when this landed -- the brief asked for +6 and +7 and named Tabs as
    # the holder of +5; update.py holds +6, so these are the next two free.
    # Counted when drawn, as those rows are.
    app.add_rows("settings", lambda a: [{
        "label": "Columns ▸  which columns the two tables show (%d hidden, %d pinned)"
                 % cols.counts(),
        "sub": "columns",
        "order": len(muxsettings.DASHBOARD_KEYS) * 10 + 7}])
    app.add_rows("settings", lambda a: [{
        "label": "Panels ▸  which panels the main view shows (%d hidden)"
                 % len(columnsmod.hidden_panels(PROFILE)),
        "sub": "panels",
        "order": len(muxsettings.DASHBOARD_KEYS) * 10 + 8}])
    app.add_help("COLUMNS AND PANELS", HELP_COLUMNS, order=32)
