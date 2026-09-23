#!/usr/bin/env bash
# What the executor pastes, read back through `claude-watchdog.sh --check
# <entry> --body` -- the same composer the launcher uses, so the report and the
# paste cannot drift apart. No window is opened: --check resolves an entry
# without launching it.
#
#   bash tests/test_sched_template.sh
#
# WHAT IS UNDER TEST.
#
#   - `template:` on a WORK entry. It used to be prepended for `plan` only, so
#     a self-rescheduling sweep had to copy its whole template into the next
#     entry's body, and an edit to the template never reached a chain in
#     flight. Now: the template, then the body, then the handover footer, in
#     that order; a plan entry is unchanged; a work entry whose body is empty
#     is NOT "empty" when its template carries the prompt.
#   - {{HANDOVERS}} and {{STATE}}, the two folders an orchestrator reads,
#     resolved beside {{HANDOVER}} in one body. sched_subst replaces
#     {{HANDOVER}} FIRST -- the order that would break if its pattern could
#     match the front of {{HANDOVERS}} -- so a clean paste here is the proof
#     that the whole token, closing braces included, is what is matched.
#
# The sandbox of tests/notify_sandbox.sh on a socket of its own; nothing here
# reaches a real pane, schedule or account.
set -uo pipefail
SB_SOCKET=mxtmpl
. "$(dirname "$0")/notify_sandbox.sh"
sb_init
W="$REPO/claude-watchdog.sh"
SC="$HOME/.code/schedules"; HO="$HOME/.code/handovers"
mkdir -p "$SC/templates"
entry() {  # entry NAME TYPE TEMPLATE [body] -- far in the future, never due
  { printf 'type: %s\nat: 2099-01-01 00:00\nslug: %s\ncwd: %s\nstatus: pending\n' "$2" "$1" "$HOME"
    [ -n "$3" ] && printf 'template: %s\n' "$3"
    printf -- '---\n'
    [ -n "${4:-}" ] && printf '%s\n' "$4"; } > "$SC/$1.md"
}
# The paste block of --check --body: everything after its heading.
paste_of() { "$W" --check "$1" --body 2>&1 | sed -n '/what would be pasted/,$p'; }
# Line number of the first line matching $2 in $1, or 0.
at() { grep -n -m1 -- "$2" <<<"$1" | cut -d: -f1 | grep . || echo 0; }
in_order() {  # in_order TEXT A B C: each found, and strictly in that order
  local t="$1" prev=0 n; shift
  for p in "$@"; do n="$(at "$t" "$p")"; [ "$n" -gt "$prev" ] || return 1; prev="$n"; done
}
printf 'TEMPLATE-LINE: the shared brief\n' > "$SC/templates/brief.md"

echo "== a work entry with a template: template, then body, then footer"
entry lane-tw work brief "BODY-LINE: this run only"
out="$(paste_of lane-tw)"
check "the template is pasted" grep -q 'TEMPLATE-LINE' <<<"$out"
check "..before the body, and the footer comes last" \
  in_order "$out" 'TEMPLATE-LINE' 'BODY-LINE' 'handover.sh done lane-tw'
chk="$("$W" --check lane-tw 2>&1)"
check "--check no longer says plan-only" bash -c '! grep -q "only prepended for type: plan" <<<"$1"' _ "$chk"
check "--check says what happens now" grep -q 'pasted first, then the body, then the handover footer' <<<"$chk"
check "the size line counts the template" grep -q 'template + body + handover footer' <<<"$chk"

echo "== a plan entry is unchanged: template, then body, no footer"
entry lane-tp plan brief "BODY-LINE: plan body"
out="$(paste_of lane-tp)"
check "template before body" in_order "$out" 'TEMPLATE-LINE' 'BODY-LINE'
check "no footer" bash -c '! grep -q "handover.sh done" <<<"$1"' _ "$out"
check "--check: template + body" grep -q '(template + body)' <<<"$("$W" --check lane-tp 2>&1)"

echo "== a work entry whose template carries the whole prompt is not empty"
entry lane-te work brief
chk="$("$W" --check lane-te --body 2>&1)"
check "not EMPTY BODY" bash -c '! grep -q "EMPTY BODY" <<<"$1"' _ "$chk"
check "the template and the footer are pasted" \
  in_order "$(sed -n '/what would be pasted/,$p' <<<"$chk")" 'TEMPLATE-LINE' 'handover.sh done lane-te'
entry lane-none work ""
check "..while no body and no template still is" grep -q 'EMPTY BODY' <<<"$("$W" --check lane-none 2>&1)"

echo "== a template: that names no file: said, and nothing prepended"
entry lane-miss work nosuch "BODY-LINE: alone"
chk="$("$W" --check lane-miss --body 2>&1)"
check "NOT IN templates/" grep -q 'nosuch   -- NOT IN templates/' <<<"$chk"
check "..and says nothing is prepended" grep -q 'nothing is prepended' <<<"$chk"
check "the body is still pasted" grep -q 'BODY-LINE: alone' <<<"$(sed -n '/what would be pasted/,$p' <<<"$chk")"

echo "== {{HANDOVER}}, {{HANDOVERS}} and {{STATE}} in one body"
ST="$XDG_STATE_HOME/claude-watchdog"
entry lane-ph work "" "one=[{{HANDOVER}}] all=[{{HANDOVERS}}] state=[{{STATE}}] again=[{{HANDOVERS}}/x]"
chk="$("$W" --check lane-ph --body 2>&1)"
out="$(sed -n '/what would be pasted/,$p' <<<"$chk")"
check "{{HANDOVER}} is this lane's file" grep -qF "one=[$HO/STATUS-lane-ph.md]" <<<"$out"
check "{{HANDOVERS}} is the folder, whole" grep -qF "all=[$HO]" <<<"$out"
check "..every time it appears" grep -qF "again=[$HO/x]" <<<"$out"
check "{{STATE}} is the watchdog's state folder" grep -qF "state=[$ST]" <<<"$out"
check "..the folder the daemon keeps its tables in" \
  bash -c '"$1" --on >/dev/null 2>&1; "$1" --once >/dev/null 2>&1; test -f "$2/sched-why.tsv"' _ "$W" "$ST"
check "no braces left in the paste" bash -c '! grep -q "{{" <<<"$1"' _ "$out"
check "no unknown-placeholder warning" bash -c '! grep -q "does not resolve" <<<"$1"' _ "$chk"
check "--check lists all three as used" \
  grep -q 'placeholders .*{{HANDOVER}} {{HANDOVERS}} {{STATE}}' <<<"$chk"
entry lane-unk work "" "{{HANDOVERSX}} {{STATES}}"
check "a near miss is still unknown, and said" \
  grep -q 'contains {{HANDOVERSX}} {{STATES}}, which this scheduler does not resolve' <<<"$("$W" --check lane-unk 2>&1)"
sb_done
