"""dashboard.menus.hints -- Settings ▸ Hints: what the dashboard explains.

Four on/off keys, all ON by default, each turning off one KIND of on-screen
explanation. A user who has never opened this menu sees exactly the
dashboard they already had; a user who knows the keys can have the screen
back.

THE WORD "HINT" MEANS FOUR THINGS IN THIS REPO, and this menu is now a fifth
name for the group. Said out loud once, here, because a reader who guesses
wrong turns off the wrong line:

    the GROUP                 this menu, DASHBOARD_HINTS_*, App.guide
    a menu's HINT LINE        MENU_HINT, add_menu(hint_fn=…), App.menu_hint,
                              menulayout.HINT -- the "↑↓ pick · enter choose ·
                              esc close" line inside a panel. The row that
                              turns it off is "Menu hint line", and the word
                              LINE in that label is doing the work.
    a FOOTER note             App.add_hint / App.hints() -- the "· 3 ?" marks
                              other modules append to the main key line. The
                              "Footer key line" row hides the KEY LIST and
                              never these: a count is news, a legend is not.
    a SETTING's explanation   muxsettings meta["hint"] -- now drawn as the
                              `desc` of that setting's row.

So the key names avoid the word entirely where they can (ROW_DESC,
MENU_LINE, FOOTER_KEYS, TABLE_NOTES) and are greppable as a set: nothing
else in the tree matches DASHBOARD_HINTS_.

EXPERT MODE is one row that moves all four together, in whichever direction
is left: all on -> all off, anything else -> all on. It is not a fifth
setting and nothing stores it -- storing it would give two sources of truth
for the same four values and a way for them to disagree -- so its label
reads the four back (`Expert mode: off`, `: ON`, `: mixed`) and its
description says where the next enter goes.

WHAT STAYS WHATEVER THIS MENU SAYS: a notice. With the menu hint line off
the line comes back for the eight seconds a notice lasts and carries it
alone (App.menu_hint), and with the footer key line off the notice, the
modules' own marks and the reset flourish still draw. A setting that could
swallow "not a directory" would be this repo's worst bug shipped twice.

This file registers everything it needs -- the four keys, the row in
Settings, the menu, the help -- so it is one of the "a feature is one file"
kind.
"""
from __future__ import annotations

import muxsettings
from dashboard.app import HINT_KEYS
from dashboard.core import DIM, PROFILE

# THE ROWS, in the order they are drawn: (kind, label, what turning it off
# hides). The labels are COLUMN-ALIGNED on their values below -- four rows
# whose only difference is a word and an ON/off read as a list of switches
# when the switches line up, and as four sentences when they do not.
ROWS = (
    ("rows",   "Row descriptions",
     "the dim sentence under the cursor's row, and a submenu's own "
     "description under its title"),
    ("menu",   "Menu hint line",
     "the ↑↓ pick · enter choose · esc close line inside a menu panel; a "
     "notice still takes it"),
    ("footer", "Footer key line",
     "the q quit · r refresh · R reload list under the main view; notices "
     "and counts stay"),
    ("notes",  "Inline table notes",
     "(navigate by arrows), (f: all) and their like inside the tables"),
)
# Padded so the values line up. Measured from the labels above rather than
# typed, so a fifth row cannot quietly break the column.
_PAD = max(len(label) for _kind, label, _why in ROWS) + 1


