"""Prompt-registry boundary for BA-specific orchestration prompts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

MODULE_PURPOSE = "Own BA-specific prompt templates and prompt-registration helpers."

OWNS = (
    "Prompt text and prompt factories for BA workflow stages",
    "Prompt selection and lookup rules",
    "Prompt registry helpers consumed by BA extraction/rendering flows",
)

MUST_NOT_OWN = (
    "NotebookLM SDK parity logic",
    "Filesystem persistence",
    "MCP transport glue outside BA-specific prompts",
    "Rendered output post-processing",
)


@dataclass(frozen=True, slots=True)
class BAPromptTemplate:
    """Named BA prompt template with a stable render contract."""

    name: str
    description: str
    template: str
    required_context: tuple[str, ...]

    def render(self, **context: Any) -> str:
        missing = [name for name in self.required_context if name not in context]
        if missing:
            missing_text = ", ".join(sorted(missing))
            raise ValueError(f"missing prompt context for {self.name}: {missing_text}")
        try:
            return self.template.format(**context).strip()
        except KeyError as exc:  # pragma: no cover - guarded above, kept for defensive clarity
            raise ValueError(f"missing prompt context for {self.name}: {exc.args[0]}") from exc


_PROMPT_REGISTRY = {
    "screen_catalog_extract": BAPromptTemplate(
        name="screen_catalog_extract",
        description="Extract the stable screen catalog and screen identifiers for a feature.",
        required_context=("feature_key", "source_scope", "schema_contract"),
        template="""
You are extracting the authoritative screen catalog for feature `{feature_key}`.

Scope discipline:
- Only include screens supported by the provided source scope: {source_scope}
- Preserve uncertainty explicitly; do not invent missing screens or flows
- Prefer smaller, screen-scoped reasoning over omnibus synthesis

Return exactly one JSON object matching this contract:
{schema_contract}
""",
    ),
    "terminology_extract": BAPromptTemplate(
        name="terminology_extract",
        description="Extract stable terminology, aliases, and ambiguous terms for the feature.",
        required_context=("feature_key", "source_scope", "schema_contract"),
        template="""
You are extracting the canonical terminology map for feature `{feature_key}`.

Evidence discipline:
- Use only the supplied source scope: {source_scope}
- Preserve alias collisions and ambiguity instead of smoothing them over
- If a term is unsupported, omit it rather than guessing

Return exactly one JSON object matching this contract:
{schema_contract}
""",
    ),
    "canonical_screen_extract": BAPromptTemplate(
        name="canonical_screen_extract",
        description="Extract confirmed, provisional, missing, and contradicted facts for one screen.",
        required_context=("feature_key", "screen_id", "concern_area", "source_scope", "schema_contract"),
        template="""
You are extracting the canonical fact set for screen `{screen_id}` in feature `{feature_key}`.

Concern area:
{concern_area}

Scope discipline:
- Use only the supplied source scope: {source_scope}
- Keep this answer tightly scoped to one screen and one concern area
- Confirm facts only when evidence is present; keep missing or contradicted items explicit

Return exactly one JSON object matching this contract:
{schema_contract}
""",
    ),
    "contradiction_review": BAPromptTemplate(
        name="contradiction_review",
        description="Review competing claims and preserve contradictions instead of flattening them.",
        required_context=("feature_key", "screen_id", "claim_set", "schema_contract"),
        template="""
You are reviewing contradictory claims for screen `{screen_id}` in feature `{feature_key}`.

Claims under review:
{claim_set}

Review discipline:
- Preserve competing claims explicitly
- Explain what evidence would resolve the contradiction
- Do not silently pick a winner unless the evidence is decisive

Return exactly one JSON object matching this contract:
{schema_contract}
""",
    ),
    "readiness_review": BAPromptTemplate(
        name="readiness_review",
        description="Assess whether a screen is ready for downstream FE/BE rendering.",
        required_context=("feature_key", "screen_id", "open_questions", "schema_contract"),
        template="""
You are assessing implementation readiness for screen `{screen_id}` in feature `{feature_key}`.

Open questions or blockers:
{open_questions}

Review discipline:
- Separate ready, degraded, and blocked outcomes clearly
- Call out unresolved evidence gaps instead of masking them
- Prefer precise next actions over generic narrative prose

Return exactly one JSON object matching this contract:
{schema_contract}
""",
    ),
}


def register_ba_prompts() -> dict[str, Callable[..., Any]]:
    """Return BA prompt handlers.

    The package skeleton is intentionally non-invasive for now; later beads can
    populate this registry without having to relocate prompt-related code.
    """

    return {name: template.render for name, template in _PROMPT_REGISTRY.items()}


def get_ba_prompt(name: str) -> BAPromptTemplate:
    """Return a named BA prompt template."""
    try:
        return _PROMPT_REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"unknown BA prompt template: {name}") from exc


def render_ba_prompt(name: str, **context: Any) -> str:
    """Render a named BA prompt template with explicit context."""
    return get_ba_prompt(name).render(**context)


__all__ = [
    "BAPromptTemplate",
    "MODULE_PURPOSE",
    "MUST_NOT_OWN",
    "OWNS",
    "get_ba_prompt",
    "register_ba_prompts",
    "render_ba_prompt",
]
