#!/usr/bin/env python3
"""muxjson -- the jq muxtopus falls back to when the machine has none.

NOT A jq CLONE, and the difference is the whole design. jq is a real
language; this understands the handful of filter shapes muxtopus actually
writes -- a dotted path (and its `?` form), a default, some arithmetic,
`select`, `@tsv` and an array -- and REFUSES anything else with a message naming the filter. That
refusal is the point. A fallback that guessed at a filter it did not
understand would hand the watchdog a plausible wrong number (an empty token
count, a session id that is not there) and nothing anywhere would say so,
which is far worse than the missing tool it is standing in for.

WHY IT EXISTS. jq is reached for at ~60 call sites across six shipped
scripts and only three of them ever checked whether it was installed. On a
box without it the watchdog cannot read sessions/<pid>.json, so it finds no
sessions, no tokens and no model -- and reports that as "0 session(s)"
rather than as a missing dependency. Measured on a fresh Ubuntu box: jq
absent, install.sh warned once and carried on, and every usage figure on the
dashboard was blank for two hours with nothing saying why.

WHY NOT JUST REQUIRE jq. Muxtopus already carries its own CPython when the
machine's is too old (install.sh, "Python"), for exactly the same reason it
should carry this: the tool's promise is that it works on a box you cannot
install packages on. A dependency it can supply itself is not a dependency.

THE SHELL SIDE is `mux_json` in profile.sh, and it has THREE TIERS:

    jq            the real thing, whenever the machine has it
    jq.py         libjq via the `jq` PyPI wheel, when it happens to be
                  importable -- reached here as --via-jq-py, which runs the
                  filter through libjq and never touches the parser below
    muxjson.py    this file: stdlib only, always present, deliberately small

So the parser below is the LAST resort, not the usual one, and it only has to
cover what the last resort must do -- the core reads (sessions, tokens, the
model, the usage figures). An exotic filter on a machine with either of the
first two tiers is jq's problem, not this file's, which is what stops this
growing every time a call site wants something new. pyjq was considered and
rejected: one macOS wheel on PyPI, a source build of jq and oniguruma
everywhere else.

    muxjson [--via-jq-py] [-r] [-c] [-n] [-s] [--arg NAME VALUE] FILTER [FILE...]

    -r  raw output: a string result is printed without its quotes
    -c  accepted and ignored -- this never pretty-prints, so it is already
        what -c asks for. Taken so a call site can pass jq's flags as-is.
    -n  no input: run the filter once against null (jq -n)
    -s  slurp: read every input value into one array before filtering

INPUT IS ONE JSON VALUE PER LINE, which is what almost every muxtopus call
site feeds it (a .jsonl transcript, a sessions/<pid>.json). A blank line is
skipped; a line that is not JSON is skipped too, because a poll that lands
mid-write catches half a record and that one record is not worth failing the
whole scan for (claude-watchdog.sh, token_totals).

A CURL BODY IS THE EXCEPTION, and it cost a release to find: api.github.com
pretty-prints, so its `{` sits on a line of its own and NOT ONE LINE of the
reply parses. Read per line, a release with notes came out as no notes at
all. So when the first non-blank line is not a whole value, the input is
read as a stream of values separated by whitespace -- which is what jq does
for every input, and is the only reading under which both shapes work. The
line rule stays for everything after that first line: see read_values.
"""
from __future__ import annotations

import json
import sys

MISSING = object()          # distinct from None, which is a real JSON null


class Unsupported(Exception):
    """A filter this does not implement. Always fatal, never guessed at."""


# --------------------------------------------------------------- the lexer
# Small enough to be one function. The only subtlety is that `.foo` is TWO
# tokens to the parser ('.' then the name) but `//` is one, so the two-char
# operators are tried before the one-char ones.
_PUNCT2 = ("//", "==", "!=")
_PUNCT1 = ".|+[],(){}:?"


