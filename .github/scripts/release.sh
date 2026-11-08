#!/usr/bin/env bash
# Tags and releases the Code Grading Suite version held in bundle/ at one commit.
# Called by .github/workflows/release.yml; safe to run again (it skips versions that are already tagged).
#
# Which commit:
#   TARGET set          that commit (any ref or SHA)
#   otherwise           the newest commit on main's first-parent line, up to the pushed commit,
#                       that changed bundle/web/manifest.json (where the version lives). For a
#                       bundle PR that's its merge commit; for other edits it's the last version's.
#
# Needs: git with full history and tags, python3, zip, gh (GH_TOKEN with contents: write).
# DRY_RUN=1 prints what it would do instead of creating the release.
#
# Two steps, so the workflow can sign the files in between (build provenance, see release.yml):
#   STAGE_DIR=dir    build the zips, SHA256SUMS and notes into dir (and print tag=… for GITHUB_OUTPUT); no release
#   PUBLISH_DIR=dir  create the release from a staged dir (plus any *.intoto.jsonl signature bundle in it)
# With neither, it builds and releases in one go, as before.
set -euo pipefail

repo="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is not set}"
target="${TARGET:-}"
if [ -z "$target" ]; then
  target="$(git log -1 --first-parent --format=%H "${GITHUB_SHA:-HEAD}" -- bundle/web/manifest.json)"
fi
[ -n "$target" ] || { echo "::notice::No bundle on this branch yet; nothing to release."; exit 0; }
target="$(git rev-parse --verify "$target^{commit}")"

if ! git cat-file -e "$target:bundle/web/manifest.json" 2>/dev/null || ! git cat-file -e "$target:bundle/bare/CHANGELOG.md" 2>/dev/null; then
  echo "::notice::No bundle at ${target:0:7}; nothing to release."
  exit 0
fi

