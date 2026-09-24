"""dashboard.schedules -- a schedule entry as DATA: read, checked, rewritten.

The parser that keeps the broken files, the linter that mirrors the
executor's rules, the slug rule every handover path is built from, and the
options header that is the source of truth for the checkbox table.

NO RICH, for the same reason dashboard.data has none: this module is the
half of the schedule story that a test, the executor or a bot can ask
without a terminal, and tests/test_entry_options.py is exactly that caller.
Drawing an entry is dashboard/views/schedules.py's job.
"""
from __future__ import annotations

import string
import time
from pathlib import Path

from dashboard.core import SCHEDULES_DIR, SCHED_TEMPLATES
# The limit lives in dashboard.naming, which is pure and imports nothing of
# ours, so there is no cycle; one number for both is what keeps the Create
# row's padding and the rule that cuts the name from drifting apart.
from dashboard.naming import MAX_SLUG


SLUG_OK = frozenset(string.ascii_letters + string.digits + "._-")


def sanitise_slug(raw: str) -> str:
    """The executor's rule, character for character: tr -c 'A-Za-z0-9._-' '-'
    then cut to MAX_SLUG (32). Mirrored here rather than shelled out to, for the same
    reason validate_schedule mirrors the executor's other rules -- this side is
    a linter, and a linter that disagrees with the thing it lints is worse than
    none."""
    return "".join(c if c in SLUG_OK else "-" for c in raw)[:MAX_SLUG]


def resolve_slug(row: dict) -> str:
    """What the window, the handover file and `handover.sh done` will all be
    called. An explicit slug: wins over the title; the filename is the last
    resort."""
    raw = row.get("slug") or row.get("title") or row["file"].stem
    return sanitise_slug(raw)


def slug_warning(row: dict) -> str:
    """Empty when the slug is exactly what was written down.

    Not corruption -- a title that sanitises still launches -- but the gap
    between "27-storage wave 2" and the slug 27-storage-wave-2 is what put a
    lane's handover in a file nothing was watching, so it is said out loud."""
    raw = row.get("slug") or row.get("title")
    src = "slug" if row.get("slug") else "title"
    if not raw:
        return ""
    slug = sanitise_slug(raw)
    if slug == raw:
        return ""
    if len(raw) > MAX_SLUG and raw[:MAX_SLUG] == slug:
        return "%s truncated to %r — set slug: to pin it" % (src, slug)
    return "%s is not a slug; it becomes %r — set slug: to pin it" % (src, slug)


def read_schedules() -> list[dict]:
    """Parse every schedule file, KEEPING the broken ones.

    The executor (claude-watchdog.sh) silently skips what it cannot parse;
    this side's whole job is the opposite -- show the file with the reason it
    will never launch, because a schedule that quietly does nothing is the
    worst failure a scheduler can have."""
    rows: list[dict] = []
    try:
        files = sorted(SCHEDULES_DIR.glob("*.md"))
    except OSError:
        return rows
    for f in files:
        if f.name == "README.md":
            continue
        row = {"file": f, "type": "", "at": "", "title": "", "slug": "",
               "window": "", "cwd": "", "template": "", "status": "",
               "created": "", "launched": "", "after": "", "parent": "",
               "options": "", "model": "", "effort": "",
               "body": "", "bad": "", "warn": "", "resolved": ""}
        try:
            text = f.read_text()
        except OSError as exc:
            row["bad"] = "unreadable: %s" % exc
            rows.append(row)
            continue
        head, sep, body = text.partition("\n---\n")
        if not sep:
            row["bad"] = "no --- separator line"
        for line in head.splitlines():
            k, _, v = line.partition(": ")
            k = k.rstrip(":")           # tolerate "launched:" with no value
            if k in row and k not in ("file", "body", "bad"):
                row[k] = v.strip()
        row["body"] = body.strip()
        row["resolved"] = resolve_slug(row)
        row["warn"] = slug_warning(row)
        if not row["bad"]:
            row["bad"] = validate_schedule(row)
        rows.append(row)
    return rows


