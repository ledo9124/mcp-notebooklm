"""Unit tests for typed BA fixture loader helpers."""

from __future__ import annotations

import json
from pathlib import Path

from notebooklm_mcp.ba.fixtures import FixtureScenario, load_fixture_package, load_rerun_diff_fixture


def test_load_fixture_package_returns_seeded_clean_feature_maps() -> None:
    fixture = load_fixture_package(FixtureScenario.CLEAN_FEATURE, workspace_root=Path("."))

    assert fixture.manifest.scenario is FixtureScenario.CLEAN_FEATURE
    assert sorted(fixture.source_text_by_name) == ["api-contract", "glossary", "requirements"]
    assert fixture.note_text_by_name == {}
    assert "scenario-signals" in fixture.expected_text_by_name

    signals = json.loads(fixture.expected_text_by_name["scenario-signals"])
    assert signals["scenario"] == FixtureScenario.CLEAN_FEATURE.value
    assert signals["expected_readiness_decision"] == "READY_FOR_FE_AND_BE"
    assert signals["source_keys"] == ["api-contract", "glossary", "requirements"]
    assert signals["note_keys"] == []
    assert "POST /customers" in fixture.source_text_by_name["api-contract"]


def test_load_fixture_package_keeps_note_and_before_after_maps_isolated() -> None:
    note_fixture = load_fixture_package(FixtureScenario.NOTE_CLARIFICATION, workspace_root=Path("."))
    rerun_fixture = load_fixture_package(FixtureScenario.RERUN_DIFF, workspace_root=Path("."))

    assert sorted(note_fixture.note_text_by_name) == ["clarification-note"]
    assert note_fixture.before_text_by_name == {}
    assert note_fixture.after_text_by_name == {}
    assert sorted(rerun_fixture.before_text_by_name) == ["glossary", "requirements"]
    assert sorted(rerun_fixture.after_text_by_name) == ["glossary", "requirements"]
    assert sorted(rerun_fixture.expected_text_by_name) == ["changelog", "impacted-screens"]


def test_load_rerun_diff_fixture_returns_source_keyed_maps_and_expected_artifacts() -> None:
    fixture = load_rerun_diff_fixture(workspace_root=Path("."))

    assert fixture.manifest.scenario is FixtureScenario.RERUN_DIFF
    assert sorted(fixture.before_text_by_source) == ["glossary", "requirements"]
    assert sorted(fixture.after_text_by_source) == ["glossary", "requirements"]
    assert "Loyalty Tier" in fixture.before_text_by_source["requirements"]
    assert "VIP Tier" in fixture.after_text_by_source["requirements"]
    assert fixture.before_text_by_source["glossary"] == fixture.after_text_by_source["glossary"]
    assert fixture.expected_impacted_screens_json.startswith("{\n")
    assert '"changed_sources": [\n    "requirements"\n  ]' in fixture.expected_impacted_screens_json
    assert fixture.expected_changelog_markdown.startswith("# Changelog\n")
    assert "Targeted rerun is sufficient." in fixture.expected_changelog_markdown
