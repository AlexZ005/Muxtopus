#!/usr/bin/env python3
"""Every tmux call names its socket, and nothing anywhere kills a server it
did not name.

    python3 tests/test_tmux_guard.py        (no dependency beyond python3)

THE ACCIDENT THIS FORBIDS. 2026-09-19 09:04: a session in a lane window ran
`TMUX_TMPDIR=$SB/sock tmux kill-server` to clean a test sandbox. Inside a
pane $TMUX is set, and tmux takes its socket from $TMUX whenever neither -S
nor -L is given -- TMUX_TMPDIR is ignored. It killed the real server: the
dashboard, every lane window and five Claude sessions. So (docs/plan-restore.md
§3) profile.sh's mux_tmux passes -L/-S on every call, and this test holds
two lines:

  1. EVERYWHERE (every .sh, .py, muxtopus and every test): a `tmux
     kill-server` or `tmux kill-session` in command position must be
     `mux_tmux ...` or `tmux -L ... ` / `tmux -S ...`. A wrapper script on
     PATH does not count: the socket has to be in the line a reader sees.
  2. IN THE FILES THAT DRIVE THE REAL SERVER (muxtopus, profile.sh, the
     watchdog, the usage probe, the test sandbox): no bare `tmux <verb>` in
     command position at all.

Command position is what a shell would execute: line start, after `$(`,
`<(`, `;`, `&&`, `||`, `!`, `then`, `else`, `do`, or inside a bash -c
string. Comments and the words "tmux session" in a log line are not.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FAILS = 0

STRICT = [ROOT / "muxtopus", ROOT / "profile.sh", ROOT / "claude-watchdog.sh",
          ROOT / "claude-usage.sh"] + sorted((ROOT / "tests" / "sandbox").glob("*.sh"))
EVERY = sorted(set(
    [p for p in ROOT.glob("*.sh")] + [ROOT / "muxtopus"] +
    list(ROOT.glob("*.py")) + list((ROOT / "dashboard").rglob("*.py")) +
    list((ROOT / "tests").rglob("*.sh")) + list((ROOT / "tests").rglob("*.py")) +
    list((ROOT / "tests" / "sandbox" / "bin").iterdir())))

VERBS = ("kill-server|kill-session|kill-window|capture-pane|list-windows|list-panes|"
         "has-session|send-keys|new-window|new-session|load-buffer|paste-buffer|"
         "display-message|select-window|set-environment|respawn-pane|switch-client|"
         "attach-session|detach-client|source-file|list-sessions|rename-window|"
         "kill-pane|split-window|list-clients")
# A tmux in command position: what precedes it is a place a command starts.
POS = r'(?:^|\$\(|<\(|[;|&!]\s*|\bthen\s+|\belse\s+|\bdo\s+|-c\s+["\x27]\s*|=\s*|\b[A-Z_]+=\S*\s+)\s*'
KILL = re.compile(POS + r'(?:\S*/)?tmux["\x27]?\s+(kill-server|kill-session)\b')
BARE = re.compile(POS + r'tmux\s+(' + VERBS + r')\b')
# The python side: subprocess argv lists.
PY_KILL = re.compile(r'\[\s*["\']tmux["\']\s*,\s*["\'](kill-server|kill-session)["\']')


def code_lines(path):
    """(lineno, text) for every line that is not a comment."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return []
    out = []
    for i, line in enumerate(text.split("\n"), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.append((i, line))
    return out


def report(what, hits):
    global FAILS
    if hits:
        FAILS += len(hits)
        print("  FAIL %s" % what)
        for h in hits:
            print("         %s" % h)
    else:
        print("  ok   %s" % what)


hits = []
for p in EVERY:
    if p == ROOT / "tests" / "test_tmux_guard.py":
        continue
    for n, line in code_lines(p):
        if KILL.search(line) or PY_KILL.search(line):
            hits.append("%s:%d: %s" % (p.relative_to(ROOT), n, line.strip()[:100]))
report("no bare `tmux kill-server` / `kill-session` anywhere (mux_tmux, -L or -S)", hits)

hits = []
for p in STRICT:
    for n, line in code_lines(p):
        if BARE.search(line):
            hits.append("%s:%d: %s" % (p.relative_to(ROOT), n, line.strip()[:100]))
report("muxtopus, profile.sh, the watchdog, the probe and the sandbox: every tmux goes through mux_tmux", hits)

# A SANDBOX THAT WRAPS tmux MUST ALSO NAME ITS SOCKET TO THE SCRIPTS. mux_tmux
# appends -L on every call and tmux takes the LAST -L, so a wrapper of
# `exec tmux -L mxfoo "$@"` on its own is overridden by the helper's
# `-L default` -- and the watchdog under test reaches the real server.
hits = []
for p in sorted((ROOT / "tests").rglob("*.sh")):
    text = p.read_text(errors="replace")
    if "bin/tmux" in text and "MUXTOPUS_TMUX_SOCKET" not in text \
            and "/env.sh\"" not in text and "notify_sandbox.sh" not in text:
        hits.append(str(p.relative_to(ROOT)))
report("every sandbox that wraps tmux also exports MUXTOPUS_TMUX_SOCKET", hits)

# The helper itself is the one place `tmux` is spelled with its socket.
prof = (ROOT / "profile.sh").read_text()
report("profile.sh defines mux_tmux with the socket arguments",
       [] if re.search(r'^mux_tmux\(\) \{ command tmux "\$\{MUX_TMUX_SOCK\[@\]\}" "\$@"; \}', prof, re.M)
       else ["mux_tmux() not found, or it no longer passes ${MUX_TMUX_SOCK[@]}"])

print()
if FAILS:
    print("%d FAILED" % FAILS)
    sys.exit(1)
print("tmux guard: clean")
