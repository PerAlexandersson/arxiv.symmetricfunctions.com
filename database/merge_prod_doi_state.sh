#!/bin/bash
# Merge production DOI review state into the local DB without replacing
# local-only DOI lookup results.
#
# Usage:
#   cd database && ./merge_prod_doi_state.sh          # dry run
#   cd database && ./merge_prod_doi_state.sh --apply  # apply changes

set -euo pipefail

MODE="dry-run"
if [[ $# -gt 1 ]]; then
    echo "Usage: $0 [--apply]"
    exit 1
fi
if [[ $# -eq 1 ]]; then
    case "$1" in
        --apply)
            MODE="apply"
            ;;
        -h|--help)
            echo "Usage: $0 [--apply]"
            echo ""
            echo "Dry-run is the default."
            echo "Use --apply to write the DOI-only merge into the local DB."
            exit 0
            ;;
        *)
            echo "Usage: $0 [--apply]"
            exit 1
            ;;
    esac
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ ! -f "$ROOT_DIR/.env" ]]; then
    echo "Error: $ROOT_DIR/.env not found."
    exit 1
fi
if [[ ! -f "$ROOT_DIR/.env.production" ]]; then
    echo "Error: $ROOT_DIR/.env.production not found."
    exit 1
fi

source "$ROOT_DIR/activate_venv.sh"

python3 - "$MODE" "$ROOT_DIR" <<'PY'
import base64
import csv
import io
import shlex
import subprocess
import sys
from decimal import Decimal

import pymysql
from dotenv import dotenv_values

REMOTE_HOST = "symmetricf@ns12.inleed.net"
REMOTE_PORT = "2020"


def normalize_conf(value):
    if value in (None, ""):
        return None
    return format(Decimal(str(value)), "0.3f")


def decode_b64(value):
    if not value:
        return ""
    return base64.b64decode(value).decode("utf-8")


def fetch_prod_rows(prod_env, sql):
    remote_cmd = (
        f"MYSQL_PWD={shlex.quote(prod_env['DB_PASSWORD'])} "
        f"mysql -N -B --raw -u {shlex.quote(prod_env['DB_USER'])} "
        f"{shlex.quote(prod_env['DB_NAME'])} -e {shlex.quote(sql)}"
    )
    res = subprocess.run(
        ["ssh", "-p", REMOTE_PORT, REMOTE_HOST, remote_cmd],
        check=True,
        capture_output=True,
        text=True,
    )
    if not res.stdout.strip():
        return []
    return list(csv.reader(io.StringIO(res.stdout), delimiter="\t"))


def fetch_local_rows(cur, sql_prefix, values, row_handler):
    rows = []
    values = sorted(values)
    for i in range(0, len(values), 500):
        chunk = values[i:i + 500]
        placeholders = ",".join(["%s"] * len(chunk))
        cur.execute(sql_prefix.format(placeholders=placeholders), chunk)
        rows.extend(row_handler(cur.fetchall()))
    return rows


def local_counts(cur):
    cur.execute("SELECT status, COUNT(*) AS c FROM doi_candidates GROUP BY status ORDER BY status")
    doi_counts = {row["status"]: row["c"] for row in cur.fetchall()}
    cur.execute(
        "SELECT COALESCE(doi_status, 'NULL') AS status, COUNT(*) AS c "
        "FROM papers GROUP BY status ORDER BY status"
    )
    paper_counts = {row["status"]: row["c"] for row in cur.fetchall()}
    return doi_counts, paper_counts


def print_counts(label, doi_counts, paper_counts):
    print(label)
    print(
        "  doi_candidates:",
        f"pending={doi_counts.get('pending', 0)}",
        f"approved={doi_counts.get('approved', 0)}",
        f"rejected={doi_counts.get('rejected', 0)}",
    )
    print(
        "  papers:",
        f"NULL={paper_counts.get('NULL', 0)}",
        f"arxiv={paper_counts.get('arxiv', 0)}",
        f"auto={paper_counts.get('auto', 0)}",
        f"verified={paper_counts.get('verified', 0)}",
    )


def sample_lines(label, items, formatter):
    if not items:
        return
    print(label)
    for item in items[:5]:
        print(" ", formatter(item))


mode = sys.argv[1]
root_dir = sys.argv[2]

prod_env = dotenv_values(f"{root_dir}/.env.production")
local_env = dotenv_values(f"{root_dir}/.env")
for name, env in (("production", prod_env), ("local", local_env)):
    for key in ("DB_USER", "DB_PASSWORD", "DB_NAME"):
        if not env.get(key):
            raise SystemExit(f"Missing {key} in {name} env")

print("Fetching production DOI papers...")
prod_papers_rows = fetch_prod_rows(
    prod_env,
    "SELECT arxiv_id, doi, doi_status, "
    "COALESCE(CAST(doi_confidence AS CHAR), ''), "
    "COALESCE(DATE_FORMAT(doi_checked_at, '%Y-%m-%d %H:%i:%s'), '') "
    "FROM papers "
    "WHERE doi_status IN ('auto', 'verified') "
    "ORDER BY arxiv_id",
)
print(f"  {len(prod_papers_rows)} rows")

