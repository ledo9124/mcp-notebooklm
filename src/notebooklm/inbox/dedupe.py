"""Deterministic dedupe and clustering helpers for inbox triage."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from urllib.parse import urlsplit, urlunsplit


_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SIGNAL_ORDER = {
    "canonical_uri": 0,
    "content_hash": 1,
    "normalized_title": 2,
    "domain_slug_similarity": 3,
    "report_citation_provenance": 4,
}
_EXACT_DUPLICATE_SIGNALS = frozenset({"canonical_uri", "content_hash", "normalized_title"})


@dataclass(frozen=True)
class InboxDedupeCandidate:
    """Signals available for one candidate entering the inbox pipeline."""

    id: str
    kind: str
    title: str | None = None
    canonical_uri: str | None = None
    content_hash: str | None = None
    report_citation_provenance: str | None = None
    priority: int = 0
    novelty_score: float = 0.0
    relevance_score: float = 0.0
    trust_score: float = 0.0


@dataclass(frozen=True)
class InboxClusterAction:
    """Recommended approval-first next step for a cluster."""

    kind: str
    target_count: int | None = None


@dataclass(frozen=True)
class InboxClusterVariant:
    """A non-representative member plus the signals that pulled it into the cluster."""

    candidate: InboxDedupeCandidate
    match_signals: tuple[str, ...]


@dataclass(frozen=True)
class InboxDedupeCluster:
    """A deduped inbox cluster ready for later approval/apply flows."""

    fingerprint: str
    representative: InboxDedupeCandidate
    variants: tuple[InboxClusterVariant, ...]
    signals: tuple[str, ...]
    recommended_action: InboxClusterAction


def cluster_inbox_candidates(
    candidates: list[InboxDedupeCandidate] | tuple[InboxDedupeCandidate, ...],
) -> list[InboxDedupeCluster]:
    """Cluster candidates by deterministic duplicate/near-duplicate signals."""

    if not candidates:
        return []

    parent = list(range(len(candidates)))
    pair_signals: dict[tuple[int, int], tuple[str, ...]] = {}

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for left_index, left in enumerate(candidates):
        for right_index in range(left_index + 1, len(candidates)):
            signals = _match_signals(left, candidates[right_index])
            if not signals:
                continue
            pair_signals[(left_index, right_index)] = signals
            union(left_index, right_index)

    members_by_root: dict[int, list[int]] = {}
    for index in range(len(candidates)):
        members_by_root.setdefault(find(index), []).append(index)

    clusters: list[InboxDedupeCluster] = []
    for member_indexes in members_by_root.values():
        members = [candidates[index] for index in member_indexes]
        representative = _select_representative(members)
        representative_index = next(
            index for index in member_indexes if candidates[index].id == representative.id
        )
        cluster_signals = _cluster_signals(member_indexes, pair_signals)
        variants = tuple(
            InboxClusterVariant(
                candidate=candidates[index],
                match_signals=_variant_signals(
                    representative_index,
                    index,
                    member_indexes,
                    pair_signals,
                    cluster_signals,
                ),
            )
            for index in sorted(
                (index for index in member_indexes if index != representative_index),
                key=lambda item: _candidate_sort_key(candidates[item]),
            )
        )
        clusters.append(
            InboxDedupeCluster(
                fingerprint=_cluster_fingerprint(members),
                representative=representative,
                variants=variants,
                signals=cluster_signals,
                recommended_action=_recommended_action(
                    representative=representative,
                    members=members,
                    cluster_signals=cluster_signals,
                ),
            )
        )

    return sorted(clusters, key=_cluster_sort_key)


def _cluster_sort_key(cluster: InboxDedupeCluster) -> tuple[float, float, float, int, str]:
    representative = cluster.representative
    return (
        -representative.trust_score,
        -representative.relevance_score,
        -representative.novelty_score,
        -representative.priority,
        representative.id,
    )


def _candidate_sort_key(candidate: InboxDedupeCandidate) -> tuple[float, float, float, int, int, int, int, str]:
    return (
        -candidate.trust_score,
        -candidate.relevance_score,
        -candidate.novelty_score,
        -candidate.priority,
        -int(bool(_normalize_uri(candidate.canonical_uri))),
        -int(bool(_normalize_content_hash(candidate.content_hash))),
        -int(bool(_normalize_provenance(candidate.report_citation_provenance))),
        candidate.id,
    )


def _select_representative(members: list[InboxDedupeCandidate]) -> InboxDedupeCandidate:
    return sorted(members, key=_candidate_sort_key)[0]


def _cluster_signals(
    member_indexes: list[int],
    pair_signals: dict[tuple[int, int], tuple[str, ...]],
) -> tuple[str, ...]:
    signals: set[str] = set()
    for left_index, left_member in enumerate(member_indexes):
        for right_member in member_indexes[left_index + 1 :]:
            signals.update(pair_signals.get(_pair_key(left_member, right_member), ()))
    return tuple(sorted(signals, key=lambda name: _SIGNAL_ORDER[name]))


def _variant_signals(
    representative_index: int,
    candidate_index: int,
    member_indexes: list[int],
    pair_signals: dict[tuple[int, int], tuple[str, ...]],
    cluster_signals: tuple[str, ...],
) -> tuple[str, ...]:
    direct = pair_signals.get(_pair_key(representative_index, candidate_index))
    if direct:
        return direct

    bridged: set[str] = set()
    for member_index in member_indexes:
        if member_index in {representative_index, candidate_index}:
            continue
        bridged.update(pair_signals.get(_pair_key(representative_index, member_index), ()))
        bridged.update(pair_signals.get(_pair_key(candidate_index, member_index), ()))
    if bridged:
        return tuple(sorted(bridged, key=lambda name: _SIGNAL_ORDER[name]))
    return cluster_signals


def _pair_key(left: int, right: int) -> tuple[int, int]:
    if left < right:
        return (left, right)
    return (right, left)


def _match_signals(left: InboxDedupeCandidate, right: InboxDedupeCandidate) -> tuple[str, ...]:
    signals: list[str] = []

    left_uri = _normalize_uri(left.canonical_uri)
    right_uri = _normalize_uri(right.canonical_uri)
    if left_uri and right_uri and left_uri == right_uri:
        signals.append("canonical_uri")

    left_hash = _normalize_content_hash(left.content_hash)
    right_hash = _normalize_content_hash(right.content_hash)
    if left_hash and right_hash and left_hash == right_hash:
        signals.append("content_hash")

    left_title = _normalize_title(left.title)
    right_title = _normalize_title(right.title)
    if left_title and right_title and left_title == right_title and _title_match_allowed(left_uri, right_uri):
        signals.append("normalized_title")

    left_provenance = _normalize_provenance(left.report_citation_provenance)
    right_provenance = _normalize_provenance(right.report_citation_provenance)
    if left_provenance and right_provenance and left_provenance == right_provenance:
        signals.append("report_citation_provenance")

    if left_uri != right_uri and _domain_slug_similarity(left_uri, right_uri) >= 0.6:
        signals.append("domain_slug_similarity")

    return tuple(sorted(signals, key=lambda name: _SIGNAL_ORDER[name]))


def _recommended_action(
    *,
    representative: InboxDedupeCandidate,
    members: list[InboxDedupeCandidate],
    cluster_signals: tuple[str, ...],
) -> InboxClusterAction:
    worthwhile_count = sum(1 for member in members if _is_import_worthy(member))
    unique_uris = {
        normalized
        for normalized in (_normalize_uri(member.canonical_uri) for member in members)
        if normalized
    }
    provenance_keys = {
        normalized
        for normalized in (
            _normalize_provenance(member.report_citation_provenance) for member in members
        )
        if normalized
    }
    exact_duplicate_cluster = set(cluster_signals).issubset(_EXACT_DUPLICATE_SIGNALS)

    if exact_duplicate_cluster and all(member.novelty_score <= 0.3 for member in members):
        return InboxClusterAction(kind="reject")

    if representative.kind == "report" and representative.trust_score >= 0.55:
        return InboxClusterAction(kind="approve_import_report_only")

    if (
        len(provenance_keys) == 1
        and len(members) > 1
        and all(member.kind == "source" for member in members)
    ):
        return InboxClusterAction(kind="approve_cited_only_sources")

    if worthwhile_count > 1 and len(unique_uris) > 1:
        return InboxClusterAction(kind="approve_top_n", target_count=worthwhile_count)

    if representative.trust_score < 0.45 and representative.relevance_score < 0.45:
        return InboxClusterAction(kind="defer")

    return InboxClusterAction(kind="approve_import_source")


def _is_import_worthy(candidate: InboxDedupeCandidate) -> bool:
    return (
        candidate.trust_score >= 0.65
        or candidate.relevance_score >= 0.75
        or (
            candidate.trust_score >= 0.55
            and candidate.relevance_score >= 0.55
            and candidate.novelty_score >= 0.35
        )
    )


def _cluster_fingerprint(members: list[InboxDedupeCandidate]) -> str:
    canonical_uris = sorted(
        {
            normalized
            for normalized in (_normalize_uri(member.canonical_uri) for member in members)
            if normalized
        }
    )
    titles = sorted(
        {normalized for normalized in (_normalize_title(member.title) for member in members) if normalized}
    )
    content_hashes = sorted(
        {
            normalized
            for normalized in (_normalize_content_hash(member.content_hash) for member in members)
            if normalized
        }
    )
    provenance_keys = sorted(
        {
            normalized
            for normalized in (
                _normalize_provenance(member.report_citation_provenance) for member in members
            )
            if normalized
        }
    )
    domain_slug_keys = sorted(
        {
            key
            for key in (_domain_slug_key(_normalize_uri(member.canonical_uri)) for member in members)
            if key
        }
    )

    payload = {
        "canonical_uris": canonical_uris,
        "content_hashes": content_hashes,
        "domain_slug_keys": domain_slug_keys,
        "provenance_keys": provenance_keys,
        "titles": titles,
    }
    if not any(payload.values()):
        payload["fallback_ids"] = sorted(member.id for member in members)

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _normalize_title(value: str | None) -> str | None:
    if value is None:
        return None
    collapsed = " ".join(value.lower().split())
    return collapsed or None


def _normalize_provenance(value: str | None) -> str | None:
    if value is None:
        return None
    collapsed = " ".join(value.lower().split())
    return collapsed or None


def _normalize_content_hash(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip().lower()
    return stripped or None


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


def _title_match_allowed(left_uri: str | None, right_uri: str | None) -> bool:
    if left_uri is None or right_uri is None:
        return True
    return urlsplit(left_uri).netloc == urlsplit(right_uri).netloc


def _domain_slug_similarity(left_uri: str | None, right_uri: str | None) -> float:
    if left_uri is None or right_uri is None:
        return 0.0

    left = urlsplit(left_uri)
    right = urlsplit(right_uri)
    if not left.netloc or left.netloc != right.netloc:
        return 0.0

    left_tokens = _slug_tokens(left.path)
    right_tokens = _slug_tokens(right.path)
    if not left_tokens or not right_tokens:
        return 0.0

    overlap = len(left_tokens & right_tokens)
    if overlap < 2:
        return 0.0
    return overlap / max(len(left_tokens), len(right_tokens))


def _domain_slug_key(uri: str | None) -> str | None:
    if uri is None:
        return None
    parsed = urlsplit(uri)
    if not parsed.netloc:
        return None
    tokens = sorted(_slug_tokens(parsed.path))
    if not tokens:
        return None
    return f"{parsed.netloc}:{','.join(tokens)}"


def _slug_tokens(path: str) -> set[str]:
    tokens = _TOKEN_RE.findall(path.lower())
    return {token for token in tokens if len(token) > 2}


__all__ = [
    "InboxClusterAction",
    "InboxClusterVariant",
    "InboxDedupeCandidate",
    "InboxDedupeCluster",
    "cluster_inbox_candidates",
]
