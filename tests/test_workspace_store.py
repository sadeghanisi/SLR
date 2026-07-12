import json
import sqlite3
from pathlib import Path

import pytest

import workspace_store


def _table_names(root: Path) -> set[str]:
    with workspace_store.workspace_connection(root) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    return {row["name"] for row in rows}


def _count(root: Path, table: str) -> int:
    with workspace_store.workspace_connection(root) as conn:
        return conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]


def _automation_runs(root: Path) -> dict[str, dict]:
    with workspace_store.workspace_connection(root) as conn:
        rows = conn.execute(
            """
            SELECT run_id, started_at, finished_at, status, input_count,
                   output_count, metadata_json
            FROM automation_runs
            ORDER BY run_id
            """
        ).fetchall()
    return {row["run_id"]: dict(row) for row in rows}


def _assert_connection_closed(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        conn.execute("SELECT 1")


def test_connect_returns_caller_owned_raw_connection(tmp_path):
    root = tmp_path / "workspace"
    workspace_store.create_workspace(root)

    conn = workspace_store.connect(root)

    assert isinstance(conn, sqlite3.Connection)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("SELECT 1").fetchone()[0] == 1
    conn.close()
    _assert_connection_closed(conn)


def test_workspace_connection_closes_after_success_and_commits(tmp_path):
    root = tmp_path / "workspace"
    workspace_store.create_workspace(root)

    with workspace_store.workspace_connection(root) as conn:
        conn.execute(
            "INSERT INTO workspace_meta(key, value, updated_at) VALUES (?, ?, ?)",
            ("lifecycle_commit", "committed", workspace_store.utc_now()),
        )

    _assert_connection_closed(conn)
    with sqlite3.connect(root / workspace_store.DATABASE_NAME) as check:
        value = check.execute(
            "SELECT value FROM workspace_meta WHERE key = ?",
            ("lifecycle_commit",),
        ).fetchone()[0]
    assert value == "committed"


def test_workspace_connection_closes_after_exception_and_rolls_back(tmp_path):
    root = tmp_path / "workspace"
    workspace_store.create_workspace(root)

    with pytest.raises(RuntimeError, match="force rollback"):
        with workspace_store.workspace_connection(root) as conn:
            conn.execute(
                "INSERT INTO workspace_meta(key, value, updated_at) VALUES (?, ?, ?)",
                ("lifecycle_rollback", "not committed", workspace_store.utc_now()),
            )
            raise RuntimeError("force rollback")

    _assert_connection_closed(conn)
    with sqlite3.connect(root / workspace_store.DATABASE_NAME) as check:
        row = check.execute(
            "SELECT value FROM workspace_meta WHERE key = ?",
            ("lifecycle_rollback",),
        ).fetchone()
    assert row is None


def test_workspace_connection_enables_foreign_keys(tmp_path):
    root = tmp_path / "workspace"
    workspace_store.create_workspace(root)

    with workspace_store.workspace_connection(root) as conn:
        enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]

    assert enabled == 1
    _assert_connection_closed(conn)


def test_workspace_database_can_be_renamed_moved_and_deleted_after_operations(tmp_path):
    root = tmp_path / "workspace"
    workspace_store.create_workspace(root)
    workspace_store.get_workspace_summary(root)

    database = root / workspace_store.DATABASE_NAME
    renamed = root / "renamed.sqlite3"
    moved = tmp_path / "moved.sqlite3"
    database.rename(renamed)
    renamed.replace(moved)
    moved.unlink()

    assert not moved.exists()


def test_workspace_creation_creates_db_json_and_subfolders(tmp_path):
    root = tmp_path / "review_workspace"

    handle = workspace_store.create_workspace(root, name="Review Workspace")

    assert handle.root == root.resolve()
    assert (root / workspace_store.DATABASE_NAME).is_file()
    assert (root / workspace_store.WORKSPACE_JSON).is_file()
    for folder in workspace_store.WORKSPACE_SUBDIRS:
        assert (root / folder).is_dir()

    tables = _table_names(root)
    assert {
        "workspace_meta",
        "reviewers",
        "sources",
        "records",
        "record_sources",
        "pdfs",
        "exclusion_reasons",
        "automation_runs",
        "audit_events",
        "schema_migrations",
        "review_items",
        "decisions",
        "extraction_forms",
        "extraction_fields",
        "extraction_values",
    }.issubset(tables)


