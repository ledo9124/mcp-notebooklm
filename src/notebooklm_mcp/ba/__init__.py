"""Dedicated BA runner subsystem for ``notebooklm_mcp``.

This package is intentionally separate from the generic MCP tool, resource,
and prompt modules. Later BA-specific work should land here first unless it is
truly generic NotebookLM parity work.
"""

from __future__ import annotations

from . import (
    adapter,
    contracts,
    extraction,
    fixtures,
    gaps,
    matrices,
    models,
    prompts,
    readiness,
    rendering,
    reruns,
    run_store,
    state_machine,
)
from . import schema_version, tools, validation

MODULE_BOUNDARIES: dict[str, dict[str, tuple[str, ...] | str]] = {
    "models": {
        "purpose": models.MODULE_PURPOSE,
        "owns": models.OWNS,
        "must_not_own": models.MUST_NOT_OWN,
    },
    "schema_version": {
        "purpose": schema_version.MODULE_PURPOSE,
        "owns": schema_version.OWNS,
        "must_not_own": schema_version.MUST_NOT_OWN,
    },
    "adapter": {
        "purpose": adapter.MODULE_PURPOSE,
        "owns": adapter.OWNS,
        "must_not_own": adapter.MUST_NOT_OWN,
    },
    "contracts": {
        "purpose": contracts.MODULE_PURPOSE,
        "owns": contracts.OWNS,
        "must_not_own": contracts.MUST_NOT_OWN,
    },
    "matrices": {
        "purpose": matrices.MODULE_PURPOSE,
        "owns": matrices.OWNS,
        "must_not_own": matrices.MUST_NOT_OWN,
    },
    "run_store": {
        "purpose": run_store.MODULE_PURPOSE,
        "owns": run_store.OWNS,
        "must_not_own": run_store.MUST_NOT_OWN,
    },
    "fixtures": {
        "purpose": fixtures.MODULE_PURPOSE,
        "owns": fixtures.OWNS,
        "must_not_own": fixtures.MUST_NOT_OWN,
    },
    "prompts": {
        "purpose": prompts.MODULE_PURPOSE,
        "owns": prompts.OWNS,
        "must_not_own": prompts.MUST_NOT_OWN,
    },
    "extraction": {
        "purpose": extraction.MODULE_PURPOSE,
        "owns": extraction.OWNS,
        "must_not_own": extraction.MUST_NOT_OWN,
    },
    "gaps": {
        "purpose": gaps.MODULE_PURPOSE,
        "owns": gaps.OWNS,
        "must_not_own": gaps.MUST_NOT_OWN,
    },
    "readiness": {
        "purpose": readiness.MODULE_PURPOSE,
        "owns": readiness.OWNS,
        "must_not_own": readiness.MUST_NOT_OWN,
    },
    "rendering": {
        "purpose": rendering.MODULE_PURPOSE,
        "owns": rendering.OWNS,
        "must_not_own": rendering.MUST_NOT_OWN,
    },
    "validation": {
        "purpose": validation.MODULE_PURPOSE,
        "owns": validation.OWNS,
        "must_not_own": validation.MUST_NOT_OWN,
    },
    "reruns": {
        "purpose": reruns.MODULE_PURPOSE,
        "owns": reruns.OWNS,
        "must_not_own": reruns.MUST_NOT_OWN,
    },
    "state_machine": {
        "purpose": state_machine.MODULE_PURPOSE,
        "owns": state_machine.OWNS,
        "must_not_own": state_machine.MUST_NOT_OWN,
    },
    "tools": {
        "purpose": tools.MODULE_PURPOSE,
        "owns": tools.OWNS,
        "must_not_own": tools.MUST_NOT_OWN,
    },
}

MODULE_NAMES = tuple(MODULE_BOUNDARIES)

DEPENDENCY_RULES = (
    "Keep BA-specific orchestration under notebooklm_mcp.ba instead of generic MCP modules.",
    "Let ba.tools and ba.prompts depend inward on adapter/models/rendering, not the reverse.",
    "Let ba.adapter depend on the notebooklm SDK surface, not on notebooklm_mcp.tools.* handlers.",
    "Let ba.run_store own local persistence; do not spread run artifacts across unrelated modules.",
)

__all__ = [
    "DEPENDENCY_RULES",
    "MODULE_BOUNDARIES",
    "MODULE_NAMES",
]
