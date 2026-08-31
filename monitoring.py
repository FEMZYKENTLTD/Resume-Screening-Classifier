"""
Prometheus instrumentation for API + worker.

- API: request counters/latency via middleware in api_server.py, /metrics endpoint
- Worker: task counters, duration histogram, last-score gauge; optionally
  exposes its own /metrics on WORKER_METRICS_PORT (default off)

Import-safe: if prometheus-client is missing, everything is a no-op.
"""

import os
import threading

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
        start_http_server,
    )
    _OK = True
except ImportError:                            # pragma: no cover
    _OK = False


if _OK:
    registry = CollectorRegistry()

    http_requests_total = Counter(
        "http_requests_total", "HTTP requests by route",
        ["method", "path", "status"], registry=registry,
    )
    http_request_seconds = Histogram(
        "http_request_seconds", "HTTP request latency",
        ["method", "path"], registry=registry,
        buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
    )
    resume_tasks_total = Counter(
        "resume_tasks_total", "Resume analysis tasks by final status",
        ["status"], registry=registry,
    )
    resume_task_seconds = Histogram(
        "resume_task_seconds", "Resume task processing time",
        registry=registry, buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60),
    )
    resume_last_match_score = Gauge(
        "resume_last_match_score", "Most recent resume-JD match score (0-100)",
        registry=registry,
    )

    # Pre-register children so /metrics exposes stable series from boot
    # (prometheus only serializes counters that have been touched).
    for _status in ("completed", "failed"):
        resume_tasks_total.labels(status=_status)
    resume_last_match_score.set(0)
else:                                          # pragma: no cover
    registry = None


def metrics_response():
    """(body, content_type) for the /metrics endpoint."""
    if not _OK:                                # pragma: no cover
        return b"# prometheus-client not installed\n", "text/plain"
    return generate_latest(registry), CONTENT_TYPE_LATEST


def init_metrics() -> None:
    """Called by the API on startup: pre-register label children so every
    series is present from the first scrape (Prometheus only serializes
    counters that have been touched)."""
    if not _OK:                                # pragma: no cover
        return
    for _status in ("completed", "failed"):
        resume_tasks_total.labels(status=_status)
    resume_last_match_score.set(0)


def record_request(path: str, method: str = "GET", status: int = 200,
                   seconds: float | None = None) -> None:
    """Record one API request. Used by the middleware in api_server.py;
    `path` should be the route template (e.g. /results/{job_id}) to keep
    label cardinality bounded."""
    if not _OK:                                # pragma: no cover
        return
    http_requests_total.labels(
        method=method, path=path, status=str(status)
    ).inc()
    if seconds is not None:
        http_request_seconds.labels(method=method, path=path).observe(seconds)


def task_finished(status: str, seconds: float, score=None):
    if not _OK:
        return
    resume_tasks_total.labels(status=status).inc()
    resume_task_seconds.observe(seconds)
    if score is not None:
        resume_last_match_score.set(score)


def maybe_start_worker_metrics_server() -> bool:
    """Expose /metrics for the worker when WORKER_METRICS_PORT is set."""
    port = os.environ.get("WORKER_METRICS_PORT", "").strip()
    if not (_OK and port):
        return False
    port_i = int(port)

    def _serve():
        start_http_server(port_i, registry=registry)

    threading.Thread(target=_serve, daemon=True).start()
    return True
