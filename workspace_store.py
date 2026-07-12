"""
Local workspace persistence for SLR Assistant.

Phase 1 deliberately keeps this module small and standard-library only:
folder lifecycle, SQLite schema/migrations, reference-import metadata, PDF
metadata, and workspace audit events.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator

try:
    from version import VERSION
except Exception:  # pragma: no cover - defensive for standalone use
    VERSION = "unknown"


SCHEMA_VERSION = 4
DATABASE_NAME = "workspace.sqlite3"
WORKSPACE_JSON = "workspace.json"
WORKSPACE_SUBDIRS = ("imports", "pdfs", "exports", "cache", "audit")
WORKSPACE_PDF_TOKEN = "workspace:pdfs"
AUTOMATION_RUN_STATUS_RUNNING = "running"
AUTOMATION_RUN_STATUS_INTERRUPTED = "interrupted"

# Default on-disk location for workspaces created through the guided flow.
# Researchers should not have to paste an absolute path to start a project.
DEFAULT_WORKSPACES_DIR_NAME = "SLR Assistant Workspaces"
REVIEW_TYPE_SYSTEMATIC = "systematic_review"
REVIEW_TYPE_SCOPING = "scoping_review"
REVIEW_TYPE_OTHER = "other"
REVIEW_TYPES = (REVIEW_TYPE_SYSTEMATIC, REVIEW_TYPE_SCOPING, REVIEW_TYPE_OTHER)

# Optional review metadata stored in workspace.json (not a database schema
# change). These describe the project for display only; they do not alter
# screening, deduplication, or export count definitions.
REVIEW_METADATA_KEYS = ("review_title", "review_type", "review_question", "reviewer_name")

DEDUP_STATUS_UNIQUE = "unique"
DEDUP_STATUS_DUPLICATE = "duplicate"
DEDUP_METHOD_DOI = "doi"
DEDUP_METHOD_FUZZY_TITLE = "fuzzy_title"
DEDUP_METHOD_OTHER = "other"

DEFAULT_REVIEWER_ID = "default-local-reviewer"
DEFAULT_EXCLUSION_REASONS = (
    ("wrong_population", "Wrong population", "Population does not match the review criteria."),
    ("wrong_intervention", "Wrong intervention or exposure", "Intervention or exposure is outside scope."),
    ("wrong_comparator", "Wrong comparator", "Comparator does not match the review criteria."),
    ("wrong_outcome", "Wrong outcome", "Outcomes do not match the review criteria."),
    ("wrong_study_design", "Wrong study design", "Study design or publication type is outside scope."),
    ("not_empirical", "Not empirical research", "Record is not an empirical research study."),
    ("outside_scope", "Outside date, language, or topic scope", "Record is outside declared review limits."),
    ("full_text_unavailable", "Full text unavailable", "Full text could not be obtained."),
    ("duplicate", "Duplicate record", "Record duplicates another imported record."),
)

SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "credential",
    "prompt",
    "full_text",
    "paper_text",
    "document_text",
    "extracted_text",
)
SAFE_HASH_KEY_SUFFIXES = ("_hash",)
SAFE_METADATA_KEYS = {"cache_key"}

REVIEW_STAGE_TITLE_ABSTRACT = "title_abstract"
REVIEW_STAGE_FULL_TEXT = "full_text"
REVIEW_STAGES = {REVIEW_STAGE_TITLE_ABSTRACT, REVIEW_STAGE_FULL_TEXT}

REVIEW_STATUS_PENDING = "pending"
REVIEW_STATUS_SUGGESTED = "suggested"
REVIEW_STATUS_INCLUDED = "included"
REVIEW_STATUS_EXCLUDED = "excluded"
REVIEW_STATUS_MAYBE = "maybe"
REVIEW_STATUS_FAILED = "failed"
REVIEW_STATUSES = {
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_SUGGESTED,
    REVIEW_STATUS_INCLUDED,
    REVIEW_STATUS_EXCLUDED,
    REVIEW_STATUS_MAYBE,
    REVIEW_STATUS_FAILED,
}

DECISION_INCLUDE = "include"
DECISION_EXCLUDE = "exclude"
DECISION_MAYBE = "maybe"
DECISION_FLAG = "flag"
DECISION_FAILED = "failed"
DECISIONS = {
    DECISION_INCLUDE,
    DECISION_EXCLUDE,
    DECISION_MAYBE,
    DECISION_FLAG,
    DECISION_FAILED,
}

ACTOR_AI = "ai"
ACTOR_HUMAN = "human"
ACTOR_SYSTEM = "system"
ACTOR_TYPES = {ACTOR_AI, ACTOR_HUMAN, ACTOR_SYSTEM}

RECORD_ORIGIN_IMPORTED_REFERENCE = "imported_reference"
RECORD_ORIGIN_PDF_ONLY = "pdf_only"
RECORD_ORIGIN_MANUAL = "manual"
RECORD_ORIGINS = {
    RECORD_ORIGIN_IMPORTED_REFERENCE,
    RECORD_ORIGIN_PDF_ONLY,
    RECORD_ORIGIN_MANUAL,
}


class WorkspaceError(ValueError):
    """Base class for workspace validation and persistence errors."""


class UnsafeWorkspacePath(WorkspaceError):
    """Raised when a workspace path is unsafe."""


class WorkspaceNotFound(WorkspaceError):
    """Raised when a path is not an existing workspace."""


@dataclass(frozen=True)
class WorkspaceHandle:
    root: Path
    workspace_id: str
    name: str
    schema_version: int
    review_title: str = ""
    review_type: str = ""
    review_question: str = ""
    reviewer_name: str = ""

    @property
    def db_path(self) -> Path:
        return self.root / DATABASE_NAME

    def public_summary(self) -> dict[str, Any]:
        summary = get_workspace_summary(self.root)
        summary.update({
            "workspace_id": self.workspace_id,
            "name": self.name,
            "schema_version": self.schema_version,
            "pdf_folder": WORKSPACE_PDF_TOKEN,
            "review_title": self.review_title or summary.get("review_title", ""),
            "review_type": self.review_type or summary.get("review_type", ""),
            "review_question": self.review_question or summary.get("review_question", ""),
            "reviewer_name": self.reviewer_name or summary.get("reviewer_name", ""),
        })
        return summary


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def create_workspace(
    root: str | Path | None = None,
    name: str | None = None,
    *,
    review_title: str | None = None,
    review_type: str | None = None,
    review_question: str | None = None,
    reviewer_name: str | None = None,
) -> WorkspaceHandle:
    review_title_text = _bounded_text(review_title)
    review_type_value = _normalize_review_type(review_type)
    review_question_text = _bounded_text(review_question)
    reviewer_name_text = _bounded_text(reviewer_name)

    if not root or str(root).strip() == "":
        root = default_workspace_path(review_title=review_title_text, name=name)

    workspace_root = validate_workspace_root(root)
    if workspace_root.exists():
        _reject_unrelated_existing_contents(workspace_root)

    workspace_root.mkdir(parents=True, exist_ok=True)
    _ensure_subfolders(workspace_root)

    metadata_path = workspace_root / WORKSPACE_JSON
    if metadata_path.exists():
        metadata = _load_workspace_json(workspace_root)
        if name:
            metadata["name"] = name
    else:
        now = utc_now()
        metadata = {
            "workspace_id": uuid.uuid4().hex,
            "name": name or workspace_root.name,
            "schema_version": SCHEMA_VERSION,
            "app_version": VERSION,
            "created_at": now,
            "updated_at": now,
            "database": DATABASE_NAME,
            "folders": {folder: folder for folder in WORKSPACE_SUBDIRS},
        }
    if review_title_text:
        metadata["review_title"] = review_title_text
    if review_type_value:
        metadata["review_type"] = review_type_value
    if review_question_text:
        metadata["review_question"] = review_question_text
    if reviewer_name_text:
        metadata["reviewer_name"] = reviewer_name_text
    _write_workspace_json(workspace_root, metadata)

    migrate(workspace_root)
    return open_workspace(workspace_root)


def open_workspace(root: str | Path) -> WorkspaceHandle:
    workspace_root = validate_workspace_root(root)
    if not workspace_root.exists() or not workspace_root.is_dir():
        raise WorkspaceNotFound("Workspace folder not found")
    if not (workspace_root / WORKSPACE_JSON).is_file():
        raise WorkspaceNotFound("workspace.json not found")
    if not (workspace_root / DATABASE_NAME).is_file():
        raise WorkspaceNotFound("workspace.sqlite3 not found")

    migrate(workspace_root)
    metadata = _load_workspace_json(workspace_root)
    _ensure_subfolders(workspace_root)

    workspace_id = str(metadata.get("workspace_id") or get_meta(workspace_root, "workspace_id") or "")
    name = str(metadata.get("name") or get_meta(workspace_root, "name") or workspace_root.name)
    schema_version = int(metadata.get("schema_version") or SCHEMA_VERSION)
    review_title = str(metadata.get("review_title") or "")
    review_type = _normalize_review_type(metadata.get("review_type"))
    review_question = str(metadata.get("review_question") or "")
    reviewer_name = str(metadata.get("reviewer_name") or "")

    if not workspace_id:
        raise WorkspaceError("Workspace metadata is missing workspace_id")
    return WorkspaceHandle(
        workspace_root,
        workspace_id,
        name,
        schema_version,
        review_title=review_title,
        review_type=review_type,
        review_question=review_question,
        reviewer_name=reviewer_name,
    )


def migrate(root: str | Path) -> None:
    workspace_root = validate_workspace_root(root)
    workspace_root.mkdir(parents=True, exist_ok=True)
    _ensure_subfolders(workspace_root)

    metadata = _load_workspace_json(workspace_root) if (workspace_root / WORKSPACE_JSON).exists() else {}
    if not metadata:
        now = utc_now()
        metadata = {
            "workspace_id": uuid.uuid4().hex,
            "name": workspace_root.name,
            "schema_version": SCHEMA_VERSION,
            "app_version": VERSION,
            "created_at": now,
            "updated_at": now,
            "database": DATABASE_NAME,
            "folders": {folder: folder for folder in WORKSPACE_SUBDIRS},
        }
        _write_workspace_json(workspace_root, metadata)

    with workspace_connection(workspace_root) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        for statement in _schema_statements():
            conn.execute(statement)
        _apply_record_origin_migration(conn)
        _apply_dedup_migration(conn)
        _apply_review_queue_migrations(conn)
        _seed_workspace_meta(conn, metadata)
        _seed_default_reviewer(conn)
        _seed_default_exclusion_reasons(conn)
        conn.execute(
            """
            INSERT OR IGNORE INTO schema_migrations(version, name, applied_at)
            VALUES (?, ?, ?)
            """,
            (1, "phase_1_workspace_schema", utc_now()),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO schema_migrations(version, name, applied_at)
            VALUES (?, ?, ?)
            """,
            (2, "phase_2_review_queue_schema", utc_now()),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO schema_migrations(version, name, applied_at)
            VALUES (?, ?, ?)
            """,
            (3, "phase_3_record_origin_schema", utc_now()),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO schema_migrations(version, name, applied_at)
            VALUES (?, ?, ?)
            """,
            (4, "phase_4_dedup_state_schema", utc_now()),
        )

    metadata["schema_version"] = SCHEMA_VERSION
    metadata["updated_at"] = utc_now()
    _write_workspace_json(workspace_root, metadata)


