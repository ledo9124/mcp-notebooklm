"""Manifest-facing transport bindings for the Phase-0 command surface."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from notebooklm.contracts import load_capabilities
from notebooklm.contracts.command_specs import CommandSpec
from notebooklm.rpc import BATCHEXECUTE_URL, QUERY_URL, RPCMethod


@dataclass(frozen=True)
class RPCBinding:
    """Transport metadata for one manifest-backed command variant."""

    command_name: str
    intent: str
    mode: str
    client_method: str
    transport_kind: Literal["httpx", "local"]
    endpoint: str | None
    rpc_method: RPCMethod | None = None
    source_path_template: str | None = None

    @property
    def rpcid(self) -> str | None:
        """Return the batchexecute RPC ID when the binding uses one."""
        return self.rpc_method.value if self.rpc_method is not None else None


@dataclass(frozen=True)
class _BindingTemplate:
    client_method: str
    transport_kind: Literal["httpx", "local"]
    endpoint: str | None
    rpc_method: RPCMethod | None = None
    source_path_template: str | None = None
    mode_override: str | None = None


_BINDING_TEMPLATES: dict[str, tuple[_BindingTemplate, ...]] = {
    "ask": (
        _BindingTemplate(
            client_method="chat.ask",
            transport_kind="httpx",
            endpoint=QUERY_URL,
        ),
    ),
    "overview": (
        _BindingTemplate(
            client_method="notebooks.get_description",
            transport_kind="httpx",
            endpoint=BATCHEXECUTE_URL,
            rpc_method=RPCMethod.SUMMARIZE,
            source_path_template="/notebook/{notebook_id}",
        ),
    ),
    "summarize": (
        _BindingTemplate(
            client_method="artifacts.generate_report",
            transport_kind="httpx",
            endpoint=BATCHEXECUTE_URL,
            rpc_method=RPCMethod.CREATE_ARTIFACT,
            source_path_template="/notebook/{notebook_id}",
        ),
    ),
    "study-guide": (
        _BindingTemplate(
            client_method="artifacts.generate_report",
            transport_kind="httpx",
            endpoint=BATCHEXECUTE_URL,
            rpc_method=RPCMethod.CREATE_ARTIFACT,
            source_path_template="/notebook/{notebook_id}",
        ),
    ),
    "audio": (
        _BindingTemplate(
            client_method="artifacts.generate_audio",
            transport_kind="httpx",
            endpoint=BATCHEXECUTE_URL,
            rpc_method=RPCMethod.CREATE_ARTIFACT,
            source_path_template="/notebook/{notebook_id}",
        ),
    ),
    "research.start": (
        _BindingTemplate(
            client_method="research.start",
            transport_kind="httpx",
            endpoint=BATCHEXECUTE_URL,
            rpc_method=RPCMethod.START_FAST_RESEARCH,
            source_path_template="/notebook/{notebook_id}",
            mode_override="fast",
        ),
        _BindingTemplate(
            client_method="research.start",
            transport_kind="httpx",
            endpoint=BATCHEXECUTE_URL,
            rpc_method=RPCMethod.START_DEEP_RESEARCH,
            source_path_template="/notebook/{notebook_id}",
            mode_override="deep",
        ),
    ),
    "research.wait": (
        _BindingTemplate(
            client_method="research.poll",
            transport_kind="httpx",
            endpoint=BATCHEXECUTE_URL,
            rpc_method=RPCMethod.POLL_RESEARCH,
            source_path_template="/notebook/{notebook_id}",
        ),
    ),
    "research.import": (
        _BindingTemplate(
            client_method="research.import_sources",
            transport_kind="httpx",
            endpoint=BATCHEXECUTE_URL,
            rpc_method=RPCMethod.IMPORT_RESEARCH,
            source_path_template="/notebook/{notebook_id}",
        ),
    ),
    "history.search": (
        _BindingTemplate(
            client_method="history.search",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "history.show": (
        _BindingTemplate(
            client_method="history.show",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "trace.show": (
        _BindingTemplate(
            client_method="trace.show",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "events.tail": (
        _BindingTemplate(
            client_method="events.tail",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "doctor": (
        _BindingTemplate(
            client_method="doctor.fast",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "doctor.check": (
        _BindingTemplate(
            client_method="doctor.check",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "doctor.fix": (
        _BindingTemplate(
            client_method="doctor.fix",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "doctor.bundle": (
        _BindingTemplate(
            client_method="doctor.bundle",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "workspace.list": (
        _BindingTemplate(
            client_method="workspace.list",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "workspace.create": (
        _BindingTemplate(
            client_method="workspace.create",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "workspace.add": (
        _BindingTemplate(
            client_method="workspace.add",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "workspace.remove": (
        _BindingTemplate(
            client_method="workspace.remove",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "workspace.show": (
        _BindingTemplate(
            client_method="workspace.show",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "workspace.ask": (
        _BindingTemplate(
            client_method="workspace.ask",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "workspace.compare": (
        _BindingTemplate(
            client_method="workspace.compare",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "workspace.index": (
        _BindingTemplate(
            client_method="workspace.index",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "watch.add": (
        _BindingTemplate(
            client_method="watch.add",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "watch.list": (
        _BindingTemplate(
            client_method="watch.list",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "watch.pause": (
        _BindingTemplate(
            client_method="watch.pause",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "watch.run-now": (
        _BindingTemplate(
            client_method="watch.run_now",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "radar.status": (
        _BindingTemplate(
            client_method="radar.status",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "radar.list": (
        _BindingTemplate(
            client_method="radar.list",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "radar.brief": (
        _BindingTemplate(
            client_method="radar.brief",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "radar.ignore": (
        _BindingTemplate(
            client_method="radar.ignore",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "inbox.list": (
        _BindingTemplate(
            client_method="inbox.list",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "inbox.view": (
        _BindingTemplate(
            client_method="inbox.view",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "inbox.why": (
        _BindingTemplate(
            client_method="inbox.why",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "inbox.approve": (
        _BindingTemplate(
            client_method="inbox.approve",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "inbox.reject": (
        _BindingTemplate(
            client_method="inbox.reject",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "inbox.defer": (
        _BindingTemplate(
            client_method="inbox.defer",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "inbox.import": (
        _BindingTemplate(
            client_method="inbox.import_item",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "inbox.apply-batch": (
        _BindingTemplate(
            client_method="inbox.apply_batch",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "notebook.delete": (
        _BindingTemplate(
            client_method="notebooks.delete",
            transport_kind="httpx",
            endpoint=BATCHEXECUTE_URL,
            rpc_method=RPCMethod.DELETE_NOTEBOOK,
            source_path_template="/notebook/{notebook_id}",
        ),
    ),
    "source.guide": (
        _BindingTemplate(
            client_method="sources.get_guide",
            transport_kind="httpx",
            endpoint=BATCHEXECUTE_URL,
            rpc_method=RPCMethod.GET_SOURCE_GUIDE,
            source_path_template="/notebook/{notebook_id}",
        ),
    ),
    "source.delete": (
        _BindingTemplate(
            client_method="sources.delete",
            transport_kind="httpx",
            endpoint=BATCHEXECUTE_URL,
            rpc_method=RPCMethod.DELETE_SOURCE,
            source_path_template="/notebook/{notebook_id}",
        ),
    ),
    "sync.notebooks": (
        _BindingTemplate(
            client_method="sync.notebooks",
            transport_kind="httpx",
            endpoint=BATCHEXECUTE_URL,
        ),
    ),
    "cache.status": (
        _BindingTemplate(
            client_method="cache.status",
            transport_kind="local",
            endpoint=None,
        ),
    ),
    "cache.prune": (
        _BindingTemplate(
            client_method="cache.prune",
            transport_kind="local",
            endpoint=None,
        ),
    ),
}


def _binding_mode(spec: CommandSpec, mode_override: str | None) -> str:
    """Derive the route mode for a binding.

    Priority:
    1. Explicit mode override for commands that fan out to multiple transports
    2. Manifest `mode` field
    3. Manifest `output` field
    4. Normalized command name when neither field exists
    """
    if mode_override is not None:
        return mode_override
    if spec.mode is not None:
        return spec.mode
    if spec.output is not None:
        return spec.output
    return spec.name.replace(".", "_").replace("-", "_")


def build_rpc_map(command_specs: Mapping[str, CommandSpec]) -> dict[tuple[str, str], RPCBinding]:
    """Build the Phase-0 intent+mode transport registry from typed command specs."""
    missing_templates = set(command_specs) - set(_BINDING_TEMPLATES)
    if missing_templates:
        missing_list = ", ".join(sorted(missing_templates))
        raise ValueError(f"rpc_map templates missing commands: {missing_list}")

    bindings: dict[tuple[str, str], RPCBinding] = {}

    for command_name, spec in command_specs.items():
        for template in _BINDING_TEMPLATES[command_name]:
            mode = _binding_mode(spec, template.mode_override)
            key = (spec.intent, mode)
            if key in bindings:
                raise ValueError(f"duplicate rpc_map key: {key!r}")

            bindings[key] = RPCBinding(
                command_name=command_name,
                intent=spec.intent,
                mode=mode,
                client_method=template.client_method,
                transport_kind=template.transport_kind,
                endpoint=template.endpoint,
                rpc_method=template.rpc_method,
                source_path_template=template.source_path_template,
            )

    return bindings


def load_rpc_map(path: str | Path | None = None) -> dict[tuple[str, str], RPCBinding]:
    """Load `capabilities.yaml` and build the default Phase-0 transport registry."""
    manifest = load_capabilities(path)
    commands = manifest.get("commands")
    if not isinstance(commands, dict):
        raise ValueError("capabilities manifest is missing a `commands` mapping")

    specs = {
        name: CommandSpec.from_manifest(name, raw)
        for name, raw in commands.items()
        if isinstance(raw, Mapping)
    }
    return build_rpc_map(specs)


RPC_MAP = load_rpc_map()


__all__ = ["RPCBinding", "RPC_MAP", "build_rpc_map", "load_rpc_map"]
