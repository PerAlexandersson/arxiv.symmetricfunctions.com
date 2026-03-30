#!/bin/bash
# batch_doi_lookup.sh - Run DOI lookup in batches, gentle on Crossref.
#
# Usage:
#   ./batch_doi_lookup.sh                        # 500 papers from 2023-01-01 backwards
#   ./batch_doi_lookup.sh 200                    # custom batch size
#   ./batch_doi_lookup.sh 500 0.85               # custom batch + threshold
#   ./batch_doi_lookup.sh 500 0.90 2020-01-01    # start from a specific date backwards

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
source activate_venv.sh

BATCH=${1:-500}
THRESHOLD=${2:-0.90}
START_DATE=${3:-2023-01-01}

echo "============================================="
echo "  DOI Batch Lookup"
echo "  Batch size:      $BATCH"
echo "  Auto-approve:    >= $THRESHOLD"
echo "  Papers before:   $START_DATE (working backwards)"
echo "  Rate:            0.5s between requests"
echo "  Estimated time:  ~$(( BATCH / 2 / 60 )) min"
echo "============================================="
echo ""

cd src
python3 doi_lookup.py \
    --batch "$BATCH" \
    --auto-approve "$THRESHOLD" \
    --min-age 60 \
    --to-date "$START_DATE"