print("Fetching production reviewed DOI candidates...")
prod_candidates_rows = fetch_prod_rows(
    prod_env,
    "SELECT p.arxiv_id, dc.doi, COALESCE(CAST(dc.confidence AS CHAR), ''), "
    "REPLACE(TO_BASE64(COALESCE(dc.crossref_title, '')), '\n', ''), "
    "REPLACE(TO_BASE64(COALESCE(dc.crossref_authors, '')), '\n', ''), "
    "COALESCE(CAST(dc.crossref_year AS CHAR), ''), "
    "dc.status, "
    "COALESCE(DATE_FORMAT(dc.reviewed_at, '%Y-%m-%d %H:%i:%s'), ''), "
    "COALESCE(DATE_FORMAT(dc.created_at, '%Y-%m-%d %H:%i:%s'), '') "
    "FROM doi_candidates dc "
    "JOIN papers p ON p.id = dc.paper_id "
    "WHERE dc.status IN ('approved', 'rejected') "
    "ORDER BY p.arxiv_id, dc.doi",
)
print(f"  {len(prod_candidates_rows)} rows")

prod_papers = {
    row[0]: {
        "doi": row[1],
        "doi_status": row[2],
        "doi_confidence": normalize_conf(row[3]),
        "doi_checked_at": row[4] or None,
    }
    for row in prod_papers_rows
}
prod_candidates = {
    (row[0], row[1]): {
        "confidence": normalize_conf(row[2]),
        "crossref_title": decode_b64(row[3]),
        "crossref_authors": decode_b64(row[4]),
        "crossref_year": int(row[5]) if row[5] else None,
        "status": row[6],
        "reviewed_at": row[7] or None,
        "created_at": row[8] or None,
    }
    for row in prod_candidates_rows
}

relevant_arxiv_ids = set(prod_papers) | {arxiv_id for arxiv_id, _ in prod_candidates}

conn = pymysql.connect(
    host=local_env.get("DB_HOST", "localhost"),
    user=local_env["DB_USER"],
    password=local_env["DB_PASSWORD"],
    database=local_env["DB_NAME"],
    charset=local_env.get("DB_CHARSET", "utf8mb4"),
    cursorclass=pymysql.cursors.DictCursor,
    autocommit=False,
)
cur = conn.cursor()

before_doi_counts, before_paper_counts = local_counts(cur)
print_counts("Local counts before merge:", before_doi_counts, before_paper_counts)

print("Fetching matching local papers...")
local_papers = {}
paper_rows = fetch_local_rows(
    cur,
    "SELECT id, arxiv_id, COALESCE(doi, '') AS doi, "
    "COALESCE(doi_status, '') AS doi_status, "
    "COALESCE(CAST(doi_confidence AS CHAR), '') AS doi_confidence, "
    "COALESCE(DATE_FORMAT(doi_checked_at, '%%Y-%%m-%%d %%H:%%i:%%s'), '') AS doi_checked_at "
    "FROM papers WHERE arxiv_id IN ({placeholders})",
    relevant_arxiv_ids,
    lambda rows: rows,
)
for row in paper_rows:
    local_papers[row["arxiv_id"]] = {
        "id": row["id"],
        "doi": row["doi"],
        "doi_status": row["doi_status"],
        "doi_confidence": normalize_conf(row["doi_confidence"]),
        "doi_checked_at": row["doi_checked_at"] or None,
    }
print(f"  {len(local_papers)} rows")

print("Fetching matching local DOI candidates...")
local_candidates = {}
candidate_rows = fetch_local_rows(
    cur,
    "SELECT p.arxiv_id, dc.paper_id, dc.doi, "
    "COALESCE(CAST(dc.confidence AS CHAR), '') AS confidence, "
    "COALESCE(dc.crossref_title, '') AS crossref_title, "
    "COALESCE(dc.crossref_authors, '') AS crossref_authors, "
    "dc.crossref_year, dc.status, "
    "COALESCE(DATE_FORMAT(dc.reviewed_at, '%%Y-%%m-%%d %%H:%%i:%%s'), '') AS reviewed_at, "
    "COALESCE(DATE_FORMAT(dc.created_at, '%%Y-%%m-%%d %%H:%%i:%%s'), '') AS created_at "
    "FROM doi_candidates dc "
    "JOIN papers p ON p.id = dc.paper_id "
    "WHERE p.arxiv_id IN ({placeholders})",
    relevant_arxiv_ids,
    lambda rows: rows,
)
for row in candidate_rows:
    local_candidates[(row["arxiv_id"], row["doi"])] = {
        "paper_id": row["paper_id"],
        "confidence": normalize_conf(row["confidence"]),
        "crossref_title": row["crossref_title"],
        "crossref_authors": row["crossref_authors"],
        "crossref_year": row["crossref_year"],
        "status": row["status"],
        "reviewed_at": row["reviewed_at"] or None,
        "created_at": row["created_at"] or None,
    }
