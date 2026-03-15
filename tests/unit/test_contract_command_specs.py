"""Unit tests for typed command metadata models."""

from notebooklm.contracts.command_specs import (
    CommandSpec,
    CompatibilitySpec,
    DeprecationState,
)
from notebooklm.contracts.risk import RiskTier


def test_compatibility_spec_parses_alias_and_warning_metadata():
    """Compatibility metadata should round-trip from the manifest shape."""
    compatibility = CompatibilitySpec.from_manifest(
        {
            "aliases": ["summary"],
            "deprecation_state": "warn",
            "deprecation_warning": "Deprecated compatibility command. Use `notebooklm overview` instead.",
        }
    )

    assert compatibility.aliases == ("summary",)
    assert compatibility.deprecation_state is DeprecationState.WARN
    assert compatibility.deprecation_warning == (
        "Deprecated compatibility command. Use `notebooklm overview` instead."
    )


def test_command_spec_parses_read_only_generation_metadata():
    """Typed command specs should preserve the manifest's optional fields."""
    spec = CommandSpec.from_manifest(
        "summarize",
        {
            "intent": "GENERATION",
            "risk_tier": "T0_READ",
            "output": "artifact_request",
            "mode": "briefing_doc",
            "compatibility": {
                "aliases": ["generate report --format briefing-doc"],
                "deprecation_state": "warn",
                "deprecation_warning": "Deprecated compatibility command. Use `notebooklm summarize` instead.",
            },
            "read_only": False,
            "waitable": True,
            "destructive": False,
            "approval_gated": False,
        },
    )

    assert spec.name == "summarize"
    assert spec.intent == "GENERATION"
    assert spec.risk_tier is RiskTier.T0_READ
    assert spec.output == "artifact_request"
    assert spec.mode == "briefing_doc"
    assert spec.compatibility.aliases == ("generate report --format briefing-doc",)
    assert spec.waitable is True
    assert spec.remote is None


def test_command_spec_keeps_manifest_mutation_intents_as_strings():
    """The command manifest currently uses command-intent strings beyond route intents."""
    spec = CommandSpec.from_manifest(
        "notebook.delete",
        {
            "intent": "MUTATION",
            "risk_tier": "T3_DESTRUCTIVE",
            "compatibility": {
                "aliases": [],
                "deprecation_state": "none",
            },
            "read_only": False,
            "waitable": False,
            "destructive": True,
            "approval_gated": True,
        },
    )

    assert spec.intent == "MUTATION"
    assert spec.risk_tier is RiskTier.T3_DESTRUCTIVE
    assert spec.destructive is True
    assert spec.approval_gated is True
