"""dashboard.menus.update -- Settings ▸ Updates, and the one line that says so.

docs/updates.md. The watchdog notices a new release on a slow shared clock
and writes what it found; this file is where a hand reads the notes, takes
it, and decides how much of that should happen without being asked.

    Settings ▸ Updates ▸       a menu kind of its own (esc_to="settings")
    esc ▸ Update to X ▸        a row that exists only while one is waiting
    the footer's `muxtopus X is out`
    the header's `running <version> · <new> installed, press R`

NOTHING HERE TOUCHES THE NETWORK ON A FRAME. Every row reads the state file
mux-update.sh writes, cached for a few seconds, because a menu is redrawn
many times a second and a menu that forks is a menu that stutters. The two
rows that DO reach the network -- Check now, and the update itself -- are
actions behind a keypress, and the second is behind a confirm as well.

WHY THE UPDATE ROWS AND THE SETTINGS ROWS ARE IN ONE MENU. Notifications
split them (a Set up row, then seven switches) and this follows it: what is
happening now at the top, what it should do next time at the bottom. Three
switches is not a screen of its own.

WHY THE KEYS ARE GLOBAL. There is one installed tree. muxsettings.scope_of
sends these three to the shared dashboard.conf however many accounts exist,
so "check daily" cannot mean two different things on one machine.
"""
from __future__ import annotations

import os
import subprocess
import time

from rich.markup import escape
from rich.text import Text

import muxconfig
import muxsettings
from dashboard.core import DIM, GREEN, PROFILE, SCRIPTS, YELLOW

UPDATE_SH = SCRIPTS / "mux-update.sh"

# The three, in the order they have in muxconfig.KEYS and profile.sh's
# MUX_CONFIG_KEYS. `scope="global"` is what sends them to the shared file.
UPDATE_KEYS: dict[str, dict] = {
    "MUXTOPUS_UPDATE_MODE": {
        "label": "New releases", "kind": "choice", "scope": "global",
        "choices": ("off", "notify", "download"),
        "hint": "notify: say so, download nothing · download: fetch it too, ready to apply"},
    "MUXTOPUS_UPDATE_EVERY": {
        "label": "Check every", "kind": "choice", "scope": "global",
        "choices": ("6", "24", "168"),
        "hint": "hours; one request that follows the releases/latest redirect"},
    "MUXTOPUS_UPDATE_CHANNEL": {
        "label": "Channel", "kind": "choice", "scope": "global",
        "choices": ("stable", "prerelease"),
        "hint": "prerelease: also take release candidates, for a machine you dogfood on"},
}

EVERY_WORDS = {"6": "6h", "24": "a day", "168": "a week"}

HELP_UPDATE = f"""
  [{DIM}]UPDATES (esc ▸ Settings ▸ Updates)[/]
    The watchdog asks GitHub once a day what the newest release is -- one
    request that follows the `releases/latest` redirect, with no token and
    nothing about this machine in it -- and says so here and in the footer.
    Nothing is downloaded until you ask, and nothing is installed without
    the confirm row. `off` stops the request being made at all.

    Taking one swaps `~/.local/lib/muxtopus` for the new release, keeping
    what it replaced as `muxtopus.prev`, and reloads every watchdog onto it:
    a running claude window is a process in a pane and is not touched, so
    nothing you are working on is interrupted. The dashboard is the one
    thing still on the old code afterwards, and its header says so until
    you press R.

    `Roll back` is the same move in reverse, out of that kept tree. A git
    checkout is never touched by any of this: `git pull` is its update.
"""


