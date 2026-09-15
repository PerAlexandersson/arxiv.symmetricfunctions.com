#!/usr/bin/env bash
# sync_to_prod.sh — Deploy code/config to production.
#
# What this does:
#   1. Upload source code, templates, static assets, and passenger_wsgi.py
#   2. Upload .env.production as the remote .env
#   3. Install Python dependencies on the server
#   4. Refresh the persistent SymCat label snapshot
#   5. Restart Passenger
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

set -euo pipefail

REMOTE_HOST="symmetricf@ns12.inleed.net"
REMOTE_PORT="2020"
REMOTE_PATH="domains/arxiv.symmetricfunctions.com"
ARXIV_PYTHON_VERSION="${ARXIV_PYTHON_VERSION:-3.11}"
REMOTE_VENV="~/virtualenv/domains/arxiv.symmetricfunctions.com/$ARXIV_PYTHON_VERSION/bin/activate"
PASSENGER_PYTHON="/home/symmetricf/virtualenv/domains/arxiv.symmetricfunctions.com/$ARXIV_PYTHON_VERSION/bin/python3"

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROD_ENV="$SCRIPT_DIR/.env.production"

[ -f "$PROD_ENV" ] || {
    echo "Error: .env.production not found at $PROD_ENV"
    exit 1
}

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

printf '%s\n' "========================================="
printf '%s\n' "  Deploy -> production (code only)"
printf '%s\n' "========================================="
printf '%s\n' "  Remote: $REMOTE_HOST:$REMOTE_PORT"
printf '%s\n' ""

printf '%b\n' "${YELLOW}Preflight: checking SSH command execution...${NC}"
if ! ssh -p "$REMOTE_PORT" "$REMOTE_HOST" "printf '%s\n' ssh-ok" >/dev/null; then
    printf '%s\n' "Error: SSH login worked poorly or remote command execution is disabled."
    printf '%s\n' "Try: ssh -p $REMOTE_PORT $REMOTE_HOST 'echo ok'"
    exit 1
fi
if ! ssh -p "$REMOTE_PORT" "$REMOTE_HOST" "test -x '$PASSENGER_PYTHON'"; then
    printf '%s\n' "Error: cPanel Python $ARXIV_PYTHON_VERSION is not available at $PASSENGER_PYTHON"
    exit 1
fi
ssh -p "$REMOTE_PORT" "$REMOTE_HOST" "'$PASSENGER_PYTHON' --version"
if [[ "$ARXIV_PYTHON_VERSION" == 3.9 ]]; then
    printf '%b\n' "${YELLOW}Warning: Python 3.9 is end-of-life; select a newer cPanel runtime when the host offers one.${NC}"
fi

printf '%b\n' "${YELLOW}Preflight: checking the production list schema...${NC}"
LIST_SCHEMA_COLUMNS="$(ssh -p "$REMOTE_PORT" "$REMOTE_HOST" "
    set -a
    . ~/$REMOTE_PATH/.env
    set +a
    MYSQL_PWD=\"\$DB_PASSWORD\" mariadb \
      --host=\"\${DB_HOST:-localhost}\" \
      --user=\"\$DB_USER\" \
      --database=\"\$DB_NAME\" \
      --batch --skip-column-names \
      --execute=\"SELECT COUNT(*) FROM information_schema.COLUMNS
                  WHERE TABLE_SCHEMA = DATABASE()
                    AND TABLE_NAME = 'user_lists'
                    AND COLUMN_NAME IN ('category_id', 'paper_id')\"
")"
if [[ "$LIST_SCHEMA_COLUMNS" != "2" ]]; then
    printf '%s\n' "Error: production user_lists is not normalized."
    printf '%s\n' "Back it up and apply database/migrate_normalize_user_lists.sql before deploying."
    exit 1
fi

printf '%b\n' "${YELLOW}Step 1: Ensuring remote directories exist...${NC}"
ssh -p "$REMOTE_PORT" "$REMOTE_HOST" "
    mkdir -p ~/$REMOTE_PATH/src
    mkdir -p ~/$REMOTE_PATH/src/static
    mkdir -p ~/$REMOTE_PATH/src/templates
    mkdir -p ~/$REMOTE_PATH/src/templates/admin
    mkdir -p ~/$REMOTE_PATH/docs
    mkdir -p ~/$REMOTE_PATH/public_html/static
    mkdir -p ~/$REMOTE_PATH/tmp
    mkdir -p ~/$REMOTE_PATH/log
