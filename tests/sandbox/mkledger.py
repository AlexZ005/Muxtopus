#!/usr/bin/env python3
"""Write a SYNTHETIC stats ledger into a sandbox state dir.

The insights view asks about "this week" and "today", so a ledger committed
with fixed dates would drift out of every period within a week and the test
would start proving nothing. This generator anchors the same shaped data on
whatever today is, which is also why the insights checks are ASSERTIONS on a
capture rather than byte goldens -- a screen whose title contains today's
date cannot be a golden.

NOTHING HERE CAME FROM A REAL TRANSCRIPT. The projects, sessions, models,
lanes and counts are invented; only the SHAPE (muxstats' LEDGER_COLS,
budget.tsv, weeks.tsv, lanes.tsv, meta) is real, and it is imported from
muxstats rather than retyped so a column added there fails here loudly.

    mkledger.py <stats-dir> [--days N] [--seed N] [--scale F] [--empty]

--empty writes only `meta`, which is the day-one screen: collecting since
today, and no rows at all.
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import muxstats  # noqa: E402

PROJECTS = ["~/work/repo-a", "~/work/repo-b", "~/code/muxtopus"]
# claude-opus-5-5 FIRST: index 0 is today's first session on every run, so
# whatever period the view is on and whatever day of the week the suite runs,
# the newest Opus has a row -- which is what insights.sh's "priced, not
# `no price`" check for it needs. Further down the list it only appeared
# on some weekdays.
MODELS = ["claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-haiku-4-5"]
LANES = ["", "root-lane", "kid-lane", "insights-dash"]
TOOLS = ["Bash", "Read", "Edit", "Grep", "Write", "Agent"]


def rows_for(days: int, rng: random.Random, scale: float) -> list[dict]:
    today = dt.date.today()
    out = []
    for back in range(days):
        day = (today - dt.timedelta(days=back)).isoformat()
        # A quiet day now and then, so the rhythm sparkline and the active-day
        # streak have something other than a flat line to draw.
        if back and back % 9 == 0:
            continue
        for n in range(1 + (back % 3)):
            sid = "%08x-0000-4000-8000-%012x" % (rng.getrandbits(32), rng.getrandbits(48))
            project = PROJECTS[(back + n) % len(PROJECTS)]
            lane = LANES[(back * 2 + n) % len(LANES)]
            for side in (0, 1) if n == 0 else (0,):
                model = MODELS[(back + n + side) % len(MODELS)]
                r = muxstats.new_row(day, sid, model, side)
                f = (0.25 if side else 1.0) * scale
                r["project"] = project
                r["lane"] = lane
                r["requests"] = int(20 * f) + n
                r["in"] = int(rng.randint(40_000, 90_000) * f)
                r["out"] = int(rng.randint(8_000, 30_000) * f)
                r["cache_read"] = int(rng.randint(400_000, 2_000_000) * f)
                r["cache_w5m"] = int(rng.randint(30_000, 120_000) * f)
                r["cache_w1h"] = int(rng.randint(0, 40_000) * f)
                r["thinking"] = int(r["out"] * 0.3)
                r["ctx_n"] = r["requests"]
                r["ctx_peak"] = rng.randint(120_000, 800_000)
                r["ctx_sum"] = r["ctx_peak"] * r["ctx_n"] // 2
                r["tools"] = rng.randint(10, 90)
                r["web"] = rng.randint(0, 3)
                r["turns"] = rng.randint(5, 40)
                r["active_s"] = rng.randint(600, 9000)
                r["compactions"] = 1 if back % 5 == 0 and not side else 0
                start = int(dt.datetime.fromisoformat(day + "T09:00").timestamp())
                r["first_ts"] = start + n * 3600
                r["last_ts"] = r["first_ts"] + r["active_s"]
                r["hours"] = ";".join("%d=%d" % (9 + h, r["in"] // 3)
                                      for h in range(3))
                mix = {}
                for t in TOOLS[: 3 + (back % 4)]:
                    mix[t] = rng.randint(1, 30)
                r["tool_mix"] = muxstats._mix_str(mix)
                out.append(r)
    # One coarse day, older than every real one: the backfill flag has to be
    # drawn somewhere, and "counts toward totals only" is a claim with a
    # picture behind it.
    c = muxstats.new_row((today - dt.timedelta(days=days + 2)).isoformat(),
                         "coarse-backfill", "claude-opus-5", 0)
    c["in"] = int(750_000 * scale)
    c["coarse"] = 1
    out.append(c)
    return out


def budget_rows(days: int, rng: random.Random) -> tuple[list[dict], list[dict]]:
    today = dt.date.today()
    bud, weeks = [], []
    for back in range(0, days, 2):
        day = today - dt.timedelta(days=back)
        start = int(dt.datetime.fromisoformat(day.isoformat() + "T08:00").timestamp())
        bud.append({"reset_at": start + 5 * 3600, "day": day.isoformat(),
                    "window_start": start,
                    "session_peak_pct": rng.randint(20, 99),
                    "week_pct": rng.randint(5, 80),
                    "limited_s": rng.choice([0, 0, 900, 3600]),
                    "hits": rng.choice([0, 0, 1]), "resumes": rng.choice([0, 1]),
                    "winddowns": rng.choice([0, 0, 1])})
        if day.weekday() == 0:
            weeks.append({"reset_at": start, "day": day.isoformat(),
                          "week_pct": rng.randint(30, 95),
                          "sampled_at": start - 600, "hits": 0})
    return bud, weeks


def lane_rows(days: int) -> list[dict]:
    today = dt.date.today()
    out = []
    for i, slug in enumerate(["root-lane", "kid-lane", "insights-dash", "old-lane"]):
        launched = int(dt.datetime.combine(today - dt.timedelta(days=i * 3 + 1),
                                           dt.time(10, 0)).timestamp())
        done = launched + 3600 * (4 + i) if i < 3 else 0
        out.append({"slug": slug, "parent": "root-lane" if i else "",
                    "launched": str(launched), "done": str(done),
                    "questions_asked": str(i % 3), "questions_answered": str(i % 2),
                    "stranded": "1" if i == 3 else "0"})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--days", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--empty", action="store_true")
    a = ap.parse_args(argv)

    d = pathlib.Path(a.dir)
    d.mkdir(parents=True, exist_ok=True)
    today = dt.date.today()
    if a.empty:
        since = today.isoformat()
        for name in ("ledger.tsv", "budget.tsv", "weeks.tsv", "lanes.tsv"):
            (d / name).unlink(missing_ok=True)
    else:
        rng = random.Random(a.seed)
        rows = rows_for(a.days, rng, a.scale)
        since = min(r["day"] for r in rows if not r["coarse"])
        bud, weeks = budget_rows(a.days, rng)
        (d / "ledger.tsv").write_text(muxstats._tsv(rows, muxstats.LEDGER_COLS))
        (d / "budget.tsv").write_text(muxstats._tsv(bud, muxstats.BUDGET_COLS))
        (d / "weeks.tsv").write_text(muxstats._tsv(weeks, muxstats.WEEK_COLS))
        (d / "lanes.tsv").write_text(muxstats._tsv(lane_rows(a.days), muxstats.LANE_COLS))
    (d / "meta").write_text(
        "last_collect\t%d\nschema\t%d\nsince\t%s\n"
        % (int(dt.datetime.now().timestamp()), muxstats.SCHEMA, since))
    print("ledger written: %s (since %s)" % (d, since))
    return 0


if __name__ == "__main__":
    sys.exit(main())
