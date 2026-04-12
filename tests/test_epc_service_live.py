import os
import time

import pytest

from property_core.epc_client import EPCClient

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional local dev dependency
    load_dotenv = None


if load_dotenv:
    load_dotenv()


@pytest.mark.anyio
async def test_epc_service_live_search() -> None:
    if os.getenv("RUN_LIVE_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_TESTS=1 to run live network tests")

    client = EPCClient()
    if not client.is_configured():
        pytest.skip("EPC credentials not configured")

    postcode = os.getenv("EPC_TEST_POSTCODE", "SW1A 1AA")
    address = os.getenv("EPC_TEST_ADDRESS")

    start = time.perf_counter()
    result = await client.search_by_postcode(postcode, address=address)
    elapsed = time.perf_counter() - start

    print(f"EPC live search took {elapsed:.2f}s")
    if result is None:
        raise AssertionError(
            "No EPC result for test postcode. Set EPC_TEST_POSTCODE to a known-good "
            "postcode (and EPC_TEST_ADDRESS if needed)."
        )
    print(f"EPC rating={result.rating} score={result.score} address={result.address}")
    assert result.rating


@pytest.mark.anyio
async def test_epc_service_live_area_search() -> None:
    """Live test: search_all_by_postcode returns list of certs for a residential postcode."""
    if os.getenv("RUN_LIVE_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_TESTS=1 to run live network tests")

    client = EPCClient()
    if not client.is_configured():
        pytest.skip("EPC credentials not configured")

    postcode = os.getenv("EPC_TEST_POSTCODE", "NG11 9HD")

    start = time.perf_counter()
    certs = await client.search_all_by_postcode(postcode)
    elapsed = time.perf_counter() - start

    print(f"EPC area search for {postcode} took {elapsed:.2f}s -> {len(certs)} certs")
    if not certs:
        pytest.skip(f"No EPC certs for {postcode}. Try a different EPC_TEST_POSTCODE.")

    assert len(certs) >= 1
    # Sanity check — at least some certs should have ratings
    assert any(c.rating for c in certs), "expected at least one cert with a rating"