"

printf '%b\n' "${YELLOW}Step 2: Uploading code and config...${NC}"
scp -P "$REMOTE_PORT" "$SCRIPT_DIR/passenger_wsgi.py" \
    "$REMOTE_HOST:~/$REMOTE_PATH/"
scp -P "$REMOTE_PORT" "$SCRIPT_DIR/requirements.txt" \
    "$REMOTE_HOST:~/$REMOTE_PATH/"
scp -P "$REMOTE_PORT" "$SCRIPT_DIR/cron_update.sh" \
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
scp -P "$REMOTE_PORT" "$SCRIPT_DIR/docs/openapi-v1.yaml" \
    "$REMOTE_HOST:~/$REMOTE_PATH/docs/"

if [ -f "$SCRIPT_DIR/keywords.csv" ]; then
    scp -P "$REMOTE_PORT" "$SCRIPT_DIR/keywords.csv" \
        "$REMOTE_HOST:~/$REMOTE_PATH/keywords.csv"
fi

HTACCESS_TMP="$(mktemp)"
trap 'rm -f "$HTACCESS_TMP"' EXIT
cat > "$HTACCESS_TMP" <<EOF
PassengerEnabled on
PassengerAppType wsgi
PassengerStartupFile passenger_wsgi.py
PassengerAppRoot /home/symmetricf/$REMOTE_PATH
PassengerPython $PASSENGER_PYTHON
PassengerAppEnv production
<FilesMatch "\\.(jpg|jpeg|png|gif|css|js|ico|svg|woff|woff2|ttf|eot)\$">
    PassengerEnabled off
</FilesMatch>
EOF
scp -P "$REMOTE_PORT" "$HTACCESS_TMP" \
    "$REMOTE_HOST:~/$REMOTE_PATH/public_html/.htaccess"

if [ -f "$SCRIPT_DIR/deployment/static_htaccess" ]; then
    scp -P "$REMOTE_PORT" "$SCRIPT_DIR/deployment/static_htaccess" \
        "$REMOTE_HOST:~/$REMOTE_PATH/public_html/static/.htaccess"
fi

printf '%b\n' "${YELLOW}Step 3: Installing dependencies...${NC}"
ssh -p "$REMOTE_PORT" "$REMOTE_HOST" "
    set -e
    . $REMOTE_VENV
    cd ~/$REMOTE_PATH
    pip install -r requirements.txt
    chmod 600 ~/$REMOTE_PATH/.env
    chmod 755 passenger_wsgi.py
    chmod 755 cron_update.sh
    chmod -R 755 public_html
    chmod 664 public_html/static/*.css public_html/static/*.js 2>/dev/null || true
"

printf '%b\n' "${YELLOW}Step 4: Refreshing the SymCat label snapshot...${NC}"
if ! ssh -p "$REMOTE_PORT" "$REMOTE_HOST" "
    . $REMOTE_VENV
    cd ~/$REMOTE_PATH/src
    python -c \"from app import refresh_sf_labels; count, error = refresh_sf_labels(); print('SymCat labels:', count); raise SystemExit(1 if error else 0)\"
"; then
    printf '%b\n' "${YELLOW}Warning: SymCat labels could not be refreshed; the last cached snapshot will remain active.${NC}"
fi

printf '%b\n' "${YELLOW}Step 5: Restarting Passenger...${NC}"
ssh -p "$REMOTE_PORT" "$REMOTE_HOST" \
    "touch ~/$REMOTE_PATH/passenger_wsgi.py ~/$REMOTE_PATH/tmp/restart.txt"

printf '%s\n' ""
printf '%b\n' "${GREEN}=========================================${NC}"
printf '%b\n' "${GREEN}  Done!${NC}"
printf '%b\n' "${GREEN}=========================================${NC}"
printf '%s\n' "Code/config deploy complete. No database changes were made."
