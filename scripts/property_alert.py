#!/usr/bin/env python3
"""
London Property Alert
=====================
Searches Rightmove for period houses in N/NW/NE London matching your criteria
and sends an HTML digest email via Gmail.

SETUP (one-time)
----------------
1. Enable 2-Step Verification on your Google account.
2. Create a Gmail App Password:
     https://myaccount.google.com/apppasswords
   (Category: Mail, Device: Other → give it a name → copy the 16-char password)
3. Add three GitHub Secrets (Settings → Secrets → Actions):
     GMAIL_USER          your Gmail address, e.g. you@gmail.com
     GMAIL_APP_PASSWORD  the 16-character App Password
     ALERT_EMAIL_TO      recipient address (can be the same as GMAIL_USER)

RUN LOCALLY
-----------
  export GMAIL_USER=you@gmail.com
  export GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
  export ALERT_EMAIL_TO=you@gmail.com
  uv run python scripts/property_alert.py          # new listings only (last 4 days)
  uv run python scripts/property_alert.py --all    # all current matches
  uv run python scripts/property_alert.py --dry-run  # print results, don't email
"""

from __future__ import annotations

import argparse
import os
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

# ---------------------------------------------------------------------------
# Criteria — edit these to change what gets searched and scored
# ---------------------------------------------------------------------------

MAX_PRICE = 1_300_000
MIN_BEDROOMS = 3

# Zone 2 outcodes only — N and NW London
# NW1: Camden Town, Kentish Town, Euston
# NW3: Belsize Park, Swiss Cottage, South Hampstead
# NW5: Tufnell Park, Kentish Town (upper)
# NW6: Kilburn, Queen's Park, West Hampstead
# NW8: St John's Wood
# NW10: Kensal Rise, Kensal Green
# N1:  Islington, Canonbury, Barnsbury
# N4:  Finsbury Park, Stroud Green
# N5:  Highbury
# N7:  Holloway, Caledonian Road
# N16: Stoke Newington (Overground Zone 2)
# N19: Archway, Upper Holloway
TARGET_OUTCODES: list[str] = [
    # NW London — Zone 2
    "NW1", "NW3", "NW5", "NW6", "NW8", "NW10",
    # N London — Zone 2
    "N1", "N4", "N5", "N7", "N16", "N19",
]

# Rightmove building type codes for houses (excludes F=flat)
HOUSE_BUILDING_TYPES = ["D", "S", "T"]  # detached, semi-detached, terraced

# Only show listings first seen within this many days (use --all to override)
NEW_LISTING_DAYS = 4

# Keywords that signal a period / character property
PERIOD_KEYWORDS = [
    "victorian", "edwardian", "georgian", "period", "character",
    "original features", "high ceiling", "bay window", "sash window",
    "period features", "period home", "period property",
]

# Scoring weights
SCORE_PERIOD = 10
SCORE_GARAGE = 8
SCORE_PARKING = 5
SCORE_GARDEN_CONFIRMED = 3   # belt-and-braces on top of mustHave filter
SCORE_REDUCED = 5
SCORE_HEADROOM_10 = 5        # price ≤ 90 % of budget
SCORE_HEADROOM_5 = 3         # price ≤ 95 % of budget

# ---------------------------------------------------------------------------
# Stamp duty estimate (primary residence, April 2025 bands)
# ---------------------------------------------------------------------------

def _stamp_duty_primary(price: int) -> int:
    """Calculate SDLT for a primary residence purchase (April 2025 bands)."""
    bands = [
        (250_000, 0.00),
        (675_000, 0.05),
        (575_000, 0.10),
        (float("inf"), 0.12),
    ]
    tax = 0
    remaining = price
    for band_width, rate in bands:
        if remaining <= 0:
            break
        taxable = min(remaining, band_width)
        tax += int(taxable * rate)
        remaining -= taxable
    return tax


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    # Rightmove returns ISO strings; handle both Z and +00:00 suffixes
    normalized = date_str.replace("Z", "+00:00")
    # Some older formats: 2024-01-15T10:30:00.000+0000
    if len(normalized) >= 28 and normalized[-5] in ("+", "-") and ":" not in normalized[-5:]:
        normalized = normalized[:-5] + normalized[-5:-2] + ":" + normalized[-2:]
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _is_recent(date_str: str | None, days: int) -> bool:
    dt = _parse_date(date_str)
    if dt is None:
        return True  # unknown date → include rather than exclude
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt >= cutoff


