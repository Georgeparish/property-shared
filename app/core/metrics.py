"""Prometheus metrics endpoint for the FastAPI app."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest


def setup_metrics(app: FastAPI) -> None:
    """Expose /metrics endpoint backed by the global prometheus-client registry."""

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
