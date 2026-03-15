"""Unit tests for the contracts package manifest loader."""

from pathlib import Path

from notebooklm.contracts import CAPABILITIES_PATH, Envelope, Intent, load_capabilities


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_load_capabilities_reads_manifest_into_python_types():
    """The manifest loader should decode the current YAML contract without extras."""
    capabilities = load_capabilities()

    assert capabilities["version"] == 1
    assert capabilities["commands"]["ask"]["read_only"] is True
    assert capabilities["commands"]["overview"]["compatibility"]["aliases"] == ["summary"]
    assert capabilities["commands"]["doctor.check"]["mode"] == "doctor_check"
    assert capabilities["doctor_checks"] == [
        "auth_snapshot_present",
        "auth_snapshot_fresh",
        "build_label_present",
        "db_openable",
        "schema_current",
        "write_permissions_ok",
        "notebooklm_home_consistent",
    ]
    assert capabilities["doctor_check_categories"]["workspace"] == [
        "workspace_tables_ready",
        "workspace_index_fresh",
    ]
    assert capabilities["risk_tiers"]["T3_DESTRUCTIVE"]["alias"] == "CRITICAL"


def test_contracts_package_exports_loader_and_existing_contract_types():
    """The package root should expose the loader alongside landed contract types."""
    capabilities = load_capabilities(REPO_ROOT / "src/notebooklm/contracts/capabilities.yaml")

    assert CAPABILITIES_PATH.name == "capabilities.yaml"
    assert Intent.QUERY.value == "QUERY"
    assert Envelope.__name__ == "Envelope"
    assert capabilities["commands"]["audio"]["compatibility"]["aliases"] == ["generate audio"]
