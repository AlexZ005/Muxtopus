#!/usr/bin/env python3
"""Writes the synthetic transcripts tests/test_stats.py reads.

    python3 tests/fixtures/transcripts/make_fixtures.py     (rewrites claude/)

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

test_stats.py checks that this script still produces the committed files, so
the generator and the fixture cannot drift apart.
"""
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE / "claude"
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
    """relative path -> file content"""
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


def main():
    for rel, text in build().items():
        p = ROOT / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    print("wrote %d file(s) under %s" % (len(build()), ROOT))


if __name__ == "__main__":
    main()
