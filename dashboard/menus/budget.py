"""dashboard.menus.budget -- Settings ▸ Budget ▸, the budget guard's knobs.

docs/budget.md. Every row is a WATCHDOG_BUDGET_* key (or one of the two
wind-down lines, or the e2e slot count) written through muxsettings into this
account's dashboard.conf; the daemon notices the edit within one pass and
re-reads its config, so a change here is in force by the next judgement.

AN EMPTY KNOB IS THE PLAN'S NUMBER. The presets live in one place --
claude-watchdog.sh budget_preset -- and this menu does not copy them: it
shows what the daemon last resolved each knob to (the `budget` file it
publishes), so "(plan: 4)" is the number actually in force, not a second
table that could disagree with the first. Typing a number pins it; an empty
line gives it back to the plan.
"""
from __future__ import annotations

from rich.markup import escape

import muxsettings
from dashboard.core import DIM, PROFILE
from dashboard.views.budget import read_budget


def _whole(v: str) -> str:
    """"" or why not: a whole number, or empty for the plan's value."""
    if v == "" or v.isdigit():
        return ""
    return "a whole number, or empty for the plan's value (got %r)" % v


def _pct(v: str) -> str:
    why = _whole(v)
    if why:
        return why
    if v and not 1 <= int(v) <= 100:
        return "a percentage, 1-100 (got %s)" % v
    return ""


# THE KEYS, in menu order. `shows` names the field of the budget
# file that holds the value in force, for the "(plan: N)" a blank knob shows.
BUDGET_KEYS: dict[str, dict] = {
    "WATCHDOG_BUDGET": {
        "label": "Budget guard", "kind": "onoff",
        "hint": "hold launches that would overspend; resume in waves; off holds nothing"},
    "WATCHDOG_BUDGET_PLAN": {
        "label": "Plan", "kind": "choice",
        "choices": ("auto", "pro", "max5x", "max20x", "team", "custom"),
        "hint": "auto reads the account's rateLimitTier; each sets the defaults below"},
    "WATCHDOG_BUDGET_LANES": {
        "label": "Most windows working at once", "kind": "text", "check": _whole,
        "shows": "lanes", "hint": "a due entry past this waits for one to stop"},
    "WATCHDOG_BUDGET_HOLD_PCT": {
        "label": "Hold new launches at session %", "kind": "text", "check": _pct,
        "shows": "hold_pct", "hint": "p1's line; release +10, ops -5, p2 -10"},
    "WATCHDOG_HARD_PCT": {
        "label": "Wind down at session %", "kind": "text", "check": _pct,
        "hint": "the hard band: checkpoint and stop (same class shift); default 85"},
    "WATCHDOG_SOFT_PCT": {
        "label": "Soft note at session %", "kind": "text", "check": _pct,
        "hint": "the soft band: fewer subagents, partial reads; default 65"},
    "WATCHDOG_BUDGET_LANE_PCT": {
        "label": "Session % one lane burns an hour", "kind": "text", "check": _whole,
        "shows": "lane_pct", "hint": "the estimate between readings; measured 8 on Max 5x"},
    "WATCHDOG_BUDGET_START_PCT": {
        "label": "Session % a start costs", "kind": "text", "check": _whole,
        "shows": "start_pct", "hint": "a fresh lane's first 15 minutes; measured 3.5 on Max 5x"},
    "WATCHDOG_BUDGET_CHECKPOINT_MIN": {
        "label": "Minutes a lane needs to checkpoint", "kind": "text", "check": _whole,
        "shows": "checkpoint_min", "hint": "never start one that would run out sooner"},
    "WATCHDOG_BUDGET_DAY_PCT": {
        "label": "Weekly pace, % per day", "kind": "text", "check": _pct,
        "shows": "day_pct", "hint": "ahead of it, p2/ops wait (p1 two days ahead); manual resets count"},
    "WATCHDOG_BUDGET_WAVE": {
        "label": "Resume wave size", "kind": "text", "check": _whole,
        "shows": "wave", "hint": "windows resumed (and `at: reset` entries started) per wave"},
    "WATCHDOG_BUDGET_WAVE_MIN": {
        "label": "Minutes between waves", "kind": "text", "check": _whole,
        "shows": "wave_min", "hint": "the next wave waits this long after the last"},
    "WATCHDOG_BUDGET_FRESH_CTX": {
        "label": "Resume FRESH above (tokens)", "kind": "text", "check": _whole,
        "shows": "fresh_ctx", "hint": "a bigger stopped window restarts from its handover"},
    "WATCHDOG_BUDGET_PROBE_MIN": {
        "label": "Read the usage every (minutes)", "kind": "text", "check": _whole,
        "hint": "while anything works; no tokens, a throwaway claude ~15 s"},
    "MUXTOPUS_E2E_SLOTS": {
        "label": "e2e runs at once (e2e-slot)", "kind": "text", "check": _whole,
        "scope": "global", "hint": "machine-wide Playwright slots; default 2"},
}

