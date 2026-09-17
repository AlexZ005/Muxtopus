#!/usr/bin/env python3
"""Writes the synthetic transcripts tests/test_stats.py reads.

    python3 tests/fixtures/transcripts/make_fixtures.py     (rewrites every fixture)

SYNTHETIC, WITH THE REAL SHAPE. Every record carries the keys a Claude Code
2.1.27x transcript carries (checked against real files by listing KEYS only);
every value is invented here. No text from a real transcript belongs in this
directory -- muxtopus goes public, and so do its fixtures.

What is in it, and what the test expects of it:

  alpha/<A>.jsonl   session A, opus: a message on 1 line, one split over 3
                    lines, one over 9; user and attachment noise; a turn, a
                    compaction; a usage-limit refusal; a line that is not
                    JSON; and a LAST LINE CUT MID-WRITE (no newline)
  alpha/<A>/subagents/agent-*.jsonl   a haiku subagent of A, isSidechain
  alpha/<B>.jsonl   session B RESUMED from A: A's first two messages and its
                    turn COPIED in (same ids, timestamps, uuids), then one new
                    sonnet message on the next day
  stats-cache.json  two coarse days before the oldest transcript, and one that
                    overlaps it (must be skipped)

and, for query() (every figure hand-computed in tests/test_stats.py):

  ledger/           a small ledger: four rows this week (2026-09-14..), one the
                    week before, one on 09-01, one coarse day
  watchdog/         usage.log (hourly readings, a failed read, an am/pm reset,
                    an idle 0% window), log (resumes, wind-downs, stranded),
                    tree.tsv (three launched lanes and one adopted window)
  muxhome/          schedules/ with `launched:` stamps, handovers/ with done
                    STATUS files and QUESTIONS files (mtimes are set by the test:
                    git does not keep them)

test_stats.py checks that this script still produces the committed files, so
the generator and the fixture cannot drift apart.
"""
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
PROJ = "-home-user-proj-alpha"
CWD = "/home/user/proj/alpha"
A = "aaaaaaaa-0000-4000-8000-00000000000a"
B = "bbbbbbbb-0000-4000-8000-00000000000b"
VERSION = "2.1.274"

_n = [0]


def uid(tag):
    _n[0] += 1
    return "%s-%04d-4000-8000-%012d" % (tag, _n[0], _n[0])


def base(typ, sid, ts, side=False, parent=None):
    return {"parentUuid": parent, "isSidechain": side, "userType": "external",
            "cwd": CWD, "sessionId": sid, "version": VERSION, "gitBranch": "main",
            "entrypoint": "cli", "type": typ, "uuid": uid("u0000000"), "timestamp": ts}


def usage(inp, out, rd, w5m, w1h, thinking=0, web_s=0, web_f=0):
    return {"input_tokens": inp, "cache_creation_input_tokens": w5m + w1h,
            "cache_read_input_tokens": rd, "output_tokens": out,
            "server_tool_use": {"web_search_requests": web_s, "web_fetch_requests": web_f},
            "service_tier": "standard",
            "cache_creation": {"ephemeral_1h_input_tokens": w1h, "ephemeral_5m_input_tokens": w5m},
            "output_tokens_details": {"thinking_tokens": thinking},
            "inference_geo": "not_available",
            "iterations": [{"input_tokens": inp, "output_tokens": out,
                            "cache_read_input_tokens": rd,
                            "cache_creation_input_tokens": w5m + w1h,
                            "cache_creation": {"ephemeral_5m_input_tokens": w5m,
                                               "ephemeral_1h_input_tokens": w1h},
                            "type": "message"}],
            "speed": "standard"}


def blocks_of(kinds):
    out = []
    for k in kinds:
        if k == "text":
            out.append({"type": "text", "text": "synthetic reply"})
        elif k == "thinking":
            out.append({"type": "thinking", "thinking": "synthetic", "signature": "x"})
        else:  # a tool name
            out.append({"type": "tool_use", "id": uid("toolu000"), "name": k,
                        "input": {"synthetic": True}, "caller": {"type": "direct"}})
    return out


def message(sid, ts, model, msg_id, req_id, u, kinds, side=False):
    """One API message as Claude Code writes it: one line PER content block,
    every line repeating the same usage."""
    lines = []
    for i, blk in enumerate(blocks_of(kinds)):
        r = base("assistant", sid, ts, side)
        r.update({"message": {"model": model, "id": msg_id, "type": "message",
                              "role": "assistant", "content": [blk],
                              "stop_reason": None, "stop_sequence": None,
                              "stop_details": None, "usage": u, "diagnostics": None},
                  "requestId": req_id, "apiBlockIndex": i, "effort": "high"})
        lines.append(r)
    return lines


