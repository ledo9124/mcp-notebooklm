"""Notebook target resolution helpers for the experimental NL router."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import Literal


ResolutionSource = Literal[
    "explicit_option",
    "request_id",
    "exact_title",
    "current_context",
    "fuzzy_title",
    "none",
]
ResolutionStatus = Literal["resolved", "ambiguous", "unresolved", "none"]

_NOTEBOOK_ID_PREFIXES = ("nb_", "nb-", "notebook_", "notebook-")
_ID_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]{2,}")
_HINT_FRAGMENT = r"[a-z0-9][a-z0-9&'/-]*(?:\s+[a-z0-9][a-z0-9&'/-]*){0,3}"
_HINT_PATTERNS = (
    re.compile(
        rf"\b(?:for|from|about|on|in|into|of)\s+(?:the\s+)?(?P<hint>{_HINT_FRAGMENT})\s+notebook\b"
    ),
    re.compile(
        rf"\b(?:for|from|about|on|in|into|of)\s+(?:the\s+)?(?P<hint>{_HINT_FRAGMENT})\s+sources?\b"
    ),
    re.compile(rf"\bthe\s+(?P<hint>{_HINT_FRAGMENT})\s+notebook\b"),
    re.compile(rf"\bthe\s+(?P<hint>{_HINT_FRAGMENT})\s+sources?\b"),
)


@dataclass(frozen=True)
class NotebookResolutionCandidate:
    """One cached notebook candidate available to the router."""

    notebook_id: str
    title: str
    normalized_title: str


@dataclass(frozen=True)
class RankedNotebookCandidate:
    """One ranked notebook suggestion returned on ambiguous or weak matches."""

    notebook_id: str
    title: str
    score: float
    reason: str


@dataclass(frozen=True)
class NotebookResolution:
    """Notebook resolution outcome for one routed natural-language request."""

    notebook_id: str | None
    source: ResolutionSource
    status: ResolutionStatus
    matched_text: str | None
    rationale: str
    candidates: tuple[RankedNotebookCandidate, ...] = ()


def resolve_notebook_target(
    *,
    request: str,
    explicit_notebook_id: str | None,
    current_notebook_id: str | None,
    cached_candidates: list[NotebookResolutionCandidate],
) -> NotebookResolution:
    """Resolve a notebook target using the router-specific six-step cascade."""
    normalized_request = _normalize_text(request)

    if explicit_notebook_id:
        return _resolve_explicit_option(explicit_notebook_id, cached_candidates)

    request_id_resolution = _resolve_request_notebook_id(normalized_request, cached_candidates)
    if request_id_resolution is not None:
        return request_id_resolution

    exact_title_matches = [
        candidate
        for candidate in cached_candidates
        if candidate.normalized_title and _contains_phrase(normalized_request, candidate.normalized_title)
    ]
    if len(exact_title_matches) == 1:
        candidate = exact_title_matches[0]
        return NotebookResolution(
            notebook_id=candidate.notebook_id,
            source="exact_title",
            status="resolved",
            matched_text=candidate.title,
            rationale=f"Matched cached notebook title '{candidate.title}' in the request.",
        )
    if len(exact_title_matches) > 1:
        return _failed_resolution(
            status="ambiguous",
            matched_text=None,
            rationale="Multiple cached notebook titles appear in the request.",
            candidates=_rank_exact_matches(exact_title_matches, reason="exact title match"),
        )

    if current_notebook_id:
        return NotebookResolution(
            notebook_id=current_notebook_id,
            source="current_context",
            status="resolved",
            matched_text="current notebook" if "current notebook" in normalized_request else None,
            rationale="No explicit ID or exact title matched; using the current notebook context before fuzzy title matching.",
        )

    hints = _extract_request_hints(normalized_request)
    if hints:
        ranked = _rank_candidates(hints, cached_candidates)
        if ranked and _is_decisive_fuzzy_match(ranked):
            best = ranked[0]
            return NotebookResolution(
                notebook_id=best.notebook_id,
                source="fuzzy_title",
                status="resolved",
                matched_text=hints[0],
                rationale=f"Fuzzy title match on '{hints[0]}' selected '{best.title}'.",
            )

        failure_status: ResolutionStatus = "ambiguous" if len(ranked) > 1 else "unresolved"
        failure_reason = (
            f"Fuzzy notebook hint '{hints[0]}' matched multiple cached candidates."
            if ranked
            else f"No cached notebook matched inferred hint '{hints[0]}'."
        )
        return _failed_resolution(
            status=failure_status,
            matched_text=hints[0],
            rationale=failure_reason,
            candidates=ranked,
        )

    return NotebookResolution(
        notebook_id=None,
        source="none",
        status="none",
        matched_text=None,
        rationale="No notebook target was detected in the request.",
    )


def _resolve_explicit_option(
    selector: str,
    cached_candidates: list[NotebookResolutionCandidate],
) -> NotebookResolution:
    normalized_selector = _normalize_text(selector)

    exact_id_matches = [
        candidate for candidate in cached_candidates if candidate.notebook_id.casefold() == normalized_selector
    ]
    if len(exact_id_matches) == 1:
        return NotebookResolution(
            notebook_id=exact_id_matches[0].notebook_id,
            source="explicit_option",
            status="resolved",
            matched_text=selector,
            rationale="Explicit --notebook selector matched a cached notebook ID.",
        )

    prefix_matches = [
        candidate for candidate in cached_candidates if candidate.notebook_id.casefold().startswith(normalized_selector)
    ]
    if len(prefix_matches) == 1:
        return NotebookResolution(
            notebook_id=prefix_matches[0].notebook_id,
            source="explicit_option",
            status="resolved",
            matched_text=selector,
            rationale="Explicit --notebook selector matched a cached notebook ID prefix.",
        )
    if len(prefix_matches) > 1:
        return _failed_resolution(
            status="ambiguous",
            matched_text=selector,
            rationale=f"Explicit --notebook selector '{selector}' matches multiple cached notebook IDs.",
            candidates=_rank_exact_matches(prefix_matches, reason="ID prefix match"),
        )

    exact_title_matches = [
        candidate for candidate in cached_candidates if candidate.normalized_title == normalized_selector
    ]
    if len(exact_title_matches) == 1:
        return NotebookResolution(
            notebook_id=exact_title_matches[0].notebook_id,
            source="explicit_option",
            status="resolved",
            matched_text=selector,
            rationale="Explicit --notebook selector matched a cached notebook title.",
        )
    if len(exact_title_matches) > 1:
        return _failed_resolution(
            status="ambiguous",
            matched_text=selector,
            rationale=f"Explicit --notebook selector '{selector}' matches multiple cached notebook titles.",
            candidates=_rank_exact_matches(exact_title_matches, reason="exact title match"),
        )

    ranked = _rank_candidates((normalized_selector,), cached_candidates)
    if ranked and _is_decisive_fuzzy_match(ranked):
        best = ranked[0]
        return NotebookResolution(
            notebook_id=best.notebook_id,
            source="explicit_option",
            status="resolved",
            matched_text=selector,
            rationale=f"Explicit --notebook selector '{selector}' fuzzily matched '{best.title}'.",
        )
    if ranked:
        return _failed_resolution(
            status="ambiguous" if len(ranked) > 1 else "unresolved",
            matched_text=selector,
            rationale=f"Explicit --notebook selector '{selector}' did not identify a single cached notebook.",
            candidates=ranked,
        )

    return NotebookResolution(
        notebook_id=selector,
        source="explicit_option",
        status="resolved",
        matched_text=selector,
        rationale="Explicit --notebook selector was not found in cache; forwarding the raw selector downstream.",
    )


def _resolve_request_notebook_id(
    normalized_request: str,
    cached_candidates: list[NotebookResolutionCandidate],
) -> NotebookResolution | None:
    id_tokens = [
        token for token in _ID_TOKEN_RE.findall(normalized_request) if token.startswith(_NOTEBOOK_ID_PREFIXES)
    ]
    if not id_tokens:
        return None

    for token in id_tokens:
        exact_matches = [
            candidate for candidate in cached_candidates if candidate.notebook_id.casefold() == token
        ]
        if len(exact_matches) == 1:
            return NotebookResolution(
                notebook_id=exact_matches[0].notebook_id,
                source="request_id",
                status="resolved",
                matched_text=token,
                rationale=f"Request text explicitly named notebook ID '{token}'.",
            )

    for token in id_tokens:
        prefix_matches = [
            candidate for candidate in cached_candidates if candidate.notebook_id.casefold().startswith(token)
        ]
        if len(prefix_matches) == 1:
            return NotebookResolution(
                notebook_id=prefix_matches[0].notebook_id,
                source="request_id",
                status="resolved",
                matched_text=token,
                rationale=f"Request text explicitly named notebook ID prefix '{token}'.",
            )
        if len(prefix_matches) > 1:
            return _failed_resolution(
                status="ambiguous",
                matched_text=token,
                rationale=f"Request text notebook ID '{token}' matches multiple cached notebooks.",
                candidates=_rank_exact_matches(prefix_matches, reason="ID prefix match"),
            )

    return NotebookResolution(
        notebook_id=id_tokens[0],
        source="request_id",
        status="resolved",
        matched_text=id_tokens[0],
        rationale=f"Request text explicitly named notebook ID '{id_tokens[0]}' outside the local cache.",
    )


def _extract_request_hints(normalized_request: str) -> tuple[str, ...]:
    hints: list[str] = []
    for pattern in _HINT_PATTERNS:
        for match in pattern.finditer(normalized_request):
            hint = _normalize_text(match.group("hint"))
            if not hint or hint == "current":
                continue
            if hint not in hints:
                hints.append(hint)
    return tuple(hints)


def _rank_candidates(
    hints: tuple[str, ...],
    cached_candidates: list[NotebookResolutionCandidate],
) -> tuple[RankedNotebookCandidate, ...]:
    ranked: list[RankedNotebookCandidate] = []
    for candidate in cached_candidates:
        best_score = 0.0
        best_reason = ""
        for hint in hints:
            score, reason = _score_hint_against_title(hint, candidate.normalized_title)
            if score > best_score:
                best_score = score
                best_reason = reason
        if best_score <= 0:
            continue
        ranked.append(
            RankedNotebookCandidate(
                notebook_id=candidate.notebook_id,
                title=candidate.title,
                score=round(best_score, 2),
                reason=best_reason,
            )
        )
    ranked.sort(key=lambda candidate: (-candidate.score, candidate.title.casefold(), candidate.notebook_id))
    return tuple(ranked[:5])


def _score_hint_against_title(hint: str, normalized_title: str) -> tuple[float, str]:
    if not normalized_title:
        return 0.0, ""
    if hint == normalized_title:
        return 1.0, "exact title hint"

    title_tokens = normalized_title.split()
    hint_tokens = hint.split()
    if any(token.startswith(hint) or hint.startswith(token) for token in title_tokens):
        return 0.88, "token prefix match"
    if normalized_title.startswith(hint):
        return 0.84, "title prefix match"
    if hint in normalized_title and len(hint) >= 4:
        return 0.76, "title contains hint"

    overlap = 0.0
    if hint_tokens and title_tokens:
        overlap = len(set(hint_tokens) & set(title_tokens)) / max(len(hint_tokens), len(title_tokens))
    sequence = SequenceMatcher(None, hint, normalized_title).ratio()
    score = max(overlap * 0.7, sequence * 0.65)
    if score < 0.3:
        return 0.0, ""
    return score, "title similarity"


def _is_decisive_fuzzy_match(ranked: tuple[RankedNotebookCandidate, ...]) -> bool:
    if not ranked:
        return False
    if len(ranked) == 1:
        return ranked[0].score >= 0.55
    return ranked[0].score >= 0.75 and (ranked[0].score - ranked[1].score) >= 0.15


def _rank_exact_matches(
    matches: list[NotebookResolutionCandidate],
    *,
    reason: str,
) -> tuple[RankedNotebookCandidate, ...]:
    return tuple(
        RankedNotebookCandidate(
            notebook_id=candidate.notebook_id,
            title=candidate.title,
            score=1.0,
            reason=reason,
        )
        for candidate in sorted(matches, key=lambda candidate: (candidate.title.casefold(), candidate.notebook_id))
    )


def _failed_resolution(
    *,
    status: ResolutionStatus,
    matched_text: str | None,
    rationale: str,
    candidates: tuple[RankedNotebookCandidate, ...],
) -> NotebookResolution:
    return NotebookResolution(
        notebook_id=None,
        source="none",
        status=status,
        matched_text=matched_text,
        rationale=rationale,
        candidates=candidates,
    )


def _contains_phrase(normalized_text: str, phrase: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", normalized_text) is not None


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


__all__ = [
    "NotebookResolution",
    "NotebookResolutionCandidate",
    "RankedNotebookCandidate",
    "resolve_notebook_target",
]
