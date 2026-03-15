"""Unit tests for the contract intent enum."""

from notebooklm.contracts.intents import Intent


def test_intent_values_match_contract_taxonomy():
    """Keep the intent surface aligned with the Phase-0 contract docs."""
    assert [intent.value for intent in Intent] == [
        "LOCAL_METADATA",
        "LOCAL_MUTATION",
        "REMOTE_METADATA",
        "QUERY",
        "GENERATION",
        "RESEARCH",
        "DOCTOR",
        "WORKSPACE_QUERY",
        "WORKSPACE_COMPARE",
        "RADAR_STATUS",
        "RADAR_BRIEF",
        "INBOX_TRIAGE",
        "INBOX_APPLY",
    ]


def test_intent_round_trips_from_manifest_strings():
    """Manifest and envelope strings should map directly to enum members."""
    assert Intent("QUERY") is Intent.QUERY
    assert Intent("DOCTOR") is Intent.DOCTOR
    assert Intent("LOCAL_MUTATION") is Intent.LOCAL_MUTATION
    assert Intent("INBOX_APPLY") is Intent.INBOX_APPLY
