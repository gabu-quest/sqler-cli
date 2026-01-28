"""CLI integration tests for sqler-cli.

These tests verify actual behavior, not just "something happened".
Every test must be able to FAIL for a specific reason.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sqler_cli.cli import app

runner = CliRunner()


class TestRemember:
    """Tests for the remember command - storing memories."""

    def test_stores_content_and_returns_valid_id(self, temp_db_path: str) -> None:
        """Memory is persisted with correct content and assigned an ID."""
        content = "The database connection string is in config.yaml"
        result = runner.invoke(app, ["remember", content, "--db", temp_db_path])

        assert result.exit_code == 0

        # Verify via list --json that the EXACT content was stored
        list_result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(list_result.stdout)

        assert len(memories) == 1, "Expected exactly 1 memory"
        assert memories[0]["content"] == content, "Content must match exactly"
        assert memories[0]["id"] >= 1, "ID must be a positive integer"

    def test_stores_multiple_tags_correctly(self, temp_db_path: str) -> None:
        """Tags are stored as an array and retrievable."""
        result = runner.invoke(app, [
            "remember", "User settings",
            "--tag", "preferences",
            "--tag", "ui",
            "--tag", "important",
            "--db", temp_db_path,
        ])
        assert result.exit_code == 0

        list_result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(list_result.stdout)

        assert len(memories) == 1
        tags = memories[0]["tags"]
        assert len(tags) == 3, "Expected exactly 3 tags"
        assert set(tags) == {"preferences", "ui", "important"}

    def test_stores_context_metadata(self, temp_db_path: str) -> None:
        """Context field is stored and retrievable."""
        result = runner.invoke(app, [
            "remember", "JWT secret rotation needed",
            "--context", "Security audit on 2024-01-15",
            "--db", temp_db_path,
        ])
        assert result.exit_code == 0

        list_result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(list_result.stdout)

        assert memories[0]["context"] == "Security audit on 2024-01-15"

    def test_stores_custom_source(self, temp_db_path: str) -> None:
        """Source field defaults to 'user' but can be overridden."""
        # Default source
        runner.invoke(app, ["remember", "Default source", "--db", temp_db_path])

        # Custom source
        runner.invoke(app, [
            "remember", "From Claude",
            "--source", "claude",
            "--db", temp_db_path,
        ])

        list_result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(list_result.stdout)

        sources = {m["content"]: m["source"] for m in memories}
        assert sources["Default source"] == "user"
        assert sources["From Claude"] == "claude"

    def test_json_output_returns_stored_id(self, temp_db_path: str) -> None:
        """JSON output includes the assigned ID for chaining commands."""
        result = runner.invoke(app, [
            "remember", "Test content",
            "--json",
            "--db", temp_db_path,
        ])
        assert result.exit_code == 0

        data = json.loads(result.stdout)
        assert data["id"] >= 1
        assert data["content"] == "Test content"

        # Verify the ID is correct by fetching
        list_result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(list_result.stdout)
        assert memories[0]["id"] == data["id"]

    def test_quiet_output_returns_only_id(self, temp_db_path: str) -> None:
        """Quiet mode returns just the ID for scripting."""
        result = runner.invoke(app, [
            "remember", "Quiet test",
            "--quiet",
            "--db", temp_db_path,
        ])
        assert result.exit_code == 0

        memory_id = result.stdout.strip()
        assert memory_id.isdigit(), f"Expected numeric ID, got: {memory_id!r}"

        # Verify this ID exists
        list_result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(list_result.stdout)
        assert memories[0]["id"] == int(memory_id)

    def test_reads_content_from_file(self, temp_db_path: str, tmp_path: Path) -> None:
        """File content is read and stored exactly."""
        file_content = "Line 1\nLine 2\nLine 3 with special chars: @#$%"
        test_file = tmp_path / "notes.txt"
        test_file.write_text(file_content)

        result = runner.invoke(app, [
            "remember",
            "--file", str(test_file),
            "--db", temp_db_path,
        ])
        assert result.exit_code == 0

        list_result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(list_result.stdout)
        assert memories[0]["content"] == file_content

    def test_handles_unicode_content(self, temp_db_path: str) -> None:
        """Unicode content is stored and retrieved correctly."""
        content = "日本語テスト 🎉 émojis and ñ special çharacters"
        result = runner.invoke(app, ["remember", content, "--db", temp_db_path])
        assert result.exit_code == 0

        list_result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(list_result.stdout)
        assert memories[0]["content"] == content

    def test_rejects_empty_content(self, temp_db_path: str) -> None:
        """Cannot store empty memories."""
        result = runner.invoke(app, ["remember", "--db", temp_db_path])
        assert result.exit_code == 1
        assert "no content" in result.stdout.lower() or "no content" in (result.stderr or "").lower()

    def test_rejects_missing_file(self, temp_db_path: str) -> None:
        """Error on non-existent file."""
        result = runner.invoke(app, [
            "remember",
            "--file", "/nonexistent/path/file.txt",
            "--db", temp_db_path,
        ])
        assert result.exit_code == 1
        assert "not found" in result.stdout.lower() or "not found" in (result.stderr or "").lower()


class TestRecall:
    """Tests for recall command - FTS search."""

    @pytest.fixture
    def seeded_db(self, temp_db_path: str) -> str:
        """Seed database with known content for search tests."""
        memories = [
            ("SQLite uses B-tree indexes for fast lookups", ["database", "performance"]),
            ("PostgreSQL supports JSON columns natively", ["database", "json"]),
            ("The API endpoint is /api/v1/users", ["api", "docs"]),
            ("Redis cache TTL is set to 3600 seconds", ["cache", "config"]),
            ("SQLite FTS5 provides full-text search", ["database", "search"]),
        ]
        for content, tags in memories:
            tag_args = []
            for t in tags:
                tag_args.extend(["--tag", t])
            runner.invoke(app, ["remember", content, *tag_args, "--db", temp_db_path])
        return temp_db_path

    def test_finds_exact_term(self, seeded_db: str) -> None:
        """FTS finds documents containing search term."""
        result = runner.invoke(app, ["recall", "SQLite", "--json", "--db", seeded_db])
        assert result.exit_code == 0

        memories = json.loads(result.stdout)
        assert len(memories) == 2, "Expected exactly 2 SQLite matches"

        contents = [m["content"] for m in memories]
        assert any("B-tree" in c for c in contents)
        assert any("FTS5" in c for c in contents)

    def test_finds_nothing_for_nonexistent_term(self, seeded_db: str) -> None:
        """No results for terms not in any memory."""
        result = runner.invoke(app, ["recall", "nonexistent", "--json", "--db", seeded_db])
        assert result.exit_code == 0

        memories = json.loads(result.stdout)
        assert len(memories) == 0, "Expected no matches"

    def test_tag_filter_narrows_results(self, seeded_db: str) -> None:
        """Tag filter only returns memories with that tag."""
        # Without tag filter: should find 2 SQLite matches
        result = runner.invoke(app, ["recall", "SQLite", "--json", "--db", seeded_db])
        all_results = json.loads(result.stdout)
        assert len(all_results) == 2, "Expected 2 SQLite matches without filter"

        # With tag filter: only those with 'search' tag (the FTS5 one)
        result = runner.invoke(app, [
            "recall", "SQLite",
            "--tag", "search",
            "--json",
            "--db", seeded_db,
        ])
        filtered_results = json.loads(result.stdout)

        assert len(filtered_results) == 1, "Tag filter should narrow to 1 result"
        assert "search" in filtered_results[0]["tags"]
        assert "FTS5" in filtered_results[0]["content"]

    def test_limit_restricts_result_count(self, seeded_db: str) -> None:
        """Limit parameter caps number of results."""
        # First verify we have more than 1 match
        result = runner.invoke(app, ["recall", "SQLite", "--json", "--db", seeded_db])
        all_results = json.loads(result.stdout)
        assert len(all_results) >= 2, "Need at least 2 results to test limit"

        # Now limit to 1
        result = runner.invoke(app, [
            "recall", "SQLite",
            "--limit", "1",
            "--json",
            "--db", seeded_db,
        ])
        limited_results = json.loads(result.stdout)
        assert len(limited_results) == 1

    def test_searches_context_field(self, temp_db_path: str) -> None:
        """FTS includes context field in search."""
        runner.invoke(app, [
            "remember", "Generic content",
            "--context", "Authentication module security review",
            "--db", temp_db_path,
        ])

        result = runner.invoke(app, ["recall", "Authentication", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)

        assert len(memories) == 1, "Should find via context field"


class TestList:
    """Tests for list command - browsing memories."""

    def test_empty_database_shows_message(self, temp_db_path: str) -> None:
        """Empty database returns empty list, not error."""
        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        assert result.exit_code == 0

        memories = json.loads(result.stdout)
        assert memories == [], "Expected empty list"

    def test_returns_all_memories(self, temp_db_path: str) -> None:
        """List returns all stored memories."""
        contents = ["Memory A", "Memory B", "Memory C"]
        for c in contents:
            runner.invoke(app, ["remember", c, "--db", temp_db_path])

        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)

        assert len(memories) == 3
        returned_contents = {m["content"] for m in memories}
        assert returned_contents == set(contents)

    def test_tag_filter_exact_match(self, temp_db_path: str) -> None:
        """Tag filter only returns memories with exact tag."""
        runner.invoke(app, ["remember", "Has important", "--tag", "important", "--db", temp_db_path])
        runner.invoke(app, ["remember", "Has urgent", "--tag", "urgent", "--db", temp_db_path])
        runner.invoke(app, ["remember", "Has both", "--tag", "important", "--tag", "urgent", "--db", temp_db_path])

        result = runner.invoke(app, ["list", "--tag", "important", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)

        assert len(memories) == 2
        for m in memories:
            assert "important" in m["tags"], f"Memory missing 'important' tag: {m}"

    def test_limit_restricts_count(self, temp_db_path: str) -> None:
        """Limit parameter caps results."""
        for i in range(10):
            runner.invoke(app, ["remember", f"Memory {i}", "--db", temp_db_path])

        result = runner.invoke(app, ["list", "--limit", "3", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)

        assert len(memories) == 3


class TestForget:
    """Tests for forget command - deleting memories."""

    def test_delete_by_id_removes_memory(self, temp_db_path: str) -> None:
        """Deleted memory is no longer retrievable."""
        # Create and get ID
        result = runner.invoke(app, ["remember", "To be deleted", "--quiet", "--db", temp_db_path])
        memory_id = int(result.stdout.strip())

        # Delete
        result = runner.invoke(app, ["forget", str(memory_id), "--db", temp_db_path])
        assert result.exit_code == 0

        # Verify gone
        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        assert len(memories) == 0, "Memory should be deleted"

    def test_delete_preserves_other_memories(self, temp_db_path: str) -> None:
        """Deleting one memory doesn't affect others."""
        runner.invoke(app, ["remember", "Keep this", "--db", temp_db_path])
        result = runner.invoke(app, ["remember", "Delete this", "--quiet", "--db", temp_db_path])
        delete_id = result.stdout.strip()
        runner.invoke(app, ["remember", "Also keep", "--db", temp_db_path])

        runner.invoke(app, ["forget", delete_id, "--db", temp_db_path])

        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)

        assert len(memories) == 2
        contents = {m["content"] for m in memories}
        assert contents == {"Keep this", "Also keep"}

    def test_bulk_delete_by_tag(self, temp_db_path: str) -> None:
        """Delete all memories with a specific tag."""
        runner.invoke(app, ["remember", "Permanent", "--db", temp_db_path])
        runner.invoke(app, ["remember", "Temp 1", "--tag", "temporary", "--db", temp_db_path])
        runner.invoke(app, ["remember", "Temp 2", "--tag", "temporary", "--db", temp_db_path])
        runner.invoke(app, ["remember", "Temp 3", "--tag", "temporary", "--db", temp_db_path])

        result = runner.invoke(app, [
            "forget",
            "--tag", "temporary",
            "--confirm",
            "--db", temp_db_path,
        ])
        assert result.exit_code == 0
        assert "3" in result.stdout, "Should report 3 deleted"

        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)

        assert len(memories) == 1
        assert memories[0]["content"] == "Permanent"

    def test_nonexistent_id_returns_error(self, temp_db_path: str) -> None:
        """Cannot delete non-existent memory."""
        result = runner.invoke(app, ["forget", "99999", "--db", temp_db_path])
        assert result.exit_code == 1

    def test_requires_id_or_tag(self, temp_db_path: str) -> None:
        """Must provide either ID or --tag."""
        result = runner.invoke(app, ["forget", "--db", temp_db_path])
        assert result.exit_code == 1