def connect(root: str | Path) -> sqlite3.Connection:
    workspace_root = validate_workspace_root(root)
    conn = sqlite3.connect(workspace_root / DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def workspace_connection(root: str | Path) -> Iterator[sqlite3.Connection]:
    conn = connect(root)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def default_workspaces_root() -> Path:
    """Return the safe default directory used to store guided-flow workspaces."""
    return Path.home() / DEFAULT_WORKSPACES_DIR_NAME


def default_workspace_path(*, review_title: str | None = None, name: str | None = None) -> Path:
    """Build a safe, non-colliding workspace folder under the default location.

    The researcher supplies a review title and the app picks a folder name. They
    never have to type an absolute path in the normal flow.
    """
    raw = _bounded_text(review_title) or _bounded_text(name) or ""
    if not raw:
        raise WorkspaceError(
            "A review title is required to create a workspace in the default location"
        )
    slug = _slugify(raw) or "workspace"
    base = default_workspaces_root()
    candidate = base / slug
    counter = 2
    while candidate.exists():
        if not candidate.is_dir():
            raise WorkspaceError(
                "Default workspace location already contains a file with this name"
            )
        candidate = base / f"{slug}-{counter}"
        counter += 1
        if counter > 9999:
            raise WorkspaceError("Could not find a free default workspace folder name")
    return candidate


def _normalize_review_type(value: Any) -> str:
    text = _bounded_text(value)
    if not text:
        return ""
    lowered = text.lower()
    if lowered in REVIEW_TYPES:
        return lowered
    return ""


def _slugify(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._ -]+", "_", value or "").strip()
    text = re.sub(r"[ ]+", "-", text)
    text = re.sub(r"[_]+", "_", text).strip("-_")
    if not text:
        return ""
    return text[:80]


def validate_workspace_root(root: str | Path) -> Path:
    if root is None or str(root).strip() == "":
        raise UnsafeWorkspacePath("Workspace path is required")

    workspace_root = Path(root).expanduser().resolve()

    if workspace_root == workspace_root.parent:
        raise UnsafeWorkspacePath("Filesystem root cannot be used as a workspace")
    if workspace_root.anchor:
        try:
            if workspace_root == Path(workspace_root.anchor).resolve():
                raise UnsafeWorkspacePath("Drive root cannot be used as a workspace")
        except OSError:
            raise UnsafeWorkspacePath("Drive root cannot be used as a workspace")
    try:
        if workspace_root == Path.home().resolve():
            raise UnsafeWorkspacePath("Home directory cannot be used as a workspace")
    except OSError:
        pass
    if workspace_root.exists() and not workspace_root.is_dir():
        raise UnsafeWorkspacePath("Workspace path must be a folder")
    return workspace_root


def resolve_workspace_relative_path(
    root: str | Path,
    relative_path: str,
    *,
    subdir: str | None = None,
    must_exist: bool = False,
    require_file: bool = False,
) -> Path:
    workspace_root = validate_workspace_root(root)
    clean_relative = _validate_relative_path(relative_path)
    target = (workspace_root / clean_relative).resolve()
    base = (workspace_root / subdir).resolve() if subdir else workspace_root.resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise UnsafeWorkspacePath("Path is outside the workspace") from exc
    if must_exist and not target.exists():
        raise FileNotFoundError("Workspace path not found")
    if require_file and target.exists() and not target.is_file():
        raise UnsafeWorkspacePath("Workspace path is not a file")
    return target


def persist_reference_import(
    root: str | Path,
    source_path: str | Path,
    records: list[dict[str, Any]],
    *,
    original_filename: str | None = None,
) -> dict[str, Any]:
    workspace_root = validate_workspace_root(root)
    source = Path(source_path).resolve()
    if not source.is_file():
        raise FileNotFoundError("Import file not found")

    copied = copy_file_into_workspace(
        workspace_root,
        source,
        "imports",
        original_filename=original_filename,
    )
    source_id = uuid.uuid4().hex
    imported_at = utc_now()

    try:
        with workspace_connection(workspace_root) as conn:
            conn.execute(
                """
                INSERT INTO sources(
                    source_id, source_type, original_filename, stored_filename,
                    relative_path, file_size, sha256, record_count, imported_at,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    "reference_import",
                    copied["original_filename"],
                    copied["stored_filename"],
                    copied["relative_path"],
                    copied["size"],
                    copied["sha256"],
                    len(records),
                    imported_at,
                    "{}",
                ),
            )
            for index, record in enumerate(records):
                record_id = _record_id(record)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO records(
                        record_id, title, abstract, authors, year, journal, doi,
                        keywords, source_file, record_origin, created_at, updated_at, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record_id,
                        _text(record.get("title")),
                        _text(record.get("abstract")),
                        _text(record.get("authors")),
                        _text(record.get("year")),
                        _text(record.get("journal")),
                        _text(record.get("doi")),
                        _text(record.get("keywords")),
                        copied["original_filename"],
                        RECORD_ORIGIN_IMPORTED_REFERENCE,
                        imported_at,
                        imported_at,
                        "{}",
                    ),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO record_sources(
                        record_id, source_id, source_record_index,
                        source_record_id, created_at, raw_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record_id,
                        source_id,
                        index,
                        _text(record.get("record_id")),
                        imported_at,
                        json_dumps(_sanitize_metadata(record)),
                    ),
                )
                _create_review_item_row(
                    conn,
                    record_id=record_id,
                    stage=REVIEW_STAGE_TITLE_ABSTRACT,
                    pdf_id=None,
                    created_at=imported_at,
                )
            _insert_audit_event(
                conn,
                event_type="reference_imported",
                entity_type="source",
                entity_id=source_id,
                summary=f"Imported {len(records)} reference records",
                metadata={"record_count": len(records), "source_sha256": copied["sha256"]},
            )
    except Exception:
        copied_path = resolve_workspace_relative_path(workspace_root, copied["relative_path"])
        copied_path.unlink(missing_ok=True)
        raise

    return {
        "source_id": source_id,
        "record_count": len(records),
        "relative_path": copied["relative_path"],
        "original_filename": copied["original_filename"],
        "sha256": copied["sha256"],
    }


def apply_reference_deduplication(root: str | Path, *, fuzzy_threshold: int = 90) -> dict[str, Any]:
    workspace_root = validate_workspace_root(root)
    try:
        threshold = int(fuzzy_threshold)
    except (TypeError, ValueError):
        threshold = 90
    threshold = max(0, min(100, threshold))

    with workspace_connection(workspace_root) as conn:
        records = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    r.record_id, r.title, r.authors, r.year, r.doi, r.created_at,
                    MIN(s.imported_at) AS first_imported_at,
                    MIN(rs.source_record_index) AS first_source_record_index
                FROM records r
                LEFT JOIN record_sources rs ON rs.record_id = r.record_id
                LEFT JOIN sources s ON s.source_id = rs.source_id
                WHERE r.record_origin = ?
                GROUP BY r.record_id
                ORDER BY
                    COALESCE(first_imported_at, r.created_at),
                    COALESCE(first_source_record_index, 0),
                    r.created_at,
                    r.record_id
                """,
                (RECORD_ORIGIN_IMPORTED_REFERENCE,),
            ).fetchall()
        ]

        duplicate_map: dict[str, dict[str, Any]] = {}
        doi_canonicals: dict[str, str] = {}
        pass1: list[dict[str, Any]] = []
        for record in records:
            record_id = record["record_id"]
            doi = _dedup_doi(record.get("doi"))
            if doi and doi in doi_canonicals:
                duplicate_map[record_id] = {
                    "duplicate_of_record_id": doi_canonicals[doi],
                    "dedup_method": DEDUP_METHOD_DOI,
                    "dedup_score": 100.0,
                }
                continue
            if doi:
                doi_canonicals[doi] = record_id
            pass1.append(record)

        kept_for_fuzzy: list[tuple[str, str]] = []
        for record in pass1:
            record_id = record["record_id"]
            title = _dedup_title(record.get("title"))
            if not title:
                kept_for_fuzzy.append((record_id, title))
                continue
            best_record_id = ""
            best_score = 0.0
            for kept_record_id, kept_title in kept_for_fuzzy:
                if not kept_title:
                    continue
                score = _dedup_title_score(title, kept_title)
                if score > best_score:
                    best_score = score
                    best_record_id = kept_record_id
            if best_record_id and best_score >= threshold:
                duplicate_map[record_id] = {
                    "duplicate_of_record_id": best_record_id,
                    "dedup_method": DEDUP_METHOD_FUZZY_TITLE,
                    "dedup_score": round(best_score, 2),
                }
            else:
                kept_for_fuzzy.append((record_id, title))

        now = utc_now()
        conn.execute(
            """
            UPDATE records
            SET is_active_for_screening = 1,
                duplicate_of_record_id = NULL,
                dedup_method = '',
                dedup_score = NULL,
                updated_at = ?
            WHERE record_origin = ?
            """,
            (now, RECORD_ORIGIN_IMPORTED_REFERENCE),
        )
        conn.execute(
            """
            UPDATE record_sources
            SET dedup_status = ?,
                duplicate_of_record_id = NULL,
                dedup_method = '',
                dedup_score = NULL
            WHERE record_id IN (
                SELECT record_id FROM records WHERE record_origin = ?
            )
            """,
            (DEDUP_STATUS_UNIQUE, RECORD_ORIGIN_IMPORTED_REFERENCE),
        )

        for duplicate_record_id, evidence in duplicate_map.items():
            conn.execute(
                """
                UPDATE records
                SET is_active_for_screening = 0,
                    duplicate_of_record_id = ?,
                    dedup_method = ?,
                    dedup_score = ?,
                    updated_at = ?
                WHERE record_id = ?
                """,
                (
                    evidence["duplicate_of_record_id"],
                    evidence["dedup_method"],
                    evidence["dedup_score"],
                    now,
                    duplicate_record_id,
                ),
            )
            conn.execute(
                """
                UPDATE record_sources
                SET dedup_status = ?,
                    duplicate_of_record_id = ?,
                    dedup_method = ?,
                    dedup_score = ?
                WHERE record_id = ?
                """,
                (
                    DEDUP_STATUS_DUPLICATE,
                    evidence["duplicate_of_record_id"],
                    evidence["dedup_method"],
                    evidence["dedup_score"],
                    duplicate_record_id,
                ),
            )

        canonical_rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT record_id, doi
                FROM records
                WHERE record_origin = ? AND is_active_for_screening = 1
                """,
                (RECORD_ORIGIN_IMPORTED_REFERENCE,),
            ).fetchall()
        ]
        for record in canonical_rows:
            source_rows = conn.execute(
                """
                SELECT record_id, source_id, source_record_index
                FROM record_sources
                WHERE record_id = ?
                ORDER BY created_at, source_id, source_record_index
                """,
                (record["record_id"],),
            ).fetchall()
            if len(source_rows) <= 1:
                continue
            method = DEDUP_METHOD_DOI if _dedup_doi(record.get("doi")) else DEDUP_METHOD_OTHER
            for source_row in source_rows[1:]:
                conn.execute(
                    """
                    UPDATE record_sources
                    SET dedup_status = ?,
                        duplicate_of_record_id = ?,
                        dedup_method = ?,
                        dedup_score = ?
                    WHERE record_id = ? AND source_id = ? AND source_record_index = ?
                    """,
                    (
                        DEDUP_STATUS_DUPLICATE,
                        record["record_id"],
                        method,
                        100.0,
                        source_row["record_id"],
                        source_row["source_id"],
                        source_row["source_record_index"],
                    ),
                )

        stats = _dedup_stats(conn)
        workspace_id_row = conn.execute(
            "SELECT value FROM workspace_meta WHERE key = ?",
            ("workspace_id",),
        ).fetchone()
        _insert_audit_event(
            conn,
            event_type="reference_deduplicated",
            entity_type="workspace",
            entity_id=workspace_id_row["value"] if workspace_id_row else "",
            summary=(
                f"Deduplicated references: {stats['total_after']} active unique "
                f"of {stats['total_before']} imported records"
            ),
            metadata={
                "fuzzy_threshold": threshold,
                "duplicate_record_ids": sorted(duplicate_map),
                "stats": stats,
            },
        )
        return {
            "stats": stats,
            "duplicates": [
                {"record_id": record_id, **evidence}
                for record_id, evidence in sorted(duplicate_map.items())
            ],
        }


def copy_file_into_workspace(
    root: str | Path,
    source_path: str | Path,
    subdir: str,
    *,
    original_filename: str | None = None,
    allowed_exts: Iterable[str] | None = None,
    max_size: int | None = None,
) -> dict[str, Any]:
    workspace_root = validate_workspace_root(root)
    if subdir not in WORKSPACE_SUBDIRS:
        raise UnsafeWorkspacePath("Unsupported workspace subfolder")

    source = Path(source_path).resolve()
    if not source.is_file():
        raise FileNotFoundError("Source file not found")

    original = _validate_filename(original_filename or source.name, allowed_exts=allowed_exts)
    size = source.stat().st_size
    if max_size is not None and size > max_size:
        raise WorkspaceError(f"File is too large; limit is {max_size} bytes")

    stored_filename = unique_stored_filename(original)
    dest_dir = workspace_root / subdir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = (dest_dir / stored_filename).resolve()
    try:
        dest.relative_to(dest_dir.resolve())
    except ValueError as exc:
        raise UnsafeWorkspacePath("Copy destination is outside the workspace") from exc

    shutil.copy2(source, dest)
    relative_path = dest.relative_to(workspace_root.resolve()).as_posix()
    return {
        "relative_path": relative_path,
        "stored_filename": stored_filename,
        "original_filename": original,
        "size": dest.stat().st_size,
        "sha256": sha256_file(dest),
    }


def register_pdf(
    root: str | Path,
    relative_path: str,
    *,
    original_filename: str,
    display_name: str | None = None,
    record_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workspace_root = validate_workspace_root(root)
    target = resolve_workspace_relative_path(
        workspace_root,
        relative_path,
        subdir="pdfs",
        must_exist=True,
        require_file=True,
    )
    if target.suffix.lower() != ".pdf":
        raise UnsafeWorkspacePath("PDF metadata path must point to a PDF")

    pdf_id = uuid.uuid4().hex
    uploaded_at = utc_now()
    relative = target.relative_to(workspace_root.resolve()).as_posix()
    size = target.stat().st_size
    digest = sha256_file(target)

    with workspace_connection(workspace_root) as conn:
        conn.execute(
            """
            INSERT INTO pdfs(
                pdf_id, relative_path, original_filename, display_name,
                file_size, sha256, record_id, uploaded_at, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pdf_id,
                relative,
                original_filename,
                display_name or original_filename,
                size,
                digest,
                record_id,
                uploaded_at,
                json_dumps(_sanitize_metadata(metadata or {})),
            ),
        )
        _insert_audit_event(
            conn,
            event_type="pdf_uploaded",
            entity_type="pdf",
            entity_id=pdf_id,
            summary=f"Uploaded PDF {display_name or original_filename}",
            metadata={"file_size": size, "sha256": digest},
        )

    return {
        "pdf_id": pdf_id,
        "relative_path": relative,
        "original_filename": original_filename,
        "display_name": display_name or original_filename,
        "size": size,
        "sha256": digest,
    }


