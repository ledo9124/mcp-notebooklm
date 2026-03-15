"""CLI-to-manifest contract checks for the Phase-0 capabilities surface."""

from pathlib import Path

import click

from notebooklm.notebooklm_cli import cli


REPO_ROOT = Path(__file__).resolve().parents[2]
CAPABILITIES_PATH = REPO_ROOT / "src/notebooklm/contracts/capabilities.yaml"

# Commands that already resolve to a canonical capabilities entry today, even if the
# currently shipped CLI still uses a transitional root or grouped form.
LIVE_COMMAND_TO_MANIFEST = {
    "ask": {"ask"},
    "audio": {"audio"},
    "cache prune": {"cache.prune"},
    "cache status": {"cache.status"},
    "delete": {"notebook.delete"},
    "doctor check": {"doctor.check"},
    "doctor bundle": {"doctor.bundle"},
    "doctor fix": {"doctor.fix"},
    "events tail": {"events.tail"},
    "overview": {"overview"},
    "summary": {"overview"},
    "study-guide": {"study-guide"},
    "summarize": {"summarize"},
    "support-bundle create": {"doctor.bundle"},
    "generate audio": {"audio"},
    "generate report": {"summarize", "study-guide"},
    "history search": {"history.search"},
    "history show": {"history.show"},
    "inbox approve": {"inbox.approve"},
    "inbox apply-batch": {"inbox.apply-batch"},
    "inbox defer": {"inbox.defer"},
    "inbox import": {"inbox.import"},
    "inbox list": {"inbox.list"},
    "inbox reject": {"inbox.reject"},
    "inbox view": {"inbox.view"},
    "radar brief": {"radar.brief"},
    "radar ignore": {"radar.ignore"},
    "radar list": {"radar.list"},
    "radar status": {"radar.status"},
    "trace show": {"trace.show"},
    "watch add": {"watch.add"},
    "watch list": {"watch.list"},
    "watch pause": {"watch.pause"},
    "watch run-now": {"watch.run-now"},
    "workspace add": {"workspace.add"},
    "workspace ask": {"workspace.ask"},
    "workspace compare": {"workspace.compare"},
    "workspace create": {"workspace.create"},
    "workspace index": {"workspace.index"},
    "workspace list": {"workspace.list"},
    "workspace remove": {"workspace.remove"},
    "workspace show": {"workspace.show"},
    "source add-research": {"research.start"},
    "research import": {"research.import"},
    "research start": {"research.start"},
    "research wait": {"research.wait"},
    "source guide": {"source.guide"},
    "source delete": {"source.delete"},
    "sync notebooks": {"sync.notebooks"},
}

# Phase-0 retained commands that are intentionally still shipped without a canonical
# capabilities entry on this branch. If a new live command appears, it must either
# be mapped above or be added here deliberately with an updated contract decision.
INTENTIONALLY_RETAINED_COMMANDS = {
    "agent",
    "auth check",
    "auth inspect",
    "auth refresh",
    "clear",
    "create",
    "list",
    "login",
    "notebook list",
    "notebook show",
    "notebook use",
    "research status",
    "route explain",
    "source add",
    "source list",
    "source wait",
    "status",
    "use",
}


def _manifest_command_names() -> set[str]:
    """Extract top-level capabilities command keys without adding a YAML dependency."""
    names: set[str] = set()
    in_commands = False

    for line in CAPABILITIES_PATH.read_text(encoding="utf-8").splitlines():
        if not in_commands:
            if line == "commands:":
                in_commands = True
            continue

        if not line:
            continue
        if not line.startswith("  "):
            break
        if line.startswith("  ") and not line.startswith("    ") and line.endswith(":"):
            names.add(line[2:-1])

    return names


def _leaf_command_paths(group: click.Group, prefix: str = "") -> set[str]:
    """Return all registered leaf command paths under a Click group."""
    ctx = click.Context(group)
    paths: set[str] = set()

    for name in group.list_commands(ctx):
        command = group.get_command(ctx, name)
        if command is None or command.hidden:
            continue

        path = f"{prefix} {name}".strip()
        if isinstance(command, click.Group):
            paths |= _leaf_command_paths(command, path)
        else:
            paths.add(path)

    return paths


def test_registered_cli_commands_are_accounted_for_by_phase0_contract():
    """Each live CLI leaf must be explicitly mapped or deliberately retained."""
    live_commands = _leaf_command_paths(cli)
    accounted_commands = set(LIVE_COMMAND_TO_MANIFEST) | INTENTIONALLY_RETAINED_COMMANDS

    assert live_commands == accounted_commands


def test_cli_to_manifest_mapping_targets_known_capabilities_commands():
    """Mapped CLI leaves should only point at declared manifest command entries."""
    manifest_commands = _manifest_command_names()

    for live_command, manifest_targets in LIVE_COMMAND_TO_MANIFEST.items():
        assert manifest_targets <= manifest_commands, live_command
