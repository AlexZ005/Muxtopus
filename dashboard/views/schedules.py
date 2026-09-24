"""dashboard.views.schedules -- the `s` screen: entries, why, and the table.

One .md per window to open later. This module draws them, says why the
selected one has not fired, and owns everything that writes one: the create
flow, the options table, duplicate, launch-now, delete, and the resume
entry that the session menu offers from the main view.

WHAT IT READS THAT IS NOT ITS OWN, and the only supported way across the
line (docs/dashboard-views.md):

    app.view_of("main").cursor_sid() / .cursor_window() / .cursor_cwd()

-- because "schedule a resume of THIS window" and "create an entry in the
folder I am looking at" are both questions about the main view's cursor. The
accessors exist so that coupling is a named call anybody can grep for,
rather than `self.cursor` reached from the far side of the dashboard.

THE ROW IT PUTS IN SOMEBODY ELSE'S MENU. `Schedule a resume of <window>` is a
row in the SESSION menu, which dashboard/views/main.py owns. It arrives
through `app.add_rows("session", ..., order=85)` and not by editing that
file -- which is the whole point of the registry, demonstrated on the one
place the old code really did reach across.
"""
from __future__ import annotations

import subprocess
import time

from rich import box
from rich.console import Group
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import muxhandovers
import muxsettings
from dashboard.app import View
from dashboard.menulayout import (PAGE_KEYS, TABLE_MIN, fit_columns,
                                  make_table, page_jump, page_land,
                                  rendered_height, share_rows)
from dashboard.core import (DIM, FRAME, GREEN, HANDOVERS_DIR, HOME, PROFILE,
                            QUESTIONS_DIR, RED, SCHEDULES_DIR, SCHED_TEMPLATES,
                            SCRIPTS, YELLOW, human_age, options_paths,
                            read_options)
from dashboard.data import (handover_state, lane_slug_of, live_windows,
                            read_tree, sched_why, usage_limits)
from dashboard.schedules import (asked_value, options_fields, options_line,
                                 options_section, parse_options_line,
                                 read_schedules, rewrite_options,
                                 sanitise_slug)
from dashboard.naming import MAX_SLUG


