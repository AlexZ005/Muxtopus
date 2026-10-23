#!/usr/bin/env python3
"""profile.sh's key list survives a hand edit: a comment on a key's line, a
comment line, a blank line. Every script sources profile.sh, so one stray
`#` there used to take the watchdog, e2e-slot and handover.sh down together.

    python3 tests/test_profile_keys.py
"""
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
fails = 0


def ok(cond, what):
    global fails
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        fails += 1


src = (ROOT / "profile.sh").read_text()
ok("\nWATCHDOG_REPORT_E2E_MIN=300\n" in src, "the key this test edits is in the list")
edited = src.replace("\nWATCHDOG_REPORT_E2E_MIN=300\n",
                     "\nWATCHDOG_REPORT_E2E_MIN=600   # 300 normally; raised until a fix ships (a-lane)\n"
                     "# a comment line of its own\n\n", 1)
with tempfile.TemporaryDirectory() as d:
    p = pathlib.Path(d) / "profile.sh"
    p.write_text(edited)
    (pathlib.Path(d) / "lib").mkdir()
    env = dict(os.environ, HOME=d, MUXTOPUS_CONFIG=os.path.join(d, "none"))
    env.pop("CLAUDE_CONFIG_DIR", None)
    r = subprocess.run(["bash", "-c", 'set -u; . "$1"; printf "%s|%s|%s\\n" "${MUX_SUFFIX-UNSET}" "$WATCHDOG_REPORT_E2E_MIN" '
                        '"$(printf "%s\\n" "$MUX_CONFIG_KEYS" | grep -c "=")"', "_", str(p)],
                       capture_output=True, text=True, env=env)
    out = r.stdout.strip().split("|")
    ok(r.returncode == 0, "sourcing it under set -u succeeds (rc %d)" % r.returncode)
    ok(r.stderr.strip() == "", "and says nothing on stderr: %r" % r.stderr.strip()[:200])
    ok(len(out) == 3 and out[0] == "", "MUX_SUFFIX is set (the default account's empty suffix)")
    ok(len(out) == 3 and out[1] == "600", "the edited default is the one in effect")
    n_src = sum(1 for l in src.split('MUX_CONFIG_KEYS="', 1)[1].split('"', 1)[0].splitlines() if "=" in l)
    ok(len(out) == 3 and out[2] == str(n_src), "every key is still a key, and no comment word became one (%s)" % out[2:])

print("all passed" if not fails else "%d FAILED" % fails)
sys.exit(1 if fails else 0)
