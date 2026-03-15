"""Workspace synthesis helpers with explicit provenance."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CONTRIBUTION_LIMIT = 160
_COMPARE_STOPWORDS = frozenset(
    {
        "about",
        "across",
        "after",
        "also",
        "answer",
        "answers",
        "before",
        "between",
        "compare",
        "compared",
        "comparing",
        "different",
        "differently",
        "from",
        "into",
        "local",
        "more",
        "most",
        "need",
        "needs",
        "note",
        "notes",
        "point",
        "points",
        "question",
        "returned",
        "same",
        "selected",
        "should",
        "still",
        "than",
        "that",
        "their",
        "them",
        "these",
        "they",
        "this",
        "those",
        "through",
        "using",
        "what",
        "when",
        "where",
        "which",
        "while",
        "with",
        "without",
        "workspace",
    }
)


@dataclass(frozen=True)
class WorkspaceNotebookAnswer:
    """One per-notebook answer ready for local workspace synthesis."""

    notebook_id: str
    notebook_title: str | None
    answer_text: str


@dataclass(frozen=True)
class WorkspaceProvenanceRecord:
    """One provenance contribution carried into a synthesized workspace answer."""

    notebook_id: str
    notebook_title: str | None
    contribution: str


@dataclass(frozen=True)
class WorkspaceContradictionRecord:
    """One pair of notebook positions that disagree on the same topical terms."""

    id: str
    topic: str
    shared_terms: tuple[str, ...]
    left_notebook_id: str
    left_notebook_title: str | None
    left_position: str
    right_notebook_id: str
    right_notebook_title: str | None
    right_position: str
    explanation: str


@dataclass(frozen=True)
class WorkspaceSynthesisResult:
    """Deterministic local workspace synthesis output."""

    answer: str
    provenance: tuple[WorkspaceProvenanceRecord, ...]


def _normalize_text(value: str) -> str:
    return " ".join(value.split()).strip()


def _contribution_excerpt(value: str) -> str:
    normalized = _normalize_text(value)
    if not normalized:
        return "No answer returned."
    first_sentence = _SENTENCE_RE.split(normalized, maxsplit=1)[0]
    if len(first_sentence) <= _CONTRIBUTION_LIMIT:
        return first_sentence
    return first_sentence[: _CONTRIBUTION_LIMIT - 3].rstrip() + "..."


def _compare_tokens(value: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in _TOKEN_RE.findall(value.casefold())
        if len(token) > 2 and token not in _COMPARE_STOPWORDS
    )


def _shared_topic_terms(left: str, right: str) -> tuple[str, ...]:
    right_terms = set(_compare_tokens(right))
    return tuple(dict.fromkeys(token for token in _compare_tokens(left) if token in right_terms))


def _topic_label(shared_terms: tuple[str, ...]) -> str:
    if not shared_terms:
        return "the same topic"
    return " ".join(shared_terms[:2])


def _contradiction_id(
    left: WorkspaceProvenanceRecord,
    right: WorkspaceProvenanceRecord,
    *,
    left_position: str,
    right_position: str,
) -> str:
    encoded = "\n".join(
        (
            left.notebook_id,
            right.notebook_id,
            left_position.casefold(),
            right_position.casefold(),
        )
    ).encode("utf-8")
    return f"wcx_{hashlib.sha1(encoded).hexdigest()[:16]}"


def detect_workspace_contradictions(
    answers: tuple[WorkspaceNotebookAnswer, ...],
) -> tuple[WorkspaceContradictionRecord, ...]:
    """Detect notebook pairs that disagree on the same topical terms."""

    contradictions: list[WorkspaceContradictionRecord] = []
    for index, left in enumerate(answers):
        left_answer = _normalize_text(left.answer_text)
        left_position = _contribution_excerpt(left.answer_text)
        if not left_position or left_position == "No answer returned.":
            continue

        for right in answers[index + 1 :]:
            right_answer = _normalize_text(right.answer_text)
            right_position = _contribution_excerpt(right.answer_text)
            if not right_position or right_position == "No answer returned.":
                continue
            if left_answer.casefold() == right_answer.casefold():
                continue

            shared_terms = _shared_topic_terms(left_answer, right_answer)
            if len(shared_terms) < 2:
                continue

            topic = _topic_label(shared_terms)
            left_title = left.notebook_title or left.notebook_id
            right_title = right.notebook_title or right.notebook_id
            contradictions.append(
                WorkspaceContradictionRecord(
                    id=_contradiction_id(
                        WorkspaceProvenanceRecord(
                            notebook_id=left.notebook_id,
                            notebook_title=left.notebook_title,
                            contribution=left_position,
                        ),
                        WorkspaceProvenanceRecord(
                            notebook_id=right.notebook_id,
                            notebook_title=right.notebook_title,
                            contribution=right_position,
                        ),
                        left_position=left_position,
                        right_position=right_position,
                    ),
                    topic=topic,
                    shared_terms=shared_terms,
                    left_notebook_id=left.notebook_id,
                    left_notebook_title=left.notebook_title,
                    left_position=left_position,
                    right_notebook_id=right.notebook_id,
                    right_notebook_title=right.notebook_title,
                    right_position=right_position,
                    explanation=(
                        f"{left_title} and {right_title} answer {topic} differently, "
                        "so the workspace may need a gap-fill follow-up."
                    ),
                )
            )
    return tuple(contradictions)


def synthesize_workspace_answer(
    question: str,
    answers: list[WorkspaceNotebookAnswer],
) -> WorkspaceSynthesisResult:
    """Combine per-notebook answers into a transparent local workspace result."""
    if not answers:
        return WorkspaceSynthesisResult(
            answer=f'No notebook answers were available for workspace question "{question}".',
            provenance=(),
        )

    provenance = tuple(
        WorkspaceProvenanceRecord(
            notebook_id=answer.notebook_id,
            notebook_title=answer.notebook_title,
            contribution=_contribution_excerpt(answer.answer_text),
        )
        for answer in answers
    )
    if len(answers) == 1:
        return WorkspaceSynthesisResult(
            answer=_normalize_text(answers[0].answer_text),
            provenance=provenance,
        )

    lines = ["Workspace synthesis:"]
    for contribution in provenance:
        title = contribution.notebook_title or contribution.notebook_id
        lines.append(f"- {title}: {contribution.contribution}")
    return WorkspaceSynthesisResult(answer="\n".join(lines), provenance=provenance)


__all__ = [
    "WorkspaceContradictionRecord",
    "WorkspaceNotebookAnswer",
    "WorkspaceProvenanceRecord",
    "WorkspaceSynthesisResult",
    "detect_workspace_contradictions",
    "synthesize_workspace_answer",
]
