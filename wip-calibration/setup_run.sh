#!/bin/bash
# setup_run.sh GOLDEN TAG -> /tmp/calib/GOLDEN-TAG with kit/, the code checkout, grading/, scratch/ (and gomod/ for Go)
set -euo pipefail
G=$1; T=$2; R=/tmp/calib/$G-$T
case $G in
  realworld-go)      SRC=golang-gin-realworld-example-app; REV=de2be2ab8832 ;;
  realworld-angular) SRC=angular-realworld-example-app;    REV=a7a19c511b0b ;;
  hexyl)             SRC=hexyl;                            REV=6ecc29b9c8c8 ;;
  nanogpt)           SRC=nanoGPT;                          REV=93a43d9 ;;
  *) echo "unknown golden $G" >&2; exit 2 ;;
esac
[ -e "$R" ] && { echo "$R exists" >&2; exit 1; }
mkdir -p "$R/scratch" "$R/grading/projects/$G"
cp -r /tmp/calib/kit6/source "$R/kit"
git clone -q "/tmp/calib/src/$SRC" "$R/$SRC"
git -C "$R/$SRC" checkout -q --detach "$REV"
git -C "$R/$SRC" remote set-url origin "$(git -C /tmp/calib/src/$SRC remote get-url origin)"
git -C "$R/$SRC" for-each-ref --format='%(refname)' refs/remotes refs/heads | xargs -r -n1 git -C "$R/$SRC" update-ref -d
if [ "$G" = realworld-angular ]; then git -C "$R/$SRC" submodule update -q --init; fi
if [ "$G" = realworld-go ]; then mkdir -p "$R/gomod" && cp /tmp/calib/go/go.mod /tmp/calib/go/go.sum "$R/gomod/"; fi
cp "/tmp/calib/goldens/$G/project.toml" "$R/grading/projects/$G/"
git -C "$R/grading" init -q && git -C "$R/grading" add -A && git -C "$R/grading" -c user.name=calibration -c user.email=calibration@localhost commit -qm "Project config for $G"
echo "$R $SRC $(git -C "$R/$SRC" rev-parse HEAD)"
