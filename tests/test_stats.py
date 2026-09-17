#!/usr/bin/env python3
"""muxstats -- the ledger, against synthetic transcripts with the real shape.

Run it:  python3 tests/test_stats.py     (no pytest, no dependency)

Every expected number below is computed BY HAND from
tests/fixtures/transcripts/make_fixtures.py, not by running the code under
test and pasting what it printed.
"""
import os
import pathlib
import shutil
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ["TZ"] = "UTC"
time.tzset()

import muxstats  # noqa: E402

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "transcripts"
sys.path.insert(0, str(FIX))
import make_fixtures  # noqa: E402

A, B = make_fixtures.A, make_fixtures.B
PROJ = "projects/" + make_fixtures.PROJ
NOW = 1788400000

fails = []


def check(cond, what):
    print(("ok    " if cond else "FAIL  ") + what)
    if not cond:
        fails.append(what)


def tree_copy(tmp: pathlib.Path, name: str) -> pathlib.Path:
    """The fixture account, copied so a test can grow, cut or delete files.
    mtimes are pinned: A before B, as a resume would leave them."""
    dst = tmp / name
    shutil.copytree(FIX / "claude", dst)
    base = 1788250000
    for i, rel in enumerate(["%s/%s/subagents/agent-a0000000000000001.jsonl" % (PROJ, A),
                             "%s/%s.jsonl" % (PROJ, A), "%s/%s.jsonl" % (PROJ, B)]):
        os.utime(dst / rel, (base + i, base + i))
    return dst


def rows_by(state, **match):
    return [r for r in muxstats.load_ledger(state)
            if all(r[k] == v for k, v in match.items())]


def state_files(state: pathlib.Path) -> dict:
    return {p.relative_to(state).as_posix(): p.read_bytes()
            for p in sorted(state.rglob("*")) if p.is_file()}


def test_fixture_is_generated():
    for rel, text in make_fixtures.build().items():
        p = FIX / "claude" / rel
        check(p.is_file() and p.read_text() == text,
              "fixture %s is what make_fixtures.py writes" % rel.rsplit("/", 1)[-1])


def test_ledger(tmp):
    cfg = tree_copy(tmp, "ledger")
    st = tmp / "ledger-state"
    rep = muxstats.collect(cfg, st, NOW, wd_dir=tmp / "no-wd")

    # Session A, main, opus. Three messages written over 1, 3 and 9 lines.
    (o,) = rows_by(st, session=A, model="claude-opus-5", side=0) or [None]
    check(o is not None, "one row for A / opus / main")
    if o:
        check(o["requests"] == 3, "a message over 1, 3 and 9 lines is 3 requests (got %d)" % o["requests"])
        check((o["in"], o["out"], o["cache_read"]) == (16, 1050, 6000),
              "in/out/cache_read = 10+5+1, 100+50+900, 1000+2000+3000")
        check((o["cache_w5m"], o["cache_w1h"]) == (300, 300), "5m / 1h cache writes split")
        check(o["thinking"] == 40, "thinking tokens from output_tokens_details")
        check((o["ctx_peak"], o["ctx_sum"], o["ctx_n"]) == (3101, 6616, 3),
              "ctx = in + read + write per request: peak 3101, sum 1510+2005+3101")
        check(o["tools"] == 10 and o["tool_mix"] == "Bash=5;Read=5",
              "tool calls counted per block, names only (%r)" % o["tool_mix"])
        check(o["web"] == 3, "web searches + fetches")
        check((o["turns"], o["active_s"], o["compactions"]) == (1, 61, 1),
              "a turn of 61.4s -> 61 active seconds; one compaction")
        check(o["project"] == "/home/user/proj/alpha" and o["lane"] == "",
              "project is the cwd; no lane without a tree")
        check((o["first_ts"], o["last_ts"]) == (1788256805, 1788262200), "first / last instant")

    (s,) = rows_by(st, session=A, side=1) or [None]
    check(s is not None and s["model"] == "claude-haiku-4-5-20251001",
          "a subagent file is side=1, under its PARENT session")
    if s:
        check((s["requests"], s["in"], s["out"], s["cache_read"], s["cache_w5m"]) == (2, 22, 33, 440, 50),
              "subagent: 2 requests, the one split over 2 lines counted once")

    (b,) = rows_by(st, session=B) or [None]
    check(b is not None and b["model"] == "claude-sonnet-5" and b["day"] == "2026-09-02",
          "the resumed session B has ONE row: its own new message")
    if b:
        check((b["requests"], b["in"], b["turns"], b["active_s"]) == (1, 3, 1, 10),
              "the messages and turn B copied from A are not counted again")
    check(rep.copies == 5, "5 copied lines recognised (1 + 3 message lines, 1 turn), got %d" % rep.copies)
    check(rep.bad_lines == 1, "a line that is not JSON is skipped, not fatal")

    real = [r for r in muxstats.load_ledger(st) if not r["coarse"]]
    total = sum(r["in"] + r["out"] + r["cache_read"] + r["cache_w5m"] + r["cache_w1h"] for r in real)
    check(total == 16 + 1050 + 6000 + 600 + 22 + 33 + 440 + 50 + 3 + 30 + 500 + 60,
          "ledger total tokens = the hand sum (%d)" % total)
    naive = naive_sum(cfg)
    check(naive > total * 2,
          "a naive per-line sum over the same files is %.2fx the ledger" % (naive / total))

    lim = (st / "limits.tsv").read_text().splitlines()
    check(lim[1:] == ["five_hour\t1788274800\t1788264000\t1788264300"],
          "two refusals for one 5h window are one limit hit, first and last kept")

    # Coarse backfill: days before the oldest transcript only, flagged.
    coarse = [r for r in muxstats.load_ledger(st) if r["coarse"]]
    check(sorted((r["day"], r["model"], r["in"]) for r in coarse) == [
        ("2026-08-30", "claude-opus-5", 123456), ("2026-08-31", "claude-opus-5", 1000),
        ("2026-08-31", "claude-sonnet-5", 2000)],
          "coarse rows for 08-30 and 08-31; 09-01 overlaps a transcript and is skipped")
    check(muxstats.load_meta(st).get("since") == "2026-08-30", "collecting since the oldest day")

    # The privacy promise, checked on every byte this wrote.
    leaked = [n for n, data in state_files(st).items()
              if b"synthetic" in data or b"msg_fixture" in data or b"toolu" in data]
    check(not leaked, "no content, message id or tool input in any state file %s" % leaked)
    return cfg, st


