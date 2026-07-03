"""
Economic calendar for the news trading bot.

Two sources, in priority order:

1. Finnhub economic calendar API (if FINNHUB_API_KEY is set in .env) —
   accurate, auto-updating release times pulled live.
2. Built-in schedule — NFP and ISM Manufacturing are computed from their
   fixed weekday rules. CPI, Retail Sales, GDP, FOMC, ECB and BOE decisions
   do NOT follow a fixed weekday rule, so they must be filled in from the
   issuing agency's official calendar:
     - FOMC:   https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
     - CPI/Retail Sales/GDP: https://www.bls.gov/schedule/news_release/  and
       https://www.census.gov/retail/marts/www/marts_current.html and
       https://www.bea.gov/news/schedule
     - ECB:    https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html
     - BOE:    https://www.bankofengland.co.uk/monetary-policy-summary-and-minutes

   MANUAL_EVENTS below ships empty by default — populate it (or set
   FINNHUB_API_KEY) before relying on this for live trading.
"""

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from calendar import monthrange
from zoneinfo import ZoneInfo

import httpx

import config

ET = ZoneInfo("America/New_York")
LONDON = ZoneInfo("Europe/London")
FRANKFURT = ZoneInfo("Europe/Berlin")
UTC = ZoneInfo("UTC")


@dataclass
class EconomicEvent:
    name: str
    country: str
    time_utc: datetime
    currency: str
    impact: str = "high"

    def __lt__(self, other):
        return self.time_utc < other.time_utc


# Fill these in from the official sources listed above — release dates that
# don't fall on a fixed weekday (CPI, Retail Sales, GDP, FOMC, ECB, BOE)
# can't be derived programmatically. Each entry: (name, country, currency,
# local_date "YYYY-MM-DD", local_time "HH:MM", timezone)
MANUAL_EVENTS = [
    # ("CPI", "US", "USD", "2026-07-14", "08:30", ET),
    # ("FOMC Rate Decision", "US", "USD", "2026-07-29", "14:00", ET),
    # ("ECB Rate Decision", "EU", "EUR", "2026-07-23", "12:15", FRANKFURT),
    # ("BOE Rate Decision", "UK", "GBP", "2026-08-06", "12:00", LONDON),
]


def _first_friday(year: int, month: int) -> datetime:
    day = 1
    d = datetime(year, month, day)
    offset = (4 - d.weekday()) % 7  # weekday(): Monday=0 ... Friday=4
    return datetime(year, month, 1 + offset)


def _first_business_day(year: int, month: int) -> datetime:
    d = datetime(year, month, 1)
    while d.weekday() >= 5:  # Sat/Sun
        d += timedelta(days=1)
    return d


def _localize(dt: datetime, tz: ZoneInfo) -> datetime:
    return dt.replace(tzinfo=tz)


def nfp_event(year: int, month: int) -> EconomicEvent:
    d = _first_friday(year, month)
    local = _localize(datetime(d.year, d.month, d.day, 8, 30), ET)
    return EconomicEvent("NFP", "US", local.astimezone(UTC), "USD")


def ism_manufacturing_event(year: int, month: int) -> EconomicEvent:
    d = _first_business_day(year, month)
    local = _localize(datetime(d.year, d.month, d.day, 10, 0), ET)
    return EconomicEvent("ISM Manufacturing", "US", local.astimezone(UTC), "USD")


def _built_in_events(start: datetime, end: datetime) -> list[EconomicEvent]:
    events = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        events.append(nfp_event(year, month))
        events.append(ism_manufacturing_event(year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1

    for name, country, currency, date_str, time_str, tz in MANUAL_EVENTS:
        naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        local = _localize(naive, tz)
        events.append(EconomicEvent(name, country, local.astimezone(UTC), currency))

    return [e for e in events if start <= e.time_utc <= end]


def _finnhub_events(start: datetime, end: datetime) -> list[EconomicEvent]:
    if not config.FINNHUB_API_KEY:
        return []
    resp = httpx.get(
        "https://finnhub.io/api/v1/calendar/economic",
        params={
            "from": start.strftime("%Y-%m-%d"),
            "to": end.strftime("%Y-%m-%d"),
            "token": config.FINNHUB_API_KEY,
        },
        timeout=10,
    )
    resp.raise_for_status()
    events = []
    for item in resp.json().get("economicCalendar", []):
        if item.get("impact") != "high":
            continue
        event_name = item.get("event", "")
        if not any(tag.lower() in event_name.lower() for tag in config.TRADED_EVENTS):
            continue
        naive = datetime.strptime(item["time"], "%Y-%m-%d %H:%M:%S")
        events.append(
            EconomicEvent(
                name=event_name,
                country=item.get("country", ""),
                time_utc=naive.replace(tzinfo=UTC),
                currency=item.get("country", ""),
            )
        )
    return events


def get_events(start: datetime, end: datetime) -> list[EconomicEvent]:
    """Return high-impact events between start and end (both UTC-aware)."""
    events = _finnhub_events(start, end)
    if not events:
        events = _built_in_events(start, end)
    return sorted(events)


def get_week_events() -> list[EconomicEvent]:
    now = datetime.now(UTC)
    return get_events(now, now + timedelta(days=7))


def _print_events(events: list[EconomicEvent]) -> None:
    try:
        from rich.console import Console
        from rich.table import Table

        table = Table(title="Economic Calendar — next 7 days")
        table.add_column("When (UTC)")
        table.add_column("Event")
        table.add_column("Country")
        table.add_column("Currency")
        for e in events:
            table.add_row(e.time_utc.strftime("%Y-%m-%d %H:%M"), e.name, e.country, e.currency)
        Console().print(table)
    except ImportError:
        for e in events:
            print(f"{e.time_utc.strftime('%Y-%m-%d %H:%M')} UTC  {e.name:<20} {e.country} {e.currency}")


if __name__ == "__main__":
    events = get_week_events()
    if not events:
        print("No events found. Set FINNHUB_API_KEY in .env for live data, "
              "or populate MANUAL_EVENTS in news_calendar.py.")
        sys.exit(0)
    _print_events(events)
