"""Rightmove location lookup and URL builder (pure Python).

Rightmove uses internal location identifiers (e.g. ``OUTCODE^620``) in search URLs.
This module wraps their (undocumented) typeahead endpoint to convert postcodes/outcodes
to those identifiers and then build search URLs.
"""

from __future__ import annotations

import time
from typing import Optional
from urllib.parse import urlencode

import requests


class LocationLookupError(Exception):
    """Raised when Rightmove location lookup fails."""


_SORT_TYPES = {
    "newest": 6,
    "oldest": 10,
    "price_low": 2,
    "price_high": 12,
    "most_reduced": 4,
}

# PPD property type codes → Rightmove propertyTypes param values
_BUILDING_TYPES = {
    "F": "flat",
    "D": "detached",
    "S": "semi-detached",
    "T": "terraced",
    "B": "bungalow",
}


class RightmoveLocationAPI:
    """Client for Rightmove's location autocomplete API."""

    API_BASE = "https://los.rightmove.co.uk"
    TYPEAHEAD_ENDPOINT = "/typeahead"

    PROPERTY_TYPES = {
        "sale": "property-for-sale",
        "rent": "property-to-rent",
    }

    def __init__(
        self,
        *,
        timeout: float = 10.0,
        rate_limit_delay: float = 0.2,
        cache_enabled: bool = True,
    ):
        self.timeout = timeout
        self.rate_limit_delay = rate_limit_delay
        self._cache: dict[str, str] | None = {} if cache_enabled else None
        self._last_request_time = 0.0

    def _rate_limit(self) -> None:
        if self.rate_limit_delay <= 0:
            return
        elapsed = time.time() - self._last_request_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self._last_request_time = time.time()

    def lookup_postcode(self, postcode: str) -> Optional[str]:
        """Return Rightmove location identifier for a postcode/outcode."""
        postcode_upper = postcode.upper().strip()
        if self._cache is not None and postcode_upper in self._cache:
            return self._cache[postcode_upper]

        self._rate_limit()
        url = f"{self.API_BASE}{self.TYPEAHEAD_ENDPOINT}"
        params = {"query": postcode_upper, "limit": 10, "exclude": "STREET"}

        try:
            response = requests.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise LocationLookupError(f"Failed to lookup postcode '{postcode}': {exc}") from exc

        matches = data.get("matches", [])
        if not matches:
            return None

        first_match = matches[0]
        location_id = first_match.get("id")
        location_type = first_match.get("type", "OUTCODE")
        if not location_id:
            return None

        identifier = f"{location_type}^{location_id}"
        if self._cache is not None:
            self._cache[postcode_upper] = identifier
        return identifier

    def build_search_url(
        self,
        postcode: str,
        *,
        property_type: str = "sale",
        building_type: str | None = None,
        building_types: list[str] | None = None,
        min_price: int | None = None,
        max_price: int | None = None,
        min_bedrooms: int | None = None,
        max_bedrooms: int | None = None,
        radius: float | None = None,
        sort_by: str | None = None,
        must_have: list[str] | None = None,
        dont_show: list[str] | None = None,
        **extra_params,
    ) -> str:
        """Build a Rightmove search URL from a postcode/outcode.

        Args:
            postcode: UK postcode or outcode (e.g. "NW3", "SW1A 1AA").
            property_type: "sale" or "rent".
            building_type: Single PPD building code — F/D/S/T/B.
            building_types: Multiple PPD building codes (overrides building_type).
            min_price / max_price: Price range in GBP.
            min_bedrooms / max_bedrooms: Bedroom range.
            radius: Search radius in miles.
            sort_by: newest | oldest | price_low | price_high | most_reduced.
            must_have: Rightmove mustHave features, e.g. ["garden", "parking"].
            dont_show: Rightmove dontShow features, e.g. ["newHome", "sharedOwnership"].
        """
        location_identifier = self.lookup_postcode(postcode)
        if not location_identifier:
            raise LocationLookupError(
                f"Could not find location identifier for postcode '{postcode}'."
            )

        # Full postcodes tend to be very tight searches; default to a small radius
        # so the first request is more likely to return results.
        if radius is None and location_identifier.startswith("POSTCODE^"):
            radius = 0.25

        property_path = self.PROPERTY_TYPES.get(property_type, "property-for-sale")
        base_url = f"https://www.rightmove.co.uk/{property_path}/find.html"

        # Use a list of tuples to support repeated keys (propertyTypes, mustHave[], etc.)
        params: list[tuple[str, object]] = [("locationIdentifier", location_identifier)]

        if min_price is not None:
            params.append(("minPrice", min_price))
        if max_price is not None:
            params.append(("maxPrice", max_price))
        if min_bedrooms is not None:
            params.append(("minBedrooms", min_bedrooms))
        if max_bedrooms is not None:
            params.append(("maxBedrooms", max_bedrooms))
        if radius is not None:
            params.append(("radius", radius))
        if sort_by:
            code = _SORT_TYPES.get(sort_by)
            if code is not None:
                params.append(("sortType", code))

        # Resolve building type(s) — building_types takes precedence over building_type
        resolved_types: list[str] = []
        for code in (building_types or ([building_type] if building_type else [])):
            rm_type = _BUILDING_TYPES.get(code.upper())
            if rm_type:
                resolved_types.append(rm_type)
        for rm_type in resolved_types:
            params.append(("propertyTypes", rm_type))

        # Rightmove bracket-notation list params
        for feature in (must_have or []):
            params.append(("mustHave[]", feature))
        for feature in (dont_show or []):
            params.append(("dontShow[]", feature))

        for k, v in extra_params.items():
            params.append((k, v))

        return f"{base_url}?{urlencode(params)}"