def tokenise(src: str) -> list:
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c.isspace():
            i += 1
            continue
        if src.startswith(_PUNCT2, i):
            out.append(("op", src[i:i + 2]))
            i += 2
            continue
        if c in _PUNCT1:
            out.append(("op", c))
            i += 1
            continue
        if c == '"':
            j, buf = i + 1, []
            while j < n and src[j] != '"':
                if src[j] == "\\" and j + 1 < n:
                    buf.append(src[j + 1])
                    j += 2
                    continue
                buf.append(src[j])
                j += 1
            if j >= n:
                raise Unsupported("unterminated string")
            out.append(("str", "".join(buf)))
            i = j + 1
            continue
        if c == "@":
            j = i + 1
            while j < n and src[j].isalpha():
                j += 1
            out.append(("fmt", src[i:j]))
            i = j
            continue
        if c == "$":
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            out.append(("var", src[i + 1:j]))
            i = j
            continue
        if c.isdigit():
            j = i
            while j < n and (src[j].isdigit() or src[j] == "."):
                j += 1
            text = src[i:j]
            out.append(("num", float(text) if "." in text else int(text)))
            i = j
            continue
        if c.isalpha() or c == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] in "_-"):
                j += 1
            out.append(("name", src[i:j]))
            i = j
            continue
        raise Unsupported("cannot read %r in the filter" % c)
    return out