print(f"  {len(local_candidates)} rows")

missing_papers = []
paper_updates = []
for arxiv_id, prod_row in prod_papers.items():
    local_row = local_papers.get(arxiv_id)
    if not local_row:
        missing_papers.append(arxiv_id)
        continue
    if (
        local_row["doi"] != prod_row["doi"]
        or local_row["doi_status"] != prod_row["doi_status"]
        or local_row["doi_confidence"] != prod_row["doi_confidence"]
        or local_row["doi_checked_at"] != prod_row["doi_checked_at"]
    ):
        paper_updates.append({
            "paper_id": local_row["id"],
            "arxiv_id": arxiv_id,
            "doi": prod_row["doi"],
            "doi_status": prod_row["doi_status"],
            "doi_confidence": prod_row["doi_confidence"],
            "doi_checked_at": prod_row["doi_checked_at"],
        })

candidate_updates = []
candidate_inserts = []
missing_candidate_papers = []
for key, prod_row in prod_candidates.items():
    arxiv_id, doi = key
    local_paper = local_papers.get(arxiv_id)
    if not local_paper:
        missing_candidate_papers.append(arxiv_id)
        continue
    local_row = local_candidates.get(key)
    if not local_row:
        candidate_inserts.append({
            "paper_id": local_paper["id"],
            "arxiv_id": arxiv_id,
            "doi": doi,
            **prod_row,
        })
        continue
    if (
        local_row["confidence"] != prod_row["confidence"]
        or local_row["crossref_title"] != prod_row["crossref_title"]
        or local_row["crossref_authors"] != prod_row["crossref_authors"]
        or local_row["crossref_year"] != prod_row["crossref_year"]
        or local_row["status"] != prod_row["status"]
        or local_row["reviewed_at"] != prod_row["reviewed_at"]
        or local_row["created_at"] != prod_row["created_at"]
    ):
        candidate_updates.append({
            "paper_id": local_paper["id"],
            "arxiv_id": arxiv_id,
            "doi": doi,
            **prod_row,
        })

print("Planned DOI-only merge:")
print(f"  paper updates:       {len(paper_updates)}")
print(f"  candidate inserts:   {len(candidate_inserts)}")
print(f"  candidate updates:   {len(candidate_updates)}")
print(f"  missing local papers:{len(missing_papers)}")
if missing_candidate_papers:
    print(f"  missing candidate papers: {len(set(missing_candidate_papers))}")

sample_lines(
    "Sample paper updates:",
    paper_updates,
    lambda row: (
        f"{row['arxiv_id']} -> {row['doi_status']} "
        f"{row['doi']} conf={row['doi_confidence']}"
    ),
)
sample_lines(
    "Sample candidate inserts:",
    candidate_inserts,
    lambda row: (
        f"{row['arxiv_id']} {row['doi']} "
        f"status={row['status']} conf={row['confidence']}"
    ),
)
sample_lines(
    "Sample candidate updates:",
    candidate_updates,
    lambda row: (
        f"{row['arxiv_id']} {row['doi']} "
        f"status={row['status']} conf={row['confidence']}"
    ),
)
sample_lines("Sample missing local papers:", missing_papers, lambda row: row)

if mode != "apply":
    print("")
    print("Dry run only. No changes were written.")
    cur.close()
    conn.close()
    raise SystemExit(0)

if paper_updates:
    cur.executemany(
        "UPDATE papers SET doi=%s, doi_status=%s, doi_confidence=%s, doi_checked_at=%s "
        "WHERE id=%s",
        [
            (
                row["doi"],
                row["doi_status"],
                row["doi_confidence"],
                row["doi_checked_at"],
                row["paper_id"],
            )
            for row in paper_updates
        ],
    )

if candidate_inserts:
    cur.executemany(
        "INSERT INTO doi_candidates "
        "(paper_id, doi, confidence, crossref_title, crossref_authors, crossref_year, "
        " status, reviewed_at, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        [
            (
                row["paper_id"],
                row["doi"],
                row["confidence"],
                row["crossref_title"],
                row["crossref_authors"],
                row["crossref_year"],
                row["status"],
                row["reviewed_at"],
                row["created_at"],
            )
            for row in candidate_inserts
        ],
    )

if candidate_updates:
    cur.executemany(
        "UPDATE doi_candidates SET confidence=%s, crossref_title=%s, crossref_authors=%s, "
        "crossref_year=%s, status=%s, reviewed_at=%s, created_at=%s "
        "WHERE paper_id=%s AND doi=%s",
        [
            (
                row["confidence"],
                row["crossref_title"],
                row["crossref_authors"],
                row["crossref_year"],
                row["status"],
                row["reviewed_at"],
                row["created_at"],
                row["paper_id"],
                row["doi"],
            )
            for row in candidate_updates
        ],
    )

conn.commit()
after_doi_counts, after_paper_counts = local_counts(cur)
print("")
print_counts("Local counts after merge:", after_doi_counts, after_paper_counts)

cur.close()
conn.close()
PY