if [ -n "${PUBLISH_DIR:-}" ]; then
  # shellcheck disable=SC1091
  . "$PUBLISH_DIR/release.env"
  [ -n "${tag:-}" ] || { echo "::notice::Nothing staged; nothing to release."; exit 0; }
  assets=("$PUBLISH_DIR"/*.zip "$PUBLISH_DIR/SHA256SUMS")
  for b in "$PUBLISH_DIR"/*.intoto.jsonl; do [ -e "$b" ] && assets+=("$b"); done
  if [ -n "${DRY_RUN:-}" ]; then
    echo "--- would run: gh release create $tag ${assets[*]} --target $target --latest=$latest"
    exit 0
  fi
  gh release create "$tag" "${assets[@]}" \
    --repo "$repo" --target "$target" --title "$tag" \
    --notes-file "$PUBLISH_DIR/notes.md" --latest="$latest"
  echo "::notice::Released $tag (latest: $latest)"
  exit 0
fi

# Work on a copy of bundle/ as it is at the target commit.
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
git archive "$target" bundle | tar -x -C "$work"
bundle="$work/bundle"

version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$bundle/web/manifest.json")"
top="$(grep -m1 -oE '^## [0-9]+\.[0-9]+\.[0-9]+' "$bundle/bare/CHANGELOG.md" | cut -c4-)"
if [ "$version" != "$top" ]; then
  echo "::error::bundle/web is version $version but bundle/bare/CHANGELOG.md starts at $top. Both folders must hold the same version."
  exit 1
fi
tag="v$version"

git fetch -q --tags origin 2>/dev/null || true
if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
  echo "::notice::$tag is already tagged (at $(git rev-parse --short "$tag^{commit}")); nothing to do."
  exit 0
fi

echo "Releasing $tag from ${target:0:7}"
(cd "$bundle/web" && sha256sum -c --quiet SHA256SUMS)

# Zips: the bare kit inside a code-grading-suite/ folder, and the website at the top level.
dist="$work/dist"
mkdir -p "$dist/stage"
cp -r "$bundle/bare" "$dist/stage/code-grading-suite"
bare_zip="$dist/code-grading-suite-$tag.zip"
web_zip="$dist/code-grading-suite-web-$tag.zip"
(cd "$dist/stage" && zip -qrX "$bare_zip" code-grading-suite -x '*/__pycache__/*' '*.pyc' '*.DS_Store')
(cd "$bundle/web" && zip -qrX "$web_zip" . -x '*/__pycache__/*' '*.pyc' '*.DS_Store')
(cd "$dist" && sha256sum "$(basename "$bare_zip")" "$(basename "$web_zip")" > SHA256SUMS)

# The pull request that brought this version in, if there is one.
pr=""
if [ -z "${DRY_RUN:-}" ]; then
  pr="$(gh api "repos/$repo/commits/$target/pulls" --jq '.[0].number // empty' 2>/dev/null || true)"
fi
[ -n "$pr" ] || pr="$(git log -1 --format=%s "$target" | grep -oE '#[0-9]+' | head -1 | tr -d '#' || true)"

notes="$dist/notes.md"
{
  echo "## Code Grading Suite $tag"
  echo
  awk -v h="## $version" '$0 == h || index($0, h " ") == 1 { on = 1; next } /^## / { on = 0 } on' "$bundle/bare/CHANGELOG.md" \
    | awk 'NF { started = 1 } started { lines[++n] = $0; if (NF) last = n } END { for (i = 1; i <= last; i++) print lines[i] }'
  echo
  echo "### Downloads"
  echo
  echo "| File | What it is |"
  echo "|---|---|"
  echo "| \`code-grading-suite-$tag.zip\` | The bare kit: prompts, rubric, config, schema, \`gradekit.py\`, docs |"
  echo "| \`code-grading-suite-web-$tag.zip\` | The built website, ready for any static web server (checksums in \`SHA256SUMS\`) |"
  echo
  echo "These are \`bundle/bare/\` and \`bundle/web/\` at this tag. The bare kit leaves out the website builder."
  echo
  echo "### Verify a download"
  echo
  echo "\`SHA256SUMS\` lists each file's checksum, and each zip is signed with build provenance from this repository's release workflow:"
  echo
  echo "\`\`\`"
  echo "sha256sum -c SHA256SUMS --ignore-missing"
  echo "gh attestation verify code-grading-suite-$tag.zip --repo $repo"
  echo "\`\`\`"
  if [ -n "$pr" ]; then echo; echo "Added in #$pr."; fi
} > "$notes"

# Mark as Latest only if no higher version is already tagged.
highest="$({ git tag -l 'v[0-9]*'; echo "$tag"; } | sort -V | tail -1)"
latest=false
[ "$highest" = "$tag" ] && latest=true

if [ -n "${STAGE_DIR:-}" ]; then
  mkdir -p "$STAGE_DIR"
  cp "$bare_zip" "$web_zip" "$dist/SHA256SUMS" "$notes" "$STAGE_DIR/"
  printf 'tag=%s\ntarget=%s\nlatest=%s\n' "$tag" "$target" "$latest" > "$STAGE_DIR/release.env"
  echo "tag=$tag"
  echo "::notice::Staged $tag in $STAGE_DIR"
  exit 0
fi

if [ -n "${DRY_RUN:-}" ]; then
  echo "--- would run: gh release create $tag --target $target --title $tag --latest=$latest"
  echo "--- notes:"; cat "$notes"
  echo "--- assets:"; ls -l "$bare_zip" "$web_zip"
  unzip -l "$bare_zip" | tail -1; unzip -l "$web_zip" | tail -1
  exit 0
fi

gh release create "$tag" "$bare_zip" "$web_zip" "$dist/SHA256SUMS" \
  --repo "$repo" --target "$target" --title "$tag" \
  --notes-file "$notes" --latest="$latest"
echo "::notice::Released $tag (latest: $latest)"
