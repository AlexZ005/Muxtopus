"""dashboard.views.newsession -- c: a new claude session, on ONE screen.

A FORM, NOT A WIZARD. `c` opens a menu with every parameter on it, each row
already carrying the default it would use, and `Create` on the first row --
so the whole of "give me a window" is `c` then enter, and changing something
is arrowing to that row and pressing enter on it. It was seven pickers in a
fixed order, which meant answering six questions you did not have an opinion
about to reach the one you did, and no way to go back and change your mind
about the second one without abandoning the flow.

Every row still uses the App's own picker and prompt -- the folder row opens
the same candidate list it always did -- and they now come back to the form
instead of ending it, because a submode can say what esc means for it
(App._submode_cancel, `on_cancel`).

Then ONE file: a schedule entry with `at:` already past. The dashboard opens
no window itself. The watchdog's next pass does the trust dialog, the
readiness wait, the bracketed paste, the tree row, the footer and the log
line -- one launcher, whoever asked, and none of it reimplemented here. What
this adds is the FOLLOW: it remembers the slug it just asked for and moves
the tmux client to that window the moment the launcher opens it, so `c enter`
lands you in the session rather than back on a dashboard row.

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
import subprocess
import time

from rich.markup import escape
from rich.text import Text

import muxsettings
from dashboard.core import (CONFIG_DIR, DIM, GREEN, PROFILE, SCHEDULES_DIR,
                            YELLOW, model_choices, mux_home)
from dashboard.data import (dirty_repos, lane_slug_of, live_windows,
                            read_tree)
from dashboard.schedules import read_schedules, sanitise_slug

# How long the form keeps watching for the window it asked for. The launcher
# opens one within a watchdog pass and then waits on claude's readiness, so
# this is that plus room for a slow start; after it, the jump is dropped and
# the window is simply there to be opened with enter like any other.
FOLLOW_FOR = 180.0


class NewSession:
    """The c flow. Its answers so far live in app.ns, because esc in any of
    the three submodes abandons the flow and App is what owns that cancel."""

    def __init__(self, app) -> None:
        self.app = app
        # The window this form asked for and has not landed in yet:
        # {"slug", "until"}. See follow_hint.
        self.follow: dict | None = None

    # ------------------------------------------------ c: the form
    # ONE MENU, every parameter on it, Create first. app.ns holds the answers
    # while it is open -- the same dict the seven pickers filled, so _ns_write
    # below did not have to change shape -- and the menu is redrawn from it on
    # every frame, which is what makes a row show the value you just set.
    def start_new_session(self) -> str:
        cwd = self._default_cwd()
        name = self._free_slug(self._name_for(cwd))
        mode = muxsettings.get("DASHBOARD_NEW_PERMISSION_MODE", PROFILE)
        self.app.ns = {
            "cwd": cwd,
            "model": muxsettings.get("DASHBOARD_NEW_MODEL", PROFILE),
            "effort": muxsettings.get("DASHBOARD_NEW_EFFORT", PROFILE),
            # `ask` is the Settings value meaning "do not preselect a mode".
            # On a form there is nothing to preselect INTO, so it means what
            # it has always meant one layer down: no --permission-mode flag,
            # the account's own defaultMode.
            "mode": mode if mode in muxsettings.PERM_MODES else "",
            "window": "", "parent": "", "prompt": "",
            "title": name, "slug": name,
        }
        self.app.open_menu("newsession")
        return ""

    @staticmethod
    def _name_for(cwd: str) -> str:
        """The name a folder suggests. The LEADING DOT GOES: sanitise_slug is
        the executor's rule character for character and keeps it (a slug may
        legitimately contain one), but a folder called ~/.code would then
        offer `.code`, whose handover is the hidden file STATUS-.code.md and
        whose window is ➥.code. Typing that is still allowed; offering it is
        not something anybody meant to ask for."""
        base = os.path.basename(cwd.rstrip("/")).lstrip(".")
        if not base:
            base = os.path.basename(os.path.dirname(cwd.rstrip("/"))).lstrip(".")
        return sanitise_slug(base) or "session"

    def _default_cwd(self) -> str:
        """Where a session starts when nobody says otherwise: the setting, the
        folder of the row the cursor is on, then home. The same first two the
        candidate list offers, in the same order -- a default that is not the
        top of the list you would have been shown is a default nobody expects."""
        for p in (muxsettings.get("DASHBOARD_NEW_CWD", PROFILE),
                  self.app.view_of("main").cursor_cwd()):
            p = os.path.expanduser(p or "")
            if p and p != "-" and os.path.isdir(p):
                return os.path.abspath(p)
        return str(mux_home())

    def _taken_slugs(self) -> set:
        """Every slug that is already a window or a pending entry. `c enter`
        has to work on the second press as well as the first, so the default
        name is checked against this before it is offered, not only after it
        is typed."""
        taken = {r["resolved"] for r in read_schedules()
                 if r["status"] in ("pending", "launched")}
        return taken | {lane_slug_of(w)
                        for w in self.app.view_of("main").known_windows()}

    def _free_slug(self, base: str) -> str:
        taken = self._taken_slugs()
        if base not in taken:
            return base
        for n in range(2, 100):
            if "%s-%d" % (base, n) not in taken:
                return "%s-%d" % (base, n)
        return base

    # ------------------------------------------------------------- the rows
    def entries(self) -> list[dict]:
        ns = self.app.ns
        if not ns:                       # esc closed it; the menu goes too
            return []
        where = ("under %s" % ns["window"]) if ns.get("window") else "a top-level window"
        prompt = ns.get("prompt") or ""
        items = [
            {"label": "Create ➥%s  and go to its window" % ns["slug"],
             "act": self._create},
            {"sep": True},
            {"label": "Name: %s  the window, the handover, `handover.sh done`" % ns["slug"],
             "act": self._edit_name, "stay": True},
            {"label": "Folder: %s  where claude starts" % self._short(ns["cwd"]),
             "act": self._edit_cwd, "stay": True},
            {"label": "Model: %s  a CLI alias; the MODEL column's names are refused"
                      % (ns["model"] or "(account default)"),
             "act": self._edit_model, "stay": True},
            {"label": "Effort: %s" % (ns["effort"] or "(account default)"),
             "act": self._edit_effort, "stay": True},
            {"label": "Permission mode: %s  cannot be changed after launch"
                      % (ns["mode"] or "(account default)"),
             "act": self._edit_mode, "stay": True},
            {"label": "Where: %s" % where, "act": self._edit_where, "stay": True},
            {"label": "First prompt: %s  empty makes it a plan entry"
                      % (self._short_prompt(prompt)),
             "act": self._edit_prompt, "stay": True},
            {"sep": True},
            {"label": "Cancel", "act": self._cancel},
        ]
        if ns.get("default_msg"):
            items.insert(1, {"label": "settings.json %s: %s"
                                      % ("NOT written" if ns.get("default_err") else "written",
                                         ns["default_msg"]),
                             "disabled": "already done"})
        return items

    @staticmethod
    def _short(path: str) -> str:
        home = os.path.expanduser("~")
        return "~" + path[len(home):] if path.startswith(home + "/") else path

    @staticmethod
    def _short_prompt(text: str) -> str:
        if not text:
            return "(none)"
        one = " ".join(text.split())
        return '"%s…"' % one[:44] if len(one) > 44 else '"%s"' % one

    def title(self) -> str:
        return "new session[/] [%s]· %s" % (DIM, escape(self._short(self.app.ns["cwd"]))
                                            if self.app.ns else "")

    # ------------------------------------------------------- the row editors
    # Every one of them opens a submode and says, through on_cancel, that esc
    # means "leave this row alone" rather than "abandon the form". The menu is
    # still open underneath -- App.menu_activate leaves it open whenever the
    # row's action put a submode up -- so there is nothing to reopen.
    def _stay(self) -> str:
        return ""

    def _edit_name(self) -> str:
        self.app.prompt = {"title": "name  (the slug: window ➥name, STATUS-name.md)",
                           "buf": self.app.ns["title"], "fn": self._set_name,
                           "keep_menu": True, "on_cancel": self._stay}
        return ""

    def _set_name(self, text: str) -> str:
        slug = sanitise_slug(text.strip())
        why = ""
        if not slug:
            why = "empty"
        elif slug != self.app.ns["slug"] and slug in self._taken_slugs():
            why = "%s is taken (a window or an entry has it)" % slug
        if why:
            self.app.prompt = {"title": "%s — name" % why, "buf": text.strip(),
                               "fn": self._set_name, "keep_menu": True,
                               "on_cancel": self._stay}
            return ""
        self.app.ns["title"] = text.strip()
        self.app.ns["slug"] = slug
        return ""

    def _edit_cwd(self) -> str:
        cands = self._ns_folder_candidates()
        cur = self.app.ns["cwd"]
        self.app.picker = {"title": "working folder", "options": cands + ["other…  type a path"],
                           "i": cands.index(cur) if cur in cands else 0,
                           "fn": self._ns_folder, "on_cancel": self._stay}
        return ""

    def _edit_model(self) -> str:
        choices = [""] + model_choices()
        cur = self.app.ns["model"]
        self.app.picker = {"title": "model  (CLI aliases — opus, fable, sonnet…)",
                           "i": choices.index(cur) if cur in choices else 0,
                           "options": [c or "(account default)" for c in choices],
                           "fn": self._set_model, "on_cancel": self._stay}
        return ""

    def _set_model(self, c: str) -> str:
        self.app.ns["model"] = "" if c.startswith("(account") else c
        return ""

    def _edit_effort(self) -> str:
        choices = [""] + list(muxsettings.EFFORTS)
        cur = self.app.ns["effort"]
        self.app.picker = {"title": "effort",
                           "i": choices.index(cur) if cur in choices else 0,
                           "options": [c or "(account default)" for c in choices],
                           "fn": self._set_effort, "on_cancel": self._stay}
        return ""

    def _set_effort(self, c: str) -> str:
        self.app.ns["effort"] = "" if c.startswith("(account") else c
        return ""

    def _edit_mode(self) -> str:
        choices = [""] + list(muxsettings.PERM_MODES)
        cur = self.app.ns["mode"]
        self.app.picker = {"title": "permission mode  (pinned for the life of the window)",
                           "i": choices.index(cur) if cur in choices else 0,
                           "options": [c or "(account default)" for c in choices],
                           "fn": self._set_mode, "on_cancel": self._stay}
        return ""

    def _set_mode(self, c: str) -> str:
        self.app.ns["mode"] = "" if c.startswith("(account") else c
        if self.app.ns["mode"] == "bypassPermissions":
            # The one offer that writes a file, kept exactly as it was: it is
            # about every FUTURE session in that folder, not about this one,
            # so it is worth the extra screen even on a form.
            self.app.picker = {"title": "bypassPermissions", "i": 0,
                               "options": ["this window only",
                                           "…and make it the default  (writes settings.json)"],
                               "fn": self._ns_bypass, "on_cancel": self._stay}
        return ""

    def _edit_where(self) -> str:
        opts = ["a top-level window"]
        for _sid, win, pane, _cwd in self.app.view_of("main").listed_sessions():
            if win and pane:
                opts.append("under %s" % win)
        cur = ("under %s" % self.app.ns["window"]) if self.app.ns.get("window") else opts[0]
        self.app.picker = {"title": "where it goes",
                           "i": opts.index(cur) if cur in opts else 0,
                           "options": opts, "fn": self._ns_where,
                           "on_cancel": self._stay}
        return ""

    def _edit_prompt(self) -> str:
        self.app.prompt = {"title": "first prompt  (may be empty)",
                           "buf": self.app.ns.get("prompt", ""), "fn": self._set_prompt,
                           "keep_menu": True, "on_cancel": self._stay}
        return ""

    def _set_prompt(self, text: str) -> str:
        self.app.ns["prompt"] = text.strip()
        return ""

    def _cancel(self) -> str:
        self.app.ns = None
        return "cancelled"

    def _create(self) -> str:
        """Write the entry, then watch for the window it will become."""
        slug = self.app.ns["slug"]
        msg = self._ns_write()
        if not msg.startswith("could not"):
            self.follow = {"slug": slug, "until": time.time() + FOLLOW_FOR}
        return msg

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
            self.app.prompt = {"title": "working folder", "buf": "",
                               "fn": self._ns_folder_typed, "keep_menu": True,
                               "on_cancel": self._stay}
            return ""
        return self._ns_folder_typed(choice)

    def _ns_folder_typed(self, text: str) -> str:
        p = os.path.expanduser(text.strip())
        if not p or not os.path.isdir(p):
            # Said in the prompt's own title: the notice is not drawn while a
            # prompt owns the footer.
            self.app.prompt = {"title": "not a directory: %s — working folder"
                                        % (text.strip() or "(empty)"),
                               "buf": text.strip(), "fn": self._ns_folder_typed,
                               "keep_menu": True, "on_cancel": self._stay}
            return ""
        self.app.ns["cwd"] = os.path.abspath(p)
        return ""

    def _ns_bypass(self, c: str) -> str:
        if c.startswith("this window"):
            return ""
        scope = muxsettings.get("DASHBOARD_PERMANENT_MODE_SCOPE", PROFILE) or "project"
        path = muxsettings.settings_json_path(scope, self.app.ns["cwd"], CONFIG_DIR)
        self.app.confirm = {
            "label": ('⚠ writes  "permissions": {"defaultMode": "bypassPermissions"}  to %s\n'
                      '  EVERY future Claude session there skips permission prompts,\n'
                      '  including ones nothing is watching.  (%s — Settings changes where)'
                      % (path, scope)),
            "fn": lambda p=path: self._ns_bypass_write(p),
            # A confirm's "yes" closes the menu (App.confirm_key), and this
            # one sits INSIDE the form -- so both answers put it back.
            "no_fn": self._reopen, "on_cancel": self._reopen}
        return ""

    def _ns_bypass_write(self, path) -> str:
        # THE ONE WRITE lives in muxsettings; this is an entrance to it.
        msg, err = muxsettings.set_default_mode(path, "bypassPermissions")
        self.app.ns["default_msg"] = err or msg
        self.app.ns["default_err"] = bool(err)
        return self._reopen()

    def _ns_where(self, c: str) -> str:
        if c.startswith("under "):
            win = c[len("under "):]
            # window: is the tmux name (the launcher strips ➥ to find it);
            # parent: is the slug, which is what the tree is keyed on.
            self.app.ns["window"] = win
            self.app.ns["parent"] = lane_slug_of(win)
        else:
            self.app.ns["window"] = ""
            self.app.ns["parent"] = ""
        return ""

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
        # ABSENT MEANS THE ACCOUNT'S OWN defaultMode -- the launcher passes no
        # --permission-mode flag for an empty one -- which is what the form's
        # "(account default)" row says it will do.
        if ns.get("mode"):
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


    # --------------------------------------------------------- the follow
    # "and go to its window" cannot happen when Create is pressed: there is no
    # window yet. The dashboard writes an entry and the WATCHDOG opens the
    # window a pass later, so the jump has to wait for something that has not
    # been created yet by anything on this side of the line.
    #
    # WHY IT IS A HINT. A hint runs on every main-view frame and may draw one
    # mark on the key line, which is exactly the shape this needs: something
    # that looks each frame, says "opening ➥name" while it is looking, and
    # stops when it has looked long enough. The jump is a side effect of a
    # hint, which is unusual enough to say out loud -- but the alternative is
    # a per-frame seam invented for one caller, and the mark on the key line
    # is the honest description of what the side effect is about to do.
    #
    # IT COSTS NOTHING WHEN NOTHING IS PENDING: the first line returns.
    def follow_hint(self, _app) -> Text | None:
        f = self.follow
        if not f:
            return None
        if time.time() > f["until"]:
            # Gave up. Not an error and not a notice: the window is either
            # there to be opened with enter like any other, or the entry
            # failed and the schedules tab is where that is explained.
            self.follow = None
            return None
        node = read_tree().get(f["slug"])
        wid = node["wid"] if node else ""
        if wid and wid in live_windows():
            self.follow = None
            self.goto_window(wid)
            return None
        return Text("  · opening ➥%s" % f["slug"], style=YELLOW)

    def goto_window(self, target: str) -> str:
        """Move the tmux client to a window id; the dashboard keeps running in
        window 0, so Ctrl-b 0 comes straight back. The same two calls the
        schedules tab's own `Open its window` row makes."""
        try:
            r = subprocess.run(["tmux", "select-window", "-t", target],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return ""
            r = subprocess.run(["tmux", "switch-client", "-t", target],
                               capture_output=True, text=True, timeout=5)
            return "" if r.returncode == 0 else "could not open: %s" % r.stderr.strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            return "could not open: %s" % exc

    def _reopen(self) -> str:
        """Put the form back up -- for the one submode that closes it."""
        if self.app.ns:
            self.app.open_menu("newsession")
        return ""


# ------------------------------------------------------------------ help
# This module's slice of `?`. Registered with the ORDER it has always had,
# so the help screen reads exactly as it did when it was one string in
# deck_status.py -- the split moved who owns the words, not the words.
HELP_NEWSESSION = f"""
  [{DIM}]A NEW CLAUDE SESSION (c)[/]
    ONE SCREEN, not a questionnaire. `c` opens a form with every parameter
    already filled in from Settings ▸ the new-window defaults, and `Create` on
    the first row -- so a window you have no particular opinion about is
    [bold]c enter[/], and one you do is arrowing to that row and pressing enter
    on it. The form stays open while you do: set the effort, change your mind
    about the folder, set it back. esc on a row leaves that row alone; esc on
    the form abandons the whole thing.

    Name          the slug: the window ➥name, STATUS-name.md, `handover.sh
                  done name`. Offered from the folder, and made unique before
                  it is offered, so c enter works a second time
    Folder        enter opens the candidates -- the cursor's folder, the
                  setting, every live session's, the dirty trees the watchdog
                  publishes, the checkouts under MUXTOPUS_HOME -- or a typed
                  path, which must exist
    Model         a CLI ALIAS (opus, fable, sonnet…). `--model opus-5` is
                  refused by the CLI and kills the window after it has eaten
                  the paste, so the MODEL column's names are not offered
    Effort        passed as claude --effort
    Permission    pinned for the life of the window; it cannot be fixed
                  afterwards. (account default) passes no flag at all
    Where         a top-level window, or under a live one: ➥➥name, inserted
                  after that parent's subtree and drawn indented
    First prompt  empty writes a PLAN entry: the session gets its identity
                  line and nothing invented

    THEN IT WRITES A SCHEDULE ENTRY with at: already past, and nothing else:
    the watchdog opens the window within one pass and does the trust dialog,
    the readiness wait, the paste and the tree row -- one launcher, whoever
    asked. The entry carries model:, effort:, permission-mode:, cwd:,
    parent:/window:, and watchdog: off / monitor: off when Settings says a new
    window is not watched or monitored (the launcher opts the session out once
    it has an id). `/rc` is not written into the entry: the launcher sends it
    to every new window when Settings ▸ Send /rc to a new window is on (an
    entry's own rc: on|off wins).

    AND THEN IT TAKES YOU THERE. There is no window to jump to when you press
    Create -- the launcher has not opened it yet -- so the form remembers the
    slug, the key line reads `opening ➥name`, and the tmux client moves to
    that window the moment it appears. The dashboard keeps running in window
    0, so Ctrl-b 0 comes straight back. After three minutes it stops waiting
    and the window is simply there, like any other.

    Choosing bypassPermissions also offers "…and make it the default": a
    confirm names the exact settings.json (project or account, per Settings)
    and what changes -- EVERY future session there skips permission prompts,
    including ones nothing is watching. The write merges permissions.defaultMode
    into the existing JSON (nested, where Claude Code reads it), backs the
    old file up beside itself, and refuses a file that is not valid JSON.
"""

def register(app) -> None:
    flow = NewSession(app)
    app.newsession = flow
    # THE FORM IS A MENU LIKE ANY OTHER, so it gets the mover, the layouts,
    # the drawing and esc for free, and `c` only has to open it. No esc_to:
    # esc on the form closes it, because the form is not inside anything.
    app.add_menu("newsession", flow.entries, title_fn=flow.title,
                 hint_fn=lambda: "↑↓ pick · enter set · esc cancel",
                 on_esc=flow._cancel)
    app.add_hint(flow.follow_hint)
    app.add_help("A NEW CLAUDE SESSION (c)", HELP_NEWSESSION, order=20)
