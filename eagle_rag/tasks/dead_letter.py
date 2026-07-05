"""Failure retry and dead-letter queue.

Two retry paths are provided:
- ``with_retry`` decorator: automatic exponential-backoff retry built on Celery
  ``autoretry_for``; defaults to the ``DeadLetterTask`` base class so that exhausted
  retries are auto-delivered to the dead-letter queue.
- ``retry_on_failure`` manual helper: called from a task's try/except; if the retry
  limit is not exceeded it calls ``task.retry``, otherwise it delivers to the dead-letter
  queue. Backoff: ``countdown = settings.celery.retry_backoff * (2 ** retries)``.

The ``dead_letter`` queue holds task messages whose retries are exhausted, for admin
inspection and manual replay (``drain_dead_letter`` / ``replay_dead_letter``). It is
intentionally not registered in ``task_queues`` so business workers do not consume it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from kombu import Consumer, Producer, Queue

from eagle_rag.config import get_settings
from eagle_rag.tasks.celery_app import app

__all__ = [
    "dead_letter_queue",
    "DeadLetterTask",
    "with_retry",
    "retry_on_failure",
    "send_to_dead_letter",
    "drain_dead_letter",
    "replay_dead_letter",
]

_cfg = get_settings().celery

# Dead-letter queue: holds task messages whose retries are exhausted.
dead_letter_queue = Queue("dead_letter", routing_key="dead_letter")


class DeadLetterTask(app.Task):
    """Celery task base class that delivers to the dead-letter queue on final failure.

    Pairs with ``with_retry`` (autoretry): when retries are exhausted and the exception
    propagates, ``on_failure`` is triggered.
    """

    abstract = True

    def on_failure(self, exc, task_id, args, kwargs, einfo):  # noqa: ANN001
        try:
            send_to_dead_letter(
                task_id,
                self.name,
                {"args": list(args) if args else [], "kwargs": kwargs or {}},
                repr(exc),
            )
        except Exception:  # noqa: BLE001
            # Dead-letter delivery failure must not mask the original task exception.
            pass
        return super().on_failure(exc, task_id, args, kwargs, einfo)


def with_retry(
    *,
    name: str | None = None,
    bind: bool = True,
    queue: str | None = None,
    base: type[app.Task] | None = DeadLetterTask,
    max_retries: int | None = None,
    retry_backoff: int | bool | None = None,
    **task_kwargs: Any,
) -> Callable[[Callable], Any]:
    """Decorator factory that registers a function as a Celery task with auto-retry.

    Defaults to the ``DeadLetterTask`` base class (auto-delivers to dead-letter on
    exhaustion), ``autoretry_for=(Exception,)`` and exponential backoff with base
    ``settings.celery.retry_backoff`` (same formula as ``retry_on_failure``).
    Pass ``base=None`` to disable auto dead-letter delivery and call
    ``retry_on_failure`` manually inside the task body instead.
    """
    _max_retries = max_retries if max_retries is not None else _cfg.max_retries
    _backoff = retry_backoff if retry_backoff is not None else _cfg.retry_backoff

    def decorator(func: Callable) -> Any:
        options: dict[str, Any] = {
            "bind": bind,
            "max_retries": _max_retries,
            "autoretry_for": (Exception,),
            "retry_backoff": _backoff,
            "retry_backoff_max": _cfg.retry_backoff * (2**_max_retries),
            "retry_jitter": False,
            "acks_late": True,
        }
        if base is not None:
            options["base"] = base
        if name is not None:
            options["name"] = name
        if queue is not None:
            options["queue"] = queue
        options.update(task_kwargs)
        return app.task(**options)(func)

    return decorator


def retry_on_failure(task: Any, exc: BaseException) -> None:
    """Call from a task's exception handler: ``task.retry`` if under limit, else dead-letter.

    Backoff: ``countdown = settings.celery.retry_backoff * (2 ** task.request.retries)``.
    Marks the audit as RETRYING before retrying; on exhaustion ``send_to_dead_letter``
    marks it FAILED.
    """
    from eagle_rag.tasks.state import TaskState, update_state

    job_id = task.request.id
    max_retries = task.max_retries or _cfg.max_retries
    if task.request.retries < max_retries:
        countdown = _cfg.retry_backoff * (2**task.request.retries)
        if job_id is not None:
            try:
                update_state(
                    job_id,
                    TaskState.RETRYING,
                    error=str(exc),
                    log_entry=f"retry#{task.request.retries + 1}: {exc}",
                )
            except Exception:  # noqa: BLE001
                pass
        raise task.retry(exc=exc, countdown=countdown)
    # Retries exhausted -> deliver to dead-letter queue.
    send_to_dead_letter(
        job_id,
        task.name,
        {
            "args": list(task.request.args) if task.request.args else [],
            "kwargs": dict(task.request.kwargs) if task.request.kwargs else {},
        },
        repr(exc),
    )


def send_to_dead_letter(
    job_id: str | None,
    task_name: str,
    payload: Any,
    error: str,
) -> None:
    """Publish a failed task's message to the dead-letter queue and mark the audit as FAILED."""
    from eagle_rag.tasks.state import TaskState, update_state

    body = {
        "job_id": job_id,
        "task_name": task_name,
        "payload": payload,
        "error": error,
        "timestamp": datetime.now(UTC).isoformat(),
        "retries_exhausted": True,
    }
    with app.connection_or_acquire() as conn:
        Producer(conn).publish(
            body,
            exchange="",
            routing_key="dead_letter",
            serializer="json",
            declare=[dead_letter_queue],
        )
    if job_id is not None:
        try:
            update_state(
                job_id,
                TaskState.FAILED,
                error=error,
                log_entry=f"dead-letter: {error}",
            )
        except Exception:  # noqa: BLE001
            pass


