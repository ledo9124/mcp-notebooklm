"""Focused tests for the experimental NL router classifier."""

from __future__ import annotations

import pytest

from notebooklm.contracts import Intent
from notebooklm.router import IntentClassification, classify_request


@pytest.mark.parametrize(
    ("request_text", "expected_intent", "expected_term"),
    [
        ("list notebooks", Intent.LOCAL_METADATA, "list notebooks"),
        ("which notebooks have PDF sources?", Intent.LOCAL_METADATA, "which notebooks"),
        ("sync stale drive sources", Intent.REMOTE_METADATA, "sync stale"),
        ("refresh notebook metadata for pricing", Intent.REMOTE_METADATA, "refresh notebook"),
        (
            "what do the pricing sources say about renewals?",
            Intent.QUERY,
            "say about",
        ),
        ("quick overview of current notebook", Intent.QUERY, "quick overview"),
        ("summarize current notebook", Intent.GENERATION, "summarize"),
        (
            "make an audio overview for the pricing notebook",
            Intent.GENERATION,
            "audio overview",
        ),
        ("start deep research on AI safety", Intent.RESEARCH, "deep research"),
        ("import research results for pricing", Intent.RESEARCH, "import research"),
    ],
)
def test_classify_request_matches_plan_examples(request_text, expected_intent, expected_term):
    result = classify_request(request_text)

    assert isinstance(result, IntentClassification)
    assert result.intent is expected_intent
    assert expected_term in result.matched_terms
    assert 0.0 < result.confidence <= 0.99
    assert result.rationale


def test_classify_request_defaults_to_query_when_no_rule_matches():
    result = classify_request("pricing notebook renewal themes")

    assert result.intent is Intent.QUERY
    assert result.matched_terms == ()
    assert result.confidence == 0.35
    assert "falling back to QUERY" in result.rationale


def test_classify_request_rejects_blank_input():
    with pytest.raises(ValueError, match="must not be blank"):
        classify_request("   ")