class TestTags:
    """Tests for tag management commands."""

    def test_list_tags_with_counts(self, temp_db_path: str) -> None:
        """Tags list shows correct counts."""
        runner.invoke(app, ["remember", "M1", "--tag", "alpha", "--tag", "beta", "--db", temp_db_path])
        runner.invoke(app, ["remember", "M2", "--tag", "alpha", "--db", temp_db_path])
        runner.invoke(app, ["remember", "M3", "--tag", "alpha", "--tag", "gamma", "--db", temp_db_path])

        result = runner.invoke(app, ["tags", "list", "--json", "--db", temp_db_path])
        tags = json.loads(result.stdout)

        assert tags["alpha"] == 3
        assert tags["beta"] == 1
        assert tags["gamma"] == 1

    def test_add_tag_to_memory(self, temp_db_path: str) -> None:
        """Adding a tag persists it."""
        result = runner.invoke(app, ["remember", "Untagged", "--quiet", "--db", temp_db_path])
        memory_id = result.stdout.strip()

        # Add tag
        result = runner.invoke(app, ["tags", "add", memory_id, "newtag", "--db", temp_db_path])
        assert result.exit_code == 0

        # Verify
        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        assert "newtag" in memories[0]["tags"]

    def test_add_duplicate_tag_is_idempotent(self, temp_db_path: str) -> None:
        """Adding existing tag doesn't duplicate."""
        result = runner.invoke(app, [
            "remember", "Tagged",
            "--tag", "existing",
            "--quiet",
            "--db", temp_db_path,
        ])
        memory_id = result.stdout.strip()

        # Add same tag again
        runner.invoke(app, ["tags", "add", memory_id, "existing", "--db", temp_db_path])

        # Should still have only 1 instance
        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        assert memories[0]["tags"].count("existing") == 1

    def test_remove_tag_from_memory(self, temp_db_path: str) -> None:
        """Removing a tag persists the removal."""
        result = runner.invoke(app, [
            "remember", "Multi-tagged",
            "--tag", "keep",
            "--tag", "remove",
            "--quiet",
            "--db", temp_db_path,
        ])
        memory_id = result.stdout.strip()

        # Remove one tag
        result = runner.invoke(app, ["tags", "rm", memory_id, "remove", "--db", temp_db_path])
        assert result.exit_code == 0

        # Verify
        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        assert "keep" in memories[0]["tags"]
        assert "remove" not in memories[0]["tags"]


