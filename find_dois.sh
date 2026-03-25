#!/bin/bash
# find_dois.sh - Find DOIs for papers via Crossref API.
# Usage: ./find_dois.sh [args passed to doi_lookup.py]

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
source activate_venv.sh
cd src
python3 doi_lookup.py "$@"