def naive_sum(cfg):
    import json
    n = 0
    for p in (cfg / "projects").rglob("*.jsonl"):
        for line in p.read_text().splitlines():
            try:
                u = json.loads(line)["message"]["usage"]
            except (ValueError, KeyError, TypeError):
                continue
            n += sum(u.get(k, 0) for k in ("input_tokens", "output_tokens",
                                           "cache_read_input_tokens",
                                           "cache_creation_input_tokens"))
    return n


def test_idempotent_and_incremental(tmp, cfg, st):
    before = state_files(st)
    rep = muxstats.collect(cfg, st, NOW, wd_dir=tmp / "no-wd")
    check(state_files(st) == before, "collect twice -> every state file byte-identical")
    check(rep.files_read == 0 and rep.requests == 0, "the second collect reads nothing")

    # The last line was cut mid-write: its bytes were left for later. Finish it.
    a = cfg / ("%s/%s.jsonl" % (PROJ, A))
    whole = make_fixtures.message(A, "2026-09-01T13:00:00.000Z", "claude-opus-5",
                                  "msg_fixture_0004", "req_fixture_0004",
                                  make_fixtures.usage(7, 70, 700, 0, 0), ["text"])[0]
    import json
    full = json.dumps(whole, separators=(",", ":"))
    text = a.read_text()
    check(full.startswith(text.rsplit("\n", 1)[1]), "(the fixture's last line is a prefix of a record)")
    with open(a, "a") as fh:
        fh.write(full[len(text.rsplit("\n", 1)[1]):] + "\n")
    muxstats.collect(cfg, st, NOW, wd_dir=tmp / "no-wd")
    (o,) = rows_by(st, session=A, model="claude-opus-5", side=0)
    check((o["requests"], o["in"], o["out"]) == (4, 23, 1120),
          "a line finished after a collect is counted once, whole (req %d)" % o["requests"])


