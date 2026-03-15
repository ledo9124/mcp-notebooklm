"""Contract checks for the manifest-backed capabilities surface."""

from pathlib import Path

from click.testing import CliRunner

from notebooklm.notebooklm_cli import cli


REPO_ROOT = Path(__file__).resolve().parents[2]
CAPABILITIES_PATH = REPO_ROOT / "src/notebooklm/contracts/capabilities.yaml"
VALID_COMMAND_INTENTS = {
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


def _top_level_list(name: str) -> list[str]:
    """Extract a top-level YAML list without adding a YAML parser dependency."""
    items: list[str] = []
    in_block = False

    for line in CAPABILITIES_PATH.read_text(encoding="utf-8").splitlines():
        if not in_block:
            if line == f"{name}:":
                in_block = True
            continue

        if not line:
            continue
        if not line.startswith("  - "):
            break

        items.append(line.removeprefix("  - "))

    return items


def _top_level_mapping_keys(name: str) -> list[str]:
    """Extract keys from a top-level mapping block."""
    keys: list[str] = []
    in_block = False

    for line in CAPABILITIES_PATH.read_text(encoding="utf-8").splitlines():
        if not in_block:
            if line == f"{name}:":
                in_block = True
            continue

        if not line:
            continue
        if not line.startswith("  ") or line.startswith("  - "):
            break
        if line.startswith("    "):
            continue

        key, _, _ = line.strip().partition(":")
        keys.append(key)

    return keys


def _command_scalar_fields() -> dict[str, dict[str, str]]:
    """Extract command-level scalar fields from the top-level commands block."""
    commands: dict[str, dict[str, str]] = {}
    in_commands = False
    current_command: str | None = None

    for line in CAPABILITIES_PATH.read_text(encoding="utf-8").splitlines():
        if not in_commands:
            if line == "commands:":
                in_commands = True
            continue

        if not line:
            continue
        if not line.startswith("  "):
            break
        if line.startswith("  ") and not line.startswith("    "):
            current_command = line.strip().removesuffix(":")
            commands[current_command] = {}
            continue
        if current_command is None or ":" not in line:
            continue
        if line.startswith("    compatibility:") or line.startswith("      "):
            continue

        key, _, value = line.strip().partition(": ")
        if value:
            commands[current_command][key] = value

    return commands


def _command_compatibility() -> dict[str, dict[str, object]]:
    """Extract compatibility metadata for each manifest command."""
    compatibility: dict[str, dict[str, object]] = {}
    in_commands = False
    in_compatibility = False
    collecting_aliases = False
    current_command: str | None = None

    for line in CAPABILITIES_PATH.read_text(encoding="utf-8").splitlines():
        if not in_commands:
            if line == "commands:":
                in_commands = True
            continue

        if not line:
            continue
        if not line.startswith("  "):
            break
        if line.startswith("  ") and not line.startswith("    "):
            current_command = line.strip().removesuffix(":")
            compatibility[current_command] = {"aliases": []}
            in_compatibility = False
            collecting_aliases = False
            continue
        if current_command is None:
            continue
        if line.startswith("    compatibility:"):
            in_compatibility = True
            collecting_aliases = False
            continue
        if not in_compatibility:
            continue
        if line.startswith("    ") and not line.startswith("      "):
            in_compatibility = False
            collecting_aliases = False
            continue
        if line.startswith("      aliases:"):
            aliases_value = line.removeprefix("      aliases:").strip()
            collecting_aliases = not aliases_value
            if aliases_value == "[]":
                compatibility[current_command]["aliases"] = []
            continue
        if collecting_aliases and line.startswith("        - "):
            compatibility[current_command]["aliases"].append(line.removeprefix("        - "))
            continue
        if line.startswith("      deprecation_state: "):
            compatibility[current_command]["deprecation_state"] = line.removeprefix(
                "      deprecation_state: "
            )
            continue
        if line.startswith("      deprecation_warning: "):
            compatibility[current_command]["deprecation_warning"] = line.removeprefix(
                "      deprecation_warning: "
            )

    return compatibility


def test_capabilities_manifest_exposes_mvp_doctor_checks():
    """Keep the frozen MVP doctor inventory stable for later doctor/runtime work."""
    assert _top_level_list("doctor_checks") == [
        "auth_snapshot_present",
        "auth_snapshot_fresh",
        "build_label_present",
        "db_openable",
        "schema_current",
        "write_permissions_ok",
        "notebooklm_home_consistent",
    ]


def test_capabilities_manifest_commands_use_known_intents_and_risk_tiers():
    """Every manifest command should reference the normalized intent/tier taxonomy."""
    commands = _command_scalar_fields()
    risk_tiers = set(_top_level_mapping_keys("risk_tiers"))

    assert risk_tiers == {
        "T0_READ",
        "T1_LOCAL_MUTATION",
        "T2_KNOWLEDGE_MUTATION",
        "T3_DESTRUCTIVE",
    }
    assert commands

    for command_name, fields in commands.items():
        assert fields["intent"] in VALID_COMMAND_INTENTS, command_name
        assert fields["risk_tier"] in risk_tiers, command_name


def test_capabilities_manifest_alias_metadata_matches_current_cli_surface():
    """Deprecated compatibility entries should match the current transitional CLI surface."""
    compatibility = _command_compatibility()
    runner = CliRunner()

    root_help = runner.invoke(cli, ["--help"], prog_name="notebooklm")
    generate_help = runner.invoke(cli, ["generate", "--help"], prog_name="notebooklm")
    report_help = runner.invoke(cli, ["generate", "report", "--help"], prog_name="notebooklm")

    assert root_help.exit_code == 0
    assert generate_help.exit_code == 0
    assert report_help.exit_code == 0

    assert compatibility["overview"] == {
        "aliases": ["summary"],
        "deprecation_state": "warn",
        "deprecation_warning": "Deprecated compatibility command. Use `notebooklm overview` instead.",
    }
    assert compatibility["summarize"] == {
        "aliases": ["generate report --format briefing-doc"],
        "deprecation_state": "warn",
        "deprecation_warning": "Deprecated compatibility command. Use `notebooklm summarize` instead.",
    }
    assert compatibility["study-guide"] == {
        "aliases": ["generate report --format study-guide"],
        "deprecation_state": "warn",
        "deprecation_warning": "Deprecated compatibility command. Use `notebooklm study-guide` instead.",
    }
    assert compatibility["audio"] == {
        "aliases": ["generate audio"],
        "deprecation_state": "warn",
        "deprecation_warning": "Deprecated compatibility command. Use `notebooklm audio` instead.",
    }
    assert compatibility["doctor.bundle"] == {
        "aliases": ["support-bundle create"],
        "deprecation_state": "none",
    }

    for command_name in (
        "ask",
        "doctor",
        "doctor.check",
        "doctor.fix",
        "events.tail",
        "history.search",
        "history.show",
        "research.import",
        "research.start",
        "research.wait",
        "workspace.list",
        "workspace.create",
        "workspace.add",
        "workspace.remove",
        "workspace.show",
        "workspace.ask",
        "workspace.compare",
        "workspace.index",
        "watch.add",
        "watch.list",
        "watch.pause",
        "watch.run-now",
        "radar.status",
        "radar.list",
        "radar.brief",
        "radar.ignore",
        "trace.show",
        "inbox.list",
        "inbox.view",
        "inbox.why",
        "inbox.approve",
        "inbox.reject",
        "inbox.defer",
        "inbox.import",
        "inbox.apply-batch",
        "notebook.delete",
        "source.guide",
        "source.delete",
        "cache.status",
        "cache.prune",
    ):
        assert compatibility[command_name] == {
            "aliases": [],
            "deprecation_state": "none",
        }

    assert "summary" in root_help.output
    assert "summarize" in root_help.output
    assert "study-guide" in root_help.output
    assert "audio" in root_help.output
    assert "generate" in root_help.output
    assert "audio" in generate_help.output
    assert "report" in generate_help.output
    assert "briefing-doc" in report_help.output
    assert "study-guide" in report_help.output
