"""dashboard.menus.notify -- Settings ▸ Notifications, and the needs-you state.

docs/plan-notify-telegram.md §1 and §4. The watchdog can tell a phone four
things and obey what the phone answers; this file is where a hand switches
any of that on or off, sets it up, and proves it works -- and it is one new
file, registering through the seam, with nothing in the shell edited.

    Settings ▸ Notifications ▸      a menu kind of its own (esc_to="settings")
    the seven MUXTOPUS_NOTIFY_* keys via muxsettings.register(..., menu="notify")
    `waiting` drawn as a yellow `needs you` via app.add_state

WHY THE SEVEN KEYS ARE NOT IN THE SETTINGS LIST. muxsettings.register puts a
module's keys into the Settings menu itself, which is right for a module with
one or two. Seven is a screen, so they are registered with `menu="notify"`:
full settings in every other way -- the same get, put, validate and the same
written-and-read-back proof -- but drawn here, by the rows below, instead of
in the list above. That is the only change this lane made outside its own
files (muxsettings.py, which is nobody's shell), and it is in
~/.code/handovers/QUESTIONS-notify-dash.md with what the alternatives were.

THE SWITCHES LIVE IN THE SETTINGS STORE, not in claude-notify.conf: that file
holds a TOKEN and is per machine, while these are preferences, per account,
and the watchdog already reads the store through mux_load_config. Nothing in
this file ever reads or writes claude-notify.conf; `Set up…` hands that to
claude-notify.sh in a window of its own.
"""
from __future__ import annotations

import os
import subprocess
import time

from rich.markup import escape

import muxsettings
from dashboard.core import DIM, PROFILE, SCRIPTS, YELLOW

NOTIFY_SH = SCRIPTS / "claude-notify.sh"

# The seven, in the order they have in muxconfig.KEYS and profile.sh's
# MUX_CONFIG_KEYS -- the order a reader comparing the three lists expects,
# and the order the rows come out in, because this dict is what draws them.
NOTIFY_KEYS: dict[str, dict] = {
    "MUXTOPUS_NOTIFY_WAITING": {
        "label": "A window is waiting for you", "kind": "onoff",
        "hint": "a permission or trust prompt, seen twice -- with Yes · No · More"},
    "MUXTOPUS_NOTIFY_QUESTIONS": {
        "label": "A lane has questions", "kind": "onoff",
        "hint": "a new unanswered QUESTIONS file, or a new fork in one"},
    "MUXTOPUS_NOTIFY_TROUBLE": {
        "label": "Trouble", "kind": "onoff",
        "hint": "stalled or errored entries, a stranded lane, a failed launch"},
    "MUXTOPUS_NOTIFY_BLOCKED_AFTER": {
        "label": "Say an entry is blocked after", "kind": "choice",
        "choices": ("0", "30", "60", "120", "360"),
        "hint": "plain blocked is ordinary waiting; this is when it stops being"},
    "MUXTOPUS_NOTIFY_DONE": {
        "label": "A lane finished", "kind": "onoff",
        "hint": "its gist, and the entries it released"},
    "MUXTOPUS_NOTIFY_INBOUND": {
        "label": "Let the phone answer", "kind": "onoff",
        "hint": "off: the buttons and the bot's commands are refused for this account"},
    "MUXTOPUS_NOTIFY_PANE_TEXT": {
        "label": "Quote the prompt box", "kind": "onoff",
        "hint": "pane text leaves the machine for Telegram's servers"},
}

# The blocked-after row is minutes on disk and words on screen. One table,
# both ways, so a value written by hand that is not in it still shows as
# itself ("45 min") rather than as nothing.
BLOCKED_WORDS = {"0": "never", "30": "30m", "60": "1h", "120": "2h", "360": "6h"}

