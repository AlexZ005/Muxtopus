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
#   - `--check <prefix>-`, the whole wave of an orchestrator, and that an
#     exact match still wins over it.
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

echo "== --check <prefix>-: every entry of a wave"
# orchestrate.md's step 5 runs `--check <slug>-` over a wave of <slug>-<lane>
# entries; resolving ONE entry, it answered "no schedule entry matching" for
# every wave (measured 2026-09-24 on orch-impl-, seven entries in the folder).
entry w-a work "" "BODY-LINE: a"; entry w-b work "" "BODY-LINE: b"; entry x work "" "BODY-LINE: x"
chk="$("$W" --check w- 2>&1)"; rc=$?
check "w- reports w-a.md" grep -qx 'w-a.md' <<<"$chk"
check "..and w-b.md" grep -qx 'w-b.md' <<<"$chk"
check "..and not x.md" bash -c '! grep -qx "x.md" <<<"$1"' _ "$chk"
check "..nor anything else" bash -c '[ "$(grep -c "^  slug " <<<"$1")" = 2 ]' _ "$chk"
check "..exit 0, both runnable" [ "$rc" = 0 ]
chk="$("$W" --check w-a 2>&1)"
check "w-a is the one entry" bash -c '[ "$(grep -c "^  slug " <<<"$1")" = 1 ] && grep -qx w-a.md <<<"$1"' _ "$chk"
chk="$("$W" --check nope- 2>&1)"; rc=$?
check "nope- matches nothing: exit 2" [ "$rc" = 2 ]
check "..and says so" grep -q "no schedule entry matching 'nope-'" <<<"$chk"
# The slug counts as well as the file name: the name a lane is known by.
{ printf 'type: work\nat: 2099-01-01 00:00\nslug: w-by-slug\ncwd: %s\nstatus: pending\n---\nhi\n' "$HOME"; } > "$SC/zz.md"
check "an entry whose SLUG starts with it is in the wave" grep -qx 'zz.md' <<<"$("$W" --check w- 2>&1)"
# Worst of them: one lane that can never run makes the wave exit 1.
{ printf 'type: work\nat: 2099-01-01 00:00\nslug: w-broken\ncwd: %s/nosuch\nstatus: pending\n---\nhi\n' "$HOME"; } > "$SC/w-broken.md"
"$W" --check w- >/dev/null 2>&1; rc=$?
check "a wave with one unrunnable entry exits 1" [ "$rc" = 1 ]
# An exact match wins, even when the name itself ends in '-'.
entry w- work "" "BODY-LINE: the entry named w-"
chk="$("$W" --check w- 2>&1)"
check "an entry named w- is checked alone" \
  bash -c '[ "$(grep -c "^  slug " <<<"$1")" = 1 ] && grep -qx w-.md <<<"$1"' _ "$chk"
check "a glob character in the prefix is literal" \
  bash -c '"$1" --check "*-" >/dev/null 2>&1; [ $? = 2 ]' _ "$W"
rm -f "$SC"/w-*.md "$SC/x.md" "$SC/zz.md"

echo "== launched for real: the keys the window received"
# --check shares the composer with the launcher; this is the launcher itself,
# into a fake claude that records every key typed at it.
printf '● ready\n❯ \n' > "$HOME/fake-screen"
tmux new-session -d -s claude -n home -x 120 -y 40 "sleep 600"
"$W" --on >/dev/null
rm -f "$SC"/*.md "$HOME/fake-claude.keys"
entry lane-go work brief "BODY-LINE: launched {{HANDOVERS}}"
sed -i 's/^at: .*/at: 2020-01-01 00:00/' "$SC/lane-go.md"
"$W" --once >/dev/null 2>&1
for i in $(seq 40); do grep -q '^status: launched' "$SC/lane-go.md" && break; sleep 0.25; done
# The fake drains the paste one key per loop; wait for the footer to arrive.
for i in $(seq 120); do tr -d '\n' < "$HOME/fake-claude.keys" 2>/dev/null | grep -q 'donelane-go\|done\\ lane-go' && break; sleep 0.25; done
k="$(tr -d '\n' < "$HOME/fake-claude.keys" 2>/dev/null | sed 's/\\ / /g')"
check "launched" grep -q '^status: launched' "$SC/lane-go.md"
check "the template reached the window" grep -qF 'TEMPLATE-LINE' <<<"$k"
check "..before the body, and the footer last" \
  bash -c '[[ "$1" == *TEMPLATE-LINE*BODY-LINE*"handover.sh done lane-go"* ]]' _ "$k"
check "..with {{HANDOVERS}} resolved in it" grep -qF "launched $HO" <<<"$k"
sb_done
