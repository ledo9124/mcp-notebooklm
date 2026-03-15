"""Unit tests for deterministic inbox dedupe and clustering heuristics."""

from __future__ import annotations

from notebooklm.inbox.dedupe import InboxDedupeCandidate, cluster_inbox_candidates


def _candidate(
    candidate_id: str,
    *,
    kind: str = "source",
    title: str | None = None,
    canonical_uri: str | None = None,
    content_hash: str | None = None,
    report_citation_provenance: str | None = None,
    priority: int = 0,
    novelty_score: float = 0.5,
    relevance_score: float = 0.5,
    trust_score: float = 0.5,
) -> InboxDedupeCandidate:
    return InboxDedupeCandidate(
        id=candidate_id,
        kind=kind,
        title=title,
        canonical_uri=canonical_uri,
        content_hash=content_hash,
        report_citation_provenance=report_citation_provenance,
        priority=priority,
        novelty_score=novelty_score,
        relevance_score=relevance_score,
        trust_score=trust_score,
    )


def test_cluster_inbox_candidates_groups_exact_canonical_urls_and_keeps_fingerprint_stable():
    first = _candidate(
        "item-a",
        title="Roadmap update",
        canonical_uri="https://docs.example.com/plan/roadmap-2026",
        priority=4,
        novelty_score=0.72,
        relevance_score=0.9,
        trust_score=0.91,
    )
    second = _candidate(
        "item-b",
        title="Roadmap update copy",
        canonical_uri="https://docs.example.com/plan/roadmap-2026/",
        priority=2,
        novelty_score=0.41,
        relevance_score=0.7,
        trust_score=0.69,
    )
    third = _candidate(
        "item-c",
        title="Quarterly launch plan",
        canonical_uri="https://docs.example.com/plan/q2-launch",
        novelty_score=0.9,
        relevance_score=0.45,
        trust_score=0.52,
    )

    clusters = cluster_inbox_candidates([second, third, first])

    assert len(clusters) == 2
    canonical_cluster = next(cluster for cluster in clusters if cluster.representative.id == "item-a")
    same_members_different_order = cluster_inbox_candidates([first, second])[0]

    assert canonical_cluster.fingerprint == same_members_different_order.fingerprint
    assert canonical_cluster.signals == ("canonical_uri",)
    assert canonical_cluster.recommended_action.kind == "approve_import_source"
    assert [variant.candidate.id for variant in canonical_cluster.variants] == ["item-b"]
    assert canonical_cluster.variants[0].match_signals == ("canonical_uri",)


def test_cluster_inbox_candidates_groups_by_normalized_title_without_urls():
    clusters = cluster_inbox_candidates(
        [
            _candidate(
                "item-a",
                title="NotebookLM Migration Checklist",
                novelty_score=0.68,
                relevance_score=0.83,
                trust_score=0.71,
            ),
            _candidate(
                "item-b",
                title=" notebooklm   migration checklist ",
                novelty_score=0.64,
                relevance_score=0.72,
                trust_score=0.66,
            ),
        ]
    )

    assert len(clusters) == 1
    assert clusters[0].signals == ("normalized_title",)
    assert clusters[0].recommended_action.kind == "approve_import_source"


def test_cluster_inbox_candidates_groups_by_content_hash_and_rejects_low_novelty_duplicates():
    clusters = cluster_inbox_candidates(
        [
            _candidate(
                "item-a",
                title="Cached export",
                content_hash="sha256:abc123",
                novelty_score=0.22,
                relevance_score=0.44,
                trust_score=0.41,
            ),
            _candidate(
                "item-b",
                title="Cached export second copy",
                content_hash="SHA256:abc123",
                novelty_score=0.18,
                relevance_score=0.39,
                trust_score=0.35,
            ),
        ]
    )

    assert len(clusters) == 1
    assert clusters[0].signals == ("content_hash",)
    assert clusters[0].recommended_action.kind == "reject"


def test_cluster_inbox_candidates_groups_by_domain_slug_similarity_and_recommends_top_n():
    clusters = cluster_inbox_candidates(
        [
            _candidate(
                "item-a",
                title="Roadmap 2026 launch notes",
                canonical_uri="https://blog.example.com/updates/roadmap-2026-launch",
                priority=3,
                novelty_score=0.76,
                relevance_score=0.82,
                trust_score=0.74,
            ),
            _candidate(
                "item-b",
                title="Roadmap 2026 launch update",
                canonical_uri="https://blog.example.com/posts/roadmap-2026-launch-update",
                priority=2,
                novelty_score=0.72,
                relevance_score=0.78,
                trust_score=0.7,
            ),
            _candidate(
                "item-c",
                title="Roadmap 2026 launch notes",
                canonical_uri="https://other.example.com/posts/roadmap-2026-launch-update",
                priority=1,
                novelty_score=0.8,
                relevance_score=0.77,
                trust_score=0.71,
            ),
        ]
    )

    slug_cluster = next(cluster for cluster in clusters if cluster.representative.id == "item-a")

    assert len(clusters) == 2
    assert slug_cluster.signals == ("domain_slug_similarity",)
    assert slug_cluster.recommended_action.kind == "approve_top_n"
    assert slug_cluster.recommended_action.target_count == 2
    assert [variant.candidate.id for variant in slug_cluster.variants] == ["item-b"]


def test_cluster_inbox_candidates_groups_by_report_citation_and_prefers_cited_only_sources():
    clusters = cluster_inbox_candidates(
        [
            _candidate(
                "item-a",
                title="Primary source excerpt",
                canonical_uri="https://docs.example.com/source-a",
                report_citation_provenance="report:rpt-123:citation:4",
                novelty_score=0.66,
                relevance_score=0.88,
                trust_score=0.79,
            ),
            _candidate(
                "item-b",
                title="Secondary source excerpt",
                canonical_uri="https://docs.example.com/source-b",
                report_citation_provenance=" report:rpt-123:citation:4 ",
                novelty_score=0.58,
                relevance_score=0.74,
                trust_score=0.68,
            ),
        ]
    )

    assert len(clusters) == 1
    assert clusters[0].signals == ("report_citation_provenance",)
    assert clusters[0].recommended_action.kind == "approve_cited_only_sources"


def test_cluster_inbox_candidates_recommends_report_only_for_report_representative():
    clusters = cluster_inbox_candidates(
        [
            _candidate(
                "item-a",
                kind="report",
                title="Weekly delta briefing",
                canonical_uri="https://reports.example.com/briefings/weekly",
                novelty_score=0.62,
                relevance_score=0.81,
                trust_score=0.77,
            )
        ]
    )

    assert len(clusters) == 1
    assert clusters[0].recommended_action.kind == "approve_import_report_only"
