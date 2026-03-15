"""Focused tests for experimental notebook target resolution."""

from __future__ import annotations

from notebooklm.router import NotebookResolutionCandidate, resolve_notebook_target


def _candidate(notebook_id: str, title: str) -> NotebookResolutionCandidate:
    return NotebookResolutionCandidate(
        notebook_id=notebook_id,
        title=title,
        normalized_title=" ".join(title.casefold().split()),
    )


def test_resolve_notebook_target_prefers_explicit_option_over_request_and_context():
    resolution = resolve_notebook_target(
        request="summarize the current notebook into a briefing doc",
        explicit_notebook_id="nb_on",
        current_notebook_id="nb_context",
        cached_candidates=[
            _candidate("nb_onboarding", "Onboarding"),
            _candidate("nb_context", "Current"),
        ],
    )

    assert resolution.notebook_id == "nb_onboarding"
    assert resolution.source == "explicit_option"
    assert resolution.status == "resolved"
    assert resolution.matched_text == "nb_on"


def test_resolve_notebook_target_uses_explicit_notebook_id_in_request():
    resolution = resolve_notebook_target(
        request="make an audio overview for notebook nb_pricing",
        explicit_notebook_id=None,
        current_notebook_id="nb_context",
        cached_candidates=[
            _candidate("nb_pricing", "Pricing"),
            _candidate("nb_context", "Current"),
        ],
    )

    assert resolution.notebook_id == "nb_pricing"
    assert resolution.source == "request_id"
    assert resolution.status == "resolved"
    assert resolution.matched_text == "nb_pricing"


def test_resolve_notebook_target_uses_exact_title_match_before_current_context():
    resolution = resolve_notebook_target(
        request="what do the pricing sources say about renewals?",
        explicit_notebook_id=None,
        current_notebook_id="nb_context",
        cached_candidates=[
            _candidate("nb_pricing", "Pricing"),
            _candidate("nb_context", "Current"),
        ],
    )

    assert resolution.notebook_id == "nb_pricing"
    assert resolution.source == "exact_title"
    assert resolution.status == "resolved"
    assert resolution.matched_text == "Pricing"


def test_resolve_notebook_target_uses_current_context_before_fuzzy_title_match():
    resolution = resolve_notebook_target(
        request="summarize the current notebook into a briefing doc about renew",
        explicit_notebook_id=None,
        current_notebook_id="nb_context",
        cached_candidates=[
            _candidate("nb_context", "Inbox"),
            _candidate("nb_renewals", "Renewals Pricing"),
        ],
    )

    assert resolution.notebook_id == "nb_context"
    assert resolution.source == "current_context"
    assert resolution.status == "resolved"
    assert resolution.matched_text == "current notebook"


def test_resolve_notebook_target_supports_unique_fuzzy_title_match():
    resolution = resolve_notebook_target(
        request="make me a study guide for onboard notebook",
        explicit_notebook_id=None,
        current_notebook_id=None,
        cached_candidates=[
            _candidate("nb_onboarding", "Onboarding"),
            _candidate("nb_pricing", "Pricing"),
        ],
    )

    assert resolution.notebook_id == "nb_onboarding"
    assert resolution.source == "fuzzy_title"
    assert resolution.status == "resolved"
    assert resolution.matched_text == "onboard"


def test_resolve_notebook_target_returns_ranked_candidates_for_ambiguous_fuzzy_match():
    resolution = resolve_notebook_target(
        request="make me a study guide for pri notebook",
        explicit_notebook_id=None,
        current_notebook_id=None,
        cached_candidates=[
            _candidate("nb_pricing", "Pricing"),
            _candidate("nb_pricing_review", "Pricing Review"),
            _candidate("nb_support", "Support"),
        ],
    )

    assert resolution.notebook_id is None
    assert resolution.source == "none"
    assert resolution.status == "ambiguous"
    assert resolution.matched_text == "pri"
    assert [candidate.notebook_id for candidate in resolution.candidates[:2]] == [
        "nb_pricing",
        "nb_pricing_review",
    ]
    assert resolution.candidates[0].score >= resolution.candidates[1].score


def test_resolve_notebook_target_returns_unresolved_when_no_hint_matches():
    resolution = resolve_notebook_target(
        request="make me a study guide for legal notebook",
        explicit_notebook_id=None,
        current_notebook_id=None,
        cached_candidates=[
            _candidate("nb_support", "Support FAQ"),
            _candidate("nb_renewals", "Renewals Pricing"),
            _candidate("nb_pricing", "Pricing"),
        ],
    )

    assert resolution.notebook_id is None
    assert resolution.source == "none"
    assert resolution.status == "unresolved"
    assert resolution.matched_text == "legal"
    assert resolution.candidates == ()


def test_resolve_notebook_target_returns_none_when_no_notebook_signal_exists():
    resolution = resolve_notebook_target(
        request="which notebooks have stale drive sources?",
        explicit_notebook_id=None,
        current_notebook_id=None,
        cached_candidates=[_candidate("nb_pricing", "Pricing")],
    )

    assert resolution.notebook_id is None
    assert resolution.source == "none"
    assert resolution.status == "none"
    assert resolution.candidates == ()