def list_pdf_metadata(root: str | Path) -> list[dict[str, Any]]:
    with workspace_connection(root) as conn:
        rows = conn.execute(
            """
            SELECT pdf_id, relative_path, original_filename, display_name,
                   file_size, sha256, record_id, uploaded_at
            FROM pdfs
            ORDER BY display_name COLLATE NOCASE, relative_path COLLATE NOCASE
            """
        ).fetchall()
    return [dict(row) for row in rows]


def delete_pdf(root: str | Path, relative_path: str) -> int:
    workspace_root = validate_workspace_root(root)
    target = resolve_workspace_relative_path(
        workspace_root,
        relative_path,
        subdir="pdfs",
        must_exist=True,
        require_file=True,
    )
    relative = target.relative_to(workspace_root.resolve()).as_posix()
    with workspace_connection(workspace_root) as conn:
        row = conn.execute(
            "SELECT pdf_id, record_id FROM pdfs WHERE relative_path = ?",
            (relative,),
        ).fetchone()
        conn.execute("DELETE FROM pdfs WHERE relative_path = ?", (relative,))
        if row:
            if row["record_id"]:
                record = conn.execute(
                    "SELECT record_origin FROM records WHERE record_id = ?",
                    (row["record_id"],),
                ).fetchone()
                if record and record["record_origin"] == RECORD_ORIGIN_PDF_ONLY:
                    conn.execute(
                        """
                        UPDATE records
                        SET is_active_for_screening = 0,
                            updated_at = ?
                        WHERE record_id = ?
                        """,
                        (utc_now(), row["record_id"]),
                    )
            _insert_audit_event(
                conn,
                event_type="pdf_deleted",
                entity_type="pdf",
                entity_id=row["pdf_id"],
                summary="Deleted PDF",
                metadata={"relative_path": relative, "record_id": row["record_id"]},
            )
        remaining = conn.execute("SELECT COUNT(*) AS count FROM pdfs").fetchone()["count"]
    target.unlink(missing_ok=True)
    return int(remaining)


def clear_pdfs(root: str | Path) -> None:
    workspace_root = validate_workspace_root(root)
    for row in list_pdf_metadata(workspace_root):
        try:
            target = resolve_workspace_relative_path(
                workspace_root,
                row["relative_path"],
                subdir="pdfs",
                must_exist=True,
                require_file=True,
            )
            target.unlink(missing_ok=True)
        except (FileNotFoundError, UnsafeWorkspacePath):
            pass
    with workspace_connection(workspace_root) as conn:
        conn.execute(
            """
            UPDATE records
            SET is_active_for_screening = 0,
                updated_at = ?
            WHERE record_origin = ?
              AND record_id IN (
                  SELECT record_id FROM pdfs WHERE record_id IS NOT NULL
              )
            """,
            (utc_now(), RECORD_ORIGIN_PDF_ONLY),
        )
        conn.execute("DELETE FROM pdfs")
        _insert_audit_event(
            conn,
            event_type="pdfs_cleared",
            entity_type="workspace",
            entity_id=get_meta(workspace_root, "workspace_id") or "",
            summary="Cleared workspace PDFs",
            metadata={},
        )


def load_records(root: str | Path, *, include_inactive: bool = False) -> list[dict[str, Any]]:
    where_sql = "" if include_inactive else "WHERE is_active_for_screening = 1"
    with workspace_connection(root) as conn:
        rows = conn.execute(
            f"""
            SELECT record_id, title, abstract, authors, year, journal, doi,
                   keywords, source_file, record_origin, is_active_for_screening,
                   duplicate_of_record_id, dedup_method, dedup_score
            FROM records
            {where_sql}
            ORDER BY title COLLATE NOCASE, record_id
            """
        ).fetchall()
    return [dict(row) | {"decision": "", "rationale": "", "human_override": False} for row in rows]


def get_workspace_summary(root: str | Path) -> dict[str, Any]:
    workspace_root = validate_workspace_root(root)
    metadata = _load_workspace_json(workspace_root)
    with workspace_connection(workspace_root) as conn:
        review_status_counts = {
            status: 0
            for status in (
                REVIEW_STATUS_PENDING,
                REVIEW_STATUS_SUGGESTED,
                REVIEW_STATUS_INCLUDED,
                REVIEW_STATUS_EXCLUDED,
                REVIEW_STATUS_MAYBE,
                REVIEW_STATUS_FAILED,
            )
        }
        for row in conn.execute(
            """
            SELECT ri.status, COUNT(*) AS count
            FROM review_items ri
            JOIN records r ON r.record_id = ri.record_id
            WHERE r.is_active_for_screening = 1
            GROUP BY ri.status
            """
        ).fetchall():
            review_status_counts[row["status"]] = row["count"]
        decision_counts = {
            row["actor_type"]: row["count"]
            for row in conn.execute(
                "SELECT actor_type, COUNT(*) AS count FROM decisions GROUP BY actor_type"
            ).fetchall()
        }
        raw_imported_records = conn.execute(
            """
            SELECT COALESCE(SUM(record_count), 0) AS count
            FROM sources
            WHERE source_type = 'reference_import'
            """
        ).fetchone()["count"]
        active_unique_records = conn.execute(
            "SELECT COUNT(*) AS count FROM records WHERE is_active_for_screening = 1"
        ).fetchone()["count"]
        duplicate_source_records = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM record_sources
            WHERE dedup_status = ?
            """,
            (DEDUP_STATUS_DUPLICATE,),
        ).fetchone()["count"]
        inactive_duplicate_records = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM records
            WHERE is_active_for_screening = 0
              AND duplicate_of_record_id IS NOT NULL
            """
        ).fetchone()["count"]
        counts = {
            "sources": conn.execute("SELECT COUNT(*) AS count FROM sources").fetchone()["count"],
            "records": conn.execute("SELECT COUNT(*) AS count FROM records").fetchone()["count"],
            "raw_imported_records": int(raw_imported_records or 0),
            "active_unique_records": active_unique_records,
            "duplicate_records": duplicate_source_records,
            "duplicate_source_records": duplicate_source_records,
            "inactive_duplicate_records": inactive_duplicate_records,
            "pdfs": conn.execute("SELECT COUNT(*) AS count FROM pdfs").fetchone()["count"],
            "review_items": conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM review_items ri
                JOIN records r ON r.record_id = ri.record_id
                WHERE r.is_active_for_screening = 1
                """
            ).fetchone()["count"],
            "decisions": conn.execute("SELECT COUNT(*) AS count FROM decisions").fetchone()["count"],
            "ai_suggestions": decision_counts.get(ACTOR_AI, 0),
            "human_decisions": decision_counts.get(ACTOR_HUMAN, 0),
            "audit_events": conn.execute("SELECT COUNT(*) AS count FROM audit_events").fetchone()["count"],
            "review_items_by_status": review_status_counts,
        }
        record_origins = {origin: 0 for origin in sorted(RECORD_ORIGINS)}
        for row in conn.execute(
            "SELECT record_origin, COUNT(*) AS count FROM records GROUP BY record_origin"
        ).fetchall():
            origin = _normalize_record_origin(row["record_origin"])
            record_origins[origin] = row["count"]
        counts["records_by_origin"] = record_origins
        active_record_origins = {origin: 0 for origin in sorted(RECORD_ORIGINS)}
        for row in conn.execute(
            """
            SELECT record_origin, COUNT(*) AS count
            FROM records
            WHERE is_active_for_screening = 1
            GROUP BY record_origin
            """
        ).fetchall():
            origin = _normalize_record_origin(row["record_origin"])
            active_record_origins[origin] = row["count"]
        counts["active_records_by_origin"] = active_record_origins
    return {
        "workspace_id": metadata.get("workspace_id", ""),
        "name": metadata.get("name", workspace_root.name),
        "schema_version": int(metadata.get("schema_version", SCHEMA_VERSION)),
        "app_version": metadata.get("app_version", VERSION),
        "created_at": metadata.get("created_at", ""),
        "updated_at": metadata.get("updated_at", ""),
        "review_title": metadata.get("review_title", ""),
        "review_type": _normalize_review_type(metadata.get("review_type")),
        "review_question": metadata.get("review_question", ""),
        "reviewer_name": metadata.get("reviewer_name", ""),
        "counts": counts,
    }


def get_meta(root: str | Path, key: str) -> str | None:
    with workspace_connection(root) as conn:
        row = conn.execute(
            "SELECT value FROM workspace_meta WHERE key = ?",
            (key,),
        ).fetchone()
    return row["value"] if row else None


def write_audit_event(
    root: str | Path,
    *,
    event_type: str,
    entity_type: str,
    entity_id: str,
    summary: str,
    metadata: dict[str, Any] | None = None,
    actor_type: str = "system",
    actor_id: str | None = None,
) -> str:
    with workspace_connection(root) as conn:
        return _insert_audit_event(
            conn,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            summary=summary,
            metadata=metadata or {},
            actor_type=actor_type,
            actor_id=actor_id,
        )


def create_automation_run(
    root: str | Path,
    *,
    run_id: str | None = None,
    run_type: str,
    provider: str = "",
    model: str = "",
    base_url: str = "",
    input_count: int = 0,
    metadata: dict[str, Any] | None = None,
) -> str:
    run = _text(run_id).strip() or uuid.uuid4().hex
    with workspace_connection(root) as conn:
        conn.execute(
            """
            INSERT INTO automation_runs(
                run_id, run_type, started_at, finished_at, status, provider,
                model, base_url, input_count, output_count, metadata_json
            )
            VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                run,
                _bounded_text(run_type, limit=100),
                utc_now(),
                AUTOMATION_RUN_STATUS_RUNNING,
                _bounded_text(provider, limit=200),
                _bounded_text(model, limit=200),
                _bounded_text(base_url, limit=500),
                int(input_count or 0),
                json_dumps(_sanitize_metadata(metadata or {})),
            ),
        )
    return run


def finish_automation_run(
    root: str | Path,
    run_id: str,
    *,
    status: str,
    output_count: int = 0,
    metadata: dict[str, Any] | None = None,
) -> None:
    run = _text(run_id).strip()
    if not run:
        return
    with workspace_connection(root) as conn:
        conn.execute(
            """
            UPDATE automation_runs
            SET finished_at = ?,
                status = ?,
                output_count = ?,
                metadata_json = ?
            WHERE run_id = ?
            """,
            (
                utc_now(),
                _bounded_text(status, limit=100),
                int(output_count or 0),
                json_dumps(_sanitize_metadata(metadata or {})),
                run,
            ),
        )


def reconcile_stale_automation_runs(
    root: str | Path,
    *,
    live_run_ids: set[str] | None = None,
) -> int:
    live = {
        _text(run_id).strip()
        for run_id in (live_run_ids or set())
        if _text(run_id).strip()
    }
    with workspace_connection(root) as conn:
        stale = [
            row["run_id"]
            for row in conn.execute(
                "SELECT run_id FROM automation_runs WHERE status = ?",
                (AUTOMATION_RUN_STATUS_RUNNING,),
            ).fetchall()
            if row["run_id"] not in live
        ]
        if not stale:
            return 0
        finished_at = utc_now()
        changed = 0
        for run_id in stale:
            changed += conn.execute(
                """
                UPDATE automation_runs
                SET finished_at = ?, status = ?
                WHERE run_id = ? AND status = ?
                """,
                (
                    finished_at,
                    AUTOMATION_RUN_STATUS_INTERRUPTED,
                    run_id,
                    AUTOMATION_RUN_STATUS_RUNNING,
                ),
            ).rowcount
        return changed


