#!/bin/bash
# activate_venv.sh - Source this file to activate the project's virtual environment.
# Usage: source activate_venv.sh
#
# Automatically runs setup_venv.sh if the venv is missing or broken.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PROJECT_HASH=$(echo -n "$SCRIPT_DIR" | md5sum | cut -d' ' -f1 | cut -c1-8)
VENV_DIR="$HOME/.cache/arxiv-venv-$PROJECT_HASH"

if [ ! -d "$VENV_DIR" ] || ! source "$VENV_DIR/bin/activate" 2>/dev/null || ! python3 -c "import flask" 2>/dev/null; then
    echo "Virtual environment not found or broken, setting up..."
    "$SCRIPT_DIR/setup_venv.sh"
fi

if [ -z "$VIRTUAL_ENV" ]; then
    source "$VENV_DIR/bin/activate"
fi
