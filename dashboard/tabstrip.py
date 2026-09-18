"""tabstrip -- the tab strip, fitted to a width. Pure: no dashboard state.

The strip is drawn as the first panel's TITLE (App.tab_strip), and a title
that does not fit is not wrapped by Rich, it is cut -- so on an 80-column
client the tabs past the cut simply vanished, and so did any sign that they
were there. This module decides what to draw instead, in a fixed order:

    1. every tab, full labels            "▸schedules 6 │ handovers 4 open · 3 ?"
    2. every tab, short labels           "▸sched 6 │ hand 4 · 3?"
    3. every tab, initials (the active   "▸sched 6 │ h? │ d │ …"
       tab keeps its short label)
    4. every tab, initials               "▸s │ h? │ d │ …"
    5. SCROLL: the first LOCKED tabs stay, the rest is a window that holds
       the active tab, with a count of what is off each side:
                                         "s │ h? │ a │ b │ c │ d │ «2 │ ▸g │ 1»"
    6. the same, with one-column separators  "s│h?│a│b│c│d│«2│▸g│1»"

LABELS DEGRADE BEFORE TABS DISAPPEAR: nothing scrolls until even initials do
not fit. The locked tabs are the first LOCKED (six) of the strip as the App
hands it over -- after the user's hidden tabs are taken out, so hiding one
is what lets the seventh in (see App.visible_tabs, and the help).

A tab is (full, short, initial). The strip is a list of Rich markup pieces
joined here, so its WIDTH is counted on the text, never on the markup.

    fit(tabs, active, width, locked=LOCKED) -> Strip
    Strip.markup      the title, as markup
    Strip.shown       indexes drawn, in order
    Strip.left/right  how many scrolled tabs are hidden on each side
"""
from __future__ import annotations

from dataclasses import dataclass, field

from rich.markup import escape

LOCKED = 6
SEP = " │ "
SEP_TIGHT = "│"
DIM = "grey42"
ACCENT = "#c9a0dc"

# (tier for every other tab, tier for the active one). 0 full, 1 short,
# 2 initial. The active tab is the one you are reading, so it is the last to
# lose its name: step 3 keeps it short while the others go to initials.
TIERS = ((0, 0), (1, 1), (2, 1), (2, 2))


@dataclass
class Strip:
    markup: str
    shown: list = field(default_factory=list)
    left: int = 0
    right: int = 0
    tier: int = 0

    @property
    def scrolled(self) -> bool:
        return bool(self.left or self.right)


def _label(tab: tuple, tier: int) -> str:
    # A view that gives no short label or initial gets the next longer one;
    # every tier is at least one character, so a tab never draws as nothing.
    for t in range(tier, -1, -1):
        if t < len(tab) and tab[t]:
            return tab[t]
    return "?"


def _marker(n: int, left: bool) -> str:
    return ("«%d" % n) if left else ("%d»" % n)


def _render(pieces: list, sep: str = SEP) -> str:
    """pieces: [(text, kind)] with kind in active / tab / more."""
    out = []
    for text, kind in pieces:
        if kind == "active":
            out.append("[bold]▸%s[/]" % escape(text))
        elif kind == "more":
            out.append("[%s]%s[/]" % (ACCENT, escape(text)))
        else:
            out.append("[%s]%s[/]" % (DIM, escape(text)))
    return ("[%s]%s[/]" % (DIM, sep)).join(out)


def fit(tabs: list, active: int, width: int, locked: int = LOCKED) -> Strip:
    n = len(tabs)
    if n == 0:
        return Strip("")
    active = max(0, min(active, n - 1))
    every = list(range(n))

    # 1-4: everything, degrading the labels.
    for k, tier in enumerate(TIERS):
        pieces = _pieces(tabs, active, tier, n, n, n)
        if plain_width(pieces) <= width:
            return Strip(_render(pieces), shown=every, tier=k)

    # 5: scroll, in initials -- the tier step 4 ended on, so a narrower
    # terminal never draws a LONGER label than a wider one did. Only the
    # tabs past the locked ones ever leave the strip.
    # 6: the same with a one-column separator, which is what lets twelve
    # tabs keep a whole strip on a 40-column client.
    head = list(range(min(locked, n)))
    nh = len(head)
    last = len(TIERS) - 1
    for sep in (SEP, SEP_TIGHT):
        span = _window(tabs, active, TIERS[last], nh, width, sep)
        if span is not None:
            a, b = span
            return Strip(_render(_pieces(tabs, active, TIERS[last], nh, a, b), sep),
                         shown=head + list(range(a, b)), left=a - nh,
                         right=n - b, tier=last)

    # Narrower than the locked tabs' initials plus the active one: draw them
    # anyway and let the title be cut. The ACTIVE tab is still drawn -- a
    # strip that does not show where you are is worse than one that is cut.
    a, b = (active, active + 1) if active >= nh else (nh, nh)
    return Strip(_render(_pieces(tabs, active, TIERS[last], nh, a, b), SEP_TIGHT),
                 shown=head + list(range(a, b)), left=a - nh, right=n - b,
                 tier=last)


def _pieces(tabs, active, tier, nhead, a, b) -> list:
    """The locked tabs, then «N, then the window [a, b), then N»."""
    n = len(tabs)
    kind = lambda i: "active" if i == active else "tab"          # noqa: E731
    out = [(_label(tabs[i], tier[1] if i == active else tier[0]), kind(i))
           for i in range(nhead)]
    if a > nhead:
        out.append((_marker(a - nhead, True), "more"))
    out += [(_label(tabs[i], tier[1] if i == active else tier[0]), kind(i))
            for i in range(a, b)]
    if b < n:
        out.append((_marker(n - b, False), "more"))
    return out


def plain_width(pieces: list, sep: str = SEP) -> int:
    """What _render(pieces, sep) takes on screen, markup aside."""
    return (sum(len(t) for t, _k in pieces) + len(sep) * max(0, len(pieces) - 1)
            + sum(1 for _t, k in pieces if k == "active"))


def _window(tabs, active, tier, nhead, width, sep):
    """The widest run [a, b) past the locked tabs that holds the active tab
    -- or starts at the first scrolled tab when the active one is locked --
    and fits with its markers. None when not even that fits.

    Measured on the pieces themselves, markers included: a strip one column
    too wide is the bug this module exists to fix."""
    n = len(tabs)
    if nhead >= n:
        return None
    fits = lambda a, b: plain_width(                              # noqa: E731
        _pieces(tabs, active, tier, nhead, a, b), sep) <= width
    # On a locked tab the window may be empty: a count alone.
    a, b = (active, active + 1) if active >= nhead else (nhead, nhead)
    if not fits(a, b):
        return None
    # Grow right first (what → reaches next), then left, while it fits.
    while True:
        if b < n and fits(a, b + 1):
            b += 1
        elif a > nhead and fits(a - 1, b):
            a -= 1
        else:
            return a, b
