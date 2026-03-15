"""Package-root smoke tests for the contracts API surface."""

from notebooklm.contracts import CommandSpec, Envelope, Intent, RiskTier, load_capabilities


def test_contracts_package_root_exports_parent_acceptance_surface():
    """The package root should expose the currently landed B-005 acceptance types."""
    capabilities = load_capabilities()
    overview = CommandSpec.from_manifest("overview", capabilities["commands"]["overview"])

    assert RiskTier.T0_READ.value == "T0_READ"
    assert Intent.QUERY.value == "QUERY"
    assert Envelope.__name__ == "Envelope"
    assert overview.name == "overview"
    assert overview.risk_tier is RiskTier.T0_READ
