"""State-machine helpers for ingest retries and worker redelivery."""

from __future__ import annotations

import pytest

from eagle_rag.tasks.state import (
    InvalidStateTransitionError,
    TaskState,
    downstream_owns_lifecycle,
    prepare_rerun,
    transition,
)


def test_downstream_owns_lifecycle_active_states() -> None:
    assert downstream_owns_lifecycle(TaskState.EMBEDDING) is True
    assert downstream_owns_lifecycle(TaskState.INDEXING) is True
    assert downstream_owns_lifecycle(TaskState.RETRYING) is True
    assert downstream_owns_lifecycle("indexing") is True


def test_downstream_owns_lifecycle_inactive_states() -> None:
    assert downstream_owns_lifecycle(TaskState.PENDING) is False
    assert downstream_owns_lifecycle(TaskState.RENDERING) is False
    assert downstream_owns_lifecycle(TaskState.FAILED) is False
    assert downstream_owns_lifecycle(TaskState.SUCCESS) is False


def test_transition_indexing_to_rendering_is_illegal() -> None:
    with pytest.raises(InvalidStateTransitionError, match="indexing -> rendering"):
        transition(TaskState.INDEXING, TaskState.RENDERING)


def test_prepare_rerun_bridges_indexing_to_retrying(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[TaskState, TaskState]] = []

    def _fake_fetchone(sql: str, params: tuple[str, ...]) -> tuple[str]:
        del sql, params
        return (TaskState.INDEXING.value,)

    def _fake_update(job_id: str, state: TaskState, **kwargs: object) -> None:
        del job_id, kwargs
        if calls:
            from_state = calls[-1][1]
        else:
            from_state = TaskState.INDEXING
        calls.append((from_state, state))

    monkeypatch.setattr("eagle_rag.tasks.state.sync_fetchone", _fake_fetchone)
    monkeypatch.setattr("eagle_rag.tasks.state.update_state", _fake_update)

    result = prepare_rerun("job-1")

    assert result == TaskState.RETRYING
    assert calls[-1] == (TaskState.INDEXING, TaskState.RETRYING)
    transition(TaskState.RETRYING, TaskState.RENDERING)


def test_prepare_rerun_failed_to_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_fetchone(sql: str, params: tuple[str, ...]) -> tuple[str]:
        del sql, params
        return (TaskState.FAILED.value,)

    updates: list[TaskState] = []

    def _fake_update(job_id: str, state: TaskState, **kwargs: object) -> None:
        del job_id, kwargs
        updates.append(state)

    monkeypatch.setattr("eagle_rag.tasks.state.sync_fetchone", _fake_fetchone)
    monkeypatch.setattr("eagle_rag.tasks.state.update_state", _fake_update)

    result = prepare_rerun("job-2")

    assert result == TaskState.PENDING
    assert updates == [TaskState.PENDING]
