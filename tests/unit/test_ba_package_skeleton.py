"""Architecture tests for the BA subsystem package skeleton."""

from __future__ import annotations

from importlib import import_module

from notebooklm_mcp.ba import MODULE_BOUNDARIES, MODULE_NAMES
from notebooklm_mcp.ba.prompts import register_ba_prompts
from notebooklm_mcp.ba.tools import register_ba_tools


EXPECTED_MODULES = {
    "adapter",
    "contracts",
    "extraction",
    "fixtures",
    "gaps",
    "matrices",
    "models",
    "prompts",
    "readiness",
    "rendering",
    "reruns",
    "run_store",
    "schema_version",
    "state_machine",
    "tools",
    "validation",
}


def test_ba_package_declares_expected_modules() -> None:
    assert set(MODULE_NAMES) == EXPECTED_MODULES
    assert set(MODULE_BOUNDARIES) == EXPECTED_MODULES


def test_ba_modules_expose_boundary_metadata() -> None:
    for module_name in EXPECTED_MODULES:
        module = import_module(f"notebooklm_mcp.ba.{module_name}")
        assert isinstance(module.MODULE_PURPOSE, str)
        assert module.MODULE_PURPOSE
        assert isinstance(module.OWNS, tuple)
        assert module.OWNS
        assert isinstance(module.MUST_NOT_OWN, tuple)
        assert module.MUST_NOT_OWN


def test_ba_registries_remain_scoped_to_their_current_surface() -> None:
    prompt_registry = register_ba_prompts()
    tool_registry = register_ba_tools(object())

    assert {
        "screen_catalog_extract",
        "terminology_extract",
        "canonical_screen_extract",
        "contradiction_review",
        "readiness_review",
    } <= set(prompt_registry)
    assert all(callable(handler) for handler in prompt_registry.values())
    assert {"ba.start_run", "ba.register_sources"} <= set(tool_registry)
    assert all(callable(handler) for handler in tool_registry.values())
