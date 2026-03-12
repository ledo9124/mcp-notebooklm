"""Run-state transition engine for BA workflow execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from .models import (
    RunEventRecord,
    RunEventType,
    RunStateSnapshot,
    RunStatus,
    RunStep,
    RunStepRecord,
    RunStepStatus,
)
from .run_store import BARunStore

MODULE_PURPOSE = (
    "Own explicit BA workflow run-state transitions, resumability rules, and "
    "audit-friendly transition events."
)

OWNS = (
    "Finite run-status transition rules over persisted BA run snapshots",
    "Step-level retry, halt, degraded, and completion semantics",
    "Audit-friendly event emission aligned with persisted run-state snapshots",
)

MUST_NOT_OWN = (
    "Filesystem layout resolution outside BARunStore",
    "NotebookLM transport or prompt execution",
    "High-level pipeline orchestration policy",
    "Rendered bundle validation logic",
)

RUN_STEP_SEQUENCE: tuple[RunStep, ...] = tuple(RunStep)

_TERMINAL_RUN_STATUSES = {RunStatus.COMPLETED, RunStatus.FAILED}
_PAUSED_RUN_STATUSES = {RunStatus.DEGRADED, RunStatus.HALTED}
_RETRYABLE_STEP_STATUSES = {
    RunStepStatus.DEGRADED,
    RunStepStatus.FAILED,
    RunStepStatus.HALTED,
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunStateTransitionError(RuntimeError):
    """Raised when a requested run-state transition is invalid."""


class BARunStateMachine:
    """State-machine helper over a persisted BA run snapshot."""

    def __init__(
        self,
        snapshot: RunStateSnapshot,
        *,
        store: BARunStore | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self._state = snapshot.model_copy(deep=True)
        self._store = store
        self._clock = clock or _utc_now_iso
        if self._store is not None:
            self._store._validate_run_state_identity(self._state)  # noqa: SLF001

    @classmethod
    def from_store(
        cls,
        store: BARunStore,
        *,
        clock: Callable[[], str] | None = None,
    ) -> "BARunStateMachine":
        """Load an existing run snapshot from the run store."""

        return cls(store.load_run_state(), store=store, clock=clock)

    @property
    def state(self) -> RunStateSnapshot:
        """Return a defensive copy of the current run snapshot."""

        return self._state.model_copy(deep=True)

    def start_run(
        self,
        *,
        message: str = "BA run started",
        metadata: Mapping[str, Any] | None = None,
        note: str | None = None,
    ) -> RunStateSnapshot:
        """Move the run from pending into its explicit START_RUN step."""

        if self._state.status is not RunStatus.PENDING:
            msg = "run can only be started from PENDING"
            raise RunStateTransitionError(msg)
        return self.start_step(
            RunStep.START_RUN,
            message=message,
            metadata=metadata,
            note=note,
        )

    def start_step(
        self,
        step: RunStep,
        *,
        message: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        note: str | None = None,
    ) -> RunStateSnapshot:
        """Mark a step as actively running."""

        self._ensure_not_terminal()
        if self._state.status in _PAUSED_RUN_STATUSES:
            msg = "resume or retry the paused run before starting another step"
            raise RunStateTransitionError(msg)

        current_record = self.current_step_record()
        if current_record is not None and current_record.status is RunStepStatus.RUNNING:
            msg = f"step {self._state.current_step.value} is already running"
            raise RunStateTransitionError(msg)

        record = self._step_record(step, create=True)
        if record.status is RunStepStatus.RUNNING:
            msg = f"step {step.value} is already running"
            raise RunStateTransitionError(msg)
        if record.status is RunStepStatus.COMPLETED:
            msg = f"step {step.value} is already completed; use retry semantics for reruns"
            raise RunStateTransitionError(msg)
        if record.status in _RETRYABLE_STEP_STATUSES:
            msg = f"step {step.value} is paused or failed; use retry_step to start another attempt"
            raise RunStateTransitionError(msg)

        timestamp = self._clock()
        record.status = RunStepStatus.RUNNING
        record.started_at = timestamp
        record.completed_at = None
        record.halt_reason = None
        self._merge_metadata(record, metadata)
        self._append_note(record, note)

        self._state.status = RunStatus.RUNNING
        self._state.current_step = step
        self._state.halt_reason = None
        self._append_event(
            RunEventType.STARTED,
            step=step,
            message=message or f"{step.value} started",
            created_at=timestamp,
            details=self._step_details(record, metadata),
        )
        return self._save()

    def complete_step(
        self,
        step: RunStep | None = None,
        *,
        message: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        note: str | None = None,
    ) -> RunStateSnapshot:
        """Mark the active step as completed."""

        self._ensure_not_terminal()
        step = step or self._require_current_step()
        record = self._step_record(step)
        if record.status is not RunStepStatus.RUNNING:
            msg = f"step {step.value} is not running"
            raise RunStateTransitionError(msg)

        timestamp = self._clock()
        record.status = RunStepStatus.COMPLETED
        record.completed_at = timestamp
        record.halt_reason = None
        self._merge_metadata(record, metadata)
        self._append_note(record, note)

        self._state.status = RunStatus.RUNNING
        if self._state.current_step is step:
            self._state.current_step = None
        self._state.halt_reason = None
        self._append_event(
            RunEventType.COMPLETED,
            step=step,
            message=message or f"{step.value} completed",
            created_at=timestamp,
            details=self._step_details(record, metadata),
        )
        return self._save()

    def mark_degraded(
        self,
        reason: str,
        *,
        step: RunStep | None = None,
        message: str | None = None,
        warning: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        note: str | None = None,
    ) -> RunStateSnapshot:
        """Pause the run in an inspectable degraded state."""

        self._ensure_not_terminal()
        step = step or self._require_current_step()
        record = self._step_record(step)
        if record.status is not RunStepStatus.RUNNING:
            msg = f"step {step.value} is not running"
            raise RunStateTransitionError(msg)

        timestamp = self._clock()
        record.status = RunStepStatus.DEGRADED
        record.completed_at = timestamp
        record.halt_reason = reason
        self._merge_metadata(record, metadata)
        self._append_note(record, note)

        self._state.status = RunStatus.DEGRADED
        self._state.current_step = step
        self._state.halt_reason = None
        self._append_warning(warning or reason)
        self._append_event(
            RunEventType.DEGRADED,
            step=step,
            message=message or f"{step.value} degraded",
            created_at=timestamp,
            details=self._step_details(record, metadata, reason=reason),
        )
        return self._save()

    def halt(
        self,
        reason: str,
        *,
        step: RunStep | None = None,
        message: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        note: str | None = None,
    ) -> RunStateSnapshot:
        """Pause the run with an explicit halt reason."""

        self._ensure_not_terminal()
        step = step or self._state.current_step
        timestamp = self._clock()

        details = dict(metadata or {})
        details["reason"] = reason
        if step is not None:
            record = self._step_record(step, create=True)
            if record.status is RunStepStatus.RUNNING and record.started_at is None:
                record.started_at = timestamp
            record.status = RunStepStatus.HALTED
            record.completed_at = timestamp
            record.halt_reason = reason
            self._append_note(record, note)
            self._merge_metadata(record, metadata)
            details = self._step_details(record, metadata, reason=reason)

        self._state.status = RunStatus.HALTED
        self._state.current_step = step
        self._state.halt_reason = reason
        self._append_event(
            RunEventType.HALTED,
            step=step,
            message=message or f"{reason}",
            created_at=timestamp,
            details=details,
        )
        return self._save()

    def resume(
        self,
        *,
        step: RunStep | None = None,
        message: str = "Run resumed",
        metadata: Mapping[str, Any] | None = None,
    ) -> RunStateSnapshot:
        """Resume a previously halted or degraded run without starting a new attempt."""

        if self._state.status not in _PAUSED_RUN_STATUSES:
            msg = "only HALTED or DEGRADED runs can be resumed"
            raise RunStateTransitionError(msg)

        timestamp = self._clock()
        previous_status = self._state.status
        resumed_step = step or self._state.current_step

        self._state.status = RunStatus.RUNNING
        self._state.current_step = resumed_step
        self._state.halt_reason = None
        self._append_event(
            RunEventType.RESUMED,
            step=resumed_step,
            message=message,
            created_at=timestamp,
            details={
                "from_status": previous_status.value,
                **dict(metadata or {}),
            },
        )
        return self._save()

    def retry_step(
        self,
        step: RunStep | None = None,
        *,
        message: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        note: str | None = None,
    ) -> RunStateSnapshot:
        """Start a new attempt for a previously paused or failed step."""

        self._ensure_not_terminal()
        step = step or self._require_current_step()
        record = self._step_record(step)
        if record.status not in _RETRYABLE_STEP_STATUSES:
            msg = f"step {step.value} is not retryable from status {record.status.value}"
            raise RunStateTransitionError(msg)

        timestamp = self._clock()
        record.attempts += 1
        record.status = RunStepStatus.RUNNING
        record.started_at = timestamp
        record.completed_at = None
        record.halt_reason = None
        self._merge_metadata(record, metadata)
        self._append_note(record, note)

        self._state.status = RunStatus.RUNNING
        self._state.current_step = step
        self._state.halt_reason = None
        self._append_event(
            RunEventType.RETRIED,
            step=step,
            message=message or f"{step.value} retried",
            created_at=timestamp,
            details=self._step_details(record, metadata),
        )
        return self._save()

    def fail(
        self,
        reason: str,
        *,
        step: RunStep | None = None,
        message: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        note: str | None = None,
    ) -> RunStateSnapshot:
        """Move the run into a terminal failed state."""

        self._ensure_not_terminal()
        step = step or self._state.current_step
        timestamp = self._clock()
        details = dict(metadata or {})
        details["reason"] = reason
        details["terminal_status"] = RunStatus.FAILED.value

        if step is not None:
            record = self._step_record(step, create=True)
            if record.started_at is None:
                record.started_at = timestamp
            record.status = RunStepStatus.FAILED
            record.completed_at = timestamp
            record.halt_reason = reason
            self._merge_metadata(record, metadata)
            self._append_note(record, note)
            details = self._step_details(
                record,
                metadata,
                reason=reason,
                terminal_status=RunStatus.FAILED.value,
            )

        self._state.status = RunStatus.FAILED
        self._state.current_step = step
        self._state.halt_reason = reason
        self._append_event(
            RunEventType.HALTED,
            step=step,
            message=message or f"Run failed: {reason}",
            created_at=timestamp,
            details=details,
        )
        return self._save()

    def complete_run(
        self,
        *,
        message: str = "BA run completed",
        metadata: Mapping[str, Any] | None = None,
    ) -> RunStateSnapshot:
        """Mark the run as completed once no step is actively running."""

        self._ensure_not_terminal()
        current_record = self.current_step_record()
        if current_record is not None and current_record.status is RunStepStatus.RUNNING:
            msg = "cannot complete the run while a step is still running"
            raise RunStateTransitionError(msg)

        timestamp = self._clock()
        self._state.status = RunStatus.COMPLETED
        self._state.current_step = None
        self._state.halt_reason = None
        self._append_event(
            RunEventType.COMPLETED,
            step=None,
            message=message,
            created_at=timestamp,
            details={"run_status": RunStatus.COMPLETED.value, **dict(metadata or {})},
        )
        return self._save()

    def current_step_record(self) -> RunStepRecord | None:
        """Return the currently referenced step record, if one exists."""

        if self._state.current_step is None:
            return None
        return self._step_record(self._state.current_step, create=False)

    def can_resume(self) -> bool:
        """Return whether the run is in a resumable paused state."""

        return self._state.status in _PAUSED_RUN_STATUSES

    def is_terminal(self) -> bool:
        """Return whether the run has reached a terminal state."""

        return self._state.status in _TERMINAL_RUN_STATUSES

    def _save(self) -> RunStateSnapshot:
        if self._store is not None:
            self._store.save_run_state(self._state)
        return self.state

    def _ensure_not_terminal(self) -> None:
        if self.is_terminal():
            msg = f"run is already terminal: {self._state.status.value}"
            raise RunStateTransitionError(msg)

    def _step_record(
        self,
        step: RunStep,
        *,
        create: bool = False,
    ) -> RunStepRecord:
        for record in self._state.steps:
            if record.step is step:
                return record
        if not create:
            msg = f"step {step.value} does not exist in the run state"
            raise RunStateTransitionError(msg)
        record = RunStepRecord(step=step)
        self._state.steps.append(record)
        return record

    def _require_current_step(self) -> RunStep:
        if self._state.current_step is None:
            msg = "run has no current_step"
            raise RunStateTransitionError(msg)
        return self._state.current_step

    def _append_event(
        self,
        event_type: RunEventType,
        *,
        step: RunStep | None,
        message: str,
        created_at: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self._state.events.append(
            RunEventRecord(
                event_type=event_type,
                step=step,
                message=message,
                created_at=created_at,
                details=dict(details or {}),
            )
        )

    def _append_note(self, record: RunStepRecord, note: str | None) -> None:
        if note and note not in record.notes:
            record.notes.append(note)

    def _append_warning(self, warning: str) -> None:
        if warning not in self._state.warnings:
            self._state.warnings.append(warning)

    def _merge_metadata(
        self,
        record: RunStepRecord,
        metadata: Mapping[str, Any] | None,
    ) -> None:
        if metadata:
            record.metadata.update(dict(metadata))

    def _step_details(
        self,
        record: RunStepRecord,
        metadata: Mapping[str, Any] | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        details = {
            "attempts": record.attempts,
            "run_status": self._state.status.value,
            "step_status": record.status.value,
        }
        if metadata:
            details.update(dict(metadata))
        details.update(extra)
        return details


def next_run_step(step: RunStep) -> RunStep | None:
    """Return the next configured run step, or ``None`` for the terminal step."""

    try:
        index = RUN_STEP_SEQUENCE.index(step)
    except ValueError as exc:
        msg = f"unknown run step: {step!r}"
        raise RunStateTransitionError(msg) from exc
    if index + 1 >= len(RUN_STEP_SEQUENCE):
        return None
    return RUN_STEP_SEQUENCE[index + 1]


__all__ = [
    "BARunStateMachine",
    "MODULE_PURPOSE",
    "MUST_NOT_OWN",
    "OWNS",
    "RUN_STEP_SEQUENCE",
    "RunStateTransitionError",
    "next_run_step",
]