def user(sid, ts, side=False):
    r = base("user", sid, ts, side)
    r.update({"message": {"role": "user", "content": "synthetic prompt"},
              "promptId": uid("p0000000")})
    return r


def turn(sid, ts, ms, side=False):
    r = base("system", sid, ts, side)
    r.update({"subtype": "turn_duration", "durationMs": ms, "messageCount": 4, "isMeta": False})
    return r


def compact(sid, ts):
    r = base("system", sid, ts)
    r.update({"subtype": "compact_boundary", "content": "Conversation compacted",
              "level": "info", "logicalParentUuid": None,
              "compactMetadata": {"trigger": "auto", "preTokens": 170000}})
    return r


def limit(sid, ts, resets_at):
    r = base("assistant", sid, ts)
    r.update({"message": {"model": "<synthetic>", "id": uid("m0000000"), "type": "message",
                          "role": "assistant", "content": [{"type": "text", "text": "limit"}],
                          "stop_reason": "stop_sequence", "stop_sequence": "",
                          "usage": usage(0, 0, 0, 0, 0)},
              "requestId": None, "error": "rate_limit", "isApiErrorMessage": True,
              "apiErrorStatus": 429,
              "quotaLimits": {"status": "rejected", "rateLimitType": "five_hour",
                              "resetsAt": resets_at, "isUsingOverage": False,
                              "overageStatus": "rejected", "overageDisabledReason": "x",
                              "unifiedRateLimitFallbackAvailable": False}})
    return r


def meta_noise(sid):
    return [{"type": "last-prompt", "lastPrompt": "synthetic", "leafUuid": uid("l0000000"), "sessionId": sid},
            {"type": "permission-mode", "permissionMode": "default", "sessionId": sid},
            {"type": "ai-title", "aiTitle": "synthetic", "sessionId": sid}]


def dumps(recs):
    return "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in recs)


def build() -> dict:
    """path relative to this directory -> file content"""
    out = {"claude/" + k: v for k, v in build_transcripts().items()}
    out.update(build_query())
    return out


def build_transcripts() -> dict:
    _n[0] = 0
    D1 = "2026-09-01T"
    D2 = "2026-09-02T"
    m1 = message(A, D1 + "10:00:05.000Z", "claude-opus-5", "msg_fixture_0001", "req_fixture_0001",
                 usage(10, 100, 1000, 200, 300, thinking=40), ["text"])
    m2 = message(A, D1 + "10:01:00.000Z", "claude-opus-5", "msg_fixture_0002", "req_fixture_0002",
                 usage(5, 50, 2000, 0, 0, web_s=1), ["thinking", "text", "Bash"])
    t1 = turn(A, D1 + "10:01:30.000Z", 61400)
    m3 = message(A, D1 + "11:00:00.000Z", "claude-opus-5", "msg_fixture_0003", "req_fixture_0003",
                 usage(1, 900, 3000, 100, 0, web_f=2),
                 ["Read", "Read", "Read", "Read", "Read", "Bash", "Bash", "Bash", "Bash"])
    a_main = ([user(A, D1 + "10:00:00.000Z")] + m1 + m2 + [t1]
              + meta_noise(A)
              + [user(A, D1 + "10:59:00.000Z")]
              + m3
              + [compact(A, D1 + "11:30:00.000Z"),
                 limit(A, D1 + "12:00:00.000Z", 1788274800),
                 limit(A, D1 + "12:05:00.000Z", 1788274800)])
    text_a = dumps(a_main)
    # A line that is not JSON, in the middle, and a last line cut mid-write.
    cut = message(A, D1 + "13:00:00.000Z", "claude-opus-5", "msg_fixture_0004", "req_fixture_0004",
                  usage(7, 70, 700, 0, 0), ["text"])
    lines = text_a.splitlines(keepends=True)
    lines.insert(3, "{this is not json\n")
    text_a = "".join(lines) + json.dumps(cut[0], separators=(",", ":"))[:120]

    s1 = message(A, D1 + "10:00:40.000Z", "claude-haiku-4-5-20251001", "msg_fixture_s001",
                 "req_fixture_s001", usage(20, 30, 400, 50, 0), ["Grep", "text"], side=True)
    s2 = message(A, D1 + "10:00:50.000Z", "claude-haiku-4-5-20251001", "msg_fixture_s002",
                 "req_fixture_s002", usage(2, 3, 40, 0, 0), ["text"], side=True)
    sub = [user(A, D1 + "10:00:30.000Z", side=True)] + s1 + s2

    # B resumes A: the copies keep ids, timestamps and uuids; sessionId is B's.
    def copy(recs):
        out = []
        for r in recs:
            c = json.loads(json.dumps(r))
            c["sessionId"] = B
            out.append(c)
        return out
    m5 = message(B, D2 + "09:00:00.000Z", "claude-sonnet-5", "msg_fixture_0005", "req_fixture_0005",
                 usage(3, 30, 500, 0, 60), ["Edit", "text"])
    b_main = (copy([user(A, D1 + "10:00:00.000Z")] + m1 + m2 + [t1])
              + [user(B, D2 + "08:59:00.000Z")] + m5 + [turn(B, D2 + "09:00:10.000Z", 9600)])

    stats_cache = {"version": 2, "lastComputedDate": "2026-09-01",
                   "dailyActivity": [], "hourCounts": {}, "modelUsage": {},
                   "totalSessions": 3, "totalMessages": 10, "longestSession": {},
                   "firstSessionDate": "2026-08-30T00:00:00.000Z",
                   "dailyModelTokensVersion": 1,
                   "dailyModelTokens": [
                       {"date": "2026-08-30", "tokensByModel": {"claude-opus-5": 123456}},
                       {"date": "2026-08-31", "tokensByModel": {"claude-opus-5": 1000,
                                                                "claude-sonnet-5": 2000}},
                       {"date": "2026-09-01", "tokensByModel": {"claude-opus-5": 999999}}]}
    return {
        "projects/%s/%s.jsonl" % (PROJ, A): text_a,
        "projects/%s/%s/subagents/agent-a0000000000000001.jsonl" % (PROJ, A): dumps(sub),
        "projects/%s/%s.jsonl" % (PROJ, B): dumps(b_main),
        "stats-cache.json": json.dumps(stats_cache, indent=2) + "\n",
    }


