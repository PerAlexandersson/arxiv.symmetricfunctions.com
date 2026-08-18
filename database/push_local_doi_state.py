#!/usr/bin/env python3
"""Guardedly merge the reviewed local DOI state into production.

The default mode is read-only: it compares the local and production databases
and writes a signed JSON plan.  ``--rollback-test`` applies that exact plan in
one transaction and rolls it back.  ``--apply`` commits only after the same
preconditions and postflight checks pass.

Production is reached through an SSH tunnel.  Database credentials are loaded
from the gitignored environment files and are never written to the plan.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import socket
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pymysql
from dotenv import dotenv_values


ROOT_DIR = Path(__file__).resolve().parents[1]
LOCAL_ENV_PATH = ROOT_DIR / ".env.local"
PRODUCTION_ENV_PATH = ROOT_DIR / ".env.production"
REMOTE_HOST = "symmetricf@ns12.inleed.net"
REMOTE_PORT = 2020
PLAN_VERSION = 1
CACHE_REBUILD_DELAY_SECONDS = 10 * 60

PAPER_FIELDS = (
    "doi",
    "doi_status",
    "doi_confidence",
    "doi_checked_at",
    "publication_url",
    "publication_venue_key",
    "publication_status",
    "editor_note",
)
CANDIDATE_UPDATE_FIELDS = (
    "confidence",
    "crossref_title",
    "crossref_authors",
    "crossref_year",
    "status",
    "reviewed_at",
)
CANDIDATE_INSERT_FIELDS = CANDIDATE_UPDATE_FIELDS + ("created_at",)


class MergeError(RuntimeError):
    """Raised when a production merge safeguard fails."""


def load_env(path: Path, label: str) -> dict[str, str]:
    values = {key: value for key, value in dotenv_values(path).items() if value is not None}
    missing = [key for key in ("DB_USER", "DB_PASSWORD", "DB_NAME") if not values.get(key)]
    if missing:
        raise MergeError(f"Missing {', '.join(missing)} in {label} environment")
    return values


def db_kwargs(env: dict[str, str], *, host: str, port: int) -> dict:
    return {
        "host": host,
        "port": port,
        "user": env["DB_USER"],
        "password": env["DB_PASSWORD"],
        "database": env["DB_NAME"],
        "charset": env.get("DB_CHARSET", "utf8mb4"),
        "cursorclass": pymysql.cursors.DictCursor,
        "autocommit": False,
        "init_command": "SET time_zone = '+00:00'",
        "connect_timeout": 10,
        "read_timeout": 60,
        "write_timeout": 60,
    }


def local_connection(env: dict[str, str]):
    return pymysql.connect(
        **db_kwargs(
            env,
            host=env.get("DB_HOST", "db"),
            port=int(env.get("DB_PORT", "3306")),
        )
    )


def reserve_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextlib.contextmanager
def production_connection(env: dict[str, str]):
    local_port = reserve_local_port()
    remote_db_host = env.get("DB_HOST", "127.0.0.1")
    remote_db_port = int(env.get("DB_PORT", "3306"))
    forward = f"127.0.0.1:{local_port}:{remote_db_host}:{remote_db_port}"
    process = subprocess.Popen(
        [
            "ssh",
            "-N",
            "-p",
            str(REMOTE_PORT),
            "-o",
            "BatchMode=yes",
            "-o",
            "ExitOnForwardFailure=yes",
            "-L",
            forward,
            REMOTE_HOST,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    conn = None
    try:
        deadline = time.monotonic() + 15
        last_error = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                detail = process.stderr.read().strip() if process.stderr else ""
                raise MergeError(f"SSH tunnel exited before connecting: {detail}")
            try:
                conn = pymysql.connect(
                    **db_kwargs(env, host="127.0.0.1", port=local_port)
                )
                break
            except pymysql.Error as exc:
                last_error = exc
                time.sleep(0.2)
        if conn is None:
            raise MergeError(f"Could not connect through the SSH tunnel: {last_error}")
        yield conn
    finally:
        if conn is not None:
            conn.close()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def paper_select(*, for_update: bool = False) -> str:
    suffix = " FOR UPDATE" if for_update else ""
    return f"""
        SELECT id, arxiv_base_id,
               doi, doi_status,
               CAST(doi_confidence AS CHAR) AS doi_confidence,
               doi_checked_at,
               publication_url, publication_venue_key, publication_status,
               editor_note
        FROM papers
        {{where}}
        ORDER BY arxiv_base_id
        {suffix}
    """


def candidate_select(*, for_update: bool = False) -> str:
    suffix = " FOR UPDATE" if for_update else ""
    return f"""
        SELECT p.arxiv_base_id, dc.doi,
               CAST(dc.confidence AS CHAR) AS confidence,
               dc.crossref_title, dc.crossref_authors, dc.crossref_year,
               dc.status, dc.reviewed_at, dc.created_at
        FROM doi_candidates dc
        JOIN papers p ON p.id = dc.paper_id
        {{where}}
        ORDER BY p.arxiv_base_id, dc.doi
        {suffix}
    """


def stable_db_value(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return value


def fetch_papers(cursor, base_ids: list[str] | None = None, *, for_update: bool = False):
    rows = []
    if base_ids is None:
        cursor.execute(paper_select(for_update=for_update).format(where=""))
        rows = cursor.fetchall()
    else:
        for start in range(0, len(base_ids), 500):
            chunk = base_ids[start:start + 500]
            placeholders = ",".join(["%s"] * len(chunk))
            sql = paper_select(for_update=for_update).format(
                where=f"WHERE arxiv_base_id IN ({placeholders})"
            )
            cursor.execute(sql, chunk)
            rows.extend(cursor.fetchall())
    return {
        row["arxiv_base_id"]: {
            field: stable_db_value(row[field]) for field in PAPER_FIELDS
        }
        for row in rows
    }


def fetch_paper_ids(cursor, base_ids: list[str]):
    result = {}
    for start in range(0, len(base_ids), 500):
        chunk = base_ids[start:start + 500]
        placeholders = ",".join(["%s"] * len(chunk))
        cursor.execute(
            f"SELECT id, arxiv_base_id FROM papers "
            f"WHERE arxiv_base_id IN ({placeholders}) FOR UPDATE",
            chunk,
        )
        result.update({row["arxiv_base_id"]: row["id"] for row in cursor.fetchall()})
    return result


def fetch_candidates(
    cursor,
    base_ids: list[str] | None = None,
    *,
    for_update: bool = False,
):
    rows = []
    if base_ids is None:
        cursor.execute(candidate_select(for_update=for_update).format(where=""))
        rows = cursor.fetchall()
    else:
        for start in range(0, len(base_ids), 500):
            chunk = base_ids[start:start + 500]
            placeholders = ",".join(["%s"] * len(chunk))
            sql = candidate_select(for_update=for_update).format(
                where=f"WHERE p.arxiv_base_id IN ({placeholders})"
            )
            cursor.execute(sql, chunk)
            rows.extend(cursor.fetchall())
    return {
        (row["arxiv_base_id"], row["doi"]): {
            field: stable_db_value(row[field]) for field in CANDIDATE_INSERT_FIELDS
        }
        for row in rows
    }


def fetch_reference_counts(cursor) -> dict[str, int]:
    queries = {
        "users": "SELECT COUNT(*) AS count FROM users",
        "user_list_rows": "SELECT COUNT(*) AS count FROM user_lists",
        "keywords": "SELECT COUNT(*) AS count FROM keywords",
        "candidate_orphans": (
            "SELECT COUNT(*) AS count FROM doi_candidates dc "
            "LEFT JOIN papers p ON p.id = dc.paper_id WHERE p.id IS NULL"
        ),
    }
    counts = {}
    for name, sql in queries.items():
        cursor.execute(sql)
        counts[name] = int(cursor.fetchone()["count"])
    return counts


def normalized_doi(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().lower() or None


def state_summary(papers: dict, candidates: dict, reference_counts: dict) -> dict:
    paper_statuses = Counter(
        row["doi_status"] if row["doi_status"] is not None else "NULL"
        for row in papers.values()
    )
    candidate_statuses = Counter(row["status"] for row in candidates.values())
    owners = defaultdict(list)
    for base_id, row in papers.items():
        doi = normalized_doi(row["doi"])
        if doi:
            owners[doi].append(base_id)
    shared = {
        doi: sorted(base_ids)
        for doi, base_ids in owners.items()
        if len(base_ids) > 1
    }
    return {
        "papers": len(papers),
        "papers_with_doi": sum(bool(normalized_doi(row["doi"])) for row in papers.values()),
        "papers_with_editor_note": sum(
            bool((row["editor_note"] or "").strip())
            for row in papers.values()
        ),
        "paper_statuses": dict(sorted(paper_statuses.items())),
        "doi_candidates": len(candidates),
        "candidate_statuses": dict(sorted(candidate_statuses.items())),
        "shared_normalized_doi_values": len(shared),
        "shared_owner_sets_sha256": sha256_json(shared),
        **reference_counts,
    }


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def state_digest(papers: dict, candidates: dict) -> str:
    payload = {
        "papers": [[base_id, row] for base_id, row in sorted(papers.items())],
        "candidates": [
            [base_id, doi, row]
            for (base_id, doi), row in sorted(candidates.items())
        ],
    }
    return sha256_json(payload)


def subset(row: dict, fields: tuple[str, ...]) -> dict:
    return {field: row[field] for field in fields}


def plan_digest(plan: dict) -> str:
    unsigned = {key: value for key, value in plan.items() if key != "plan_sha256"}
    return sha256_json(unsigned)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def generate_plan(local_conn, production_conn, backup_path: Path) -> dict:
    local_cur = local_conn.cursor()
    prod_cur = production_conn.cursor()
    try:
        local_conn.begin()
        production_conn.begin()
        local_papers = fetch_papers(local_cur)
        local_candidates = fetch_candidates(local_cur)
        prod_papers = fetch_papers(prod_cur)
        prod_candidates = fetch_candidates(prod_cur)
        prod_reference_counts = fetch_reference_counts(prod_cur)

        missing_production = sorted(set(local_papers) - set(prod_papers))
        if missing_production:
            sample = ", ".join(missing_production[:5])
            raise MergeError(
                f"Production is missing {len(missing_production)} local papers; sample: {sample}"
            )

        paper_updates = []
        for base_id, desired in sorted(local_papers.items()):
            expected = prod_papers[base_id]
            if expected != desired:
                paper_updates.append({
                    "arxiv_base_id": base_id,
                    "expected": expected,
                    "desired": desired,
                })

        candidate_upserts = []
        for (base_id, doi), desired in sorted(local_candidates.items()):
            expected = prod_candidates.get((base_id, doi))
            if expected is None:
                candidate_upserts.append({
                    "action": "insert",
                    "arxiv_base_id": base_id,
                    "doi": doi,
                    "expected": None,
                    "desired": desired,
                })
                continue
            expected_update = subset(expected, CANDIDATE_UPDATE_FIELDS)
            desired_update = subset(desired, CANDIDATE_UPDATE_FIELDS)
            if expected_update != desired_update:
                candidate_upserts.append({
                    "action": "update",
                    "arxiv_base_id": base_id,
                    "doi": doi,
                    "expected": expected_update,
                    "desired": desired_update,
                })

        production_only_candidates = sorted(
            [
                key
                for key in prod_candidates
                if key not in local_candidates and key[0] in local_papers
            ]
        )

        projected_papers = dict(prod_papers)
        for item in paper_updates:
            projected_papers[item["arxiv_base_id"]] = item["desired"]
        projected_candidates = dict(prod_candidates)
        for item in candidate_upserts:
            key = (item["arxiv_base_id"], item["doi"])
            if item["action"] == "insert":
                projected_candidates[key] = item["desired"]
            else:
                projected_candidates[key] = {
                    **projected_candidates[key],
                    **item["desired"],
                }

        plan = {
            "plan_version": PLAN_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "production_backup": {
                "local_path": str(backup_path.resolve()),
                "size_bytes": backup_path.stat().st_size,
                "sha256": sha256_file(backup_path),
            },
            "local_state_sha256": state_digest(local_papers, local_candidates),
            "production_summary_before": state_summary(
                prod_papers, prod_candidates, prod_reference_counts
            ),
            "production_summary_projected": state_summary(
                projected_papers, projected_candidates, prod_reference_counts
            ),
            "ignored_new_production_papers": len(set(prod_papers) - set(local_papers)),
            "preserved_production_only_candidates": [
                {"arxiv_base_id": base_id, "doi": doi}
                for base_id, doi in production_only_candidates
            ],
            "paper_updates": paper_updates,
            "candidate_upserts": candidate_upserts,
        }
        plan["plan_sha256"] = plan_digest(plan)
        return plan
    finally:
        local_conn.rollback()
        production_conn.rollback()
        local_cur.close()
        prod_cur.close()


def verify_plan(plan: dict):
    if plan.get("plan_version") != PLAN_VERSION:
        raise MergeError(f"Unsupported plan version: {plan.get('plan_version')}")
    expected = plan.get("plan_sha256")
    actual = plan_digest(plan)
    if not expected or expected != actual:
        raise MergeError("Plan checksum mismatch")


def verify_backup(plan: dict):
    backup = plan.get("production_backup") or {}
    path_value = backup.get("local_path")
    expected_sha = backup.get("sha256")
    expected_size = backup.get("size_bytes")
    if not path_value or not expected_sha or expected_size is None:
        raise MergeError("Plan does not record a verified production backup")
    path = Path(path_value)
    if not path.is_file():
        raise MergeError(f"Production backup is missing: {path}")
    if path.stat().st_size != expected_size:
        raise MergeError("Production backup size changed after planning")
    if sha256_file(path) != expected_sha:
        raise MergeError("Production backup checksum changed after planning")


def verify_local_state(local_conn, plan: dict):
    cursor = local_conn.cursor()
    try:
        local_conn.begin()
        papers = fetch_papers(cursor)
        candidates = fetch_candidates(cursor)
        actual = state_digest(papers, candidates)
        if actual != plan["local_state_sha256"]:
            raise MergeError("Local DOI state changed after the plan was generated")
    finally:
        local_conn.rollback()
        cursor.close()


def verify_action_preconditions(cursor, plan: dict):
    paper_items = plan["paper_updates"]
    base_ids = sorted({item["arxiv_base_id"] for item in paper_items})
    actual_papers = fetch_papers(cursor, base_ids, for_update=True) if base_ids else {}
    for item in paper_items:
        actual = actual_papers.get(item["arxiv_base_id"])
        if actual != item["expected"]:
            raise MergeError(
                f"Production paper precondition changed for {item['arxiv_base_id']}"
            )

    candidate_items = plan["candidate_upserts"]
    candidate_base_ids = sorted({item["arxiv_base_id"] for item in candidate_items})
    actual_candidates = (
        fetch_candidates(cursor, candidate_base_ids, for_update=True)
        if candidate_base_ids else {}
    )
    for item in candidate_items:
        key = (item["arxiv_base_id"], item["doi"])
        actual = actual_candidates.get(key)
        if item["action"] == "insert":
            if actual is not None:
                raise MergeError(
                    f"Candidate intended for insert now exists: {key[0]} {key[1]}"
                )
        elif actual is None or subset(actual, CANDIDATE_UPDATE_FIELDS) != item["expected"]:
            raise MergeError(f"Production candidate precondition changed: {key[0]} {key[1]}")


def apply_actions(cursor, plan: dict):
    paper_items = plan["paper_updates"]
    if paper_items:
        cursor.executemany(
            """
            UPDATE papers
            SET doi=%s, doi_status=%s, doi_confidence=%s, doi_checked_at=%s,
                publication_url=%s, publication_venue_key=%s,
                publication_status=%s, editor_note=%s,
                updated_at=updated_at
            WHERE arxiv_base_id=%s
            """,
            [
                tuple(item["desired"][field] for field in PAPER_FIELDS)
                + (item["arxiv_base_id"],)
                for item in paper_items
            ],
        )
        if cursor.rowcount != len(paper_items):
            raise MergeError(
                f"Paper update count mismatch: {cursor.rowcount} != {len(paper_items)}"
            )

    candidate_items = plan["candidate_upserts"]
    base_ids = sorted({item["arxiv_base_id"] for item in candidate_items})
    paper_ids = fetch_paper_ids(cursor, base_ids) if base_ids else {}
    if len(paper_ids) != len(base_ids):
        raise MergeError("Could not resolve every candidate paper by arxiv_base_id")

    inserts = [item for item in candidate_items if item["action"] == "insert"]
    if inserts:
        cursor.executemany(
            """
            INSERT INTO doi_candidates
                (paper_id, doi, confidence, crossref_title, crossref_authors,
                 crossref_year, status, reviewed_at, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (paper_ids[item["arxiv_base_id"]], item["doi"])
                + tuple(item["desired"][field] for field in CANDIDATE_INSERT_FIELDS)
                for item in inserts
            ],
        )
        if cursor.rowcount != len(inserts):
            raise MergeError(
                f"Candidate insert count mismatch: {cursor.rowcount} != {len(inserts)}"
            )

    updates = [item for item in candidate_items if item["action"] == "update"]
    if updates:
        cursor.executemany(
            """
            UPDATE doi_candidates
            SET confidence=%s, crossref_title=%s, crossref_authors=%s,
                crossref_year=%s, status=%s, reviewed_at=%s
            WHERE paper_id=%s AND doi=%s
            """,
            [
                tuple(item["desired"][field] for field in CANDIDATE_UPDATE_FIELDS)
                + (paper_ids[item["arxiv_base_id"]], item["doi"])
                for item in updates
            ],
        )
        if cursor.rowcount != len(updates):
            raise MergeError(
                f"Candidate update count mismatch: {cursor.rowcount} != {len(updates)}"
            )

    cursor.execute(
        """
        UPDATE site_stats
        SET cache_dirty_at=NOW(),
            cache_rebuild_after=DATE_ADD(NOW(), INTERVAL %s SECOND),
            updated_at=updated_at
        WHERE id=1
        """,
        (CACHE_REBUILD_DELAY_SECONDS,),
    )
    if cursor.rowcount != 1:
        raise MergeError("Expected exactly one site_stats cache row")