# -------------------------------------------------------------- the parser
# Recursive descent, loosest operator first: pipe, then //, then +. Each node
# is a callable taking (value, args) and returning a LIST of results, because
# `.[]` and `select` are the two filters that do not return exactly one.
class Parser:
    def __init__(self, toks: list, src: str) -> None:
        self.toks, self.i, self.src = toks, 0, src

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def take(self, kind=None, text=None):
        k, t = self.peek()
        if kind and (k != kind or (text is not None and t != text)):
            raise Unsupported("expected %s %r, found %r" % (kind, text, t))
        self.i += 1
        return t

    def at(self, kind, text=None) -> bool:
        k, t = self.peek()
        return k == kind and (text is None or t == text)

    # pipe: a | b | c
    def parse(self):
        node = self.parse_alt()
        while self.at("op", "|"):
            self.take()
            right = self.parse_alt()
            node = _pipe(node, right)
        return node

    # alternative: a // b -- b is used when a is absent, null or false
    def parse_alt(self):
        node = self.parse_sum()
        while self.at("op", "//"):
            self.take()
            node = _alt(node, self.parse_sum())
        return node

    # sum: a + b, on numbers and on strings
    def parse_sum(self):
        node = self.parse_term()
        while self.at("op", "+"):
            self.take()
            node = _add(node, self.parse_term())
        return node

    def parse_term(self):
        k, t = self.peek()
        if k == "op" and t == "(":
            self.take()
            node = self.parse()
            self.take("op", ")")
            return node
        if k == "op" and t == "[":
            self.take()
            parts = [self.parse()]
            while self.at("op", ","):
                self.take()
                parts.append(self.parse())
            self.take("op", "]")
            return _array(parts)
        if k == "op" and t == "{":
            self.take()
            pairs = []
            while not self.at("op", "}"):
                kk, kt = self.peek()
                if kk not in ("name", "str"):
                    raise Unsupported("an object key must be a name or a string")
                self.take()
                self.take("op", ":")
                pairs.append((kt, self.parse()))
                if self.at("op", ","):
                    self.take()
            self.take("op", "}")
            return _object(pairs)
        if k == "op" and t == ".":
            return self.parse_path()
        if k == "str":
            self.take()
            return _const(t)
        if k == "num":
            self.take()
            return _const(t)
        if k == "var":
            self.take()
            return _var(t)
        if k == "fmt":
            self.take()
            if t != "@tsv":
                raise Unsupported("%s is not implemented (only @tsv)" % t)
            return _tsv()
        if k == "name":
            self.take()
            if t == "empty":
                return lambda v, a: []
            if t == "not":
                return lambda v, a: [not _truthy(v)]
            if t == "select":
                self.take("op", "(")
                cond = self.parse_cond()
                self.take("op", ")")
                return _select(cond)
            if t == "map":
                self.take("op", "(")
                inner = self.parse()
                self.take("op", ")")
                return _map(inner)
            if t == "join":
                self.take("op", "(")
                sep = self.parse()
                self.take("op", ")")
                return _join(sep)
            if t == "tonumber":
                return _tonumber()
            if t == "to_entries":
                return _to_entries()
            if t == "length":
                return _length()
            if t == "max":
                return _max()
            if t in ("true", "false"):
                return _const(t == "true")
            if t == "null":
                return _const(None)
            raise Unsupported("%s() is not implemented" % t)
        raise Unsupported("cannot parse the filter near %r" % (t,))

    # .a.b, .[], .[0] and a bare . -- the identity
    def parse_path(self):
        steps = []
        while self.at("op", "."):
            self.take()
            if self.at("name"):
                steps.append(("field", self.take()))
            elif self.at("op", "["):
                self.take()
                if self.at("num"):
                    # .[0] -- ONE ELEMENT, not a slice. `.[0:10]` gets as far
                    # as the ':' and then take("op", "]") refuses it, which is
                    # the behaviour tests/test_muxjson.py pins: a filter this
                    # cannot do is named, never guessed at.
                    steps.append(("index", self.take()))
                else:
                    steps.append(("iter", None))
                self.take("op", "]")
            else:
                break                      # a lone '.', the identity
            # `.[]?` and `.name?` -- jq's "no error here": a step that would
            # have failed on this value yields NOTHING instead. The watchdog's
            # SAID filter needs it on `.message.content | .[]?`, and the reason
            # is a measured difference between the tiers, not taste: fed an
            # assistant record whose content is a string, the real jq drops
            # that one record with an error, THIS parser yields nothing for it
            # -- and jq.py raises, which ends the whole read, so the idle
            # column and the digest both went blank for a single odd record.
            # With the `?` all three agree (tests/test_muxjson.py pins it).
            if self.at("op", "?"):
                self.take()
                kind, name = steps[-1]
                steps[-1] = (kind + "?", name)
        return _path(steps)

    # select's argument: comparisons joined by and/or. Deliberately flat --
    # every condition muxtopus writes is, and a precedence bug in a fallback
    # nobody watches would be a silent wrong answer.
    def parse_cond(self):
        node = self.parse_cmp()
        while self.at("name", "and") or self.at("name", "or"):
            which = self.take()
            right = self.parse_cmp()
            node = _andor(node, right, which)
        return node

    def parse_cmp(self):
        left = self.parse_alt()
        if self.at("op", "==") or self.at("op", "!="):
            op = self.take()
            right = self.parse_alt()
            return _cmp(left, right, op)
        if self.at("op", "|"):
            self.take()
            self.take("name", "not")
            return lambda v, a: [not _truthy(x) for x in left(v, a)]
        return lambda v, a: [_truthy(x) for x in left(v, a)]


# ----------------------------------------------------------- the node kinds
def _first(results):
    return results[0] if results else MISSING


def _truthy(v) -> bool:
    return v is not MISSING and v is not None and v is not False


def _const(value):
    return lambda v, a: [value]


def _var(name):
    def run(v, a):
        if name not in a:
            raise Unsupported("$%s was never passed with --arg" % name)
        return [a[name]]
    return run


