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

print("== the last real turn (claude-watchdog.sh:514)")
same("last_turn_epoch: assistant or user, its timestamp",
     ["-r", 'select(.type=="assistant" or .type=="user") | .timestamp // empty'],
     TRANSCRIPT)

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

print("\n%d checks, %d failed, %d skipped%s"
      % (ran, fails, skipped, "" if JQ else " (jq not installed here)"))
sys.exit(1 if fails else 0)
