"""dashboard.naming -- the name a new window is OFFERED, when nobody types one.

THE NAME IS NOT DECORATION. It is the slug: the tmux window itself, the
handover file (STATUS-name.md), `handover.sh done name`, and the row an agent
is told to write its handoff into. So it is read far more often than it is
typed, and the two failures that matter are opposite ones -- a name that says
nothing about the work (three windows called `brisk-amber-otter`,
`calm-slate-heron`, `eager-umber-vole` and no way to tell which is the one you
want) and a name that says the same thing as three others (`scripts`,
`scripts-2`, `scripts-3`, which is what a counter gives you and what this
replaces).

SO: THE FOLDER, AND ONE WORD. `scripts-otter`, `muxtopus-amber`. The folder is
what the window is about; the word is what makes it this one rather than the
other two, and it is a word rather than a digit because a word can be said out
loud, typed from memory and recognised in a list -- which is the whole job a
counter does badly. The word is drawn from the lists below and CHECKED against
what is taken, so it never lands on a name that already exists.

NO DEPENDENCY. coolname, petname and haikunator all do this well, and none of
them is worth a package on a machine whose dashboard has to keep working when
the venv is broken: it is two lists and a shuffle. The lists are short words
(six letters at most) for the same reason the slug is cut to 22 -- both ends
of it are read in a tmux window name and in a table column.

    suggest(base, taken, rng=None, nonce=0) -> str   the name to offer
    words()                                 -> (adjectives, nouns)

THE SAME FOLDER AND NONCE ALWAYS OFFER THE SAME WORD, because the shuffle is
seeded from those and never from the clock: `suggest` is a pure function of
its arguments, so the dashboard's golden screens are fixed rather than a coin
flip.

THE NONCE IS THE CALLER SAYING "NOT THAT ONE". Pressing `c`, seeing
`scripts-otter` and pressing `c` again used to offer `scripts-otter` a second
time, because the only thing that moved the offer on was a name being TAKEN
-- and the name you just declined is not taken. So the form counts its own
opens and passes the count here; asking again asks for a different word,
which is what asking again means. Everything else about the seeding is
unchanged, and nonce=0 is exactly the old answer.

PURE: no I/O, no dashboard state, no Rich. `taken` is any container answering
`in`, and `rng` is a random.Random a caller (a test) can pass to override the
seeding above.
"""
from __future__ import annotations

import hashlib
import random

# The slug rule's own limit (dashboard.schedules.sanitise_slug cuts to 22),
# repeated as a number rather than imported, because this module is pure and
# the only thing it wants from that rule is how much room there is.
MAX_SLUG = 22

# Short, plain, and nothing that reads as a judgement on the work: a window
# called `failed-otter` would be a bad joke on the day it is true.
ADJECTIVES = (
    "amber", "azure", "brisk", "calm", "clear", "coral", "crisp", "deep",
    "eager", "early", "fair", "fast", "fine", "firm", "fresh", "glad",
    "grand", "green", "ivory", "keen", "kind", "lilac", "lively", "lucid",
    "mild", "neat", "noble", "north", "olive", "open", "plain", "proud",
    "quick", "quiet", "rapid", "ready", "rich", "ripe", "rosy", "royal",
    "sharp", "sleek", "slim", "smart", "solid", "spare", "steady", "still",
    "sunny", "swift", "tidy", "true", "vivid", "warm", "wise", "young",
)
# Animals and landscape, in the same register: concrete, short, and readable
# in a column that may only have room for the tail of the name.
NOUNS = (
    "badger", "beaver", "bison", "cedar", "comet", "crane", "delta", "dune",
    "ember", "falcon", "finch", "fjord", "glade", "grove", "hare", "heath",
    "heron", "ibis", "kite", "lynx", "marten", "mesa", "moss", "osprey",
    "otter", "owl", "pika", "puffin", "quail", "raven", "reef", "ridge",
    "robin", "seal", "shore", "shrew", "slate", "stoat", "storm", "tern",
    "thorn", "tide", "vale", "vole", "weasel", "willow", "wren",
)


def words() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The two lists, for a caller that wants to count them (a test does)."""
    return ADJECTIVES, NOUNS


def _stable_rng(base: str, nonce: int = 0) -> random.Random:
    """A generator seeded from `base` (and `nonce`) alone. blake2b rather than
    hash(), whose string seed is salted per PROCESS -- two `c`s either side of
    a dashboard reload would disagree, and the golden screens would be a coin
    flip.

    THE NONCE IS WHAT MAKES A SECOND LOOK A SECOND OFFER. `suggest` is still
    a pure function of its arguments -- same base, same nonce, same name, so
    the goldens stay fixed -- but the caller can now say "not that one" by
    passing a different number, which is what pressing `c` again means."""
    seed = base if not nonce else "%s\x00%d" % (base, nonce)
    digest = hashlib.blake2b(seed.encode("utf-8", "replace"), digest_size=8)
    return random.Random(int.from_bytes(digest.digest(), "big"))


def _fits(base: str, word: str) -> str:
    """`base-word` inside MAX_SLUG, with the BASE cut and never the word: a
    name cut at the other end would be two windows called `some-long-na-otter`
    and `some-long-na-heron`, which is the collision this exists to avoid --
    the word is the part that distinguishes them."""
    room = MAX_SLUG - len(word) - 1
    if room < 1:                      # a word longer than the whole slug
        return word[:MAX_SLUG]
    return "%s-%s" % (base[:room].rstrip("-."), word)


def suggest(base: str, taken=(), rng: random.Random | None = None,
            nonce: int = 0) -> str:
    """The name to offer for a new window: `base-word`, free of `taken`.

    `base` is what the folder suggests, already sanitised by the caller (this
    module has no opinion about which characters a slug may hold). An empty
    one -- a folder whose name sanitised to nothing -- gets `adjective-noun`
    instead, so there is always a name to offer and it is never empty.

    Every word is tried before any is reused: the shuffle is over the whole
    list, so the second window in a folder cannot be handed the same word as
    the first and then have to count. When the lists really are exhausted (47
    windows in one folder), it counts -- `scripts-otter-2` -- because an
    offered name that is already taken is worse than an ugly one."""
    rng = rng or _stable_rng(base, nonce)
    nouns = list(NOUNS)
    rng.shuffle(nouns)
    if base:
        for w in nouns:
            name = _fits(base, w)
            if name not in taken:
                return name
    adjectives = list(ADJECTIVES)
    rng.shuffle(adjectives)
    for a in adjectives:
        for w in nouns:
            name = _fits(a, w)
            if name not in taken:
                return name
    # Everything is taken. Count off the first candidate rather than return
    # one the caller will refuse: the caller's next move is to offer this.
    stem = _fits(base, nouns[0]) if base else _fits(ADJECTIVES[0], nouns[0])
    for n in range(2, 1000):
        name = "%s-%d" % (stem[:MAX_SLUG - len(str(n)) - 1], n)
        if name not in taken:
            return name
    return stem
