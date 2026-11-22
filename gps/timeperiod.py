"""Time-period presets -> exact dates. The same function is used by the page, the project cards, dataset searches and
the connectors, so what the user sees is exactly what gets queried."""
from datetime import date, datetime, timedelta

PRESETS = [("month", "This month"), ("year", "This year"), ("2y", "Past 2 years"), ("5y", "Past 5 years"),
           ("10y", "Past 10 years"), ("custom", "Custom date range")]
LABELS = dict(PRESETS)
DEFAULT = "10y"


def _years_back(d, n):
    try:
        return d.replace(year=d.year - n)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year - n, day=28)


def _parse(s, what):
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise ValueError(f"{what} must be a date like 2024-03-31")


def resolve(preset=None, start=None, end=None, today=None):
    """Return {preset, label, start, end, days, text}. Raises ValueError with a plain message for bad custom ranges."""
    today = today or date.today()
    preset = preset if preset in LABELS else DEFAULT
    if preset == "month":
        s, e = today.replace(day=1), today
    elif preset == "year":
        s, e = today.replace(month=1, day=1), today
    elif preset in ("2y", "5y", "10y"):
        s, e = _years_back(today, int(preset[:-1])), today
    else:
        s, e = _parse(start, "Start date"), _parse(end, "End date")
        if s > e:
            raise ValueError("The start date is after the end date.")
        if s > today:
            raise ValueError("The start date is in the future.")
        if e > today:
            e = today  # nothing exists after today; clamp and say so in the label
    days = (e - s).days + 1
    return {"preset": preset, "label": LABELS[preset], "start": s.isoformat(), "end": e.isoformat(), "days": days,
            "text": f"{s.isoformat()} → {e.isoformat()} ({days:,} days)"}


def years(period):
    """(first_year, last_year) of a resolved period."""
    return int(period["start"][:4]), int(period["end"][:4])