def _path(steps):
    def run(v, a):
        cur = [v]
        for kind, name in steps:
            nxt = []
            for item in cur:
                if kind.endswith("?"):
                    # The optional forms: what the plain step does where it
                    # works, and NOTHING -- not null, not an error -- where
                    # jq would have raised. A null is not an error in jq for
                    # any of the three (null | .a, .[0] are null; .[] on null
                    # IS one, and `?` makes it empty), so null falls through
                    # to the plain step for .a and .[0].
                    base = kind[:-1]
                    if base == "iter" and not isinstance(item, (list, dict)):
                        continue
                    if base == "field" and not (
                            isinstance(item, dict) or item is None
                            or item is MISSING):
                        continue
                    if base == "index" and not (
                            isinstance(item, list) or item is None
                            or item is MISSING):
                        continue
                    kind_now = base
                else:
                    kind_now = kind
                if kind_now == "iter":
                    if isinstance(item, list):
                        nxt.extend(item)
                    elif isinstance(item, dict):
                        nxt.extend(item.values())
                    continue
                if kind_now == "index":
                    # jq's three answers, measured against jq 1.8: an index
                    # off either end of an ARRAY is null, an index of null is
                    # null, and an index of anything else is an ERROR. The
                    # first two are what let `.[0].tag_name // empty` fall
                    # through to empty on an empty releases list; the third is
                    # refused here rather than guessed at, which is this
                    # file's whole charter. (The tokeniser has no minus, so a
                    # negative index never reaches this; the bound below is
                    # written to be right either way.)
                    if item is None or item is MISSING:
                        nxt.append(None)
                        continue
                    if not isinstance(item, list):
                        raise Unsupported(
                            "cannot index %s with a number"
                            % type(item).__name__)
                    i = int(name)
                    nxt.append(item[i] if -len(item) <= i < len(item) else None)
                    continue
                if isinstance(item, dict):
                    nxt.append(item.get(name, MISSING))
                else:
                    nxt.append(MISSING)
            cur = nxt
        return cur
    return run


def _pipe(left, right):
    def run(v, a):
        out = []
        for item in left(v, a):
            out.extend(right(item, a))
        return out
    return run


def _alt(left, right):
    def run(v, a):
        kept = [x for x in left(v, a) if _truthy(x)]
        return kept if kept else right(v, a)
    return run


def _add(left, right):
    def run(v, a):
        x, y = _first(left(v, a)), _first(right(v, a))
        x = 0 if x is MISSING or x is None else x
        y = 0 if y is MISSING or y is None else y
        if isinstance(x, str) or isinstance(y, str):
            return ["%s%s" % (x, y)]
        if isinstance(x, list) and isinstance(y, list):
            return [x + y]
        return [x + y]
    return run


def _array(parts):
    def run(v, a):
        out = []
        for p in parts:
            out.extend(x for x in p(v, a) if x is not MISSING)
        return [out]
    return run


def _select(cond):
    def run(v, a):
        return [v] if _truthy(_first(cond(v, a))) else []
    return run


def _cmp(left, right, op):
    def run(v, a):
        x, y = _first(left(v, a)), _first(right(v, a))
        x = None if x is MISSING else x
        y = None if y is MISSING else y
        return [(x == y) if op == "==" else (x != y)]
    return run


def _andor(left, right, which):
    def run(v, a):
        x = _truthy(_first(left(v, a)))
        y = _truthy(_first(right(v, a)))
        return [(x and y) if which == "and" else (x or y)]
    return run


def _map(inner):
    """map(f) is jq's own [.[] | f] -- over an array's items, or an object's
    values, which is what `.[]` means for each of them."""
    def run(v, a):
        if isinstance(v, dict):
            items = list(v.values())
        elif isinstance(v, list):
            items = v
        else:
            raise Unsupported("map() needs an array")
        out = []
        for item in items:
            out.extend(x for x in inner(item, a) if x is not MISSING)
        return [out]
    return run


def _join(sep_node):
    def run(v, a):
        if not isinstance(v, list):
            raise Unsupported("join() needs an array")
        sep = _first(sep_node(v, a))
        sep = "" if sep is MISSING or sep is None else str(sep)
        # jq drops null and renders the rest as strings.
        return [sep.join("" if c is None else
                         ("true" if c is True else "false" if c is False else str(c))
                         for c in v if c is not MISSING)]
    return run


def _object(pairs):
    """{k: f, ...}. One result, built from the FIRST result of each value --
    jq would give the cartesian product of several, which no call site here
    wants and which would silently multiply output if one ever did."""
    def run(v, a):
        out = {}
        for key, node in pairs:
            val = _first(node(v, a))
            out[key] = None if val is MISSING else val
        return [out]
    return run