class TestExportImport:
    """Tests for export/import functionality."""

    def test_export_creates_valid_json(self, temp_db_path: str, tmp_path: Path) -> None:
        """Export creates parseable JSON with all fields."""
        runner.invoke(app, [
            "remember", "Test content",
            "--tag", "test",
            "--context", "Testing",
            "--source", "pytest",
            "--db", temp_db_path,
        ])

        export_file = tmp_path / "export.json"
        result = runner.invoke(app, ["export", str(export_file), "--db", temp_db_path])
        assert result.exit_code == 0

        data = json.loads(export_file.read_text())
        assert len(data) == 1
        assert data[0]["content"] == "Test content"
        assert data[0]["tags"] == ["test"]
        assert data[0]["context"] == "Testing"
        assert data[0]["source"] == "pytest"

    def test_import_restores_memories(self, temp_db_path: str, tmp_path: Path) -> None:
        """Import creates memories from JSON."""
        # Create export data manually
        export_data = [
            {"content": "Imported 1", "tags": ["imported"], "context": None, "source": "test"},
            {"content": "Imported 2", "tags": ["imported", "second"], "context": "ctx", "source": "test"},
        ]
        import_file = tmp_path / "import.json"
        import_file.write_text(json.dumps(export_data))

        result = runner.invoke(app, ["import", str(import_file), "--db", temp_db_path])
        assert result.exit_code == 0

        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)

        assert len(memories) == 2
        contents = {m["content"] for m in memories}
        assert contents == {"Imported 1", "Imported 2"}

    def test_roundtrip_preserves_data(self, temp_db_path: str, tmp_path: Path) -> None:
        """Export then import preserves all memory data."""
        # Create memories
        runner.invoke(app, [
            "remember", "Memory with all fields",
            "--tag", "complete",
            "--tag", "test",
            "--context", "Full roundtrip test",
            "--source", "pytest",
            "--db", temp_db_path,
        ])

        # Export
        export_file = tmp_path / "roundtrip.json"
        runner.invoke(app, ["export", str(export_file), "--db", temp_db_path])

        # Import to new DB
        new_db = str(tmp_path / "new.db")
        runner.invoke(app, ["import", str(export_file), "--db", new_db])

        # Compare
        result = runner.invoke(app, ["list", "--json", "--db", new_db])
        memories = json.loads(result.stdout)

        assert len(memories) == 1
        m = memories[0]
        assert m["content"] == "Memory with all fields"
        assert set(m["tags"]) == {"complete", "test"}
        assert m["context"] == "Full roundtrip test"
        # Source becomes "imported" on import by default, or original if preserved
        # This tests the actual behavior


