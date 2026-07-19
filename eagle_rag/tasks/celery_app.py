"""Eagle-RAG Celery app and queue configuration.

Defines three pipeline queues (router / knowhere / pixelrag) and routes tasks via
``settings.celery.task_routes``. Retry and timeout params are read from config; ingest
task modules are explicitly registered through the ``include=`` of ``Celery(...)`` below,
so they are imported at worker startup and bound by the ``@app.task`` decorator.

The module does not connect to the broker/backend at import time; connections are
established only when the worker starts or a task is dispatched.
"""

from __future__ import annotations

from celery import Celery
from celery.signals import task_prerun, worker_init, worker_process_init
from kombu import Queue

from eagle_rag.config import get_settings

__all__ = ["app", "celery_app", "autodiscover_tasks"]

_BASE_CELERY_MODULES = [
    "eagle_rag.ingest.router",
    "eagle_rag.ingest.knowhere_adapter",
    "eagle_rag.ingest.pixelrag_adapter",
    "eagle_rag.kb.lifecycle",
]

_IMPORTED_MODULES: set[str] = set()

_cfg = get_settings().celery

# ``include`` loads task modules after this module finishes initializing, avoiding
# the circular import ``celery_app → task module → dead_letter → celery_app``.
app = Celery(
    "eagle_rag",
    broker=_cfg.broker_url,
    backend=_cfg.result_backend,
    include=list(_BASE_CELERY_MODULES),
)

# Three pipeline queues: router (dispatch) / knowhere (structured parsing)
# / pixelrag (visual rendering).
app.conf.task_queues = (
    Queue("router_queue", routing_key="router_queue"),
    Queue("knowhere_queue", routing_key="knowhere_queue"),
    Queue("pixelrag_queue", routing_key="pixelrag_queue"),
)
app.conf.task_default_queue = "router_queue"
app.conf.task_default_routing_key = "router_queue"
app.conf.task_default_exchange = ""

# Route tasks by name to the matching queue (from settings.yaml task_routes).
app.conf.task_routes = _cfg.task_routes

# Reliability: ack only after completion, no prefetch (avoids long-task backlog),
# reject on worker loss so the message is requeued.
app.conf.task_acks_late = True
app.conf.worker_prefetch_multiplier = 1
app.conf.task_reject_on_worker_lost = True
# Celery 6.0+: explicit startup broker retry (replaces implicit broker_connection_retry).
app.conf.broker_connection_retry_on_startup = True

# Retry: default backoff interval and max retries (overridable via self.retry in-task).
app.conf.task_default_retry_delay = _cfg.retry_backoff
app.conf.task_default_max_retries = _cfg.max_retries

# Time limits: hard 1h, soft 55m (5m buffer to finalize and handle SoftTimeLimitExceeded).
app.conf.task_time_limit = 3600
app.conf.task_soft_time_limit = 3300

# Standardize on JSON serialization so result is consumable across languages.
app.conf.task_serializer = "json"
app.conf.result_serializer = "json"
app.conf.accept_content = ["json"]

# Celery beat: sample queue lengths into metric_samples every 30s.
# The beat schedule only takes effect in the celery beat process and does not affect
# workers; ``eagle_rag.admin.metrics`` registers the task name via ``@celery_app.task``,
# so beat dispatches by name (no autodiscover needed).
app.conf.beat_schedule = {
    "sample-queue-metrics": {
        "task": "eagle_rag.admin.metrics.sample_queue_metrics",
        "schedule": 30.0,
    },
}


def autodiscover_tasks() -> None:
    """Import Celery task modules from PluginManager (idempotent)."""
    import importlib

    try:
        from eagle_rag.plugins import get_plugin_manager

        modules = get_plugin_manager().collect_celery_modules()
    except Exception:  # noqa: BLE001
        modules = list(_BASE_CELERY_MODULES)

    for module in modules:
        if module in _IMPORTED_MODULES:
            continue
        importlib.import_module(module)
        _IMPORTED_MODULES.add(module)


# Telemetry: configure dual logger + tracing on worker subprocess startup; register
# Celery signals to continue traces. telemetry.tracing.send_task_with_trace lazily
# imports celery_app, so we import telemetry after constructing app to avoid a cycle.
from eagle_rag.telemetry import (  # noqa: E402
    configure_telemetry,
    register_celery_signals,
)


def _ensure_app_on_sys_path() -> None:
    """Guarantee repo root ``/app`` is importable for in-repo ``plugins.*`` modules."""
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]  # /app/eagle_rag/tasks -> /app
    root_s = str(root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)


@worker_init.connect
def _on_worker_init(**kwargs) -> None:  # noqa: ANN001
    """Import plugin Celery modules in the worker main process before consuming."""
    import logging

    _ensure_app_on_sys_path()
    try:
        from eagle_rag.plugins import get_plugin_manager

        get_plugin_manager()
        autodiscover_tasks()
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception("worker_init plugin bootstrap failed")


@worker_process_init.connect
def _init_worker(**kwargs) -> None:  # noqa: ANN001
    """Configure telemetry (dual logger + tracing) on worker subprocess startup."""
    import logging

    from eagle_rag.config import get_settings

    _ensure_app_on_sys_path()
    try:
        configure_telemetry(get_settings())
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception("worker_process_init telemetry failed")
    try:
        from eagle_rag.plugins import get_plugin_manager, reset_plugin_manager

        # Prefork children must not reuse a parent-cached manager built before
        # sys.path / profile env were fully settled.
        reset_plugin_manager()
        get_plugin_manager()
        autodiscover_tasks()
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception("worker_process_init plugin bootstrap failed")


@task_prerun.connect
def _ensure_telemetry_on_task(**kwargs) -> None:  # noqa: ANN001
    """Fallback: ensure telemetry is configured before each task runs.

    ``worker_process_init`` may not fire reliably in all pool/fork combinations
    (e.g. when Celery forks after import-time side effects set ``_configured``).
    This signal fires in the actual task execution context, so telemetry is
    guaranteed to be initialized. ``configure_telemetry`` is idempotent.
    """
    from eagle_rag.config import get_settings
    from eagle_rag.telemetry.logging_setup import _enabled

    if not _enabled:
        try:
            configure_telemetry(get_settings())
        except Exception:  # noqa: BLE001
            pass


register_celery_signals(app)

celery_app = app


if __name__ == "__main__":
    app.start()