def validate_schedule(row: dict) -> str:
    """The corrupted-marking rules. Mirrors what the bash executor requires --
    kept deliberately a little STRICTER (exact time format), since this side
    is a linter for hand-edited files and bash date -d will swallow almost
    anything, right or wrong."""
    if row["type"] not in ("plan", "work"):
        return "type must be plan or work (got %r)" % (row["type"] or "")
    if row["at"] != "reset":
        ok = False
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                time.strptime(row["at"], fmt)
                ok = True
                break
            except ValueError:
                pass
        if not ok:
            return "at must be 'reset' or YYYY-MM-DD HH:MM (got %r)" % (row["at"] or "")
    if not row["cwd"] or not Path(row["cwd"]).is_dir():
        return "cwd missing or not a directory"
    # A work entry may name a template now, and one that does can leave its
    # body empty -- the executor pastes the template alone (sched_has_prompt).
    if row["type"] == "work" and not row["body"] and not (
            row["template"] and (SCHED_TEMPLATES / (row["template"] + ".md")).exists()):
        return "work item has an empty prompt body and no template"
    if row["template"] and not (SCHED_TEMPLATES / (row["template"] + ".md")).exists():
        return "template %r not in templates/" % row["template"]
    if row["status"] not in ("pending", "launched", "error", ""):
        return "unknown status %r" % row["status"]
    return ""


# ------------------------------------------------------- schedule options
# The checkboxes offered between the template and the editor. The OPTIONS
# LIST comes from muxconfig (~/.config/muxtopus/options.md); everything here
# is about the entry FILE -- what a tick writes, and how it is read back.
#
# THE HEADER IS THE SOURCE OF TRUTH. `options: questions, phases, lanes=3`
# says which boxes were ticked and with what; the `## Options` section at the
# foot of the body is REGENERATED from it. Otherwise reopening the table is a
# lie: it would show boxes that no longer match the text underneath.
OPTIONS_HEADING = "## Options"

# WHICH `types:` EACH KIND OF ENTRY IS OFFERED. The kind is what the form was
# asked to make: plan, work, or orchestrate (a wave or a sweep, still written
# `type: work`). An orchestrator is a work entry with extra sentences, so it
# is offered the work blocks as well as its own -- the questions, phases,
# lowpri and verify lines apply to it exactly as to a lane (plan §6). A plain
# work entry is never offered an orchestrate block: `automate` on a lane is a
# lane merging its own PR.
OPTION_KINDS = {
    "plan": ("both", "plan"),
    "work": ("both", "work"),
    "orchestrate": ("both", "work", "orchestrate"),
}


def option_offered(o: dict, kind: str) -> bool:
    """True when the table offers option `o` to an entry of this kind. An
    unknown kind is offered the `both` blocks only, never everything."""
    return o["types"] in OPTION_KINDS.get(kind, ("both",))


def options_line(opts: list[dict], on: dict) -> str:
    """The `options:` header value, keys in FILE order.

    Comma-separated because the rest of the header is prose and this has to be
    read by eye as much as by the parser -- which is also why a collected
    value may not contain a comma (asked_value refuses one).
    """
    bits = []
    for o in opts:
        if o["bad"] or o["key"] not in on:
            continue
        v = on[o["key"]]
        bits.append(o["key"] if v is True else "%s=%s" % (o["key"], v))
    return ", ".join(bits)


def parse_options_line(value: str) -> dict:
    """`questions, lanes=3` -> {"questions": True, "lanes": "3"}."""
    on: dict = {}
    for bit in value.split(","):
        bit = bit.strip()
        if not bit:
            continue
        k, sep, v = bit.partition("=")
        on[k.strip()] = v.strip() if sep else True
    return on


