"""dashboard.views.newsession -- c: a new claude session, in seven screens.

The working folder, the model, the effort, the permission mode, where it
goes, the name (which is the slug) and an optional first prompt -- through the
App's existing picker and prompt, and then ONE file: a schedule entry with
`at:` already past. The dashboard opens no window itself. The watchdog's next
pass does the trust dialog, the readiness wait, the bracketed paste, the tree
row, the footer and the log line -- one launcher, whoever asked, and none of
it reimplemented here.

NOT A VIEW: it draws no screen, it drives the submodes. It registers itself
on the app as `app.newsession`, and the main view's `c` asks for it by that
name -- and says so if this module failed to load, rather than taking the
dashboard down with it.

WHAT IT READS THAT IS NOT ITS OWN (docs/dashboard-views.md):

    app.view_of("main").cursor_cwd()        the folder offered first
    app.view_of("main").listed_sessions()   the windows it can go under
    app.view_of("main").known_windows()     the names a slug may not take
"""
from __future__ import annotations

import os
import time

import muxsettings
from dashboard.core import (CONFIG_DIR, DIM, PROFILE, SCHEDULES_DIR,
                            model_choices, mux_home)
from dashboard.data import dirty_repos, lane_slug_of
from dashboard.schedules import read_schedules, sanitise_slug


