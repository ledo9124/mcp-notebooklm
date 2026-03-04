"""Parser utilities for NotebookLM chat settings payloads."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any

from .exceptions import ChatSettingsParseError
from .rpc import ChatGoal, ChatResponseLength
from .types import ChatSettings

MAX_DEPTH = 50
MAX_NODES = 200_000
MIN_CANDIDATE_SCORE = 2

_GOAL_CODE_MAP: dict[int, ChatGoal] = {
    ChatGoal.DEFAULT.value: ChatGoal.DEFAULT,
    ChatGoal.CUSTOM.value: ChatGoal.CUSTOM,
    ChatGoal.LEARNING_GUIDE.value: ChatGoal.LEARNING_GUIDE,
}

_LENGTH_CODE_MAP: dict[int, ChatResponseLength] = {
    ChatResponseLength.DEFAULT.value: ChatResponseLength.DEFAULT,
    ChatResponseLength.LONGER.value: ChatResponseLength.LONGER,
    ChatResponseLength.SHORTER.value: ChatResponseLength.SHORTER,
}


@dataclass(frozen=True)
class _Candidate:
    goal_code: int
    length_code: int
    custom_prompt: str | None
    score: int
    depth: int


def _is_int(value: Any) -> bool:
    """Return True only for non-bool ints."""
    return isinstance(value, int) and not isinstance(value, bool)


def _iter_nested_nodes(
    raw: Any,
    *,
    max_depth: int,
    max_nodes: int,
):
    """Iteratively traverse nested lists/dicts with depth and node caps."""
    stack: list[tuple[Any, int]] = [(raw, 0)]
    visited = 0

    while stack:
        node, depth = stack.pop()
        visited += 1
        if visited > max_nodes:
            raise ChatSettingsParseError(
                details=(
                    f"Traversal exceeded node cap (max_nodes={max_nodes}). "
                    "Response payload may be too large or malformed."
                )
            )

        yield node, depth

        if depth >= max_depth:
            continue

        children: list[Any]
        if isinstance(node, (list, tuple)):
            children = list(node)
        elif isinstance(node, dict):
            children = list(node.values())
        else:
            continue

        for child in reversed(children):
            if isinstance(child, (list, tuple, dict)):
                stack.append((child, depth + 1))


def _extract_candidate(node: Any, depth: int) -> _Candidate | None:
    """Return a scored candidate if `node` matches chat settings signature."""
    if not isinstance(node, list) or len(node) != 2:
        return None

    goal_array, length_array = node
    if not isinstance(goal_array, list) or len(goal_array) not in (1, 2):
        return None
    if not isinstance(length_array, list) or len(length_array) != 1:
        return None

    goal_code = goal_array[0]
    length_code = length_array[0]
    if not _is_int(goal_code) or not _is_int(length_code):
        return None

    custom_prompt: str | None = None
    if len(goal_array) == 2:
        if not isinstance(goal_array[1], str):
            return None
        custom_prompt = goal_array[1]

    score = 0
    if goal_code in _GOAL_CODE_MAP:
        score += 3
    if length_code in _LENGTH_CODE_MAP:
        score += 3
    if goal_code == ChatGoal.CUSTOM.value and custom_prompt and custom_prompt.strip():
        score += 3
    if goal_code == ChatGoal.CUSTOM.value and (custom_prompt is None or not custom_prompt.strip()):
        score -= 5

    # Signature shape score
    score += 2

    return _Candidate(
        goal_code=goal_code,
        length_code=length_code,
        custom_prompt=custom_prompt,
        score=score,
        depth=depth,
    )


def parse_chat_settings(
    raw: Any,
    *,
    strict: bool = True,
    max_depth: int = MAX_DEPTH,
    max_nodes: int = MAX_NODES,
) -> ChatSettings:
    """Parse chat settings from a raw NotebookLM payload.

    The parser scans for candidates matching:
    - ``[[goal_code] or [goal_code, custom_prompt], [response_length_code]]``

    Args:
        raw: Raw API payload to scan.
        strict: If True, unknown goal/length codes raise ChatSettingsParseError.
            If False, unknown codes fall back to DEFAULT/DEFAULT with source="unknown".
        max_depth: Max traversal depth during iterative DFS.
        max_nodes: Max nodes visited during traversal.

    Returns:
        ChatSettings instance parsed from the highest-scoring candidate.

    Raises:
        ChatSettingsParseError: If no plausible candidate is found or strict parsing fails.
    """
    if max_depth < 1:
        raise ValueError("max_depth must be >= 1")
    if max_nodes < 1:
        raise ValueError("max_nodes must be >= 1")

    best: _Candidate | None = None

    for node, depth in _iter_nested_nodes(raw, max_depth=max_depth, max_nodes=max_nodes):
        candidate = _extract_candidate(node, depth)
        if candidate is None:
            continue

        if best is None:
            best = candidate
            continue

        # Prefer higher score, then shallower depth.
        if candidate.score > best.score or (
            candidate.score == best.score and candidate.depth < best.depth
        ):
            best = candidate

    if best is None or best.score < MIN_CANDIDATE_SCORE:
        raise ChatSettingsParseError(
            details="No chat settings signature found in server payload."
        )

    goal = _GOAL_CODE_MAP.get(best.goal_code)
    response_length = _LENGTH_CODE_MAP.get(best.length_code)
    has_unknown_codes = goal is None or response_length is None

    if has_unknown_codes and strict:
        raise ChatSettingsParseError(
            details=(
                "Unknown chat settings codes in payload "
                f"(goal_code={best.goal_code}, response_length_code={best.length_code})."
            )
        )

    if has_unknown_codes and not strict:
        warnings.warn(
            (
                "Unknown chat settings codes found "
                f"(goal_code={best.goal_code}, response_length_code={best.length_code}); "
                "falling back to DEFAULT/DEFAULT with source='unknown'."
            ),
            RuntimeWarning,
            stacklevel=2,
        )
        return ChatSettings(
            goal=ChatGoal.DEFAULT,
            response_length=ChatResponseLength.DEFAULT,
            custom_prompt=None,
            source="unknown",
        )

    assert goal is not None
    assert response_length is not None

    if goal == ChatGoal.CUSTOM and (best.custom_prompt is None or not best.custom_prompt.strip()):
        raise ChatSettingsParseError(
            details="CUSTOM goal was detected but custom prompt is missing or empty."
        )

    custom_prompt = best.custom_prompt if goal == ChatGoal.CUSTOM else None

    try:
        return ChatSettings(
            goal=goal,
            response_length=response_length,
            custom_prompt=custom_prompt,
            source="server",
        )
    except Exception as exc:
        raise ChatSettingsParseError(details=str(exc), cause=exc) from exc


__all__ = [
    "MAX_DEPTH",
    "MAX_NODES",
    "MIN_CANDIDATE_SCORE",
    "parse_chat_settings",
]