HELP_NOTIFY = f"""
  [{DIM}]NOTIFICATIONS (esc ▸ Settings ▸ Notifications)[/]
    The watchdog can tell a phone four things -- a window is waiting for a
    permission prompt, a lane has questions, something is in trouble, a lane
    finished -- and each is a switch of its own, told ONCE per occurrence and
    never per pass. A `waiting` window is drawn here as a yellow [needs you],
    which is the same fact on the screen you are reading.

    `Let the phone answer` is the inbound half: Yes · No · More under a
    prompt, (a) (b) (c) · ✎ under a fork, and the bot's own menu
    (/status, /pending, /questions, /blocked, /windows, /mute). With all four
    push switches off and this one on, the bot is silent until asked -- a
    supported way to run it. `Quote the prompt box` is the one line of pane
    text that leaves this machine for Telegram's servers; off, a waiting
    message names the window and nothing else.

    `Set up…` opens {NOTIFY_SH.name} --setup in a tmux window of its own:
    it walks BotFather, validates the token, waits for your first START, and
    writes ~/.config/claude-notify.conf (0600 -- it holds a secret, and it is
    the ONE file here the dashboard never reads or writes itself). The
    switches above are not in it: they are settings, per account, in the
    dashboard's own store.
"""


class NotifyMenu:
    """Settings ▸ Notifications. Not a View: it draws no screen of its own."""

    def __init__(self, app) -> None:
        self.app = app
        self._status = ""
        self._status_at = 0.0

    # ------------------------------------------------------------ status
    def status(self, force: bool = False) -> str:
        """`claude-notify.sh --status` in one line, CACHED.

        A menu's rows are rebuilt every frame, so a row that forks is a fork
        per frame -- the rule badges are held to, and a menu row is no
        cheaper. Ten seconds is short enough that `Send a test` shows up in
        the row that reports it and long enough that holding the menu open
        costs nothing."""
        now = time.time()
        if not force and self._status and now - self._status_at < 10:
            return self._status
        self._status_at = now
        if not NOTIFY_SH.exists():
            self._status = "%s is not in the checkout" % NOTIFY_SH.name
            return self._status
        try:
            r = subprocess.run([str(NOTIFY_SH), "--status"], capture_output=True,
                               text=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._status = "cannot ask %s: %s" % (NOTIFY_SH.name, exc)
            return self._status
        if r.returncode != 0:
            self._status = "not configured"
            return self._status
        # backend: telegram / last sent: 2026-09-18 09:12:01 / last FAILED: ...
        got: dict[str, str] = {}
        for line in r.stdout.splitlines():
            k, _, v = line.partition(":")
            got[k.strip()] = v.strip()
        out = got.get("backend", "?")
        if "last sent" in got:
            out += " ✓ last sent %s" % _ago(got["last sent"])
        else:
            out += " · nothing sent yet"
        if "last FAILED" in got:
            out += " · LAST FAILED %s" % got["last FAILED"].split(" ")[0]
        self._status = out
        return self._status

    def act_status(self) -> str:
        return "notifications: %s" % self.status(force=True)

    # ------------------------------------------------------------- rows
    def entries(self) -> list[dict]:
        items: list[dict] = [
            {"label": "Notifications: %s" % self.status(),
             "act": self.act_status, "stay": True},
            {"label": "Set up…  the guide: pick a backend, paste the token, press START",
             "act": self.act_setup},
            {"label": "Send a test  one message, to prove the phone hears this account",
             "act": self.act_test, "stay": True},
            {"sep": True},
        ]
        if not os.environ.get("TMUX"):
            items[1]["disabled"] = "not inside tmux: run %s --setup" % NOTIFY_SH
        for key, meta in muxsettings.keys_of("notify").items():
            val = muxsettings.get(key, PROFILE)
            if meta["kind"] == "onoff":
                items.append({
                    "label": "%s: %s  %s" % (meta["label"], "ON" if val == "on" else "off",
                                             meta["hint"]),
                    "on": val == "on", "stay": True,
                    "act": lambda k=key: self._put(k, "off" if
                                                   muxsettings.get(k, PROFILE) == "on" else "on")})
            else:
                items.append({
                    "label": "%s: %s  %s" % (meta["label"], self._shown(key, val), meta["hint"]),
                    "stay": True, "act": lambda k=key: self._choose(k)})
        items.append({"sep": True})
        items.append({"label": "Back", "sub": "settings"})
        return items

    def _shown(self, key: str, val: str) -> str:
        if key == "MUXTOPUS_NOTIFY_BLOCKED_AFTER":
            return BLOCKED_WORDS.get(val, "%s min" % val if val else "2h")
        return val or "(default)"

    def _choose(self, key: str) -> str:
        """A choice row. The stored value is minutes; the picker offers words,
        because `120` is not a thing a hand recognises as two hours."""
        meta = muxsettings.spec_of(key)
        choices = list(meta["choices"])
        shown = [BLOCKED_WORDS.get(c, c) for c in choices]
        cur = muxsettings.get(key, PROFILE)
        i = choices.index(cur) if cur in choices else 0
        self.app.picker = {
            "title": meta["label"], "i": i, "options": shown,
            "fn": lambda word, k=key, c=choices, s=shown: self._put(
                k, c[s.index(word)] if word in s else word)}
        return ""

    def _put(self, key: str, value: str) -> str:
        meta = muxsettings.spec_of(key)
        err = muxsettings.put(key, value, PROFILE)
        if err:
            return "%s: %s" % (meta["label"], err)
        return "%s = %s  · %s" % (meta["label"], self._shown(key, value),
                                  muxsettings.dashboard_conf_path(PROFILE).name)

    # ---------------------------------------------------------- actions
    def act_setup(self) -> str:
        """The guide, in a WINDOW OF ITS OWN: it is interactive (it waits for
        the phone to press START) and the dashboard's pane is not a place a
        person can type. Nothing about the conf is decided here."""
        if not os.environ.get("TMUX"):
            return "not inside tmux -- run %s --setup by hand" % NOTIFY_SH
        try:
            r = subprocess.run(["tmux", "new-window", "-n", "notify-setup",
                                "%s --setup" % NOTIFY_SH],
                               capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return "could not open the setup window: %s" % exc
        if r.returncode != 0:
            return "could not open the setup window: %s" % r.stderr.strip()
        self._status_at = 0.0          # whatever it writes, ask again after
        return "the setup guide is in the notify-setup window"

    def act_test(self) -> str:
        try:
            r = subprocess.run([str(NOTIFY_SH), "--test"], capture_output=True,
                               text=True, timeout=25)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return "test failed: %s" % exc
        self._status_at = 0.0
        if r.returncode != 0:
            return "test FAILED: %s" % ((r.stderr or r.stdout).strip().split("\n")[-1]
                                        or "see the notify log")
        return "test sent · %s" % self.status(force=True)

    def title(self) -> str:
        return "notifications[/] [%s]· %s" % (DIM, escape(str(NOTIFY_SH.name)))


def _ago(stamp: str) -> str:
    """"2026-09-18 09:12:01" as "2m ago". The stamp is local time, written by
    claude-notify.sh itself; one it cannot parse is shown as it is."""
    try:
        sec = time.time() - time.mktime(time.strptime(stamp[:19], "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return stamp
    if sec < 90:
        return "just now"
    if sec < 3600:
        return "%dm ago" % (sec // 60)
    if sec < 86400:
        return "%dh ago" % (sec // 3600)
    return "%dd ago" % (sec // 86400)


def register(app) -> None:
    # The keys first: a row below reads one back the moment it is drawn, and
    # register() is what makes get/put accept the name at all.
    muxsettings.register(NOTIFY_KEYS, menu="notify")
    menu = NotifyMenu(app)
    app.add_menu("notify", menu.entries, title_fn=menu.title,
                 hint_fn=lambda: "↑↓ pick · enter change · esc back",
                 esc_to="settings")
    # The row that opens it, INTO somebody else's menu, under the last
    # setting and above the separator. Settings' own rows take the positional
    # orders 10, 20, 30 ... so where "last" is depends on how many settings
    # other modules have registered -- a fixed number went stale the day the
    # handovers tab added two. The row names its own order, counted when the
    # menu is drawn. (First row, above Menu layout, was the alternative and
    # put a submenu where the reader looks for the layout switch.)
    app.add_rows("settings", lambda a: [{
        "label": "Notifications ▸  what the phone is told, and what it may answer",
        "sub": "notify",
        "order": len(muxsettings.DASHBOARD_KEYS) * 10 + 5}])
    # `waiting` is published by the watchdog in status.tsv in place of idle.
    # It is not a fact about the last turn like idle is: it is a fact about
    # you, so it is drawn in the colour the screen uses for "look at this".
    app.add_state("waiting", "needs you", YELLOW)
    app.add_help("NOTIFICATIONS", HELP_NOTIFY, order=35)
