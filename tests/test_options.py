#!/usr/bin/env python3
"""muxconfig.options() -- the parser, against a fixture with one of every error.

Run it:  python3 tests/test_options.py     (no pytest, no dependency)

WHY A FIXTURE FILE and not strings in here: the file is the format's spec as
much as the docstring is, and a rule that only ever sees a string built three
lines above the assertion is a rule nobody has read in the shape users write.
"""
import os
import pathlib
import shutil
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"

# key -> a distinctive fragment of the reason it must be rejected for.
EXPECTED_BAD = {
    "": "no key:",
    "Bad_Key": "is not [a-z0-9-]+",
    "neither": "exactly one of line: or set:",
    "both": "exactly one of line: or set:",
    "setnochoices": "needs choices:",
    "askwhat": "ask: must be",
    "asknovalue": "no {{VALUE}}",
    "defaultmaybe": "default: must be on or off",
    "typesall": "types: must be",
    "strayline": "not a field:",
    "twice": "label: given twice",
}
GOOD = ("good-line", "good-set")

fails = []


def check(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        fails.append(what)


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="muxopt-"))
    try:
        (tmp / "profiles").mkdir()
        shutil.copy(FIXTURES / "broken.options.md", tmp / "options.md")
        os.environ["MUXTOPUS_CONFIG"] = str(tmp / "config")
        os.environ.pop("MUXTOPUS_PROFILES_DIR", None)
        import muxconfig

        opts = muxconfig.options()
        by_key = {}
        for o in opts:
            by_key.setdefault(o["key"], []).append(o)

        print("parsed %d block(s) from the fixture" % len(opts))
        # NOTHING IS DROPPED: 15 blocks in, 15 out, broken ones included.
        check(len(opts) == 14, "every block is returned (got %d, want 14)" % len(opts))

        for key, frag in EXPECTED_BAD.items():
            got = [o["bad"] for o in by_key.get(key, [])]
            check(any(frag in b for b in got),
                  "%-13s rejected for %r (got %r)" % (key or "(no key)", frag, got))

        for key in GOOD:
            o = by_key[key][0]
            check(o["bad"] == "", "%-13s is accepted (bad=%r)" % (key, o["bad"]))

        # The duplicate is the SECOND block with that key; the first stays good.
        dups = by_key["good-line"]
        check(len(dups) == 2 and dups[0]["bad"] == ""
              and "duplicate key" in dups[1]["bad"],
              "a repeated key marks the SECOND block, not the first")

        g = by_key["good-line"][0]
        check(g["default"] is True and g["types"] == "work"
              and g["line"].endswith("literal."),
              "fields are parsed: default on, types work, line kept whole")
        check("{{SLUG}}" in g["line"], "a placeholder in a line stays literal")
        s = by_key["good-set"][0]
        check(s["choices"] == ["opus", "opus[1m]", "fable"],
              "choices split on commas (got %r)" % (s["choices"],))
        check(s["group"] == "model" and s["default"] is False,
              "a comment inside a block does not end it")

        # Defaults for absent fields.
        check(by_key["neither"][0]["types"] == "both",
              "types defaults to both")

        # ---- the profile layer: merges field by field, and can add ----
        (tmp / "profiles" / "work.options.md").write_text(
            "key: good-line\ndefault: off\n\n"
            "key: extra\nlabel: only on this account\nline: an added sentence.\n")
        wopts = muxconfig.options("work")
        # FIRST match per key: the fixture repeats good-line on purpose, and
        # the override must have landed on the good block, not on the repeat.
        wby = {}
        for o in wopts:
            wby.setdefault(o["key"], o)
        check(wby["good-line"]["default"] is False,
              "the profile file overrides one field")
        check(wby["good-line"]["line"].endswith("literal."),
              "...and LEAVES the fields it did not mention")
        check(wby["good-line"]["label"] == "a good line option",
              "...including the label")
        check("extra" in wby and wby["extra"]["bad"] == "",
              "the profile file can add an option")
        check([o["key"] for o in wopts if o["key"] == "extra"] and
              wopts[-1]["key"] == "extra",
              "an added option lands at the end, an override keeps its place")
        check(wopts[0]["key"] == "good-line",
              "file order is preserved")

        # No file at all is empty, not an exception.
        os.environ["MUXTOPUS_CONFIG"] = str(tmp / "nowhere" / "config")
        check(muxconfig.options() == [], "a missing options.md reads as no options")

        # ---- the SHIPPED table: seeds/options.md, what install.sh copies ----
        # Every block reads clean, EXCEPT that the orchestrate-only blocks may
        # be `bad` for their type and nothing else. They land in the
        # orch-templates lane as text; the orch-form lane adds "orchestrate"
        # to OPTION_TYPES, and from then on they must be clean too. Written to
        # hold either way, so the two lanes can merge in either order -- and
        # so that the moment the word is accepted, any OTHER fault in these
        # blocks (a missing {{VALUE}}, a typo'd field) fails here, because it
        # is no longer hidden behind the type complaint.
        (tmp / "seed").mkdir()
        shutil.copy(pathlib.Path(__file__).resolve().parent.parent
                    / "seeds" / "options.md", tmp / "seed" / "options.md")
        os.environ["MUXTOPUS_CONFIG"] = str(tmp / "seed" / "config")
        seed = muxconfig.options()
        sby = {o["key"]: o for o in seed}
        orch = ("cadence", "automate", "preview-gate", "plan-window",
                "rules-file", "roles", "credits")
        accepted = "orchestrate" in muxconfig.OPTION_TYPES
        type_only = "types: must be %s (got 'orchestrate')" % "/".join(muxconfig.OPTION_TYPES)
        for key in orch:
            o = sby.get(key)
            check(o is not None and o["types"] == "orchestrate"
                  and o["bad"] == ("" if accepted else type_only),
                  "seed %-12s is types: orchestrate, %s (bad=%r)"
                  % (key, "clean" if accepted else "bad for its type only",
                     o and o["bad"]))
        others = [o for o in seed if o["key"] not in orch]
        check(others and all(o["bad"] == "" for o in others),
              "every other seed block reads clean (%s)"
              % [(o["key"], o["bad"]) for o in others if o["bad"]])
        check(len(seed) == len(sby), "no key repeats in the seed")
        check([sby[k]["default"] for k in orch]
              == [False, True, True, False, True, False, False],
              "the seed's orchestrate defaults are a wave's (automate, "
              "preview-gate, rules-file on)")
        check(sby["cadence"]["ask"] == "text" and sby["credits"]["ask"] == "text",
              "cadence and credits ask for text")
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