def test_open_workspace_validates_schema_and_migrations_are_idempotent(tmp_path):
    not_workspace = tmp_path / "not_workspace"
    not_workspace.mkdir()
    with pytest.raises(workspace_store.WorkspaceNotFound):
        workspace_store.open_workspace(not_workspace)

    root = tmp_path / "workspace"
    created = workspace_store.create_workspace(root)
    workspace_store.migrate(root)
    workspace_store.migrate(root)
    opened = workspace_store.open_workspace(root)

    assert opened.workspace_id == created.workspace_id
    assert _count(root, "schema_migrations") == workspace_store.SCHEMA_VERSION


def test_reconcile_stale_automation_runs_is_idempotent_and_preserves_workspace_data(
    tmp_path,
):
    root = tmp_path / "workspace"
    workspace_store.create_workspace(root)
    source = tmp_path / "refs.ris"
    source.write_text("TY  - JOUR\nTI  - Safe Study\nER  -\n", encoding="utf-8")
    workspace_store.persist_reference_import(
        root,
        source,
        [{"record_id": "rec-1", "title": "Safe Study", "abstract": "Harmless"}],
        original_filename="refs.ris",
    )
    pdf = root / "pdfs" / "partial.pdf"
    pdf.write_bytes(b"%PDF-1.4 partial\n")
    workspace_store.register_pdf(root, "pdfs/partial.pdf", original_filename="partial.pdf")
    item = workspace_store.get_review_queue(root)[0]
    workspace_store.add_ai_suggestion(
        root,
        record_id="rec-1",
        stage=workspace_store.REVIEW_STAGE_TITLE_ABSTRACT,
        decision="include",
        rationale="Safe suggestion",
    )
    workspace_store.add_human_decision(
        root,
        review_item_id=item["item_id"],
        reviewer_id=workspace_store.DEFAULT_REVIEWER_ID,
        decision="include",
        rationale="Human decision",
    )

    partial_files = {
        root / "exports" / "partial.csv": b"partial export",
        root / "cache" / "partial.cache": b"partial cache",
        root / "audit" / "partial.jsonl": b'{"safe":"partial"}\n',
    }
    for path, contents in partial_files.items():
        path.write_bytes(contents)

    stale_ids = {
        workspace_store.create_automation_run(
            root,
            run_id="stale-a",
            run_type="full_text_processing",
            input_count=3,
            metadata={"output_folder": "exports/partial"},
        ),
        workspace_store.create_automation_run(
            root,
            run_id="stale-b",
            run_type="full_text_processing",
        ),
    }
    live_id = workspace_store.create_automation_run(
        root,
        run_id="live",
        run_type="full_text_processing",
    )
    terminal_ids = {}
    for status in ("completed", "failed", "interrupted", "created", "cancelled", "stopped"):
        run_id = workspace_store.create_automation_run(
            root,
            run_id=f"terminal-{status}",
            run_type="full_text_processing",
        )
        workspace_store.finish_automation_run(
            root,
            run_id,
            status=status,
            output_count=1,
            metadata={"safe_status": status},
        )
        terminal_ids[status] = run_id
    with workspace_store.workspace_connection(root) as conn:
        conn.execute(
            "UPDATE automation_runs SET output_count = 1 WHERE run_id = ?",
            ("stale-a",),
        )

    terminal_before = {
        run_id: _automation_runs(root)[run_id]
        for run_id in terminal_ids.values()
    }
    preserved_counts = {
        table: _count(root, table)
        for table in (
            "sources", "records", "record_sources", "pdfs", "review_items",
            "decisions", "exclusion_reasons", "audit_events",
        )
    }
    prisma_before = workspace_store.get_prisma_ready_counts(root)

    changed = workspace_store.reconcile_stale_automation_runs(
        root,
        live_run_ids={live_id},
    )
    first = _automation_runs(root)

    assert changed == 2
    assert {first[run_id]["status"] for run_id in stale_ids} == {"interrupted"}
    assert all(first[run_id]["finished_at"] for run_id in stale_ids)
    assert first["stale-a"]["output_count"] == 1
    assert json.loads(first["stale-a"]["metadata_json"]) == {
        "output_folder": "exports/partial"
    }
    assert first[live_id]["status"] == "running"
    assert first[live_id]["finished_at"] is None
    assert {
        run_id: first[run_id]
        for run_id in terminal_ids.values()
    } == terminal_before

    changed_again = workspace_store.reconcile_stale_automation_runs(
        root,
        live_run_ids={live_id},
    )
    assert changed_again == 0
    assert _automation_runs(root) == first
    assert {
        table: _count(root, table)
        for table in preserved_counts
    } == preserved_counts
    assert workspace_store.get_prisma_ready_counts(root) == prisma_before
    assert {path: path.read_bytes() for path in partial_files} == partial_files


