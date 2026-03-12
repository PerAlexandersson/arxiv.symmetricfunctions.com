#!/bin/bash
# sync_to_prod.sh — Deploy code + sync keyword tables to production.
#
# What this does:
#   1. Deploy source code (src/, static/, templates/, passenger_wsgi.py)
#   2. Upload and apply all database/*.sql migrations (idempotent — safe to re-run)
#   3. Dump local keyword tables and import to prod
#   4. Run auto_tag.py on prod
#   5. Restart the app (touch passenger_wsgi.py)
#
# Does NOT touch papers/authors/paper_authors (prod data is authoritative).
#
# Usage:
#   ./sync_to_prod.sh              # deploy + sync keywords + auto_tag last 180 days
#   ./sync_to_prod.sh --all        # deploy + sync keywords + auto_tag all papers (slow)
#   ./sync_to_prod.sh --no-tag     # deploy + sync keywords, skip auto_tag
#   ./sync_to_prod.sh --no-code    # skip code deploy, keywords + auto_tag only

set -e

REMOTE_HOST="symmetricf@ns12.inleed.net"
REMOTE_PORT="2020"
REMOTE_PATH="domains/arxiv.symmetricfunctions.com"
REMOTE_VENV="~/virtualenv/domains/arxiv.symmetricfunctions.com/3.9/bin/activate"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_ENV="$SCRIPT_DIR/.env"
[ -f "$LOCAL_ENV" ] || { echo "Error: .env not found at $SCRIPT_DIR/.env"; exit 1; }

DUMP_FILE="$(mktemp /tmp/arxiv_keywords_dump_XXXXXX.sql)"
trap 'rm -f "$DUMP_FILE"' EXIT

# Parse flags
AUTO_TAG_ARGS=""
SKIP_TAG=false
SKIP_CODE=false
for arg in "$@"; do
    case "$arg" in
        --no-tag)  SKIP_TAG=true ;;
        --no-code) SKIP_CODE=true ;;
        *)         AUTO_TAG_ARGS="$AUTO_TAG_ARGS $arg" ;;
    esac
done
[ -z "$AUTO_TAG_ARGS" ] && AUTO_TAG_ARGS="--days 180"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Load local env vars for mysqldump
set -a
# shellcheck disable=SC1090
source "$LOCAL_ENV"
set +a

echo "========================================="
echo "  Deploy → production"
echo "========================================="
echo "  Local DB:  $DB_NAME @ $DB_HOST (user: $DB_USER)"
echo "  Remote:    $REMOTE_HOST:$REMOTE_PORT"
echo ""

# ── Step 1: deploy source code ────────────────────────────────────────────────
if [ "$SKIP_CODE" = true ]; then
    echo -e "${YELLOW}Skipping code deploy (--no-code specified).${NC}"
else
    echo -e "${YELLOW}Step 1: Deploying source code...${NC}"
    scp -P "$REMOTE_PORT" \
        "$SCRIPT_DIR/passenger_wsgi.py" \
        "$REMOTE_HOST:~/$REMOTE_PATH/"

    scp -P "$REMOTE_PORT" \
        "$SCRIPT_DIR/src/"*.py \
        "$REMOTE_HOST:~/$REMOTE_PATH/src/"

    scp -P "$REMOTE_PORT" \
        "$SCRIPT_DIR/src/static/style.css" \
        "$SCRIPT_DIR/src/static/utils.js" \
        "$REMOTE_HOST:~/$REMOTE_PATH/src/static/"

    scp -P "$REMOTE_PORT" \
        "$SCRIPT_DIR/src/static/style.css" \
        "$SCRIPT_DIR/src/static/utils.js" \
        "$REMOTE_HOST:~/$REMOTE_PATH/public_html/static/"

    scp -P "$REMOTE_PORT" \
        "$SCRIPT_DIR/src/templates/"*.html \
        "$REMOTE_HOST:~/$REMOTE_PATH/src/templates/"
    scp -P "$REMOTE_PORT" \
        "$SCRIPT_DIR/src/templates/admin/"*.html \
        "$REMOTE_HOST:~/$REMOTE_PATH/src/templates/admin/"

    # Restart app (touch both passenger_wsgi.py and tmp/restart.txt for reliability)
    ssh -p "$REMOTE_PORT" "$REMOTE_HOST" "touch ~/$REMOTE_PATH/passenger_wsgi.py ~/$REMOTE_PATH/tmp/restart.txt"
    echo -e "${GREEN}  Code deployed and app restarted${NC}"
fi

# ── Step 2: upload and apply all database migrations ─────────────────────────
echo -e "${YELLOW}Step 2: Uploading and applying database migrations...${NC}"
# Only migration files — never schema.sql (that drops all tables, for fresh installs only)
MIGRATIONS=(
    # Add new migration files here when needed; remove once applied everywhere.
)

for fname in "${MIGRATIONS[@]}"; do
    scp -P "$REMOTE_PORT" "$SCRIPT_DIR/database/$fname" "$REMOTE_HOST:~/$REMOTE_PATH/database/$fname"
    ssh -p "$REMOTE_PORT" "$REMOTE_HOST" "
        set -a
        source ~/domains/arxiv.symmetricfunctions.com/.env
        set +a
        cd ~/domains/arxiv.symmetricfunctions.com
        mysql -u \"\$DB_USER\" -p\"\$DB_PASSWORD\" \"\$DB_NAME\" < database/$fname 2>/dev/null \
            && echo '  $fname: applied' \
            || echo '  $fname: skipped (already applied or no-op)'
    "
done
echo -e "${GREEN}  Migrations OK${NC}"

# ── Step 3: dump local keyword tables ────────────────────────────────────────
echo -e "${YELLOW}Step 3: Dumping local keyword tables...${NC}"
mysqldump \
    --no-create-info \
    --insert-ignore \
    --skip-triggers \
    -h "$DB_HOST" \
    -u "$DB_USER" \
    -p"$DB_PASSWORD" \
    "$DB_NAME" \
    keywords keyword_aliases ignored_candidates math_words \
    > "$DUMP_FILE"
echo -e "${GREEN}  Dumped${NC}"

# ── Step 4: upload and import on prod ────────────────────────────────────────
echo -e "${YELLOW}Step 4: Uploading and importing keyword data...${NC}"
scp -P "$REMOTE_PORT" "$DUMP_FILE" "$REMOTE_HOST:/tmp/kw_import.sql"

ssh -p "$REMOTE_PORT" "$REMOTE_HOST" 'bash -s' << 'ENDSSH'
set -e
set -a
source ~/domains/arxiv.symmetricfunctions.com/.env
set +a
mysql -u "$DB_USER" -p"$DB_PASSWORD" "$DB_NAME" < /tmp/kw_import.sql
rm /tmp/kw_import.sql
echo "  Import done."
ENDSSH
echo -e "${GREEN}  Keyword data imported${NC}"

# ── Step 5: auto_tag on prod ──────────────────────────────────────────────────
if [ "$SKIP_TAG" = true ]; then
    echo -e "${YELLOW}Skipping auto_tag (--no-tag specified).${NC}"
else
    echo -e "${YELLOW}Step 5: Running auto_tag.py on production ($AUTO_TAG_ARGS)...${NC}"
    ssh -p "$REMOTE_PORT" "$REMOTE_HOST" "
        set -e
        source $REMOTE_VENV
        cd ~/$REMOTE_PATH/src
        python3 auto_tag.py "$AUTO_TAG_ARGS"
    "
    echo -e "${GREEN}  auto_tag done${NC}"
fi

echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}  Done!${NC}"
echo -e "${GREEN}=========================================${NC}"