def drain_dead_letter(limit: int = 100) -> list[dict[str, Any]]:
    """Pull and ack up to ``limit`` dead-letter messages; return their bodies (admin use)."""
    messages: list[dict[str, Any]] = []

    def _on_message(body: Any, message: Any) -> None:
        messages.append(body if isinstance(body, dict) else {"body": body})
        message.ack()

    with app.connection_or_acquire() as conn:
        with Consumer(
            conn,
            [dead_letter_queue],
            accept=["json"],
            callbacks=[_on_message],
        ):
            try:
                for _ in range(limit):
                    if len(messages) >= limit:
                        break
                    conn.drain_events(timeout=0.5)
            except TimeoutError:
                pass  # Queue empty or fully drained.
    return messages


def replay_dead_letter(job_id: str) -> dict[str, Any]:
    """Find a record by job_id in the dead-letter queue and re-dispatch the original task.

    Drains the dead-letter queue, re-dispatches the matching job, and re-publishes all
    other messages back to the queue so that inspecting a single record does not drop
    other failed records. Returns the replayed dead-letter record.
    """
    records = drain_dead_letter(limit=1000)
    target: dict[str, Any] | None = None
    others: list[dict[str, Any]] = []
    for r in records:
        if target is None and isinstance(r, dict) and r.get("job_id") == job_id:
            target = r
        else:
            others.append(r)

    # Re-publish non-matching messages back to the dead-letter queue for later handling.
    if others:
        with app.connection_or_acquire() as conn:
            producer = Producer(conn)
            for r in others:
                producer.publish(
                    r,
                    exchange="",
                    routing_key="dead_letter",
                    serializer="json",
                    declare=[dead_letter_queue],
                )

    if target is None:
        raise ValueError(f"dead-letter queue has no record for job_id={job_id}")

    task_name = target.get("task_name")
    payload = target.get("payload") or {}
    if not task_name:
        raise ValueError(f"dead-letter record missing task_name: {target}")

    args: tuple = ()
    kwargs: dict[str, Any] = {}
    if isinstance(payload, dict) and "args" in payload and "kwargs" in payload:
        args = tuple(payload.get("args") or ())
        kwargs = dict(payload.get("kwargs") or {})
    elif isinstance(payload, (list, tuple)):
        args = tuple(payload)
    else:
        args = (payload,)

    app.send_task(task_name, args=args, kwargs=kwargs)
    return target