def verify_action_results(cursor, plan: dict):
    paper_items = plan["paper_updates"]
    base_ids = sorted({item["arxiv_base_id"] for item in paper_items})
    actual_papers = fetch_papers(cursor, base_ids) if base_ids else {}
    for item in paper_items:
        if actual_papers.get(item["arxiv_base_id"]) != item["desired"]:
            raise MergeError(f"Paper postflight failed for {item['arxiv_base_id']}")

    candidate_items = plan["candidate_upserts"]
    candidate_base_ids = sorted({item["arxiv_base_id"] for item in candidate_items})
    actual_candidates = fetch_candidates(cursor, candidate_base_ids) if candidate_base_ids else {}
    for item in candidate_items:
        key = (item["arxiv_base_id"], item["doi"])
        actual = actual_candidates.get(key)
        fields = (
            CANDIDATE_INSERT_FIELDS
            if item["action"] == "insert"
            else CANDIDATE_UPDATE_FIELDS
        )
        if actual is None or subset(actual, fields) != item["desired"]:
            raise MergeError(f"Candidate postflight failed for {key[0]} {key[1]}")


def fetch_summary(cursor) -> dict:
    return state_summary(
        fetch_papers(cursor),
        fetch_candidates(cursor),
        fetch_reference_counts(cursor),
    )


