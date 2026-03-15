"""Focused manifest metadata checks for command intents and risk tiers."""

from notebooklm.contracts import load_capabilities
from notebooklm.contracts.risk import RiskTier


ALLOWED_COMMAND_INTENTS = {
    "DOCTOR",
    "QUERY",
    "GENERATION",
    "RESEARCH",
    "MUTATION",
    "LOCAL_MUTATION",
    "LOCAL_METADATA",
    "WORKSPACE_QUERY",
    "WORKSPACE_COMPARE",
    "RADAR_STATUS",
    "RADAR_BRIEF",
    "INBOX_TRIAGE",
    "INBOX_APPLY",
    "REMOTE_METADATA",
}


def test_manifest_commands_use_recognized_intents_and_risk_tiers():
    """Every manifest command should use the frozen command-intent/tier taxonomy."""
    capabilities = load_capabilities()
    commands = capabilities["commands"]
    declared_risk_tiers = capabilities["risk_tiers"]

    assert set(declared_risk_tiers) == {tier.value for tier in RiskTier}

    for name, spec in commands.items():
        assert spec["intent"] in ALLOWED_COMMAND_INTENTS, name
        assert spec["risk_tier"] in declared_risk_tiers, name
        assert RiskTier(spec["risk_tier"]).value == spec["risk_tier"]


def test_declared_risk_tiers_expose_contract_metadata_fields():
    """Top-level risk tiers should stay self-describing for later guard logic."""
    capabilities = load_capabilities()

    for tier_name, metadata in capabilities["risk_tiers"].items():
        assert set(metadata) == {"alias", "scope", "guard_behavior"}, tier_name
        assert metadata["alias"]
        assert metadata["scope"]
        assert metadata["guard_behavior"]


def test_manifest_includes_post_mvp_command_inventory():
    """Post-MVP command families should be declared before downstream feature work starts."""
    capabilities = load_capabilities()
    commands = capabilities["commands"]

    expected = {
        "events.tail": ("LOCAL_METADATA", RiskTier.T0_READ.value),
        "history.search": ("LOCAL_METADATA", RiskTier.T0_READ.value),
        "history.show": ("LOCAL_METADATA", RiskTier.T0_READ.value),
        "trace.show": ("LOCAL_METADATA", RiskTier.T0_READ.value),
        "doctor.fix": ("DOCTOR", RiskTier.T1_LOCAL_MUTATION.value),
        "doctor.bundle": ("DOCTOR", RiskTier.T0_READ.value),
        "workspace.list": ("LOCAL_METADATA", RiskTier.T0_READ.value),
        "workspace.create": ("LOCAL_MUTATION", RiskTier.T1_LOCAL_MUTATION.value),
        "workspace.add": ("LOCAL_MUTATION", RiskTier.T1_LOCAL_MUTATION.value),
        "workspace.remove": ("LOCAL_MUTATION", RiskTier.T1_LOCAL_MUTATION.value),
        "workspace.show": ("LOCAL_METADATA", RiskTier.T0_READ.value),
        "workspace.ask": ("WORKSPACE_QUERY", RiskTier.T0_READ.value),
        "workspace.compare": ("WORKSPACE_COMPARE", RiskTier.T1_LOCAL_MUTATION.value),
        "workspace.index": ("LOCAL_MUTATION", RiskTier.T1_LOCAL_MUTATION.value),
        "watch.add": ("LOCAL_MUTATION", RiskTier.T1_LOCAL_MUTATION.value),
        "watch.list": ("LOCAL_METADATA", RiskTier.T0_READ.value),
        "watch.pause": ("LOCAL_MUTATION", RiskTier.T1_LOCAL_MUTATION.value),
        "watch.run-now": ("LOCAL_MUTATION", RiskTier.T1_LOCAL_MUTATION.value),
        "radar.status": ("RADAR_STATUS", RiskTier.T0_READ.value),
        "radar.list": ("RADAR_STATUS", RiskTier.T0_READ.value),
        "radar.brief": ("RADAR_BRIEF", RiskTier.T0_READ.value),
        "radar.ignore": ("LOCAL_MUTATION", RiskTier.T1_LOCAL_MUTATION.value),
        "inbox.list": ("INBOX_TRIAGE", RiskTier.T0_READ.value),
        "inbox.view": ("INBOX_TRIAGE", RiskTier.T0_READ.value),
        "inbox.why": ("INBOX_TRIAGE", RiskTier.T0_READ.value),
        "inbox.approve": ("INBOX_APPLY", RiskTier.T2_KNOWLEDGE_MUTATION.value),
        "inbox.reject": ("INBOX_TRIAGE", RiskTier.T0_READ.value),
        "inbox.defer": ("INBOX_TRIAGE", RiskTier.T0_READ.value),
        "inbox.import": ("INBOX_APPLY", RiskTier.T2_KNOWLEDGE_MUTATION.value),
        "inbox.apply-batch": ("INBOX_APPLY", RiskTier.T2_KNOWLEDGE_MUTATION.value),
        "source.guide": ("REMOTE_METADATA", RiskTier.T0_READ.value),
        "sync.notebooks": ("REMOTE_METADATA", RiskTier.T1_LOCAL_MUTATION.value),
    }

    assert expected.keys() <= commands.keys()
    for name, (intent, tier) in expected.items():
        assert commands[name]["intent"] == intent
        assert commands[name]["risk_tier"] == tier
    assert commands["workspace.compare"]["read_only"] is False
