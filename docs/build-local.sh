#!/usr/bin/env bash
# Render the manual the way GitHub Pages will, into docs/_site/.
#
# GitHub builds docs/ with the container image ghcr.io/actions/jekyll-build-pages
# (the same Jekyll, the same plugins, the same theme fetch), so running that
# image here is the one local proof that means anything; a different Jekyll on
# the host would prove a different build. Needs podman or docker and nothing
# else -- no ruby, no bundler. The first run pulls ~400 MB.
#
#   docs/build-local.sh            # writes docs/_site/; open docs/_site/index.html
#   docs/build-local.sh --check    # build, then assert the pages, the nav and
#                                  # the placeholders came out right
set -euo pipefail
DOCS="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
IMAGE="${JEKYLL_IMAGE:-ghcr.io/actions/jekyll-build-pages:v1.0.13}"
OUT="${DOCS}/_site"

if command -v podman >/dev/null 2>&1; then RUN=podman
elif command -v docker >/dev/null 2>&1; then RUN=docker
else echo "build-local.sh: needs podman or docker" >&2; exit 2; fi

rm -rf -- "${OUT:?}"
mkdir -p -- "${OUT:?}"
# The image wants a checkout with .git for the GitHub metadata plugin; it
# copes without one. INPUT_* are the action's inputs. --future keeps nothing
# back, --verbose says which files became pages.
# GITHUB_WORKSPACE is prefixed to both paths; with it empty the source was
# //docs and Jekyll's cleaner walked parent directories of / until the stack
# ran out. So: a workspace, and paths relative to it.
"$RUN" run --rm \
  -v "${DOCS}:/github/workspace/docs:z" -v "${OUT}:/github/workspace/_site:z" \
  -e GITHUB_WORKSPACE=/github/workspace \
  -e INPUT_SOURCE=docs -e INPUT_DESTINATION=_site \
  -e INPUT_BUILD_REVISION=local -e INPUT_VERBOSE=false \
  -e INPUT_FUTURE=false -e INPUT_TOKEN= \
  -e PAGES_REPO_NWO=AlexZ005/Muxtopus -e JEKYLL_ENV=production \
  "$IMAGE"

[ "${1:-}" = "--check" ] || { echo "built: ${OUT}/index.html"; exit 0; }

fail=0
say() { printf '  %s %s\n' "$1" "$2"; [ "$1" = ok ] || fail=1; }
for page in "${DOCS}"/*.md; do
  base="$(basename "$page" .md)"
  head -1 "$page" | grep -q '^---$' || continue          # not a page
  if [ "$base" = index ]; then html="${OUT}/index.html"; else html="${OUT}/${base}.html"; fi
  if [ -f "$html" ]; then say ok "$base rendered"; else say FAIL "$base did not render"; fi
done
# Every page is in the nav of every other page.
# The title is the one in the FRONT MATTER: a `title:` inside a code sample
# (the schedule format, the how-to-add-a-page example) is not a page.
titles="$(for f in "${DOCS}"/*.md; do awk 'NR==1&&$0!="---"{exit} NR>1&&$0=="---"{exit} /^title: /{sub(/^title: /,""); print}' "$f"; done)"
while IFS= read -r t; do
  if grep -qF ">$t<" "${OUT}/index.html"; then say ok "nav: $t"; else say FAIL "nav is missing: $t"; fi
done <<<"$titles"
# Liquid must not have eaten a placeholder.
if grep -q '{{SLUG}}' "${OUT}/schedules.html"; then say ok "placeholders survived Liquid"
else say FAIL "{{SLUG}} is gone from schedules.html: a page lost its raw tags"; fi
# The plans are design notes, not pages: excluded, so neither rendered nor
# copied (GitHub's optional-front-matter plugin would otherwise page them).
if [ ! -f "${OUT}/plan-insights.md" ] && [ ! -f "${OUT}/plan-insights.html" ]; then say ok "plan-*.md left out of the site"
else say FAIL "plan-*.md reached the site"; fi
# Every #anchor a page links to is an id kramdown actually generated.
while IFS=$'\t' read -r src target anchor; do
  [ -n "$anchor" ] || continue
  base="${target%.md}"; [ "$base" = index ] && base=index
  if grep -q "id=\"${anchor}\"" "${OUT}/${base}.html" 2>/dev/null; then say ok "anchor: ${target}#${anchor}"
  else say FAIL "${src}: ${target}#${anchor} -- no such id in ${base}.html"; fi
done < <(grep -oH '](\([a-z-]*\.md\)#[a-z0-9-]*)' "${DOCS}"/*.md \
         | sed 's|^\(.*\)\.md:](\([^#]*\)#\(.*\))$|\1.md\t\2\t\3|' | sort -u)
[ "$fail" = 0 ] && echo "manual renders" || { echo "manual: FAILED" >&2; exit 1; }
