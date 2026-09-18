"""muxhandovers -- ONE READER for the STATUS and QUESTIONS files of a lane.

A handover is a file in the account's handovers folder, and until now three
programs each had their own idea of what one meant: `sched_dep_state` in
claude-watchdog.sh (which decides whether an `after:` is satisfied), the
dashboard's `handover_state` (which draws the WHY line), and a glob in the
schedule view that looked for QUESTIONS files in the wrong folder entirely.
They disagreed, and the disagreement was invisible: a lane that ran, was
marked done and ran again has BOTH files, and the watchdog called it finished
while the dashboard called it open.

So the rules live here, once, as pure functions of a directory -- no Rich, no
tmux, no dashboard -- and everything else calls them:

    scan(hdir, legacy_qdir=None, cache=None) -> [Row]   every file, as rows
    lane_state(hdir, slug)     -> (state, age)   THE definition; done wins
    question_state(text)       -> "unanswered" | "answered"
    summarise(text)            -> (title, gist)
    said(title, gist, slug)    -> the one line a row shows
    forks(text)                -> (count, first fork's line)
    visible(rows, done, qs)    -> the two filters
    slug_of(name)              -> (kind, slug, stamp)

and, for answering a fork without leaving the dashboard (and for the phone,
which imports these three by name):

    parse_forks(text)                       -> [Fork]
    write_answer(text, fork_id, answer, date[, source]) -> text
    all_answered(forks)                     -> bool

THE ORDER IN lane_state IS NOT AN IMPLEMENTATION DETAIL. It mirrors
sched_dep_state, which tests done/ FIRST -- so a lane with both files is
`done` to `after:` and must be `done` here too, or the dashboard would
promise a hold that the executor has already released.
tests/test_handovers.py greps that order out of the shell and asserts it, so
a future reorder on the shell side fails a Python test.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path

# A file is ANSWERED iff some line matches this (plan §2.2). `**ANSWERED
# 2026-09-17: ...` -- what the user already types by hand -- counts, which is
# why the marker is anchored past any leading punctuation rather than at the
# start of the line.
ANSWERED_RE = re.compile(r"^\W*ANSWERED\b", re.M)
# A FORK STARTS AT COLUMN 0: a `## ` heading or a top-level `N.` item. The
# leading-whitespace version of this pattern splits a fork at its own
# indented sub-list, which every real file with bulleted options has.
FORK_RE = re.compile(r"^(?:\d+\.\s|##\s)")
# A fork is answered when one of its lines starts `**Answer` -- the shape the
# files already use (`**Answer taken:**`, `**Answer: (a).**`), and the one
# write_answer writes.
ANSWER_RE = re.compile(r"^\s*\*\*Answer")
# Our own answer line, the one write_answer may replace to stay idempotent.
OURS_RE = re.compile(r"^\s*\*\*Answer \(")
OPTION_RE = re.compile(r"\(([a-z])\)")
# `Recommendation: (a)`, `Recommended: (b)` -- a letter named outside the
# option text itself.
REC_LINE_RE = re.compile(r"recommend\w*[^(\n]*\(([a-z])\)", re.I)
FENCE_RE = re.compile(r"^\s*(```|~~~)")
# STATUS-<slug>.md, QUESTIONS-<slug>.md, and the stamped name `handover.sh
# done` gives a SECOND finish of the same lane -- a name nothing parsed until
# this module.
NAME_RE = re.compile(r"^(STATUS|QUESTIONS)-(.+?)(?:-(\d{8}-\d{6}))?\.md$")
# The words a handover title carries that say nothing about the lane. What is
# left after they and the slug are removed is how much the title actually
# says (§2.3).
BOILERPLATE = re.compile(r"\b(STATUS|Handoff|Handover|Lane|DONE|done)\b", re.I)
# Rows sort by what is OWED, not by name: unanswered questions first, because
# they are the only kind of row that is waiting on the person reading it.
RANK = {"unanswered": 0, "open": 1, "answered": 2, "done": 3, "none": 4}


# --------------------------------------------------------------- the names
def slug_of(name: str) -> tuple[str, str, str]:
    """`STATUS-x.md` -> ("status", "x", ""), and the stamped second finish
    `STATUS-x-20260917-101500.md` -> ("status", "x", "20260917-101500").

    Anything else is ("", "", ""): the folder holds other files (a drafts
    directory, a README) and a reader that guessed at them would invent lanes.
    """
    m = NAME_RE.match(os.path.basename(name))
    if not m:
        return "", "", ""
    return m.group(1).lower(), m.group(2), m.group(3) or ""


def status_name(slug: str, stamp: str = "") -> str:
    """The round trip of slug_of, and the only place a STATUS path is spelt."""
    return "STATUS-%s%s.md" % (slug, "-" + stamp if stamp else "")


def questions_name(slug: str, stamp: str = "") -> str:
    return "QUESTIONS-%s%s.md" % (slug, "-" + stamp if stamp else "")


# -------------------------------------------------------------- the states
def lane_state(hdir, slug: str) -> tuple[str, float]:
    """What the lane's handover says: ("done"|"open"|"none", age in seconds).

    done/ IS TESTED FIRST, exactly as sched_dep_state does it, because that
    is what `after: <slug>` actually asks. A lane that has both files is done
    to the executor, and this saying anything else is how the dashboard came
    to promise a hold that had already been released.
    """
    hdir = Path(hdir)
    for path, label in ((hdir / "done" / status_name(slug), "done"),
                        (hdir / status_name(slug), "open")):
        try:
            return label, time.time() - path.stat().st_mtime
        except OSError:
            continue
    return "none", 0.0


def shadowed(hdir, slug: str) -> bool:
    """Both files exist: the row is drawn `open` and flagged, because a
    `done/STATUS-<slug>.md` from an EARLIER run satisfies every `after:
    <slug>` right now while the open file says the work is not finished.
    That is a real trap and showing it is the fix this module can make
    without changing the executor."""
    hdir = Path(hdir)
    return (hdir / status_name(slug)).exists() \
        and (hdir / "done" / status_name(slug)).exists()


def question_state(text: str) -> str:
    """A QUESTIONS file is answered iff it carries the marker line."""
    return "answered" if ANSWERED_RE.search(text) else "unanswered"


# ------------------------------------------------------------ what it says
def _clean(line: str) -> str:
    """One line of markdown as prose: hashes, emphasis and backticks off."""
    line = re.sub(r"^[#>\s]+", "", line)
    line = re.sub(r"\*\*|\*|`|~~", "", line)
    return line.strip().strip("-–—").strip()


def _skippable(line: str) -> bool:
    s = line.strip()
    return (not s or s.startswith("#") or s.startswith("|")
            or bool(FENCE_RE.match(line))
            or bool(re.match(r"^([-*_=])\1{2,}$", s)))


def summarise(text: str) -> tuple[str, str]:
    """(title, gist) of a handover, with NO header convention imposed.

    Seventeen of these files already exist and no two are laid out the same
    way, so this reads what is there: the first non-blank line is the title
    (a `#` heading loses its hashes), and the gist is the next non-blank line
    that is not itself a heading, a fence, a rule or a table row. Measured
    against every real shape: the gist is the useful half where the title is
    boilerplate (`# STATUS: dash-menus-settings` -> `Phase 0 done, stopped as
    instructed.`) and the title where it carries the verdict.
    """
    title, gist = "", ""
    lines = text.splitlines()
    i = 0
    for i, line in enumerate(lines):          # noqa: B007 -- i is used below
        if line.strip():
            title = _clean(line)
            break
    else:
        return "", ""
    in_fence = False
    for line in lines[i + 1:]:
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or _skippable(line):
            continue
        gist = _clean(line)
        if gist:
            break
    return title, gist


def said(title: str, gist: str, slug: str) -> str:
    """The one line the SAID column shows.

    The title when it carries the verdict, the gist when it is boilerplate:
    strip the slug and the words STATUS / Handoff / Handover / Lane out of
    the title, and if under 12 characters are left it said nothing the LANE
    column did not already say.
    """
    rest = title.replace(slug, " ")
    rest = BOILERPLATE.sub(" ", rest)
    rest = re.sub(r"[^0-9A-Za-z]+", " ", rest).strip()
    if len(rest) < 12 and gist:
        return gist
    return title or gist


def forks(text: str) -> tuple[int, str]:
    """(how many forks, the first one's line) for a QUESTIONS row.

    Tolerant by design: a miscount is cosmetic, and every file that has ever
    been written to this contract counts its forks differently."""
    found = [l for l in _top_level_lines(text) if FORK_RE.match(l)]
    return len(found), _clean(found[0]) if found else ""


def _top_level_lines(text: str) -> list[str]:
    """Every line outside a fenced code block. A numbered line inside a fence
    is a shell transcript, not a fork."""
    out, in_fence = [], False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    return out


# ----------------------------------------------------------------- the rows
def _row(path: Path, kind: str, state: str, stamp: str, slug: str,
         legacy: bool, cache: dict | None) -> dict:
    try:
        st = path.stat()
        mtime, size = st.st_mtime, st.st_size
    except OSError as exc:
        return {"kind": kind, "slug": slug, "state": state, "path": path,
                "mtime": 0.0, "title": path.name, "gist": "", "said": path.name,
                "stamp": stamp, "legacy": legacy, "shadowed": False,
                "forks": 0, "first": "", "error": str(exc)}
    key = str(path)
    hit = (cache or {}).get(key)
    if hit and hit["at"] == (mtime, size):
        row = dict(hit["row"])
        # A QUESTIONS row's state is read out of the TEXT, so the cached one
        # is the true one; a STATUS row's is which FOLDER it was found in,
        # which the caller knows and the cache does not.
        if kind == "status":
            row["state"] = state
        return row
    try:
        text = path.read_text(errors="replace")
    except OSError as exc:
        # KEPT AS A ROW, with the reason. A file that cannot be read is the
        # one most worth seeing: dropping it silently is how a handover goes
        # missing without anybody being told.
        row = {"kind": kind, "slug": slug, "state": state, "path": path,
               "mtime": mtime, "title": path.name, "gist": "",
               "said": "cannot read: %s" % exc, "stamp": stamp,
               "legacy": legacy, "shadowed": False, "forks": 0, "first": "",
               "error": str(exc)}
        return row
    title, gist = summarise(text)
    n, first = forks(text) if kind == "questions" else (0, "")
    line = said(title, gist, slug)
    if kind == "questions":
        state = question_state(text)
        # A QUESTIONS ROW SAYS WHAT IS BEING ASKED, not what the file is
        # called: every one of them is called "QUESTIONS - <slug>", which the
        # LANE column already says.
        line = "%d fork%s · %s" % (n, "" if n == 1 else "s", first or title)
    row = {"kind": kind, "slug": slug, "state": state, "path": path,
           "mtime": mtime, "title": title, "gist": gist,
           "said": line, "stamp": stamp, "legacy": legacy,
           "shadowed": False,
           "forks": n, "first": first, "error": ""}
    if cache is not None:
        cache[key] = {"at": (mtime, size), "row": dict(row)}
    return row


def _glob(d: Path, pattern: str) -> list[Path]:
    try:
        return sorted(d.glob(pattern))
    except OSError:
        return []


def scan(hdir, legacy_qdir=None, cache: dict | None = None) -> list[dict]:
    """Every STATUS and QUESTIONS file of one account, as rows.

    Both folders and both kinds, because the lifecycle is one thing: an entry
    launches a window, the window writes a handover, the handover asks
    questions, the questions are answered, the lane is done. A Row is a dict
    of kind, slug, state, path, mtime, title, gist, said, stamp, legacy,
    shadowed, forks, first, error.

    THE LEGACY FOLDER IS LIVE, not dead: MUXTOPUS_QUESTIONS_DIR still holds
    files from lanes on the older contract, and setup-schedules.py told them
    to write there. Those rows are tagged `legacy` and say which folder they
    came from rather than being quietly left out.
    """
    hdir = Path(hdir)
    done_dir = hdir / "done"
    rows: list[dict] = []
    seen_open: set[str] = set()

    for p in _glob(hdir, "STATUS-*.md"):
        kind, slug, stamp = slug_of(p.name)
        if not kind:
            continue
        seen_open.add(slug)
        row = _row(p, "status", "open", stamp, slug, False, cache)
        row["shadowed"] = (done_dir / status_name(slug)).exists()
        rows.append(row)
    for p in _glob(done_dir, "STATUS-*.md"):
        kind, slug, stamp = slug_of(p.name)
        if not kind:
            continue
        rows.append(_row(p, "status", "done", stamp, slug, False, cache))
    for p in _glob(hdir, "QUESTIONS-*.md") + _glob(done_dir, "QUESTIONS-*.md"):
        kind, slug, stamp = slug_of(p.name)
        if not kind:
            continue
        rows.append(_row(p, "questions", "unanswered", stamp, slug, False, cache))

    if legacy_qdir is not None:
        legacy = Path(legacy_qdir)
        try:
            same = legacy.resolve() == hdir.resolve()
        except OSError:
            same = False
        if not same:
            for p in _glob(legacy, "QUESTIONS-*.md"):
                kind, slug, stamp = slug_of(p.name)
                if not kind:
                    continue
                rows.append(_row(p, "questions", "unanswered", stamp, slug,
                                 True, cache))
    return order(rows)


def order(rows: list[dict]) -> list[dict]:
    """Unanswered questions, open, answered, done -- each newest first.

    THE ACTIONABLE END IS THE TOP, and the cursor starts there: the only row
    that is waiting on the person reading the screen is an unanswered fork.
    """
    return sorted(rows, key=lambda r: (RANK.get(r["state"], 4), -r["mtime"],
                                       r["kind"], r["slug"]))


def visible(rows: list[dict], show_done: bool, show_questions: bool) -> list[dict]:
    """The two filters (§4). `done` governs every FINISHED thing -- done
    handovers and answered questions alike -- so two switches cover four
    kinds of row without a third key."""
    out = []
    for r in rows:
        if not show_questions and r["kind"] == "questions":
            continue
        if not show_done and r["state"] in ("done", "answered"):
            continue
        out.append(r)
    return out


def hidden(rows: list[dict], show_done: bool, show_questions: bool) -> dict:
    """How many rows each filter is hiding. A filter may hide a row; it may
    never hide the FACT that the row exists, so the panel says this out loud
    even when it is showing nothing."""
    shown = {id(r) for r in visible(rows, show_done, show_questions)}
    rest = [r for r in rows if id(r) not in shown]
    return {"done": sum(1 for r in rest if r["state"] in ("done", "answered")),
            "questions": sum(1 for r in rest if r["kind"] == "questions"),
            "total": len(rest)}


def counts(rows: list[dict]) -> dict:
    """What the TAB STRIP says, whatever the filters are doing: open
    handovers and unanswered question files."""
    return {"open": sum(1 for r in rows
                        if r["kind"] == "status" and r["state"] == "open"),
            "unanswered": sum(1 for r in rows
                              if r["kind"] == "questions"
                              and r["state"] == "unanswered"),
            "done": sum(1 for r in rows
                        if r["kind"] == "status" and r["state"] == "done")}


# ================================================================== forks
# Answering one from the dashboard (§3b). The parser is deliberately
# forgiving: no lane was ever told a schema, four shapes already exist in the
# real folder, and the editor is one key away on every screen of the flow --
# because no parser will understand every lane's prose and pretending
# otherwise is how an answer lands in the wrong fork.
def fork_id(title: str) -> str:
    """Stable across an insertion, which a position is not: a fork keeps its
    id when another is added above it, so an answer written from the phone
    minutes later still lands in the fork it was read from."""
    return hashlib.sha1(title.strip().encode()).hexdigest()[:8]


# `- (a)` or `- **(a)` -- the marker STARTS a list item, which is the
# bulleted shape; anything else before it on the line is the inline one.
BULLET_BEFORE = re.compile(r"(?:^|\n)[ \t]*[-*+][ \t]*\**[ \t]*$")
# Where an INLINE option stops: the next bullet, a bold lead-in, an answer
# line or a recommendation line -- each of them a new block, not more option.
BLOCK_RE = re.compile(r"^\s*(?:\*\*|[-*+]\s|Recommend|Answer\b|Implemented\b)", re.I)


def _option_text(raw: str, bulleted: bool) -> str:
    """One option's words, and the two real shapes need opposite rules.

        - **(a) RECOMMENDED: esc cancels on reopen.**      a BULLET: the
          Why: esc means "back out" everywhere else.       option is its own
                                                           line; what follows
                                                           is argument.

        Options: (a) tabs on the arrows; (b) a top-level   INLINE: the option
        key of its own; (c) a toggle.                      wraps to the next
        Recommendation: (a) -- no network needed.          line, and ENDS at
                                                           the next block.

    Cutting the inline shape at the newline truncated `(b) a`; not cutting it
    at all gave the last option the `Recommendation:` and `**Answer:**` lines
    that follow the list. Both were measured on the real files, which is why
    there are two rules and not one.
    """
    if bulleted:
        head = raw.split("\n", 1)[0].strip() or " ".join(raw.split())
    else:
        keep = []
        for j, line in enumerate(raw.split("\n")):
            if j and (not line.strip() or BLOCK_RE.match(line)):
                break
            keep.append(line)
        head = " ".join(" ".join(keep).split())
    head = re.sub(r"\*\*|\*|`", "", head).strip()
    return head.strip(" ;,:-").strip()


def _options(body: str) -> list[dict]:
    """`(a)` `(b)` ... wherever they occur -- as bullets or inline, both of
    which exist in the real files -- taken only while the letters run in
    order from `a`, so a `(see (b) above)` aside cannot invent an option."""
    found = []
    for m in OPTION_RE.finditer(body):
        letter = m.group(1)
        if letter != chr(ord("a") + len(found)):
            continue
        found.append(m)
    opts = []
    for i, m in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(body)
        bulleted = bool(BULLET_BEFORE.search(body[:m.start()]))
        text = _option_text(body[m.end():end], bulleted)
        opts.append({"key": m.group(1), "text": text, "rec": False})
    if not opts:
        return opts
    named = REC_LINE_RE.search(body)
    for o in opts:
        if re.search(r"recommend", o["text"], re.I):
            o["rec"] = True
    if not any(o["rec"] for o in opts) and named:
        for o in opts:
            o["rec"] = (o["key"] == named.group(1))
    return opts


def parse_forks(text: str) -> list[dict]:
    """Every fork in a QUESTIONS file, answered or not.

    A Fork is a dict: `id` (stable, from the title), `title`, `span` (the
    half-open range of line numbers it occupies), `text` (the whole fork, for
    a detail panel or the phone), `options` ([{key, text, rec}]) and `answer`
    (the answer line, or "").
    """
    lines = text.splitlines()
    tops = _top_level_lines(text)
    starts = [i for i, l in enumerate(tops) if FORK_RE.match(l)]
    out = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        body = "\n".join(lines[start:end])
        title = _clean(lines[start])
        answer = next((l.strip() for l in lines[start:end] if ANSWER_RE.match(l)), "")
        out.append({"id": fork_id(title), "title": title, "span": (start, end),
                    "text": body.strip(), "options": _options(body),
                    "answer": answer})
    return out


def all_answered(forks_: list[dict]) -> bool:
    """Every fork in the file has an answer line. What the flow asks before
    it offers to mark the FILE answered."""
    return bool(forks_) and all(f.get("answer") for f in forks_)


def answer_line(answer: str, date: str, source: str = "user") -> str:
    """THE ONE PLACE this line is spelled. SOURCE says where the answer came
    from -- `user` at the dashboard, `user via telegram` from the phone --
    and whatever it says, the line still starts `**Answer (`, which is what
    OURS_RE matches and what keeps a second answer from stacking."""
    return "**Answer (%s, %s):** %s" % (source, date, answer.strip())


def write_answer(text: str, fork_id_: str, answer: str, date: str,
                 source: str = "user") -> str:
    """One fork answered, and NOTHING ELSE IN THE FILE TOUCHED.

    The line goes at the end of the fork, above the blank lines that separate
    it from the next one. Writing it again REPLACES our own line rather than
    stacking a second (idempotent per fork); somebody else's `**Answer
    taken:**` is left where it is, because it is the lane's own record and
    this is the user's.

    Returns the new text. The caller writes it atomically and only if the
    file is still the one that was parsed -- a live lane rewrites its
    QUESTIONS file whenever it likes.
    """
    forks_ = parse_forks(text)
    fork = next((f for f in forks_ if f["id"] == fork_id_), None)
    if fork is None:
        raise KeyError("no fork %s in this file" % fork_id_)
    lines = text.splitlines()
    keepends = text.endswith("\n")
    start, end = fork["span"]
    line = answer_line(answer, date, source)

    for i in range(start, min(end, len(lines))):
        if OURS_RE.match(lines[i]):
            indent = re.match(r"^\s*", lines[i]).group(0)
            lines[i] = indent + line
            return "\n".join(lines) + ("\n" if keepends else "")
    at = end
    while at > start and not lines[at - 1].strip():
        at -= 1
    lines.insert(at, line)
    return "\n".join(lines) + ("\n" if keepends else "")


def mark_answered(text: str, date: str) -> str:
    """The §2.2 marker, written straight into the file.

    handover.sh owns this for the handovers folder; the LEGACY folder is not
    its, so the dashboard writes there itself and this is the one
    implementation of what the line looks like either way.
    """
    if ANSWERED_RE.search(text):
        return text
    marker = "**ANSWERED %s** (marked from the dashboard)" % date
    lines = text.splitlines()
    at = 0
    for i, l in enumerate(lines):
        if l.startswith("#"):
            at = i + 1
            break
    while at < len(lines) and not lines[at].strip():
        at += 1
    lines.insert(at, marker)
    lines.insert(at + 1, "")
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


# ------------------------------------------------- the cheap question count
# WHAT THE MAIN FRAME MAY PAY. The `?` on a session row and the schedules
# tab's one-line pointer both want the same answer -- which lanes have an
# unanswered QUESTIONS file -- and the main frame is measured in forks per
# second (2) and milliseconds per frame (12.9). So: a glob of two folders and
# a marker test per file, at most once every REFRESH seconds, cached. No
# fork, and no second implementation of what "unanswered" means.
REFRESH = 5.0
_ASKING: dict = {"at": 0.0, "slugs": set(), "paths": []}


def asking(hdir, legacy_qdir=None, max_age: float = REFRESH) -> set[str]:
    """The slugs whose QUESTIONS file has no ANSWERED marker, both folders."""
    now = time.time()
    if now - _ASKING["at"] < max_age:
        return _ASKING["slugs"]
    dirs = [Path(hdir)]
    if legacy_qdir is not None:
        legacy = Path(legacy_qdir)
        try:
            if legacy.resolve() != Path(hdir).resolve():
                dirs.append(legacy)
        except OSError:
            dirs.append(legacy)
    slugs, paths = set(), []
    for d in dirs:
        for p in _glob(d, "QUESTIONS-*.md"):
            kind, slug, _stamp = slug_of(p.name)
            if not kind:
                continue
            try:
                if ANSWERED_RE.search(p.read_text(errors="replace")):
                    continue
            except OSError:
                continue
            slugs.add(slug)
            paths.append(p)
    _ASKING.update({"at": now, "slugs": slugs, "paths": paths})
    return slugs


def asking_paths(hdir, legacy_qdir=None, max_age: float = REFRESH) -> list:
    """The same answer as paths, for a panel that names the files."""
    asking(hdir, legacy_qdir, max_age)
    return list(_ASKING["paths"])
