"""Unit tests for contract risk-tier primitives."""

import pytest

from notebooklm.contracts.risk import (
    RiskTier,
    guard_refusal_details,
    manifest_risk_guard,
    risk_guard,
)


def test_risk_tier_metadata_matches_contract_taxonomy():
    """Keep aliases and guard text aligned with CONTRACT_NORMALIZATION §1."""
    assert RiskTier.T0_READ.alias == "SAFE"
    assert RiskTier.T1_LOCAL_MUTATION.alias == "CAUTION"
    assert RiskTier.T2_KNOWLEDGE_MUTATION.alias == "DANGEROUS"
    assert RiskTier.T3_DESTRUCTIVE.alias == "CRITICAL"

    assert RiskTier.T3_DESTRUCTIVE.guard_behavior == (
        "Explicit confirm/approval token required; two-step in non-interactive mode"
    )


def test_risk_guard_attaches_default_metadata():
    """The lightweight decorator should mark callables without changing behavior."""

    @risk_guard(RiskTier.T2_KNOWLEDGE_MUTATION)
    def import_sources() -> str:
        return "ok"

    assert import_sources() == "ok"
    assert import_sources.__risk_tier__ is RiskTier.T2_KNOWLEDGE_MUTATION
    assert import_sources.__risk_alias__ == "DANGEROUS"
    assert import_sources.__approval_gated__ is True
    assert import_sources.__destructive__ is False


def test_risk_guard_allows_explicit_flag_overrides():
    """Call sites can override the default approval/destructive flags when needed."""

    @risk_guard(RiskTier.T1_LOCAL_MUTATION, approval_gated=True, destructive=True)
    def prune_cache() -> str:
        return "pruned"

    assert prune_cache() == "pruned"
    assert prune_cache.__risk_tier__ is RiskTier.T1_LOCAL_MUTATION
    assert prune_cache.__approval_gated__ is True
    assert prune_cache.__destructive__ is True


def test_manifest_risk_guard_reads_risk_metadata_from_capabilities():
    """Manifest-backed decorator should derive the same callable metadata."""

    @manifest_risk_guard("notebook.delete")
    def delete_notebook() -> str:
        return "deleted"

    assert delete_notebook() == "deleted"
    assert delete_notebook.__risk_tier__ is RiskTier.T3_DESTRUCTIVE
    assert delete_notebook.__approval_gated__ is True
    assert delete_notebook.__destructive__ is True


def test_manifest_risk_guard_rejects_unknown_command_names():
    """Unknown command names should fail fast during decorator setup."""
    with pytest.raises(ValueError, match="Unknown command in capabilities manifest"):
        manifest_risk_guard("missing.command")


@pytest.mark.parametrize(
    ("tier", "next_step_kind", "next_step", "extra", "expected_fields"),
    [
        (
            RiskTier.T1_LOCAL_MUTATION,
            "confirm",
            "--yes",
            {"threshold": 10},
            {"threshold": 10},
        ),
        (
            RiskTier.T2_KNOWLEDGE_MUTATION,
            "approval_token",
            "--approval-token appr_tok_123",
            {"approval_token": "appr_tok_123"},
            {"approval_token": "appr_tok_123"},
        ),
        (
            RiskTier.T2_KNOWLEDGE_MUTATION,
            "resume_token",
            "resume_tok_123",
            {"resume_token": "resume_tok_123"},
            {"resume_token": "resume_tok_123"},
        ),
        (
            RiskTier.T1_LOCAL_MUTATION,
            "dry_run",
            "--dry-run",
            {"preview_supported": True},
            {"preview_supported": True},
        ),
    ],
)
def test_guard_refusal_details_builds_canonical_next_step_metadata(
    tier, next_step_kind, next_step, extra, expected_fields
):
    """Guard refusals should carry the exact next step plus stable risk metadata."""
    payload = guard_refusal_details(
        tier,
        next_step_kind=next_step_kind,
        next_step=next_step,
        extra=extra,
    )

    assert payload["next_step_kind"] == next_step_kind
    assert payload["next_step"] == next_step
    assert payload["risk_tier"] == tier.value
    assert payload["risk_alias"] == tier.alias
    assert payload["guard_behavior"] == tier.guard_behavior
    for key, value in expected_fields.items():
        assert payload[key] == value


def test_guard_refusal_details_rejects_invalid_shape():
    """Empty steps and unknown step kinds should fail fast."""
    with pytest.raises(ValueError, match="Unknown guard refusal next_step_kind"):
        guard_refusal_details(
            RiskTier.T1_LOCAL_MUTATION,
            next_step_kind="missing",  # type: ignore[arg-type]
            next_step="--yes",
        )

    with pytest.raises(ValueError, match="next_step cannot be empty"):
        guard_refusal_details(
            RiskTier.T1_LOCAL_MUTATION,
            next_step_kind="confirm",
            next_step="   ",
        )
