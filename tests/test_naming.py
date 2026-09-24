#!/usr/bin/env python3
"""dashboard.naming -- the name `c` offers when nobody types one.

    python3 tests/test_naming.py        (no dependency beyond python3)

WHAT THIS HAS TO GUARANTEE, because the form presses enter on it:

  it is free        an offered name that is already a window or a pending
                    entry is worse than no offer -- the prompt would refuse
                    its own suggestion, in front of somebody who pressed
                    enter to avoid thinking about it.
  it fits           the slug is cut to MAX_SLUG (32) characters by the
                    executor's own rule, and a name cut there is a name that
                    stops being unique: a long folder plus `-otter` and the
                    same folder plus `-heron` both lose the word and become
                    the same 32 characters. The FOLDER is what gets cut
                    instead.
  it is a slug      only the characters sanitise_slug keeps, so what is
                    offered is what is used, unchanged.
"""
import pathlib
import random
import string
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dashboard import naming                                # noqa: E402
from dashboard.schedules import sanitise_slug               # noqa: E402

n = 0
fails = 0


def ok(cond, what):
    global n, fails
    n += 1
    if cond:
        print("ok   " + what)
    else:
        fails += 1
        print("FAIL " + what)


adjectives, nouns = naming.words()
ok(len(set(adjectives)) == len(adjectives)
   and len(set(nouns)) == len(nouns), "no word appears twice in its list")
ok(all(w == sanitise_slug(w) and w.islower() for w in adjectives + nouns),
   "every word is already a slug, lowercase")
ok(len(adjectives) * len(nouns) > 2000,
   "%d x %d pairs, so the no-folder case is not a small pool"
   % (len(adjectives), len(nouns)))

# ---- the shape of one name ------------------------------------------------
rng = random.Random(7)
name = naming.suggest("scripts", (), rng)
ok(name.startswith("scripts-") and name.split("-")[-1] in nouns,
   "the folder and one word: %r" % name)
ok(name == sanitise_slug(name), "and it is a slug already: %r" % name)

# ---- the same folder always offers the same word --------------------------
# Not decoration: `c`, esc, `c` must offer the same window, and the golden
# screens cannot photograph a coin flip.
ok(len({naming.suggest("scripts", ()) for _ in range(20)}) == 1,
   "unseeded, one folder gives one answer: %r" % naming.suggest("scripts", ()))
ok(naming.suggest("scripts", ()) != naming.suggest("muxtopus", ()),
   "and two folders do not collide on the same word")

# ---- it is never one that is taken ----------------------------------------
taken = set()
for _ in range(len(nouns)):
    got = naming.suggest("scripts", taken, random.Random(1))
    ok_unique = got not in taken
    taken.add(got)
    if not ok_unique:
        break
ok(len(taken) == len(nouns),
   "every word is used before any is repeated: %d names, all different"
   % len(taken))
ok(naming.suggest("scripts", taken, random.Random(1)) not in taken,
   "and past the end of the list it counts rather than repeat")

# ---- the cut falls on the folder, never on the word -----------------------
long_base = "a-very-long-repository-name-indeed"
got = naming.suggest(long_base, (), random.Random(3))
ok(len(got) <= naming.MAX_SLUG, "a long folder still fits in %d: %r (%d)"
   % (naming.MAX_SLUG, got, len(got)))
ok(got.split("-")[-1] in nouns, "with the WORD intact and the folder cut: %r" % got)
two = {naming.suggest(long_base, set(), random.Random(s)) for s in range(40)}
ok(len(two) > 1, "so two windows in that folder still differ (%d seen)" % len(two))

# ---- a folder that suggests nothing ---------------------------------------
pair = naming.suggest("", (), random.Random(5))
bits = pair.split("-")
ok(len(bits) == 2 and bits[0] in adjectives and bits[1] in nouns,
   "an empty folder gets adjective-noun: %r" % pair)
ok(naming.suggest("", ()) != "", "and never an empty name")

# ---- nothing but slug characters, whatever it is handed -------------------
messy = "".join(c for c in string.printable if c not in "\t\n\r\x0b\x0c")
got = naming.suggest(sanitise_slug(messy), (), random.Random(9))
ok(got == sanitise_slug(got) and len(got) <= naming.MAX_SLUG,
   "a sanitised folder of every printable character still gives a slug: %r" % got)

print()
print("%d assertions, %s" % (n, "all passed" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
