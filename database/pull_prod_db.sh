#!/bin/bash
# Pull production database and replace local database
# Usage: cd database && ./pull_prod_db.sh

set -e

# ── Production SSH config ─────────────────────────────────────────────────────
REMOTE_HOST="symmetricf@ns12.inleed.net"
REMOTE_PORT="2020"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Load production DB credentials ────────────────────────────────────────────
PROD_ENV="$SCRIPT_DIR/../.env.production"
[ -f "$PROD_ENV" ] || { echo "Error: $PROD_ENV not found."; exit 1; }
set -a
# shellcheck disable=SC1090
source "$PROD_ENV"
set +a
PROD_DB_NAME="$DB_NAME"
PROD_DB_USER="$DB_USER"
PROD_DB_PASS="$DB_PASSWORD"

# ── Load local DB credentials (overwrite prod vars) ───────────────────────────
LOCAL_ENV="$SCRIPT_DIR/../.env"
[ -f "$LOCAL_ENV" ] || { echo "Error: $LOCAL_ENV not found."; exit 1; }
set -a
# shellcheck disable=SC1090
source "$LOCAL_ENV"
set +a
LOCAL_DB_NAME="$DB_NAME"
LOCAL_DB_USER="$DB_USER"
LOCAL_DB_PASS="$DB_PASSWORD"

# ── Colors ────────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "========================================="
echo "  Pull Production DB → Local"
echo "========================================="
echo "  Remote: $PROD_DB_NAME @ $REMOTE_HOST"
echo "  Local:  $LOCAL_DB_NAME @ localhost"
echo ""
echo -e "${RED}WARNING: This will REPLACE your local database!${NC}"
read -p "Continue? [y/N] " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Aborted."
    exit 0
fi

DUMP_FILE="$(mktemp /tmp/arxiv_prod_dump_XXXXXX.sql)"
trap 'rm -f "$DUMP_FILE"' EXIT

echo ""
echo -e "${YELLOW}Step 1: Dumping production database over SSH...${NC}"
ssh -p "$REMOTE_PORT" "$REMOTE_HOST" \
    "MYSQL_PWD='$PROD_DB_PASS' mysqldump --single-transaction --skip-add-drop-database \
     -u '$PROD_DB_USER' '$PROD_DB_NAME'" \
    > "$DUMP_FILE"

DUMP_SIZE=$(du -sh "$DUMP_FILE" | cut -f1)
echo "  Dump size: $DUMP_SIZE"

echo -e "${YELLOW}Step 2: Importing into local database '$LOCAL_DB_NAME'...${NC}"
MYSQL_PWD="$LOCAL_DB_PASS" mysql -u "$LOCAL_DB_USER" "$LOCAL_DB_NAME" < "$DUMP_FILE"

echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}Done! Local DB is now a copy of prod.${NC}"
echo -e "${GREEN}=========================================${NC}"
