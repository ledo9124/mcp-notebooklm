"""Intent classification helpers for the experimental NL router."""

from __future__ import annotations

from dataclasses import dataclass
import re

from notebooklm.contracts import Intent


_TOKEN_RE = re.compile(r"[a-z0-9]+")
_ROUTER_INTENTS = (
    Intent.LOCAL_METADATA,
    Intent.REMOTE_METADATA,
    Intent.QUERY,
    Intent.GENERATION,
    Intent.RESEARCH,
)
_INTENT_PRECEDENCE = {
    Intent.RESEARCH: 0,
    Intent.GENERATION: 1,
    Intent.REMOTE_METADATA: 2,
    Intent.LOCAL_METADATA: 3,
    Intent.QUERY: 4,
}
_PHRASE_WEIGHTS: dict[Intent, tuple[tuple[str, float], ...]] = {
    Intent.LOCAL_METADATA: (
        ("list notebooks", 1.0),
        ("which notebooks", 0.95),
        ("show notebook", 0.9),
        ("show source", 0.9),
        ("list sources", 0.95),
        ("which sources", 0.85),
        ("find notebooks", 0.85),
        ("find sources", 0.8),
        ("filter notebooks", 0.8),
        ("filter sources", 0.8),
        ("cached metadata", 0.75),
    ),
    Intent.REMOTE_METADATA: (
        ("sync notebooks", 1.0),
        ("sync sources", 0.95),
        ("sync stale", 0.95),
        ("refresh metadata", 0.9),
        ("refresh notebook", 0.85),
        ("refresh source", 0.85),
        ("stale drive sources", 0.9),
        ("latest metadata", 0.7),
        ("resync", 0.9),
    ),
    Intent.QUERY: (
        ("quick overview", 1.0),
        ("overview", 0.8),
        ("say about", 0.95),
        ("what do", 0.7),
        ("tell me", 0.7),
        ("explain", 0.8),
        ("compare", 0.75),
        ("evidence", 0.75),
        ("answer", 0.7),
    ),
    Intent.GENERATION: (
        ("briefing doc", 1.0),
        ("briefing", 0.95),
        ("study guide", 1.0),
        ("audio overview", 1.0),
        ("audio", 0.9),
        ("podcast", 0.8),
        ("report", 0.9),
        ("summarize", 0.95),
        ("summarise", 0.95),
        ("generate", 0.7),
        ("make a summary", 0.85),
    ),
    Intent.RESEARCH: (
        ("deep research", 1.0),
        ("web research", 0.95),
        ("drive research", 0.95),
        ("start research", 0.95),
        ("wait for research", 1.0),
        ("poll research", 0.95),
        ("import research", 1.0),
        ("research import", 1.0),
        ("research", 0.75),
        ("discover sources", 0.85),
    ),
}


@dataclass(frozen=True)
class IntentClassification:
    """Deterministic NL routing classification for one request."""

    intent: Intent
    confidence: float
    matched_terms: tuple[str, ...]
    rationale: str


def classify_request(request: str) -> IntentClassification:
    """Classify a natural-language request into one of the routing intent buckets."""
    normalized = _normalize_text(request)
    if not normalized:
        raise ValueError("Request must not be blank.")

    tokens = set(_TOKEN_RE.findall(normalized))
    scores = {intent: 0.0 for intent in _ROUTER_INTENTS}
    matched_terms: dict[Intent, list[str]] = {intent: [] for intent in _ROUTER_INTENTS}

    for intent, rules in _PHRASE_WEIGHTS.items():
        for phrase, weight in rules:
            if _contains_phrase(normalized, phrase, tokens=tokens):
                scores[intent] += weight
                matched_terms[intent].append(phrase)

    _apply_keyword_bonuses(scores, matched_terms, normalized=normalized, tokens=tokens)

    ranked = sorted(
        _ROUTER_INTENTS,
        key=lambda intent: (-scores[intent], _INTENT_PRECEDENCE[intent]),
    )
    best_intent = ranked[0]
    best_score = scores[best_intent]
    second_score = scores[ranked[1]] if len(ranked) > 1 else 0.0

    if best_score <= 0:
        return IntentClassification(
            intent=Intent.QUERY,
            confidence=0.35,
            matched_terms=(),
            rationale="No routing-specific keywords matched; falling back to QUERY.",
        )

    matched = tuple(dict.fromkeys(matched_terms[best_intent]))
    confidence = _clamp(0.45 + (best_score * 0.18) + max(0.0, best_score - second_score) * 0.2)
    rationale = (
        f"Matched {', '.join(matched)} -> {best_intent.value}."
        if matched
        else f"Highest heuristic score selected {best_intent.value}."
    )
    return IntentClassification(
        intent=best_intent,
        confidence=confidence,
        matched_terms=matched,
        rationale=rationale,
    )


def _apply_keyword_bonuses(
    scores: dict[Intent, float],
    matched_terms: dict[Intent, list[str]],
    *,
    normalized: str,
    tokens: set[str],
) -> None:
    metadata_nouns = {"notebook", "notebooks", "source", "sources", "metadata", "cache"}
    generation_nouns = {"audio", "briefing", "guide", "report", "summary", "study"}
    research_nouns = {"research", "sources", "import", "discover"}
    wh_words = {"what", "why", "how", "which"}

    if tokens & {"list", "show", "find", "filter"} and tokens & metadata_nouns:
        scores[Intent.LOCAL_METADATA] += 0.45
        matched_terms[Intent.LOCAL_METADATA].append("metadata verb+noun")

    if tokens & {"sync", "refresh", "resync"} and tokens & metadata_nouns:
        scores[Intent.REMOTE_METADATA] += 0.45
        matched_terms[Intent.REMOTE_METADATA].append("remote metadata verb+noun")

    if ("summarize" in tokens or "summarise" in tokens) and "overview" not in tokens:
        scores[Intent.GENERATION] += 0.35
        matched_terms[Intent.GENERATION].append("summarize")

    if tokens & {"make", "generate", "create"} and tokens & generation_nouns:
        scores[Intent.GENERATION] += 0.35
        matched_terms[Intent.GENERATION].append("generation verb+noun")

    if tokens & {"research", "import", "discover", "poll", "wait"} and tokens & research_nouns:
        scores[Intent.RESEARCH] += 0.35
        matched_terms[Intent.RESEARCH].append("research verb+noun")

    if "overview" in tokens:
        scores[Intent.QUERY] += 0.3
        matched_terms[Intent.QUERY].append("overview")

    if (tokens & wh_words or "?" in normalized) and "say" in tokens:
        scores[Intent.QUERY] += 0.3
        matched_terms[Intent.QUERY].append("question+say")
    elif tokens & {"what", "why", "how", "explain", "compare"}:
        scores[Intent.QUERY] += 0.2
        matched_terms[Intent.QUERY].append("open-ended question")


def _contains_phrase(normalized: str, phrase: str, *, tokens: set[str]) -> bool:
    candidate = _normalize_text(phrase)
    if not candidate:
        return False
    if " " in candidate:
        return f" {candidate} " in f" {normalized} "
    return candidate in tokens


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _clamp(value: float) -> float:
    return round(max(0.0, min(0.99, value)), 2)


__all__ = ["IntentClassification", "classify_request"]
