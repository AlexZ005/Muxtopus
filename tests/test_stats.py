#!/usr/bin/env python3
"""muxstats -- the ledger, against synthetic transcripts with the real shape.

Run it:  python3 tests/test_stats.py     (no pytest, no dependency)
         python3 tests/test_stats.py --update-golden   rewrite golden/, then READ the diff

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
HAIKU = make_fixtures.HAIKU
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
        p = FIX / rel
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
    check(muxstats.load_meta(st).get("since") == "2026-09-01",
          "collecting since the oldest WATCHED day, not a coarse one")

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


# ------------------------------------------------------------ phase 2
PRICES = muxstats.PriceTable({
    "claude-opus-5": {"input": 5, "output": 25, "cache_read": 0.5, "cache_write_5m": 6.25,
                      "cache_write_1h": 10, "window": 1_000_000},
    "claude-haiku-4-5": {"input": 1, "output": 5, "cache_read": 0.1, "cache_write_5m": 1.25,
                         "cache_write_1h": 2, "window": 200_000},
}, as_of="2026-09-17")


def utc(s):
    import datetime as dt
    return int(dt.datetime.fromisoformat(s + "+00:00").timestamp())


def near(a, b, eps=1e-9):
    return a is not None and b is not None and abs(a - b) <= eps * max(1, abs(b))


def test_query_figures():
    led = muxstats.load(FIX / "ledger")
    now = utc("2026-09-17T12:00:00")          # a Thursday
    q = muxstats.query(led, "week", {}, "project", now, PRICES)
    p = q["period"]
    check((p["start"], p["end"], p["prev_start"], p["prev_end"]) ==
          ("2026-09-14", "2026-09-20", "2026-09-07", "2026-09-10"),
          "week = Monday..Sunday; previous = the same Mon..Thu a week earlier")
    check(q["collected_days"] == 17 and not q["thin"] and q["needs"] == {},
          "17 days collected: nothing withheld")

    t = q["tokens"]
    check((t["total"], t["input"], t["output"], t["cache_read"], t["cache_write"], t["coarse"]) ==
          (174000, 3600, 7400, 149000, 14000, 0), "TOKENS total and its four parts")
    check(near(t["thinking_share"], 1500 / 7400), "thinking share of output = 1500/7400")
    check(near(t["per_active_hour"], 104400), "tokens per active hour = 174000 / (6000s/3600)")

    c = q["cache"]
    check(near(c["read_share"], 149000 / 166600), "cache share of input = 149000/166600")
    check((c["write_5m"], c["write_1h"]) == (10000, 4000), "5m vs 1h writes")
    check(near(c["saved_usd"], 0.6056), "cache saved, net of the write premium = $0.6056 (%r)" % c["saved_usd"])

    k = q["cost"]
    check(near(k["usd"], 0.3414), "API-equiv $ = 0.1675 + 0.0039 + 0.17 (%r)" % k["usd"])
    check(k["unpriced_models"] == ["mystery-model"] and k["unpriced_tokens"] == 1000,
          "an unpriced model is named with its tokens, not guessed")
    check(k["elapsed_days"] == 4 and near(k["per_day"], 0.08535), "per day over the 4 elapsed days")
    check(near(k["projected_month"], 0.08535 * 30), "projected September (30 days)")

    x = q["context"]
    check(near(x["avg_per_request"], 58280), "avg context per request = 1165600 / 20")
    check(near(x["avg_session_peak"], (600000 + 850000 + 100) / 3), "avg session peak (main side)")
    check(near(x["avg_session_peak_pct"], 0.725) and x["sessions_measured"] == 2,
          "avg peak % of window over the 2 sessions with a known window")
    check(x["sessions_past_80"] == 1 and x["compactions"] == 1, "one session past 80%; one compaction")

    s = q["sessions"]
    check(s["count"] == 3 and s["median_active_s"] == 1800 and s["longest_active_s"] == 3600,
          "3 sessions; median active 1800 s, longest 3600 s")
    check(near(s["turns_per_session"], 7 / 3), "turns per session = 7/3")
    check(near(s["subagent_share"], 10000 / 174000), "subagent share of tokens")
    check(s["tool_calls"] == 28 and s["top_tools"] == [("Bash", 17), ("Read", 8), ("Grep", 3)],
          "tool calls and the top tools (%r)" % (s["top_tools"],))
    check(s["web"] == 3, "web searches + fetches")

    r = q["rhythm"]
    check(r["by_weekday"] == [123000, 50000, 1000, 0, 0, 0, 0], "tokens by weekday, Monday first")
    hours = [0] * 24
    hours[9], hours[10], hours[14], hours[23] = 50000, 73000, 50000, 1000
    check(r["by_hour"] == hours, "tokens by hour")
    check((r["busiest_day"], r["busiest_hour"]) == ("2026-09-14", 10), "busiest day and hour")
    check((r["streak"], r["longest_streak"]) == (3, 3),
          "streak 14-15-16, today not over yet so it still counts")
    check(near(r["vs_previous_pct"], 248.0) and r["previous_total"] == 50000,
          "▲ 248% against last Mon..Thu (50000)")

    bd = {b["key"]: b for b in q["breakdown"]}
    check([b["key"] for b in q["breakdown"]] == ["~/p/alpha", "~/p/beta"], "breakdown by tokens")
    a, b = bd["~/p/alpha"], bd["~/p/beta"]
    check((a["tokens"], a["sessions"]) == (123000, 1) and near(a["share"], 123000 / 174000),
          "alpha: tokens, share, sessions")
    check(near(a["avg_ctx"], 1119500 / 15) and near(a["cache_pct"], 109000 / 120500)
          and near(a["usd"], 0.1714) and not a["unpriced"], "alpha: avg ctx, cache %, $")
    check((b["tokens"], b["sessions"]) == (51000, 2) and near(b["usd"], 0.17) and b["unpriced"],
          "beta: its $ is flagged partial (a model has no price)")

    # Filters compose: AND across keys, OR within one.
    f = lambda **kw: muxstats.query(led, "week", kw, "model", now, PRICES)["tokens"]["total"]  # noqa: E731
    check(f(project=["~/p/alpha"], side=["main"]) == 113000, "project AND main side")
    check(f(model=["claude-opus-5", HAIKU]) == 173000, "two models: OR within a key")
    check(f(lane=["L1"], model=["claude-opus-5"]) == 113000, "lane AND model")
    check(f(side=["sub"]) == 10000, "subagents only")

    al = muxstats.query(led, "all", {}, "month", now, PRICES)
    check(al["period"]["start"] == "2026-08-30" and al["tokens"]["total"] == 251000
          and al["tokens"]["coarse"] == 7000, "all: from the first row, coarse counted in the total")
    check(al["rhythm"]["vs_previous_pct"] is None and "rhythm.vs_previous_pct" not in al["needs"],
          "all has no previous period and does not pretend to")
    check([b["key"] for b in al["breakdown"]] == ["2026-08", "2026-09"], "group by month, in date order")
    check(al["cost"]["usd"] is not None and near(al["cost"]["usd"], 0.3414 + 0.025 + 0.0245 + 0.5),
          "coarse days are not priced; the real ones are")

    mo = muxstats.query(led, "month", {}, "day", now, PRICES)
    check((mo["period"]["prev_start"], mo["period"]["prev_end"]) == ("2026-08-01", "2026-08-17"),
          "this month compares with the same 17 days of last month")
    check(mo["rhythm"]["vs_previous_pct"] is None and mo["needs"].get("rhythm.vs_previous_pct") == "a previous period",
          "...which predates collecting, so it says so")
    l7 = muxstats.query(led, "last7", {}, "day", now, PRICES)
    check((l7["period"]["start"], l7["tokens"]["total"]) == ("2026-09-11", 174000), "last 7 d")
    td = muxstats.query(led, "today", {}, "project", now, PRICES)
    check(td["tokens"]["total"] == 0 and td["breakdown"] == [] and td["context"]["avg_per_request"] is None,
          "an empty today is zeros and blanks, not an exception")

    nop = muxstats.query(led, "week", {}, "project", now, None)
    check(nop["cost"]["usd"] is None and nop["cache"]["saved_usd"] is None
          and nop["context"]["avg_session_peak_pct"] is None and nop["tokens"]["total"] == 174000,
          "no price table: tokens only, no $ and no window %")


def test_thin_data(tmp):
    d = tmp / "thin"
    shutil.copytree(FIX / "ledger", d)
    (d / "meta").write_text("since\t2026-09-14\n")
    q = muxstats.query(muxstats.load(d), "week", {}, "project",
                       utc("2026-09-17T12:00:00"), PRICES)
    check(q["thin"] and q["collected_days"] == 4, "4 days collected is thin")
    check(q["sessions"]["median_active_s"] is None and q["cost"]["projected_month"] is None
          and q["rhythm"]["vs_previous_pct"] is None,
          "medians, projection and vs-previous are withheld")
    check(q["needs"] == {"sessions.median_active_s": "7 days", "cost.projected_month": "7 days",
                         "rhythm.vs_previous_pct": "7 days", "lanes.median_launch_to_done_s": "7 days"},
          "...each with its reason (%r)" % q["needs"])
    check(q["tokens"]["total"] == 174000 and q["sessions"]["longest_active_s"] == 3600,
          "totals and maxima are still shown")


def test_dst(tmp):
    os.environ["TZ"] = "Europe/Berlin"
    time.tzset()
    try:
        cfg = tmp / "dst" / "claude"
        proj = cfg / "projects" / "-home-user-dst"
        proj.mkdir(parents=True)
        sid = "dddddddd-0000-4000-8000-00000000000d"
        recs = []
        # 10-25 is the day CEST ends: 02:30 happens twice.
        for i, ts in enumerate(["2026-10-24T22:30:00Z", "2026-10-25T00:30:00Z",
                                "2026-10-25T01:30:00Z", "2026-10-25T22:30:00Z",
                                "2026-10-25T23:30:00Z"]):
            recs += make_fixtures.message(sid, ts.replace("Z", ".000Z"), "claude-opus-5",
                                          "msg_dst_%d" % i, "req_dst_%d" % i,
                                          make_fixtures.usage(0, 1000, 0, 0, 0), ["text"])
        (proj / (sid + ".jsonl")).write_text(make_fixtures.dumps(recs))
        st = tmp / "dst" / "state"
        muxstats.collect(cfg, st, utc("2026-10-26T10:00:00"))
        rows = {r["day"]: r for r in muxstats.load_ledger(st)}
        check(sorted(rows) == ["2026-10-25", "2026-10-26"],
              "days are LOCAL: 22:30Z on the 24th is the 25th in Berlin, 23:30Z on the 25th the 26th")
        check(rows["2026-10-25"]["out"] == 4000 and rows["2026-10-25"]["hours"] == "0=1000;2=2000;23=1000",
              "the repeated 02:00 hour holds both of its readings (%r)" % rows["2026-10-25"]["hours"])
        led = muxstats.load(st)
        sun = muxstats.query(led, "week", {}, "day", utc("2026-10-25T12:00:00"), None)
        mon = muxstats.query(led, "week", {}, "day", utc("2026-10-26T10:00:00"), None)
        l7 = muxstats.query(led, "last7", {}, "day", utc("2026-10-26T10:00:00"), None)
        check((sun["period"]["start"], sun["period"]["end"]) == ("2026-10-19", "2026-10-25"),
              "Sunday the 25th is still in the week that began Monday the 19th")
        check(mon["period"]["start"] == "2026-10-26" and mon["tokens"]["total"] == 1000,
              "Monday the 26th starts a new week holding only its own hour")
        check(l7["tokens"]["total"] == 5000, "last 7 d spans the DST change whole")
    finally:
        os.environ["TZ"] = "UTC"
        time.tzset()


def test_budget_and_lanes(tmp):
    home = tmp / "muxhome"
    shutil.copytree(FIX / "muxhome", home)
    for rel, stamp in [("handovers/done/STATUS-lane-a.md", "2026-09-15T09:00:00"),
                       ("handovers/done/STATUS-lane-b-20260916-120000.md", "2026-09-16T12:00:00")]:
        os.utime(home / rel, (utc(stamp), utc(stamp)))
    st = tmp / "budget-state"
    st.mkdir()
    shutil.copy(FIX / "ledger" / "meta", st / "meta")
    e = utc("2026-09-14T12:10:00")
    limits = {("five_hour", str(e + 30)): {"type": "five_hour", "resets_at": str(e + 30),
                                           "first_ts": str(e - 1800), "last_ts": str(e - 60)},
              ("seven_day", str(utc("2026-09-17T17:00:00"))): {
                  "type": "seven_day", "resets_at": str(utc("2026-09-17T17:00:00")),
                  "first_ts": str(utc("2026-09-17T16:30:00")), "last_ts": "0"}}
    wd = FIX / "watchdog"
    muxstats.budget_collect(st, wd, limits)
    muxstats.lanes_collect(st, wd, home / "schedules", home / "handovers")

    b = {r["reset_at"]: r for r in muxstats.load(st).budget}
    w1 = b.get(e)
    check(w1 is not None and (w1["day"], w1["window_start"], w1["session_peak_pct"], w1["week_pct"]) ==
          ("2026-09-14", e - 18000, 100, 30), "the 12:10 window: readings to a peak of 100%, week 30%")
    check(w1 is not None and (w1["hits"], w1["limited_s"], w1["resumes"], w1["winddowns"]) == (1, 1830, 2, 1),
          "...a limit hit 30 s off the reading's minute is the same window; 2 resumes, 1 wind-down")
    w2 = b.get(utc("2026-09-14T17:10:00"))
    check(w2 is not None and w2["session_peak_pct"] == 5, "'resets=5:10pm' is 17:10")
    check(utc("2026-09-15T01:00:00") not in b, "a 0% window with nothing in it is not a row")
    w4 = b.get(utc("2026-09-16T10:00:00"))
    check(w4 is not None and (w4["winddowns"], w4["session_peak_pct"]) == (1, 0),
          "a wind-down outside any known window still counts")
    check(len(b) == 4, "four windows (%d)" % len(b))

    before = state_files(st)
    muxstats.budget_collect(st, wd, limits)
    muxstats.lanes_collect(st, wd, home / "schedules", home / "handovers")
    check(state_files(st) == before, "budget and lanes collected twice -> byte-identical")
    muxstats.budget_collect(st, tmp / "rotated-away", {})
    muxstats.lanes_collect(st, tmp / "rotated-away", None, None)
    check(state_files(st) == before, "a log rotated away loses nothing already counted")

    lanes = {l["slug"]: l for l in muxstats.load(st).lanes}
    check(sorted(lanes) == ["a-title-that-is-far-to", "lane-a", "lane-b", "lane-c", "lane-d"],
          "lanes from tree + entries (slug rule of the watchdog); adopted and unlaunched skipped")
    la, lb = lanes["lane-a"], lanes["lane-b"]
    check((la["parent"], la["launched"], la["done"]) ==
          ("root", str(utc("2026-09-14T08:30:00")), str(utc("2026-09-15T09:00:00"))),
          "lane-a: launched = the earlier of entry and tree; done = its done/ mtime")
    check((la["questions_asked"], la["questions_answered"]) == ("2", "2"), "an ANSWERED file answers all its forks")
    check((lb["done"], lb["questions_asked"], lb["questions_answered"], lb["stranded"]) ==
          (str(utc("2026-09-16T12:00:00")), "3", "1", "2"),
          "lane-b: stamped done file, 3 forks 1 answered, stranded twice (not 'no longer')")

    q = muxstats.query(muxstats.load(st), "week", {}, "project", utc("2026-09-17T23:00:00"), PRICES)
    bu = q["budget"]
    check((bu["windows"], bu["hits"], bu["limited_s"], bu["resumes"], bu["winddowns"]) == (3, 1, 1830, 2, 2),
          "BUDGET: 3 windows, 1 hit, 1830 s limited, 2 resumes, 2 wind-downs")
    check(near(bu["avg_window_peak_pct"], 50.0), "average window peak = (100 + 5 + 45) / 3")
    check(bu["week_pct_at_reset"] == [["2026-09-17", 77]],
          "week % at the reset that passed; next week's is not a reset yet")
    ln = q["lanes"]
    check((ln["launched"], ln["done"], ln["deepest"]) == (5, 2, 4), "LANES: 5 launched, 2 done, depth 4")
    check(ln["median_launch_to_done_s"] == (88200 + 180000) / 2, "median launch-to-done")
    check((ln["forks_asked"], ln["forks_answered"], ln["stranded"]) == (5, 3, 2), "forks and stranded")
    lq = muxstats.query(muxstats.load(st), "week", {"lane": ["lane-b"]}, "project",
                        utc("2026-09-17T23:00:00"), PRICES)["lanes"]
    check((lq["launched"], lq["forks_asked"]) == (1, 3), "the lane filter narrows the LANES row")


# ------------------------------------------------------------ phase 3
GOLDEN = FIX / "golden"
GOLDEN_NOW = "2026-09-17T23:00:00"


def golden_state(tmp) -> pathlib.Path:
    """The fixture ledger plus budget, weeks and lanes collected from the
    fixture logs, tree, entries and handovers -- every row of the report."""
    st = tmp / "golden-state"
    if st.exists():
        return st
    shutil.copytree(FIX / "ledger", st)
    home = tmp / "golden-home"
    shutil.copytree(FIX / "muxhome", home)
    for rel, stamp in [("handovers/done/STATUS-lane-a.md", "2026-09-15T09:00:00"),
                       ("handovers/done/STATUS-lane-b-20260916-120000.md", "2026-09-16T12:00:00")]:
        os.utime(home / rel, (utc(stamp), utc(stamp)))
    e = utc("2026-09-14T12:10:00")
    muxstats.budget_collect(st, FIX / "watchdog", {("five_hour", str(e)): {
        "type": "five_hour", "resets_at": str(e), "first_ts": str(e - 1800), "last_ts": str(e)}})
    muxstats.lanes_collect(st, FIX / "watchdog", home / "schedules", home / "handovers")
    return st


def run_cli(args) -> tuple[int, str, str]:
    import contextlib
    import io
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = muxstats.main(args)
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


def test_prices():
    t = muxstats.prices(FIX / "prices.md")
    check(t is not None and t.as_of == "2026-09-17", "the price file's `as of:` line")
    check(t.price("claude-opus-5")["cache_write_1h"] == 10 and t.window("claude-opus-5") == 1_000_000,
          "a block: five prices and a window of 1M")
    check(t.price(HAIKU) is not None and t.window(HAIKU) is None,
          "a dated id matches its block; a bad window is dropped, the prices kept")
    check(t.price("half-priced") is None, "a block missing prices is no price, not a partial one")
    check(len(t.errors) == 3 and any("lots" in e for e in t.errors) and any("bogus" in e for e in t.errors)
          and any("half-priced has no output" in e for e in t.errors),
          "each broken line is named (%r)" % t.errors)
    check(muxstats.prices(FIX / "no-such-file.md") is None, "no file is None, not an exception")

    seed = muxstats.prices(pathlib.Path(__file__).resolve().parent.parent / "seeds" / "prices.md")
    check(seed is not None and seed.errors == [] and seed.as_of == "2026-09-17",
          "seeds/prices.md parses clean, as of 2026-09-17 (%r)" % (seed.errors if seed else None))
    for m in ("claude-fable-5-1", "claude-fable-5", "claude-opus-5", "claude-opus-4-8",
              "claude-sonnet-5", HAIKU):
        check(seed.price(m) is not None and seed.window(m), "seed prices %s and knows its window" % m)
    check(seed.price("claude-fable-5-1")["cache_read"] == 0.25 and seed.price("claude-fable-5")["cache_read"] == 1,
          "Fable 5.1's cache reads are its own rate, not Fable 5's")
    check(seed.price("claude-opus-4-20250514")["input"] == 15, "a legacy dated id is priced")
    check(seed.price("claude-fable-5-2") is None and seed.price("claude-opus-5-fast") is None,
          "an unnamed model is never given a neighbour's price")


def test_golden(tmp, update):
    st = golden_state(tmp)
    base = ["stats", "--week", "--no-collect", "--state-dir", str(st),
            "--prices", str(FIX / "prices.md"), "--now", str(utc(GOLDEN_NOW))]
    for fmt, flag in (("txt", []), ("json", ["--json"]), ("csv", ["--csv"]), ("md", ["--md"])):
        code, out, err = run_cli(base + flag)
        path = GOLDEN / ("week." + fmt)
        if update:
            GOLDEN.mkdir(exist_ok=True)
            path.write_text(out)
        check(code == 0 and err == "" and path.exists() and path.read_text() == out,
              "golden %s output matches %s" % (fmt, path.name))
    import csv
    import json
    js = json.loads((GOLDEN / "week.json").read_text())
    check(js["tokens"]["total"] == 174000 and js["budget"]["hits"] == 1 and js["lanes"]["launched"] == 5,
          "the json parses and carries the figures")
    rows = list(csv.DictReader((GOLDEN / "week.csv").read_text().splitlines()))
    check([r["project"] for r in rows] == ["~/p/alpha", "~/p/beta"] and rows[1]["unpriced"] == "1",
          "the csv parses: the breakdown, one row per group")
    txt = (GOLDEN / "week.txt").read_text()
    check("no price: mystery-model (1.0k tokens)" in txt, "text: an unknown model says no price")
    check("API-equiv (prices as of 2026-09-17)" in txt, "text: every $ is API-equiv with its date")
    check(txt.count("prices.md: line") == 3, "text: the price file's broken lines are listed")

    code, out, _ = run_cli(base[:5] + ["--prices", str(tmp / "absent.md"), "--now", str(utc(GOLDEN_NOW))])
    check(code == 0 and "no price file at" in out and "174.0k total" in out and "$" not in out.split("BY PROJECT")[0],
          "a missing price file: tokens only, exit 0")
    code, out, _ = run_cli(base[:5] + ["--prices", str(tmp / "absent.md"), "--now", str(utc(GOLDEN_NOW)), "--json"])
    js = json.loads(out)
    check(js["cost"]["usd"] is None and js["cost"]["unpriced_models"] == [] and js["prices_as_of"] is None,
          "...and in json: no $, and no model blamed for it")
    code, out, _ = run_cli(base + ["--project", "alpha", "--by", "model", "--json"])
    js = json.loads(out)
    check(js["filters"]["project"] == ["~/p/alpha"] and js["tokens"]["total"] == 123000,
          "--project takes a directory's basename")
    code, _, err = run_cli(["stats", "--before", "2026-09-01"])
    check(code == 2 and "--forget" in err, "--before without --forget is refused")
    code, out, _ = run_cli(["stats", "--help"])
    check(code == 0 and "--forget" in out, "stats --help")


def test_forget(tmp):
    import json
    st = tmp / "forget-state"
    shutil.copytree(golden_state(tmp), st)
    now = utc(GOLDEN_NOW)
    code, out, _ = run_cli(["stats", "--forget", "--before", "2026-09-14", "--state-dir", str(st),
                            "--now", str(now)])
    check(code == 0 and "forgot 3 ledger row(s)" in out, "--forget --before: 3 rows before 09-14 (%s)" % out.strip())
    rows = muxstats.load_ledger(st)
    check(min(r["day"] for r in rows) == "2026-09-14" and len(rows) == 4, "only 09-14 onwards is left")
    meta = muxstats.load_meta(st)
    check(meta["since"] == "2026-09-14" and meta["forget_before"] == str(utc("2026-09-14T00:00:00")),
          "since moves up; the cutoff is kept")

    # A collect that meets older records does not bring them back.
    cfg = tree_copy(tmp, "forget-claude")
    muxstats.collect(cfg, st, now)
    check(min(r["day"] for r in muxstats.load_ledger(st)) == "2026-09-14",
          "a later collect of 09-01 transcripts adds nothing before the cutoff")

    code, out, _ = run_cli(["stats", "--forget", "--state-dir", str(st), "--now", str(now)])
    check(code == 0 and muxstats.load_ledger(st) == [], "--forget with no date: everything")
    muxstats.collect(cfg, st, now)
    code, out, _ = run_cli(["stats", "--all", "--no-collect", "--state-dir", str(st), "--now", str(now), "--json"])
    js = json.loads(out)
    check(muxstats.load_ledger(st) == [] and js["tokens"]["total"] == 0 and js["budget"]["windows"] == 0
          and js["lanes"]["launched"] == 0, "...and it stays forgotten")


def test_launcher(tmp):
    """`muxtopus stats` in a sandbox: own HOME and XDG dirs, a tmux that
    records being called, the account picked by the launcher's flags."""
    import json
    import subprocess
    root = pathlib.Path(__file__).resolve().parent.parent
    sbx = tmp / "sbx"
    (sbx / "bin").mkdir(parents=True)
    marker = sbx / "tmux-called"
    (sbx / "bin" / "tmux").write_text("#!/bin/sh\necho \"$@\" >> %s\nexit 1\n" % marker)
    (sbx / "bin" / "tmux").chmod(0o755)
    shutil.copytree(golden_state(tmp), sbx / "state" / "muxtopus" / "stats-work")
    env = {"HOME": str(sbx / "home"), "XDG_CONFIG_HOME": str(sbx / "config"),
           "XDG_STATE_HOME": str(sbx / "state"), "XDG_DATA_HOME": str(sbx / "data"),
           "MUXTOPUS_CONFIG": str(sbx / "config" / "muxtopus" / "config"),
           "CLAUDE_CONFIG_DIR": str(sbx / "home" / ".claude"),
           "PATH": "%s:%s" % (sbx / "bin", os.environ.get("PATH", "")), "TZ": "UTC"}
    args = ["--week", "--json", "--no-collect", "--prices", str(FIX / "prices.md"), "--now", str(utc(GOLDEN_NOW))]
    r = subprocess.run([str(root / "muxtopus"), "-w", "stats"] + args, env=env,
                       capture_output=True, text=True, timeout=60)
    check(r.returncode == 0 and r.stdout == (GOLDEN / "week.json").read_text(),
          "muxtopus -w stats reads the work account's ledger (%s)" % r.stderr.strip()[:200])
    r = subprocess.run([str(root / "muxtopus"), "stats"] + args, env=env,
                       capture_output=True, text=True, timeout=60)
    check(r.returncode == 0 and json.loads(r.stdout)["tokens"]["total"] == 0,
          "muxtopus stats on an account with no ledger: an empty report, exit 0")
    # CLAUDE_CONFIG_DIR naming the work account, with no flag: the launcher's
    # rule is the flag or the name, so this is the default account.
    env2 = dict(env, CLAUDE_CONFIG_DIR=str(sbx / "home" / ".claude-work"))
    r = subprocess.run([str(root / "muxtopus"), "stats"] + args, env=env2,
                       capture_output=True, text=True, timeout=60)
    check(r.returncode == 0 and json.loads(r.stdout)["tokens"]["total"] == 0,
          "an inherited CLAUDE_CONFIG_DIR does not switch muxtopus stats' account")
    check(not marker.exists(), "no tmux call, no session, no watchdog")
    check(not (sbx / "home" / ".claude").exists() and not (sbx / "data").exists(),
          "nothing created under the sandbox HOME or data dir")


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="muxstats-test-"))
    try:
        test_fixture_is_generated()
        cfg, st = test_ledger(tmp)
        test_idempotent_and_incremental(tmp, cfg, st)
        test_shrink_and_replace(tmp)
        test_lanes(tmp)
        test_query_figures()
        test_thin_data(tmp)
        test_dst(tmp)
        test_budget_and_lanes(tmp)
        test_prices()
        test_golden(tmp, "--update-golden" in sys.argv)
        test_forget(tmp)
        test_launcher(tmp)
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
