from datetime import date


def add_months(d, n):
    index = d.year * 12 + (d.month - 1) + n
    return date(index // 12, index % 12 + 1, 1)