class NewSession:
    """The c flow. Its answers so far live in app.ns, because esc in any of
    the three submodes abandons the flow and App is what owns that cancel."""

    def __init__(self, app) -> None:
        self.app = app

    # ------------------------------------------- c: a new claude session
    # Seven screens through the existing picker and prompt, then ONE file: a
    # schedule entry with at: already past. The dashboard opens no window
    # itself. The watchdog's next pass does the trust dialog, the readiness
    # wait, the bracketed paste, the tree row, the footer and the log line --
    # one launcher, whoever asked, and none of it reimplemented here.
    def start_new_session(self) -> str:
        self.app.ns = {}
        cands = self._ns_folder_candidates()
        self.app.picker = {"title": "new session · working folder", "i": 0,
                       "options": cands + ["other…  type a path"], "fn": self._ns_folder}
        return ""

    def _ns_folder_candidates(self) -> list[str]:
        """Where a session might sensibly start, most likely first: the cursor
        session's folder, the setting, every live session's folder, the dirty
        trees the watchdog publishes, and the git checkouts one and two levels
        under MUXTOPUS_HOME -- the same two levels sweep_repos walks."""
        out: list[str] = []

        def add(p: str) -> None:
            if p and p != "-" and p not in out and os.path.isdir(p):
                out.append(p)

        main = self.app.view_of("main")
        add(main.cursor_cwd())
        add(muxsettings.get("DASHBOARD_NEW_CWD", PROFILE))
        for _sid, _win, _pane, cwd in main.listed_sessions():
            add(cwd)
        for path, _name, _n in dirty_repos():
            add(path)
        home = mux_home(PROFILE)
        try:
            for d in sorted(os.scandir(home), key=lambda e: e.name):
                if not d.is_dir(follow_symlinks=False) or d.name.startswith("."):
                    continue
                if os.path.exists(os.path.join(d.path, ".git")):
                    add(d.path)
                    continue
                try:
                    for dd in sorted(os.scandir(d.path), key=lambda e: e.name):
                        if dd.is_dir(follow_symlinks=False) and \
                                os.path.exists(os.path.join(dd.path, ".git")):
                            add(dd.path)
                except OSError:
                    pass
        except OSError:
            pass
        return out

    def _ns_folder(self, choice: str) -> str:
        if choice.startswith("other…"):
            self.app.prompt = {"title": "new session · working folder", "buf": "",
                           "fn": self._ns_folder_typed}
            return ""
        return self._ns_folder_typed(choice)

    def _ns_folder_typed(self, text: str) -> str:
        p = os.path.expanduser(text.strip())
        if not p or not os.path.isdir(p):
            # Said in the prompt's own title: the notice is not drawn while a
            # prompt owns the footer.
            self.app.prompt = {"title": "not a directory: %s — working folder" % (text.strip() or "(empty)"),
                           "buf": text.strip(), "fn": self._ns_folder_typed}
            return ""
        self.app.ns["cwd"] = os.path.abspath(p)
        return self._ns_ask_model()

    def _ns_ask_model(self) -> str:
        choices = [""] + model_choices()
        cur = muxsettings.get("DASHBOARD_NEW_MODEL", PROFILE)
        self.app.picker = {"title": "new session · model  (CLI aliases — the MODEL column's names are refused)",
                       "i": choices.index(cur) if cur in choices else 0,
                       "options": [c or "(account default)" for c in choices],
                       "fn": self._ns_model}
        return ""

    def _ns_model(self, c: str) -> str:
        self.app.ns["model"] = "" if c == "(account default)" else c
        choices = [""] + list(muxsettings.EFFORTS)
        cur = muxsettings.get("DASHBOARD_NEW_EFFORT", PROFILE)
        self.app.picker = {"title": "new session · effort",
                       "i": choices.index(cur) if cur in choices else 0,
                       "options": [c or "(account default)" for c in choices],
                       "fn": self._ns_effort}
        return ""

    def _ns_effort(self, c: str) -> str:
        self.app.ns["effort"] = "" if c == "(account default)" else c
        modes = list(muxsettings.PERM_MODES)
        cur = muxsettings.get("DASHBOARD_NEW_PERMISSION_MODE", PROFILE)
        pk = {"title": "new session · permission mode", "options": modes, "fn": self._ns_mode,
              "i": modes.index(cur) if cur in modes else -1}
        if pk["i"] < 0:
            # "always ask": nothing preselected. A DEFAULT is set in Settings;
            # it is never a lock, this screen is always shown.
            pk["title"] += "  (no default set — esc → Settings sets one)"
        self.app.picker = pk
        return ""

    def _ns_mode(self, c: str) -> str:
        self.app.ns["mode"] = c
        if c == "bypassPermissions":
            self.app.picker = {"title": "bypassPermissions", "i": 0,
                           "options": ["this window only",
                                       "…and make it the default  (writes settings.json)"],
                           "fn": self._ns_bypass}
            return ""
        return self._ns_ask_where()

    def _ns_bypass(self, c: str) -> str:
        if c.startswith("this window"):
            return self._ns_ask_where()
        scope = muxsettings.get("DASHBOARD_PERMANENT_MODE_SCOPE", PROFILE) or "project"
        path = muxsettings.settings_json_path(scope, self.app.ns["cwd"], CONFIG_DIR)
        self.app.confirm = {
            "label": ('⚠ writes  "permissions": {"defaultMode": "bypassPermissions"}  to %s\n'
                      '  EVERY future Claude session there skips permission prompts,\n'
                      '  including ones nothing is watching.  (%s — Settings changes where)'
                      % (path, scope)),
            "fn": lambda p=path: self._ns_bypass_write(p),
            "no_fn": self._ns_ask_where}
        return ""

    def _ns_bypass_write(self, path) -> str:
        # THE ONE WRITE lives in muxsettings; this is an entrance to it.
        msg, err = muxsettings.set_default_mode(path, "bypassPermissions")
        self.app.ns["default_msg"] = err or msg
        self.app.ns["default_err"] = bool(err)
        return self._ns_ask_where()

    def _ns_ask_where(self) -> str:
        opts = ["a top-level window"]
        for _sid, win, pane, _cwd in self.app.view_of("main").listed_sessions():
            if win and pane:
                opts.append("under %s" % win)
        title = "new session · where"
        if self.app.ns.get("default_msg"):
            # The outcome of the settings.json write, where it can be seen:
            # no notice is drawn while a picker owns the footer.
            title += "  · settings.json %s: %s" % (
                "NOT written" if self.app.ns.get("default_err") else "written",
                self.app.ns["default_msg"])
        self.app.picker = {"title": title, "i": 0, "options": opts, "fn": self._ns_where}
        return ""

    def _ns_where(self, c: str) -> str:
        if c.startswith("under "):
            win = c[len("under "):]
            # window: is the tmux name (the launcher strips ➥ to find it);
            # parent: is the slug, which is what the tree is keyed on.
            self.app.ns["window"] = win
            self.app.ns["parent"] = lane_slug_of(win)
        base = sanitise_slug(os.path.basename(self.app.ns["cwd"].rstrip("/")))
        self.app.prompt = {"title": "new session · name  (the slug: window ➥name, STATUS-name.md, handover.sh done name)",
                       "buf": base, "fn": self._ns_name}
        return ""

    def _ns_name(self, text: str) -> str:
        slug = sanitise_slug(text.strip())
        why = ""
        if not slug:
            why = "empty"
        else:
            taken = {r["resolved"] for r in read_schedules()
                     if r["status"] in ("pending", "launched")}
            live = {lane_slug_of(w)
                    for w in self.app.view_of("main").known_windows()}
            if slug in taken or slug in live:
                why = "%s is taken (a window or an entry has it)" % slug
        if why:
            self.app.prompt = {"title": "%s — new session · name" % why, "buf": text.strip(),
                           "fn": self._ns_name}
            return ""
        self.app.ns["title"] = text.strip()
        self.app.ns["slug"] = slug
        self.app.prompt = {"title": "new session · first prompt  (may be empty)", "buf": "",
                       "fn": self._ns_prompt}
        return ""

    def _ns_prompt(self, text: str) -> str:
        self.app.ns["prompt"] = text.strip()
        return self._ns_write()

    def _ns_write(self) -> str:
        """The one file. `at:` is now to the minute, so it is already past
        and the watchdog's next pass launches it; `slug:` is pinned so the
        window is named what was typed. An empty prompt makes it a `plan`
        entry with no template -- the executor refuses an empty work body,
        and a plan may be empty: the session receives its identity line and
        nothing invented (QUESTIONS 2a)."""
        ns, self.app.ns = self.app.ns, None
        slug = ns["slug"]
        now = time.strftime("%Y-%m-%d %H:%M")
        head = ["type: " + ("work" if ns["prompt"] else "plan"),
                "at: " + now, "title: " + ns["title"], "slug: " + slug]
        if ns.get("window"):
            head += ["window: " + ns["window"], "parent: " + ns["parent"]]
        head.append("cwd: " + ns["cwd"])
        for k in ("model", "effort"):
            if ns.get(k):
                head.append("%s: %s" % (k, ns[k]))
        head.append("permission-mode: " + ns["mode"])
        # The two headers the LAUNCHER applies after readiness, because a
        # session id does not exist before launch (it maps its pane to
        # sessions/<pid>.json). Absent means covered, today's default.
        if muxsettings.get("DASHBOARD_NEW_WATCHDOG", PROFILE) == "off":
            head.append("watchdog: off")
        if muxsettings.get("DASHBOARD_NEW_MONITOR", PROFILE) == "off":
            head.append("monitor: off")
        head += ["status: pending", "created: " + now, "launched:"]
        try:
            SCHEDULES_DIR.mkdir(parents=True, exist_ok=True)
            f = SCHEDULES_DIR / ("new-%s.md" % slug)
            if f.exists():
                f = SCHEDULES_DIR / ("new-%s-%s.md" % (slug, time.strftime("%H%M%S")))
            f.write_text("\n".join(head) + "\n---\n"
                         + (ns["prompt"] + "\n" if ns["prompt"] else ""))
        except OSError as exc:
            return "could not write the entry: %s" % exc
        msg = "scheduled ➥%s — the watchdog opens it within ~30s (%s)" % (slug, f.name)
        if ns.get("default_msg"):
            msg += " · settings.json %s" % ns["default_msg"]
        return msg