def test_shrink_and_replace(tmp):
    cfg = tree_copy(tmp, "shrink")
    st = tmp / "shrink-state"
    muxstats.collect(cfg, st, NOW)
    a = cfg / ("%s/%s.jsonl" % (PROJ, A))

    # Replaced with the same bytes under a new inode: re-read, not doubled.
    before = (st / "ledger.tsv").read_bytes()
    tmpf = a.with_name("x.tmp")
    tmpf.write_bytes(a.read_bytes())
    os.utime(tmpf, (a.stat().st_atime, a.stat().st_mtime))
    os.replace(tmpf, a)
    rep = muxstats.collect(cfg, st, NOW)
    check(rep.sessions_reset == 1, "a new inode resets that session")
    check((st / "ledger.tsv").read_bytes() == before, "...and the ledger is unchanged, not doubled")

    # Shrunk: everything from message 3 on is gone. A's rows are REPLACED.
    lines = a.read_text().splitlines(keepends=True)
    keep = [ln for ln in lines if "msg_fixture_0003" not in ln and "compact_boundary" not in ln
            and "rate_limit" not in ln][:-1]
    a.write_text("".join(keep))
    os.utime(a, (1788250001, 1788250001))
    muxstats.collect(cfg, st, NOW)
    (o,) = rows_by(st, session=A, model="claude-opus-5", side=0)
    check((o["requests"], o["in"], o["compactions"]) == (2, 15, 0),
          "a shrunken file's day-rows are replaced, not added (req %d)" % o["requests"])
    check(len(rows_by(st, session=A, side=1)) == 1 and rows_by(st, session=A, side=1)[0]["requests"] == 2,
          "its subagent rows are re-read with it, not lost or doubled")

    fresh = tmp / "shrink-fresh"
    cfg2 = tree_copy(tmp, "shrink2")
    (cfg2 / ("%s/%s.jsonl" % (PROJ, A))).write_text("".join(keep))
    # Same mtimes as the other copy: A before B, so A claims what B copied.
    os.utime(cfg2 / ("%s/%s.jsonl" % (PROJ, A)), (1788250001, 1788250001))
    muxstats.collect(cfg2, fresh, NOW)
    check((st / "ledger.tsv").read_text() == (fresh / "ledger.tsv").read_text(),
          "after the shrink the ledger equals a fresh collect of the shrunken files")

    # Claude Code deletes B: its row stays, its offset goes.
    (cfg / ("%s/%s.jsonl" % (PROJ, B))).unlink()
    muxstats.collect(cfg, st, NOW)
    check(len(rows_by(st, session=B)) == 1, "a deleted transcript keeps its ledger rows")
    check(B not in (st / "offsets.tsv").read_text(), "...and loses its offset")

    # The backfill happened once: a changed stats-cache.json is not re-read.
    (cfg / "stats-cache.json").write_text('{"dailyModelTokens":[{"date":"2026-08-01","tokensByModel":{"x":5}}]}')
    muxstats.collect(cfg, st, NOW)
    check(not rows_by(st, day="2026-08-01"), "coarse backfill runs once, not every collect")


def test_lanes(tmp):
    cfg = tree_copy(tmp, "lanes")
    wd = tmp / "lanes-wd"
    wd.mkdir()
    (wd / "status.tsv").write_text(
        "SESSION\tWINDOW\tPANE\tVER\n%s\t➥alpha\t%%12\t2.1.274\n%s\tplain\t%%13\t2.1.274\n" % (A, B))
    (wd / "tree.tsv").write_text(
        "old-lane\t\t@12\t%12\t1788000000\told.md\n"
        "lane-alpha\tparent\t@12\t%12\t1788250000\tlane-alpha.md\n")
    st = tmp / "lanes-state"
    muxstats.collect(cfg, st, NOW, wd_dir=wd)
    check({r["lane"] for r in rows_by(st, session=A)} == {"lane-alpha"},
          "session -> pane -> tree slug, the latest launch in a pane wins (main and subagent)")
    check(rows_by(st, session=B)[0]["lane"] == "", "a plain window has no lane")
    (wd / "status.tsv").write_text("SESSION\tWINDOW\tPANE\tVER\n")
    (cfg / ("%s/%s.jsonl" % (PROJ, A))).open("a").write("\n")
    muxstats.collect(cfg, st, NOW, wd_dir=wd)
    check({r["lane"] for r in rows_by(st, session=A)} == {"lane-alpha"},
          "a lane, once known, survives its window closing")


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="muxstats-test-"))
    try:
        test_fixture_is_generated()
        cfg, st = test_ledger(tmp)
        test_idempotent_and_incremental(tmp, cfg, st)
        test_shrink_and_replace(tmp)
        test_lanes(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if fails:
        print("%d FAILED" % len(fails))
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