def test_reconcile_stale_automation_runs_is_noop_for_fresh_workspace(tmp_path):
    root = tmp_path / "workspace"
    workspace_store.create_workspace(root)
    audit_count = _count(root, "audit_events")

    assert workspace_store.reconcile_stale_automation_runs(root) == 0
    assert _count(root, "automation_runs") == 0
    assert _count(root, "audit_events") == audit_count


def test_default_reviewer_and_exclusion_reasons_exist(tmp_path):
    root = tmp_path / "workspace"
    workspace_store.create_workspace(root)
    workspace_store.migrate(root)
    workspace_store.migrate(root)

    with workspace_store.workspace_connection(root) as conn:
        reviewers = conn.execute(
            "SELECT reviewer_id FROM reviewers WHERE is_default = 1"
        ).fetchall()
        reason_count = conn.execute(
            "SELECT COUNT(*) AS count FROM exclusion_reasons WHERE is_default = 1"
        ).fetchone()["count"]
        total_reason_count = conn.execute(
            "SELECT COUNT(*) AS count FROM exclusion_reasons"
        ).fetchone()["count"]

    assert [row["reviewer_id"] for row in reviewers] == [workspace_store.DEFAULT_REVIEWER_ID]
    assert reason_count == len(workspace_store.DEFAULT_EXCLUSION_REASONS)
    assert total_reason_count == len(workspace_store.DEFAULT_EXCLUSION_REASONS)


def test_workspace_path_safety_rejects_traversal_and_roots(tmp_path):
    root = tmp_path / "workspace"
    workspace_store.create_workspace(root)

    with pytest.raises(workspace_store.UnsafeWorkspacePath):
        workspace_store.resolve_workspace_relative_path(root, "../outside.pdf", subdir="pdfs")

    with pytest.raises(workspace_store.UnsafeWorkspacePath):
        workspace_store.resolve_workspace_relative_path(root, "/absolute.pdf", subdir="pdfs")

    with pytest.raises(workspace_store.UnsafeWorkspacePath):
        workspace_store.validate_workspace_root(Path(tmp_path.anchor))


def test_reference_import_persists_sources_records_and_links_idempotently(tmp_path):
    root = tmp_path / "workspace"
    workspace_store.create_workspace(root)
    import_file = tmp_path / "refs.ris"
    import_file.write_text("TY  - JOUR\nTI  - Test\nER  -\n", encoding="utf-8")
    records = [
        {
            "record_id": "rec-1",
            "title": "First paper",
            "abstract": "Abstract one",
            "authors": "A. Author",
            "year": "2024",
            "journal": "Journal",
            "doi": "10.1/one",
            "keywords": "alpha",
        },
        {
            "record_id": "rec-2",
            "title": "Second paper",
            "abstract": "Abstract two",
            "authors": "B. Author",
            "year": "2025",
            "journal": "Journal",
            "doi": "10.1/two",
            "keywords": "beta",
        },
    ]

    first = workspace_store.persist_reference_import(
        root,
        import_file,
        records,
        original_filename="Database Export.ris",
    )
    second = workspace_store.persist_reference_import(
        root,
        import_file,
        records,
        original_filename="Database Export.ris",
    )

    assert first["source_id"] != second["source_id"]
    assert _count(root, "sources") == 2
    assert _count(root, "records") == 2
    assert _count(root, "record_sources") == 4
    assert _count(root, "review_items") == 2
    with workspace_store.workspace_connection(root) as conn:
        origins = {
            row["record_origin"]
            for row in conn.execute("SELECT record_origin FROM records").fetchall()
        }
    assert origins == {workspace_store.RECORD_ORIGIN_IMPORTED_REFERENCE}
    copied = workspace_store.resolve_workspace_relative_path(root, first["relative_path"], must_exist=True)
    assert copied.is_file()


