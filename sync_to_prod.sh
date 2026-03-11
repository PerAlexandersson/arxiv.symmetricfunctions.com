#!/bin/bash
# sync_to_prod.sh — Sync keyword tables to production and run auto_tag.
#
# Does NOT touch papers/authors/paper_authors (prod data is authoritative).
# Safe to re-run: uses INSERT IGNORE so existing rows are kept.
#
# Usage:
#   ./sync_to_prod.sh              # sync keywords + auto_tag last 180 days
#   ./sync_to_prod.sh --all        # sync keywords + auto_tag all papers (slow)
#   ./sync_to_prod.sh --no-tag     # sync keywords only, skip auto_tag

set -e

REMOTE_HOST="symmetricf@ns12.inleed.net"
REMOTE_PORT="2020"
REMOTE_PATH="domains/arxiv.symmetricfunctions.com"
REMOTE_VENV="~/virtualenv/domains/arxiv.symmetricfunctions.com/3.9/bin/activate"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Always use the local .env for the local mysqldump credentials.
LOCAL_ENV="$SCRIPT_DIR/.env"
[ -f "$LOCAL_ENV" ] || { echo "Error: .env not found at $SCRIPT_DIR/.env"; exit 1; }

DUMP_FILE="$(mktemp /tmp/arxiv_keywords_dump_XXXXXX.sql)"
trap 'rm -f "$DUMP_FILE"' EXIT

# Parse flags
AUTO_TAG_ARGS=""
SKIP_TAG=false
for arg in "$@"; do
    case "$arg" in
        --no-tag) SKIP_TAG=true ;;
        *)        AUTO_TAG_ARGS="$AUTO_TAG_ARGS $arg" ;;
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
echo "  Sync keyword tables → production"
echo "========================================="
echo "  Local DB:  $DB_NAME @ $DB_HOST (user: $DB_USER)"
echo "  Remote:    $REMOTE_HOST:$REMOTE_PORT"
echo ""

# ── Step 1: upload migration files, apply on prod ────────────────────────────
echo -e "${YELLOW}Step 1: Uploading migration files and applying on production...${NC}"
scp -P "$REMOTE_PORT" "$SCRIPT_DIR/database/migrate.sql" \
    "$REMOTE_HOST:~/$REMOTE_PATH/database/migrate.sql"
scp -P "$REMOTE_PORT" "$SCRIPT_DIR/database/migrate_users.sql" \
    "$REMOTE_HOST:~/$REMOTE_PATH/database/migrate_users.sql"

ssh -p "$REMOTE_PORT" "$REMOTE_HOST" 'bash -s' << 'ENDSSH'
set -e
set -a
source ~/domains/arxiv.symmetricfunctions.com/.env
set +a
cd ~/domains/arxiv.symmetricfunctions.com
mysql -u "$DB_USER" -p"$DB_PASSWORD" "$DB_NAME" < database/migrate.sql
echo "  migrate.sql applied."
mysql -u "$DB_USER" -p"$DB_PASSWORD" "$DB_NAME" < database/migrate_users.sql
echo "  migrate_users.sql applied."
ENDSSH
echo -e "${GREEN}  Schema OK${NC}"

# ── Step 2: dump local keyword tables ────────────────────────────────────────
echo -e "${YELLOW}Step 2: Dumping local keyword tables...${NC}"
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
echo -e "${GREEN}  Dumped to $DUMP_FILE${NC}"

# ── Step 3: upload and import on prod ────────────────────────────────────────
echo -e "${YELLOW}Step 3: Uploading and importing keyword data...${NC}"
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

# ── Step 4: auto_tag on prod ──────────────────────────────────────────────────
if [ "$SKIP_TAG" = true ]; then
    echo -e "${YELLOW}Skipping auto_tag (--no-tag specified).${NC}"
else
    echo -e "${YELLOW}Step 4: Running auto_tag.py on production ($AUTO_TAG_ARGS)...${NC}"
    # Use heredoc so $REMOTE_VENV and $AUTO_TAG_ARGS expand locally,
    # but the rest runs in the remote shell.
    ssh -p "$REMOTE_PORT" "$REMOTE_HOST" "
        set -e
        source $REMOTE_VENV
        cd ~/$REMOTE_PATH/src
        python3 auto_tag.py $AUTO_TAG_ARGS
    "
    echo -e "${GREEN}  auto_tag done${NC}"
fi

echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}  Done!${NC}"
echo -e "${GREEN}=========================================${NC}"
