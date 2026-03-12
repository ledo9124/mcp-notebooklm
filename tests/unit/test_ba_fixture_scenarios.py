"""Semantic checks for the seeded representative BA fixture families."""

from __future__ import annotations

import json

import pytest

from notebooklm_mcp.ba.fixtures import FixtureScenario, load_fixture_package


@pytest.mark.parametrize(
    ("scenario", "expected_sources", "expected_notes", "expected_decision", "markers"),
    [
        (
            FixtureScenario.CLEAN_FEATURE,
            ("api-contract", "glossary", "requirements"),
            (),
            "READY_FOR_FE_AND_BE",
            {"requirements": "Customer Form", "api-contract": "POST /customers"},
        ),
        (
            FixtureScenario.MISSING_CONTRACT,
            ("glossary", "requirements"),
            (),
            "READY_FOR_FE_WITH_PROVISIONAL_CONTRACT",
            {"requirements": "The backend payload is not yet specified"},
        ),
        (
            FixtureScenario.CONTRADICTORY_SOURCES,
            ("business-rules", "requirements"),
            (),
            "NOT_READY_BLOCKED_BY_REQUIREMENT_GAPS",
            {"business-rules": "Validate email on blur"},
        ),
        (
            FixtureScenario.GARBLED_PDF,
            ("ocr-export",),
            (),
            "NOT_READY_BLOCKED_BY_REQUIREMENT_GAPS",
            {"ocr-export": "Cust0mer F0rm"},
        ),
        (
            FixtureScenario.NOTE_CLARIFICATION,
            ("glossary", "requirements"),
            ("clarification-note",),
            "READY_FOR_FE_WITH_PROVISIONAL_CONTRACT",
            {"clarification-note": "Supporting Clarification Note"},
        ),
    ],
)
def test_seeded_fixture_scenarios_expose_expected_behavior_markers(
    scenario: FixtureScenario,
    expected_sources: tuple[str, ...],
    expected_notes: tuple[str, ...],
    expected_decision: str,
    markers: dict[str, str],
) -> None:
    fixture = load_fixture_package(scenario)
    signals = json.loads(fixture.expected_text_by_name["scenario-signals"])

    assert tuple(sorted(fixture.source_text_by_name)) == expected_sources
    assert tuple(sorted(fixture.note_text_by_name)) == expected_notes
    assert signals["scenario"] == scenario.value
    assert signals["source_keys"] == list(expected_sources)
    assert signals["note_keys"] == list(expected_notes)
    assert signals["expected_readiness_decision"] == expected_decision

    for key, marker in markers.items():
        corpus = fixture.source_text_by_name.get(key) or fixture.note_text_by_name.get(key) or ""
        assert marker in corpus


def test_seeded_fixture_scenarios_define_machine_readable_expected_signals() -> None:
    for scenario in (
        FixtureScenario.CLEAN_FEATURE,
        FixtureScenario.MISSING_CONTRACT,
        FixtureScenario.CONTRADICTORY_SOURCES,
        FixtureScenario.GARBLED_PDF,
        FixtureScenario.NOTE_CLARIFICATION,
    ):
        fixture = load_fixture_package(scenario)
        signals = json.loads(fixture.expected_text_by_name["scenario-signals"])

        assert signals["scenario"] == scenario.value
        assert signals["source_keys"] == sorted(fixture.source_text_by_name)
        assert signals["note_keys"] == sorted(fixture.note_text_by_name)
        assert signals["rationale"]
