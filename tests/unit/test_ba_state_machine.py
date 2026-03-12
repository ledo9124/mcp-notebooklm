"""Unit tests for BA run-state transition semantics."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from notebooklm_mcp.ba.models import (
    RunEventType,
    RunStateSnapshot,
    RunStatus,
    RunStep,
    RunStepRecord,
    RunStepStatus,
)
from notebooklm_mcp.ba.run_store import BARunStore
from notebooklm_mcp.ba.state_machine import (
    BARunStateMachine,
    RunStateTransitionError,
    next_run_step,
)


def _clock(*timestamps: str) -> Iterator[str]:
    return iter(timestamps)


def _store(tmp_path: Path, *, run_id: str = "run-001") -> BARunStore:
    store = BARunStore(
        workspace_root=tmp_path,
        feature_key="customer-create",
        run_id=run_id,
    )
    store.create()
    return store


def test_state_machine_starts_and_completes_steps_with_persistence(tmp_path: Path) -> None:
    store = _store(tmp_path)
    machine = BARunStateMachine.from_store(
        store,
        clock=_clock(
            "2026-03-12T10:00:00+00:00",
            "2026-03-12T10:00:05+00:00",
            "2026-03-12T10:00:10+00:00",
        ).__next__,
    )

    machine.start_run(metadata={"trigger": "manual"})
    machine.complete_step(RunStep.START_RUN)
    machine.start_step(
        RunStep.REGISTER_SOURCES,
        metadata={"source_keys": ["ba-pdf"]},
        note="ready for registration",
    )

    state = store.load_run_state()
    assert state.status is RunStatus.RUNNING
    assert state.current_step is RunStep.REGISTER_SOURCES
    assert [record.step for record in state.steps] == [
        RunStep.START_RUN,
        RunStep.REGISTER_SOURCES,
    ]
    assert state.steps[0].status is RunStepStatus.COMPLETED
    assert state.steps[0].started_at == "2026-03-12T10:00:00+00:00"
    assert state.steps[0].completed_at == "2026-03-12T10:00:05+00:00"
    assert state.steps[1].status is RunStepStatus.RUNNING
    assert state.steps[1].metadata == {"source_keys": ["ba-pdf"]}
    assert state.steps[1].notes == ["ready for registration"]
    assert [event.event_type for event in state.events] == [
        RunEventType.STARTED,
        RunEventType.COMPLETED,
        RunEventType.STARTED,
    ]
    assert state.events[-1].details["source_keys"] == ["ba-pdf"]

    audit = store.load_run_audit()
    assert len(audit.entries) == 4
    assert audit.entries[-1].snapshot.current_step is RunStep.REGISTER_SOURCES


def test_state_machine_marks_degraded_step_and_can_resume(tmp_path: Path) -> None:
    store = _store(tmp_path, run_id="run-002")
    machine = BARunStateMachine.from_store(
        store,
        clock=_clock(
            "2026-03-12T10:10:00+00:00",
            "2026-03-12T10:10:05+00:00",
            "2026-03-12T10:10:10+00:00",
            "2026-03-12T10:10:15+00:00",
            "2026-03-12T10:10:20+00:00",
        ).__next__,
    )

    machine.start_run()
    machine.complete_step(RunStep.START_RUN)
    machine.start_step(RunStep.ASSESS_SOURCE_QUALITY)
    machine.mark_degraded(
        "OCR quality too low",
        warning="OCR quality too low",
        metadata={"source_key": "ba-pdf"},
    )

    degraded = store.load_run_state()
    assert degraded.status is RunStatus.DEGRADED
    assert degraded.current_step is RunStep.ASSESS_SOURCE_QUALITY
    assert degraded.steps[-1].status is RunStepStatus.DEGRADED
    assert degraded.steps[-1].halt_reason == "OCR quality too low"
    assert degraded.steps[-1].completed_at == "2026-03-12T10:10:15+00:00"
    assert degraded.warnings == ["OCR quality too low"]
    assert degraded.events[-1].event_type is RunEventType.DEGRADED
    assert degraded.events[-1].details["reason"] == "OCR quality too low"

    machine.resume(message="clarification note attached")

    resumed = store.load_run_state()
    assert resumed.status is RunStatus.RUNNING
    assert resumed.current_step is RunStep.ASSESS_SOURCE_QUALITY
    assert resumed.halt_reason is None
    assert resumed.steps[-1].status is RunStepStatus.DEGRADED
    assert resumed.events[-1].event_type is RunEventType.RESUMED
    assert resumed.events[-1].details["from_status"] == RunStatus.DEGRADED.value


def test_state_machine_retry_increments_attempts_after_halt(tmp_path: Path) -> None:
    store = _store(tmp_path, run_id="run-003")
    machine = BARunStateMachine.from_store(
        store,
        clock=_clock(
            "2026-03-12T10:20:00+00:00",
            "2026-03-12T10:20:05+00:00",
            "2026-03-12T10:20:10+00:00",
            "2026-03-12T10:20:15+00:00",
            "2026-03-12T10:20:20+00:00",
        ).__next__,
    )

    machine.start_run()
    machine.complete_step(RunStep.START_RUN)
    machine.start_step(RunStep.INGEST_AND_WAIT)
    machine.halt("NotebookLM ingestion timeout", metadata={"source_key": "ba-pdf"})
    machine.retry_step(metadata={"retry_reason": "operator resumed"})

    state = store.load_run_state()
    record = state.steps[-1]
    assert state.status is RunStatus.RUNNING
    assert state.current_step is RunStep.INGEST_AND_WAIT
    assert state.halt_reason is None
    assert record.status is RunStepStatus.RUNNING
    assert record.attempts == 2
    assert record.started_at == "2026-03-12T10:20:20+00:00"
    assert record.completed_at is None
    assert [event.event_type for event in state.events[-2:]] == [
        RunEventType.HALTED,
        RunEventType.RETRIED,
    ]
    assert state.events[-1].details["retry_reason"] == "operator resumed"


def test_state_machine_fail_is_terminal_and_blocks_resume(tmp_path: Path) -> None:
    store = _store(tmp_path, run_id="run-004")
    machine = BARunStateMachine.from_store(
        store,
        clock=_clock(
            "2026-03-12T10:30:00+00:00",
            "2026-03-12T10:30:05+00:00",
            "2026-03-12T10:30:10+00:00",
        ).__next__,
    )

    machine.start_run()
    machine.fail("manifest could not be normalized", step=RunStep.START_RUN)

    state = store.load_run_state()
    assert state.status is RunStatus.FAILED
    assert state.current_step is RunStep.START_RUN
    assert state.halt_reason == "manifest could not be normalized"
    assert state.steps[0].status is RunStepStatus.FAILED
    assert state.events[-1].event_type is RunEventType.HALTED
    assert state.events[-1].details["terminal_status"] == RunStatus.FAILED.value

    with pytest.raises(RunStateTransitionError):
        machine.resume()

    with pytest.raises(RunStateTransitionError):
        machine.start_step(RunStep.REGISTER_SOURCES)


def test_state_machine_completes_run_and_reports_next_step() -> None:
    machine = BARunStateMachine(
        RunStateSnapshot(
            run_id="run-005",
            feature_key="customer-create",
            status=RunStatus.RUNNING,
            steps=[
                RunStepRecord(
                    step=RunStep.VALIDATE_BUNDLE,
                    status=RunStepStatus.COMPLETED,
                    started_at="2026-03-12T10:40:00+00:00",
                    completed_at="2026-03-12T10:40:05+00:00",
                )
            ],
        ),
        clock=_clock("2026-03-12T10:40:10+00:00").__next__,
    )

    completed = machine.complete_run(metadata={"validated_screens": 3})

    assert completed.status is RunStatus.COMPLETED
    assert completed.current_step is None
    assert completed.events[-1].event_type is RunEventType.COMPLETED
    assert completed.events[-1].details["validated_screens"] == 3
    assert next_run_step(RunStep.START_RUN) is RunStep.REGISTER_SOURCES
    assert next_run_step(RunStep.VALIDATE_BUNDLE) is None