def create_review_item(
    root: str | Path,
    record_id: str,
    stage: str,
    pdf_id: str | None = None,
) -> dict[str, Any]:
    stage_value = _normalize_stage(stage)
    with workspace_connection(root) as conn:
        item_id = _create_review_item_row(
            conn,
            record_id=_text(record_id).strip(),
            stage=stage_value,
            pdf_id=_text(pdf_id).strip() or None,
        )
        return _get_review_item_status(conn, item_id)


def get_review_queue(
    root: str | Path,
    *,
    stage: str | None = None,
    status: str | None = None,
    record_origin: str | None = None,
) -> list[dict[str, Any]]:
    stage_value = _normalize_stage(stage) if stage else None
    status_value = _normalize_status_filter(status) if status else None
    origin_value = _normalize_record_origin(record_origin) if record_origin else None
    where = ["r.is_active_for_screening = 1"]
    params: list[Any] = []
    if stage_value:
        where.append("ri.stage = ?")
        params.append(stage_value)
    if status_value:
        where.append("ri.status = ?")
        params.append(status_value)
    if origin_value:
        where.append("r.record_origin = ?")
        params.append(origin_value)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    with workspace_connection(root) as conn:
        rows = conn.execute(
            f"""
            SELECT
                ri.item_id, ri.record_id, ri.pdf_id, ri.stage, ri.status,
                ri.created_at, ri.updated_at, ri.metadata_json,
                r.title, r.authors, r.year, r.journal, r.doi, r.source_file,
                r.record_origin, r.is_active_for_screening,
                r.duplicate_of_record_id, r.dedup_method, r.dedup_score,
                p.relative_path AS pdf_relative_path,
                p.original_filename AS pdf_original_filename,
                p.display_name AS pdf_display_name
            FROM review_items ri
            JOIN records r ON r.record_id = ri.record_id
            LEFT JOIN pdfs p ON p.pdf_id = ri.pdf_id
            {where_sql}
            ORDER BY
                CASE ri.status
                    WHEN 'pending' THEN 1
                    WHEN 'suggested' THEN 2
                    WHEN 'maybe' THEN 3
                    WHEN 'failed' THEN 4
                    WHEN 'included' THEN 5
                    WHEN 'excluded' THEN 6
                    ELSE 9
                END,
                r.title COLLATE NOCASE,
                ri.created_at
            """,
            params,
        ).fetchall()
        queue = []
        for row in rows:
            item = dict(row)
            item["latest_ai_suggestion"] = _decision_public(
                _latest_decision_row(conn, item["item_id"], actor_type=ACTOR_AI)
            )
            item["latest_human_decision"] = _decision_public(
                _latest_decision_row(conn, item["item_id"], actor_type=ACTOR_HUMAN)
            )
            item["latest_decision"] = _decision_public(_latest_decision_row(conn, item["item_id"]))
            item["display_title"] = item.get("title") or item.get("pdf_display_name") or item["record_id"]
            queue.append(item)
    return queue