def execute_plan(local_conn, production_conn, plan: dict, *, commit: bool) -> dict:
    verify_local_state(local_conn, plan)
    cursor = production_conn.cursor()
    try:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        production_conn.begin()
        summary_before = fetch_summary(cursor)
        if summary_before != plan["production_summary_before"]:
            raise MergeError("Production summary changed after the plan was generated")
        verify_action_preconditions(cursor, plan)
        apply_actions(cursor, plan)
        verify_action_results(cursor, plan)
        summary_after = fetch_summary(cursor)
        if summary_after != plan["production_summary_projected"]:
            raise MergeError("Production postflight summary differs from the projection")
        if commit:
            production_conn.commit()
        else:
            production_conn.rollback()
            rolled_back_summary = fetch_summary(cursor)
            if rolled_back_summary != summary_before:
                raise MergeError("Production state did not return to its pre-test summary")
        result = {
            "mode": "commit" if commit else "rollback-test",
            "plan_sha256": plan["plan_sha256"],
            "paper_updates": len(plan["paper_updates"]),
            "candidate_inserts": sum(
                item["action"] == "insert" for item in plan["candidate_upserts"]
            ),
            "candidate_updates": sum(
                item["action"] == "update" for item in plan["candidate_upserts"]
            ),
            "summary_before": summary_before,
            "summary_after": summary_after,
        }
        if not commit:
            result["summary_after_rollback"] = rolled_back_summary
        return result
    except Exception:
        production_conn.rollback()
        raise
    finally:
        cursor.close()