# ------------------------------------------------------------------ help
# This module's slice of `?`. Registered with the ORDER it has always had,
# so the help screen reads exactly as it did when it was one string in
# deck_status.py -- the split moved who owns the words, not the words.
HELP_NEWSESSION = f"""
  [{DIM}]A NEW CLAUDE SESSION (c)[/]
    Seven screens through the picker and the prompt: the working folder (the
    cursor's, the setting, every session's, the dirty trees, the checkouts
    under MUXTOPUS_HOME, or a typed path -- it must exist); the model, as a CLI
    ALIAS (opus, fable, sonnet…; `--model opus-5` is refused by the CLI and
    kills the window after it has eaten the paste); the effort; the permission
    mode (preselected from Settings, or nothing preselected when that says
    ask -- a default, never a lock); where it goes (a top-level window, or
    under a live one: ➥➥name, inserted after that parent's subtree, drawn
    indented); the name, which is the slug (window, handover, handover.sh
    done); and an optional first prompt.
    THEN IT WRITES A SCHEDULE ENTRY with at: already past, and nothing else:
    the watchdog opens the window within one pass and does the trust dialog,
    the readiness wait, the paste and the tree row -- one launcher, whoever
    asked. The entry carries model:, effort:, permission-mode:, cwd:,
    parent:/window:, and watchdog: off / monitor: off when Settings says a
    new window is not watched or monitored (the launcher opts the session out
    once it has an id). An empty prompt writes a plan entry: the session gets
    its identity line and nothing invented. `/rc` is not written into the
    entry: the launcher sends it to every new window when Settings ▸ Send
    /rc to a new window is on (an entry's own rc: on|off wins).
    Choosing bypassPermissions also offers "…and make it the default": a
    confirm names the exact settings.json (project or account, per Settings)
    and what changes -- EVERY future session there skips permission prompts,
    including ones nothing is watching. The write merges permissions.defaultMode
    into the existing JSON (nested, where Claude Code reads it), backs the
    old file up beside itself, and refuses a file that is not valid JSON.
"""

def register(app) -> None:
    app.newsession = NewSession(app)
    app.add_help("A NEW CLAUDE SESSION (c)", HELP_NEWSESSION, order=20)