def add_ai_suggestion(
    root: str | Path,
    *,
    record_id: str,
    stage: str,
    decision: str,
    pdf_id: str | None = None,
    rationale: str = "",
    confidence: Any = None,
    provider: str = "",
    model: str = "",
    prompt_hash: str = "",
    text_hash: str = "",
    cache_key: str = "",
    automation_run_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stage_value = _normalize_stage(stage)
    decision_value = _normalize_decision(decision, actor_type=ACTOR_AI)
    with workspace_connection(root) as conn:
        item_id = _create_review_item_row(
            conn,
            record_id=_text(record_id).strip(),
            stage=stage_value,
            pdf_id=_text(pdf_id).strip() or None,
        )
        decision_id = _insert_decision_row(
            conn,
            review_item_id=item_id,
            actor_type=ACTOR_AI,
            reviewer_id=None,
            decision=decision_value,
            rationale=rationale,
            confidence=confidence,
            exclusion_reason_id=None,
            provider=provider,
            model=model,
            prompt_hash=prompt_hash,
            text_hash=text_hash,
            cache_key=cache_key,
            automation_run_id=automation_run_id,
            metadata=metadata or {},
        )
        _recalculate_review_item_status(conn, item_id)
        _insert_audit_event(
            conn,
            event_type="ai_suggestion_added",
            entity_type="review_item",
            entity_id=item_id,
            summary=f"AI suggested {decision_value}",
            metadata={
                "decision_id": decision_id,
                "decision": decision_value,
                "stage": stage_value,
                "provider": provider,
                "model": model,
                "prompt_hash": prompt_hash,
                "text_hash": text_hash,
                "cache_key": cache_key,
            },
            actor_type=ACTOR_AI,
            actor_id=None,
        )
        return _get_review_item_status(conn, item_id)


def add_human_decision(
    root: str | Path,
    *,
    review_item_id: str,
    reviewer_id: str,
    decision: str,
    rationale: str = "",
    exclusion_reason_id: str | None = None,
    confidence: Any = None,
    metadata: dict[str, Any] | None = None,
    event_type: str = "human_decision_added",
) -> dict[str, Any]:
    reviewer = _text(reviewer_id).strip()
    if not reviewer:
        raise WorkspaceError("reviewer_id is required for human decisions")
    decision_value = _normalize_decision(decision, actor_type=ACTOR_HUMAN)
    if decision_value not in {DECISION_INCLUDE, DECISION_EXCLUDE, DECISION_MAYBE}:
        raise WorkspaceError("Human decision must be include, exclude, or maybe")

    with workspace_connection(root) as conn:
        item = conn.execute(
            "SELECT item_id, stage FROM review_items WHERE item_id = ?",
            (_text(review_item_id).strip(),),
        ).fetchone()
        if not item:
            raise WorkspaceError("Review item not found")
        if not _reviewer_exists(conn, reviewer):
            raise WorkspaceError("Reviewer not found")

        reason = _text(exclusion_reason_id).strip() or None
        if item["stage"] == REVIEW_STAGE_FULL_TEXT and decision_value == DECISION_EXCLUDE and not reason:
            raise WorkspaceError("Full-text exclude decisions require an exclusion reason")
        if reason and not _exclusion_reason_exists(conn, reason):
            raise WorkspaceError("Exclusion reason not found")

        decision_id = _insert_decision_row(
            conn,
            review_item_id=item["item_id"],
            actor_type=ACTOR_HUMAN,
            reviewer_id=reviewer,
            decision=decision_value,
            rationale=rationale,
            confidence=confidence,
            exclusion_reason_id=reason,
            provider="",
            model="",
            prompt_hash="",
            text_hash="",
            cache_key="",
            automation_run_id=None,
            metadata=metadata or {},
        )
        _recalculate_review_item_status(conn, item["item_id"])
        _insert_audit_event(
            conn,
            event_type=event_type,
            entity_type="review_item",
            entity_id=item["item_id"],
            summary=f"Human decided {decision_value}",
            metadata={
                "decision_id": decision_id,
                "decision": decision_value,
                "stage": item["stage"],
                "exclusion_reason_id": reason,
            },
            actor_type=ACTOR_HUMAN,
            actor_id=reviewer,
        )
        return _get_review_item_status(conn, item["item_id"])


def accept_ai_suggestion(
    root: str | Path,
    *,
    review_item_id: str,
    reviewer_id: str,
    rationale: str = "",
    exclusion_reason_id: str | None = None,
) -> dict[str, Any]:
    with workspace_connection(root) as conn:
        latest_ai = _latest_decision_row(conn, _text(review_item_id).strip(), actor_type=ACTOR_AI)
    if not latest_ai:
        raise WorkspaceError("No AI suggestion is available for this review item")
    if latest_ai["decision"] == DECISION_FAILED:
        raise WorkspaceError("Failed AI suggestions cannot be accepted as final decisions")
    decision = latest_ai["decision"] if latest_ai["decision"] in {
        DECISION_INCLUDE,
        DECISION_EXCLUDE,
        DECISION_MAYBE,
    } else DECISION_MAYBE
    return add_human_decision(
        root,
        review_item_id=review_item_id,
        reviewer_id=reviewer_id,
        decision=decision,
        rationale=rationale or "Accepted AI suggestion.",
        exclusion_reason_id=exclusion_reason_id,
        metadata={"accepted_ai_decision_id": latest_ai["decision_id"]},
        event_type="ai_suggestion_accepted",
    )


def override_decision(
    root: str | Path,
    *,
    review_item_id: str,
    reviewer_id: str,
    decision: str,
    rationale: str = "",
    exclusion_reason_id: str | None = None,
) -> dict[str, Any]:
    return add_human_decision(
        root,
        review_item_id=review_item_id,
        reviewer_id=reviewer_id,
        decision=decision,
        rationale=rationale,
        exclusion_reason_id=exclusion_reason_id,
        event_type="human_decision_overridden",
    )


def get_review_item_status(root: str | Path, review_item_id: str) -> dict[str, Any]:
    with workspace_connection(root) as conn:
        return _get_review_item_status(conn, _text(review_item_id).strip())


def get_review_summary(root: str | Path) -> dict[str, Any]:
    with workspace_connection(root) as conn:
        by_status = {
            status: 0
            for status in (
                REVIEW_STATUS_PENDING,
                REVIEW_STATUS_SUGGESTED,
                REVIEW_STATUS_INCLUDED,
                REVIEW_STATUS_EXCLUDED,
                REVIEW_STATUS_MAYBE,
                REVIEW_STATUS_FAILED,
            )
        }
        for row in conn.execute(
            """
            SELECT ri.status, COUNT(*) AS count
            FROM review_items ri
            JOIN records r ON r.record_id = ri.record_id
            WHERE r.is_active_for_screening = 1
            GROUP BY ri.status
            """
        ).fetchall():
            by_status[row["status"]] = row["count"]

        by_stage = {
            row["stage"]: row["count"]
            for row in conn.execute(
                """
                SELECT ri.stage, COUNT(*) AS count
                FROM review_items ri
                JOIN records r ON r.record_id = ri.record_id
                WHERE r.is_active_for_screening = 1
                GROUP BY ri.stage
                """
            ).fetchall()
        }
        decision_counts = {
            row["actor_type"]: row["count"]
            for row in conn.execute(
                "SELECT actor_type, COUNT(*) AS count FROM decisions GROUP BY actor_type"
            ).fetchall()
        }
        reasons = [
            dict(row)
            for row in conn.execute(
                """
                SELECT reason_id, label, description, is_default, sort_order
                FROM exclusion_reasons
                ORDER BY sort_order, label COLLATE NOCASE
                """
            ).fetchall()
        ]

    return {
        "total": sum(by_status.values()),
        "total_count": sum(by_status.values()),
        "by_status": by_status,
        "review_items_by_status": by_status,
        "by_stage": by_stage,
        "decision_counts": decision_counts,
        "ai_suggestion_count": decision_counts.get(ACTOR_AI, 0),
        "human_decision_count": decision_counts.get(ACTOR_HUMAN, 0),
        "default_reviewer_id": DEFAULT_REVIEWER_ID,
        "exclusion_reasons": reasons,
    }


def get_exportable_screening_rows(root: str | Path) -> list[dict[str, Any]]:
    """Return audit-oriented screening rows for workspace exports.

    Includes inactive duplicate records so export files can document what was
    hidden from active screening counts.
    """
    with workspace_connection(root) as conn:
        source_rows = conn.execute(
            """
            SELECT
                rs.record_id,
                COUNT(*) AS source_count,
                GROUP_CONCAT(s.original_filename, '; ') AS source_filenames,
                MAX(CASE WHEN rs.dedup_status = ? THEN 1 ELSE 0 END) AS has_duplicate_source,
                MAX(rs.duplicate_of_record_id) AS source_duplicate_of_record_id,
                MAX(rs.dedup_method) AS source_dedup_method,
                MAX(rs.dedup_score) AS source_dedup_score
            FROM record_sources rs
            JOIN sources s ON s.source_id = rs.source_id
            GROUP BY rs.record_id
            """,
            (DEDUP_STATUS_DUPLICATE,),
        ).fetchall()
        sources_by_record = {row["record_id"]: dict(row) for row in source_rows}

        rows = conn.execute(
            """
            SELECT
                r.record_id, r.title, r.authors, r.year, r.journal, r.doi,
                r.source_file, r.record_origin, r.is_active_for_screening,
                r.duplicate_of_record_id, r.dedup_method, r.dedup_score,
                ri.item_id, ri.pdf_id, ri.stage, ri.status AS current_status,
                ri.created_at AS review_item_created_at,
                ri.updated_at AS review_item_updated_at,
                p.display_name AS pdf_display_name,
                p.original_filename AS pdf_original_filename,
                p.relative_path AS pdf_relative_path
            FROM records r
            LEFT JOIN review_items ri ON ri.record_id = r.record_id
            LEFT JOIN pdfs p ON p.pdf_id = ri.pdf_id
            ORDER BY
                r.is_active_for_screening DESC,
                r.record_origin,
                r.title COLLATE NOCASE,
                r.record_id,
                ri.stage
            """
        ).fetchall()

        export_rows = []
        for row in rows:
            item = dict(row)
            source = sources_by_record.get(item["record_id"], {})
            latest_ai = _decision_public(
                _latest_decision_row(conn, item.get("item_id") or "", actor_type=ACTOR_AI)
            ) if item.get("item_id") else None
            latest_human = _decision_public(
                _latest_decision_row(conn, item.get("item_id") or "", actor_type=ACTOR_HUMAN)
            ) if item.get("item_id") else None
            reason_label = ""
            if latest_human and latest_human.get("exclusion_reason_id"):
                reason = conn.execute(
                    "SELECT label FROM exclusion_reasons WHERE reason_id = ?",
                    (latest_human["exclusion_reason_id"],),
                ).fetchone()
                reason_label = reason["label"] if reason else latest_human["exclusion_reason_id"]

            duplicate_of = item.get("duplicate_of_record_id") or source.get("source_duplicate_of_record_id") or ""
            duplicate_status = DEDUP_STATUS_DUPLICATE if duplicate_of or source.get("has_duplicate_source") else DEDUP_STATUS_UNIQUE
            decision_timestamp = ""
            final_source = "none"
            if latest_human:
                decision_timestamp = latest_human.get("created_at") or ""
                final_source = ACTOR_HUMAN
            elif latest_ai:
                decision_timestamp = latest_ai.get("created_at") or ""
                final_source = "ai_suggestion_not_final"

            export_rows.append({
                "record_id": item["record_id"],
                "stable_record_id": _stable_record_id(item),
                "title": item.get("title") or "",
                "authors": item.get("authors") or "",
                "year": item.get("year") or "",
                "journal": item.get("journal") or "",
                "doi": item.get("doi") or "",
                "record_origin": item.get("record_origin") or RECORD_ORIGIN_IMPORTED_REFERENCE,
                "is_active_for_screening": int(item.get("is_active_for_screening") or 0),
                "duplicate_status": duplicate_status,
                "duplicate_of_record_id": duplicate_of,
                "dedup_method": item.get("dedup_method") or source.get("source_dedup_method") or "",
                "dedup_score": item.get("dedup_score") if item.get("dedup_score") is not None else source.get("source_dedup_score"),
                "stage": item.get("stage") or "",
                "current_status": item.get("current_status") or "not_started",
                "ai_suggestion": latest_ai.get("decision", "") if latest_ai else "",
                "ai_rationale": latest_ai.get("rationale", "") if latest_ai else "",
                "ai_is_final": "no" if latest_ai else "",
                "human_final_decision": latest_human.get("decision", "") if latest_human else "",
                "human_rationale": latest_human.get("rationale", "") if latest_human else "",
                "final_decision_source": final_source,
                "exclusion_reason": reason_label,
                "reviewer": latest_human.get("reviewer_id", "") if latest_human else "",
                "decision_timestamp": decision_timestamp,
                "pdf_display_name": item.get("pdf_display_name") or "",
                "source_filenames": source.get("source_filenames") or item.get("source_file") or "",
                "source_count": int(source.get("source_count") or 0),
            })
    return export_rows


def get_decision_export_rows(root: str | Path, *, actor_type: str | None = None) -> list[dict[str, Any]]:
    actor = _text(actor_type).strip().lower() or None
    if actor and actor not in ACTOR_TYPES:
        raise WorkspaceError("Unsupported decision actor type")
    where_sql = "WHERE d.actor_type = ?" if actor else ""
    params: list[Any] = [actor] if actor else []
    with workspace_connection(root) as conn:
        rows = conn.execute(
            f"""
            SELECT
                d.decision_id, d.review_item_id, d.actor_type, d.reviewer_id,
                d.decision, d.rationale, d.confidence, d.exclusion_reason_id,
                er.label AS exclusion_reason,
                d.provider, d.model, d.prompt_hash, d.text_hash, d.cache_key,
                d.automation_run_id, d.created_at,
                ri.record_id, ri.pdf_id, ri.stage, ri.status AS current_status,
                r.title, r.authors, r.year, r.journal, r.doi, r.record_origin,
                r.is_active_for_screening, r.duplicate_of_record_id,
                r.dedup_method, r.dedup_score,
                p.display_name AS pdf_display_name
            FROM decisions d
            JOIN review_items ri ON ri.item_id = d.review_item_id
            JOIN records r ON r.record_id = ri.record_id
            LEFT JOIN exclusion_reasons er ON er.reason_id = d.exclusion_reason_id
            LEFT JOIN pdfs p ON p.pdf_id = ri.pdf_id
            {where_sql}
            ORDER BY d.created_at, d.rowid
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def get_full_text_exclusion_rows(root: str | Path) -> list[dict[str, Any]]:
    with workspace_connection(root) as conn:
        rows = conn.execute(
            """
            SELECT
                d.decision_id, d.review_item_id, d.reviewer_id, d.decision,
                d.rationale, d.exclusion_reason_id,
                er.label AS exclusion_reason,
                d.created_at AS decision_timestamp,
                ri.record_id, ri.pdf_id, ri.stage, ri.status AS current_status,
                r.title, r.authors, r.year, r.journal, r.doi, r.record_origin,
                p.display_name AS pdf_display_name
            FROM decisions d
            JOIN review_items ri ON ri.item_id = d.review_item_id
            JOIN records r ON r.record_id = ri.record_id
            LEFT JOIN exclusion_reasons er ON er.reason_id = d.exclusion_reason_id
            LEFT JOIN pdfs p ON p.pdf_id = ri.pdf_id
            WHERE d.actor_type = ?
              AND d.decision = ?
              AND ri.stage = ?
            ORDER BY d.created_at, d.rowid
            """,
            (ACTOR_HUMAN, DECISION_EXCLUDE, REVIEW_STAGE_FULL_TEXT),
        ).fetchall()
    return [dict(row) for row in rows]


def get_prisma_ready_counts(root: str | Path) -> dict[str, Any]:
    workspace_root = validate_workspace_root(root)
    summary = get_workspace_summary(workspace_root)
    with workspace_connection(workspace_root) as conn:
        counts = summary["counts"]
        stage_status = _stage_status_counts(conn)
        full_text_reasons = {
            row["exclusion_reason"] or row["exclusion_reason_id"] or "unspecified": row["count"]
            for row in conn.execute(
                """
                SELECT
                    d.exclusion_reason_id,
                    er.label AS exclusion_reason,
                    COUNT(*) AS count
                FROM decisions d
                JOIN review_items ri ON ri.item_id = d.review_item_id
                JOIN records r ON r.record_id = ri.record_id
                LEFT JOIN exclusion_reasons er ON er.reason_id = d.exclusion_reason_id
                WHERE d.actor_type = ?
                  AND d.decision = ?
                  AND ri.stage = ?
                  AND r.is_active_for_screening = 1
                GROUP BY d.exclusion_reason_id, er.label
                ORDER BY er.sort_order, er.label COLLATE NOCASE
                """,
                (ACTOR_HUMAN, DECISION_EXCLUDE, REVIEW_STAGE_FULL_TEXT),
            ).fetchall()
        }
        ai_only_unfinalized = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM review_items ri
            JOIN records r ON r.record_id = ri.record_id
            WHERE r.is_active_for_screening = 1
              AND EXISTS (
                  SELECT 1 FROM decisions d
                  WHERE d.review_item_id = ri.item_id
                    AND d.actor_type = ?
              )
              AND NOT EXISTS (
                  SELECT 1 FROM decisions d
                  WHERE d.review_item_id = ri.item_id
                    AND d.actor_type = ?
              )
            """,
            (ACTOR_AI, ACTOR_HUMAN),
        ).fetchone()["count"]
        human_stage_decisions = _human_stage_decision_counts(conn)
        failed_processing_items = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM review_items ri
            JOIN records r ON r.record_id = ri.record_id
            WHERE r.is_active_for_screening = 1
              AND ri.status = ?
            """,
            (REVIEW_STATUS_FAILED,),
        ).fetchone()["count"]

    active_origins = counts.get("active_records_by_origin", {})
    origins = counts.get("records_by_origin", {})
    metric_counts = {
        "raw_imported_reference_rows": _available_count(
            counts.get("raw_imported_records", 0),
            "Sum of source record_count values for reference imports.",
        ),
        "imported_reference_records": _available_count(
            origins.get(RECORD_ORIGIN_IMPORTED_REFERENCE, 0),
            "Workspace records whose origin is imported_reference, including inactive duplicates.",
        ),
        "active_unique_imported_references": _available_count(
            active_origins.get(RECORD_ORIGIN_IMPORTED_REFERENCE, 0),
            "Active imported_reference records after workspace deduplication.",
        ),
        "duplicate_records_hidden_from_active_screening": _available_count(
            counts.get("inactive_duplicate_records", counts.get("duplicate_records", 0)),
            "Inactive duplicate records retained for audit but hidden from active screening counts.",
        ),
        "duplicate_source_records": _available_count(
            counts.get("duplicate_source_records", counts.get("duplicate_records", 0)),
            "Duplicate source rows identified during deduplication.",
        ),
        "pdf_only_records": _available_count(
            origins.get(RECORD_ORIGIN_PDF_ONLY, 0),
            "Workspace records created from PDFs without imported reference metadata.",
        ),
        "active_pdf_only_records": _available_count(
            active_origins.get(RECORD_ORIGIN_PDF_ONLY, 0),
            "Active PDF-only records available for screening.",
        ),
        "manual_records": _available_count(
            origins.get(RECORD_ORIGIN_MANUAL, 0),
            "Workspace records whose origin is manual.",
        ),
        "active_manual_records": _available_count(
            active_origins.get(RECORD_ORIGIN_MANUAL, 0),
            "Active manual records available for screening.",
        ),
        "total_active_review_items": _available_count(
            counts.get("review_items", 0),
            "Review items joined to active records.",
        ),
        "title_abstract_pending": _available_count(
            stage_status.get(REVIEW_STAGE_TITLE_ABSTRACT, {}).get(REVIEW_STATUS_PENDING, 0),
            "Active title/abstract review items with pending status.",
        ),
        "title_abstract_ai_suggested": _available_count(
            stage_status.get(REVIEW_STAGE_TITLE_ABSTRACT, {}).get(REVIEW_STATUS_SUGGESTED, 0),
            "Active title/abstract review items with AI suggestion and no human final decision.",
        ),
        "title_abstract_human_included": _available_count(
            human_stage_decisions.get(REVIEW_STAGE_TITLE_ABSTRACT, {}).get(DECISION_INCLUDE, 0),
            "Latest human final include decisions at title/abstract stage.",
        ),
        "title_abstract_human_excluded": _available_count(
            human_stage_decisions.get(REVIEW_STAGE_TITLE_ABSTRACT, {}).get(DECISION_EXCLUDE, 0),
            "Latest human final exclude decisions at title/abstract stage.",
        ),
        "title_abstract_maybe": _available_count(
            human_stage_decisions.get(REVIEW_STAGE_TITLE_ABSTRACT, {}).get(DECISION_MAYBE, 0),
            "Latest human final maybe decisions at title/abstract stage.",
        ),
        "full_text_reports_available": _not_available_count(
            "The workspace schema does not yet track availability of full-text reports separately from uploaded PDFs.",
        ),
        "full_text_human_included": _available_count(
            human_stage_decisions.get(REVIEW_STAGE_FULL_TEXT, {}).get(DECISION_INCLUDE, 0),
            "Latest human final include decisions at full-text stage.",
        ),
        "full_text_human_excluded": _available_count(
            human_stage_decisions.get(REVIEW_STAGE_FULL_TEXT, {}).get(DECISION_EXCLUDE, 0),
            "Latest human final exclude decisions at full-text stage.",
        ),
        "full_text_exclusions_by_reason": {
            "value": full_text_reasons,
            "status": "available",
            "explanation": "Human full-text exclude decisions grouped by exclusion reason.",
        },
        "ai_only_unfinalized_suggestions": _available_count(
            ai_only_unfinalized,
            "Active review items with at least one AI suggestion and no human final decision.",
        ),
        "failed_processing_items": _available_count(
            failed_processing_items,
            "Active review items with failed status.",
        ),
    }
    return {
        "label": "PRISMA-ready counts",
        "generated_at": utc_now(),
        "workspace_id": summary.get("workspace_id", ""),
        "workspace_name": summary.get("name", ""),
        "app_version": summary.get("app_version", VERSION),
        "counts": metric_counts,
        "warnings": [
            "PRISMA-ready counts are derived from workspace data and should be checked before reporting.",
            "AI-only suggestions are not final decisions.",
            "Counts marked not_available are not fabricated.",
        ],
    }


def get_export_metadata(root: str | Path) -> dict[str, Any]:
    workspace_root = validate_workspace_root(root)
    summary = get_workspace_summary(workspace_root)
    with workspace_connection(workspace_root) as conn:
        sources = [
            dict(row)
            for row in conn.execute(
                """
                SELECT source_id, source_type, original_filename, record_count, imported_at
                FROM sources
                ORDER BY imported_at, original_filename COLLATE NOCASE
                """
            ).fetchall()
        ]
        dedup_methods = {
            row["dedup_method"] or DEDUP_METHOD_OTHER: row["count"]
            for row in conn.execute(
                """
                SELECT dedup_method, COUNT(*) AS count
                FROM records
                WHERE duplicate_of_record_id IS NOT NULL
                   OR is_active_for_screening = 0
                GROUP BY dedup_method
                """
            ).fetchall()
        }
        ai_models = [
            dict(row)
            for row in conn.execute(
                """
                SELECT provider, model, COUNT(*) AS suggestion_count
                FROM decisions
                WHERE actor_type = ?
                  AND (provider != '' OR model != '')
                GROUP BY provider, model
                ORDER BY suggestion_count DESC, provider COLLATE NOCASE, model COLLATE NOCASE
                """,
                (ACTOR_AI,),
            ).fetchall()
        ]
        automation_runs = [
            dict(row)
            for row in conn.execute(
                """
                SELECT run_id, run_type, started_at, finished_at, status,
                       provider, model, input_count, output_count
                FROM automation_runs
                ORDER BY started_at DESC
                LIMIT 20
                """
            ).fetchall()
        ]
    return {
        "workspace_summary": summary,
        "sources": sources,
        "dedup_methods": dedup_methods,
        "ai_models": ai_models,
        "automation_runs": automation_runs,
        "review_summary": get_review_summary(workspace_root),
    }


def ensure_record_for_pdf(root: str | Path, pdf_id: str) -> str:
    pdf = _text(pdf_id).strip()
    if not pdf:
        raise WorkspaceError("pdf_id is required")
    with workspace_connection(root) as conn:
        row = conn.execute(
            """
            SELECT pdf_id, record_id, original_filename, display_name, uploaded_at
            FROM pdfs
            WHERE pdf_id = ?
            """,
            (pdf,),
        ).fetchone()
        if not row:
            raise WorkspaceError("PDF not found")
        if row["record_id"]:
            return row["record_id"]

        now = utc_now()
        record_id = f"pdf-{pdf}"
        conn.execute(
            """
            INSERT OR IGNORE INTO records(
                record_id, title, abstract, authors, year, journal, doi,
                keywords, source_file, record_origin, created_at, updated_at, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                row["display_name"] or row["original_filename"],
                "",
                "",
                "",
                "",
                "",
                "",
                row["original_filename"] or row["display_name"],
                RECORD_ORIGIN_PDF_ONLY,
                row["uploaded_at"] or now,
                now,
                json_dumps({"source": "workspace_pdf"}),
            ),
        )
        conn.execute("UPDATE pdfs SET record_id = ? WHERE pdf_id = ?", (record_id, pdf))
        _insert_audit_event(
            conn,
            event_type="pdf_record_created",
            entity_type="pdf",
            entity_id=pdf,
            summary="Created review record for PDF",
            metadata={"record_id": record_id},
        )
        return record_id


