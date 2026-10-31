from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def money_round(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def sale_numbers(amount, advance_pct, fee_rate_pct, fee_flat, fee_timing):
    advance = money_round(amount * advance_pct / 100)
    reserve = amount - advance
    fee = money_round(amount * fee_rate_pct / 100 + (fee_flat or 0))
    upfront = fee_timing == "upfront"
    return {
        "advance": advance,
        "reserve": reserve,
        "fee": fee,
        "cash_now": advance - fee if upfront else advance,
        "release": reserve if upfront else reserve - fee,
        "net_total": amount - fee,
    }