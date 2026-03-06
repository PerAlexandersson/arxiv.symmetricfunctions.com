#!/bin/bash
# tag_papers.sh - Tag papers with curated keywords
#
# Usage:
#   ./tag_papers.sh              # last 180 days (default)
#   ./tag_papers.sh --days 30    # last 30 days
#   ./tag_papers.sh --since 2025-01-01
#   ./tag_papers.sh --all        # all papers

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

source activate_venv.sh

cd src
python3 auto_tag.py "$@"
