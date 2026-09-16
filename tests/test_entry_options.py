#!/usr/bin/env python3
"""What a ticked box does to a schedule ENTRY: the options: line, the set:
header fields, and the ## Options section.

Run it:  .venv/bin/python tests/test_entry_options.py
(the venv, because deck_status imports rich; the parser's own tests in
test_options.py need nothing but python3.)

THE POINT OF THIS FILE is the byte-preservation rule. `o` reopens the table on
an entry whose body is a hand-written brief, and an editor that reflowed or
re-emitted any of it is one nobody would dare press.
"""
import os
import pathlib
import shutil
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

OPTIONS_MD = """key: questions
group: contract
label: questions go to a file
default: on
line: Ask nobody; write to {{QUESTIONS}}.

key: verify
group: contract
label: verify by firing it
default: on
types: work
line: Run the thing you changed.

key: lanes
group: windows
label: parallel lanes
default: off
ask: number
line: Run at most {{VALUE}} lanes in parallel.

key: model
group: model
label: model
default: off
set: model
choices: opus, opus[1m], fable
"""

# Trailing spaces, an indent, a blank line and a non-ASCII window name are all
# deliberate: they are what a byte comparison is for.
ENTRY = ("type: work\n"
         "at: 2026-09-20 09:00\n"
         "title: a hand written entry\n"
         "slug: byte-test\n"
         "window: ➥parent\n"
         "cwd: /home/deck\n"
         "model: fable\n"
         "after: some-lane\n"
         "options: questions, model=fable\n"
         "status: pending\n"
         "created: 2026-09-16 07:00\n"
         "launched:\n"
         "---\n"
         "# The task\n"
         "\n"
         "Do the thing, carefully.   \n"
         "   an indented line, with trailing spaces above\n"
         "\n"
         "A second paragraph.\n"
         "\n"
         "## Options\n"
         "- an old sentence nobody will miss.\n"
         "- another one.\n")

fails = []


def check(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        fails.append(what)


def head_body(text):
    h, _, b = text.partition("\n---\n")
    return h, b


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="muxent-"))
    try:
        (tmp / "options.md").write_text(OPTIONS_MD)
        os.environ["MUXTOPUS_CONFIG"] = str(tmp / "config")
        import deck_status as d

        opts = d.read_options("")
        check(len(opts) == 4 and not any(o["bad"] for o in opts),
              "the fixture options.md reads clean")

        # ---- the round trip ----
        on = {"questions": True, "lanes": "3", "model": "opus[1m]"}
        line = d.options_line(opts, on)
        check(line == "questions, lanes=3, model=opus[1m]",
              "options: line is in FILE order, key=value for ask/set (%r)" % line)
        check(d.parse_options_line(line) == on, "…and reads back identically")
        check(d.options_fields(opts, on) == [("model", "opus[1m]")],
              "a set: option becomes a header field, not a line")
        sec = d.options_section(opts, on)
        check("- Run at most 3 lanes in parallel." in sec,
              "{{VALUE}} is resolved when the line is written")
        check("{{QUESTIONS}}" in sec,
              "every other placeholder stays LITERAL for the executor")
        check("model" not in sec, "a set: option contributes no sentence")

        # ---- the byte-preservation rule ----
        new, err = d.rewrite_options(ENTRY, opts, {"lanes": "3", "model": "fable"})
        check(err == "", "rewrite_options succeeds on a well formed entry")
        oh, ob = head_body(ENTRY)
        nh, nb = head_body(new)
        cut = ob.index("## Options")
        check(ob[:cut] == nb[:cut], "the body ABOVE the heading is byte-identical")
        changed = [(a, b) for a, b in zip(oh.split("\n"), nh.split("\n")) if a != b]
        check(changed == [("options: questions, model=fable", "options: lanes=3, model=fable")],
              "exactly one header line changed (%r)" % (changed,))
        check(len(oh.split("\n")) == len(nh.split("\n")),
              "no header line was added or lost")
        check(nb[cut:] == "## Options\n- Run at most 3 lanes in parallel.\n",
              "the section is regenerated whole (%r)" % nb[cut:])

        # ---- unticking a set: option drops its header field ----
        new2, _ = d.rewrite_options(new, opts, {"lanes": "3"})
        h2, b2 = head_body(new2)
        check("model: fable" not in h2, "unticking model: removes the header field")
        check("after: some-lane" in h2 and "slug: byte-test" in h2,
              "…and leaves every unrelated field alone")

        # ---- nothing ticked: line, field and section all go ----
        new3, _ = d.rewrite_options(new, opts, {})
        h3, b3 = head_body(new3)
        check(not [l for l in h3.split("\n") if l.startswith(("options:", "model:"))],
              "nothing ticked leaves no options: line and no set: field")
        check(b3 == ob[:cut], "…and the body is exactly what was above the heading")

        # ---- an entry with no section gets one appended, nothing else touched ----
        plain = ENTRY[:ENTRY.index("## Options")]
        new4, _ = d.rewrite_options(plain, opts, {"verify": True})
        h4, b4 = head_body(new4)
        check(b4.startswith(head_body(plain)[1].rstrip("\n")),
              "an absent section is APPENDED, the body above it unchanged")
        check(b4.rstrip("\n").endswith("- Run the thing you changed."),
              "…with the heading and the sentence at the end")
        check("options: verify" in h4, "…and a fresh options: line is inserted")
        check(h4.split("\n").index("options: verify")
              < h4.split("\n").index("status: pending"),
              "…ahead of the bookkeeping fields")

        # ---- a file the table cannot own ----
        _, err = d.rewrite_options("type: work\nno separator here\n", opts, {})
        check(err == "no --- separator line", "a headless file is refused, not mangled")
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
