#!/usr/bin/env python3
"""muxtelegram -- the phone's half of the watchdog's notifications. Stdlib only.

    python3 muxtelegram.py questions [--profile P]
        every UNANSWERED QUESTIONS file of one account, both folders, as JSON
        lines: {path, slug, legacy, title, forks: [{id, title, text}]}.
        The watchdog calls it only when a QUESTIONS file's (name, mtime, size)
        changed, and decides from the fork ids what is new.

docs/plan-notify-telegram.md §1-§3b. The reading of a QUESTIONS file belongs
to muxhandovers.py (docs/plan-handover-visibility.md §2.2, §3b); until that
module lands this carries the §2.2 rules in their tolerant minimum, and it
prefers muxhandovers the moment it is importable.
"""
import hashlib
import json
import os
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import muxconfig  # noqa: E402

try:                                    # handover-visibility's reader, when it exists
    import muxhandovers                 # type: ignore  # noqa: E402
except ImportError:                     # pragma: no cover - depends on the tree
    muxhandovers = None

# ------------------------------------------------------------ questions
# §2.2: a file is answered iff some line matches ^\W*ANSWERED\b; a fork starts
# at a `## ` heading or a top-level `N.` item; a fork is answered when one of
# its lines starts `**Answer`.
ANSWERED_RE = re.compile(r"^\W*ANSWERED\b", re.M)
FORK_RE = re.compile(r"^\s*(\d+\.|##\s)")
ANSWER_RE = re.compile(r"^\s*\*\*Answer")
FORK_TEXT_MAX = 1500


def fork_id(title: str) -> str:
    return hashlib.sha1(title.strip().encode()).hexdigest()[:8]


def _clean_title(line: str) -> str:
    return re.sub(r"^[#*\s]+|[*\s]+$", "", line).strip()


def forks_fallback(text: str) -> list[dict]:
    forks, cur = [], None
    for line in text.splitlines():
        if FORK_RE.match(line):
            cur = {"title": _clean_title(line), "lines": [line], "answered": False}
            forks.append(cur)
        elif cur is not None:
            cur["lines"].append(line)
            if ANSWER_RE.match(line):
                cur["answered"] = True
    return [{"id": fork_id(f["title"]), "title": f["title"],
             "text": "\n".join(f["lines"]).strip()[:FORK_TEXT_MAX]}
            for f in forks if not f["answered"]]


def _get(obj, name, default=None):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def unanswered_forks(text: str) -> list[dict]:
    """muxhandovers.parse_forks when it exists, else the fallback above."""
    parse = getattr(muxhandovers, "parse_forks", None) if muxhandovers else None
    if parse is None:
        return forks_fallback(text)
    out = []
    for f in parse(text):
        if _get(f, "answer"):
            continue
        title = str(_get(f, "title", "") or "")
        fid = _get(f, "id")
        out.append({"id": str(fid) if fid is not None else fork_id(title), "title": title,
                    "text": str(_get(f, "text", "") or title)[:FORK_TEXT_MAX]})
    return out


def question_dirs(profile: str) -> list[tuple[pathlib.Path, bool]]:
    hdir = muxconfig.mux_dir("handovers", profile)
    legacy = pathlib.Path(muxconfig.knob(
        "MUXTOPUS_QUESTIONS_DIR", profile,
        str(muxconfig.HOME / ".code" / "theprototype-app" / "core" / "plans")))
    out = [(hdir, False)]
    if legacy.resolve() != hdir.resolve():
        out.append((legacy, True))
    return out


def unanswered_files(profile: str) -> list[dict]:
    rows = []
    for d, legacy in question_dirs(profile):
        try:
            files = sorted(d.glob("QUESTIONS-*.md"))
        except OSError:
            continue
        for p in files:
            try:
                text = p.read_text(errors="replace")
            except OSError:
                continue
            if ANSWERED_RE.search(text):
                continue
            title = next((_clean_title(l) for l in text.splitlines() if l.strip()), p.name)
            rows.append({"path": str(p), "slug": p.name[len("QUESTIONS-"):-len(".md")],
                         "legacy": legacy, "title": title,
                         "forks": unanswered_forks(text)})
    return rows


# ------------------------------------------------------------------ main
def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    profile = ""
    if "--profile" in rest:
        i = rest.index("--profile")
        profile = rest[i + 1] if i + 1 < len(rest) else ""
        del rest[i:i + 2]
    if cmd == "questions":
        for row in unanswered_files(profile):
            print(json.dumps(row, ensure_ascii=False))
        return 0
    print("unknown command: %s" % cmd, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