# ---------------------------------------------------------------------------
# Listing helpers
# ---------------------------------------------------------------------------

def _text_lower(listing) -> str:  # type: ignore[no-untyped-def]
    return ((listing.summary or "") + " " + (listing.property_type or "")).lower()


def _is_house(listing) -> bool:  # type: ignore[no-untyped-def]
    """Return True if the listing is a house type (not flat/apartment)."""
    pt = (listing.property_type or "").lower()
    flat_signals = ("flat", "apartment", "studio", "maisonette")
    return not any(s in pt for s in flat_signals)


def _is_new_build(listing) -> bool:  # type: ignore[no-untyped-def]
    text = _text_lower(listing)
    signals = ("new build", "new home", "new development", "newly built", "new instruction")
    # "new instruction" is NOT a new build — only flag actual new-build signals
    return any(s in text for s in ("new build", "new home", "new development", "newly built"))


def _has_keyword(text: str, keywords: list[str]) -> bool:
    return any(kw in text for kw in keywords)


def _score_listing(listing) -> int:  # type: ignore[no-untyped-def]
    text = _text_lower(listing)
    score = 0

    if _has_keyword(text, PERIOD_KEYWORDS):
        score += SCORE_PERIOD
    if "garage" in text:
        score += SCORE_GARAGE
    if "parking" in text:
        score += SCORE_PARKING
    if "garden" in text:
        score += SCORE_GARDEN_CONFIRMED
    if listing.tags and any("REDUCED" in str(t).upper() for t in listing.tags):
        score += SCORE_REDUCED
    if listing.price and listing.price <= MAX_PRICE * 0.90:
        score += SCORE_HEADROOM_10
    elif listing.price and listing.price <= MAX_PRICE * 0.95:
        score += SCORE_HEADROOM_5

    return score


