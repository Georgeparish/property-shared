"""Tests for PPDService._find_subject_property — subject property matching.

Covers two layers of defence:
  1. Parse-gate in the service: ambiguous input should not trigger a query.
  2. Model-level invariant on SubjectProperty: cannot represent multiple buildings.

These tests mix unit tests (for the parse-gate and validator) with a live
network test for the end-to-end regression case.
"""
from __future__ import annotations

import os

import pytest

from property_core.models.ppd import PPDTransaction, SubjectProperty
from property_core.ppd_service import PPDService


# ---------------------------------------------------------------------------
# Unit tests — SubjectProperty model validator
# ---------------------------------------------------------------------------


def _make_txn(paon: str, street: str, price: int = 100_000, date: str = "2024-01-01") -> PPDTransaction:
    return PPDTransaction(
        transaction_id=f"{paon}-{date}",
        price=price,
        date=date,
        postcode="NG11 9HD",
        paon=paon,
        street=street,
    )


def test_subject_property_accepts_single_building():
    """Model constructs cleanly when all history rows are the same building."""
    txns = [
        _make_txn("39", "HAVENWOOD RISE", 100_000, "2010-01-01"),
        _make_txn("39", "HAVENWOOD RISE", 120_000, "2015-06-01"),
    ]
    sp = SubjectProperty(
        address="39 Havenwood Rise",
        postcode="NG11 9HD",
        last_sale=txns[1],
        transaction_count=2,
        transaction_history=txns,
    )
    assert sp.transaction_count == 2


def test_subject_property_rejects_mixed_buildings():
    """Model refuses to construct when history spans multiple (paon, street)."""
    txns = [
        _make_txn("27", "HAVENWOOD RISE"),
        _make_txn("39", "HAVENWOOD RISE"),
    ]
    with pytest.raises(ValueError, match="distinct"):
        SubjectProperty(
            address="Havenwood Rise",
            postcode="NG11 9HD",
            last_sale=txns[0],
            transaction_count=2,
            transaction_history=txns,
        )


def test_subject_property_rejects_last_sale_not_in_history():
    """last_sale must correspond to a building in transaction_history."""
    history = [_make_txn("39", "HAVENWOOD RISE")]
    outsider = _make_txn("27", "HAVENWOOD RISE")
    with pytest.raises(ValueError, match="last_sale"):
        SubjectProperty(
            address="39 Havenwood Rise",
            postcode="NG11 9HD",
            last_sale=outsider,
            transaction_count=1,
            transaction_history=history,
        )


def test_subject_property_rejects_count_mismatch():
    """transaction_count must equal len(transaction_history)."""
    history = [_make_txn("39", "HAVENWOOD RISE")]
    with pytest.raises(ValueError, match="transaction_count"):
        SubjectProperty(
            address="39 Havenwood Rise",
            postcode="NG11 9HD",
            last_sale=history[0],
            transaction_count=99,
            transaction_history=history,
        )


def test_subject_property_empty_history_ok():
    """Empty history is allowed (no subject_property found case)."""
    sp = SubjectProperty(
        address="39 Havenwood Rise",
        postcode="NG11 9HD",
        last_sale=None,
        transaction_count=0,
        transaction_history=[],
    )
    assert sp.transaction_history == []


# ---------------------------------------------------------------------------
# Live tests — full PPDService.comps flow
# ---------------------------------------------------------------------------


pytestmark_live = pytest.mark.skipif(
    os.getenv("RUN_LIVE_TESTS") != "1",
    reason="Set RUN_LIVE_TESTS=1 to run live network tests",
)


@pytestmark_live
def test_vague_street_only_returns_none_subject():
    """Regression: user passes just a street name with no house number.

    Previously this returned the most-recent sale on the street as if
    it were the subject property — a false attribution.
    """
    service = PPDService()
    result = service.comps(
        postcode="NG11 9HD",
        address="Havenwood Rise",  # no house number
        limit=10,
        months=120,
    )
    assert result.subject_property is None, (
        "vague street-only address must not resolve to a subject property"
    )


@pytestmark_live
def test_vague_substring_returns_none_subject():
    """Regression: substring like 'havenwood' must not trigger a false match."""
    service = PPDService()
    result = service.comps(
        postcode="NG11 9HD",
        address="havenwood",
        limit=10,
        months=120,
    )
    assert result.subject_property is None


@pytestmark_live
def test_very_short_substring_returns_none_subject():
    """Regression: 'haven' is too vague to identify a property."""
    service = PPDService()
    result = service.comps(
        postcode="NG11 9HD",
        address="haven",
        limit=10,
        months=120,
    )
    assert result.subject_property is None


@pytestmark_live
def test_specific_address_still_resolves():
    """Sanity: a real, specific address must still produce a subject_property."""
    service = PPDService()
    result = service.comps(
        postcode="NG11 9HD",
        address="39 Havenwood Rise",
        limit=10,
        months=120,
    )
    assert result.subject_property is not None
    assert "39" in result.subject_property.address.upper()
    # All history rows should belong to #39
    paons = {t.paon for t in result.subject_property.transaction_history}
    assert paons == {"39"}, f"expected only paon='39' in history, got {paons}"


@pytestmark_live
def test_wrong_house_number_returns_none():
    """A house number that doesn't exist on the street returns None."""
    service = PPDService()
    result = service.comps(
        postcode="NG11 9HD",
        address="99999 Havenwood Rise",
        limit=10,
        months=120,
    )
    assert result.subject_property is None