def test_workspace_dedup_persists_doi_fuzzy_state_and_active_queue(tmp_path):
    root = tmp_path / "workspace"
    workspace_store.create_workspace(root)
    import_file = tmp_path / "refs.csv"
    import_file.write_text("title,doi\nplaceholder,\n", encoding="utf-8")
    records = [
        {
            "record_id": "rec-doi-1",
            "title": "Machine learning review in health",
            "abstract": "A",
            "doi": "10.1000/dup",
        },
        {
            "record_id": "rec-doi-2",
            "title": "Different database title for the same DOI",
            "abstract": "B",
            "doi": "10.1000/DUP",
        },
        {
            "record_id": "rec-fuzzy-1",
            "title": "Deep learning for screening records",
            "abstract": "C",
        },
        {
            "record_id": "rec-fuzzy-2",
            "title": "Deep-learning for record screening",
            "abstract": "D",
        },
    ]
    workspace_store.persist_reference_import(root, import_file, records, original_filename="refs.csv")

    result = workspace_store.apply_reference_deduplication(root, fuzzy_threshold=80)
    reopened = workspace_store.open_workspace(root)
    summary = reopened.public_summary()["counts"]
    queue = workspace_store.get_review_queue(root)

    assert result["stats"]["total_before"] == 4
    assert result["stats"]["total_after"] == 2
    assert result["stats"]["removed_doi"] == 1
    assert result["stats"]["removed_fuzzy"] == 1
    assert summary["raw_imported_records"] == 4
    assert summary["active_unique_records"] == 2
    assert summary["duplicate_records"] == 2
    assert summary["active_records_by_origin"][workspace_store.RECORD_ORIGIN_IMPORTED_REFERENCE] == 2
    assert len(queue) == 2
    assert {item["record_id"] for item in queue} == {"rec-doi-1", "rec-fuzzy-1"}

    with workspace_store.workspace_connection(root) as conn:
        duplicate_records = {
            row["record_id"]: dict(row)
            for row in conn.execute(
                """
                SELECT record_id, is_active_for_screening, duplicate_of_record_id,
                       dedup_method, dedup_score
                FROM records
                WHERE is_active_for_screening = 0
                """
            ).fetchall()
        }
        source_evidence = [
            dict(row)
            for row in conn.execute(
                """
                SELECT record_id, dedup_status, duplicate_of_record_id,
                       dedup_method, dedup_score, raw_json
                FROM record_sources
                ORDER BY source_record_index
                """
            ).fetchall()
        ]

    assert duplicate_records["rec-doi-2"]["duplicate_of_record_id"] == "rec-doi-1"
    assert duplicate_records["rec-doi-2"]["dedup_method"] == workspace_store.DEDUP_METHOD_DOI
    assert duplicate_records["rec-fuzzy-2"]["duplicate_of_record_id"] == "rec-fuzzy-1"
    assert duplicate_records["rec-fuzzy-2"]["dedup_method"] == workspace_store.DEDUP_METHOD_FUZZY_TITLE
    assert float(duplicate_records["rec-fuzzy-2"]["dedup_score"]) >= 80
    assert len(source_evidence) == 4
    assert {row["dedup_method"] for row in source_evidence if row["dedup_status"] == "duplicate"} == {
        workspace_store.DEDUP_METHOD_DOI,
        workspace_store.DEDUP_METHOD_FUZZY_TITLE,
    }
    assert all(row["raw_json"] for row in source_evidence)


def test_pdf_metadata_persists_duplicate_display_basenames_as_distinct_files(tmp_path):
    root = tmp_path / "workspace"
    workspace_store.create_workspace(root)

    registered = []
    for payload in (b"%PDF-1.4 one\n", b"%PDF-1.4 two\n"):
        stored_name = workspace_store.unique_stored_filename("Paper.pdf")
        pdf_path = root / "pdfs" / stored_name
        pdf_path.write_bytes(payload)
        registered.append(
            workspace_store.register_pdf(
                root,
                f"pdfs/{stored_name}",
                original_filename="Paper.pdf",
                display_name="Paper.pdf",
            )
        )

    rows = workspace_store.list_pdf_metadata(root)

    assert len(rows) == 2
    assert rows[0]["display_name"] == "Paper.pdf"
    assert rows[1]["display_name"] == "Paper.pdf"
    assert rows[0]["relative_path"] != rows[1]["relative_path"]
    assert all(row["sha256"] for row in rows)
    assert {item["pdf_id"] for item in registered} == {row["pdf_id"] for row in rows}


