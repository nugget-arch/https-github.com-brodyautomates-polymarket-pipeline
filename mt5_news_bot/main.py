"""
Entry point for the news trading bot.

Loads the upcoming economic calendar, and for each tradeable event, sleeps
until shortly before release time and arms a buy-stop/sell-stop straddle
via bot.NewsTradingBot. Runs until interrupted (Ctrl+C).
"""

import sys
import time
from datetime import datetime, timedelta, timezone

import config
from bot import NewsTradingBot
from mt5_client import MT5Client, MT5ConnectionError
from news_calendar import get_events


def log(message: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {message}", flush=True)


def upcoming_events(hours: int = 24):
    now = datetime.now(timezone.utc)
    events = get_events(now, now + timedelta(hours=hours))
    return [e for e in events if any(tag.lower() in e.name.lower() for tag in config.TRADED_EVENTS)]


def symbols_for(event) -> list[str]:
    return config.EVENT_SYMBOLS.get(event.currency, [])


def main() -> None:
    mode = "DRY RUN (simulated fills)" if config.DRY_RUN else "LIVE"
    log(f"News trading bot starting — mode: {mode}, server: {config.MT5_SERVER}")

    client = MT5Client()
    try:
        client.connect()
    except MT5ConnectionError as e:
        log(f"[FATAL] Could not connect to MT5: {e}")
        sys.exit(1)

    bot = NewsTradingBot(client, log=log)

    try:
        while True:
            events = upcoming_events(hours=24)
            if not events:
                log("No tradeable events in the next 24h. Sleeping 1h.")
                time.sleep(3600)
                continue

            for event in events:
                symbols = symbols_for(event)
                if not symbols:
                    log(f"[SKIP] No configured symbols for currency {event.currency} ({event.name})")
                    continue

                seconds_until = (event.time_utc.timestamp() - time.time())
                if seconds_until < -config.POST_NEWS_TIMEOUT_SECONDS:
                    continue  # already passed

                for symbol in symbols:
                    bot.run_event(event, symbol)

            time.sleep(5)
    except KeyboardInterrupt:
        log("Shutting down (Ctrl+C)")
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
