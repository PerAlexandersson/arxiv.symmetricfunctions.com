#!/bin/sh
# sync_to_prod.sh — Deploy code/config to production.
#
# What this does:
#   1. Upload source code, templates, static assets, and passenger_wsgi.py
#   2. Upload .env.production as the remote .env
#   3. Install Python dependencies on the server
#   4. Restart Passenger
#
# What this does NOT do:
#   - apply SQL migrations
#   - import database/schema.sql
#   - dump/import keyword tables
#   - run auto_tag.py
#   - fetch papers
#
# The production database is authoritative and should only be changed
# intentionally, outside routine code deploys.

set -eu

REMOTE_HOST="symmetricf@ns12.inleed.net"
REMOTE_PORT="2020"
REMOTE_PATH="domains/arxiv.symmetricfunctions.com"
REMOTE_VENV="~/virtualenv/domains/arxiv.symmetricfunctions.com/3.9/bin/activate"

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROD_ENV="$SCRIPT_DIR/.env.production"

[ -f "$PROD_ENV" ] || {
    echo "Error: .env.production not found at $PROD_ENV"
    exit 1
}

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "========================================="
echo "  Deploy → production (code only)"
echo "========================================="
echo "  Remote: $REMOTE_HOST:$REMOTE_PORT"
echo ""

echo -e "${YELLOW}Step 1: Ensuring remote directories exist...${NC}"
ssh -p "$REMOTE_PORT" "$REMOTE_HOST" "
    mkdir -p ~/$REMOTE_PATH/src
    mkdir -p ~/$REMOTE_PATH/src/static
    mkdir -p ~/$REMOTE_PATH/src/templates
    mkdir -p ~/$REMOTE_PATH/src/templates/admin
    mkdir -p ~/$REMOTE_PATH/public_html/static
    mkdir -p ~/$REMOTE_PATH/tmp
    mkdir -p ~/$REMOTE_PATH/log
"

echo -e "${YELLOW}Step 2: Uploading code and config...${NC}"
scp -P "$REMOTE_PORT" "$SCRIPT_DIR/passenger_wsgi.py" \
    "$REMOTE_HOST:~/$REMOTE_PATH/"
scp -P "$REMOTE_PORT" "$SCRIPT_DIR/requirements.txt" \
    "$REMOTE_HOST:~/$REMOTE_PATH/"
scp -P "$REMOTE_PORT" "$PROD_ENV" \
    "$REMOTE_HOST:~/$REMOTE_PATH/.env"

scp -P "$REMOTE_PORT" "$SCRIPT_DIR/src/"*.py \
    "$REMOTE_HOST:~/$REMOTE_PATH/src/"
scp -P "$REMOTE_PORT" "$SCRIPT_DIR/src/static/"* \
    "$REMOTE_HOST:~/$REMOTE_PATH/src/static/"
scp -P "$REMOTE_PORT" "$SCRIPT_DIR/src/static/"* \
    "$REMOTE_HOST:~/$REMOTE_PATH/public_html/static/"
scp -P "$REMOTE_PORT" "$SCRIPT_DIR/src/templates/"*.html \
    "$REMOTE_HOST:~/$REMOTE_PATH/src/templates/"
scp -P "$REMOTE_PORT" "$SCRIPT_DIR/src/templates/admin/"*.html \
    "$REMOTE_HOST:~/$REMOTE_PATH/src/templates/admin/"

if [ -f "$SCRIPT_DIR/keywords.csv" ]; then
    scp -P "$REMOTE_PORT" "$SCRIPT_DIR/keywords.csv" \
        "$REMOTE_HOST:~/$REMOTE_PATH/keywords.csv"
fi

if [ -f "$SCRIPT_DIR/deployment/.htaccess" ]; then
    scp -P "$REMOTE_PORT" "$SCRIPT_DIR/deployment/.htaccess" \
        "$REMOTE_HOST:~/$REMOTE_PATH/public_html/.htaccess"
fi

if [ -f "$SCRIPT_DIR/deployment/static_htaccess" ]; then
    scp -P "$REMOTE_PORT" "$SCRIPT_DIR/deployment/static_htaccess" \
        "$REMOTE_HOST:~/$REMOTE_PATH/public_html/static/.htaccess"
fi

echo -e "${YELLOW}Step 3: Installing dependencies...${NC}"
ssh -p "$REMOTE_PORT" "$REMOTE_HOST" "
    set -e
    source $REMOTE_VENV
    cd ~/$REMOTE_PATH
    pip install -r requirements.txt
    chmod 755 passenger_wsgi.py
    chmod -R 755 public_html
    chmod 664 public_html/static/*.css public_html/static/*.js 2>/dev/null || true
"

echo -e "${YELLOW}Step 4: Restarting Passenger...${NC}"
ssh -p "$REMOTE_PORT" "$REMOTE_HOST" \
    "touch ~/$REMOTE_PATH/passenger_wsgi.py ~/$REMOTE_PATH/tmp/restart.txt"

echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}  Done!${NC}"
echo -e "${GREEN}=========================================${NC}"
echo "Code/config deploy complete. No database changes were made."