class HintsMenu:
    def __init__(self, app) -> None:
        self.app = app

    def state(self) -> dict[str, bool]:
        """All four, ONE read of the settings file for the whole frame.

        App.guide caches the four together for a second and the menu is
        rebuilt every frame, so this is per frame at worst -- never the four
        reads per row that asking inside the loop below would be."""
        return {kind: self.app.guide(kind) for kind, _label, _why in ROWS}

    def entries(self) -> list[dict]:
        on = self.state()
        items: list[dict] = []
        for kind, label, why in ROWS:
            items.append({"label": "%-*s %s" % (_PAD, label + ":",
                                                "ON" if on[kind] else "off"),
                          "desc": "off hides " + why,
                          "on": on[kind], "stay": True,
                          "act": lambda k=kind: self.toggle(k)})
        items.append({"sep": True})
        every = all(on.values())
        items.append({"label": "Expert mode: %s" % (
                          "off" if every else "ON" if not any(on.values()) else "mixed"),
                      "desc": "turn all four off" if every else "turn all four back on",
                      "on": not any(on.values()), "stay": True,
                      "act": self.expert})
        items.append({"sep": True})
        items.append({"label": "Back", "sub": "settings"})
        return items

    # ------------------------------------------------------------- writing
    def _put(self, kinds: tuple, value: str) -> str:
        """Write one or four, and say what was written and where -- the same
        sentence Settings ▸ Tabs' toggle says, because it is the same
        promise: a value is reported as saved only once put has read it back
        off disk."""
        for kind in kinds:
            err = muxsettings.put(HINT_KEYS[kind], value, PROFILE)
            if err:
                # forget_guide even on the failure: put may have written some
                # of the four before it refused, and a stale cache would then
                # draw a row that disagrees with the file.
                self.app.forget_guide()
                return "hints: not saved -- %s" % err
        self.app.forget_guide()
        what = "every hint" if len(kinds) > 1 else \
            dict((k, l) for k, l, _w in ROWS)[kinds[0]].lower()
        return "%s %s  · %s" % (what, "on" if value == "on" else "off",
                                muxsettings.dashboard_conf_path(PROFILE).name)

    def toggle(self, kind: str) -> str:
        return self._put((kind,), "off" if self.app.guide(kind) else "on")

    def expert(self) -> str:
        """All four at once, in whichever direction is left. Not a stored
        setting: it reads the four and writes the four."""
        on = self.state()
        return self._put(tuple(k for k, _l, _w in ROWS),
                         "off" if all(on.values()) else "on")

    # ------------------------------------------------------------- chrome
    def title(self) -> str:
        on = self.state()
        off = sum(1 for v in on.values() if not v)
        return "hints[/] [%s]· %d of %d off" % (DIM, off, len(ROWS))

    def desc(self) -> str:
        return "what the dashboard explains on screen; Expert mode turns it all off"

    def hint(self) -> str:
        return "enter show/hide · a notice is shown whatever is off here · esc back"


HELP_HINTS = f"""
  [{DIM}]WHAT THE DASHBOARD EXPLAINS (esc ▸ Settings ▸ Hints)[/]
    The dashboard explains itself in four places, and each can be turned off:
    the dim ROW DESCRIPTION under the cursor in a menu (and the line a
    submenu draws under its own title), the MENU HINT LINE inside a panel
    (↑↓ pick · enter choose · esc close), the FOOTER KEY LINE under the main
    view (q quit, r refresh, R reload …), and the INLINE TABLE NOTES --
    (navigate by arrows), (f: all), (enter reclaims).

    All four start ON, so nothing changes until you ask. EXPERT MODE is one
    row that moves all four: with everything on it turns everything off, and
    from anywhere else it turns everything back on. Each panel is SHORTER
    with its explanations off -- the lines are not blanked, they are not
    reserved.

    A MESSAGE STILL REACHES YOU whatever is off here. With the menu hint line
    off, that line comes back for the eight seconds a notice lasts and
    carries the notice alone; with the footer key line off, the notice, the
    counts other views put on that line and the reset flourish all still
    draw. The keys are DASHBOARD_HINTS_ROW_DESC, _MENU_LINE, _FOOTER_KEYS
    and _TABLE_NOTES in dashboard.conf.
"""


def _register_keys() -> None:
    muxsettings.register({
        HINT_KEYS["rows"]: {
            "label": "Row descriptions", "kind": "onoff",
            "hint": "the dim line under a menu's cursor, and a submenu's header"},
        HINT_KEYS["menu"]: {
            "label": "Menu hint line", "kind": "onoff",
            "hint": "the ↑↓/enter/esc line inside a panel; a notice still takes it"},
        HINT_KEYS["footer"]: {
            "label": "Footer key line", "kind": "onoff",
            "hint": "the key list under the main view; notices and counts stay"},
        HINT_KEYS["notes"]: {
            "label": "Inline table notes", "kind": "onoff",
            "hint": "(navigate by arrows), (f: all) and their like in the tables"},
    }, menu="hints")


def register(app) -> None:
    # Once per process, as tabs.py does: the settings store is module-level
    # and the tests build several Apps in one interpreter.
    if muxsettings.spec_of(HINT_KEYS["rows"]) is None:
        _register_keys()
    menu = HintsMenu(app)
    app.add_menu("hints", menu.entries, title_fn=menu.title, hint_fn=menu.hint,
                 desc_fn=menu.desc, esc_to="settings")
    app.add_rows("settings", lambda a: [{
        "label": "Hints ▸",
        "sub": "hints",
        # Under the last setting with the other submenu rows: Notifications
        # and Tabs take +5, Updates +6, and dash-columns' Columns ▸ and
        # Panels ▸ took +7 and +8 when they merged. +9 keeps this one last
        # and ties with nothing -- a tie would only sort by label, but an
        # order nobody shares is one less thing to reason about.
        "order": len(muxsettings.DASHBOARD_KEYS) * 10 + 9}])
    # 32 is COLUMNS AND PANELS'; 33 puts this after it, beside the menus it
    # is about rather than in the middle of them.
    app.add_help("HINTS", HELP_HINTS, order=33)