DEFAULTS = {"WATCHDOG_HARD_PCT": "85", "WATCHDOG_SOFT_PCT": "65",
            "WATCHDOG_BUDGET_PROBE_MIN": "15", "MUXTOPUS_E2E_SLOTS": "2"}


class BudgetMenu:
    """Settings ▸ Budget. Not a View: `b` is the screen; this is the knobs."""

    def __init__(self, app) -> None:
        self.app = app

    def shown(self, key: str, val: str, b: dict[str, str]) -> str:
        meta = muxsettings.spec_of(key) or {}
        if meta.get("kind") == "onoff":
            return "ON" if (val or "on") == "on" else "off"
        if val:
            return val
        if key == "WATCHDOG_BUDGET_PLAN":
            return "auto"
        f = meta.get("shows")
        if f and b.get(f):
            return "(plan: %s)" % b[f]
        return "(default: %s)" % DEFAULTS.get(key, "plan")

    def entries(self) -> list[dict]:
        b = read_budget()
        plan = b.get("plan", "")
        items: list[dict] = [
            {"label": "Budget: %s" % (("plan %s · %s" % (plan, b.get("plan_src", "")))
                                      if plan else "no verdict yet"),
             "desc": "the figures and every window the guard holds or queues (b)",
             "act": lambda: (self.app.switch_to("budget"), "")[1]},
            {"sep": True},
        ]
        for key, meta in muxsettings.keys_of("budget").items():
            val = muxsettings.get(key, PROFILE)
            row = {"label": "%s: %s" % (meta["label"], self.shown(key, val, b)),
                   "desc": meta["hint"], "stay": True,
                   "act": lambda k=key: self._edit(k)}
            if meta["kind"] == "onoff":
                row["on"] = (val or "on") == "on"
            items.append(row)
        items += [{"sep": True}, {"label": "Back", "sub": "settings"}]
        return items

    def _edit(self, key: str) -> str:
        meta = muxsettings.spec_of(key)
        cur = muxsettings.get(key, PROFILE)
        if meta["kind"] == "onoff":
            return self._put(key, "off" if (cur or "on") == "on" else "on")
        if meta["kind"] == "choice":
            choices = list(meta["choices"])
            i = choices.index(cur) if cur in choices else 0
            self.app.picker = {"title": meta["label"], "i": i, "options": choices,
                               "fn": lambda c, k=key: self._put(k, c)}
            return ""
        self.app.prompt = {"title": meta["label"] + " (empty: the plan's)", "buf": cur,
                           "keep_menu": True,
                           "fn": lambda s, k=key: self._put(k, s.strip())}
        return ""

    def _put(self, key: str, value: str) -> str:
        meta = muxsettings.spec_of(key)
        err = muxsettings.put(key, value, PROFILE)
        if err:
            return "%s: %s" % (meta["label"], err)
        where = muxsettings.dashboard_conf_path(muxsettings.scope_of(key, PROFILE)).name
        return "%s = %s  · %s -- the watchdog re-reads it within a pass" % (
            meta["label"], value or "(the plan's)", where)

    def title(self) -> str:
        return "budget[/] [%s]· %s" % (DIM, escape("WATCHDOG_BUDGET_*"))

    def desc(self) -> str:
        return "how many windows, how much of the 5-hour window and the week, and how to come back"


def register(app) -> None:
    muxsettings.register(BUDGET_KEYS, menu="budget")
    menu = BudgetMenu(app)
    app.add_menu("budget", menu.entries, title_fn=menu.title,
                 hint_fn=lambda: "↑↓ pick · enter change · esc back",
                 desc_fn=menu.desc, esc_to="settings")
    app.add_rows("settings", lambda a: [{
        "label": "Budget ▸", "sub": "budget",
        "order": len(muxsettings.DASHBOARD_KEYS) * 10 + 4}])
