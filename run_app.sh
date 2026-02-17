#!/bin/bash
# Simple script to run the Flask app

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

source activate_venv.sh

# Run Flask app
cd src
echo ""
echo "Starting arXiv Combinatorics Frontend..."
echo "Visit http://localhost:5000 in your browser"
echo "Press Ctrl+C to stop"
echo ""

python3 app.py
