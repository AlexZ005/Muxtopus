#!/usr/bin/env python3
"""hosts.conf, read by lib/hosts.sh and muxhosts.py alike, and the handover
sync (muxhosts.sync): the decision table, and whole syncs through a fake ssh.

    python3 tests/test_hosts.py

THE FAKE SSH maps one folder to another: the "far" side of a sync is a second
folder here, and every remote command and rsync path naming HERE is rewritten
to THERE -- so a move, an edit and a removal really travel, and a file that
should survive really does.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import muxhosts  # noqa: E402

fails = 0


def ok(cond, what):
    global fails
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        fails += 1


T = pathlib.Path(tempfile.mkdtemp(prefix="mxhosts-"))
try:
    conf = T / "hosts.conf"
    conf.write_text("""# a comment
[pc]
ssh = alice@192.0.2.10    # trailing comment
port = 22022
key = ~/.ssh/k
e2e_slots=2
[gpu-box]
ssh=bob@198.51.100.7
[bad name]
ssh = nobody@203.0.113.9
""")
    os.environ["MUXTOPUS_HOSTS"] = str(conf)
    h = muxhosts.load()
    ok(list(h) == ["pc", "gpu-box"], "two hosts; a section name with a space is not one")
    ok(h["pc"]["ssh"] == "alice@192.0.2.10", "a trailing comment is not part of the value")
    ok(h["pc"]["e2e_slots"] == "2", "no spaces around = is fine")
    ok(muxhosts.get("gpu-box", "e2e_slots", "1") == "1", "a missing key takes the default")
    argv = muxhosts.ssh_argv("pc")
    ok(argv[-1] == "alice@192.0.2.10" and "-p" in argv and argv[argv.index("-p") + 1] == "22022", "ssh argv: port and target")
    ok(os.path.expanduser("~/.ssh/k") in argv and "IdentitiesOnly=yes" in argv, "..the key, expanded, IdentitiesOnly")
    ok(muxhosts.ssh_argv("nope") is None, "an unknown host has no argv")
    # THE SHELL READER AGREES.
    def sh(expr):
        return subprocess.run(["bash", "-c", f". {ROOT}/lib/hosts.sh; {expr}"], capture_output=True, text=True,
                              env=dict(os.environ)).stdout
    ok(sh("mux_host_names").split() == ["pc", "gpu-box"], "hosts.sh: the same two names")
    for host, key in (("pc", "ssh"), ("pc", "port"), ("pc", "e2e_slots"), ("gpu-box", "ssh"), ("gpu-box", "port")):
        ok(sh(f"mux_host_get {host} {key}") == muxhosts.get(host, key), f"hosts.sh: {host}.{key} the same")
    sh_argv = sh('mux_host_ssh pc; printf "%s\\n" "${MUX_HOST_SSH[@]}"').splitlines()
    ok(sh_argv == argv, "hosts.sh: the same ssh argv")

    # THE DECISION TABLE.
    A, B, C = [1, 10], [2, 10], [3, 11]
    P = muxhosts.plan
    ok(P({"x": A}, {"x": A}, {"x": A}) == ([], [], [], []), "equal: nothing")
    ok(P({"x": B}, {"x": A}, {"x": A}) == (["x"], [], [], []), "edited here: pushed")
    ok(P({"x": A}, {"x": B}, {"x": A}) == ([], ["x"], [], []), "edited there: pulled")
    ok(P({}, {"x": A}, {"x": A}) == ([], [], [], ["x"]), "removed here: removed there")
    ok(P({"x": A}, {}, {"x": A}) == ([], [], ["x"], []), "removed there: removed here")
    ok(P({"x": B}, {"x": C}, {"x": A}) == ([], ["x"], [], []), "edited on both: the newer (there) wins")
    ok(P({}, {"x": B}, {"x": A}) == ([], ["x"], [], []), "removed here, edited there: kept (pulled)")
    ok(P({"x": A}, {}, None) == (["x"], [], [], []), "no manifest: a file only here is pushed, never removed")
    ok(P({}, {"x": A}, None) == ([], ["x"], [], []), "no manifest: a file only there is pulled, never removed")
    ok(P({"done/x": A}, {"x": A}, {"x": A}) == (["done/x"], [], [], ["x"]), "a move into done/ here travels as a move")

    # WHOLE SYNCS through the fake ssh.
    here, there = T / "here" / "handovers", T / "there" / "handovers"
    here.mkdir(parents=True)
    fake = T / "bin" / "ssh"
    fake.parent.mkdir()
    fake.write_text(f"""#!/usr/bin/env bash