def unique_stored_filename(original_filename: str) -> str:
    safe = _validate_filename(original_filename)
    stem = Path(safe).stem or "file"
    ext = Path(safe).suffix.lower()
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or "file"
    stem = stem[:80]
    return f"{uuid.uuid4().hex}_{stem}{ext}"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


def _schema_statements() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS workspace_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS reviewers (
            reviewer_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'primary',
            is_default INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS sources (
            source_id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            stored_filename TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            file_size INTEGER NOT NULL DEFAULT 0,
            sha256 TEXT NOT NULL,
            record_count INTEGER NOT NULL DEFAULT 0,
            imported_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS records (
            record_id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            abstract TEXT NOT NULL DEFAULT '',
            authors TEXT NOT NULL DEFAULT '',
            year TEXT NOT NULL DEFAULT '',
            journal TEXT NOT NULL DEFAULT '',
            doi TEXT NOT NULL DEFAULT '',
            keywords TEXT NOT NULL DEFAULT '',
            source_file TEXT NOT NULL DEFAULT '',
            record_origin TEXT NOT NULL DEFAULT 'imported_reference',
            is_active_for_screening INTEGER NOT NULL DEFAULT 1,
            duplicate_of_record_id TEXT,
            dedup_method TEXT NOT NULL DEFAULT '',
            dedup_score REAL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (duplicate_of_record_id) REFERENCES records(record_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS record_sources (
            record_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            source_record_index INTEGER NOT NULL,
            source_record_id TEXT NOT NULL DEFAULT '',
            dedup_status TEXT NOT NULL DEFAULT 'unique',
            duplicate_of_record_id TEXT,
            dedup_method TEXT NOT NULL DEFAULT '',
            dedup_score REAL,
            created_at TEXT NOT NULL,
            raw_json TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY (record_id, source_id, source_record_index),
            FOREIGN KEY (record_id) REFERENCES records(record_id) ON DELETE CASCADE,
            FOREIGN KEY (source_id) REFERENCES sources(source_id) ON DELETE CASCADE,
            FOREIGN KEY (duplicate_of_record_id) REFERENCES records(record_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pdfs (
            pdf_id TEXT PRIMARY KEY,
            relative_path TEXT NOT NULL UNIQUE,
            original_filename TEXT NOT NULL,
            display_name TEXT NOT NULL,
            file_size INTEGER NOT NULL DEFAULT 0,
            sha256 TEXT NOT NULL,
            record_id TEXT,
            uploaded_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (record_id) REFERENCES records(record_id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS exclusion_reasons (
            reason_id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            is_default INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS automation_runs (
            run_id TEXT PRIMARY KEY,
            run_type TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL DEFAULT 'created',
            provider TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            base_url TEXT NOT NULL DEFAULT '',
            input_count INTEGER NOT NULL DEFAULT 0,
            output_count INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            event_id TEXT PRIMARY KEY,
            occurred_at TEXT NOT NULL,
            actor_type TEXT NOT NULL DEFAULT 'system',
            actor_id TEXT,
            event_type TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS review_items (
            item_id TEXT PRIMARY KEY,
            record_id TEXT NOT NULL,
            pdf_id TEXT,
            stage TEXT NOT NULL DEFAULT 'title_abstract',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (record_id) REFERENCES records(record_id) ON DELETE CASCADE,
            FOREIGN KEY (pdf_id) REFERENCES pdfs(pdf_id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS decisions (
            decision_id TEXT PRIMARY KEY,
            review_item_id TEXT NOT NULL,
            actor_type TEXT NOT NULL DEFAULT 'human',
            reviewer_id TEXT,
            decision TEXT NOT NULL,
            rationale TEXT NOT NULL DEFAULT '',
            confidence TEXT,
            exclusion_reason_id TEXT,
            provider TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            prompt_hash TEXT NOT NULL DEFAULT '',
            text_hash TEXT NOT NULL DEFAULT '',
            cache_key TEXT NOT NULL DEFAULT '',
            automation_run_id TEXT,
            created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (review_item_id) REFERENCES review_items(item_id) ON DELETE CASCADE,
            FOREIGN KEY (reviewer_id) REFERENCES reviewers(reviewer_id),
            FOREIGN KEY (exclusion_reason_id) REFERENCES exclusion_reasons(reason_id),
            FOREIGN KEY (automation_run_id) REFERENCES automation_runs(run_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS extraction_forms (
            form_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS extraction_fields (
            field_id TEXT PRIMARY KEY,
            form_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            field_label TEXT NOT NULL,
            field_type TEXT NOT NULL DEFAULT 'text',
            sort_order INTEGER NOT NULL DEFAULT 0,
            required INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (form_id) REFERENCES extraction_forms(form_id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS extraction_values (
            value_id TEXT PRIMARY KEY,
            record_id TEXT NOT NULL,
            field_id TEXT NOT NULL,
            reviewer_id TEXT,
            value_text TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (record_id) REFERENCES records(record_id) ON DELETE CASCADE,
            FOREIGN KEY (field_id) REFERENCES extraction_fields(field_id) ON DELETE CASCADE,
            FOREIGN KEY (reviewer_id) REFERENCES reviewers(reviewer_id)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_records_doi ON records(doi)",
        "CREATE INDEX IF NOT EXISTS idx_record_sources_source ON record_sources(source_id)",
        "CREATE INDEX IF NOT EXISTS idx_pdfs_record ON pdfs(record_id)",
        "CREATE INDEX IF NOT EXISTS idx_review_items_record ON review_items(record_id)",
        "CREATE INDEX IF NOT EXISTS idx_review_items_pdf ON review_items(pdf_id)",
        "CREATE INDEX IF NOT EXISTS idx_review_items_status ON review_items(stage, status)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_review_items_unique_scope ON review_items(record_id, stage, COALESCE(pdf_id, ''))",
        "CREATE INDEX IF NOT EXISTS idx_decisions_item_created ON decisions(review_item_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_decisions_actor ON decisions(actor_type, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_audit_events_type ON audit_events(event_type, occurred_at)",
    ]


def _seed_workspace_meta(conn: sqlite3.Connection, metadata: dict[str, Any]) -> None:
    now = utc_now()
    for key, value in (
        ("workspace_id", metadata.get("workspace_id", "")),
        ("name", metadata.get("name", "")),
        ("schema_version", str(SCHEMA_VERSION)),
        ("app_version", metadata.get("app_version", VERSION)),
        ("created_at", metadata.get("created_at", now)),
    ):
        conn.execute(
            """
            INSERT INTO workspace_meta(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, str(value), now),
        )


def _seed_default_reviewer(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO reviewers(
            reviewer_id, display_name, role, is_default, created_at, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (DEFAULT_REVIEWER_ID, "Local reviewer", "primary", 1, utc_now(), "{}"),
    )


def _seed_default_exclusion_reasons(conn: sqlite3.Connection) -> None:
    now = utc_now()
    for sort_order, (reason_id, label, description) in enumerate(DEFAULT_EXCLUSION_REASONS, start=1):
        conn.execute(
            """
            INSERT OR IGNORE INTO exclusion_reasons(
                reason_id, label, description, is_default, sort_order, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (reason_id, label, description, 1, sort_order, now),
        )


def _apply_review_queue_migrations(conn: sqlite3.Connection) -> None:
    review_columns = _table_columns(conn, "review_items")
    if "pdf_id" not in review_columns:
        conn.execute("ALTER TABLE review_items ADD COLUMN pdf_id TEXT")
    if "updated_at" not in review_columns:
        conn.execute("ALTER TABLE review_items ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")
        conn.execute(
            "UPDATE review_items SET updated_at = created_at WHERE updated_at = ''"
        )

    decision_columns = _table_columns(conn, "decisions")
    if decision_columns and "review_item_id" not in decision_columns:
        _rebuild_legacy_decisions_table(conn)
    else:
        _ensure_decisions_columns(conn, decision_columns)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_review_items_record ON review_items(record_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_review_items_pdf ON review_items(pdf_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_review_items_status ON review_items(stage, status)")
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_review_items_unique_scope
        ON review_items(record_id, stage, COALESCE(pdf_id, ''))
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_decisions_item_created ON decisions(review_item_id, created_at)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_decisions_actor ON decisions(actor_type, created_at)")


def _apply_record_origin_migration(conn: sqlite3.Connection) -> None:
    columns = _table_columns(conn, "records")
    if "record_origin" not in columns:
        conn.execute(
            """
            ALTER TABLE records
            ADD COLUMN record_origin TEXT NOT NULL DEFAULT 'imported_reference'
            """
        )
        columns = set(columns)
        columns.add("record_origin")

    select_columns = ["record_id", "record_origin", "metadata_json"]
    if "stable_record_id" in columns:
        select_columns.append("stable_record_id")

    rows = conn.execute(
        f"SELECT {', '.join(select_columns)} FROM records"
    ).fetchall()
    for row in rows:
        item = dict(row)
        current = _text(item.get("record_origin")).strip()
        try:
            origin = _normalize_record_origin(current)
        except WorkspaceError:
            origin = RECORD_ORIGIN_IMPORTED_REFERENCE
        if _has_pdf_only_legacy_marker(item):
            origin = RECORD_ORIGIN_PDF_ONLY
        if origin != current:
            conn.execute(
                "UPDATE records SET record_origin = ? WHERE record_id = ?",
                (origin, item["record_id"]),
            )


def _apply_dedup_migration(conn: sqlite3.Connection) -> None:
    record_columns = _table_columns(conn, "records")
    record_additions = {
        "is_active_for_screening": "INTEGER NOT NULL DEFAULT 1",
        "duplicate_of_record_id": "TEXT",
        "dedup_method": "TEXT NOT NULL DEFAULT ''",
        "dedup_score": "REAL",
    }
    for column, ddl in record_additions.items():
        if column not in record_columns:
            conn.execute(f"ALTER TABLE records ADD COLUMN {column} {ddl}")

    source_columns = _table_columns(conn, "record_sources")
    source_additions = {
        "dedup_status": "TEXT NOT NULL DEFAULT 'unique'",
        "duplicate_of_record_id": "TEXT",
        "dedup_method": "TEXT NOT NULL DEFAULT ''",
        "dedup_score": "REAL",
    }
    for column, ddl in source_additions.items():
        if column not in source_columns:
            conn.execute(f"ALTER TABLE record_sources ADD COLUMN {column} {ddl}")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_records_active ON records(is_active_for_screening, record_origin)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_records_duplicate_of ON records(duplicate_of_record_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_record_sources_dedup ON record_sources(dedup_status, duplicate_of_record_id)"
    )


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def _rebuild_legacy_decisions_table(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE decisions RENAME TO decisions_legacy_v1")
    _create_decisions_table(conn)
    legacy_columns = _table_columns(conn, "decisions_legacy_v1")
    rows = conn.execute("SELECT * FROM decisions_legacy_v1").fetchall()
    for row in rows:
        item_id = row["item_id"] if "item_id" in legacy_columns else ""
        reviewer_id = row["reviewer_id"] if "reviewer_id" in legacy_columns else DEFAULT_REVIEWER_ID
        decision = row["decision"] if "decision" in legacy_columns else DECISION_MAYBE
        exclusion_reason_id = row["exclusion_reason_id"] if "exclusion_reason_id" in legacy_columns else None
        rationale = row["rationale"] if "rationale" in legacy_columns else ""
        created_at = row["decided_at"] if "decided_at" in legacy_columns else utc_now()
        metadata_json = row["metadata_json"] if "metadata_json" in legacy_columns else "{}"
        conn.execute(
            """
            INSERT INTO decisions(
                decision_id, review_item_id, actor_type, reviewer_id, decision,
                rationale, confidence, exclusion_reason_id, provider, model,
                prompt_hash, text_hash, cache_key, automation_run_id,
                created_at, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["decision_id"] if "decision_id" in legacy_columns else uuid.uuid4().hex,
                item_id,
                ACTOR_HUMAN,
                reviewer_id,
                _normalize_decision(decision, actor_type=ACTOR_HUMAN),
                rationale,
                None,
                exclusion_reason_id,
                "",
                "",
                "",
                "",
                "",
                None,
                created_at or utc_now(),
                metadata_json or "{}",
            ),
        )
    conn.execute("DROP TABLE decisions_legacy_v1")


def _create_decisions_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS decisions (
            decision_id TEXT PRIMARY KEY,
            review_item_id TEXT NOT NULL,
            actor_type TEXT NOT NULL DEFAULT 'human',
            reviewer_id TEXT,
            decision TEXT NOT NULL,
            rationale TEXT NOT NULL DEFAULT '',
            confidence TEXT,
            exclusion_reason_id TEXT,
            provider TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            prompt_hash TEXT NOT NULL DEFAULT '',
            text_hash TEXT NOT NULL DEFAULT '',
            cache_key TEXT NOT NULL DEFAULT '',
            automation_run_id TEXT,
            created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (review_item_id) REFERENCES review_items(item_id) ON DELETE CASCADE,
            FOREIGN KEY (reviewer_id) REFERENCES reviewers(reviewer_id),
            FOREIGN KEY (exclusion_reason_id) REFERENCES exclusion_reasons(reason_id),
            FOREIGN KEY (automation_run_id) REFERENCES automation_runs(run_id)
        )
        """
    )


def _ensure_decisions_columns(conn: sqlite3.Connection, columns: set[str]) -> None:
    additions = {
        "actor_type": "TEXT NOT NULL DEFAULT 'human'",
        "reviewer_id": "TEXT",
        "rationale": "TEXT NOT NULL DEFAULT ''",
        "confidence": "TEXT",
        "exclusion_reason_id": "TEXT",
        "provider": "TEXT NOT NULL DEFAULT ''",
        "model": "TEXT NOT NULL DEFAULT ''",
        "prompt_hash": "TEXT NOT NULL DEFAULT ''",
        "text_hash": "TEXT NOT NULL DEFAULT ''",
        "cache_key": "TEXT NOT NULL DEFAULT ''",
        "automation_run_id": "TEXT",
        "created_at": "TEXT NOT NULL DEFAULT ''",
        "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
    }
    for column, ddl in additions.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE decisions ADD COLUMN {column} {ddl}")
    if "created_at" not in columns:
        conn.execute("UPDATE decisions SET created_at = ? WHERE created_at = ''", (utc_now(),))


def _create_review_item_row(
    conn: sqlite3.Connection,
    *,
    record_id: str,
    stage: str,
    pdf_id: str | None = None,
    created_at: str | None = None,
) -> str:
    record = _text(record_id).strip()
    if not record:
        raise WorkspaceError("record_id is required")
    stage_value = _normalize_stage(stage)
    pdf = _text(pdf_id).strip() or None
    now = created_at or utc_now()

    if pdf is None:
        existing = conn.execute(
            """
            SELECT item_id FROM review_items
            WHERE record_id = ? AND stage = ? AND pdf_id IS NULL
            """,
            (record, stage_value),
        ).fetchone()
    else:
        existing = conn.execute(
            """
            SELECT item_id FROM review_items
            WHERE record_id = ? AND stage = ? AND pdf_id = ?
            """,
            (record, stage_value, pdf),
        ).fetchone()
    if existing:
        return existing["item_id"]

    item_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO review_items(
            item_id, record_id, pdf_id, stage, status, created_at, updated_at, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (item_id, record, pdf, stage_value, REVIEW_STATUS_PENDING, now, now, "{}"),
    )
    return item_id


def _normalize_stage(stage: str | None) -> str:
    value = _text(stage).strip().lower().replace("-", "_").replace("/", "_").replace(" ", "_")
    aliases = {
        "": REVIEW_STAGE_TITLE_ABSTRACT,
        "title": REVIEW_STAGE_TITLE_ABSTRACT,
        "abstract": REVIEW_STAGE_TITLE_ABSTRACT,
        "title_abstract": REVIEW_STAGE_TITLE_ABSTRACT,
        "title__abstract": REVIEW_STAGE_TITLE_ABSTRACT,
        "titleabstract": REVIEW_STAGE_TITLE_ABSTRACT,
        "screening": REVIEW_STAGE_TITLE_ABSTRACT,
        "full": REVIEW_STAGE_FULL_TEXT,
        "full_text": REVIEW_STAGE_FULL_TEXT,
        "fulltext": REVIEW_STAGE_FULL_TEXT,
        "pdf": REVIEW_STAGE_FULL_TEXT,
    }
    normalized = aliases.get(value, value)
    if normalized not in REVIEW_STAGES:
        raise WorkspaceError("Unsupported review stage")
    return normalized


def _normalize_status_filter(status: str | None) -> str:
    value = _text(status).strip().lower()
    if value not in REVIEW_STATUSES:
        raise WorkspaceError("Unsupported review status")
    return value


def _normalize_decision(decision: str, *, actor_type: str) -> str:
    actor = _text(actor_type).strip().lower()
    if actor not in ACTOR_TYPES:
        raise WorkspaceError("Unsupported decision actor type")
    value = _text(decision).strip().lower().replace("-", " ").replace("_", " ")
    if not value:
        raise WorkspaceError("Decision is required")
    if "error" in value or "fail" in value:
        return DECISION_FAILED
    if "exclude" in value or value == "no":
        return DECISION_EXCLUDE
    if "include" in value or value == "yes":
        return DECISION_INCLUDE
    if "maybe" in value or "uncertain" in value:
        return DECISION_MAYBE
    if "flag" in value or "review" in value:
        return DECISION_FLAG
    if value in DECISIONS:
        return value
    raise WorkspaceError("Unsupported decision")


def _normalize_record_origin(origin: str | None) -> str:
    value = _text(origin).strip().lower().replace("-", "_").replace(" ", "_")
    if value not in RECORD_ORIGINS:
        raise WorkspaceError("Unsupported record origin")
    return value


def _has_pdf_only_legacy_marker(record: dict[str, Any]) -> bool:
    if _text(record.get("record_id")).startswith("pdf-"):
        return True
    if _text(record.get("stable_record_id")).startswith("pdf-"):
        return True

    metadata_text = _text(record.get("metadata_json")).strip()
    if not metadata_text:
        return False
    try:
        metadata = json.loads(metadata_text)
    except json.JSONDecodeError:
        return "workspace_pdf" in metadata_text
    return isinstance(metadata, dict) and metadata.get("source") == "workspace_pdf"


def _insert_decision_row(
    conn: sqlite3.Connection,
    *,
    review_item_id: str,
    actor_type: str,
    reviewer_id: str | None,
    decision: str,
    rationale: str,
    confidence: Any,
    exclusion_reason_id: str | None,
    provider: str,
    model: str,
    prompt_hash: str,
    text_hash: str,
    cache_key: str,
    automation_run_id: str | None,
    metadata: dict[str, Any],
) -> str:
    actor = _text(actor_type).strip().lower()
    if actor not in ACTOR_TYPES:
        raise WorkspaceError("Unsupported decision actor type")
    if actor == ACTOR_HUMAN and not _text(reviewer_id).strip():
        raise WorkspaceError("reviewer_id is required for human decisions")

    decision_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO decisions(
            decision_id, review_item_id, actor_type, reviewer_id, decision,
            rationale, confidence, exclusion_reason_id, provider, model,
            prompt_hash, text_hash, cache_key, automation_run_id,
            created_at, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            decision_id,
            review_item_id,
            actor,
            _text(reviewer_id).strip() or None,
            decision,
            _bounded_text(rationale),
            _confidence_text(confidence),
            _text(exclusion_reason_id).strip() or None,
            _bounded_text(provider, limit=200),
            _bounded_text(model, limit=200),
            _bounded_text(prompt_hash, limit=128),
            _bounded_text(text_hash, limit=128),
            _bounded_text(cache_key, limit=256),
            _text(automation_run_id).strip() or None,
            utc_now(),
            json_dumps(_sanitize_metadata(metadata)),
        ),
    )
    return decision_id


def _latest_decision_row(
    conn: sqlite3.Connection,
    review_item_id: str,
    *,
    actor_type: str | None = None,
) -> sqlite3.Row | None:
    params: list[Any] = [_text(review_item_id).strip()]
    actor_sql = ""
    if actor_type:
        actor_sql = "AND actor_type = ?"
        params.append(actor_type)
    return conn.execute(
        f"""
        SELECT
            decision_id, review_item_id, actor_type, reviewer_id, decision,
            rationale, confidence, exclusion_reason_id, provider, model,
            prompt_hash, text_hash, cache_key, automation_run_id,
            created_at, metadata_json
        FROM decisions
        WHERE review_item_id = ?
        {actor_sql}
        ORDER BY created_at DESC, rowid DESC
        LIMIT 1
        """,
        params,
    ).fetchone()


def _decision_public(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "decision_id": row["decision_id"],
        "review_item_id": row["review_item_id"],
        "actor_type": row["actor_type"],
        "reviewer_id": row["reviewer_id"],
        "decision": row["decision"],
        "rationale": row["rationale"],
        "confidence": row["confidence"],
        "exclusion_reason_id": row["exclusion_reason_id"],
        "provider": row["provider"],
        "model": row["model"],
        "prompt_hash": row["prompt_hash"],
        "text_hash": row["text_hash"],
        "cache_key": row["cache_key"],
        "automation_run_id": row["automation_run_id"],
        "created_at": row["created_at"],
    }


def _recalculate_review_item_status(conn: sqlite3.Connection, review_item_id: str) -> str:
    item = conn.execute(
        "SELECT item_id FROM review_items WHERE item_id = ?",
        (_text(review_item_id).strip(),),
    ).fetchone()
    if not item:
        raise WorkspaceError("Review item not found")

    human = _latest_decision_row(conn, item["item_id"], actor_type=ACTOR_HUMAN)
    if human:
        status = {
            DECISION_INCLUDE: REVIEW_STATUS_INCLUDED,
            DECISION_EXCLUDE: REVIEW_STATUS_EXCLUDED,
            DECISION_MAYBE: REVIEW_STATUS_MAYBE,
        }.get(human["decision"], REVIEW_STATUS_MAYBE)
    else:
        latest = _latest_decision_row(conn, item["item_id"])
        if not latest:
            status = REVIEW_STATUS_PENDING
        elif latest["decision"] == DECISION_FAILED:
            status = REVIEW_STATUS_FAILED
        elif latest["actor_type"] == ACTOR_AI:
            status = REVIEW_STATUS_SUGGESTED
        else:
            status = REVIEW_STATUS_PENDING

    conn.execute(
        "UPDATE review_items SET status = ?, updated_at = ? WHERE item_id = ?",
        (status, utc_now(), item["item_id"]),
    )
    return status


def _get_review_item_status(conn: sqlite3.Connection, review_item_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT
            ri.item_id, ri.record_id, ri.pdf_id, ri.stage, ri.status,
            ri.created_at, ri.updated_at,
            r.title, r.authors, r.year, r.journal, r.doi,
            r.record_origin, r.is_active_for_screening,
            r.duplicate_of_record_id, r.dedup_method, r.dedup_score,
            p.relative_path AS pdf_relative_path,
            p.display_name AS pdf_display_name
        FROM review_items ri
        JOIN records r ON r.record_id = ri.record_id
        LEFT JOIN pdfs p ON p.pdf_id = ri.pdf_id
        WHERE ri.item_id = ?
        """,
        (_text(review_item_id).strip(),),
    ).fetchone()
    if not row:
        raise WorkspaceError("Review item not found")
    item = dict(row)
    item["latest_ai_suggestion"] = _decision_public(
        _latest_decision_row(conn, item["item_id"], actor_type=ACTOR_AI)
    )
    item["latest_human_decision"] = _decision_public(
        _latest_decision_row(conn, item["item_id"], actor_type=ACTOR_HUMAN)
    )
    item["latest_decision"] = _decision_public(_latest_decision_row(conn, item["item_id"]))
    return item


def _stable_record_id(record: dict[str, Any]) -> str:
    doi = _text(record.get("doi")).strip().lower()
    if doi:
        return f"doi:{doi}"
    title = _text(record.get("title")).strip().lower()
    year = _text(record.get("year")).strip()
    if title:
        digest = hashlib.sha256(f"{title}|{year}".encode("utf-8")).hexdigest()[:16]
        return f"title:{digest}"
    return _text(record.get("record_id")).strip()


def _available_count(value: Any, explanation: str) -> dict[str, Any]:
    return {
        "value": int(value or 0),
        "status": "available",
        "explanation": explanation,
    }


def _not_available_count(explanation: str) -> dict[str, Any]:
    return {
        "value": None,
        "status": "not_available",
        "explanation": explanation,
    }


def _stage_status_counts(conn: sqlite3.Connection) -> dict[str, dict[str, int]]:
    counts = {
        stage: {status: 0 for status in REVIEW_STATUSES}
        for stage in REVIEW_STAGES
    }
    for row in conn.execute(
        """
        SELECT ri.stage, ri.status, COUNT(*) AS count
        FROM review_items ri
        JOIN records r ON r.record_id = ri.record_id
        WHERE r.is_active_for_screening = 1
        GROUP BY ri.stage, ri.status
        """
    ).fetchall():
        stage = _normalize_stage(row["stage"])
        status = _normalize_status_filter(row["status"])
        counts.setdefault(stage, {item: 0 for item in REVIEW_STATUSES})[status] = row["count"]
    return counts


def _human_stage_decision_counts(conn: sqlite3.Connection) -> dict[str, dict[str, int]]:
    counts = {
        stage: {decision: 0 for decision in (DECISION_INCLUDE, DECISION_EXCLUDE, DECISION_MAYBE)}
        for stage in REVIEW_STAGES
    }
    for row in conn.execute(
        """
        SELECT ri.stage, d.decision, COUNT(*) AS count
        FROM decisions d
        JOIN review_items ri ON ri.item_id = d.review_item_id
        JOIN records r ON r.record_id = ri.record_id
        WHERE r.is_active_for_screening = 1
          AND d.actor_type = ?
          AND NOT EXISTS (
              SELECT 1
              FROM decisions newer
              WHERE newer.review_item_id = d.review_item_id
                AND newer.actor_type = ?
                AND (
                    newer.created_at > d.created_at
                    OR (newer.created_at = d.created_at AND newer.rowid > d.rowid)
                )
          )
        GROUP BY ri.stage, d.decision
        """,
        (ACTOR_HUMAN, ACTOR_HUMAN),
    ).fetchall():
        stage = _normalize_stage(row["stage"])
        decision = _normalize_decision(row["decision"], actor_type=ACTOR_HUMAN)
        counts.setdefault(stage, {item: 0 for item in (DECISION_INCLUDE, DECISION_EXCLUDE, DECISION_MAYBE)})[decision] = row["count"]
    return counts


def _reviewer_exists(conn: sqlite3.Connection, reviewer_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM reviewers WHERE reviewer_id = ?",
        (_text(reviewer_id).strip(),),
    ).fetchone() is not None


def _exclusion_reason_exists(conn: sqlite3.Connection, reason_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM exclusion_reasons WHERE reason_id = ?",
        (_text(reason_id).strip(),),
    ).fetchone() is not None


def _insert_audit_event(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    entity_type: str,
    entity_id: str,
    summary: str,
    metadata: dict[str, Any],
    actor_type: str = "system",
    actor_id: str | None = None,
) -> str:
    event_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO audit_events(
            event_id, occurred_at, actor_type, actor_id, event_type,
            entity_type, entity_id, summary, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            utc_now(),
            actor_type,
            actor_id,
            event_type,
            entity_type,
            entity_id,
            summary,
            json_dumps(_sanitize_metadata(metadata)),
        ),
    )
    return event_id


def _ensure_subfolders(root: Path) -> None:
    for folder in WORKSPACE_SUBDIRS:
        (root / folder).mkdir(parents=True, exist_ok=True)


def _reject_unrelated_existing_contents(root: Path) -> None:
    allowed = set(WORKSPACE_SUBDIRS) | {DATABASE_NAME, WORKSPACE_JSON}
    for child in root.iterdir():
        if child.name not in allowed:
            raise WorkspaceError("Workspace folder must be empty or already be a workspace")


def _load_workspace_json(root: Path) -> dict[str, Any]:
    try:
        data = json.loads((root / WORKSPACE_JSON).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkspaceNotFound("workspace.json not found") from exc
    except json.JSONDecodeError as exc:
        raise WorkspaceError("workspace.json is invalid") from exc
    if not isinstance(data, dict):
        raise WorkspaceError("workspace.json must contain an object")
    return data


def _write_workspace_json(root: Path, metadata: dict[str, Any]) -> None:
    safe = _sanitize_metadata(metadata)
    (root / WORKSPACE_JSON).write_text(
        json.dumps(safe, indent=2, sort_keys=True, ensure_ascii=True),
        encoding="utf-8",
    )


def _validate_relative_path(relative_path: str) -> str:
    if not relative_path or str(relative_path).strip() == "":
        raise UnsafeWorkspacePath("Relative path is required")
    pure = PurePosixPath(str(relative_path).replace("\\", "/"))
    if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
        raise UnsafeWorkspacePath("Invalid relative path")
    return pure.as_posix()


def _validate_filename(filename: str, *, allowed_exts: Iterable[str] | None = None) -> str:
    original = (filename or "").strip()
    if not original:
        raise UnsafeWorkspacePath("Filename is required")
    if "/" in original or "\\" in original or original in {".", ".."}:
        raise UnsafeWorkspacePath("Invalid filename")
    safe = re.sub(r"[^A-Za-z0-9._ -]+", "_", original).strip()
    if not safe or safe in {".", ".."}:
        raise UnsafeWorkspacePath("Invalid filename")
    if allowed_exts is not None and Path(safe).suffix.lower() not in {ext.lower() for ext in allowed_exts}:
        raise WorkspaceError("Unsupported file extension")
    return safe


def _record_id(record: dict[str, Any]) -> str:
    existing = _text(record.get("record_id")).strip()
    if existing:
        return existing
    source = "|".join(
        _text(record.get(key)).strip().lower()
        for key in ("title", "doi", "year")
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]


def _dedup_doi(value: Any) -> str:
    return _text(value).strip().lower()


def _dedup_title(value: Any) -> str:
    return re.sub(r"[^\w\s]", "", _text(value).lower()).strip()


def _dedup_title_score(left: str, right: str) -> float:
    try:
        from thefuzz import fuzz

        return float(fuzz.token_sort_ratio(left, right))
    except ImportError:
        from difflib import SequenceMatcher

        return SequenceMatcher(None, " ".join(sorted(left.split())), " ".join(sorted(right.split()))).ratio() * 100


def _dedup_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    raw_imported = conn.execute(
        """
        SELECT COALESCE(SUM(record_count), 0) AS count
        FROM sources
        WHERE source_type = 'reference_import'
        """
    ).fetchone()["count"]
    active_imported = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM records
        WHERE record_origin = ? AND is_active_for_screening = 1
        """,
        (RECORD_ORIGIN_IMPORTED_REFERENCE,),
    ).fetchone()["count"]
    duplicate_sources = conn.execute(
        """
        SELECT dedup_method, COUNT(*) AS count
        FROM record_sources
        WHERE dedup_status = ?
        GROUP BY dedup_method
        """,
        (DEDUP_STATUS_DUPLICATE,),
    ).fetchall()
    duplicate_by_method = {
        _text(row["dedup_method"]) or DEDUP_METHOD_OTHER: row["count"]
        for row in duplicate_sources
    }
    inactive_records = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM records
        WHERE record_origin = ?
          AND is_active_for_screening = 0
          AND duplicate_of_record_id IS NOT NULL
        """,
        (RECORD_ORIGIN_IMPORTED_REFERENCE,),
    ).fetchone()["count"]
    duplicate_record_sources = sum(duplicate_by_method.values())
    return {
        "total_before": int(raw_imported or 0),
        "removed_doi": int(duplicate_by_method.get(DEDUP_METHOD_DOI, 0)),
        "removed_fuzzy": int(duplicate_by_method.get(DEDUP_METHOD_FUZZY_TITLE, 0)),
        "removed_other": int(duplicate_by_method.get(DEDUP_METHOD_OTHER, 0)),
        "total_after": int(active_imported),
        "raw_imported_records": int(raw_imported or 0),
        "active_unique_records": int(active_imported),
        "duplicate_records": int(duplicate_record_sources),
        "duplicate_source_records": int(duplicate_record_sources),
        "inactive_duplicate_records": int(inactive_records),
        "duplicate_records_by_method": duplicate_by_method,
    }


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _bounded_text(value: Any, *, limit: int = 4000) -> str:
    text = _text(value)
    if len(text) <= limit:
        return text
    return text[:limit]


def _confidence_text(value: Any) -> str | None:
    text = _text(value).strip()
    return text[:64] if text else None


def _is_sensitive_metadata_key(key_text: str) -> bool:
    lowered = key_text.lower()
    if lowered in SAFE_METADATA_KEYS or any(lowered.endswith(suffix) for suffix in SAFE_HASH_KEY_SUFFIXES):
        return False
    return any(part in lowered for part in SECRET_KEY_PARTS)


def _sanitize_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        clean = {}
        for key, nested in value.items():
            key_text = str(key)
            if _is_sensitive_metadata_key(key_text):
                continue
            clean[key_text] = _sanitize_metadata(nested)
        return clean
    if isinstance(value, list):
        return [_sanitize_metadata(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_metadata(item) for item in value]
    return value
