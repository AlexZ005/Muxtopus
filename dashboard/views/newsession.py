"""dashboard.views.newsession -- c: a new claude session, on ONE screen.

A FORM, NOT A WIZARD, AND NOT A MODAL EITHER. `c` opens one menu with every
parameter on it, each row already carrying the value it would use, and
`Create` on the first row -- so the whole of "give me a window" is `c enter`,
and changing something is arrowing to that row and pressing enter on it. It
was seven pickers in a fixed order, which meant answering six questions you
had no opinion about to reach the one you did.

THE NAME IS IN THE CREATE ROW, and it is typed there:

    Create [muxtopus-crane       ]  and go to its window  · type to rename

It was a prompt over the top of the form, asked before the form was drawn.
Three things were wrong with that. The modal's box RESIZED as the name was
typed and the form jumped when it closed; the name was answered before the
folder it is derived from could be seen; and it was a question you had to
dismiss even when the offer was the answer. Now the row IS the field --
letters and backspace go into it (App._menu_edit), everything else belongs to
the menu -- it is padded to MAX_SLUG so nothing moves as you type, and the
first character typed replaces the whole offer rather than appending to it.

THE OFFER MOVES ON when you ask again. `c`, then `c` again, used to suggest
the same name twice: the offer was seeded from the folder alone and the only
thing that advanced it was a name being TAKEN -- which a name you just
declined is not. The form counts its opens and passes that as naming.suggest's
nonce.

A NAME IS REFUSED BY Create, not while it is typed. There is no modal to put
back up, so an empty or taken name leaves the form exactly as it is with the
reason on the notice line, and the fix is to keep typing. sanitise_slug runs
once, on Create, and never per keystroke -- a field that rewrites the
character under the cursor is not a field.

TWO SUB-WINDOW ROWS, under Create. A fork of the lane the cursor is on, empty
or carrying on from that lane's handover, is the common second window and was
two rows and a paste away; it is now one enter. The top row is unchanged and
still makes a top-level window.

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
    app.view_of("main").cursor_window()     what a sub-window goes under
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
from dashboard import naming
from dashboard.core import (CONFIG_DIR, DIM, GREEN, HANDOVERS_DIR, PROFILE,
                            SCHED_TEMPLATES, SCHEDULES_DIR, SCRIPTS,
                            WATCHDOG_ENABLED, YELLOW, model_choices, mux_home)
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
        # How many times `c` has been pressed this run. It is the nonce the
        # offered name is seeded with, so asking again asks for a different
        # word -- see start_new_session.
        self._opens = 0

    # ------------------------------------------------ c: the form
    # ONE MENU, every parameter on it, Create first. app.ns holds the answers
    # while it is open -- the same dict the seven pickers filled, so _ns_write
    # below did not have to change shape -- and the menu is redrawn from it on
    # every frame, which is what makes a row show the value you just set.
    def start_new_session(self) -> str:
        mode = muxsettings.get("DASHBOARD_NEW_PERMISSION_MODE", PROFILE)
        cwd = self._default_cwd()
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
            "title": "", "slug": "",
        }
        # A SECOND `c` OFFERS A SECOND NAME. The offer used to be seeded from
        # the folder alone, so pressing `c`, reading `muxtopus-crane` and
        # pressing `c` again offered `muxtopus-crane` again -- the only thing
        # that moved it on was a name being TAKEN, and a name you just
        # declined is not taken. The counter is what "ask me again" means.
        self._opens += 1
        self.app.ns["offer"] = self._suggested_name(self._opens - 1)
        # NO MODAL. The name is the one parameter nothing else can choose
        # well, so it is still the first thing on the screen -- but it is now
        # typed INTO the Create row rather than into a prompt over the top of
        # it. `c` used to open a modal whose box resized as the name was
        # typed, which meant the form underneath jumped when it closed and the
        # answer was given before the folder it belongs to could be seen.
        # The row is the field, the field is fixed width, and `c enter` is one
        # keystroke SHORTER than it was.
        self.app.ns["slug"] = self.app.ns["offer"]
        self.app.ns["title"] = self.app.ns["offer"]
        self.app.ns["typed"] = False
        self.app.open_menu("newsession")
        return ""

    @staticmethod
    def _name_for(cwd: str) -> str:
        """What the FOLDER contributes to the offered name. The LEADING DOT
        GOES: sanitise_slug is the executor's rule character for character and
        keeps it (a slug may legitimately contain one), but a folder called
        ~/.code would then offer `.code`, whose handover is the hidden file
        STATUS-.code.md and whose window is called .code. Typing that is still
        allowed; offering it is not something anybody meant to ask for."""
        base = os.path.basename(cwd.rstrip("/")).lstrip(".")
        if not base:
            base = os.path.basename(os.path.dirname(cwd.rstrip("/"))).lstrip(".")
        return sanitise_slug(base)

    def _suggested_name(self, nonce: int = 0) -> str:
        """The name in the brackets: the folder and one word (naming.py).

        WHY NOT THE FOLDER ALONE, which is what it used to be: the second
        window in a folder cannot have that name, and the answer then was
        `scripts-2`, `scripts-3` -- which is the collision papered over
        rather than solved, because the digit tells you nothing about which
        of the three you are looking at. A word does: `scripts-otter` and
        `scripts-heron` are as easy to tell apart as they are to say, and
        the first one in a folder gets a word too, so there is no odd one
        out and no renaming when the second arrives."""
        return naming.suggest(self._name_for(self.app.ns["cwd"]),
                              self._taken_slugs(), nonce=nonce)

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

    # ------------------------------------------------------------- the rows
    def entries(self) -> list[dict]:
        ns = self.app.ns
        if not ns:                       # esc closed it; the menu goes too
            return []
        where = ("under %s" % ns["window"]) if ns.get("window") else "a top-level window"
        prompt = ns.get("prompt") or ""
        items = [
            {"label": "Create [%s]" % self._name_field(),
             "desc": "and go to its window · type to rename",
             "act": self._create, "edit": self._name_key},
            {"sep": True},
        ]
        items += self._quick_rows()
        items += [
            {"label": "Folder: %s" % self._short(ns["cwd"]),
             "desc": "where claude starts",
             "act": self._edit_cwd, "stay": True},
            {"label": "Model: %s" % self._shows("model", ns["model"]),
             "desc": "a CLI alias; the MODEL column's names are refused",
             "act": self._edit_model, "stay": True},
            {"label": "Effort: %s" % self._shows("effort", ns["effort"]),
             "act": self._edit_effort, "stay": True},
            {"label": "Permission mode: %s" % self._shows("mode", ns["mode"]),
             "desc": "cannot be changed after launch",
             "act": self._edit_mode, "stay": True},
            {"label": "Where: %s" % where, "act": self._edit_where, "stay": True},
            {"label": "First prompt: %s" % (self._short_prompt(prompt)),
             "desc": "empty makes it a plan entry",
             "act": self._edit_prompt, "stay": True},
            {"sep": True},
            {"label": "Cancel", "act": self._cancel},
        ]
        if ns.get("default_msg"):
            items.insert(1, {"label": "settings.json %s: %s"
                                      % ("NOT written" if ns.get("default_err") else "written",
                                         ns["default_msg"]),
                             "disabled": "already done"})
        # THE DISARMED WATCHDOG, SAID OUT LOUD. `c` writes an entry and the
        # WATCHDOG opens the window; a disarmed one returns at the first line
        # of check_schedules, so the entry is written, nothing ever reads it,
        # and the form reported "scheduled" exactly as it does when it worked.
        # Measured on a fresh box: an entry sat `pending` for 19 minutes with
        # no new window and nothing anywhere saying why.
        if not WATCHDOG_ENABLED.exists():
            items.insert(1, {"label": "⚠ the watchdog is DISARMED — nothing will open this "
                                      "window until it is armed",
                             "disabled": "press w on the dashboard to arm it"})
        return items

    # ------------------------------------------------- the two quick rows
    # A SUB-WINDOW IS THE COMMON SECOND WINDOW. You are in a lane, the work
    # forks, and what you want is another session under this one -- either
    # empty, to put something unrelated in, or carrying on from where this
    # one wrote its handover. Both are reachable from the rows below (Where,
    # then First prompt), and both were four keystrokes and a paste away;
    # these are the same two entries written for you, one enter each.
    #
    # THE TOP ROW STAYS A TOP-LEVEL WINDOW. That is what `c enter` has always
    # made and what most windows are; a form whose first row changed meaning
    # depending on where the cursor happened to be would be a form you had to
    # read before pressing enter on it.
    def _quick_parent(self) -> tuple[str, str]:
        """(window name, slug) of the window a quick sub-window would go
        under: the one the form was told about, else the one the cursor is
        on. ("", "") when there is none -- a lane row, the extras row, or a
        session with no window at all."""
        win = self.app.ns.get("window") or self.app.view_of("main").cursor_window()
        return (win, lane_slug_of(win)) if win else ("", "")

    def _quick_rows(self) -> list[dict]:
        win, lane = self._quick_parent()
        if not win:
            return []
        status = HANDOVERS_DIR / ("STATUS-%s.md" % lane)
        # THESE TWO ROWS DIFFER ONLY IN THE PROMPT THEY SEND, so that
        # difference belongs on the LABEL and not in the description: a
        # description is drawn for one row at a time, and two rows both
        # reading "Sub-window x under y", with the half that tells them
        # apart visible only on whichever one the cursor is on, is a list
        # you cannot choose from. An explicit `key` for the same reason --
        # row_id would take the shared head off both and esc could not tell
        # which of them it came from.
        rows = [
            {"key": "sub_empty",
             "label": "Sub-window %s under %s: empty" % (self.app.ns["slug"], win),
             "desc": "no first prompt -- the window opens on a blank claude",
             "act": self._create_sub_empty},
            {"key": "sub_handover",
             "label": "Sub-window %s under %s: from its handover"
                      % (self.app.ns["slug"], win),
             "desc": "continues from its handover -- STATUS-%s.md is read into "
                     "its first prompt" % lane,
             "act": self._create_sub_handover},
        ]
        if not status.exists():
            # NOT hidden, and not silently pointed at a file that is not
            # there: the row is the answer to "can I fork this lane yet", and
            # "not until it has written one" is that answer. `Wind down` in
            # the session menu is what asks for one.
            rows[1]["disabled"] = "%s has not written STATUS-%s.md" % (win, lane)
        rows.append({"sep": True})
        return rows

    def _create_sub(self, prompt: str) -> str:
        win, lane = self._quick_parent()
        if not win:
            return "no window to go under"
        # window: is the tmux name, parent: the slug the tree is keyed on --
        # the same two fields the Where row sets, because this IS the Where
        # row, answered for you.
        self.app.ns["window"], self.app.ns["parent"] = win, lane
        self.app.ns["prompt"] = prompt
        return self._create()

    def _create_sub_empty(self) -> str:
        return self._create_sub("")

    def _create_sub_handover(self) -> str:
        """The child reads the parent's handover. The same template the
        schedule view's `Schedule resume` uses, resolved the same way, so a
        resume at the next reset and a fork right now say one thing to the
        session and not two."""
        _win, lane = self._quick_parent()
        status = "%s/STATUS-%s.md" % (HANDOVERS_DIR, lane)
        try:
            tpl = (SCHED_TEMPLATES / "resume-status.md").read_text()
        except OSError:
            tpl = ('Read {{STATUS_FILE}} and continue from its "How to resume" '
                   "section. One commit per phase; update the STATUS file "
                   "before stopping.")
        return self._create_sub(tpl.replace("{{STATUS_FILE}}", status).strip())

    # ------------------------------------------- the name, typed in the row
    # FIXED WIDTH, and that is the point of padding a field nobody asked to
    # be padded. The Create row is the widest thing on this menu, so the
    # MENU's width followed the name: every character typed re-measured the
    # box and the whole form twitched sideways under the cursor. Padded to
    # MAX_SLUG the row is the same width empty, full, and at every keystroke
    # in between -- and the blank space is the budget, which is worth seeing
    # on a field that is silently cut at 22.
    def _name_field(self) -> str:
        return self.app.ns["slug"].ljust(naming.MAX_SLUG)

    def _name_key(self, key: str) -> bool:
        """Type into the Create row. True for a key this took.

        WHAT IT TAKES is deliberately narrow: the characters a slug may hold,
        and backspace. Everything else -- enter, the arrows, esc, the page
        keys -- belongs to the menu, so the row is a field without ever
        becoming a mode you have to leave. sanitise_slug is not applied per
        keystroke: it would rewrite the character under the cursor as it was
        typed, which is the one thing a text field must never do. It is
        applied once, on Create."""
        ns = self.app.ns
        if key in ("\x7f", "\b"):
            # THE OFFER GOES WHOLE on the first backspace. Deleting one
            # character of a name you never typed leaves `muxtopus-cran`,
            # which is not a name anybody wanted and is one keystroke from
            # being created by accident.
            ns["slug"] = "" if not ns.get("typed") else ns["slug"][:-1]
            ns["typed"] = True
            ns["title"] = ns["slug"]
            return True
        # SPACE IS A HYPHEN, and it must be CONSUMED either way. A slug has no
        # spaces, so the obvious reading of a typed space is the one
        # sanitise_slug always gave it -- `typed one` is `typed-one`. Letting
        # it fall through instead would hand it to the menu, where space
        # CLOSES the form: typing a two-word name would have thrown the whole
        # thing away mid-word.
        if key == " ":
            key = "-"
        if len(key) == 1 and key.isprintable():
            if not ns.get("typed"):
                # The first character REPLACES the offer rather than being
                # appended to it: the offer is a suggestion, and typing is
                # how you decline it.
                ns["slug"] = ""
                ns["typed"] = True
            if len(ns["slug"]) < naming.MAX_SLUG:
                ns["slug"] += key
                ns["title"] = ns["slug"]
            return True
        return False

    # ------------------------------------------ what a default actually IS
    def _shows(self, what: str, chosen: str) -> str:
        """The value a row reports: what was picked, or -- when nothing was --
        WHAT WILL ACTUALLY HAPPEN.

        These three rows used to read "(account default)", which names the
        mechanism (no flag is passed) and not the outcome, and the outcome is
        the only part anyone wants to know before pressing Create. So the
        settings.json layers are read and the value is named. When nothing
        sets it anywhere, that is said too -- and it is a different answer
        from a value, not a worse one: it means the CLI's own built-in
        default applies, which this cannot know without running claude."""
        if chosen:
            return chosen
        value, where = muxsettings.effective_default(
            what, self.app.ns["cwd"], CONFIG_DIR)
        if value:
            return "%s  (from %s)" % (value, where)
        return "unset  (no flag; the CLI's own default)"

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

    # THE NAME IS CHECKED ON CREATE, not as it is typed. There is no modal
    # to put back up any more, so a refusal has to be something the form can
    # say while staying open: Create reports why and changes nothing, the
    # name is still in the row, and the fix is to keep typing.
    def _name_problem(self) -> str:
        """Why this name cannot be used, or "" when it can."""
        slug = sanitise_slug(self.app.ns["slug"].strip())
        if not slug:
            return "the name is empty — type one into the Create row"
        if slug in self._taken_slugs():
            return "%s is taken (a window or an entry has it) — type another" % slug
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
        """Write the entry, then watch for the window it will become.

        The name is checked HERE because there is no longer a modal to refuse
        it in. A bad one leaves the form open, exactly as it was, with the
        reason on the notice line -- so the fix is to carry on typing rather
        than to start again."""
        why = self._name_problem()
        if why:
            return why
        # Sanitised once, at the end, rather than per keystroke: applying the
        # slug rule while someone is typing rewrites the character under the
        # cursor, which is the one thing a text field must not do.
        self.app.ns["slug"] = sanitise_slug(self.app.ns["slug"].strip())
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
            # window: is the tmux name -- lane_slug_of takes the markers
            # off an older release's;
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
        and a plan may be empty: nothing is pasted, the window opens at a
        blank prompt, and its identity rides in the system prompt
        (QUESTIONS 2a)."""
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
        # GO NOW, rather than waiting out the poll. The entry is already on
        # disk, so this is pure latency: nudged, the window appears in about a
        # second; unnudged it took up to a full interval (measured at 20-30s),
        # which read as the dashboard having ignored the keypress.
        if not WATCHDOG_ENABLED.exists():
            # Written, and honestly reported as going nowhere. Not refused:
            # the entry is a real record of what was asked for, and arming
            # the watchdog launches it without retyping any of the form.
            return ("wrote %s — but the watchdog is DISARMED, so nothing will "
                    "open it. Press w to arm it." % f.name)
        woke = self._nudge_watchdog()
        msg = ("scheduled %s — opening it now (%s)" if woke else
               "scheduled %s — the watchdog opens it within ~30s (%s)") % (slug, f.name)
        if ns.get("default_msg"):
            msg += " · settings.json %s" % ns["default_msg"]
        return msg

    @staticmethod
    def _nudge_watchdog() -> bool:
        """Ask the daemon to take its next pass NOW. Best effort by design:
        the entry is written either way and the next ordinary pass launches
        it, so a daemon that is not running, or one too old to know --nudge,
        costs the old latency and never an error."""
        cmd = [str(SCRIPTS / "claude-watchdog.sh")]
        if PROFILE:
            cmd += ["--profile", PROFILE]
        cmd += ["--nudge"]
        try:
            return subprocess.run(cmd, capture_output=True, timeout=5).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False


    # --------------------------------------------------------- the follow
    # "and go to its window" cannot happen when Create is pressed: there is no
    # window yet. The dashboard writes an entry and the WATCHDOG opens the
    # window a pass later, so the jump has to wait for something that has not
    # been created yet by anything on this side of the line.
    #
    # WHY IT IS A HINT. A hint runs on every main-view frame and may draw one
    # mark on the key line, which is exactly the shape this needs: something
    # that looks each frame, says "opening name" while it is looking, and
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
        return Text("  · opening %s" % f["slug"], style=YELLOW)

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
    ONE SCREEN, not a questionnaire and no modal in front of it. `c` opens a
    form with every parameter already filled in from Settings ▸ the new-window
    defaults and `Create` on the first row -- so a window you have no
    particular opinion about is [bold]c enter[/], and one you do is arrowing
    to that row and pressing enter on it. The form stays open while you do:
    set the effort, change your mind about the folder, set it back. esc on a
    row leaves that row alone; esc on the form abandons the whole thing.

    THE NAME IS TYPED INTO THE CREATE ROW:

        Create [scripts-otter       ]  and go to its window  · type to rename

    It is the slug -- the window name, STATUS-name.md, `handover.sh done
    name` -- so it is worth reading before you press enter, and what is in the
    brackets is what enter takes. Type and it is yours: the first character
    replaces the whole offer, backspace clears it, and the field is padded so
    the form does not move under you while you type. An empty or already-taken
    name is refused by Create with the reason on the notice line, and the form
    stays exactly as it was.

    THE OFFER IS THE FOLDER AND ONE WORD, `scripts-otter`, checked against
    every window and pending entry first. The word is there because the second
    window in a folder used to be `scripts-2` and the third `scripts-3`, and a
    digit tells you nothing about which of the three you are looking at. Press
    `c` again and you get a different word -- asking again is how you say you
    did not want that one.

    TWO SUB-WINDOW ROWS sit under Create whenever the cursor is on a live
    session: `empty, no prompt`, and `continues from its handover`, which
    pastes the same brief `Schedule resume` does -- read STATUS-<parent>.md
    and carry on from its "How to resume" section. Both make a  child of
    that window; the handover row is greyed with the reason until that lane
    has actually written one (`Wind down` in the session menu asks for it).
    Create itself is unchanged: a top-level window.
    Folder        enter opens the candidates -- the cursor's folder, the
                  setting, every live session's, the dirty trees the watchdog
                  publishes, the checkouts under MUXTOPUS_HOME -- or a typed
                  path, which must exist
    Model         a CLI ALIAS (opus, fable, sonnet…). `--model opus-5` is
                  refused by the CLI and kills the window after it has eaten
                  the paste, so the MODEL column's names are not offered
    Effort        passed as claude --effort
    Permission    pinned for the life of the window; it cannot be fixed
                  afterwards

    MODEL, EFFORT AND PERMISSION SAY WHAT YOU WILL GET. A row nobody has set
    used to read "(account default)", which names the mechanism -- no flag is
    passed -- and not the outcome. It now reads the value out of the
    settings.json layers that will actually apply (the project's
    settings.local.json, its settings.json, then the account's) and names it
    and the file. When nothing anywhere sets it the row says `unset`, which is
    a different answer and an honest one: the CLI's own built-in default
    applies, and that cannot be known without running claude.
    Where         a top-level window, or under a live one: name, inserted
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
    slug, the key line reads `opening name`, and the tmux client moves to
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