def verify_persisted_summary(production_conn, expected: dict) -> dict:
    cursor = production_conn.cursor()
    try:
        production_conn.begin()
        actual = fetch_summary(cursor)
        if actual != expected:
            raise MergeError("Committed production state failed independent postflight")
        return actual
    finally:
        production_conn.rollback()
        cursor.close()


def print_plan_summary(plan: dict):
    inserts = sum(item["action"] == "insert" for item in plan["candidate_upserts"])
    updates = sum(item["action"] == "update" for item in plan["candidate_upserts"])
    before = plan["production_summary_before"]
    projected = plan["production_summary_projected"]
    print(f"Plan SHA-256: {plan['plan_sha256']}")
    print(f"Paper updates: {len(plan['paper_updates'])}")
    print(f"Candidate inserts: {inserts}")
    print(f"Candidate updates: {updates}")
    print(f"New production papers preserved: {plan['ignored_new_production_papers']}")
    print(
        "Projected: "
        f"papers={projected['papers']} "
        f"doi_papers={projected['papers_with_doi']} "
        f"notes={projected['papers_with_editor_note']} "
        f"pending={projected['candidate_statuses'].get('pending', 0)} "
        f"shared_dois={projected['shared_normalized_doi_values']}"
    )
    print(
        "Current:   "
        f"papers={before['papers']} "
        f"doi_papers={before['papers_with_doi']} "
        f"notes={before['papers_with_editor_note']} "
        f"pending={before['candidate_statuses'].get('pending', 0)} "
        f"shared_dois={before['shared_normalized_doi_values']}"
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True, help="JSON plan path")
    parser.add_argument(
        "--backup",
        type=Path,
        help="verified local copy of the fresh production backup (plan generation only)",
    )
    parser.add_argument(
        "--local-host",
        help="override DB_HOST from .env.local (use 'db' inside the Docker app container)",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--rollback-test",
        action="store_true",
        help="apply the saved plan transactionally, verify it, and roll it back",
    )
    modes.add_argument(
        "--apply",
        action="store_true",
        help="apply and commit the saved plan after all safeguards pass",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    local_env = load_env(LOCAL_ENV_PATH, "local")
    production_env = load_env(PRODUCTION_ENV_PATH, "production")
    if args.local_host:
        local_env["DB_HOST"] = args.local_host
    local_conn = None
    try:
        local_conn = local_connection(local_env)
        with production_connection(production_env) as prod_conn:
            if not args.rollback_test and not args.apply:
                if args.backup is None or not args.backup.is_file():
                    raise MergeError("Plan generation requires --backup with a verified dump")
                plan = generate_plan(local_conn, prod_conn, args.backup)
                args.plan.parent.mkdir(parents=True, exist_ok=True)
                args.plan.write_text(
                    json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                print_plan_summary(plan)
                print(f"Read-only plan written to {args.plan}")
                return 0

            plan = json.loads(args.plan.read_text(encoding="utf-8"))
            verify_plan(plan)
            verify_backup(plan)
            print_plan_summary(plan)
            result = execute_plan(local_conn, prod_conn, plan, commit=args.apply)
            if args.apply:
                result["persisted_summary"] = verify_persisted_summary(
                    prod_conn, plan["production_summary_projected"]
                )
            result_path = args.plan.with_suffix(
                ".applied.json" if args.apply else ".rollback.json"
            )
            result_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(
                "Committed production merge."
                if args.apply
                else "Rollback test passed; production changes were rolled back."
            )
            print(f"Result written to {result_path}")
            return 0
    except (MergeError, pymysql.Error, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        if local_conn is not None:
            local_conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
