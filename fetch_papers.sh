#!/bin/bash
# Convenience script to fetch arXiv papers

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

source activate_venv.sh

# Default to fetching last 7 days if no arguments provided
if [ $# -eq 0 ]; then
    echo "Fetching papers from the last 7 days..."
    cd src
    python3 fetch_arxiv.py --recent --days 7
else
    # Pass all arguments to the fetch script
    cd src
    python3 fetch_arxiv.py "$@"
fi