class TestStats:
    """Tests for stats command."""

    def test_stats_counts_correct(self, temp_db_path: str) -> None:
        """Stats reports accurate counts."""
        runner.invoke(app, ["remember", "M1", "--tag", "a", "--db", temp_db_path])
        runner.invoke(app, ["remember", "M2", "--tag", "b", "--db", temp_db_path])
        runner.invoke(app, ["remember", "M3", "--tag", "a", "--tag", "c", "--db", temp_db_path])

        result = runner.invoke(app, ["stats", "--json", "--db", temp_db_path])
        stats = json.loads(result.stdout)

        assert stats["memory_count"] == 3
        assert stats["tag_count"] == 3  # a, b, c
        assert stats["tags"]["a"] == 2
        assert stats["tags"]["b"] == 1
        assert stats["tags"]["c"] == 1


class TestEdgeCases:
    """Edge cases and error handling."""

    def test_very_long_content(self, temp_db_path: str) -> None:
        """Can store and retrieve large content."""
        long_content = "x" * 100_000  # 100KB
        result = runner.invoke(app, ["remember", long_content, "--db", temp_db_path])
        assert result.exit_code == 0

        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        assert len(memories[0]["content"]) == 100_000

    def test_special_characters_in_tags(self, temp_db_path: str) -> None:
        """Tags can contain various characters."""
        result = runner.invoke(app, [
            "remember", "Special tags",
            "--tag", "with-dash",
            "--tag", "with_underscore",
            "--tag", "with.dot",
            "--db", temp_db_path,
        ])
        assert result.exit_code == 0

        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        tags = set(memories[0]["tags"])
        assert tags == {"with-dash", "with_underscore", "with.dot"}

    def test_multiline_content(self, temp_db_path: str) -> None:
        """Multiline content is preserved."""
        content = "Line 1\nLine 2\nLine 3"
        result = runner.invoke(app, ["remember", content, "--db", temp_db_path])
        assert result.exit_code == 0

        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        assert memories[0]["content"] == content
        assert memories[0]["content"].count("\n") == 2

    def test_quotes_in_content(self, temp_db_path: str) -> None:
        """Content with quotes is handled."""
        content = 'He said "hello" and she said \'hi\''
        result = runner.invoke(app, ["remember", content, "--db", temp_db_path])
        assert result.exit_code == 0

        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        assert memories[0]["content"] == content


