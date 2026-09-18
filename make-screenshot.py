#!/usr/bin/env python3
"""Regenerate the README's screenshot from mocked fixtures.

    .venv/bin/python make-screenshot.py            # docs/dashboard.{svg,png}, docs/screens/
    .venv/bin/python make-screenshot.py --keep     # leave the sandbox running afterwards

NOT A PHOTOGRAPH OF ANYBODY'S MACHINE. The picture is the real dashboard --
its layout, its colours, its column widths -- drawn over a fake machine built
from tests/fixtures/screenshot/ by the same sandbox harness the golden screens
use (tests/sandbox/). The account is `work`, the repos are ~/src/acme/*, the
session ids are made up, and the story (a tree three levels deep, a lane in
every state the STATE column can show, schedules and handovers to match) is
told in that folder's README. Change the fixture, run this, commit both.

The sandbox pins its own tmux server (`tmux -L mxshot`), so nothing here can
reach the real `claude` sessions or any window you are working in; the seven
windows it opens are `sleep`s on that private server, there so the handovers
tab can say which lanes' windows are still open.

Three panels read the HOST and not the fixture -- deck (memory, cpu),
lanes (real dev servers; the sandbox account owns two throwaway ones this
script starts, and every other one is "hidden") and system -- and any home
path they leak is replaced, width-preserved. Every replacement keeps the
line exactly as wide as it was, and the script refuses to write a frame
whose width changed: the panels are box-drawn, and a replacement one
character short frays the border.

Output: docs/screens/{main,schedules,handovers}.svg (+ .png when
rsvg-convert is installed), and docs/dashboard.{svg,png}: the main view
above the handovers tab, which is the README's picture.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
SANDBOX = HERE / "tests" / "sandbox"
FIXTURES = HERE / "tests" / "fixtures" / "screenshot"
DOCS = HERE / "docs"
SCREENS = DOCS / "screens"

SB = pathlib.Path(os.environ.get("SB", "/tmp/muxshot-sandbox"))
SOCKET = "mxshot"
SESSION = "mxshot"
ACCOUNT = "work"
ROWS = int(os.environ.get("ROWS", "44"))

ANSI = re.compile(r"\x1b\[[0-9;]*m")
# @T-3600@ an epoch, @HM+5400@ a clock (HH:MM), @DATE-1800@ a stamp
# (YYYY-MM-DD HH:MM), each that many seconds from now -- so the reset the
# deck panel names, the one the schedules view computes and the `limited`
# state's own all agree whenever the picture is taken.
TIME_TOKEN = re.compile(r"@(T|HM|DATE)([+-]\d+)@")

# The seven windows tree.tsv's @1..@7 stand for, opened in this order on the
# sandbox server so the ids come out as written.
WINDOWS = ["➥checkout-refactor", "➥➥cart-api", "➥➥➥cart-qa", "➥➥cart-ui",
           "➥billing-migration", "➥➥billing-db", "➥search-index"]
# Two throwaway dev servers so the lanes table has rows that belong to the
# sandbox account: (port, cwd under the fake HOME).
SERVERS = [(5173, "src/acme/checkout"), (8000, "src/acme/billing")]


def env() -> dict[str, str]:
    e = dict(os.environ)
    e.update(SB=str(SB), SANDBOX_SOCKET=SOCKET, SANDBOX_SESSION=SESSION,
             SANDBOX_ACCOUNT=ACCOUNT, SANDBOX_FIXTURES=str(FIXTURES),
             SCRIPTS=str(HERE))
    return e


def sh(*cmd: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), env=env(), capture_output=True, text=True, **kw)


def tmux(*args: str) -> subprocess.CompletedProcess:
    return sh("tmux", "-L", SOCKET, *args)


def resolve_times() -> None:
    """@T-3600@ -> now-3600 in every fixture file, and mtimes.tsv applied."""
    now = int(time.time())

    def resolve(m: re.Match) -> str:
        at = now + int(m.group(2))
        if m.group(1) == "T":
            return str(at)
        fmt = "%H:%M" if m.group(1) == "HM" else "%Y-%m-%d %H:%M"
        return time.strftime(fmt, time.localtime(at))

    for path in SB.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        new = TIME_TOKEN.sub(resolve, text)
        if new != text:
            path.write_text(new)
    ages = SB / "mtimes.tsv"
    if ages.exists():
        for line in ages.read_text().splitlines():
            rel, _, secs = line.partition("\t")
            if rel and secs.strip().isdigit():
                os.utime(SB / rel, (now - int(secs), now - int(secs)))


def capture() -> list[str]:
    """A settled frame: two identical reads in a row (a read that lands inside
    Live's repaint comes back missing a line -- tests/sandbox/handovers.sh)."""
    last = None
    for _ in range(12):
        out = sh(str(SANDBOX / "cap.sh"), "-e").stdout
        if out == last:
            break
        last = out
        time.sleep(0.2)
    lines = (last or "").rstrip("\n").split("\n")
    while lines and not ANSI.sub("", lines[-1]).strip():
        lines.pop()
    return lines


def key(*keys: str) -> None:
    sh(str(SANDBOX / "k.sh"), *keys)
    time.sleep(0.6)


def fit(new: str, old: str) -> str:
    return new[:len(old)].ljust(len(old))


BORDER = re.compile(r"((?:\x1b\[[0-9;]*m)*[│╮╯]\s*(?:\x1b\[[0-9;]*m)*)$")


def scrub(lines: list[str]) -> list[str]:
    """Width-preserving: the sandbox HOME and any home path become `~`, and
    the characters that shortening took out are given back as spaces just
    before the line's closing border, so the text reads naturally and the
    box stays a box."""
    widths = [len(ANSI.sub("", ln)) for ln in lines]
    out = []
    for ln, width in zip(lines, widths):
        ln = ln.replace(str(SB / "home"), "~").replace(str(SB), "~")
        ln = re.sub(r"/home/[a-z0-9_-]+", "~", ln)
        deficit = width - len(ANSI.sub("", ln))
        if deficit > 0:
            m = BORDER.search(ln)
            if m:
                ln = ln[:m.start()] + " " * deficit + ln[m.start():]
            else:
                ln = ln + " " * deficit
        out.append(ln)
    bad = [(i + 1, w, len(ANSI.sub("", ln)))
           for i, (w, ln) in enumerate(zip(widths, out)) if w != len(ANSI.sub("", ln))]
    if bad:
        for i, was, now in bad[:10]:
            print("line %d changed width %d -> %d" % (i, was, now), file=sys.stderr)
        raise SystemExit("refusing to write a frayed screenshot")
    return out


def render(frames: list[list[str]], out: pathlib.Path, title: str) -> None:
    from rich.console import Console
    from rich.text import Text
    body = "\n\n".join("\n".join(f) for f in frames)
    width = max(len(ANSI.sub("", ln)) for f in frames for ln in f)
    console = Console(record=True, width=width, force_terminal=True,
                      color_system="truecolor", legacy_windows=False)
    console.print(Text.from_ansi(body), overflow="ignore", crop=False, no_wrap=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    console.save_svg(str(out), title=title)
    rows = sum(len(f) for f in frames) + len(frames) - 1
    print("wrote %s  (%d cols x %d rows)" % (out.relative_to(HERE), width, rows))
    if shutil.which("rsvg-convert"):
        png = out.with_suffix(".png")
        r = subprocess.run(["rsvg-convert", "--zoom", "1.5", "-o", str(png), str(out)],
                           capture_output=True, text=True)
        if r.returncode == 0:
            print("wrote %s" % png.relative_to(HERE))
        else:
            print("rsvg-convert failed: %s" % r.stderr.strip(), file=sys.stderr)
    else:
        print("no rsvg-convert on PATH: %s written, no PNG" % out.name, file=sys.stderr)


def main() -> int:
    keep = "--keep" in sys.argv
    try:
        import rich  # noqa: F401
    except ImportError:
        print("needs rich: run this with the dashboard venv's python", file=sys.stderr)
        return 1
    if not FIXTURES.is_dir():
        print("no fixture set at %s" % FIXTURES, file=sys.stderr)
        return 1

    servers: list[subprocess.Popen] = []
    try:
        r = sh(str(SANDBOX / "setup.sh"))
        if r.returncode != 0:
            print(r.stderr, file=sys.stderr)
            return 1
        resolve_times()

        # The two throwaway dev servers. The lanes table recognises a server
        # by its command line (core.SERVER_HINTS: a vite under
        # node_modules/.bin, `npm run dev`...), attributes it by the
        # CLAUDE_CONFIG_DIR in its environment and names it by its cwd -- so
        # each is python's http.server run through a script called
        # node_modules/.bin/vite in the fake repo, in its own process group,
        # with the sandbox account in its environment.
        for port, rel in SERVERS:
            cwd = SB / "home" / rel
            vite = cwd / "node_modules" / ".bin" / "vite"
            vite.parent.mkdir(parents=True, exist_ok=True)
            vite.write_text("import http.server, sys\n"
                            "http.server.test(HandlerClass=http.server.SimpleHTTPRequestHandler,"
                            " port=int(sys.argv[1]), bind='127.0.0.1')\n")
            e = env()
            e["CLAUDE_CONFIG_DIR"] = str(SB / "home" / (".claude-" + ACCOUNT))
            servers.append(subprocess.Popen(
                [sys.executable, str(vite), str(port)], cwd=str(cwd), env=e,
                start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

        # start.sh leaves the heartbeat faker running in the background, and
        # a captured pipe would never close while it holds it -- so no pipe.
        r = subprocess.run([str(SANDBOX / "start.sh"), str(ROWS)], env=env(),
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        if r.returncode != 0:
            print("start.sh failed (%d)" % r.returncode, file=sys.stderr)
            return 1
        for name in WINDOWS:
            tmux("new-window", "-d", "-t", SESSION, "-n", name, "sleep 3600")
        time.sleep(3.0)                          # two frames, so the tree is drawn

        main_view = scrub(capture())
        key("s")
        schedules = scrub(capture())
        key("Right")
        handovers = scrub(capture())
    finally:
        for p in servers:
            p.kill()
        if not keep:
            sh(str(SANDBOX / "stop.sh"))

    if not main_view or "claude" not in ANSI.sub("", "\n".join(main_view)):
        print("the main view did not come up; is .venv linked?", file=sys.stderr)
        return 1

    render([main_view], SCREENS / "main.svg", "muxtopus · ctrl-b 0")
    render([schedules], SCREENS / "schedules.svg", "muxtopus · s")
    render([handovers], SCREENS / "handovers.svg", "muxtopus · s, →")
    render([main_view, handovers], DOCS / "dashboard.svg", "muxtopus · ctrl-b 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
