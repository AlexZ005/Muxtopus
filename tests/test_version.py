#!/usr/bin/env python3
"""VERSION is the one place the release number is written down.

Everything that shows a version reads that file at run time: the dashboard's
header (dashboard/app.py), the bash renderer (deck-status.sh), `muxtopus
--version`, and release.sh, which stamps it into the tarball's name and the
installer it builds. So a release is one edit to one file, and this test is
what keeps it that way: a literal copy of the number anywhere else is a
second source of truth waiting to disagree with the first.

    python3 tests/test_version.py
"""
import os
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
fails = 0


def ok(cond, what):
    global fails
    if cond:
        print("ok   " + what)
    else:
        fails += 1
        print("FAIL " + what)


version = (ROOT / "VERSION").read_text().strip()
ok(re.fullmatch(r"\d+\.\d+\.\d+", version) is not None,
   "VERSION is X.Y.Z: %r" % version)

# `muxtopus --version` reads the file beside it. MUXTOPUS_CONFIG points
# nowhere, or a real config's MUXTOPUS_DIR would answer for another checkout.
with tempfile.TemporaryDirectory() as home:
    env = dict(os.environ, HOME=home, MUXTOPUS_CONFIG=os.path.join(home, "none"))
    for flag in ("--version", "-V"):
        out = subprocess.run(["bash", str(ROOT / "muxtopus"), flag], env=env,
                             capture_output=True, text=True, timeout=20)
        ok(out.stdout.strip() == version, "muxtopus %s prints %s: %r"
           % (flag, version, out.stdout.strip()))

# No second copy. The CHANGELOG names every version ever released, and that is
# history, not a source; the screenshots are pictures of a dashboard that read
# VERSION when they were taken.
EXEMPT = {"VERSION", "CHANGELOG.md"}
EXEMPT_PREFIX = ("tests/fixtures/", "docs/screens/", "docs/dashboard.")
files = subprocess.run(["git", "-C", str(ROOT), "ls-files"],
                       capture_output=True, text=True).stdout.split()
pat = re.compile(r"(?<![\d.])v?" + re.escape(version) + r"(?![\d.])")
stray = []
for f in files:
    if f in EXEMPT or f.startswith(EXEMPT_PREFIX):
        continue
    try:
        text = (ROOT / f).read_text(errors="strict")
    except (UnicodeDecodeError, OSError):
        continue
    for n, line in enumerate(text.splitlines(), 1):
        if pat.search(line):
            stray.append("%s:%d" % (f, n))
ok(not stray, "no file but VERSION states %s: %s" % (version, stray or "none"))

changelog = ROOT / "CHANGELOG.md"
if changelog.exists():
    m = re.search(r"^## \[?v?(\d+\.\d+\.\d+)", changelog.read_text(), re.M)
    ok(m is not None and m.group(1) == version,
       "the newest CHANGELOG entry is VERSION: %s" % (m and m.group(1)))

print("%d failed" % fails if fails else "all passed")
sys.exit(1 if fails else 0)