while [ $# -gt 0 ]; do case "$1" in -o|-p|-i|-l) shift 2 ;; -*) shift ;; *) shift; break ;; esac; done
H='{here}'; X='{there}'
cmd="$*"; cmd="${{cmd//"$H"/"$X"}}"
exec bash -c "$cmd"
""")
    fake.chmod(0o755)
    os.environ["PATH"] = f"{fake.parent}:{os.environ['PATH']}"
    man = str(T / "state" / "manifest.json")

    def run():
        return muxhosts.sync("pc", str(here), man)

    (here / "STATUS-a.md").write_text("a1")
    (here / "done").mkdir()
    ok(run() == 0, "first sync: rc 0")
    ok((there / "STATUS-a.md").read_text() == "a1", "..a file here reaches there")
    ok(json.loads(pathlib.Path(man).read_text()).get("STATUS-a.md") is not None, "..and is in the manifest")
    (there / "STATUS-b.md").write_text("b1")
    run()
    ok((here / "STATUS-b.md").read_text() == "b1", "a lane there writes its STATUS: it arrives here")
    # handover.sh done here: a move.
    (here / "STATUS-a.md").rename(here / "done" / "STATUS-a.md")
    run()
    ok(not (there / "STATUS-a.md").exists() and (there / "done" / "STATUS-a.md").read_text() == "a1",
       "done here: moved there too, not resurrected")
    run()
    ok(not (here / "STATUS-a.md").exists(), "..and stays moved on the next pass")
    # handover.sh done there.
    (there / "done").mkdir(exist_ok=True)
    (there / "STATUS-b.md").rename(there / "done" / "STATUS-b.md")
    run()
    ok(not (here / "STATUS-b.md").exists() and (here / "done" / "STATUS-b.md").exists(), "done there: moved here too")
    # An answer here, an edit there.
    (here / "QUESTIONS-c.md").write_text("q?")
    run()
    time.sleep(1.1)
    (here / "QUESTIONS-c.md").write_text("q?\nANSWERED: yes")
    run()
    ok("ANSWERED" in (there / "QUESTIONS-c.md").read_text(), "an answer written here reaches the lane there")
    # The manifest lost: nothing is removed anywhere.
    os.remove(man)
    (there / "STATUS-d.md").write_text("d")
    run()
    ok((here / "done" / "STATUS-a.md").exists() and (there / "done" / "STATUS-a.md").exists()
       and (here / "STATUS-d.md").exists(), "a lost manifest: only copies, nothing removed")
    ok(muxhosts.sync("nope", str(here), man) == 2, "an unknown host: rc 2")

    # THE TOKEN FILE: two hosts' ledgers, by day, host and lane.
    import muxstats
    cols = muxstats.LEDGER_COLS
    def ledger(path, rows):
        lines = ["\t".join(cols)]
        for r in rows:
            d = {c: "0" for c in cols}
            d.update({"hours": "", "tool_mix": "", "project": "-", "session": "s"})
            d.update({k: str(v) for k, v in r.items()})
            lines.append("\t".join(d[c] for c in cols))
        path.write_text("\n".join(lines) + "\n")
    la, lb = T / "a.tsv", T / "b.tsv"
    ledger(la, [{"day": "2026-10-23", "lane": "57-clips", "model": "m1", "in": 10, "out": 5, "cache_w5m": 1, "cache_w1h": 2, "cache_read": 100},
                {"day": "2026-10-23", "lane": "57-clips", "model": "m2", "side": 1, "in": 1, "out": 1, "cache_read": 7},
                {"day": "2026-10-22", "lane": "", "model": "m1", "in": 3},
                {"day": "2026-08-25", "lane": "", "model": "m1", "in": 999, "coarse": 1}])
    ledger(lb, [{"day": "2026-10-23", "lane": "mux-pc-host", "model": "m1", "out": 4, "cache_read": 40}])
    out = T / "tbl.jsonl"
    n = muxstats.tokens_by_lane([("deck", la), ("pc", lb)], out)
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    ok(n == 3 and len(rows) == 3, "three rows: one per day, host and lane; a backfilled day left out")
    ok(rows[1] == {"date": "2026-10-23", "host": "deck", "slug": "57-clips", "roadmap": "57", "spent": 20, "cached": 107},
       "spent is in + out + cache writes, cached is cache reads, over models and subagents")
    ok(rows[0]["slug"] == "-" and rows[0]["roadmap"] == "", "a session that is no lane is slug -, no roadmap")
    ok(rows[2]["host"] == "pc" and rows[2]["roadmap"] == "", "the other host's lane, a slug with no number")
finally:
    shutil.rmtree(T, ignore_errors=True)

print("all passed" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
