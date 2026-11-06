import json
import logging
import urllib.request
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.utils import timezone

from .models import ExchangeRate

log = logging.getLogger(__name__)

PRIMARY = "https://open.er-api.com/v6/latest/USD"
FALLBACK = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json"
FRESH_FOR = timedelta(hours=24)
STALE_AFTER = timedelta(days=3)
MIN_GAP = 600                                    # seconds between attempts, so a failing service is never hammered
SANE = (Decimal("20"), Decimal("1000"))          # KES per USD. Anything outside this is treated as a bad reading


def _json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "ExpenseTracker/1.0"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def _fetch():
    try:
        data = _json(PRIMARY)
        if data.get("result") == "success":
            return Decimal(str(data["rates"]["KES"])), "exchangerate-api.com"
    except Exception as exc:
        log.warning("Primary rate source failed: %s", exc)
    try:
        return Decimal(str(_json(FALLBACK)["usd"]["kes"])), "currency-api"
    except Exception as exc:
        log.warning("Fallback rate source failed: %s", exc)
    return None


def latest():
    return ExchangeRate.objects.filter(base="USD", quote="KES").first()


def refresh(force=False):
    """Returns the newest stored rate, fetching a new one first when the stored one is over a day old.
    A failed fetch never raises: the last known rate keeps working."""
    current = latest()
    if current and not force and timezone.now() - current.fetched_at < FRESH_FOR:
        return current
    if not cache.add("rates:last-attempt", 1, MIN_GAP):      # someone tried a moment ago
        return current
    result = _fetch()
    if result is None or not (SANE[0] < result[0] < SANE[1]):
        return current
    return ExchangeRate.objects.create(base="USD", quote="KES", rate=result[0].quantize(Decimal("0.000001")), source=result[1])


def is_stale(row):
    return row is None or timezone.now() - row.fetched_at > STALE_AFTER


def rate_between(a, b):
    """Stored rate for 1 `a` expressed in `b`, with no network call. None when unknown."""
    if a == b:
        return Decimal(1)
    row = latest()
    if not row:
        return None
    if (a, b) == ("USD", "KES"):
        return row.rate
    if (a, b) == ("KES", "USD"):
        return Decimal(1) / row.rate
    return None


def rate_to_base(entry_currency, base, usd_kes):
    """From the rate a person sees (1 USD = X KES) to the multiplier that turns an entry amount into the account currency."""
    if entry_currency == base:
        return Decimal(1)
    if entry_currency == "USD":
        return usd_kes
    return (Decimal(1) / usd_kes).quantize(Decimal("0.00000001"))


def usd_kes_from(entry_currency, base, stored):
    """The reverse: show a saved entry's multiplier as '1 USD = X KES'."""
    if entry_currency == base or not stored:
        return None
    value = stored if entry_currency == "USD" else Decimal(1) / stored
    return value.quantize(Decimal("0.0001"))