def options_section(opts: list[dict], on: dict) -> str:
    """The `## Options` block: one `- <sentence>` per ticked line option.

    {{VALUE}} is resolved HERE, because only this side knows what the prompt
    collected. Every other placeholder ({{SLUG}}, {{HANDOVER}}, …) is written
    out literally and resolved by the executor at paste time, when the slug
    finally exists."""
    lines = []
    for o in opts:
        if o["bad"] or o["key"] not in on or not o["line"]:
            continue
        v = on[o["key"]]
        text = o["line"] if v is True else o["line"].replace("{{VALUE}}", str(v))
        lines.append("- " + text)
    if not lines:
        return ""
    return OPTIONS_HEADING + "\n" + "\n".join(lines) + "\n"


def options_fields(opts: list[dict], on: dict) -> list[tuple[str, str]]:
    """The header fields a ticked `set:` option writes -- (name, value) pairs,
    e.g. ("model", "opus-5"). The launcher passes these as flags."""
    out = []
    for o in opts:
        if o["bad"] or not o["set"] or o["key"] not in on:
            continue
        v = on[o["key"]]
        if v is not True:
            out.append((o["set"], str(v)))
    return out


def asked_value(kind: str, text: str) -> tuple[str, str]:
    """(value, complaint) for what an `ask:` option collected."""
    text = text.strip()
    if not text:
        return "", "nothing entered"
    if "," in text:
        # The options: header line is comma separated and must round-trip, so
        # a comma is refused OUT LOUD rather than quietly rewritten.
        return "", "no commas — the options: line is comma separated"
    if kind == "number" and not text.isdigit():
        return "", "a number, please (got %r)" % text
    return text, ""


def rewrite_options(text: str, opts: list[dict], on: dict) -> tuple[str, str]:
    """(new file text, error) with ONLY three things replaced: the `options:`
    line, the header fields owned by `set:` options, and the `## Options`
    section from its heading to the end of the body.

    EVERY OTHER BYTE IS PRESERVED, and that is the whole contract of the `o`
    key: the body above the heading is where the task is written, often at
    length and by hand, and an editor that reflowed it would be one nobody
    dared press. So the head is rebuilt line by line from the file's own lines
    and the body is sliced at the heading, rather than either being
    regenerated from a parse."""
    head, sep, body = text.partition("\n---\n")
    if not sep:
        return "", "no --- separator line"
    managed = {o["set"] for o in opts if o["set"]}
    want = dict(options_fields(opts, on))
    line = options_line(opts, on)

    out: list[str] = []
    seen: set[str] = set()
    for raw in head.split("\n"):
        k = raw.partition(":")[0].strip()
        if k == "options":
            seen.add("options")
            if line:
                out.append("options: " + line)
            continue
        if k in managed:
            seen.add(k)
            if k in want:
                out.append("%s: %s" % (k, want[k]))
            # An UNTICKED set: option drops its header field. That is only
            # ever a deliberate untick, because a field already in the file is
            # ticked back on when the table opens.
            continue
        out.append(raw)

    # New fields go where the create flow puts them: with cwd -- what the
    # entry IS -- and ahead of the bookkeeping.
    at = len(out)
    for i, raw in enumerate(out):
        if raw.partition(":")[0].strip() in ("status", "created", "launched"):
            at = i
            break
    fresh = ["%s: %s" % (k, v) for k, v in want.items() if k not in seen]
    if line and "options" not in seen:
        fresh.append("options: " + line)
    out[at:at] = fresh

    section = options_section(opts, on)
    blines = body.split("\n")
    pos = None
    at_char = 0
    for l in blines:
        if l.rstrip() == OPTIONS_HEADING:
            pos = at_char
            break
        at_char += len(l) + 1
    if pos is not None:
        new_body = body[:pos] + section
    elif section:
        # Appended, which is the one case that has to touch the end of the
        # body: separated by a blank line, nothing above it altered.
        new_body = body.rstrip("\n") + "\n\n" + section if body.strip() else section
    else:
        new_body = body
    return "\n".join(out) + "\n---\n" + new_body, ""
