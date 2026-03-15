"""Deterministic scoring helpers for inbox candidate ranking."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import sqlite3
from urllib.parse import urlsplit, urlunsplit

from ..local.repositories import (
    InboxItemRepository,
    QueryRunRepository,
    WorkspaceMemberRepository,
    WorkspaceRunRepository,
)


_TOKEN_RE = re.compile(r"[a-z0-9]+")
_OFFICIAL_HOST_PREFIXES = ("docs.", "developers.", "developer.")
_MAX_HISTORY_TEXTS = 8
_MAX_CONTEXT_MATCHES = 3


@dataclass(frozen=True)
class InboxScoringContext:
    """Signals mined from local workspace/query/inbox history."""

    workspace_match_count: int = 0
    query_history_match_count: int = 0
    prior_approved_count: int = 0
    prior_rejected_count: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "workspace_match_count": self.workspace_match_count,
            "query_history_match_count": self.query_history_match_count,
            "prior_approved_count": self.prior_approved_count,
            "prior_rejected_count": self.prior_rejected_count,
        }


@dataclass(frozen=True)
class InboxScoringSignals:
    """Signals available when ranking one inbox candidate."""

    origin: str
    kind: str
    title: str | None = None
    snippet: str | None = None
    canonical_uri: str | None = None
    context_text: str | None = None
    existing_canonical_uris: tuple[str, ...] = ()
    existing_titles: tuple[str, ...] = ()
    cluster_match: bool = False
    cited_by_research: bool = False
    repeated_agreement_count: int = 0
    parseable: bool = True
    official_domain: bool | None = None
    context: InboxScoringContext = field(default_factory=InboxScoringContext)


@dataclass(frozen=True)
class InboxScore:
    """Deterministic base scores for one inbox candidate."""

    relevance: float
    novelty: float
    trust: float


def score_inbox_candidate(signals: InboxScoringSignals) -> InboxScore:
    """Compute deterministic inbox scores from candidate-local heuristics."""

    canonical_uri = _normalize_uri(signals.canonical_uri)
    existing_uris = {value for value in (_normalize_uri(uri) for uri in signals.existing_canonical_uris) if value}
    existing_titles = {
        value for value in (_normalize_title(title) for title in signals.existing_titles) if value
    }
    normalized_title = _normalize_title(signals.title)

    relevance = 0.2
    if signals.origin in {"change_radar", "deep_research", "fast_research"}:
        relevance += 0.2
    if signals.kind in {"source", "report", "replacement", "resync"}:
        relevance += 0.15
    if signals.title:
        relevance += 0.1
    if signals.snippet:
        relevance += 0.05
    if canonical_uri:
        relevance += 0.05
    relevance += min(0.2, 0.2 * _term_overlap(signals.title, signals.snippet, signals.context_text))
    relevance += min(0.12, 0.04 * signals.context.workspace_match_count)
    relevance += min(0.09, 0.03 * signals.context.query_history_match_count)
    if signals.context.prior_approved_count > 0:
        relevance += min(0.12, 0.03 * signals.context.prior_approved_count)
    if signals.context.prior_rejected_count > 0:
        relevance -= min(0.15, 0.05 * signals.context.prior_rejected_count)

    novelty = 0.85
    if signals.kind in {"resync", "replacement"}:
        novelty -= 0.25
    if canonical_uri and canonical_uri in existing_uris:
        novelty -= 0.35
    if normalized_title and normalized_title in existing_titles:
        novelty -= 0.25
    if signals.cluster_match:
        novelty -= 0.15
    if signals.context.prior_approved_count > 0:
        novelty -= min(0.18, 0.06 * signals.context.prior_approved_count)
    if signals.context.prior_rejected_count > 0:
        novelty -= min(0.12, 0.04 * signals.context.prior_rejected_count)

    trust = 0.4
    official_domain = (
        signals.official_domain
        if signals.official_domain is not None
        else _looks_official_domain(canonical_uri)
    )
    if official_domain:
        trust += 0.35
    elif canonical_uri:
        trust += 0.1
    if signals.parseable:
        trust += 0.1
    if signals.cited_by_research:
        trust += 0.1
    if signals.repeated_agreement_count > 1:
        trust += min(0.15, 0.05 * (signals.repeated_agreement_count - 1))
    if signals.title:
        trust += 0.05
    if signals.context.prior_approved_count > 0:
        trust += min(0.15, 0.05 * signals.context.prior_approved_count)
    if signals.context.prior_rejected_count > 0:
        trust -= min(0.18, 0.06 * signals.context.prior_rejected_count)

    return InboxScore(
        relevance=_clamp(relevance, minimum=0.0, maximum=1.0),
        novelty=_clamp(novelty, minimum=0.2, maximum=1.0),
        trust=_clamp(trust, minimum=0.0, maximum=0.98),
    )


def collect_inbox_scoring_context(
    connection: sqlite3.Connection,
    *,
    profile_id: str | None,
    notebook_id: str | None = None,
    workspace_id: str | None = None,
    title: str | None = None,
    snippet: str | None = None,
    canonical_uri: str | None = None,
) -> InboxScoringContext:
    """Collect local history signals that can refine inbox ranking."""

    candidate_terms = _tokenize(title) | _tokenize(snippet)
    query_history_texts = _recent_query_history_texts(
        connection,
        profile_id=profile_id,
        notebook_id=notebook_id,
    )
    workspace_history_texts = _recent_workspace_history_texts(
        connection,
        notebook_id=notebook_id,
        workspace_id=workspace_id,
    )
    prior_approved_count, prior_rejected_count = _prior_decision_counts(
        connection,
        profile_id=profile_id,
        notebook_id=notebook_id,
        canonical_uri=canonical_uri,
        title=title,
    )
    return InboxScoringContext(
        workspace_match_count=_history_match_count(candidate_terms, workspace_history_texts),
        query_history_match_count=_history_match_count(candidate_terms, query_history_texts),
        prior_approved_count=prior_approved_count,
        prior_rejected_count=prior_rejected_count,
    )


def _clamp(value: float, *, minimum: float, maximum: float) -> float:
    return round(max(minimum, min(maximum, value)), 2)


def _normalize_title(value: str | None) -> str | None:
    if value is None:
        return None
    collapsed = " ".join(value.lower().split())
    return collapsed or None


def _normalize_uri(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None

    parsed = urlsplit(stripped)
    if not parsed.scheme and not parsed.netloc:
        return stripped.rstrip("/").lower()

    normalized_path = parsed.path.rstrip("/")
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            normalized_path,
            "",
            "",
        )
    )


def _tokenize(value: str | None) -> set[str]:
    if value is None:
        return set()
    return {token for token in _TOKEN_RE.findall(value.lower()) if len(token) > 2}


def _term_overlap(title: str | None, snippet: str | None, context_text: str | None) -> float:
    context_terms = _tokenize(context_text)
    if not context_terms:
        return 0.0
    candidate_terms = _tokenize(title) | _tokenize(snippet)
    if not candidate_terms:
        return 0.0
    return len(candidate_terms & context_terms) / len(context_terms)


def _looks_official_domain(uri: str | None) -> bool:
    if uri is None:
        return False
    host = urlsplit(uri).netloc.lower()
    if not host:
        return False
    if host.endswith(".gov") or host.endswith(".edu"):
        return True
    if host == "docs.google.com" or host.endswith(".google.com"):
        return True
    return any(host.startswith(prefix) for prefix in _OFFICIAL_HOST_PREFIXES)


def _recent_query_history_texts(
    connection: sqlite3.Connection,
    *,
    profile_id: str | None,
    notebook_id: str | None,
) -> tuple[str, ...]:
    repository = QueryRunRepository(connection)
    if notebook_id is not None:
        runs = repository.list_for_notebook(notebook_id)
    elif profile_id is not None:
        runs = repository.list_for_profile(profile_id)
    else:
        return ()
    return _recent_history_texts(
        run.prompt_text
        for run in sorted(
            runs,
            key=lambda record: ((record.started_at or ""), record.id),
            reverse=True,
        )
        if run.prompt_text and run.status != "failed"
    )


def _recent_workspace_history_texts(
    connection: sqlite3.Connection,
    *,
    notebook_id: str | None,
    workspace_id: str | None,
) -> tuple[str, ...]:
    workspace_ids: set[str] = set()
    if workspace_id is not None:
        workspace_ids.add(workspace_id)
    if notebook_id is not None:
        workspace_ids.update(
            member.workspace_id
            for member in WorkspaceMemberRepository(connection).list_for_notebook(notebook_id)
            if member.enabled
        )
    if not workspace_ids:
        return ()

    repository = WorkspaceRunRepository(connection)
    runs = [
        run
        for workspace_key in workspace_ids
        for run in repository.list_for_workspace(workspace_key)
        if run.query_text and run.mode in {"ask", "compare"} and run.status != "failed"
    ]
    return _recent_history_texts(
        run.query_text
        for run in sorted(
            runs,
            key=lambda record: ((record.started_at or ""), record.id),
            reverse=True,
        )
    )


def _prior_decision_counts(
    connection: sqlite3.Connection,
    *,
    profile_id: str | None,
    notebook_id: str | None,
    canonical_uri: str | None,
    title: str | None,
) -> tuple[int, int]:
    repository = InboxItemRepository(connection)
    if notebook_id is not None:
        items = repository.list_for_notebook(notebook_id)
    elif profile_id is not None:
        items = repository.list_for_profile(profile_id)
    else:
        return 0, 0

    normalized_uri = _normalize_uri(canonical_uri)
    normalized_title = _normalize_title(title)
    approved = 0
    rejected = 0
    for item in items:
        if not _decision_matches_item(
            item_canonical_uri=item.canonical_uri,
            item_title=item.title,
            normalized_uri=normalized_uri,
            normalized_title=normalized_title,
        ):
            continue
        if item.state in {"approved", "applied"}:
            approved += 1
        elif item.state == "rejected":
            rejected += 1
    return min(_MAX_CONTEXT_MATCHES, approved), min(_MAX_CONTEXT_MATCHES, rejected)


def _decision_matches_item(
    *,
    item_canonical_uri: str | None,
    item_title: str | None,
    normalized_uri: str | None,
    normalized_title: str | None,
) -> bool:
    if normalized_uri is not None and _normalize_uri(item_canonical_uri) == normalized_uri:
        return True
    if normalized_title is not None and _normalize_title(item_title) == normalized_title:
        return True
    return False


def _recent_history_texts(values) -> tuple[str, ...]:
    texts: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw).strip()
        if not text or text in seen:
            continue
        texts.append(text)
        seen.add(text)
        if len(texts) >= _MAX_HISTORY_TEXTS:
            break
    return tuple(texts)


def _history_match_count(candidate_terms: set[str], history_texts: tuple[str, ...]) -> int:
    if not candidate_terms or not history_texts:
        return 0
    matches = 0
    for text in history_texts:
        if candidate_terms & _tokenize(text):
            matches += 1
            if matches >= _MAX_CONTEXT_MATCHES:
                break
    return matches


__all__ = [
    "InboxScore",
    "InboxScoringContext",
    "InboxScoringSignals",
    "collect_inbox_scoring_context",
    "score_inbox_candidate",
]