def test_pdf_only_record_origin_and_provenance_counts(tmp_path):
    root = tmp_path / "workspace"
    workspace_store.create_workspace(root)
    pdf_name = workspace_store.unique_stored_filename("Paper.pdf")
    (root / "pdfs" / pdf_name).write_bytes(b"%PDF-1.4\n")
    pdf = workspace_store.register_pdf(root, f"pdfs/{pdf_name}", original_filename="Paper.pdf")

    record_id = workspace_store.ensure_record_for_pdf(root, pdf["pdf_id"])

    with workspace_store.workspace_connection(root) as conn:
        row = conn.execute(
            "SELECT record_origin, metadata_json FROM records WHERE record_id = ?",
            (record_id,),
        ).fetchone()
        source_links = conn.execute(
            "SELECT COUNT(*) AS count FROM record_sources WHERE record_id = ?",
            (record_id,),
        ).fetchone()["count"]
    summary = workspace_store.get_workspace_summary(root)

    assert record_id.startswith("pdf-")
    assert row["record_origin"] == workspace_store.RECORD_ORIGIN_PDF_ONLY
    assert json.loads(row["metadata_json"])["source"] == "workspace_pdf"
    assert source_links == 0
    assert summary["counts"]["records"] == 1
    assert summary["counts"]["records_by_origin"] == {
        workspace_store.RECORD_ORIGIN_IMPORTED_REFERENCE: 0,
        workspace_store.RECORD_ORIGIN_MANUAL: 0,
        workspace_store.RECORD_ORIGIN_PDF_ONLY: 1,
    }


def test_deleting_pdf_only_pdf_hides_orphaned_review_state(tmp_path):
    root = tmp_path / "workspace"
    workspace_store.create_workspace(root)
    pdf_name = workspace_store.unique_stored_filename("Paper.pdf")
    (root / "pdfs" / pdf_name).write_bytes(b"%PDF-1.4\n")
    pdf = workspace_store.register_pdf(root, f"pdfs/{pdf_name}", original_filename="Paper.pdf")
    record_id = workspace_store.ensure_record_for_pdf(root, pdf["pdf_id"])
    item = workspace_store.create_review_item(root, record_id, "full_text", pdf_id=pdf["pdf_id"])
    workspace_store.add_ai_suggestion(
        root,
        record_id=record_id,
        pdf_id=pdf["pdf_id"],
        stage="full_text",
        decision="Likely Include",
    )

    assert workspace_store.get_review_queue(root)[0]["item_id"] == item["item_id"]

    workspace_store.delete_pdf(root, pdf["relative_path"])

    assert workspace_store.get_review_queue(root) == []
    with workspace_store.workspace_connection(root) as conn:
        record = conn.execute(
            "SELECT is_active_for_screening FROM records WHERE record_id = ?",
            (record_id,),
        ).fetchone()
        decisions = conn.execute("SELECT COUNT(*) AS count FROM decisions").fetchone()["count"]

    assert record["is_active_for_screening"] == 0
    assert decisions == 1