LEDGER_COLS = ("day", "session", "project", "lane", "model", "side",
               "requests", "in", "out", "cache_read", "cache_w5m", "cache_w1h", "thinking",
               "ctx_peak", "ctx_sum", "ctx_n", "tools", "web", "turns", "active_s",
               "compactions", "first_ts", "last_ts", "hours", "tool_mix", "coarse")
OPUS, HAIKU = "claude-opus-5", "claude-haiku-4-5-20251001"
S1, S2, S3, S4, S5 = ("11111111-0000-4000-8000-000000000001", "22222222-0000-4000-8000-000000000002",
                      "33333333-0000-4000-8000-000000000003", "44444444-0000-4000-8000-000000000004",
                      "55555555-0000-4000-8000-000000000005")
# R1..R7 of tests/test_stats.py, in column order after `side`:
# req in out read w5m w1h think peak ctx_sum ctx_n tools web turns active comp first last hours mix coarse
LEDGER_ROWS = [
    ("2026-08-30", "-", "-", "", OPUS, 0, 0, 7000, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, "", "", 1),
    ("2026-09-01", S5, "~/p/alpha", "", OPUS, 0, 1, 0, 20000, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 300, 0,
     1788264000, 1788264300, "12=20000", "", 0),
    ("2026-09-08", S4, "~/p/alpha", "", OPUS, 0, 2, 0, 1000, 49000, 0, 0, 0, 30000, 49000, 2, 0, 0, 1, 1200, 0,
     1788854400, 1788855600, "8=50000", "", 0),
    ("2026-09-14", S1, "~/p/alpha", "L1", HAIKU, 1, 5, 500, 500, 9000, 0, 0, 0, 5000, 9500, 5, 3, 0, 0, 0, 0,
     1789380000, 1789383000, "10=10000", "Grep=3", 0),
    ("2026-09-14", S1, "~/p/alpha", "L1", OPUS, 0, 10, 1000, 2000, 100000, 10000, 0, 500, 600000, 1110000, 10,
     20, 1, 4, 3600, 1, 1789376400, 1789383600, "9=50000;10=63000", "Bash=12;Read=8", 0),
    ("2026-09-15", S2, "~/p/beta", "", OPUS, 0, 4, 2000, 4000, 40000, 0, 4000, 1000, 850000, 46000, 4,
     5, 2, 2, 1800, 0, 1789480800, 1789482600, "14=50000", "Bash=5", 0),
    ("2026-09-16", S3, "~/p/beta", "", "mystery-model", 0, 1, 100, 900, 0, 0, 0, 0, 100, 100, 1,
     0, 0, 1, 600, 0, 1789599600, 1789600200, "23=1000", "", 0),
]

