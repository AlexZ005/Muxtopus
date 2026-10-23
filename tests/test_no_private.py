#!/usr/bin/env python3
"""Nothing of one machine's network or home folder is in the repository.

muxtopus is published, and it grew up on one person's machines: the first
remote e2e slot shipped with that LAN's addresses in its manual and its
examples, and older files named the author's home folder. Hosts now live in
~/.config/muxtopus/hosts.conf, which is never tracked (lib/hosts.sh), and
this test keeps the rest honest: every tracked text file is searched for

  - a 192.168.x.y address (examples use the documentation ranges of RFC 5737:
    192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24 -- those pass),
  - a MAC address (six colon- or dash-separated hex pairs),
  - the author's home folder.

THE WORDS ONLY YOU KNOW. A machine's own names -- a server's, a Windows
user's, a drive folder -- cannot be listed here without publishing them, so
the test also reads ~/.config/muxtopus/private-words (MUXTOPUS_PRIVATE_WORDS
moves it; one word per line, # comments, matched without regard to case)
when it exists. CI has none; the author's machine does.

CHANGELOG.md is searched too. Git history is not: old tags keep the old text,
and rewriting published history is a decision for a person, not a test.

    python3 tests/test_no_private.py
"""
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
# Built from pieces, so this file does not match itself.
PATTERNS = [
    ("a 192.168 address", re.compile(r"\b192\." r"168\.\d{1,3}\.\d{1,3}\b")),
    ("a MAC address", re.compile(r"\b(?:[0-9A-Fa-f]{2}([:-]))(?:[0-9A-Fa-f]{2}\1){4}[0-9A-Fa-f]{2}\b")),
    ("the author's home folder", re.compile(r"/home/" r"deck\b")),
]
fails = 0

WORDS_FILE = pathlib.Path(os.environ.get("MUXTOPUS_PRIVATE_WORDS")
                          or pathlib.Path(os.environ.get("XDG_CONFIG_HOME") or pathlib.Path.home() / ".config")
                          / "muxtopus" / "private-words")
try:
    words = [w.split("#", 1)[0].strip() for w in WORDS_FILE.read_text(encoding="utf-8").splitlines()]
    words = [w for w in words if w]
except OSError:
    words = []
if words:
    PATTERNS.append(("a word from %s" % WORDS_FILE.name, re.compile("|".join(re.escape(w) for w in words), re.I)))


def tracked():
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=True).stdout
        return [ROOT / p for p in out.decode().split("\0") if p]
    except (OSError, subprocess.CalledProcessError):
        # A tarball has no .git: every file under the root, then.
        return [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts and ".venv" not in p.parts]


files = tracked()
for path in files:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue  # a picture, or a file a test deleted
    for n, line in enumerate(text.splitlines(), 1):
        for what, rx in PATTERNS:
            if rx.search(line):
                fails += 1
                print("FAIL %s:%d: %s: %s" % (path.relative_to(ROOT), n, what, line.strip()[:120]))

# The test has to be able to fail: each pattern catches its own example, and
# the documentation ranges are not caught.
for what, rx in PATTERNS[:3]:
    sample = {"a 192.168 address": "ssh lanes@192." "168.1.20", "a MAC address": "mac 0a:1b:2c" ":3d:4e:5f",
              "the author's home folder": "cd /home/" "deck/code"}[what]
    if not rx.search(sample):
        fails += 1
        print("FAIL the pattern for %s misses %r" % (what, sample))
for doc in ("192.0.2.10", "198.51.100.7", "203.0.113.5", "aa:bb", "12:34:56", "sha256:0a1b2c3d4e5f"):
    if any(rx.search(doc) for _, rx in PATTERNS[:3]):
        fails += 1
        print("FAIL %r is caught, and it should not be" % doc)

print("%d files searched%s; %s" % (len(files), ", %d private words" % len(words) if words else "",
                                   "clean" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
