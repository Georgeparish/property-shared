"""API envelope schemas for EPC endpoints.

Domain model (EPCData) lives in property_core.models.epc.
This file defines only the API response wrappers.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

# Convenience re-exports for API layer imports
from property_core.models.epc import EPCData  # noqa: F401


class EPCRecordResponse(BaseModel):
    """Normalized EPC record with optional raw payload."""

    record: EPCData
    raw: Optional[dict[str, Any]] = None


class EPCAreaSummary(BaseModel):
    """Aggregated statistics for EPC certificates in a postcode area."""

    count: int
    rating_distribution: dict[str, int] = Field(default_factory=dict)
    floor_area_min: float | None = None
    floor_area_max: float | None = None
    floor_area_avg: float | None = None
    property_type_breakdown: dict[str, int] = Field(default_factory=dict)


class EPCAreaResponse(BaseModel):
    """EPC area search results with summary statistics."""

    postcode: str
    summary: EPCAreaSummary
    certificates: list[EPCData]