USAGE_LOG = """\
2026-09-14 08:15:00\tsession=10%\tresets=12:10\tweek=20%\tresets=Sep 17, 17:00\tFable=10%
2026-09-14 10:15:00\tsession=60%\tresets=12:10\tweek=24%\tresets=Sep 17, 17:00\tFable=15%
2026-09-14 11:59:00\tsession=100%\tresets=12:10\tweek=30%\tresets=Sep 17, 17:00\tFable=20%
2026-09-14 12:30:00\tREAD FAILED: the probe never rendered /usage
2026-09-14 13:15:00\tsession=5%\tresets=5:10pm\tweek=31%\tresets=Sep 17, 17:00\tFable=21%
2026-09-14 20:00:00\tsession=0%\tresets=01:00\tweek=31%\tresets=Sep 17, 17:00\tFable=21%
2026-09-17 16:00:00\tsession=40%\tresets=20:00\tweek=77%\tresets=Sep 17, 17:00\tFable=50%
2026-09-17 18:00:00\tsession=45%\tresets=20:00\tweek=2%\tresets=Sep 24, 17:00\tFable=1%
"""

WATCHDOG_LOG = """\
2026-09-14 11:00:00  wound down 1234abcd in alpha band=1 session=79% week=25% ctx=500000
2026-09-14 12:00:00  alive: 3 session(s), 0 pending schedule(s), polling every 30s
2026-09-14 12:10:40  prompted 1234abcd in alpha (pane %3) after reset 12:10pm
2026-09-14 12:10:41  prompted 5678abcd in beta (pane %4) after reset 12:10pm
2026-09-15 03:00:00  stranded: ➥➥lane-b idle 2h10m with an open handover (/x/STATUS-lane-b.md) and no pending schedule entry naming it
2026-09-15 04:00:00  no longer stranded: ➥➥lane-b is now working
2026-09-16 03:00:00  stranded: ➥➥lane-b idle 1h05m with an open handover (/x/STATUS-lane-b.md) and no pending schedule entry naming it
2026-09-16 05:00:00  wound down 1234abcd in alpha band=2 session=90% week=40% ctx=900000
"""

TREE = """\
lane-a\troot\t@1\t%1\t1789376400\tlane-a.md
lane-b\tlane-a\t@2\t%2\t1789380000\tlane-b.md
lane-c\tlane-b\t@3\t%3\t1789466400\tlane-c.md
adopted-window\tlane-a\t@4\t%4\t1789380000\t(adopted)
"""


def entry(title, launched, slug=None, parent=None):
    h = ["title: " + title]
    if slug:
        h.append("slug: " + slug)
    if parent:
        h.append("parent: " + parent)
    h += ["type: work", "status: " + ("done" if launched else "pending")]
    if launched:
        h.append("launched: " + launched)
    return "\n".join(h) + "\n---\nA synthetic prompt body.\nlaunched: 1999-01-01 00:00 is body text, not a header\n"


QUESTIONS_B = """\
# Questions from lane-b

## 1. First synthetic fork
Which way?
**Answer:** the first way.

## 2. Second synthetic fork
Which way?

3. A third, as a numbered item
Which way?
"""

QUESTIONS_A = """\
# Questions from lane-a
ANSWERED 2026-09-15

## One
?

## Two
?
"""


def build_query() -> dict:
    ledger = ["\t".join(LEDGER_COLS)] + ["\t".join(str(v) for v in r) for r in LEDGER_ROWS]
    return {
        "ledger/ledger.tsv": "\n".join(ledger) + "\n",
        "ledger/meta": "backfill\tdone\nlast_collect\t1789646400\nschema\t1\nsince\t2026-09-01\n",
        "watchdog/usage.log": USAGE_LOG,
        "watchdog/log": WATCHDOG_LOG,
        "watchdog/tree.tsv": TREE,
        "muxhome/schedules/lane-a.md": entry("lane a", "2026-09-14 08:30", slug="lane-a", parent="root"),
        "muxhome/schedules/lane-d.md": entry("lane d", "2026-09-16 08:00", slug="lane-d", parent="lane-c"),
        "muxhome/schedules/never.md": entry("never launched", None, slug="never"),
        "muxhome/schedules/long.md": entry("a title that is far too long", "2026-09-16 09:00"),
        "muxhome/handovers/done/STATUS-lane-a.md": "# lane-a\nsynthetic handover\n",
        "muxhome/handovers/done/STATUS-lane-b-20260916-120000.md": "# lane-b\nsynthetic handover\n",
        "muxhome/handovers/done/QUESTIONS-lane-a.md": QUESTIONS_A,
        "muxhome/handovers/QUESTIONS-lane-b.md": QUESTIONS_B,
    }


def main():
    for rel, text in build().items():
        p = HERE / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    print("wrote %d file(s) under %s" % (len(build()), HERE))


if __name__ == "__main__":
    main()
