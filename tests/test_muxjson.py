#!/usr/bin/env python3
"""muxjson against the real jq, on the filters muxtopus actually writes.

DIFFERENTIAL, not expected-output. Every case below runs through BOTH jq and
muxjson.py and the two answers must match byte for byte -- because the only
thing this fallback has to be is indistinguishable from the tool it replaces
at the call sites that use it. An expected-output test would freeze my
reading of jq's semantics; this freezes jq's.

WHERE THE CASES COME FROM: each one is a filter copied out of a shipped
script, named with the file and line it came from, so a filter that changes
there without changing here is a test that stops covering it. The last block
is the refusals -- filters muxjson must reject rather than guess at, which is
the property that makes it safe to ship (see muxjson.py's docstring).

jq IS OPTIONAL HERE. Without it the differential cases skip and the refusals
still run, so this is useful on the very machines muxjson exists for.
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUXJSON = os.path.join(ROOT, "muxjson.py")
JQ = shutil.which("jq")

fails = 0
ran = 0
skipped = 0


def ok(cond, label):
    global fails, ran
    ran += 1
    if not cond:
        fails += 1
        print("FAIL  %s" % label)
    else:
        print("ok    %s" % label)


def run(cmd, stdin_text):
    p = subprocess.run(cmd, input=stdin_text, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def same(label, args, stdin_text=""):
    """jq and muxjson give the same stdout for these args."""
    global skipped
    mine = run([sys.executable, MUXJSON] + args, stdin_text)
    if not JQ:
        skipped += 1
        print("skip  %s (no jq)" % label)
        return
    theirs = run([JQ] + args, stdin_text)
    if mine[1] != theirs[1]:
        print("      jq      -> %r" % theirs[1])
        print("      muxjson -> %r" % mine[1])
        print("      stderr  -> %r" % mine[2][:200])
    ok(mine[1] == theirs[1], label)


def refuses(label, args, stdin_text=""):
    """muxjson must exit non-zero and say so, NOT invent an answer."""
    rc, out, err = run([sys.executable, MUXJSON] + args, stdin_text)
    ok(rc != 0 and out == "" and "muxjson:" in err, label)


# THE WATCHDOG'S OWN STRING, read out of the script rather than copied: this
# filter is the one whose every odd corner the tier tests below exist for,
# and a copy here would go on passing after the script's had changed.
WATCHDOG = os.path.join(ROOT, "claude-watchdog.sh")
with open(WATCHDOG, encoding="utf-8") as _fh:
    TURN_FILTER = next(line.split("=", 1)[1].strip().strip("'")
                       for line in _fh if line.startswith("TURN_FILTER="))

# ---------------------------------------------------------------- fixtures
# A transcript line, as claude-watchdog.sh's token_totals sees it.
USAGE_LINE = json.dumps({
    "type": "assistant", "timestamp": "2026-09-21T12:28:00Z",
    "message": {"model": "claude-opus-5", "usage": {
        "input_tokens": 100, "output_tokens": 20,
        "cache_creation_input_tokens": 7, "cache_read_input_tokens": 4000}}})
USER_LINE = json.dumps({"type": "user", "timestamp": "2026-09-21T12:29:00Z",
                        "message": {"role": "user"}})
NOISE_LINE = json.dumps({"type": "ai-title", "title": "no usage here"})
TRANSCRIPT = "\n".join([USAGE_LINE, USER_LINE, NOISE_LINE]) + "\n"

# A sessions/<pid>.json, as tree/session discovery reads it.
SESSION = json.dumps({"pid": 2683, "sessionId": "a351864d-3672", "cwd": "/home/user",
                      "tmux": "claude:1.%1", "version": "2.1.4",
                      "status": "running", "kind": "interactive"}) + "\n"
SESSION_SPARSE = json.dumps({"pid": 44}) + "\n"

# ~/.claude.json, as claude-usage.sh's probe_dir reads it.
CLAUDE_JSON = json.dumps({"projects": {
    "/root": {"hasTrustDialogAccepted": True},
    "/home/user": {"hasTrustDialogAccepted": False}}}) + "\n"

print("== token accounting (claude-watchdog.sh:458, :487)")
same("context_tokens: cache read + cache creation",
     ["-r", "(.message.usage.cache_read_input_tokens // 0)"
      " + (.message.usage.cache_creation_input_tokens // 0)"], TRANSCRIPT)
same("token_totals: the @tsv pair of spent and read",
     ["-r", "[ (.message.usage.input_tokens // 0)"
      " + (.message.usage.cache_creation_input_tokens // 0)"
      " + (.message.usage.output_tokens // 0),"
      " (.message.usage.cache_read_input_tokens // 0) ] | @tsv"], TRANSCRIPT)

print("== the last real turn, and what it said (claude-watchdog.sh, last_turn)")
same("last_turn: every turn a row, its timestamp and any text blocks",
     ["-r", TURN_FILTER], TRANSCRIPT)

print("== session discovery (claude-watchdog.sh:1507, :1690, :2851-2858)")
for field, filt in (("tmux", ".tmux // empty"),
                    ("sessionId", ".sessionId // empty"),
                    ("pid", ".pid // empty"),
                    ("cwd", ".cwd // empty"),
                    ("version", '.version // "?"'),
                    ("status", '.status // "?"'),
                    ("kind", '.kind // "?"')):
    same("sessions/<pid>.json: %s" % field, ["-r", filt], SESSION)
    same("sessions/<pid>.json: %s when absent" % field, ["-r", filt], SESSION_SPARSE)

print("== the model (claude-watchdog.sh:2071, claude-usage.sh:68)")
same("model_of: .message.model", ["-r", ".message.model // empty"], TRANSCRIPT)
same("usage: .model with a default", ["-r", '.model // "opus"'], SESSION)

print("== trust, the shape probe_dir needs (claude-usage.sh:111)")
same("every folder this account has accepted",
     ["-r", ".projects | .[] | .hasTrustDialogAccepted // false"], CLAUDE_JSON)
same("--arg reaches the filter",
     ["-r", "--arg", "h", "/home/user", "$h"], CLAUDE_JSON)

print("== the flags the call sites pass")
same("-r on a string drops the quotes", ["-r", ".cwd"], SESSION)
same("without -r a string keeps them", [".cwd"], SESSION)
same("-n runs once against null", ["-n", "-r", '"hello"'], "")
same("-s slurps the lines into one array", ["-s", "-r", ". | .[] | .pid // empty"],
     SESSION + SESSION_SPARSE)

print("== a half-written line is skipped, not fatal")
half = USAGE_LINE + "\n" + '{"type":"assis'
same("a torn record does not fail the scan",
     ["-r", ".type // empty"], half + "\n")
# ...and it must still be skipped now that a first line which does not parse
# switches the reader to whole-document mode. This one is in the MIDDLE, so
# it does not switch, and the lines after it are still read. NOT a
# differential case: real jq STOPS at a torn record, and skipping it is the
# deliberate difference the module docstring argues for, so this asserts
# muxtopus's own behaviour rather than jq's.
_rc, _out, _err = run([sys.executable, MUXJSON, "-r", ".type // empty"],
                      USAGE_LINE + "\n" + '{"type":"assis' + "\n" + USAGE_LINE + "\n")
ok(_out.count("assistant") == 2,
   "a torn record in the MIDDLE does not eat the lines after it")

print("== a pretty-printed reply (mux-update.sh --notes: api.github.com)")
# The bug this reader was changed for: api.github.com indents, so NOT ONE
# LINE of the reply is a whole JSON value and --notes printed "could not be
# fetched" for a release whose notes were right there.
PRETTY = ('{\n'
          '  "tag_name": "v1.2.3",\n'
          '  "draft": false,\n'
          '  "body": "## What is in it\\n\\n- a fix\\n"\n'
          '}\n')
same("the release body off a pretty-printed object", ["-r", ".body // empty"], PRETTY)
same("a field off a pretty-printed object", ["-r", ".tag_name // empty"], PRETTY)
PRETTY_LIST = ('[\n'
               '  {\n    "draft": true,\n    "tag_name": "v9.9.9"\n  },\n'
               '  {\n    "draft": false,\n    "tag_name": "v1.2.3"\n  }\n'
               ']\n')
same("the newest non-draft tag, the way resolve_tag asks for it",
     ["-r", 'map(select(.draft | not)) | .[0].tag_name // empty'], PRETTY_LIST)

print("== .[n] -- one element, and never a slice")
same(".[0] of an array", ["-r", ".forks | .[0].id // empty"],
     json.dumps({"forks": [{"id": "f1"}, {"id": "f2"}]}) + "\n")
same(".[0] past the end is null, not an error", ["-c", ".a | .[0]"],
     json.dumps({"a": []}) + "\n")
same(".[0] of a missing key is null, as jq has it", ["-c", ".nope | .[0]"],
     json.dumps({"a": []}) + "\n")

print("== the fork rows (claude-watchdog.sh:2589)")
FORKS = json.dumps({"path": "/a/b", "slug": "lane-q",
                    "forks": [{"id": "f1", "text": "one"}, {"id": "f2", "text": "two"}]}) + "\n"
same("path, slug and the fork ids joined",
     ["-r", '[.path, .slug, (.forks | map(.id) | join(","))] | @tsv'], FORKS)
same("map/join over an empty list",
     ["-r", '[.path, (.nope | map(.id) | join(","))] | @tsv'],
     json.dumps({"path": "/a", "nope": []}) + "\n")
same("length of an array", ["-r", ".forks | length"], FORKS)
same("max of a list", ["-r", "[.forks | .[] | .id] | max"], FORKS)

print("== building JSON (claude-usage.sh:401, --json)")
same("the --json object, built with -n and --arg",
     ["-c", "-n", "--arg", "sp", "42", "--arg", "sr", "18:40",
      "--arg", "wp", "7", "--arg", "wr", "Sep 28", "--arg", "m", "opus",
      "--arg", "mp", "12", "--arg", "age", "3",
      "{session:{pct:$sp,resets:$sr},week:{pct:$wp,resets:$wr},"
      "model:{name:$m,pct:$mp},age_minutes:($age|tonumber)}"], "")
same("to_entries over an object", ["-c", ".projects | to_entries"], CLAUDE_JSON)

print("== the optional steps, .[]? and .name?")
# What the SAID filter leans on. Each is a value jq would have RAISED on
# without the `?` -- and jq.py raising ends the whole read (see the jq.py
# tier block below, and last_turn's comment).
ODD = "\n".join(json.dumps(x) for x in (
    {"c": "a string"}, {"c": [1, "s", {"type": "text"}]}, {"c": None},
    {"c": {"k": "v"}}, {"nope": 1})) + "\n"
same(".[]? over a string, a list, null, an object and a missing key",
     ["-c", ".c | .[]?"], ODD)
same(".name? over the elements, whatever they are",
     ["-c", ".c | .[]? | .type?"], ODD)
same("select on .type? drops a bare string element rather than erroring",
     ["-c", '.c | .[]? | select(.type? == "text")'], ODD)
same(".[0]? of a string is nothing, of null is null",
     ["-c", ".c | .[0]?"], ODD)

print("== REFUSALS -- a filter it cannot do must never be guessed at")
refuses("if/then/else", ["-r", "if .a then .b else .c end"], "{}\n")
refuses("split()", ["-r", '.a | split("||")'], "{}\n")
refuses("assignment", ["-r", ".a = true"], "{}\n")
refuses("string slicing", ["-r", ".a | .[0:10]"], "{}\n")
# .[0] exists now; a SLICE still does not, and indexing an object is jq's
# own error rather than something to guess a null for.
refuses("slicing, now that .[0] parses", ["-r", ".a | .[1:2]"],
        '{"a":[1,2,3]}\n')
refuses("indexing an object with a number", ["-r", ".a | .[0]"],
        '{"a":{"b":1}}\n')
refuses("an unknown flag", ["-X", "."], "{}\n")
refuses("an unknown @format", ["-r", ". | @csv"], "[]\n")
refuses("$var that was never passed", ["-r", "$nope"], "{}\n")

# ---------------------------------------------------- the jq.py middle tier
# profile.sh reaches for libjq (the `jq` PyPI wheel) before this file's own
# parser. Where it is installed, --via-jq-py must agree with the real jq --
# including on filters the parser below deliberately refuses, which is the
# entire reason that tier exists.
print("== the jq.py tier (--via-jq-py), where the wheel is installed")
HAVE_JQPY = subprocess.run([sys.executable, "-c", "import jq"],
                           capture_output=True).returncode == 0
if not HAVE_JQPY:
    skipped += 1
    print("skip  jq.py is not installed for %s" % os.path.basename(sys.executable))
elif not JQ:
    skipped += 1
    print("skip  no jq to compare against")
else:
    for label, args, data in (
            ("a core filter", ["-r", ".sessionId // empty"], SESSION),
            ("arithmetic", ["-r", "(.message.usage.input_tokens // 0)"
                            " + (.message.usage.output_tokens // 0)"], TRANSCRIPT),
            ("if/then/else -- REFUSED by the parser, fine here",
             ["-r", 'if .pid then "has-pid" else "none" end'], SESSION),
            ("split() -- likewise", ["-c", '.cwd | split("/")'], SESSION)):
        mine = run([sys.executable, MUXJSON, "--via-jq-py"] + args, data)
        theirs = run([JQ] + args, data)
        if mine[1] != theirs[1]:
            print("      jq    -> %r" % theirs[1])
            print("      jq.py -> %r / %r" % (mine[1], mine[2][:120]))
        ok(mine[1] == theirs[1], "jq.py matches jq: %s" % label)

# ------------------------------------------ SAID: one filter, three tiers
# The whole of last_turn -- the filter, the awk fold and the bash cut -- run
# against tests/fixtures/said/transcript.jsonl with mux_json pinned to each
# tier in turn. The fixture is built to hit every corner at once: a text
# block that is NOT the last turn (a tool_use-only record and a user turn
# with string content come after it), a tab, a CRLF, a newline, multi-byte
# characters that land on the cut, a backslash and a literal backslash-n
# (which must survive as two characters, not become a space), and more than
# eighty characters. Every tier must give the SAME epoch and digest, and the
# digest is also asserted outright, so "all three agree on something wrong"
# is not a pass.
print("== SAID: last_turn through all three tiers")
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "said", "transcript.jsonl")
WANT_AT = "1790157612"          # 2026-09-23T10:00:12Z, the last user turn
WANT_SAID = ("P1 is in: the digest folds a tab, a newline and keeps "
             "\u00e9\u00e8\u00e7 \u2014 \u2713 whole; a back\\slas")


def last_turn_via(mux_json_body, path, lc_all=None):
    """(rc, TURN_AT, TURN_SAID) from the script's own last_turn, with
    mux_json replaced by the given body. The functions are cut out of the
    script by their comment fences, so this runs the shipped text."""
    with open(WATCHDOG, encoding="utf-8") as fh:
        src = fh.read()
    start = src.index("TURN_FILTER=")
    end = src.index("# One field out of the usage cache.")
    script = ("mux_json() { %s; }\n%s\nlast_turn %s; rc=$?\n"
              "printf '%%s\\t%%s\\t%%s' \"$rc\" \"$TURN_AT\" \"$TURN_SAID\"\n"
              % (mux_json_body, src[start:end], _sh(path)))
    env = dict(os.environ)
    if lc_all is not None:
        env["LC_ALL"] = lc_all
        env.pop("LANG", None)
    p = subprocess.run(["bash", "-c", script], capture_output=True, env=env)
    out = p.stdout.decode("utf-8", "replace").split("\t")
    return tuple(out) if len(out) == 3 else (p.stderr.decode()[:200], "", "")


def _sh(x):
    return "'" + x.replace("'", "'\\''") + "'"


TIERS = []
if JQ:
    TIERS.append(("jq", 'command jq "$@"'))
else:
    skipped += 1
    print("skip  SAID via the real jq: jq is not installed")
if HAVE_JQPY:
    TIERS.append(("jq.py", '%s %s --via-jq-py "$@"' % (_sh(sys.executable), _sh(MUXJSON))))
else:
    skipped += 1
    print("skip  SAID via jq.py: the jq wheel is not installed for %s"
          % os.path.basename(sys.executable))
TIERS.append(("muxjson.py", '%s %s "$@"' % (_sh(sys.executable), _sh(MUXJSON))))

for name, body in TIERS:
    rc, at, said = last_turn_via(body, FIXTURE)
    ok(rc == "0" and at == WANT_AT,
       "%s: the epoch is the last TURN's, past the tool call and the metadata (%r)" % (name, at))
    ok(said == WANT_SAID,
       "%s: the digest is the last TEXT, folded, cut to 80 characters (%r)" % (name, said))
    ok(len(said) == 80, "%s: ...eighty characters, not eighty bytes (%d)" % (name, len(said)))

# The daemon's locale is not ours to choose: on a fresh box it may have no
# LANG at all. The cut is still by character.
rc, at, said = last_turn_via(TIERS[-1][1], FIXTURE, lc_all="C")
ok(said == WANT_SAID, "under LC_ALL=C the cut is still by character (%d chars)" % len(said))

# Nothing to say is `-`, never an empty field: a transcript whose window
# holds no text block at all, and an empty file.
_tmp = os.path.join(os.path.dirname(FIXTURE), ".no-text.jsonl.tmp")
try:
    with open(_tmp, "w") as fh:
        fh.write(json.dumps({"type": "assistant", "timestamp": "2026-09-23T10:00:00Z",
                             "message": {"content": [{"type": "tool_use", "id": "x"}]}}) + "\n")
    rc, at, said = last_turn_via(TIERS[-1][1], _tmp)
    ok(at == "1790157600" and said == "-",
       "a window with no text block: the epoch, and SAID is '-' (%r)" % said)
    # A literal backslash-n is two characters of text and stays two: @tsv
    # writes it as \\n, and only the fold's split on \\ pairs keeps it from
    # being read as the escape of a newline.
    with open(_tmp, "w") as fh:
        fh.write(json.dumps({"type": "assistant", "timestamp": "2026-09-23T10:00:00Z",
                             "message": {"content": [{"type": "text",
                                                      "text": "C:\\new\\\tdir\n\nok"}]}}) + "\n")
    rc, at, said = last_turn_via(TIERS[-1][1], _tmp)
    ok(said == "C:\\new\\ dir ok",
       "a literal backslash-n survives; a real tab and newlines fold, runs squeezed (%r)" % said)
    with open(_tmp, "w") as fh:
        pass
    rc, at, said = last_turn_via(TIERS[-1][1], _tmp)
    ok(rc == "1" and at == "" and said == "-",
       "an empty transcript: no epoch (rc 1, as before) and SAID is '-'")
finally:
    os.unlink(_tmp)

print("\n%d checks, %d failed, %d skipped%s"
      % (ran, fails, skipped, "" if JQ else " (jq not installed here)"))
sys.exit(1 if fails else 0)
