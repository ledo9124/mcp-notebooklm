"""Unit tests for BA prompt registry and structured ask parsing utilities."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from notebooklm_mcp.ba.extraction import (
    StructuredParseQuality,
    ask_structured,
    parse_structured_response,
)
from notebooklm_mcp.ba.prompts import get_ba_prompt, register_ba_prompts, render_ba_prompt


def test_prompt_registry_exposes_named_prompt_families_and_renders_context() -> None:
    registry = register_ba_prompts()

    assert {
        "screen_catalog_extract",
        "terminology_extract",
        "canonical_screen_extract",
        "contradiction_review",
        "readiness_review",
    } <= set(registry)

    prompt = get_ba_prompt("canonical_screen_extract")
    rendered = render_ba_prompt(
        prompt.name,
        feature_key="customer-create",
        screen_id="SCR-001",
        concern_area="backend contract",
        source_scope="requirements.pdf, glossary.md",
        schema_contract='{"facts": [], "questions": []}',
    )

    assert "SCR-001" in rendered
    assert "backend contract" in rendered
    assert '{"facts": [], "questions": []}' in rendered


def test_parse_structured_response_accepts_exact_json() -> None:
    result = parse_structured_response('{"screen_id":"SCR-001","facts":[]}')

    assert result.parse_quality is StructuredParseQuality.EXACT
    assert result.payload == {"screen_id": "SCR-001", "facts": []}
    assert result.partial_payload is None


def test_parse_structured_response_extracts_fenced_json() -> None:
    result = parse_structured_response(
        """
        Here is the response:
        ```json
        {"screen_id": "SCR-001", "facts": []}
        ```
        """.strip()
    )

    assert result.parse_quality is StructuredParseQuality.FENCED_JSON
    assert result.payload == {"screen_id": "SCR-001", "facts": []}


def test_parse_structured_response_extracts_first_valid_json_span() -> None:
    result = parse_structured_response(
        'Use this payload {"screen_id":"SCR-001","facts":["gateway"]} for the next step.'
    )

    assert result.parse_quality is StructuredParseQuality.SPAN_EXTRACTED
    assert result.payload == {"screen_id": "SCR-001", "facts": ["gateway"]}


@pytest.mark.asyncio
async def test_ask_structured_degrades_to_raw_text_with_safe_partial_payload() -> None:
    async def _fake_ask(
        prompt_text: str,
        *,
        source_ids: list[str] | None = None,
        conversation_id: str | None = None,
    ) -> SimpleNamespace:
        assert "SCR-001" in prompt_text
        assert source_ids == ["src-1"]
        assert conversation_id == "conv-9"
        return SimpleNamespace(
            answer='Draft output {"screen_id": "SCR-001", "confidence": 0.82, "facts": ',
            conversation_id="conv-10",
            turn_number=4,
            is_follow_up=True,
            citations=("citation-1",),
        )

    result = await ask_structured(
        _fake_ask,
        prompt_name="canonical_screen_extract",
        prompt_context={
            "feature_key": "customer-create",
            "screen_id": "SCR-001",
            "concern_area": "backend contract",
            "source_scope": "requirements.pdf",
            "schema_contract": '{"facts": [], "confidence": 0.0}',
        },
        source_ids=("src-1",),
        conversation_id="conv-9",
    )

    assert result.parse_quality is StructuredParseQuality.DEGRADED
    assert result.payload is None
    assert result.partial_payload == {"screen_id": "SCR-001", "confidence": 0.82}
    assert result.conversation_id == "conv-10"
    assert result.citations == ("citation-1",)