def _tonumber():
    def run(v, a):
        if isinstance(v, bool) or v is MISSING or v is None:
            raise Unsupported("tonumber on %r" % (v,))
        if isinstance(v, (int, float)):
            return [v]
        try:
            return [int(v)]
        except (TypeError, ValueError):
            pass
        try:
            return [float(v)]
        except (TypeError, ValueError):
            raise Unsupported("tonumber: %r is not a number" % (v,))
    return run


def _to_entries():
    """{"a":1} -> [{"key":"a","value":1}]. jq's own key order is the object's,
    which for us is json.loads' insertion order -- the same order."""
    def run(v, a):
        if v is MISSING or v is None:
            return [[]]
        if not isinstance(v, dict):
            raise Unsupported("to_entries needs an object")
        return [[{"key": k, "value": val} for k, val in v.items()]]
    return run


def _length():
    def run(v, a):
        if v is MISSING or v is None:
            return [0]
        if isinstance(v, (list, dict, str)):
            return [len(v)]
        if isinstance(v, bool):
            raise Unsupported("length of a boolean")
        return [abs(v)]
    return run


def _max():
    def run(v, a):
        if not isinstance(v, list):
            raise Unsupported("max needs an array")
        real = [x for x in v if x is not MISSING and x is not None]
        if not real:
            return [None]
        return [max(real)]
    return run


def _tsv():
    def run(v, a):
        if not isinstance(v, list):
            raise Unsupported("@tsv needs an array")
        cells = []
        for c in v:
            if c is None or c is MISSING:
                cells.append("")
            elif c is True or c is False:
                cells.append("true" if c else "false")
            else:
                cells.append(str(c).replace("\\", "\\\\").replace("\t", "\\t")
                             .replace("\n", "\\n").replace("\r", "\\r"))
        return ["\t".join(cells)]
    return run


# ------------------------------------------------------------------- output
def emit(value, raw: bool, out) -> None:
    if value is MISSING:
        return
    if raw and isinstance(value, str):
        out.write(value + "\n")
        return
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    out.write(json.dumps(value, separators=(",", ":"), ensure_ascii=False) + "\n")


def _document_values(head: str, stream):
    """A stream whose FIRST value spans several lines, as jq reads it.

    api.github.com pretty-prints: `{` on a line of its own and one field per
    line after it. Read a line at a time, every one of them fails to parse,
    and the whole body comes out as nothing -- which is how `--notes` on a
    box without jq printed "could not be fetched" for a release that had
    perfectly good notes. jq has no line rule at all; it reads a stream of
    values separated by whitespace, and this is that, for the one case the
    line rule cannot serve.

    IT KEEPS THE RECOVERY the line rule has: raw_decode refusing at some
    offset means the bytes from there are not a value, so this skips to the
    next line and tries again rather than giving up on the rest of the file.
    """
    text = head + stream.read()
    dec = json.JSONDecoder()
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            return
        try:
            value, i = dec.raw_decode(text, i)
        except ValueError:
            nl = text.find("\n", i)
            if nl < 0:
                return
            i = nl + 1
            continue
        yield value


def read_values(paths: list, raw_input: bool):
    """Every input value, in order.

    ONE JSON VALUE PER LINE is the fast path and the usual one -- a .jsonl
    transcript, a sessions/<pid>.json -- and a line that will not parse is
    skipped rather than fatal (see the module docstring: a poll can land
    mid-write). When the first non-blank line is not a whole value the input
    is not that shape at all, and the rest is read as a stream of values the
    way jq reads it; _document_values says why that case exists."""
    if paths:
        streams = []
        for p in paths:
            try:
                streams.append(open(p, "r", encoding="utf-8", errors="replace"))
            except OSError as exc:
                sys.stderr.write("muxjson: %s\n" % exc)
                raise SystemExit(2)
    else:
        streams = [sys.stdin]
    for s in streams:
        first = True
        for line in s:
            stripped = line.strip()
            if not stripped:
                continue
            if raw_input:
                first = False
                yield stripped
                continue
            try:
                value = json.loads(stripped)
            except ValueError:
                # THE DECISION IS MADE ONCE, on the first non-blank line, and
                # never again: a torn line in the MIDDLE of a transcript must
                # go on being skipped, not turn the rest of a 40 MB file into
                # one string in memory.
                if first:
                    first = False
                    for value in _document_values(line, s):
                        yield value
                    break
                first = False
                continue
            first = False
            yield value
        if s is not sys.stdin:
            s.close()