def test_record_origin_migration_backfills_legacy_pdf_records(tmp_path):
    root = tmp_path / "legacy_workspace"
    root.mkdir()
    with sqlite3.connect(root / workspace_store.DATABASE_NAME) as conn:
        conn.execute(
            """
            CREATE TABLE records (
                record_id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                abstract TEXT NOT NULL DEFAULT '',
                authors TEXT NOT NULL DEFAULT '',
                year TEXT NOT NULL DEFAULT '',
                journal TEXT NOT NULL DEFAULT '',
                doi TEXT NOT NULL DEFAULT '',
                keywords TEXT NOT NULL DEFAULT '',
                source_file TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO records(
                record_id, title, abstract, authors, year, journal, doi,
                keywords, source_file, created_at, updated_at, metadata_json
            )
            VALUES (?, ?, '', '', '', '', '', '', '', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', ?)
            """,
            [
                ("pdf-legacy-id", "PDF ID marker", "{}"),
                ("legacy-json-marker", "PDF metadata marker", json.dumps({"source": "workspace_pdf"})),
                ("imported-record", "Imported marker", "{}"),
            ],
        )

    workspace_store.migrate(root)
    workspace_store.migrate(root)
    opened = workspace_store.open_workspace(root)

    with workspace_store.workspace_connection(root) as conn:
        origins = {
            row["record_id"]: row["record_origin"]
            for row in conn.execute("SELECT record_id, record_origin FROM records").fetchall()
        }

    assert opened.schema_version == workspace_store.SCHEMA_VERSION
    assert _count(root, "schema_migrations") == workspace_store.SCHEMA_VERSION
    assert origins == {
        "pdf-legacy-id": workspace_store.RECORD_ORIGIN_PDF_ONLY,
        "legacy-json-marker": workspace_store.RECORD_ORIGIN_PDF_ONLY,
        "imported-record": workspace_store.RECORD_ORIGIN_IMPORTED_REFERENCE,
    }


def test_workspace_summary_survives_open(tmp_path):
    root = tmp_path / "workspace"
    workspace_store.create_workspace(root)
    import_file = tmp_path / "refs.ris"
    import_file.write_text("TY  - JOUR\nTI  - Test\nER  -\n", encoding="utf-8")
    workspace_store.persist_reference_import(
        root,
        import_file,
        [{"record_id": "rec-1", "title": "First paper"}],
        original_filename="refs.ris",
    )
    pdf_name = workspace_store.unique_stored_filename("Paper.pdf")
    (root / "pdfs" / pdf_name).write_bytes(b"%PDF-1.4\n")
    workspace_store.register_pdf(root, f"pdfs/{pdf_name}", original_filename="Paper.pdf")

    reopened = workspace_store.open_workspace(root)
    summary = reopened.public_summary()

    assert summary["counts"]["sources"] == 1
    assert summary["counts"]["records"] == 1
    assert summary["counts"]["pdfs"] == 1
    assert summary["counts"]["records_by_origin"][workspace_store.RECORD_ORIGIN_IMPORTED_REFERENCE] == 1


def test_no_api_keys_are_stored_in_workspace_db(tmp_path):
    root = tmp_path / "workspace"
    workspace_store.create_workspace(root)

    workspace_store.write_audit_event(
        root,
        event_type="test_event",
        entity_type="workspace",
        entity_id="workspace",
        summary="secret scrub check",
        metadata={
            "api_key": "sk-secret-value",
            "screening_prompt": "full prompt should not be stored",
            "full_text": "full paper text should not be stored",
            "nested": {"token": "secret-token", "paper_text": "nested paper text", "ok": "kept"},
        },
    )

    with sqlite3.connect(root / workspace_store.DATABASE_NAME) as conn:
        dump = "\n".join(conn.iterdump())

    assert "sk-secret-value" not in dump
    assert "secret-token" not in dump
    assert "api_key" not in dump
    assert "full prompt should not be stored" not in dump
    assert "full paper text should not be stored" not in dump
    assert "nested paper text" not in dump


def _workspace_with_record(tmp_path):
    root = tmp_path / "workspace"
    workspace_store.create_workspace(root)
    import_file = tmp_path / "refs.ris"
    import_file.write_text("TY  - JOUR\nTI  - Review Study\nER  -\n", encoding="utf-8")
    workspace_store.persist_reference_import(
        root,
        import_file,
        [{"record_id": "rec-1", "title": "Review Study", "abstract": "Short abstract"}],
        original_filename="refs.ris",
    )
    return root