def _detect_flags(listing) -> dict[str, bool]:
    text = _text_lower(listing)
    return {
        "period": _has_keyword(text, PERIOD_KEYWORDS),
        "garden": "garden" in text,
        "parking": "parking" in text,
        "garage": "garage" in text,
        "reduced": bool(listing.tags and any("REDUCED" in str(t).upper() for t in listing.tags)),
    }


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def _search_all_outcodes(
    new_only: bool = True,
) -> list[tuple[object, int, dict[str, bool]]]:  # type: ignore[type-arg]
    """Search all target outcodes and return filtered, scored listings."""
    from property_core.rightmove_location import RightmoveLocationAPI, LocationLookupError
    from property_core.rightmove_scraper import fetch_listings, RightmoveError

    api = RightmoveLocationAPI()
    seen_ids: set = set()
    results: list[tuple[object, int, dict[str, bool]]] = []

    total = len(TARGET_OUTCODES)
    for i, outcode in enumerate(TARGET_OUTCODES, 1):
        print(f"  [{i}/{total}] {outcode} ...", end=" ", flush=True)
        try:
            url = api.build_search_url(
                outcode,
                property_type="sale",
                building_types=HOUSE_BUILDING_TYPES,
                max_price=MAX_PRICE,
                min_bedrooms=MIN_BEDROOMS,
                must_have=["garden"],
                dont_show=["newHome", "sharedOwnership", "retirement"],
                sort_by="newest",
            )
        except LocationLookupError as exc:
            print(f"lookup failed: {exc}")
            continue

        try:
            listings = fetch_listings(url, max_pages=1)
        except RightmoveError as exc:
            print(f"fetch failed: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001
            print(f"error: {exc}")
            continue

        added = 0
        for listing in listings:
            if listing.id in seen_ids:
                continue
            seen_ids.add(listing.id)

            # Hard filters
            if not _is_house(listing):
                continue
            if _is_new_build(listing):
                continue
            if new_only and not _is_recent(listing.first_visible_date, NEW_LISTING_DAYS):
                continue

            score = _score_listing(listing)
            flags = _detect_flags(listing)
            results.append((listing, score, flags))
            added += 1

        print(f"{added} new match{'es' if added != 1 else ''}")

    # Sort by score descending, then price ascending
    results.sort(key=lambda x: (-x[1], x[0].price or 0))
    return results


# ---------------------------------------------------------------------------
# HTML email builder
# ---------------------------------------------------------------------------

_BUDGET_SDLT = _stamp_duty_primary(MAX_PRICE)
_ACQUISITION_COST = MAX_PRICE + _BUDGET_SDLT + 2_000  # rough legal/survey fees


def _fmt_price(p: int | None) -> str:
    if p is None:
        return "POA"
    return f"£{p:,.0f}"


def _headroom_pct(price: int | None) -> str:
    if price is None or price >= MAX_PRICE:
        return ""
    pct = (MAX_PRICE - price) / MAX_PRICE * 100
    return f" &nbsp;·&nbsp; {pct:.0f}% under budget"


def _badge(label: str, colour: str) -> str:
    return (
        f'<span style="display:inline-block;background:{colour};color:#fff;'
        f'font-size:12px;font-weight:bold;padding:3px 8px;border-radius:12px;'
        f'margin:2px 4px 2px 0">{label}</span>'
    )


def _property_card(listing, score: int, flags: dict[str, bool]) -> str:  # type: ignore[no-untyped-def]
    image_html = ""
    if listing.images:
        image_html = (
            f'<img src="{listing.images[0]}" alt="property" '
            f'style="width:100%;max-height:220px;object-fit:cover;display:block">'
        )

    price_html = f'<span style="font-size:22px;font-weight:bold;color:#1a3a5c">{_fmt_price(listing.price)}</span>'
    headroom = _headroom_pct(listing.price)

    beds = f"{listing.bedrooms} bed" if listing.bedrooms else ""
    baths = f"{listing.bathrooms} bath" if listing.bathrooms else ""
    details = " &nbsp;·&nbsp; ".join(filter(None, [beds, baths, listing.property_type or ""]))

    badges = []
    if flags["period"]:
        badges.append(_badge("🏛 Period", "#5d4037"))
    if flags["garden"]:
        badges.append(_badge("🌿 Garden", "#2e7d32"))
    if flags["parking"]:
        badges.append(_badge("🅿 Parking", "#1565c0"))
    if flags["reduced"]:
        badges.append(_badge("⬇ Reduced", "#c62828"))

    garage_banner = ""
    if flags["garage"]:
        garage_banner = (
            '<div style="background:#f9a825;color:#333;font-weight:bold;'
            'padding:6px 12px;border-radius:4px;margin:8px 0;font-size:13px">'
            "🏠 GARAGE — luxury feature highlighted</div>"
        )

    summary_html = ""
    if listing.summary:
        truncated = listing.summary[:280] + ("…" if len(listing.summary) > 280 else "")
        summary_html = f'<p style="color:#555;font-size:13px;margin:8px 0">{truncated}</p>'

    return f"""
<div style="border:1px solid #e0e0e0;border-radius:8px;margin-bottom:24px;overflow:hidden;background:#fff">
  {image_html}
  <div style="padding:16px">
    <div>{price_html}{headroom}</div>
    <div style="color:#444;margin:4px 0 8px;font-size:15px">{listing.address or "Address not available"}</div>
    <div style="color:#666;font-size:13px;margin-bottom:8px">{details}</div>
    <div style="margin-bottom:8px">{''.join(badges)}</div>
    {garage_banner}
    {summary_html}
    <a href="{listing.url}"
       style="display:inline-block;background:#1a3a5c;color:#fff;padding:10px 18px;
              text-decoration:none;border-radius:4px;font-size:13px;margin-top:8px">
      View on Rightmove →
    </a>
  </div>
</div>"""


def build_email_html(
    results: list[tuple[object, int, dict[str, bool]]],
    new_only: bool,
) -> str:
    period_label = f"last {NEW_LISTING_DAYS} days" if new_only else "all current"
    count = len(results)

    if count == 0:
        body_html = (
            '<p style="color:#555;font-size:16px;text-align:center;padding:40px 0">'
            f"No matching period houses found ({period_label}).<br>"
            "Check back next time — the search will run again automatically.</p>"
        )
    else:
        cards = "\n".join(_property_card(l, s, f) for l, s, f in results)
        body_html = cards

    sdlt_str = _fmt_price(_BUDGET_SDLT)
    acq_str = _fmt_price(_ACQUISITION_COST)
    pct = _BUDGET_SDLT / MAX_PRICE * 100

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:20px;background:#f4f4f4;font-family:Arial,Helvetica,sans-serif">
<div style="max-width:620px;margin:0 auto">

  <!-- Header -->
  <div style="background:#1a3a5c;color:#fff;padding:24px;border-radius:8px 8px 0 0">
    <h1 style="margin:0 0 6px;font-size:22px">🏡 London Property Alert</h1>
    <p style="margin:0;font-size:13px;opacity:0.85">
      Zone 2 · N &amp; NW London &nbsp;·&nbsp; ≤ {_fmt_price(MAX_PRICE)} &nbsp;·&nbsp;
      {MIN_BEDROOMS}+ beds &nbsp;·&nbsp; Period houses &nbsp;·&nbsp;
      Garden required &nbsp;·&nbsp; {period_label.title()}
    </p>
  </div>

  <!-- Result count banner -->
  <div style="background:#e8f4fd;padding:12px 20px;font-size:14px;color:#1a3a5c;font-weight:bold">
    {"No new matches" if count == 0 else f"{count} propert{'y' if count == 1 else 'ies'} found"}
    &nbsp;·&nbsp; <span style="font-weight:normal">Searched {len(TARGET_OUTCODES)} outcodes</span>
  </div>

  <!-- Property cards -->
  <div style="background:#f4f4f4;padding:20px 0">
    {body_html}
  </div>

  <!-- Stamp duty footer -->
  <div style="background:#fff;border:1px solid #e0e0e0;border-radius:8px;padding:16px;margin-bottom:20px;font-size:13px;color:#444">
    <strong>Stamp Duty (primary residence, April 2025 bands) at {_fmt_price(MAX_PRICE)}:</strong>
    {sdlt_str} ({pct:.1f}% effective rate)<br>
    <strong>Estimated total acquisition cost:</strong>
    {_fmt_price(MAX_PRICE)} + {sdlt_str} SDLT + £2,000 fees = <strong>{acq_str}</strong>
  </div>

  <!-- Disclaimer -->
  <p style="font-size:11px;color:#999;text-align:center;padding-bottom:20px">
    Data sourced from Rightmove. This is automated research, not financial or legal advice.
    Yields, prices, and availability change daily — always verify before acting.
  </p>

</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Email sender
# ---------------------------------------------------------------------------

def send_email(subject: str, html_body: str) -> None:
    gmail_user = os.environ.get("GMAIL_USER", "").strip()
    app_password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    recipient = os.environ.get("ALERT_EMAIL_TO", gmail_user).strip()

    if not gmail_user or not app_password:
        print("ERROR: GMAIL_USER and GMAIL_APP_PASSWORD environment variables required.")
        sys.exit(1)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.login(gmail_user, app_password)
        server.sendmail(gmail_user, recipient, msg.as_string())

    print(f"Email sent to {recipient}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="London property alert digest")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include all current matches, not just new listings",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print results to stdout without sending email",
    )
    args = parser.parse_args()

    new_only = not args.all
    mode = "all current listings" if args.all else f"new listings (last {NEW_LISTING_DAYS} days)"
    print(f"London Property Alert — searching {mode}")
    print(f"Outcodes: {len(TARGET_OUTCODES)} | Budget: {_fmt_price(MAX_PRICE)} | Min beds: {MIN_BEDROOMS}")
    print()

    results = _search_all_outcodes(new_only=new_only)

    count = len(results)
    print(f"\n{count} propert{'y' if count == 1 else 'ies'} matched after filtering.\n")

    html = build_email_html(results, new_only=new_only)

    if args.dry_run:
        for listing, score, flags in results:
            flag_str = " ".join(k.upper() for k, v in flags.items() if v)
            print(f"  [{score:2d}] {_fmt_price(listing.price):>13}  {listing.address}  [{flag_str}]")
            print(f"        {listing.url}")
        print("\n(--dry-run: email not sent)")
        return

    today = datetime.now().strftime("%-d %b %Y")
    subject = (
        f"🏡 {count} London propert{'y' if count == 1 else 'ies'} matched · {today}"
        if count > 0
        else f"🏡 London Property Alert · No new matches · {today}"
    )
    send_email(subject, html)


if __name__ == "__main__":
    main()
