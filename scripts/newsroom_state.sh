#!/usr/bin/env bash
# Persist the newsroom's working state between GitHub Actions runs.
#
#   scripts/newsroom_state.sh restore   # unpack the state branch into $STATE_DIR
#   scripts/newsroom_state.sh save      # store $STATE_DIR as the state branch
#
# The state (SQLite database + results CSVs) lives on the branch $STATE_BRANCH as a
# single commit with no parent, force-pushed each time, so the branch never grows.
# Uses the repository's own credentials (actions/checkout), so no extra token.
set -euo pipefail

BRANCH="${STATE_BRANCH:-newsroom-state}"
DIR="${STATE_DIR:-.newsroom}"
REMOTE="${STATE_REMOTE:-origin}"

case "${1:-}" in
  restore)
    mkdir -p "$DIR"
    if git fetch --quiet --depth 1 "$REMOTE" "refs/heads/$BRANCH" 2>/dev/null; then
      git archive FETCH_HEAD | tar -x -C "$DIR"
      echo "Restored newsroom state from branch $BRANCH"
    else
      echo "No $BRANCH branch yet: starting with a fresh newsroom"
    fi
    ;;
  save)
    if [ ! -d "$DIR" ] || [ -z "$(find "$DIR" -type f ! -name '*-wal' ! -name '*-shm' ! -name '*.joblib' -print -quit)" ]; then
      echo "Nothing to save"
      exit 0
    fi
    # Fold SQLite's write-ahead log into the database file before storing it.
    for db in "$DIR"/*.db; do
      [ -e "$db" ] && python - "$db" <<'PY'
import sqlite3, sys
sqlite3.connect(sys.argv[1]).execute("PRAGMA wal_checkpoint(TRUNCATE)")
PY
    done
    git_dir="$(git rev-parse --absolute-git-dir)"
    index="$(mktemp -u)"
    (
      cd "$DIR"
      export GIT_DIR="$git_dir" GIT_WORK_TREE="$PWD" GIT_INDEX_FILE="$index"
      git add --force -- $(find . -type f ! -name '*-wal' ! -name '*-shm' ! -name '*.joblib' -printf '%P\n')
      tree="$(git write-tree)"
      commit="$(GIT_AUTHOR_NAME="touchline-takes-newsroom" GIT_AUTHOR_EMAIL="newsroom@users.noreply.github.com" \
                GIT_COMMITTER_NAME="touchline-takes-newsroom" GIT_COMMITTER_EMAIL="newsroom@users.noreply.github.com" \
                git commit-tree "$tree" -m "Newsroom state $(date -u +%Y-%m-%dT%H:%M:%SZ)")"
      git push --quiet --force "$REMOTE" "$commit:refs/heads/$BRANCH"
    )
    rm -f "$index"
    echo "Saved newsroom state to branch $BRANCH"
    ;;
  *)
    echo "usage: $0 restore|save" >&2
    exit 2
    ;;
esac
