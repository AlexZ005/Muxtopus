#!/usr/bin/env python3
"""The manual in docs/ is a set of Jekyll pages GitHub renders as they are,
so the things that break it break silently: a page with no front matter has
no title and drops out of the nav; a {{PLACEHOLDER}} outside a raw block is
eaten by Liquid and the sentence around it lies; a relative link to a file
that was renamed 404s. None of that fails a build. This does.

It also holds the LIST OF HEADINGS the README had before it was cut down to a
README, and asserts every one of them is still a heading somewhere in the
manual (under the same words, or the words the table below maps it to). That
is the proof that cutting the README relocated its content rather than
losing it, kept as a test so a later edit that drops a section is caught.

    python3 tests/test_manual.py
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
MANUAL_URL = "https://alexz005.github.io/Muxtopus/"

# Every heading the README had at 7e52e78 (the last commit before the cut),
# mapped to the heading it lives under now. Same words: None.
README_HEADINGS = {
    "Muxtopus": None,
    "Why this exists": None,
    "Install": None,
    "Quick start": None,
    "Adding an account": None,
    "One account, one of everything": None,
    "The dashboard": None,
    "Panels": None,
    "Handovers and questions (`s`, then `→`)": "The handovers tab (`s`, then `→`)",
    "Insights (`i`)": "The `i` view",
    "What the ledger stores, and how to forget it": None,
    "The watchdog": None,
    "Scheduled windows": None,
    "`permission-mode:`, the one setting that cannot be fixed after launch": None,
    "`watchdog: off` and `monitor: off`": None,
    "The schedule view's menu": None,
    "The options table": None,
    "The slug is the lane's name in four places": None,
    "`at: reset` is two gates": None,
    "Every pending entry says why it has not fired": None,
    "A tree of windows": "The window tree",
    "Placeholders in the body": None,
    "`model:` and `effort:`": None,
    "`after: <slug>[, <slug>…]`": None,
    "`stranded`, and why the orchestrator is a pattern rather than a process": None,
    "Handovers": "Handovers and questions",
    "Notifications, and answering from the phone": None,
    "Configuration": None,
    "After a reboot": None,
    "Steam Deck extras": None,
    "How the pieces fit": None,
    "License": None,
}

fails = []
def check(cond, msg):
    if not cond:
        fails.append(msg)

def front_matter(text: str) -> dict | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    fm = {}
    for line in text[4:end].splitlines():
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip()
    return fm

def body_of(text: str) -> str:
    end = text.find("\n---\n", 4)
    return text[end + 5:] if text.startswith("---\n") and end >= 0 else text

def liquid_safe(body: str, name: str) -> None:
    """Every {{ and every {% that is not a raw/endraw tag must sit inside a
    raw block, and the blocks must nest sanely."""
    depth = 0
    for m in re.finditer(r"\{%\s*(raw|endraw)\s*%\}|\{\{|\{%", body):
        tok = m.group(0)
        if m.group(1) == "raw":
            check(depth == 0, "%s: raw inside raw at %d" % (name, m.start()))
            depth += 1
        elif m.group(1) == "endraw":
            check(depth == 1, "%s: endraw without raw at %d" % (name, m.start()))
            depth -= 1
        else:
            check(depth == 1, "%s: %r outside a raw block at %d (Liquid would eat it)"
                  % (name, tok, m.start()))
    check(depth == 0, "%s: raw block never closed" % name)

pages = {}
headings = []
for md in sorted(DOCS.glob("*.md")):
    if md.name.startswith("plan-"):
        continue                               # design notes, excluded from the site
    text = md.read_text()
    fm = front_matter(text)
    check(fm is not None, "%s: no front matter, so no title and no nav entry" % md.name)
    if fm is None:
        continue
    check(fm.get("title"), "%s: front matter has no title" % md.name)
    check(fm.get("nav_order", "").isdigit(), "%s: nav_order missing or not a number" % md.name)
    pages[md.name] = fm
    body = body_of(text)
    liquid_safe(body, md.name)
    for line in body.splitlines():
        if line.startswith("#"):
            headings.append(line.lstrip("#").strip())
    # Relative links resolve to a file in docs/ (with or without an anchor).
    for m in re.finditer(r"\]\(([^)\s]+)\)", body):
        target = m.group(1)
        if re.match(r"[a-z]+:", target) or target.startswith("#"):
            continue
        path = target.split("#", 1)[0]
        check((DOCS / path).exists(), "%s: link to %s, which does not exist" % (md.name, target))
    # Nothing in the manual is a tour of the author's machine.
    check("/home/deck" not in text, "%s: names a real home directory" % md.name)

# A parent named by a sub-page is a page.
titles = {fm["title"] for fm in pages.values()}
for name, fm in pages.items():
    if fm.get("parent"):
        check(fm["parent"] in titles, "%s: parent %r is not a page" % (name, fm["parent"]))
        parent = next(f for f in pages.values() if f["title"] == fm["parent"])
        check(parent.get("has_children") == "true",
              "%s: parent %r needs has_children: true" % (name, fm["parent"]))

# The pages the manual's index promises.
for must in ("index.md", "install.md", "accounts.md", "dashboard.md", "schedules.md",
             "handovers.md", "watchdog.md", "notifications.md", "stats.md",
             "configuration.md", "contributing.md", "dashboard-views.md"):
    check(must in pages, "the manual has no %s" % must)

# The plans are excluded, or GitHub pages them.
cfg = (DOCS / "_config.yml").read_text()
check('"plan-*.md"' in cfg, "_config.yml no longer excludes plan-*.md")
check("remote_theme:" in cfg, "_config.yml has no remote_theme")

# Nothing the README used to say is gone.
for old, new in README_HEADINGS.items():
    want = new or old
    check(want in headings, "README heading %r is not in the manual (looked for %r)" % (old, want))

# The README says where the manual is, and so does the dashboard's help.
readme = (ROOT / "README.md").read_text()
check(MANUAL_URL in readme, "README does not link %s" % MANUAL_URL)
check(len(readme.splitlines()) < 120, "README is %d lines; the manual is for the rest"
      % len(readme.splitlines()))
help_py = (ROOT / "dashboard" / "help.py").read_text()
check(MANUAL_URL in help_py, "dashboard/help.py does not name the manual")

if fails:
    for f in fails:
        print("FAIL", f)
    print("%d failure(s)" % len(fails))
    sys.exit(1)
print("manual: %d pages, %d headings, every README heading accounted for" % (len(pages), len(headings)))
