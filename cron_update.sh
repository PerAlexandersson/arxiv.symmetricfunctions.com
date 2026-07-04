#!/bin/bash
# cron_update.sh - Scheduled arXiv fetch + DOI discovery.
#
# Intended for production cron. Uses a lock so slow Crossref/arXiv runs do not
# overlap, and appends timestamped output to one log file.
#
# Environment overrides:
#   ARXIV_VENV=/path/to/venv          # optional; otherwise activate_venv.sh
#   ARXIV_CRON_LOG_DIR=$HOME/logs     # default
#   ARXIV_CRON_LOCK_DIR=$HOME/.cache/arxiv-cron
#   FETCH_DAYS=3
#   DOI_BATCH=50
#   DOI_MIN_AGE=30
#   DOI_RECHECK=180
#   DOI_AUTO_APPROVE=0.95             # set to "none" to only stage candidates

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${ARXIV_CRON_LOG_DIR:-$HOME/logs}"
LOCK_DIR="${ARXIV_CRON_LOCK_DIR:-$HOME/.cache/arxiv-cron}"
LOG_FILE="$LOG_DIR/arxiv-update.log"
LOCK_FILE="$LOCK_DIR/update.lock"

FETCH_DAYS="${FETCH_DAYS:-3}"
DOI_BATCH="${DOI_BATCH:-50}"
DOI_MIN_AGE="${DOI_MIN_AGE:-30}"
DOI_RECHECK="${DOI_RECHECK:-180}"
DOI_AUTO_APPROVE="${DOI_AUTO_APPROVE:-0.95}"

mkdir -p "$LOG_DIR" "$LOCK_DIR"

if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    printf '[%s] Previous update still running; exiting.\n' "$(date -Is)" >> "$LOG_FILE"
    exit 0
  fi
else
  LOCK_FALLBACK="$LOCK_FILE.d"
  if ! mkdir "$LOCK_FALLBACK" 2>/dev/null; then
    printf '[%s] Previous update still running; exiting.\n' "$(date -Is)" >> "$LOG_FILE"
    exit 0
  fi
  trap 'rmdir "$LOCK_FALLBACK"' EXIT
fi

exec >> "$LOG_FILE" 2>&1

printf '\n[%s] Starting scheduled arXiv update\n' "$(date -Is)"
cd "$PROJECT_DIR"

if [ -n "${ARXIV_VENV:-}" ]; then
  # shellcheck disable=SC1090
  source "$ARXIV_VENV/bin/activate"
else
  # shellcheck disable=SC1091
  source "$PROJECT_DIR/activate_venv.sh"
fi

python3 src/fetch_arxiv.py --recent --days "$FETCH_DAYS"

doi_args=(
  --batch "$DOI_BATCH"
  --min-age "$DOI_MIN_AGE"
  --recheck "$DOI_RECHECK"
)
if [ "$DOI_AUTO_APPROVE" != "none" ] && [ -n "$DOI_AUTO_APPROVE" ]; then
  doi_args+=(--auto-approve "$DOI_AUTO_APPROVE")
fi

python3 src/doi_lookup.py "${doi_args[@]}"

printf '[%s] Scheduled arXiv update complete\n' "$(date -Is)"