class ScheduleView(View):
    """The `s` screen. Its own state is the cursor and the rows under it;
    everything else it touches belongs to the App or to the main view."""

    # `group` is what makes a SECOND table of scheduled things a new file
    # rather than an edit to this one: a view that declares the same group is
    # a tab beside this, the shell draws the strip in the panel title and ←→
    # cycles them. Alone in its group, as it is today, there is no strip and
    # nothing changes.
    name, key, group, order = "sched", "s", "s", 20

    def __init__(self, app) -> None:
        # The app is held as well as passed: the protocol hands it to
        # build/on_key/footer so a view CAN be written with no constructor,
        # and it is the same object either way. A menu row stores
        # `"act": self.duplicate_selected` -- a bound method of no arguments
        # -- and that is why the methods here reach it through self.
        self.app = app
        self.i = 0
        self.rows: list[dict] = []
        self._foot = None
        # THE TABLE'S PAGE, for PageUp/PageDown: the row lines build_sched
        # actually gave it this frame, which on a terminal with room is every
        # row there is.
        self._page = TABLE_MIN

    # ------------------------------------------------------ the protocol
    def tab_label(self, app) -> str:
        """What the strip calls this tab, WITH ITS COUNT -- the count is the
        reason a strip is worth the line: from the tab beside this one you
        can still see how many entries are waiting over here."""
        return "schedules %d" % len(self.rows)

    def tab_short(self, app) -> str:
        return "sched %d" % len(self.rows)

    def tab_initial(self, app) -> str:
        return "s"

    def build(self, app) -> list:
        return self.build_sched()

    def footer(self, app):
        return self._foot

    def menu_anchor(self, app) -> int:
        return 0

    def on_key(self, app, key) -> bool:
        return self.sched_key(key)

    # ------------------------------------------------------------ schedules
    def sched_move(self, delta: int) -> None:
        if self.rows:
            self.i = max(0, min(len(self.rows) - 1, self.i + delta))

    def sched_page(self, key: str) -> None:
        """PageUp/PageDown/Home/End in the entries table, clamped at both
        ends. A page is what the table SHOWS -- fewer rows on a short
        terminal, every row on a tall one."""
        j = page_jump(key, self.i, len(self.rows), self._page)
        if j is not None:
            self.i = j


    def _sched_sel(self):
        if 0 <= self.i < len(self.rows):
            return self.rows[self.i]
        return None


    def request_edit_selected(self) -> str:
        r = self._sched_sel()
        if r is None:
            return "nothing selected — c creates one"
        self.app.pending_edit = str(r["file"])
        return ""


    def reopen_options(self) -> str:
        """o: the same table on an entry that already exists.

        Pre-ticked from its own header, values and all, because the header is
        the source of truth -- opening boxes that disagree with the sentences
        underneath is exactly the lie this key exists to prevent."""
        r = self._sched_sel()
        if r is None:
            return "nothing selected — c creates one"
        if r["bad"]:
            return "cannot reopen: %s" % r["bad"]
        if r["status"] != "pending":
            return ("only a pending entry's options can be changed "
                    "(this one is %s)" % (r["status"] or "?"))
        opts = read_options(PROFILE)
        on = parse_options_line(r["options"])
        # A HEADER FIELD WRITTEN BY HAND TICKS ITS BOX. Otherwise `model: opus`
        # in a hand-edited entry would read as off here and be deleted by the
        # first save -- the table owns those fields, so it has to show what is
        # actually in the file.
        try:
            head = r["file"].read_text().partition("\n---\n")[0]
        except OSError as exc:
            return "cannot read: %s" % exc
        have = {}
        for l in head.split("\n"):
            k, sep, v = l.partition(":")
            if sep and v.strip():
                have[k.strip()] = v.strip()
        for o in opts:
            if o["set"] and o["key"] not in on and have.get(o["set"]):
                on[o["key"]] = have[o["set"]]
        self.open_options(r["file"].name[:-3], r["type"], opts, on,
                          lambda st, f=r["file"]: self._write_options(f, st),
                          mode="reopen")
        return ""


    def _write_options(self, f, st: dict) -> str:
        try:
            text = f.read_text()
            new, err = rewrite_options(text, st["all"], st["on"])
            if err:
                return "cannot rewrite: %s" % err
            if new == text:
                return "%s unchanged" % f.name
            f.write_text(new)
            n = len(parse_options_line(options_line(st["all"], st["on"])))
            return "%s — %d option(s)" % (f.name, n)
        except OSError as exc:
            return "rewrite failed: %s" % exc


    def start_create(self) -> None:
        self.app.picker = {"title": "schedule what?", "i": 0,
                       "options": ["plan", "work"], "fn": self._create_type}


    def _create_type(self, choice: str) -> str:
        if choice == "plan":
            tpls = sorted(t.stem for t in SCHED_TEMPLATES.glob("*.md"))
            if tpls:
                self.app.picker = {"title": "from which template?", "i": 0,
                               "options": tpls, "fn": self._create_tpl}
                return ""
        return self._create_options(choice, "")


    def _create_tpl(self, choice: str) -> str:
        return self._create_options("plan", choice)


    def _create_options(self, typ: str, tpl: str) -> str:
        """The step the plan added between the template and the editor.

        The FILENAME is settled here rather than in _create_write, so the
        table can name the entry it is about to write in its own title."""
        name = "%s-%s.md" % (typ, time.strftime("%Y%m%d-%H%M%S"))
        opts = read_options(PROFILE)
        on = {o["key"]: True for o in opts
              if o["default"] and not o["bad"] and o["types"] in ("both", typ)}
        self.open_options(name[:-3], typ, opts, on,
                          lambda st: self._create_write(typ, tpl, name, st))
        return ""


    def _create_write(self, typ: str, tpl: str, name: str, st: dict) -> str:
        """Write a pre-filled item and drop straight into the editor on it.

        The chosen template is COPIED into the body rather than referenced, so
        what you edit is exactly what gets pasted -- a referenced template
        would be prepended again by the executor."""
        try:
            SCHEDULES_DIR.mkdir(parents=True, exist_ok=True)
            f = SCHEDULES_DIR / name
            cwd = self.app.view_of("main").cursor_cwd()
            if not cwd or cwd == "-":
                # The setting, not a constant: this used to name one project
                # on one machine.
                cwd = muxsettings.get("DASHBOARD_NEW_CWD", PROFILE) or str(HOME)
            body = ""
            if tpl:
                try:
                    body = (SCHED_TEMPLATES / (tpl + ".md")).read_text()
                except OSError:
                    body = ""
            opts, on = st["all"], st["on"]
            # The set: fields and options: sit with cwd -- what the entry IS --
            # and ahead of status/created/launched, which are bookkeeping.
            extra = "".join("%s: %s\n" % kv for kv in options_fields(opts, on))
            line = options_line(opts, on)
            if line:
                extra += "options: %s\n" % line
            section = options_section(opts, on)
            if section:
                # AT THE END of the body, after the template: the body starts
                # with the task, as every brief does, and the contract follows.
                body = (body.rstrip() + "\n\n" if body.strip() else "") + section
            f.write_text("type: %s\n" % typ
                         + "at: reset\n"
                         + "title: \n"
                         + "window: \n"
                         + "cwd: %s\n" % cwd
                         + extra
                         + "status: pending\n"
                         + "created: %s\n" % time.strftime("%Y-%m-%d %H:%M")
                         + "launched:\n"
                         + "---\n" + body)
            self.app.pending_edit = str(f)
            n = len(parse_options_line(line))
            return ("created %s with %d option(s) — set the title and time, "
                    "paste the prompt" % (f.name, n))
        except OSError as exc:
            return "create failed: %s" % exc

    # ------------------------------------------------- the options table
    # Rendered and driven exactly like the space menu (option_rows /
    # options_move / options_key mirror menu_entries / menu_move /
    # menu_activate), and it reuses the existing prompt and picker for the
    # two options that need a value. Nothing new in the input layer.
    def open_options(self, title: str, typ: str, opts: list[dict],
                     on: dict, fn, mode: str = "create") -> None:
        """opts is SNAPSHOT at open: the ticks are keyed by option key, and a
        list that re-read itself every frame could reorder under the cursor
        while someone is halfway down it.

        ESC CANCELS, in both modes (the user's answer to
        QUESTIONS-sched-options-table §1, superseding the create flow's old
        "esc skips"): on create nothing is written, because the file is
        written by fn after the table and fn is simply not called; on a
        reopen the file is untouched. "Continue with nothing ticked" is a
        ROW at the bottom now, as are check all, uncheck all and continue."""
        # "key" and "panel" are what makes this A VIEW'S OWN MODAL rather
        # than a fourth submode App knows the shape of: App routes keys to
        # one and draws the footer with the other, and knows nothing else
        # about what is in here.
        self.app.modal = {"title": title, "typ": typ, "all": opts, "mode": mode,
                      "on": dict(on), "i": 0, "fn": fn,
                      "key": self.options_key, "panel": self.options_panel}
        self.options_move(0)


    def option_rows(self) -> list[dict]:
        """Group headings and option rows, in file order.

        A broken block is shown greyed with its reason and cannot be ticked --
        the same rule the schedule view applies to a corrupted entry, for the
        same reason: silently dropping it makes a typo look like a file nobody
        ever wrote."""
        st = self.app.modal
        if st is None:
            return []
        rows: list[dict] = []
        group = None
        known = set()
        for o in st["all"]:
            known.add(o["key"])
            # A TICKED OPTION IS ALWAYS SHOWN, even where types: would hide it:
            # a hand-edited entry can carry one, and a tick nobody can see is a
            # tick nobody can take off.
            if (not o["bad"] and o["types"] not in ("both", st["typ"])
                    and o["key"] not in st["on"]):
                continue
            if o["group"] != group:
                group = o["group"]
                rows.append({"head": group.upper()})
            rows.append({"opt": o, "disabled": o["bad"]})
        gone = [k for k in st["on"] if k not in known]
        if gone:
            rows.append({"head": "NOT IN options.md"})
            for k in gone:
                rows.append({"opt": {"key": k, "label": k, "hint": "", "bad":
                                     "gone from options.md — dropped on save",
                                     "set": "", "ask": "", "line": ""},
                             "disabled": "gone"})
        # THE ACTIONS ARE ROWS, not hidden key meanings: what enter does is
        # written where the cursor can reach it. `skip` exists only on create
        # -- on a reopen "save nothing ticked" beside "save" is the trap the
        # user just removed, and uncheck all + save says it in two steps.
        rows.append({"head": "ACTIONS"})
        rows.append({"act": "check_all", "label": "check all"})
        rows.append({"act": "uncheck_all", "label": "uncheck all"})
        if st["mode"] == "reopen":
            rows.append({"act": "continue", "label": "save  what is ticked"})
        else:
            rows.append({"act": "continue", "label": "continue  save what is ticked, then the editor"})
            rows.append({"act": "skip", "label": "skip  continue with nothing ticked"})
        return rows


    def options_move(self, delta: int) -> None:
        rows = self.option_rows()
        if not rows:
            return
        i = self.app.modal["i"]
        if delta == 0 and 0 <= i < len(rows) and not rows[i].get("head") \
                and not rows[i].get("disabled"):
            return
        step = delta or 1
        for _ in range(len(rows)):
            i = (i + step) % len(rows)
            if not rows[i].get("head") and not rows[i].get("disabled"):
                self.app.modal["i"] = i
                return


    def options_page(self, key: str) -> None:
        """The same four keys in the options table. EVERY ROW IS DRAWN there
        -- it is a panel, not a viewport -- so its page is its length and
        PageDown lands where End does; the headings are skipped the way the
        mover skips them."""
        rows = self.option_rows()
        if not rows or self.app.modal is None:
            return
        j = page_land(key, self.app.modal["i"], len(rows), len(rows),
                      lambda k: bool(rows[k].get("head")
                                     or rows[k].get("disabled")))
        if j is not None:
            self.app.modal["i"] = j


    def _option_sel(self) -> dict | None:
        rows = self.option_rows()
        i = self.app.modal["i"] if self.app.modal else -1
        if 0 <= i < len(rows) and rows[i].get("opt") and not rows[i].get("disabled"):
            return rows[i]["opt"]
        return None


    def options_toggle(self) -> str:
        """space: tick, untick, or ask for the value the tick needs."""
        o = self._option_sel()
        if o is None:
            return ""
        st = self.app.modal
        if o["key"] in st["on"]:
            del st["on"][o["key"]]
            return ""
        if o["set"]:
            self.app.picker = {"title": o["set"] + ":", "i": 0, "options": o["choices"],
                           "fn": lambda c, k=o["key"]: self._option_chose(k, c)}
            return ""
        if o["ask"]:
            self.app.prompt = {"title": o["label"], "buf": "",
                           "fn": lambda s, k=o["key"], a=o["ask"]: self._option_asked(k, a, s)}
            return ""
        st["on"][o["key"]] = True
        return ""


    def options_check_all(self) -> None:
        """Tick every plain option shown. One that needs a value (a choice
        or a number) is LEFT ALONE rather than ticked with nothing -- the
        sentence would go out with {{VALUE}} in it -- and the notice says
        how many were skipped for that reason."""
        st = self.app.modal
        skipped = 0
        for r in self.option_rows():
            o = r.get("opt")
            if not o or r.get("disabled") or o["key"] in st["on"]:
                continue
            if o["set"] or o["ask"]:
                skipped += 1
                continue
            st["on"][o["key"]] = True
        if skipped:
            self.app.say("%d option(s) need a value — tick those one by one" % skipped)


    def _option_chose(self, key: str, choice: str) -> str:
        if self.app.modal is not None:
            self.app.modal["on"][key] = choice
        return ""


    def _option_asked(self, key: str, kind: str, text: str) -> str:
        value, why = asked_value(kind, text)
        if why:
            # LEFT UNTICKED rather than ticked with a value nobody can use: the
            # sentence would go out with {{VALUE}} still in it.
            return "%s: %s — not ticked" % (key, why)
        if self.app.modal is not None:
            self.app.modal["on"][key] = value
        return ""


    def options_key(self, key: str) -> None:
        st = self.app.modal
        if st is None:
            return
        if key == "UP":
            self.options_move(-1)
        elif key == "DOWN":
            self.options_move(1)
        elif key in PAGE_KEYS:
            self.options_page(key)
        elif key == " ":
            msg = self.options_toggle()
            if msg:
                self.app.say(msg)
        elif key in ("\r", "\n"):
            rows = self.option_rows()
            row = rows[st["i"]] if 0 <= st["i"] < len(rows) else {}
            act = row.get("act")
            if act is None:
                # An option row: enter toggles, like space, now that continue
                # is a row of its own (QUESTIONS-dash-menus-settings 3a).
                msg = self.options_toggle()
                if msg:
                    self.app.say(msg)
                return
            if act == "check_all":
                self.options_check_all()
                return
            if act == "uncheck_all":
                st["on"] = {}
                return
            if act == "skip":
                st["on"] = {}
            fn = st["fn"]
            self.app.modal = None
            self.app.say(fn(st))
        elif key == "\x1b":
            # CANCEL, in both modes. The create flow's file is written by fn,
            # after the table, so not calling it means nothing is written.
            self.app.modal = None
            self.app.say("unchanged" if st["mode"] == "reopen"
                     else "cancelled — nothing written")


    def options_panel(self) -> Panel:
        """One row per option, laid out like the menu. Every cell that can grow
        is no_wrap + ellipsis: a hint is a whole sentence, and a row that wraps
        tears the table in half (see the WOUND column)."""
        st = self.app.modal
        g = Table.grid(padding=(0, 1), expand=True)
        g.add_column(width=1)                                     # cursor
        g.add_column(width=3)                                     # [x]
        g.add_column(width=38, overflow="ellipsis", no_wrap=True)  # label
        g.add_column(ratio=1, overflow="ellipsis", no_wrap=True)   # hint
        rows = self.option_rows()
        for i, r in enumerate(rows):
            if r.get("head"):
                g.add_row("", "", Text(r["head"], style="bold " + DIM), "")
                continue
            cur = (i == st["i"])
            mark = Text("▸" if cur else " ", style="bold #c9a0dc")
            if r.get("act"):
                g.add_row(mark, "", Text(r["label"], style="bold #c9a0dc" if cur else "#c9a0dc"), "")
                continue
            o = r["opt"]
            if o["bad"]:
                g.add_row(mark, Text("   ", style=FRAME),
                          Text(o["label"], style=FRAME),
                          Text(o["bad"], style=FRAME))
                continue
            v = st["on"].get(o["key"])
            label = o["label"] if v in (None, True) else "%s: %s" % (o["label"], v)
            box_txt = Text("[x]" if v is not None else "[ ]",
                           style=("bold " + GREEN) if v is not None else DIM)
            g.add_row(mark, box_txt,
                      Text(label, style="bold" if cur else ""),
                      Text(o["hint"], style=DIM))
        if not rows:
            g.add_row("", "", Text("no options", style=DIM),
                      Text(str(options_paths(PROFILE)[0]), style=DIM))
        keys = Text("   ↑↓ pick · space/enter toggle · enter on a row below does it · esc cancel",
                    style=DIM)
        # THE NOTICE HAS TO LIVE HERE. The footer is this panel while the table
        # is open, so a refused value ("a number, please — not ticked") reached
        # self.app.say and was then drawn nowhere at all.
        if self.app.notice and time.time() - self.app.notice_at < 8:
            keys = Text.assemble(("   " + self.app.notice, "#c9a0dc"), "\n", keys)
        return Panel(Group(g, keys),
                     title="[bold]options[/] [%s]· %s" % (DIM, st["title"]),
                     title_align="left", border_style="#c9a0dc", box=box.ROUNDED)


    def launch_selected_now(self) -> str:
        """Make the item due immediately; the daemon does the actual launch on
        its next 30s pass -- one launcher, whoever asked."""
        r = self._sched_sel()
        if r is None:
            return "nothing selected"
        if r["bad"]:
            return "cannot launch: %s" % r["bad"]
        if r["status"] != "pending":
            return "only a pending item launches (this one is %s)" % (r["status"] or "?")
        try:
            text = r["file"].read_text()
            lines = text.split("\n")
            for i, l in enumerate(lines):
                if l.startswith("at: "):
                    lines[i] = "at: " + time.strftime("%Y-%m-%d %H:%M")
                    break
            r["file"].write_text("\n".join(lines))
            return "due now — the watchdog launches it within ~30s"
        except OSError as exc:
            return "failed: %s" % exc


    def confirm_delete_selected(self) -> None:
        r = self._sched_sel()
        if r is None:
            self.app.say("nothing selected")
            return
        f = r["file"]
        self.app.confirm = {"label": "Delete %s?" % f.name,
                        "fn": lambda: self._do_sched_delete(f)}


    def _do_sched_delete(self, f) -> str:
        try:
            f.unlink()
            return "deleted %s" % f.name
        except OSError as exc:
            return "delete failed: %s" % exc


    def act_schedule_resume(self) -> str:
        """The wound-down flow's other half: a work item, due at the reset,
        that opens a fresh window right after this one and reads the STATUS
        handoff the wind-down asked the session to write."""
        main = self.app.view_of("main")
        win = main.cursor_window()
        cwd = main.cursor_cwd()
        if not win or not cwd or cwd == "-":
            return "no window/cwd to schedule from"
        try:
            SCHEDULES_DIR.mkdir(parents=True, exist_ok=True)
            # NOT in cwd. The handoff belongs to the account, not to the
            # working tree: it is scratch state that would otherwise be
            # committed, and two accounts on one repo would collide on the
            # window name.
            # THE SLUG, NOT THE DISPLAY NAME. `win` is the tmux name and can
            # carry ➥ markers, which sanitise to dashes: "resume ➥27-storage"
            # would derive the slug "resume--27-storage" and point the resumed
            # lane at a handover file the original never wrote. Pin both ends.
            lane = lane_slug_of(win)
            slug = sanitise_slug("resume-" + lane)
            status_file = "%s/STATUS-%s.md" % (HANDOVERS_DIR, lane)
            try:
                tpl = (SCHED_TEMPLATES / "resume-status.md").read_text()
            except OSError:
                tpl = ('Read {{STATUS_FILE}} and continue from its "How to resume" '
                       "section. One commit per phase; update the STATUS file "
                       "before stopping.")
            f = SCHEDULES_DIR / ("resume-%s.md" % lane)
            f.write_text("type: work\n"
                         + "at: reset\n"
                         + "title: resume %s\n" % lane
                         + "slug: %s\n" % slug
                         # window: is also what makes the resumed window a CHILD
                         # of the one it resumes, when that one was scheduled.
                         + "window: %s\n" % win
                         + "cwd: %s\n" % cwd
                         + "status: pending\n"
                         + "created: %s\n" % time.strftime("%Y-%m-%d %H:%M")
                         + "launched:\n"
                         + "---\n" + tpl.replace("{{STATUS_FILE}}", status_file))
            return "scheduled %s at the next reset (%s)" % (slug, f.name)
        except OSError as exc:
            return "schedule failed: %s" % exc

    # ------------------------------------------------- the schedule menu
    def sched_menu_entries(self) -> list[dict]:
        """Space in the schedule view: a menu for the SELECTED ENTRY.

        Built from _sched_sel() and nothing else -- it never reads
        self.cursor, so nothing in it can act on a claude session. (Before
        this, space fell through to the global handler and opened the
        session menu over a view that shows no sessions.) The why sentence
        leads when there is one, because that is the question in front of
        the row; a corrupted entry gets its reason and only Delete."""
        r = self._sched_sel()
        if r is None:
            return [{"label": "nothing scheduled", "disabled": "c creates an entry"}]
        name = r["file"].name
        if r["bad"]:
            return [{"label": "will never launch: " + r["bad"], "disabled": "corrupted"},
                    {"sep": True},
                    {"label": "Delete %s" % name, "act": self.confirm_delete_selected,
                     "danger": True}]
        items: list[dict] = []
        verdict, reason, _at = r.get("why", ("", "", 0))
        if verdict in ("blocked", "waiting", "stalled") and reason:
            items.append({"label": reason, "disabled": verdict})
        pending = r["status"] == "pending"
        only = "" if pending else "only a pending entry; this one is %s" % (r["status"] or "?")
        items += [
            {"label": "Edit %s" % name, "act": self.request_edit_selected},
            {"label": "Options",
             "desc": "the checkbox table, pre-ticked from the header",
             "act": self.reopen_options, "disabled": only},
            {"label": "Launch now",
             "desc": "make it due; the watchdog opens it within ~30s",
             "act": self.launch_selected_now, "disabled": only},
            {"label": "Duplicate as a new pending entry",
             "desc": "and open it in the editor",
             "act": self.duplicate_selected},
            {"label": "Check",
             "desc": "resolve it without launching: slug, window, paste, verdict",
             "act": self.check_selected},
        ]
        if r["status"] == "launched":
            node = read_tree().get(r["resolved"])
            if node and node["wid"] in live_windows():
                items.append({"label": "Open its window  %s" % node["wid"],
                              "act": lambda w=node["wid"]: self.goto_window(w)})
        items += [{"sep": True},
                  {"label": "Delete %s" % name, "act": self.confirm_delete_selected,
                   "danger": True}]
        return items


    def goto_window(self, target: str) -> str:
        """Move the tmux client to a window id; the dashboard keeps running."""
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


    def duplicate_selected(self) -> str:
        """A copy, pending, with the bookkeeping reset -- and a DIFFERENT
        slug. Two entries resolving to one slug are one window name and one
        handover file, so a pinned `slug:` is dropped and the title gains
        '-copy' (a suffix that sanitises to itself, so no slug warning); the
        editor opens on the copy so the title can be fixed at
        once. Everything else, the body included, is byte for byte."""
        r = self._sched_sel()
        if r is None:
            return "nothing selected"
        src = r["file"]
        dst = None
        for n in range(1, 100):
            cand = src.with_name("%s-copy%s.md" % (src.stem, "" if n == 1 else n))
            if not cand.exists():
                dst = cand
                break
        if dst is None:
            return "too many copies of %s already" % src.name
        try:
            text = src.read_text()
        except OSError as exc:
            return "cannot read: %s" % exc
        head, sep, body = text.partition("\n---\n")
        out: list[str] = []
        dropped = False
        titled = False
        for raw in head.split("\n"):
            k, has, v = raw.partition(":")
            k = k.strip()
            if not has:
                out.append(raw)
                continue
            if k == "slug":
                dropped = True
                continue
            if k == "title":
                out.append("title: %s-copy" % (v.strip() or src.stem))
                titled = True
                continue
            if k == "status":
                out.append("status: pending")
                continue
            if k == "launched":
                out.append("launched:")
                continue
            if k == "created":
                out.append("created: " + time.strftime("%Y-%m-%d %H:%M"))
                continue
            out.append(raw)
        if not titled:
            out.insert(1, "title: %s-copy" % src.stem)
        try:
            dst.write_text("\n".join(out) + sep + body)
        except OSError as exc:
            return "cannot write %s: %s" % (dst.name, exc)
        self.app.pending_edit = str(dst)
        return "duplicated as %s%s" % (
            dst.name, " — the pinned slug: was dropped; the title says -copy" if dropped else "")


    def check_selected(self) -> str:
        """The executor's own --check report, full screen: what THIS entry
        resolves to and why it has or has not fired, from the functions that
        will launch it -- the one thing this view cannot compute itself."""
        r = self._sched_sel()
        if r is None:
            return "nothing selected"
        script = SCRIPTS / "claude-watchdog.sh"
        if not script.exists():
            return "claude-watchdog.sh not found"
        acct = ["--profile", PROFILE] if PROFILE else []
        try:
            out = subprocess.run([str(script), *acct, "--check", str(r["file"]), "--body"],
                                 capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return "check failed: %s" % exc
        self.app.pending_report = (out.stdout + out.stderr) or "(--check printed nothing)"
        return ""


    def build_sched(self) -> list:
        """The schedule view's SECTIONS, top to bottom, and its footer put
        where SchedView.footer can find it. Placing an open menu among them
        is App.build's job now, and it is the same placer the main view gets
        -- which is the whole reason a view returns sections rather than a
        finished Group."""
        rows = read_schedules()
        self.rows = rows
        self.i = max(0, min(self.i, len(rows) - 1)) if rows else 0

        u = usage_limits()
        reset_txt = ""
        if u.get("session_reset_at"):
            try:
                reset_txt = time.strftime("%H:%M", time.localtime(int(u["session_reset_at"])))
            except (ValueError, OverflowError):
                pass

        # Columns as data, made into the table at the end once the frame
        # knows its size (menulayout.fit_columns / make_table, the ones the
        # main view uses): the number is the order a narrow terminal gives a
        # column up in, and TITLE carries the "▼ N more" marker.
        #
        # SLUG IS AS WIDE AS THE LONGEST SLUG ON SCREEN, never less than the 24
        # it always was and never more than MAX_SLUG + 2. It is the column that
        # shows the RESOLVED name -- the one the window, the handover and
        # `handover.sh done` will all use -- so an ellipsis in it hides the
        # exact characters it is there to show: at a literal 24, once the limit
        # rose from 22 to 32, a 30-character `<orchestrator>-<lane>` slug was
        # drawn cut. But a fixed MAX_SLUG + 2 cost everybody ten columns for
        # names almost nobody has: MEASURED with tests/sandbox/prove.sh, at
        # 100 columns fit_columns then gave SLUG up entirely, where the 24
        # had kept it. Sized to the rows, a machine with short slugs draws
        # exactly the table it drew before, and one with a long slug pays for
        # it out of TITLE (the ratio column), or on a narrow terminal loses AT
        # (rank 1) and then SLUG (rank 2) whole -- never drawn short.
        slug_w = min(MAX_SLUG, max([22] + [len(r["resolved"] or r["file"].name)
                                           for r in rows])) + 2
        st_cols = [
            ("", {"width": 3}, None),
            ("STATUS", {"width": 10}, None),
            ("TYPE", {"width": 6}, 3),
            ("FOR", {"width": 18}, 4),
            ("AT", {"width": 17}, 1),
            ("TITLE", {"ratio": 1, "min_width": 12}, None),
            ("SLUG", {"width": slug_w}, 2),
        ]
        st_rows: list[list] = []
        why = sched_why()
        for i, r in enumerate(rows):
            mark = Text("▸" if i == self.i else " ", style="bold #c9a0dc")
            r["why"] = why.get(r["file"].name, ("", "", 0))
            verdict = r["why"][0]
            if r["bad"]:
                stx = Text("corrupted", style=RED)
            elif r["status"] == "launched":
                stx = Text("launched", style=DIM)
            elif r["status"] == "error":
                stx = Text("error", style=RED)
            elif verdict == "stalled":
                # PENDING FOREVER IS NOT PENDING. An entry the executor cannot
                # judge used to be indistinguishable from one that is simply
                # early, and it never resolved on its own.
                stx = Text("stalled", style=RED)
            elif verdict == "blocked":
                stx = Text("blocked", style=YELLOW)
            elif verdict == "due":
                stx = Text("due", style="bold " + GREEN)
            else:
                stx = Text("pending", style=GREEN)
            when_for = r["at"] or "?"
            if r["at"] == "reset" and reset_txt:
                when_for = "reset (%s)" % reset_txt
            title = r["title"] or r["file"].stem
            if r["bad"]:
                ttx = Text("%s — %s" % (title, r["bad"]), style=RED)
            elif r["warn"]:
                # A divergent slug is not corruption -- it launches -- so it is
                # a warning on an otherwise normal row, not a refusal.
                ttx = Text.assemble(title, ("  ⚠ " + r["warn"], YELLOW))
            elif r["status"] == "launched" and r["launched"]:
                ttx = Text("%s — launched %s" % (title, r["launched"]))
            else:
                ttx = Text(title)
            st_rows.append([mark, stx, Text(r["type"] or "?", style=DIM),
                            Text(when_for), Text(r["created"] or "—", style=DIM),
                            ttx, Text(r["resolved"] or r["file"].name, style=DIM)])
        if not rows:
            st_rows.append(["", Text("—", style=DIM), "",
                            Text("nothing scheduled — press c", style=DIM), "", "", ""])
        st_keep = fit_columns(st_cols, self.app.console.size.width)

        def table_panel(lines):
            return Panel(make_table(st_cols, st_keep, [] if lines == "chrome" else st_rows,
                                    self.i, 5, None if lines == "chrome" else lines),
                         title="[bold]scheduled windows[/] "
                         f"[{DIM}]· {SCHEDULES_DIR} · templates in templates/",
                         title_align="left", border_style=FRAME, box=box.ROUNDED)

        parts = [table_panel(None)]
        self._page = max(1, len(rows))

        # WHY THE SELECTED ENTRY IS NOT RUNNING, in the executor's own words.
        # One line under the table rather than a column: the sentence is long
        # on purpose (it names the gate, the figure and the threshold) and it
        # is only ever wanted for the row under the cursor.
        sel = self._sched_sel()
        if sel is not None:
            verdict, reason, at = sel.get("why", ("", "", 0))
            if sel["bad"]:
                line = Text.assemble(("will never launch: ", RED), (sel["bad"], RED))
            elif reason:
                stale = " (%s ago)" % human_age(time.time() - at) if at else ""
                line = Text.assemble((reason, RED if verdict == "stalled" else ""),
                                     (stale, DIM))
            elif sel["status"] == "launched":
                # WHAT THE WINDOW THEN DID. The scheduler records the pane and
                # the window id at launch and stops there; whether the worker
                # errored, stalled or finished was invisible from here. The
                # tree plus the handover file answers it without the scheduler
                # having to follow the work it started.
                node = read_tree().get(sel["resolved"])
                bits = [("launched %s" % (sel["launched"] or "?"), DIM)]
                if node:
                    alive = node["wid"] in live_windows()
                    bits.append(("  ·  window %s %s" % (node["wid"],
                                 "open" if alive else "exited"),
                                 GREEN if alive else DIM))
                    bits.append(("  ·  pane %s" % node["pane"], DIM))
                state, age = handover_state(sel["resolved"])
                if state == "none":
                    bits.append(("  ·  no handover written yet", YELLOW))
                else:
                    bits.append(("  ·  handover %s, %s ago" % (state, human_age(age)),
                                 GREEN if state == "done" else ""))
                line = Text.assemble(*bits)
            else:
                line = Text("no verdict yet — the watchdog writes one every pass",
                            style=DIM)
            # WHAT IT WILL LAUNCH WITH, from the fields the options table
            # writes: they are header fields, so without this the only way to
            # see them was to open the file.
            bits = []
            if sel["model"]:
                bits.append("model %s" % sel["model"])
            if sel["effort"]:
                bits.append("effort %s" % sel["effort"])
            if sel["options"]:
                bits.append("%d option(s)" % len(parse_options_line(sel["options"])))
            if bits:
                line = Text.assemble(line, "\n",
                                     ("  ·  ".join(bits), DIM),
                                     ("      o reopens the table", DIM)
                                     if sel["status"] == "pending" else "")
            if sel["warn"]:
                line = Text.assemble(line, "\n", ("⚠ " + sel["warn"], YELLOW))
            parts.append(Panel(line, title="[bold]why", title_align="left",
                               border_style=FRAME, box=box.ROUNDED))

        # AWAITING YOUR ANSWERS, in ONE LINE and pointing somewhere.
        # This used to be a panel listing filenames out of QUESTIONS_DIR
        # alone -- the legacy folder -- so it showed nothing at all while
        # three unanswered files sat in the handovers folder, and it offered
        # no way to answer any of them. The handovers tab is both halves of
        # that fix; what stays here is the pointer, because this is the
        # screen the message was already familiar on.
        asking = muxhandovers.asking(HANDOVERS_DIR, QUESTIONS_DIR)
        if asking:
            parts.append(Panel(
                Text.assemble(
                    ("awaiting your answers: %d" % len(asking), "bold " + YELLOW),
                    # → skips a hidden tab, so the pointer must not lie.
                    ("   → to answer", DIM) if "handovers" not in self.app.hidden_tabs()
                    else ("   the handovers tab is hidden: esc ▸ Settings ▸ Tabs ▸ Open handovers once",
                          DIM)),
                border_style=FRAME, box=box.ROUNDED))

        # Settings ▸ Hints ▸ Footer key line, gated as the main view's is:
        # an empty Text, so the notice prepended below still lands and the
        # panel above keeps the height it measured against.
        keys = Text() if not self.app.guide("footer") else Text.assemble(
            (" ↑↓", DIM), " pick  ", ("pgup/dn home/end", DIM), " jump  ",
            ("space", DIM), " menu  ",
            ("enter", DIM), "/", ("e", DIM), " edit  ",
            ("c", DIM), " create  ", ("o", DIM), " options  ",
            ("l", DIM), " launch now  ",
            ("d", DIM), " delete  ", ("r", DIM), " reload  ",
            ("s", DIM), "/", ("esc", DIM), " back  ", ("q", DIM), " quit",
        )
        if self.app.notice and time.time() - self.app.notice_at < 8:
            keys = Text.assemble((" " + self.app.notice, "#c9a0dc"), "\n", keys)
        self._foot = keys
        # A SHORT TERMINAL: the table gets the rows that are left once the
        # panels under it and the footer are measured, and scrolls in them
        # with the menus' rule -- the main view's arithmetic, not a second
        # one. Under TABLE_MIN it keeps its minimum and Live crops.
        console = self.app.console
        foot = self.app._submode_foot() or keys
        if rendered_height(console, Group(*parts, foot)) > console.size.height:
            room = (console.size.height - rendered_height(console, table_panel("chrome"))
                    - rendered_height(console, Group(*parts[1:], foot)))
            lines = share_rows(room, [len(st_rows)]) or [TABLE_MIN]
            self._page = max(1, lines[0])
            parts[0] = table_panel(lines[0])
        # The entry's menu goes under the TABLE -- the why sentence belongs
        # in the menu, not above it -- so the anchor is section 0.
        return [("sched", parts[0])] + [("more", p) for p in parts[1:]]


    def sched_key(self, key: str) -> bool:
        """The schedule view owns most keys while it is open.

        Anything it does not claim falls through to the shell, which is why
        w, m, u, U and f still work from here -- they did before the split,
        and the split is not the place to decide they should not."""
        if key == "UP":
            self.sched_move(-1)
        elif key == "DOWN":
            self.sched_move(1)
        elif key in PAGE_KEYS:
            self.sched_page(key)
        elif key in ("\r", "\n", "e", "E"):
            m = self.request_edit_selected()
            if m:
                self.app.say(m)
        elif key == " ":
            # THE ENTRY'S menu. Without this case space fell through to the
            # global handler and opened the session menu over a view that
            # shows no sessions.
            self.app.open_menu("sched")
        elif key == "c":
            self.start_create()
        elif key == "o":
            m = self.reopen_options()
            if m:
                self.app.say(m)
        elif key == "l":
            self.app.say(self.launch_selected_now())
        elif key == "d":
            self.confirm_delete_selected()
        elif key == "r":
            self.app.say("schedules re-read")
        elif key in ("s", "\x1b"):
            self.app.switch_to("main")
        elif key in ("LEFT", "RIGHT", "t"):
            # The tree keys belong to the sessions table, not here;
            # swallowed so they cannot fold a row nobody can see.
            pass
        else:
            return False
        return True


    def _sched_menu_title(self) -> str:
        r = self._sched_sel()
        return "menu[/] [%s]· %s" % (DIM, escape(r["file"].name)) if r else "menu"


    # ------------------------- the row this view puts in the session menu
    def session_rows(self, app) -> list[dict]:
        """`Schedule a resume of <window>` -- a row in the MAIN view's session
        menu, registered rather than written into that view's file.

        It returns NOTHING for a lane row, the extras row or an empty cursor,
        because those three branches of the session menu never carried it:
        cursor_sid() is "" for exactly those, which is why the accessor
        answers that question rather than handing over the raw cursor."""
        main = app.view_of("main")
        sid = main.cursor_sid()
        if not sid:
            return []
        label = main.cursor_window() or sid[:8]
        return [{"label": "Schedule a resume of %s at the next reset" % label,
                 "desc": "reads its STATUS file",
                 "act": self.act_schedule_resume}]



# ------------------------------------------------------------------ help
# This module's slice of `?`. Registered with the ORDER it has always had,
# so the help screen reads exactly as it did when it was one string in
# deck_status.py -- the split moved who owns the words, not the words.
HELP_SCHEDULES = f"""
  [{DIM}]SCHEDULED WINDOWS (s)[/]
    One .md per window to open later, in {SCHEDULES_DIR} (templates in
    templates/; the folder README documents the format). The watchdog daemon
    launches due items: `at: reset` fires when the session limit resets or the
    budget simply reads fresh; an absolute time fires when it passes. The new
    window opens right after its `window:` target, named for its slug,
    and the prompt lands as ONE bracketed paste. A file the view cannot parse
    shows as corrupted with the reason, and never launches.
    In the view: enter/e edit · c create (type, template, THE OPTIONS TABLE,
    then the editor to paste the prompt) · o reopen the options table on a
    pending entry · l launch now · d delete · r reload · s/esc back.
    space opens the ENTRY'S menu: the why sentence when it is blocked, waiting
    or stalled, then edit, options, launch now, duplicate (a pending copy
    with a different slug, opened in the editor), check (the executor's
    --check --body report, full screen), open its window when it has one,
    and delete. A corrupted entry gets its reason and only delete.
"""

HELP_OPTIONS = f"""
  [{DIM}]THE OPTIONS TABLE (c, and o on a pending entry)[/]
    The checkboxes between the template and the editor: the contract sentences
    you would otherwise retype into every brief, ticked once. They come from

        {options_paths(PROFILE)[0]}

    which is YOURS -- one block per option, blank-line separated, `key: value`
    like a schedule header, its own comment block at the top being the format
    spec. Edit it and the table changes; a second account overrides or adds to
    it in profiles/<name>.options.md. A block the reader cannot make sense of
    is shown greyed with the reason rather than dropped, exactly as a
    corrupted schedule entry is.

    ↑↓ picks, space or enter ticks. An option that needs a number or a time
    opens the text prompt; one with a list of choices opens the picker (that
    is how model: and effort: are set). THE ACTIONS ARE ROWS at the bottom:
    check all, uncheck all, continue (save what is ticked, then the editor;
    "save" on a reopen) and, on create only, skip (continue with nothing
    ticked). esc CANCELS, on create and on reopen alike: on create no entry
    file is written at all, on reopen the file is untouched.

    A TICK WRITES ONE OF TWO THINGS: a sentence, appended to the body under a
    `## Options` heading at the END of it, or a header field (model:, effort:)
    the launcher passes as a flag. The header also records `options:
    questions, phases, lanes=3`, and THAT is the source of truth: o reopens
    the table from it and regenerates the section, so a sentence edited by
    hand in that section is overwritten on the next save. To keep one, move it
    ABOVE the heading -- everything above it is preserved byte for byte -- or
    edit it in options.md where it came from.

    Placeholders in a sentence ({{{{SLUG}}}}, {{{{WINDOW}}}}, {{{{HANDOVER}}}},
    {{{{HANDOVERS}}}}, {{{{QUESTIONS}}}}, {{{{SCHEDULES}}}}, {{{{STATE}}}}, {{{{CWD}}}},
    {{{{PARENT}}}}) are written out LITERALLY and resolved by the executor when the prompt is pasted, because
    the slug does not exist yet while the table is open. {{{{VALUE}}}} is the
    exception -- it is what the prompt collected, and it is resolved here.

    WHY AN ENTRY HAS NOT FIRED is printed under the table for the row under the
    cursor, in the executor's own words -- `at: reset` is two gates (the budget
    reading fresh, or the five-hour window rolling over) and the line says which
    one it is waiting on. A row marked [{RED}]stalled[/] cannot be judged at all and
    will not resolve on its own. To resolve an entry in full without launching
    anything -- slug, window name, handover path, insert target, the exact
    paste, and the due verdict with its reason:

        claude-watchdog.sh --check <name> [--body] Plan sessions write their forks into core/plans/QUESTIONS-*.md
    instead of asking; those files are listed in the view until answered.
"""

def register(app) -> None:
    """Called once, by the shell, with no file naming this module."""
    view = ScheduleView(app)
    app.add_view(view)
    app.add_menu("sched", view.sched_menu_entries,
                 title_fn=view._sched_menu_title)
    # 85 puts it where it has always been: after "Continue at low priority"
    # (the eighth row, so 80) and before the separator above Close (90).
    app.add_rows("session", view.session_rows, order=85)
    app.add_help("SCHEDULED WINDOWS (s)", HELP_SCHEDULES, order=50)
    app.add_help("THE OPTIONS TABLE (c, and o on a pending entry)", HELP_OPTIONS, order=51)