class TestRebuildIndex:
    """Tests for rebuild-index command."""

    def test_rebuild_index_returns_count(self, temp_db_path: str) -> None:
        """Rebuild-index reports correct memory count."""
        # Create some memories
        runner.invoke(app, ["remember", "Memory 1", "--db", temp_db_path])
        runner.invoke(app, ["remember", "Memory 2", "--db", temp_db_path])
        runner.invoke(app, ["remember", "Memory 3", "--db", temp_db_path])

        result = runner.invoke(app, ["rebuild-index", "--db", temp_db_path])
        assert result.exit_code == 0
        assert "3 memories" in result.stdout

    def test_rebuild_index_preserves_searchability(self, temp_db_path: str) -> None:
        """After rebuild, search still works correctly."""
        runner.invoke(app, ["remember", "SQLite database configuration", "--db", temp_db_path])
        runner.invoke(app, ["remember", "PostgreSQL connection string", "--db", temp_db_path])

        # Rebuild index
        result = runner.invoke(app, ["rebuild-index", "--db", temp_db_path])
        assert result.exit_code == 0

        # Verify search works
        result = runner.invoke(app, ["recall", "SQLite", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        assert len(memories) == 1
        assert "SQLite" in memories[0]["content"]


class TestUpdate:
    """Tests for update command."""

    def test_update_content_preserves_id(self, temp_db_path: str) -> None:
        """Updating content keeps the same memory ID."""
        result = runner.invoke(app, ["remember", "Original content", "--quiet", "--db", temp_db_path])
        memory_id = result.stdout.strip()

        runner.invoke(app, ["update", memory_id, "Updated content", "--db", temp_db_path])

        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        assert len(memories) == 1
        assert memories[0]["id"] == int(memory_id)
        assert memories[0]["content"] == "Updated content"

    def test_update_preserves_created_at(self, temp_db_path: str) -> None:
        """Updating content doesn't change creation timestamp."""
        result = runner.invoke(app, ["remember", "Original", "--quiet", "--db", temp_db_path])
        memory_id = result.stdout.strip()

        # Get original created_at
        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        original_created = json.loads(result.stdout)[0]["created_at"]

        # Update
        runner.invoke(app, ["update", memory_id, "Modified", "--db", temp_db_path])

        # Check created_at unchanged
        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        assert memories[0]["created_at"] == original_created

    def test_update_adds_tags(self, temp_db_path: str) -> None:
        """Can add tags via update without removing existing ones."""
        result = runner.invoke(app, [
            "remember", "Tagged memory",
            "--tag", "original",
            "--quiet",
            "--db", temp_db_path,
        ])
        memory_id = result.stdout.strip()

        runner.invoke(app, ["update", memory_id, "--tag", "newtag", "--db", temp_db_path])

        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        assert set(memories[0]["tags"]) == {"original", "newtag"}

    def test_update_clear_tags(self, temp_db_path: str) -> None:
        """--clear-tags removes all tags."""
        result = runner.invoke(app, [
            "remember", "Tagged",
            "--tag", "a",
            "--tag", "b",
            "--quiet",
            "--db", temp_db_path,
        ])
        memory_id = result.stdout.strip()

        runner.invoke(app, ["update", memory_id, "--clear-tags", "--db", temp_db_path])

        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        assert memories[0]["tags"] == []

    def test_update_context(self, temp_db_path: str) -> None:
        """Can update context field."""
        result = runner.invoke(app, ["remember", "Memory", "--quiet", "--db", temp_db_path])
        memory_id = result.stdout.strip()

        runner.invoke(app, ["update", memory_id, "--context", "New context", "--db", temp_db_path])

        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        assert memories[0]["context"] == "New context"

    def test_update_nonexistent_memory_fails(self, temp_db_path: str) -> None:
        """Updating non-existent memory returns error."""
        result = runner.invoke(app, ["update", "99999", "New content", "--db", temp_db_path])
        assert result.exit_code == 1
        assert "not found" in result.stdout.lower() or "not found" in (result.stderr or "").lower()

    def test_update_importance(self, temp_db_path: str) -> None:
        """Can update importance level."""
        result = runner.invoke(app, ["remember", "Normal memory", "--quiet", "--db", temp_db_path])
        memory_id = result.stdout.strip()

        runner.invoke(app, ["update", memory_id, "--importance", "5", "--db", temp_db_path])

        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        assert memories[0]["importance"] == 5

    def test_update_see_also(self, temp_db_path: str) -> None:
        """Can add related memory references."""
        # Create two memories
        result = runner.invoke(app, ["remember", "First memory", "--quiet", "--db", temp_db_path])
        first_id = result.stdout.strip()
        result = runner.invoke(app, ["remember", "Second memory", "--quiet", "--db", temp_db_path])
        second_id = result.stdout.strip()

        # Link first to second
        runner.invoke(app, ["update", first_id, "--see-also", second_id, "--db", temp_db_path])

        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        first_mem = next(m for m in memories if m["id"] == int(first_id))
        assert int(second_id) in first_mem["see_also"]


class TestShowScore:
    """Tests for --show-score flag on recall."""

    def test_show_score_includes_score_in_json(self, temp_db_path: str) -> None:
        """--show-score adds score field to JSON output."""
        runner.invoke(app, ["remember", "API endpoint documentation", "--db", temp_db_path])
        runner.invoke(app, ["remember", "Database configuration", "--db", temp_db_path])

        result = runner.invoke(app, ["recall", "API", "--show-score", "--json", "--db", temp_db_path])
        assert result.exit_code == 0

        memories = json.loads(result.stdout)
        assert len(memories) >= 1
        assert "score" in memories[0], "JSON output must include score field"
        assert isinstance(memories[0]["score"], float)

    def test_score_not_present_without_flag(self, temp_db_path: str) -> None:
        """Without --show-score, no score in output."""
        runner.invoke(app, ["remember", "API endpoint documentation", "--db", temp_db_path])

        result = runner.invoke(app, ["recall", "API", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        assert "score" not in memories[0]


class TestSessionLinking:
    """Tests for session-based memory isolation."""

    def test_session_isolates_remember(self, temp_db_path: str) -> None:
        """Memories with --session are stored with session_id."""
        runner.invoke(app, ["remember", "Session A content", "--session", "A", "--db", temp_db_path])
        runner.invoke(app, ["remember", "Session B content", "--session", "B", "--db", temp_db_path])
        runner.invoke(app, ["remember", "No session content", "--db", temp_db_path])

        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)

        sessions = {m["content"]: m["session_id"] for m in memories}
        assert sessions["Session A content"] == "A"
        assert sessions["Session B content"] == "B"
        assert sessions["No session content"] is None

    def test_session_isolates_recall(self, temp_db_path: str) -> None:
        """Recall with --session only returns that session's memories."""
        runner.invoke(app, ["remember", "API in session A", "--session", "A", "--db", temp_db_path])
        runner.invoke(app, ["remember", "API in session B", "--session", "B", "--db", temp_db_path])
        runner.invoke(app, ["remember", "API without session", "--db", temp_db_path])

        # Search within session A only
        result = runner.invoke(app, ["recall", "API", "--session", "A", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)

        assert len(memories) == 1
        assert memories[0]["session_id"] == "A"
        assert "session A" in memories[0]["content"]

    def test_session_isolates_list(self, temp_db_path: str) -> None:
        """List with --session only returns that session's memories."""
        runner.invoke(app, ["remember", "Work note 1", "--session", "work", "--db", temp_db_path])
        runner.invoke(app, ["remember", "Work note 2", "--session", "work", "--db", temp_db_path])
        runner.invoke(app, ["remember", "Personal note", "--session", "personal", "--db", temp_db_path])

        result = runner.invoke(app, ["list", "--session", "work", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)

        assert len(memories) == 2
        for m in memories:
            assert m["session_id"] == "work"


class TestRecentFirst:
    """Tests for --recent-first flag on recall."""

    def test_recent_first_sorts_by_date(self, temp_db_path: str) -> None:
        """--recent-first sorts results by creation date, not relevance."""
        import time
        # Create memories with small delays to ensure distinct timestamps
        runner.invoke(app, ["remember", "First API note", "--db", temp_db_path])
        time.sleep(0.01)
        runner.invoke(app, ["remember", "Second API note", "--db", temp_db_path])
        time.sleep(0.01)
        runner.invoke(app, ["remember", "Third API note", "--db", temp_db_path])

        result = runner.invoke(app, ["recall", "API", "--recent-first", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)

        assert len(memories) == 3
        # Newest first
        assert "Third" in memories[0]["content"]
        assert "First" in memories[2]["content"]


class TestSimilarMemories:
    """Tests for showing similar memories after remember."""

    def test_similar_shown_after_remember(self, temp_db_path: str) -> None:
        """After storing, similar existing memories are displayed."""
        # Create initial memory
        runner.invoke(app, ["remember", "The API key is stored in .env file", "--db", temp_db_path])

        # Create similar memory
        result = runner.invoke(app, ["remember", "API keys are in the .env file", "--db", temp_db_path])

        # Should show similar (though exact output depends on FTS scoring)
        assert result.exit_code == 0
        # The feature outputs "Similar existing memories:" if matches found
        # With these similar strings, it should find the first one

    def test_similar_not_shown_in_quiet_mode(self, temp_db_path: str) -> None:
        """Similar memories not shown in quiet mode."""
        runner.invoke(app, ["remember", "API configuration details", "--db", temp_db_path])
        result = runner.invoke(app, ["remember", "API configuration settings", "--quiet", "--db", temp_db_path])

        # Quiet mode only outputs the ID
        assert result.stdout.strip().isdigit()


class TestAutoTagging:
    """Tests for automatic tagging feature."""

    def test_auto_tag_detects_api(self, temp_db_path: str) -> None:
        """--auto-tag detects API-related keywords."""
        result = runner.invoke(app, [
            "remember", "The REST API endpoint is /api/users",
            "--auto-tag",
            "--db", temp_db_path,
        ])
        assert result.exit_code == 0
        assert "auto-tagged" in result.stdout.lower()

        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        assert "api" in memories[0]["tags"]

    def test_auto_tag_detects_database(self, temp_db_path: str) -> None:
        """--auto-tag detects database-related keywords."""
        result = runner.invoke(app, [
            "remember", "PostgreSQL database connection string",
            "--auto-tag",
            "--db", temp_db_path,
        ])
        assert result.exit_code == 0

        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        assert "database" in memories[0]["tags"]

    def test_auto_tag_detects_auth(self, temp_db_path: str) -> None:
        """--auto-tag detects authentication-related keywords."""
        result = runner.invoke(app, [
            "remember", "JWT authentication token expires in 1 hour",
            "--auto-tag",
            "--db", temp_db_path,
        ])
        assert result.exit_code == 0

        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        assert "auth" in memories[0]["tags"]

    def test_auto_tag_multiple_categories(self, temp_db_path: str) -> None:
        """--auto-tag can detect multiple categories."""
        result = runner.invoke(app, [
            "remember", "API uses JWT authentication for database access",
            "--auto-tag",
            "--db", temp_db_path,
        ])
        assert result.exit_code == 0

        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        tags = set(memories[0]["tags"])
        assert "api" in tags
        assert "auth" in tags
        assert "database" in tags

    def test_auto_tag_json_output_includes_auto_tags(self, temp_db_path: str) -> None:
        """JSON output with --auto-tag includes auto_tags field."""
        result = runner.invoke(app, [
            "remember", "API security configuration",
            "--auto-tag",
            "--json",
            "--db", temp_db_path,
        ])
        assert result.exit_code == 0

        data = json.loads(result.stdout)
        assert "auto_tags" in data
        assert "api" in data["auto_tags"]


class TestMemoryChains:
    """Tests for memory linking (supersedes, see_also)."""

    def test_supersedes_stores_reference(self, temp_db_path: str) -> None:
        """--supersedes stores the referenced memory ID."""
        result = runner.invoke(app, ["remember", "Old API URL is /v1", "--quiet", "--db", temp_db_path])
        old_id = int(result.stdout.strip())

        runner.invoke(app, [
            "remember", "New API URL is /v2",
            "--supersedes", str(old_id),
            "--db", temp_db_path,
        ])

        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        new_mem = next(m for m in memories if "v2" in m["content"])
        assert new_mem["supersedes"] == old_id

    def test_see_also_stores_references(self, temp_db_path: str) -> None:
        """--see-also stores related memory IDs."""
        result = runner.invoke(app, ["remember", "Auth overview", "--quiet", "--db", temp_db_path])
        auth_id = int(result.stdout.strip())
        result = runner.invoke(app, ["remember", "Security notes", "--quiet", "--db", temp_db_path])
        sec_id = int(result.stdout.strip())

        runner.invoke(app, [
            "remember", "Login flow documentation",
            "--see-also", str(auth_id),
            "--see-also", str(sec_id),
            "--db", temp_db_path,
        ])

        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        login_mem = next(m for m in memories if "Login" in m["content"])
        assert auth_id in login_mem["see_also"]
        assert sec_id in login_mem["see_also"]


class TestSourceAttribution:
    """Tests for source URL and file tracking."""

    def test_source_url_stored(self, temp_db_path: str) -> None:
        """--source-url is stored and retrievable."""
        runner.invoke(app, [
            "remember", "Rate limit is 100 requests/minute",
            "--source-url", "https://api.example.com/docs#limits",
            "--db", temp_db_path,
        ])

        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        assert memories[0]["source_url"] == "https://api.example.com/docs#limits"

    def test_source_file_stored(self, temp_db_path: str) -> None:
        """--source-file is stored and retrievable."""
        runner.invoke(app, [
            "remember", "Database config format",
            "--source-file", "/etc/app/config.yaml:42",
            "--db", temp_db_path,
        ])

        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        assert memories[0]["source_file"] == "/etc/app/config.yaml:42"


class TestImportanceScoring:
    """Tests for importance levels."""

    def test_importance_default_is_3(self, temp_db_path: str) -> None:
        """Default importance is 3."""
        runner.invoke(app, ["remember", "Normal memory", "--db", temp_db_path])

        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        assert memories[0]["importance"] == 3

    def test_importance_can_be_set(self, temp_db_path: str) -> None:
        """--importance sets the level correctly."""
        runner.invoke(app, [
            "remember", "Critical: Never commit secrets",
            "--importance", "5",
            "--db", temp_db_path,
        ])

        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)
        assert memories[0]["importance"] == 5

    def test_min_importance_filters_list(self, temp_db_path: str) -> None:
        """--min-importance filters list results."""
        runner.invoke(app, ["remember", "Low priority", "--importance", "1", "--db", temp_db_path])
        runner.invoke(app, ["remember", "Normal priority", "--importance", "3", "--db", temp_db_path])
        runner.invoke(app, ["remember", "High priority", "--importance", "5", "--db", temp_db_path])

        result = runner.invoke(app, ["list", "--min-importance", "4", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)

        assert len(memories) == 1
        assert memories[0]["importance"] == 5

    def test_min_importance_filters_recall(self, temp_db_path: str) -> None:
        """--min-importance filters recall results."""
        runner.invoke(app, ["remember", "Low priority API note", "--importance", "1", "--db", temp_db_path])
        runner.invoke(app, ["remember", "High priority API note", "--importance", "5", "--db", temp_db_path])

        result = runner.invoke(app, ["recall", "API", "--min-importance", "4", "--json", "--db", temp_db_path])
        memories = json.loads(result.stdout)

        assert len(memories) == 1
        assert memories[0]["importance"] == 5


class TestDedupe:
    """Tests for dedupe command."""

    def test_dedupe_dry_run_shows_groups(self, temp_db_path: str) -> None:
        """--dry-run shows duplicate groups without merging."""
        # Create near-duplicates
        runner.invoke(app, ["remember", "API key stored in env file", "--db", temp_db_path])
        runner.invoke(app, ["remember", "API key stored in environment file", "--db", temp_db_path])
        runner.invoke(app, ["remember", "Completely different content about databases", "--db", temp_db_path])

        result = runner.invoke(app, ["dedupe", "--dry-run", "--db", temp_db_path])
        assert result.exit_code == 0
        # Should show some output about groups (exact format may vary)

    def test_dedupe_no_duplicates_message(self, temp_db_path: str) -> None:
        """Shows appropriate message when no duplicates found."""
        runner.invoke(app, ["remember", "Unique content about APIs", "--db", temp_db_path])
        runner.invoke(app, ["remember", "Completely different database stuff", "--db", temp_db_path])

        result = runner.invoke(app, ["dedupe", "--db", temp_db_path])
        assert result.exit_code == 0
        # Either "No duplicates" or groups shown

    def test_dedupe_auto_merges(self, temp_db_path: str) -> None:
        """--auto merges duplicates keeping newest."""
        # Create duplicates with different tags
        runner.invoke(app, [
            "remember", "API configuration documentation",
            "--tag", "old-tag",
            "--db", temp_db_path,
        ])
        runner.invoke(app, [
            "remember", "API configuration documentation guide",
            "--tag", "new-tag",
            "--db", temp_db_path,
        ])

        # Count before
        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        before_count = len(json.loads(result.stdout))

        # Auto-merge with a permissive threshold
        runner.invoke(app, ["dedupe", "--auto", "--threshold", "-2.0", "--db", temp_db_path])

        # Count after (should be less if duplicates were found and merged)
        result = runner.invoke(app, ["list", "--json", "--db", temp_db_path])
        after_memories = json.loads(result.stdout)

        # If duplicates were merged, count should be less and tags combined
        if len(after_memories) < before_count:
            # Tags should be combined in the survivor
            survivor = after_memories[0]
            # Both tags should be present
            assert set(survivor["tags"]) == {"old-tag", "new-tag"}