def via_jq_py(filt, args, values, raw, out) -> int:
    """Run the filter through libjq (the `jq` PyPI wheel) instead of the
    subset above. profile.sh passes --via-jq-py only when it has already
    checked that the module imports, so this is never a guess -- and because
    it IS libjq, a filter muxjson would refuse works here exactly as jq would.

    The point of the tier is that the small parser below never has to grow to
    cover an exotic filter on a machine that has this."""
    import jq as jqlib                                  # noqa: PLC0415
    program = jqlib.compile(filt, args=args) if args else jqlib.compile(filt)
    for value in values:
        for result in program.input_value(value):
            emit(result, raw, out)
    return 0


def whole_input(paths: list) -> str:
    """Every byte of the input as one string -- what jq's -R -s means."""
    if not paths:
        return sys.stdin.read()
    out = []
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                out.append(fh.read())
        except OSError as exc:
            sys.stderr.write("muxjson: %s\n" % exc)
            raise SystemExit(2)
    return "".join(out)


def main(argv: list) -> int:
    raw = compact = null_input = slurp = raw_input = False
    args: dict = {}
    filt = None
    paths: list = []
    use_jq_py = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--via-jq-py":
            use_jq_py = True
            i += 1
            continue
        if a == "--arg":
            args[argv[i + 1]] = argv[i + 2]
            i += 3
            continue
        if a.startswith("-") and len(a) > 1 and not a.startswith("--") and filt is None:
            for ch in a[1:]:
                if ch == "r":
                    raw = True
                elif ch == "c":
                    compact = True          # already how this prints
                elif ch == "n":
                    null_input = True
                elif ch == "s":
                    slurp = True
                elif ch == "R":
                    raw_input = True
                else:
                    sys.stderr.write("muxjson: -%s is not implemented\n" % ch)
                    return 2
            i += 1
            continue
        if filt is None:
            filt = a
        else:
            paths.append(a)
        i += 1
    if filt is None:
        sys.stderr.write("muxjson: no filter given\n")
        return 2

    out = sys.stdout
    if use_jq_py:
        try:
            if null_input:
                values = [None]
            elif slurp:
                values = [list(read_values(paths, raw_input))]
            else:
                values = read_values(paths, raw_input)
            return via_jq_py(filt, args, values, raw, out)
        except ImportError:
            pass          # the wheel went away; the subset below still works
        except BrokenPipeError:
            return 0
        except Exception as exc:                        # noqa: BLE001
            sys.stderr.write("muxjson: jq.py: %s\n  filter: %s\n" % (exc, filt))
            return 2

    try:
        node = Parser(tokenise(filt), filt).parse()
    except Unsupported as exc:
        sys.stderr.write("muxjson: %s\n  filter: %s\n"
                         "  this is muxtopus's small stand-in for jq; install jq "
                         "for the real thing\n" % (exc, filt))
        return 2

    try:
        if null_input:
            values = [None]
        elif slurp and raw_input:
            # -R -s TOGETHER: the whole input as ONE string, newlines and all.
            # Not a list of lines -- that is -R alone. `jq -Rs .` is how a
            # shell script JSON-escapes an arbitrary blob, and getting this
            # wrong would quietly escape only its first line.
            values = [whole_input(paths)]
        elif slurp:
            values = [list(read_values(paths, raw_input))]
        else:
            values = read_values(paths, raw_input)
        for value in values:
            for result in node(value, args):
                emit(result, raw, out)
    except Unsupported as exc:
        sys.stderr.write("muxjson: %s\n  filter: %s\n" % (exc, filt))
        return 2
    except BrokenPipeError:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
