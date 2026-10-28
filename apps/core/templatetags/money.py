# apps/core/templatetags/money.py
from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def money(value, symbol="$"):
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return ""
    sign = "-" if amount < 0 else ""
    return f"{sign}{symbol}{abs(amount):,.2f}"