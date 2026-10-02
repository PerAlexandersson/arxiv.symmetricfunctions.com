#!/usr/bin/env python3
"""Bounded, read-only keyword evidence scan over the local math.CO corpus.

The scanner joins paper-cache text artifacts to the web database by normalized
arXiv base ID.  It reuses ``extract_keywords`` tokenization and n-gram filters,
but never writes to MariaDB.  Results and resume state live in an explicit
output directory outside the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pymysql

from config import DB_CONFIG
from extract_keywords import extract_ngrams, is_useful, tokenize


SCHEMA_VERSION = 1
STRUCTURAL_SECTION_RE = re.compile(
    r"(?:^|\b)(references?|bibliograph(?:y|ies)|acknowledg(?:e)?ments?|contents?)(?:\b|$)",
    re.IGNORECASE,
)
PDF_REFERENCE_HEADING_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?\s+)?(?:references?|bibliograph(?:y|ies))\s*$",
    re.IGNORECASE,
)
PDF_CONTENTS_HEADING_RE = re.compile(
    r"^\s*(?:table\s+of\s+)?contents?\s*$", re.IGNORECASE
)
BOILERPLATE_RE = re.compile(
    r"(?:^arxiv:|^mathematics subject classification|^keywords?\s*[:.]|"
    r"^e-?mail\s*[:.]|^received\s|^accepted\s|^submitted\s|"
    r"copyright|all rights reserved|creative commons|"
    r"this (?:preprint|manuscript|version) (?:has been|was) submitted)",
    re.IGNORECASE,
)
STRUCTURED_PLACEHOLDER_RE = re.compile(
    r"\{\{(?:cite|formula|figure|table|ref):[^{}]+\}\}", re.IGNORECASE
)
NOVEL_PHRASE_NOISE_WORDS = {
    "acknowledgment", "acknowledgement", "apply", "bibliography", "cite",
    "corollary", "definition", "equation", "fig", "figure", "lemma",
    "proof", "proposition", "ref", "reference", "section", "see", "theorem",
}
VERSION_RE = re.compile(r"v\d+$", re.IGNORECASE)
MODERN_ID_RE = re.compile(r"\d{4}\.\d{4,5}$")
LEGACY_ID_RE = re.compile(r"[a-z-]+(?:\.[a-z-]+)?/\d{7}$", re.IGNORECASE)


@dataclass(frozen=True)
class Paragraph:
    text: str
    section: str | None = None
    page: int | None = None
    suppressed_reason: str | None = None


@dataclass(frozen=True)
class Artifact:
    arxiv_id: str
    versioned_arxiv_id: str | None
    corpus_name: str
    release_id: str
    source_kind: str
    relative_path: str
    size: int
    sha256: str
    format: str
    extraction_status: str
    quality_rank: int
    current_version: str | None


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def normalize_arxiv_base_id(value: str | None) -> str | None:
    """Normalize modern or legacy arXiv input to its unversioned base ID."""
    if not value:
        return None
    normalized = value.strip().strip("<>.,;()[]{}")
    normalized = re.sub(r"^https?://(?:www\.)?arxiv\.org/(?:abs|pdf|html)/", "", normalized, flags=re.I)
    normalized = re.sub(r"^arxiv:\s*", "", normalized, flags=re.I)
    normalized = re.sub(r"\.pdf$", "", normalized, flags=re.I)
    normalized = VERSION_RE.sub("", normalized)
    normalized = normalized.strip().lower()
    if MODERN_ID_RE.fullmatch(normalized) or LEGACY_ID_RE.fullmatch(normalized):
        return normalized
    return None


def arxiv_id_argument(value: str) -> str:
    normalized = normalize_arxiv_base_id(value)
    if normalized is None:
        raise argparse.ArgumentTypeError("must be a valid modern or legacy arXiv ID")
    return normalized


def source_kind(format_value: str, corpus_name: str) -> str | None:
    if format_value == "structured-json":
        return "structured-corpus"
    if format_value.startswith("text/plain") and corpus_name == "local-pdf-text":
        return "local-pdf-text"
    return None


def latest_version(arxiv_id: str, versions_json: str) -> str | None:
    try:
        rows = json.loads(versions_json)
    except (TypeError, json.JSONDecodeError):
        return None
    versions: list[tuple[int, str]] = []
    if isinstance(rows, list):
        for row in rows:
            value = row.get("version") if isinstance(row, dict) else row
            if not isinstance(value, str):
                continue
            match = re.fullmatch(r"v(\d+)", value, re.IGNORECASE)
            if match:
                versions.append((int(match.group(1)), f"{arxiv_id}v{int(match.group(1))}"))
    return max(versions)[1] if versions else None


def split_paragraphs(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return [part.strip() for part in re.split(r"\n[ \t]*\n+", text) if part.strip()]


def structured_paragraphs(payload: bytes) -> list[Paragraph]:
    row = json.loads(payload.decode("utf-8"))
    body = row.get("body_text") if isinstance(row, dict) else None
    if isinstance(body, str):
        entries: list[Any] = [body]
    elif isinstance(body, list):
        entries = body
    else:
        raise ValueError("structured corpus record has no body_text list or string")
    result: list[Paragraph] = []
    for entry in entries:
        section = None
        page = None
        if isinstance(entry, str):
            text = entry
        elif isinstance(entry, dict):
            text = entry.get("text")
            section_value = entry.get("section") or entry.get("section_title")
            section = section_value if isinstance(section_value, str) else None
            page_value = entry.get("page")
            page = page_value if isinstance(page_value, int) else None
        else:
            continue
        if not isinstance(text, str):
            continue
        reason = "structural-section" if section and STRUCTURAL_SECTION_RE.search(section) else None
        for chunk in split_paragraphs(text):
            cleaned = STRUCTURED_PLACEHOLDER_RE.sub(" ", chunk)
            if not cleaned.strip():
                continue
            chunk_reason = reason or ("boilerplate" if BOILERPLATE_RE.search(cleaned) else None)
            result.append(Paragraph(cleaned, section, page, chunk_reason))
    return result


def pdf_paragraphs(payload: bytes) -> list[Paragraph]:
    text = payload.decode("utf-8")
    result: list[Paragraph] = []
    references_active = False
    for page_number, page_text in enumerate(text.split("\f"), start=1):
        chunks = split_paragraphs(page_text)
        contents_page = any(
            PDF_CONTENTS_HEADING_RE.fullmatch(line.strip())
            for chunk in chunks for line in chunk.splitlines()
        )
        for chunk in chunks:
            lines = [line.strip() for line in chunk.splitlines() if line.strip()]
            if any(PDF_REFERENCE_HEADING_RE.fullmatch(line) for line in lines):
                references_active = True
            reason = None
            if references_active:
                reason = "references"
            elif contents_page or PDF_CONTENTS_HEADING_RE.fullmatch(chunk):
                reason = "contents"
            elif BOILERPLATE_RE.search(chunk):
                reason = "boilerplate"
            result.append(Paragraph(chunk, None, page_number, reason))
    return result


def evidence_text(text: str, limit: int = 600) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact if len(compact) <= limit else compact[: limit - 1].rstrip() + "…"


def indexed_phrase_matches(
    tokens: list[str],
    phrase_index: dict[tuple[str, ...], list[dict[str, Any]]],
    max_ngram: int,
) -> Iterable[tuple[list[dict[str, Any]], int]]:
    """Yield indexed keyword rows and occurrence count via bounded n-grams."""
    counts: Counter[tuple[str, ...]] = Counter()
    for size in range(1, max_ngram + 1):
        for index in range(len(tokens) - size + 1):
            phrase_tokens = tuple(tokens[index:index + size])
            if phrase_tokens in phrase_index:
                counts[phrase_tokens] += 1
    for phrase_tokens, count in counts.items():
        yield phrase_index[phrase_tokens], count


def metadata_ngram_set(tokens: list[str], max_ngram: int) -> set[str]:
    return {
        phrase
        for phrase in extract_ngrams(tokens, max_ngram)
        if is_useful(phrase)
    }


def analyze_paper(
    *,
    paper: dict[str, Any],
    artifact: Artifact,
    payload: bytes,
    phrase_index: dict[tuple[str, ...], list[dict[str, Any]]],
    known_phrases: set[str],
    excluded_candidates: set[str],
    max_ngram: int,
    candidate_min_occurrences: int,
    max_candidate_phrases: int,
) -> dict[str, Any]:
    paragraphs = (
        structured_paragraphs(payload)
        if artifact.source_kind == "structured-corpus"
        else pdf_paragraphs(payload)
    )
    metadata_tokens = tokenize(f"{paper.get('title') or ''} {paper.get('abstract') or ''}")
    metadata_ngrams = metadata_ngram_set(metadata_tokens, max_ngram)
    metadata_keyword_ids: set[int] = set()
    for entries, _ in indexed_phrase_matches(metadata_tokens, phrase_index, max_ngram):
        metadata_keyword_ids.update(entry["keyword_id"] for entry in entries)

    body_keyword: dict[int, dict[str, Any]] = {}
    novel_counts: Counter[str] = Counter()
    novel_evidence: dict[str, dict[str, Any]] = {}
    suppression_counts: Counter[str] = Counter()
    analyzed_paragraphs = 0
    analyzed_tokens = 0
    for paragraph_index, paragraph in enumerate(paragraphs):
        if paragraph.suppressed_reason:
            suppression_counts[paragraph.suppressed_reason] += 1
            continue
        tokens = tokenize(paragraph.text)
        if not tokens:
            continue
        analyzed_paragraphs += 1
        analyzed_tokens += len(tokens)
        for entries, occurrences in indexed_phrase_matches(tokens, phrase_index, max_ngram):
            for entry in entries:
                item = body_keyword.setdefault(
                    entry["keyword_id"],
                    {
                        "keyword_id": entry["keyword_id"],
                        "canonical_phrase": entry["canonical_phrase"],
                        "matched_phrases": set(),
                        "occurrences": 0,
                        "evidence": None,
                    },
                )
                item["matched_phrases"].add(entry["matched_phrase"])
                item["occurrences"] += occurrences
                if item["evidence"] is None:
                    item["evidence"] = {
                        "paragraph": paragraph_index,
                        "section": paragraph.section,
                        "page": paragraph.page,
                        "passage": evidence_text(paragraph.text),
                    }
        for phrase in extract_ngrams(tokens, max_ngram):
            word_count = len(phrase.split())
            if word_count < 2 or not is_useful(phrase):
                continue
            words = phrase.split()
            if any(word in NOVEL_PHRASE_NOISE_WORDS for word in words):
                continue
            if any(len(word.replace("-", "")) < 3 for word in words):
                continue
            if len(set(words)) == 1:
                continue
            if phrase in known_phrases or phrase in excluded_candidates or phrase in metadata_ngrams:
                continue
            novel_counts[phrase] += 1
            novel_evidence.setdefault(
                phrase,
                {
                    "paragraph": paragraph_index,
                    "section": paragraph.section,
                    "page": paragraph.page,
                    "passage": evidence_text(paragraph.text),
                },
            )

    existing_tags = {
        int(item["keyword_id"]): item["source"] for item in paper.get("existing_tags", [])
    }
    additional_keywords = []
    all_body_keywords = []
    for keyword_id, item in sorted(body_keyword.items(), key=lambda pair: pair[1]["canonical_phrase"]):
        record = {
            **item,
            "matched_phrases": sorted(item["matched_phrases"]),
            "metadata_match": keyword_id in metadata_keyword_ids,
            "existing_tag_source": existing_tags.get(keyword_id),
            "provenance": "body-full-text",
        }
        all_body_keywords.append(record)
        if keyword_id not in metadata_keyword_ids:
            additional_keywords.append(record)

    novel = [
        {
            "phrase": phrase,
            "occurrences": count,
            "word_count": len(phrase.split()),
            "provenance": "body-full-text",
            "evidence": novel_evidence[phrase],
        }
        for phrase, count in novel_counts.items()
        if count >= candidate_min_occurrences
    ]
    novel.sort(key=lambda item: (-item["occurrences"], -item["word_count"], item["phrase"]))
    novel = novel[:max_candidate_phrases]

    metadata_sha = paper_metadata_sha256(paper)
    return {
        "schema_version": SCHEMA_VERSION,
        "arxiv_base_id": artifact.arxiv_id,
        "versioned_arxiv_id": artifact.versioned_arxiv_id,
        "title": paper.get("title") or "",
        "join": {"key": "normalized-arxiv-base-id", "database_paper_id": paper["id"]},
        "provenance": {
            "metadata": "database-title-abstract",
            "full_text": {
                "source_kind": artifact.source_kind,
                "corpus_name": artifact.corpus_name,
                "release_id": artifact.release_id,
                "path": artifact.relative_path,
                "sha256": artifact.sha256,
                "version_status": (
                    "unknown" if not artifact.current_version or not artifact.versioned_arxiv_id
                    else "current" if artifact.current_version == artifact.versioned_arxiv_id
                    else "stale"
                ),
            },
        },
        "checksums": {"metadata_sha256": metadata_sha, "full_text_sha256": artifact.sha256},
        "counts": {
            "paragraphs_total": len(paragraphs),
            "paragraphs_analyzed": analyzed_paragraphs,
            "tokens_analyzed": analyzed_tokens,
            "suppressed_paragraphs": sum(suppression_counts.values()),
            "suppression_reasons": dict(sorted(suppression_counts.items())),
        },
        "metadata_keyword_ids": sorted(metadata_keyword_ids),
        "existing_database_tags": paper.get("existing_tags", []),
        "body_keyword_evidence": all_body_keywords,
        "additional_keyword_candidates": additional_keywords,
        "novel_body_phrase_candidates": novel,
        "notice": "Dry-run evidence only; no keyword or paper tag was inserted.",
    }


def connect_database(host_override: str | None):
    config = dict(DB_CONFIG)
    if host_override:
        config["host"] = host_override
    config["cursorclass"] = pymysql.cursors.DictCursor
    config["autocommit"] = True
    return pymysql.connect(**config)


def paper_metadata_sha256(paper: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json({
        "title": paper.get("title") or "",
        "abstract": paper.get("abstract") or "",
        "existing_tags": paper.get("existing_tags", []),
    }))


def load_database_context(conn) -> tuple[set[str], dict[int, str], dict[tuple[str, ...], list[dict[str, Any]]], set[str], str]:
    with conn.cursor() as cursor:
        cursor.execute("SELECT arxiv_base_id FROM papers")
        database_ids = {
            normalized for row in cursor.fetchall()
            if (normalized := normalize_arxiv_base_id(row["arxiv_base_id"]))
        }
        cursor.execute("SELECT id, phrase FROM keywords WHERE active=1 ORDER BY id")
        keywords = {int(row["id"]): row["phrase"] for row in cursor.fetchall()}
        cursor.execute(
            "SELECT ka.keyword_id, ka.alias FROM keyword_aliases ka "
            "JOIN keywords k ON k.id=ka.keyword_id WHERE k.active=1 "
            "ORDER BY ka.keyword_id, ka.alias"
        )
        aliases = cursor.fetchall()
        cursor.execute("SELECT phrase FROM ignored_candidates UNION SELECT phrase FROM math_words")
        excluded = {
            " ".join(tokenize(row["phrase"]))
            for row in cursor.fetchall()
            if tokenize(row["phrase"])
        }
    phrase_rows = [
        {"keyword_id": keyword_id, "canonical_phrase": phrase, "matched_phrase": phrase}
        for keyword_id, phrase in keywords.items()
    ] + [
        {
            "keyword_id": int(row["keyword_id"]),
            "canonical_phrase": keywords[int(row["keyword_id"])],
            "matched_phrase": row["alias"],
        }
        for row in aliases
    ]
    phrase_index: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in phrase_rows:
        phrase_tokens = tuple(tokenize(row["matched_phrase"]))
        if phrase_tokens:
            phrase_index[phrase_tokens].append(row)
    snapshot = {
        "keywords": sorted((keyword_id, phrase) for keyword_id, phrase in keywords.items()),
        "aliases": [(int(row["keyword_id"]), row["alias"]) for row in aliases],
        "excluded": sorted(excluded),
    }
    return database_ids, keywords, phrase_index, excluded, sha256_bytes(canonical_json(snapshot))


def load_paper(conn, arxiv_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT id, arxiv_base_id, title, abstract FROM papers WHERE arxiv_base_id=%s",
            (arxiv_id,),
        )
        paper = cursor.fetchone()
        if not paper:
            return None
        cursor.execute(
            "SELECT keyword_id, source FROM paper_keywords WHERE paper_id=%s ORDER BY keyword_id",
            (paper["id"],),
        )
        paper["existing_tags"] = cursor.fetchall()
        return paper


def load_inventory(root: Path) -> tuple[list[Artifact], set[str]]:
    uri = (root / "archive.sqlite").resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        metadata_ids = {
            normalized
            for row in conn.execute("SELECT arxiv_id FROM metadata")
            if (normalized := normalize_arxiv_base_id(row[0]))
        }
        rows = conn.execute(
            """SELECT t.arxiv_id,t.versioned_arxiv_id,t.corpus_name,t.release_id,
                      t.path,t.size,t.sha256,t.format,t.extraction_status,t.quality_rank,
                      m.versions_json
               FROM text_artifacts t JOIN metadata m ON m.arxiv_id=t.arxiv_id
               WHERE t.size>0
               ORDER BY t.arxiv_id,
                        CASE WHEN t.format='structured-json' THEN 0 ELSE 1 END,
                        t.quality_rank DESC,t.corpus_name,t.release_id DESC"""
        ).fetchall()
    finally:
        conn.close()
    artifacts: list[Artifact] = []
    seen: set[str] = set()
    for row in rows:
        arxiv_id = normalize_arxiv_base_id(row["arxiv_id"])
        kind = source_kind(row["format"], row["corpus_name"])
        if not arxiv_id or not kind or arxiv_id in seen:
            continue
        seen.add(arxiv_id)
        artifacts.append(Artifact(
            arxiv_id=arxiv_id,
            versioned_arxiv_id=row["versioned_arxiv_id"],
            corpus_name=row["corpus_name"], release_id=row["release_id"],
            source_kind=kind, relative_path=row["path"], size=int(row["size"]),
            sha256=row["sha256"], format=row["format"],
            extraction_status=row["extraction_status"], quality_rank=int(row["quality_rank"]),
            current_version=latest_version(arxiv_id, row["versions_json"]),
        ))
    return artifacts, metadata_ids


def select_stratified(artifacts: list[Artifact], count: int) -> list[Artifact]:
    groups: dict[str, list[Artifact]] = defaultdict(list)
    for artifact in artifacts:
        groups[artifact.source_kind].append(artifact)
    selected: list[Artifact] = []
    kinds = sorted(groups)
    quotas = {kind: count // len(kinds) for kind in kinds}
    for kind in kinds[: count % len(kinds)]:
        quotas[kind] += 1
    for kind in kinds:
        group = groups[kind]
        quota = min(quotas[kind], len(group))
        if quota == 1:
            indexes = [len(group) // 2]
        elif quota > 1:
            indexes = [round(i * (len(group) - 1) / (quota - 1)) for i in range(quota)]
        else:
            indexes = []
        selected.extend(group[index] for index in indexes)
    return sorted(selected, key=lambda item: item.arxiv_id)


def open_state(path: Path, config: dict[str, Any]) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
           CREATE TABLE IF NOT EXISTS processed (
             arxiv_id TEXT PRIMARY KEY,
             source_sha256 TEXT NOT NULL,
             metadata_sha256 TEXT NOT NULL,
             source_bytes INTEGER NOT NULL,
             source_kind TEXT NOT NULL,
             result_json TEXT NOT NULL
           );"""
    )
    config_sha = sha256_bytes(canonical_json(config))
    existing = conn.execute("SELECT value FROM meta WHERE key='config_sha256'").fetchone()
    if existing and existing["value"] != config_sha:
        conn.close()
        raise ValueError("resume state has a different keyword/config snapshot; use a new output directory")
    conn.execute("INSERT OR IGNORE INTO meta VALUES('config_sha256',?)", (config_sha,))
    conn.execute("INSERT OR IGNORE INTO meta VALUES('config_json',?)", (canonical_json(config).decode(),))
    conn.commit()
    return conn


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def write_outputs(state: sqlite3.Connection, output_dir: Path, summary: dict[str, Any]) -> None:
    papers_path = output_dir / "papers.jsonl"
    temporary = papers_path.with_name(f".{papers_path.name}.{os.getpid()}.tmp")
    keyword_counts: Counter[str] = Counter()
    phrase_papers: Counter[str] = Counter()
    phrase_occurrences_total: Counter[str] = Counter()
    phrase_examples: dict[str, dict[str, Any]] = {}
    with temporary.open("wb") as handle:
        for row in state.execute("SELECT result_json FROM processed ORDER BY arxiv_id"):
            result = json.loads(row["result_json"])
            handle.write(canonical_json(result) + b"\n")
            for item in result["additional_keyword_candidates"]:
                keyword_counts[item["canonical_phrase"]] += 1
            for item in result["novel_body_phrase_candidates"]:
                phrase = item["phrase"]
                phrase_papers[phrase] += 1
                phrase_occurrences_total[phrase] += item["occurrences"]
                phrase_examples.setdefault(phrase, {
                    "arxiv_base_id": result["arxiv_base_id"], **item["evidence"]
                })
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, papers_path)
    aggregate = {
        "schema_version": SCHEMA_VERSION,
        "additional_existing_keywords": [
            {"phrase": phrase, "paper_count": count}
            for phrase, count in keyword_counts.most_common()
        ],
        "novel_body_phrases": [
            {
                "phrase": phrase,
                "paper_count": count,
                "occurrences": phrase_occurrences_total[phrase],
                "example": phrase_examples[phrase],
            }
            for phrase, count in sorted(phrase_papers.items(), key=lambda item: (-item[1], -phrase_occurrences_total[item[0]], item[0]))
        ],
    }
    summary["state_total_papers"] = state.execute("SELECT COUNT(*) FROM processed").fetchone()[0]
    summary["outputs"] = {
        "papers": str(papers_path),
        "aggregate": str(output_dir / "aggregate.json"),
        "summary": str(output_dir / "summary.json"),
    }
    atomic_write(output_dir / "aggregate.json", canonical_json(aggregate) + b"\n")
    atomic_write(output_dir / "summary.json", canonical_json(summary) + b"\n")


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    root = args.corpus_root.resolve()
    output_dir = args.output_dir.resolve()
    project_root = Path(__file__).resolve().parents[1]
    try:
        output_dir.relative_to(project_root)
    except ValueError:
        pass
    else:
        raise ValueError("output directory must be outside the repository")
    artifacts, archive_metadata_ids = load_inventory(root)
    database = connect_database(args.db_host)
    try:
        database_ids, keywords, phrase_index, excluded, keyword_snapshot = load_database_context(database)
        artifact_ids = {item.arxiv_id for item in artifacts}
        by_source = Counter(item.source_kind for item in artifacts)
        version_status = Counter(
            "unknown" if not item.current_version or not item.versioned_arxiv_id
            else "current" if item.current_version == item.versioned_arxiv_id
            else "stale"
            for item in artifacts
        )
        overlap = [item for item in artifacts if item.arxiv_id in database_ids]
        coverage = {
            "database_papers": len(database_ids),
            "archive_metadata_papers": len(archive_metadata_ids),
            "database_archive_metadata_overlap": len(database_ids & archive_metadata_ids),
            "database_papers_not_in_archive_metadata": len(database_ids - archive_metadata_ids),
            "archive_metadata_papers_not_in_database": len(archive_metadata_ids - database_ids),
            "text_artifact_papers": len(artifact_ids),
            "text_artifacts_joined_to_database": len(overlap),
            "text_artifacts_not_in_database": len(artifact_ids - database_ids),
            "database_papers_without_text": len(database_ids - artifact_ids),
            "database_text_coverage_percent": round(100 * len(database_ids & artifact_ids) / len(database_ids), 3),
            "text_by_source": dict(sorted(by_source.items())),
            "text_version_status": dict(sorted(version_status.items())),
        }
        filtered = [
            item for item in overlap
            if args.source_kind == "all" or item.source_kind == args.source_kind
        ]
        candidates = (
            select_stratified(filtered, args.max_papers)
            if args.selection == "stratified" else filtered
        )
        config = {
            "schema_version": SCHEMA_VERSION,
            "keyword_snapshot_sha256": keyword_snapshot,
            "max_ngram": args.max_ngram,
            "candidate_min_occurrences": args.candidate_min_occurrences,
            "max_candidate_phrases": args.max_candidate_phrases,
            "suppression": {
                "structural_section": STRUCTURAL_SECTION_RE.pattern,
                "boilerplate": BOILERPLATE_RE.pattern,
                "structured_placeholders": STRUCTURED_PLACEHOLDER_RE.pattern,
            },
        }
        state = open_state(output_dir / "state.sqlite", config)
        processed = 0
        reused = 0
        input_bytes = 0
        stop_reason = "selection-complete" if args.selection == "stratified" else "inventory-complete"
        next_arxiv_id = None
        known_phrases = {" ".join(tokens) for tokens in phrase_index}
        try:
            for artifact in candidates:
                if args.selection == "sequential" and args.start_after and artifact.arxiv_id <= args.start_after:
                    continue
                paper = load_paper(database, artifact.arxiv_id)
                if paper is None:
                    continue
                current_metadata_sha = paper_metadata_sha256(paper)
                existing = state.execute(
                    "SELECT source_sha256,metadata_sha256 FROM processed WHERE arxiv_id=?",
                    (artifact.arxiv_id,),
                ).fetchone()
                if (
                    existing
                    and existing["source_sha256"] == artifact.sha256
                    and existing["metadata_sha256"] == current_metadata_sha
                ):
                    reused += 1
                    continue
                if processed >= args.max_papers:
                    stop_reason = "paper-limit"
                    next_arxiv_id = artifact.arxiv_id
                    break
                if input_bytes + artifact.size > args.max_input_mib * 1024 * 1024:
                    stop_reason = "input-byte-limit"
                    next_arxiv_id = artifact.arxiv_id
                    break
                path = (root / artifact.relative_path).resolve()
                try:
                    path.relative_to(root)
                except ValueError as exc:
                    raise ValueError(f"artifact escapes corpus root: {artifact.relative_path}") from exc
                payload = path.read_bytes()
                if len(payload) != artifact.size or sha256_bytes(payload) != artifact.sha256:
                    raise ValueError(f"artifact integrity mismatch: {artifact.relative_path}")
                result = analyze_paper(
                    paper=paper, artifact=artifact, payload=payload,
                    phrase_index=phrase_index, known_phrases=known_phrases,
                    excluded_candidates=excluded, max_ngram=args.max_ngram,
                    candidate_min_occurrences=args.candidate_min_occurrences,
                    max_candidate_phrases=args.max_candidate_phrases,
                )
                state.execute(
                    """INSERT INTO processed(arxiv_id,source_sha256,metadata_sha256,source_bytes,source_kind,result_json)
                       VALUES(?,?,?,?,?,?)
                       ON CONFLICT(arxiv_id) DO UPDATE SET
                         source_sha256=excluded.source_sha256,
                         metadata_sha256=excluded.metadata_sha256,
                         source_bytes=excluded.source_bytes,
                         source_kind=excluded.source_kind,
                         result_json=excluded.result_json""",
                    (artifact.arxiv_id, artifact.sha256, result["checksums"]["metadata_sha256"],
                     artifact.size, artifact.source_kind, canonical_json(result).decode()),
                )
                state.commit()
                processed += 1
                input_bytes += artifact.size
            elapsed = time.monotonic() - started
            summary = {
                "schema_version": SCHEMA_VERSION,
                "dry_run": True,
                "database_writes": 0,
                "coverage": coverage,
                "run": {
                    "selection": args.selection,
                    "source_kind": args.source_kind,
                    "max_papers": args.max_papers,
                    "max_input_bytes": args.max_input_mib * 1024 * 1024,
                    "processed_papers": processed,
                    "reused_checkpoints": reused,
                    "input_bytes": input_bytes,
                    "elapsed_seconds": round(elapsed, 3),
                    "papers_per_second": round(processed / elapsed, 3) if elapsed and processed else 0,
                    "mib_per_second": round(input_bytes / 1024 / 1024 / elapsed, 3) if elapsed and input_bytes else 0,
                    "stop_reason": stop_reason,
                    "next_arxiv_id": next_arxiv_id,
                },
                "configuration": config,
            }
            write_outputs(state, output_dir, summary)
            return summary
        finally:
            state.close()
    finally:
        database.close()


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-root", type=Path, default=Path("/papers/math-co"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--db-host", help="override DB_HOST (use 'db' inside Docker)")
    parser.add_argument("--max-papers", type=int, required=True)
    parser.add_argument("--max-input-mib", type=int, required=True)
    parser.add_argument("--max-ngram", type=int, default=4, choices=range(2, 5))
    parser.add_argument("--candidate-min-occurrences", type=int, default=2)
    parser.add_argument("--max-candidate-phrases", type=int, default=30)
    parser.add_argument("--source-kind", choices=("all", "structured-corpus", "local-pdf-text"), default="all")
    parser.add_argument("--selection", choices=("sequential", "stratified"), default="sequential")
    parser.add_argument("--start-after", type=arxiv_id_argument)
    args = parser.parse_args(argv)
    for name in ("max_papers", "max_input_mib", "candidate_min_occurrences", "max_candidate_phrases"):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    return args


def main(argv: Iterable[str] | None = None) -> int:
    try:
        summary = run(parse_args(argv))
    except (OSError, ValueError, pymysql.MySQLError, sqlite3.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