class UpdateMenu:
    """Settings ▸ Updates. Not a View: it draws no screen of its own."""

    def __init__(self, app) -> None:
        self.app = app
        self._state: dict[str, str] = {}
        self._at = 0.0

    # ------------------------------------------------------------- state
    def state(self, force: bool = False) -> dict[str, str]:
        """What mux-update.sh last wrote, as a dict, at most once a second.

        READ, NEVER ASKED: this parses the state file directly instead of
        running `--status`, because a menu row is drawn on every frame and
        the file is a dozen short lines. `--status` is for a person at a
        terminal, and it is what the `i` row prints.
        """
        now = time.time()
        if not force and now - self._at < 1.0:
            return self._state
        self._at = now
        got: dict[str, str] = {}
        try:
            with open(muxconfig.update_dir() / "state", encoding="utf-8") as fh:
                for line in fh:
                    k, _, v = line.partition("=")
                    got[k.strip()] = v.strip()
        except OSError:
            pass
        self._state = got
        return got

    def available(self) -> str:
        """The version waiting to be installed, or "". The one question every
        other file in the dashboard asks this module."""
        st = self.state()
        if st.get("STATE") in ("available", "staged") and st.get("LATEST"):
            return st["LATEST"]
        return ""

    def rollback_to(self) -> str:
        """The version `muxtopus.prev` holds, or ""."""
        lib = os.environ.get("MUXTOPUS_DIR") or str(SCRIPTS)
        try:
            with open(lib + ".prev/VERSION", encoding="utf-8") as fh:
                return fh.read().strip()
        except OSError:
            return ""

    def _ago(self) -> str:
        at = self.state().get("CHECKED_AT", "")
        if not at.isdigit():
            return "never checked"
        mins = int((time.time() - int(at)) // 60)
        if mins < 2:
            return "checked just now"
        if mins < 60:
            return "checked %dm ago" % mins
        if mins < 48 * 60:
            return "checked %dh ago" % (mins // 60)
        return "checked %dd ago" % (mins // 1440)

    def status_line(self) -> str:
        st = self.state()
        cur = self.app.version
        if muxsettings.get("MUXTOPUS_UPDATE_MODE", PROFILE) == "off":
            return "%s · checks are off" % cur
        new = self.available()
        if new:
            staged = " (downloaded)" if st.get("STATE") == "staged" else ""
            return "%s · [%s]%s is out%s[/] · %s" % (cur, YELLOW, new, staged, self._ago())
        if st.get("ERROR"):
            return "%s · %s · %s" % (cur, escape(st["ERROR"]), self._ago())
        if st.get("STATE") == "uptodate":
            return "%s · [%s]newest[/] · %s" % (cur, GREEN, self._ago())
        return "%s · %s" % (cur, self._ago())

    # -------------------------------------------------------------- rows
    def entries(self) -> list[dict]:
        new = self.available()
        back = self.rollback_to()
        items: list[dict] = [
            {"label": "Updates: %s" % self.status_line(),
             "desc": "the full report, full screen",
             "act": self.act_status, "stay": True},
            {"label": "Check now",
             "desc": "ask GitHub for the newest release, ignoring the clock",
             "act": self.act_check, "stay": True},
        ]
        if new:
            items += [
                {"label": "What is in %s…" % new,
                 "desc": "its release notes, full screen",
                 "act": lambda v=new: self.act_notes(v)},
                {"label": "Update to %s and reload" % new,
                 "desc": "swaps the install, reloads the watchdogs",
                 "act": lambda v=new: self.act_apply(v)},
            ]
        if back:
            items.append({
                "label": "Roll back to %s" % back,
                "desc": "put the kept tree back in place",
                "act": lambda v=back: self.act_rollback(v), "danger": True})
        items.append({"sep": True})
        for key, meta in muxsettings.keys_of("update").items():
            val = muxsettings.get(key, PROFILE)
            items.append({
                "label": "%s: %s" % (meta["label"], self._shown(key, val)),
                "desc": meta["hint"],
                "stay": True, "act": lambda k=key: self._choose(k)})
        items += [{"sep": True}, {"label": "Back", "sub": "settings"}]
        if not UPDATE_SH.exists():
            for it in items:
                if it.get("act"):
                    it["disabled"] = "%s is not in the checkout" % UPDATE_SH.name
        return items

    def _shown(self, key: str, val: str) -> str:
        if key == "MUXTOPUS_UPDATE_EVERY":
            return EVERY_WORDS.get(val, "%s h" % val if val else "a day")
        return val or "(default)"

    def _choose(self, key: str) -> str:
        meta = muxsettings.spec_of(key)
        choices = list(meta["choices"])
        shown = [self._shown(key, c) for c in choices]
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
        self._at = 0.0
        return "%s = %s  · %s (every account)" % (
            meta["label"], self._shown(key, value),
            muxsettings.dashboard_conf_path(muxsettings.scope_of(key, PROFILE)).name)

    # ----------------------------------------------------------- actions
    def _run(self, args: list[str], timeout: int) -> subprocess.CompletedProcess:
        return subprocess.run([str(UPDATE_SH)] + args, capture_output=True,
                              text=True, timeout=timeout)

    def act_status(self) -> str:
        """The full report, as a person at a terminal would get it."""
        try:
            r = self._run(["--status"], 20)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return "cannot ask %s: %s" % (UPDATE_SH.name, exc)
        self.app.pending_report = (r.stdout + r.stderr) or "(--status printed nothing)"
        return ""

    def act_check(self) -> str:
        """--force, because this row IS the answer to "check now". It reaches
        the network, so it is bounded and its failure is a notice, not a
        traceback: a laptop on a train is the ordinary case."""
        try:
            r = self._run(["--check", "--force"], 40)
        except subprocess.TimeoutExpired:
            return "the release check timed out -- the network, most likely"
        except OSError as exc:
            return "could not run %s: %s" % (UPDATE_SH.name, exc)
        self._at = 0.0
        new = self.available()
        if new:
            return "muxtopus %s is out -- the rows above read it and take it" % new
        if r.returncode != 0:
            return (r.stderr or r.stdout).strip().split("\n")[-1] or "the check failed"
        return "this is the newest release (%s)" % self.app.version

    def act_notes(self, version: str) -> str:
        """The notes full screen, through the shell's pending_report, which
        is what the handovers tab uses for a file."""
        try:
            r = self._run(["--notes", version], 30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return "could not fetch the notes: %s" % exc
        self.app.pending_report = "muxtopus %s\n\n%s" % (
            version, (r.stdout or r.stderr).strip() or "(no notes)")
        return ""

    def act_apply(self, version: str) -> str:
        self.app.confirm = {
            "label": "Install muxtopus %s over %s? Your claude windows keep running."
                     % (version, self.app.version),
            "fn": lambda v=version: self._do_apply(v)}
        return ""

    def _do_apply(self, version: str) -> str:
        """THE ONE ROW THAT REPLACES THE CODE UNDER THE DASHBOARD.

        Foreground and bounded: it is a download, an unpack and an install.sh,
        measured at a few seconds, and a frame that stalls for them is the
        honest picture of what is happening. The output goes to the full
        screen either way, because "what did the installer say" is the
        question after an install that did anything surprising.

        Then the dashboard reloads ITSELF -- R's own path -- so the screen
        you are looking at is the new code before you have to wonder whether
        it is. The watchdogs were reloaded by mux-update.sh already.
        """
        try:
            r = self._run(["--apply", "--yes"], 600)
        except subprocess.TimeoutExpired:
            return "the install is still running after 10 minutes -- see mux-update.sh --status"
        except OSError as exc:
            return "could not run %s: %s" % (UPDATE_SH.name, exc)
        self._at = 0.0
        out = (r.stdout + r.stderr).strip()
        if r.returncode != 0:
            self.app.pending_report = "muxtopus %s was NOT installed\n\n%s" % (version, out)
            return "the update failed -- nothing was changed; the report says why"
        self.app.pending_report = "muxtopus %s installed\n\n%s" % (version, out)
        self.app.pending_reload = True
        return ""

    def act_rollback(self, version: str) -> str:
        self.app.confirm = {
            "label": "Put muxtopus %s back in place of %s?" % (version, self.app.version),
            "fn": lambda v=version: self._do_rollback(v)}
        return ""

    def _do_rollback(self, version: str) -> str:
        try:
            r = self._run(["--rollback", "--yes"], 600)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return "the rollback did not finish: %s" % exc
        self._at = 0.0
        out = (r.stdout + r.stderr).strip()
        if r.returncode != 0:
            self.app.pending_report = "muxtopus %s was NOT put back\n\n%s" % (version, out)
            return "the rollback failed -- the report says why"
        self.app.pending_report = "muxtopus %s is back\n\n%s" % (version, out)
        self.app.pending_reload = True
        return ""

    def title(self) -> str:
        return "updates[/] [%s]· %s" % (DIM, escape(str(UPDATE_SH.name)))

    def desc(self) -> str:
        return "new releases: whether to look, what to take, and what to keep"


# ---------------------------------------------------------------------------
# THE OTHER WAY THE NUMBER IN THE HEADER CAN BE LESS THAN THE WHOLE TRUTH.
#
# Everything above answers "is there a NEWER release than mine?". This answers
# the question that only has an answer on a machine that DEVELOPS muxtopus:
# "is what I am running the release this number names, or is it that release
# plus whatever has landed on main since?" On this box `~/.local/bin/muxtopus`
# is a symlink into the checkout, so the dashboard runs main -- and between a
# merge and a tag, VERSION still names the LAST release while the code is
# something else. A header that says that number either way is not wrong so
# much as incomplete, and it is incomplete at exactly the moment someone is
# deciding whether to cut a release.
#
# IT IS SILENT ON AN INSTALLED RELEASE, which is the common case and the one
# this must not clutter: a tarball install has no .git, so `checkout_state`
# returns nothing and no note is added. It is also silent when HEAD IS the
# tag, which is every checkout on the day of a release.
#
# WHAT IT COUNTS. `changes/*.md` is one fragment per merged pull request, and
# `changes/README.md` is the folder's own documentation rather than a
# fragment -- the release consumes the first and leaves the second, so the
# count of the rest is "how many merged changes are waiting for a number".
# It is the same list the CHANGELOG entry is assembled from, so the header
# and the release ritual cannot disagree about how much is pending.
#
# NO FORK PER FRAME. Two `git` calls, cached for a minute: a commit does not
# arrive sixty times a second, and the header is redrawn that often.
_CO: dict[str, object] = {"at": 0.0, "note": ""}
_CO_EVERY = 60.0


def checkout_state(now: float | None = None) -> str:
    """`unreleased · <sha>[ · N changes]` for a checkout ahead of its tag; "".

    Empty whenever the question does not arise: no `.git` beside the code (an
    installed release), no readable VERSION, no tag by that name yet, or HEAD
    already sitting on it. Any git failure is empty too -- this is a note in a
    header, and a header that raises is worse than a header that is quiet.
    """
    now = time.time() if now is None else now
    if now - float(_CO["at"]) < _CO_EVERY:
        return str(_CO["note"])
    _CO["at"] = now
    _CO["note"] = ""
    try:
        if not (SCRIPTS / ".git").exists():
            return ""
        version = (SCRIPTS / "VERSION").read_text(encoding="utf-8").strip()
        if not version:
            return ""

        def git(*args: str) -> str:
            out = subprocess.run(("git", "-C", str(SCRIPTS)) + args,
                                 capture_output=True, text=True, timeout=5)
            return out.stdout.strip() if out.returncode == 0 else ""

        head = git("rev-parse", "HEAD")
        # ^{commit} so an ANNOTATED tag resolves to what it points at rather
        # than to the tag object, which never equals a HEAD sha.
        tag = git("rev-list", "-n", "1", "v%s^{commit}" % version)
        if not head or not tag or head == tag:
            return ""
        note = "unreleased · %s" % head[:7]
        try:
            pending = sum(1 for f in (SCRIPTS / "changes").glob("*.md")
                          if f.name != "README.md")
        except OSError:
            pending = 0
        if pending:
            note += " · %d change%s" % (pending, "" if pending == 1 else "s")
        _CO["note"] = note
    except (OSError, ValueError, subprocess.SubprocessError):
        _CO["note"] = ""
    return str(_CO["note"])


def register(app) -> None:
    muxsettings.register(UPDATE_KEYS, menu="update")
    menu = UpdateMenu(app)
    app.add_menu("update", menu.entries, title_fn=menu.title,
                 hint_fn=lambda: "↑↓ pick · enter change · esc back",
                 desc_fn=menu.desc, esc_to="settings")
    # The row in Settings, under the last setting, the way Notifications does
    # it: an order counted when the menu is drawn, never a fixed number that
    # goes stale the day somebody registers a tenth key.
    app.add_rows("settings", lambda a: [{
        "label": "Updates ▸",
        "sub": "update",
        "order": len(muxsettings.DASHBOARD_KEYS) * 10 + 6}])
    # AND A ROW IN THE esc MENU, but only while there is something to say --
    # exactly like Restore. An update is the rare thing esc should offer
    # without being looked for, and on every other day this row is not there.
    app.add_rows("mux", lambda a, m=menu: (
        [{"label": "Update to %s ▸" % m.available(),
          "sub": "update", "order": 15}] if m.available() else []))
    app.add_hint(lambda a, m=menu: Text("  · %s out" % m.available(), style=YELLOW)
                 if m.available() else None)
    # AND BESIDE THE VERSION IN THE HEADER. The footer hint above says the
    # same thing, but it sits at the far end of the screen from the number it
    # is about: "v<this one>" and "<that one> is out" were two facts in two
    # places, and the question ("am I behind?") is one that occurs while
    # reading the version. Yellow, in brackets, and gone on the ordinary day
    # -- this is the one registry note that must not become permanent
    # furniture. `staged` says the bytes are already down, which is the
    # difference between "press enter twice" and "wait for a download".
    app.add_version_note(lambda a, m=menu: (
        "[%s](v%s %s)[/]" % (YELLOW, escape(m.available()),
                             "downloaded" if m.state().get("STATE") == "staged"
                             else "available")) if m.available() else None)
    # AND THE DEVELOPER'S HALF OF THE SAME QUESTION, in the same place and
    # the same brackets, but DIM rather than yellow: "there is a newer
    # release" is something to act on, "you are ahead of your tag" is
    # something to know. On an installed release this returns nothing and
    # the header is exactly as it was.
    app.add_version_note(lambda a: ("[%s](%s)[/]" % (DIM, escape(checkout_state()))
                                    if checkout_state() else None))
    app.add_help("UPDATES", HELP_UPDATE, order=37)
