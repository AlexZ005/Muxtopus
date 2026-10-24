"""dashboard.menus.reports -- Settings ▸ Reports ▸, what a lane's parent is told.

docs/watchdog.md, "Reports to the parent". Every row is a key the watchdog
reads -- WATCHDOG_STALL_MIN and the WATCHDOG_REPORT_* / _NUDGE_ / _CLOSE_
family -- written through muxsettings into this account's dashboard.conf; the
daemon notices the edit within one pass and re-reads its config.

THE DEFAULTS ARE SHOWN, NOT IMPLIED. Unlike the budget's knobs, none of these
has a plan preset behind it, and two of them default to OFF: a nudge starts a
turn nobody asked for and a close cannot be taken back. So an unset row says
"(default: off)" rather than leaving the reader to guess which way an empty
value falls -- the budget menu's "empty onoff means on" would read the nudge
as switched on when it is not.
"""
from __future__ import annotations

from rich.markup import escape

import muxsettings
from dashboard.core import DIM, PROFILE


def _minutes(v: str) -> str:
    """"" or why not: whole minutes, or empty for the default."""
    if v == "" or v.isdigit():
        return ""
    return "whole minutes, or empty for the default (got %r)" % v


def _off_or_minutes(v: str) -> str:
    if v in ("", "off") or v.isdigit():
        return ""
    return "off, or whole minutes (got %r)" % v


# THE KEYS, in menu order -- the order of muxconfig.KEYS and profile.sh, so a
# reader comparing the three lists finds them in the same place.
REPORT_KEYS: dict[str, dict] = {
    "WATCHDOG_STALL_MIN": {
        "label": "A lane is stalled after (minutes)", "kind": "text", "check": _minutes,
        "default": "15", "hint": "idle at its prompt, handover open, nothing running; 0 off"},
    "WATCHDOG_REPORT": {
        "label": "Report lane problems to", "kind": "choice",
        "choices": ("on", "notify-only", "off"), "default": "on",
        "hint": "on: the lane's parent window, else the phone · notify-only: the phone"},
    "WATCHDOG_REPORT_REPEAT_MIN": {
        "label": "Say it again after (minutes)", "kind": "text", "check": _minutes,
        "default": "60", "hint": "while the same problem lasts; a new one is said at once"},
    "WATCHDOG_REPORT_E2E_MIN": {
        "label": "Report an e2e slot held over (minutes)", "kind": "text", "check": _minutes,
        "default": "300", "hint": "a run that is not finishing holds every other lane; 0 off"},
    "WATCHDOG_REPORT_MEM_MIN": {
        "label": "Report entries memory-held over (minutes)", "kind": "text", "check": _minutes,
        "default": "30", "hint": "told to the windows they would open under; 0 off"},
    "WATCHDOG_NUDGE_STALLED": {
        "label": "Nudge a stalled lane", "kind": "onoff", "default": "off",
        "hint": "one line, once per stall: its job ended, read the log, continue"},
    "WATCHDOG_CLOSE_FINISHED": {
        "label": "Close a finished window after (minutes)", "kind": "text",
        "check": _off_or_minutes, "default": "off",
        "hint": "handover in done/, nothing pending under it; off keeps it"},
    "WATCHDOG_DONE_NUDGE": {
        "label": "Re-nudge a finished run after (minutes)", "kind": "text",
        "check": _off_or_minutes, "default": "5",
        "hint": "a mux-done marker whose notification was lost; off never"},
}


class ReportsMenu:
    """Settings ▸ Reports. The knobs of report_pass in claude-watchdog.sh."""

    def __init__(self, app) -> None:
        self.app = app

    @staticmethod
    def shown(key: str, val: str) -> str:
        meta = muxsettings.spec_of(key) or {}
        if meta.get("kind") == "onoff":
            return "ON" if (val or meta["default"]) == "on" else "off"
        return val if val else "(default: %s)" % meta["default"]

    def entries(self) -> list[dict]:
        items: list[dict] = [
            {"label": "Ask now: claude-watchdog.sh --health", "desc":
             "the same verdicts, once, in the shell -- nothing is sent", "act": lambda: (
                 "run claude-watchdog.sh --health%s in a shell"
                 % (" --profile %s" % PROFILE if PROFILE else ""))},
            {"sep": True},
        ]
        for key, meta in muxsettings.keys_of("reports").items():
            val = muxsettings.get(key, PROFILE)
            row = {"label": "%s: %s" % (meta["label"], self.shown(key, val)),
                   "desc": meta["hint"], "stay": True,
                   "act": lambda k=key: self._edit(k)}
            if meta["kind"] == "onoff":
                row["on"] = (val or meta["default"]) == "on"
            items.append(row)
        items += [{"sep": True}, {"label": "Back", "sub": "settings"}]
        return items

    def _edit(self, key: str) -> str:
        meta = muxsettings.spec_of(key)
        cur = muxsettings.get(key, PROFILE)
        if meta["kind"] == "onoff":
            return self._put(key, "off" if (cur or meta["default"]) == "on" else "on")
        if meta["kind"] == "choice":
            choices = list(meta["choices"])
            i = choices.index(cur) if cur in choices else 0
            self.app.picker = {"title": meta["label"], "i": i, "options": choices,
                               "fn": lambda c, k=key: self._put(k, c)}
            return ""
        self.app.prompt = {"title": meta["label"] + " (empty: %s)" % meta["default"], "buf": cur,
                           "keep_menu": True,
                           "fn": lambda s, k=key: self._put(k, s.strip())}
        return ""

    def _put(self, key: str, value: str) -> str:
        meta = muxsettings.spec_of(key)
        # AN EMPTY LINE WRITES THE DEFAULT rather than removing the key:
        # muxsettings.put reads the value back to prove it, and with the key
        # gone it reads the built-in default -- "15" is not "" -- and reports
        # a higher layer overriding it, which is not what happened.
        value = value or meta["default"]
        err = muxsettings.put(key, value, PROFILE)
        if err:
            return "%s: %s" % (meta["label"], err)
        where = muxsettings.dashboard_conf_path(muxsettings.scope_of(key, PROFILE)).name
        return "%s = %s  · %s -- the watchdog re-reads it within a pass" % (
            meta["label"], value, where)

    def title(self) -> str:
        return "reports[/] [%s]· %s" % (DIM, escape("WATCHDOG_REPORT_*"))

    def desc(self) -> str:
        return "what a lane's parent window is told when the lane stalls, finishes or gets stuck"


def register(app) -> None:
    muxsettings.register(REPORT_KEYS, menu="reports")
    menu = ReportsMenu(app)
    app.add_menu("reports", menu.entries, title_fn=menu.title,
                 hint_fn=lambda: "↑↓ pick · enter change · esc back",
                 desc_fn=menu.desc, esc_to="settings")
    # Beside Budget ▸ (the same order; ties break by label, B before R).
    app.add_rows("settings", lambda a: [{
        "label": "Reports ▸", "sub": "reports",
        "order": len(muxsettings.DASHBOARD_KEYS) * 10 + 4}])