def test_ai_suggestion_is_suggested_until_human_decision(tmp_path):
    root = _workspace_with_record(tmp_path)

    queue = workspace_store.get_review_queue(root)
    assert len(queue) == 1
    assert queue[0]["status"] == "pending"

    suggested = workspace_store.add_ai_suggestion(
        root,
        record_id="rec-1",
        stage="title_abstract",
        decision="Likely Include",
        rationale="Matches the criteria",
        confidence="High",
        provider="TestProvider",
        model="test-model",
        prompt_hash="prompt-hash",
        text_hash="text-hash",
        cache_key="cache-key",
    )

    assert suggested["status"] == "suggested"
    assert suggested["latest_ai_suggestion"]["decision"] == "include"
    assert suggested["latest_human_decision"] is None

    final = workspace_store.add_human_decision(
        root,
        review_item_id=suggested["item_id"],
        reviewer_id=workspace_store.DEFAULT_REVIEWER_ID,
        decision="include",
        rationale="Human agrees",
    )

    assert final["status"] == "included"
    assert final["latest_human_decision"]["decision"] == "include"

    after_rerun = workspace_store.add_ai_suggestion(
        root,
        record_id="rec-1",
        stage="title_abstract",
        decision="Likely Exclude",
        rationale="Different AI run",
    )
    assert after_rerun["status"] == "included"

    with workspace_store.workspace_connection(root) as conn:
        events = conn.execute(
            "SELECT event_type FROM audit_events WHERE event_type = 'human_decision_added'"
        ).fetchall()
    assert len(events) == 1


def test_full_text_exclude_requires_reason_and_accept_override(tmp_path):
    root = _workspace_with_record(tmp_path)
    title_item = workspace_store.get_review_queue(root)[0]
    workspace_store.add_ai_suggestion(
        root,
        record_id="rec-1",
        stage="title_abstract",
        decision="Likely Include",
        rationale="AI include",
    )

    accepted = workspace_store.accept_ai_suggestion(
        root,
        review_item_id=title_item["item_id"],
        reviewer_id=workspace_store.DEFAULT_REVIEWER_ID,
    )
    assert accepted["status"] == "included"

    overridden = workspace_store.override_decision(
        root,
        review_item_id=title_item["item_id"],
        reviewer_id=workspace_store.DEFAULT_REVIEWER_ID,
        decision="maybe",
        rationale="Needs another look",
    )
    assert overridden["status"] == "maybe"
    assert overridden["latest_ai_suggestion"]["decision"] == "include"

    pdf_name = workspace_store.unique_stored_filename("Paper.pdf")
    (root / "pdfs" / pdf_name).write_bytes(b"%PDF-1.4\n")
    pdf = workspace_store.register_pdf(root, f"pdfs/{pdf_name}", original_filename="Paper.pdf")
    record_id = workspace_store.ensure_record_for_pdf(root, pdf["pdf_id"])
    full_text_item = workspace_store.create_review_item(root, record_id, "full_text", pdf_id=pdf["pdf_id"])

    with pytest.raises(workspace_store.WorkspaceError):
        workspace_store.add_human_decision(
            root,
            review_item_id=full_text_item["item_id"],
            reviewer_id=workspace_store.DEFAULT_REVIEWER_ID,
            decision="exclude",
            rationale="Wrong scope",
        )

    excluded = workspace_store.add_human_decision(
        root,
        review_item_id=full_text_item["item_id"],
        reviewer_id=workspace_store.DEFAULT_REVIEWER_ID,
        decision="exclude",
        rationale="Wrong scope",
        exclusion_reason_id=workspace_store.DEFAULT_EXCLUSION_REASONS[0][0],
    )
    assert excluded["status"] == "excluded"


def test_review_decisions_do_not_store_secrets_full_prompts_or_full_text(tmp_path):
    root = _workspace_with_record(tmp_path)

    workspace_store.add_ai_suggestion(
        root,
        record_id="rec-1",
        stage="title_abstract",
        decision="Likely Include",
        rationale="Short rationale",
        prompt_hash="safe-prompt-hash",
        text_hash="safe-text-hash",
        metadata={
            "api_key": "sk-secret-value",
            "full_prompt": "full prompt should not be stored",
            "full_text": "full paper text should not be stored",
            "prompt_hash": "metadata-prompt-hash",
            "nested": {"token": "secret-token", "ok": "kept"},
        },
    )

    with sqlite3.connect(root / workspace_store.DATABASE_NAME) as conn:
        dump = "\n".join(conn.iterdump())

    assert "sk-secret-value" not in dump
    assert "secret-token" not in dump
    assert "full prompt should not be stored" not in dump
    assert "full paper text should not be stored" not in dump
    assert "safe-prompt-hash" in dump
    assert "metadata-prompt-hash" in dump
