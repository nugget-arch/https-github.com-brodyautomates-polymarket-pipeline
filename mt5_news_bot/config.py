import os
from dotenv import load_dotenv

load_dotenv()

# --- MetaTrader 5 account ---
MT5_LOGIN = int(os.getenv("MT5_LOGIN", "0") or "0")
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "ICMarkets-Demo")
MT5_TERMINAL_PATH = os.getenv("MT5_TERMINAL_PATH", "")  # optional, path to terminal64.exe

# --- Strategy timing ---
SECONDS_BEFORE_NEWS = float(os.getenv("SECONDS_BEFORE_NEWS", "5"))
ORDER_EXPIRY_SECONDS = float(os.getenv("ORDER_EXPIRY_SECONDS", "120"))  # cancel unfilled straddle after this long
POST_NEWS_TIMEOUT_SECONDS = float(os.getenv("POST_NEWS_TIMEOUT_SECONDS", "30"))  # how long to wait for a fill after T+0

# --- Risk settings ---
STRADDLE_PIPS = float(os.getenv("STRADDLE_PIPS", "10"))    # distance of each stop order from current price
STOP_LOSS_PIPS = float(os.getenv("STOP_LOSS_PIPS", "15"))
TAKE_PROFIT_PIPS = float(os.getenv("TAKE_PROFIT_PIPS", "30"))
LOT_SIZE = float(os.getenv("LOT_SIZE", "0.10"))
MAX_SPREAD_PIPS = float(os.getenv("MAX_SPREAD_PIPS", "3"))
MAX_SLIPPAGE_PIPS = float(os.getenv("MAX_SLIPPAGE_PIPS", "10"))

# --- Safety ---
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
MAX_TRADES_PER_DAY = int(os.getenv("MAX_TRADES_PER_DAY", "3"))
DAILY_LOSS_LIMIT_USD = float(os.getenv("DAILY_LOSS_LIMIT_USD", "100"))

# --- Symbols traded per currency exposed by an event ---
EVENT_SYMBOLS = {
    "USD": ["EURUSD", "GBPUSD", "USDJPY"],
    "EUR": ["EURUSD"],
    "GBP": ["GBPUSD"],
}

# --- Economic calendar source (optional, for live/precise event times) ---
# Free tier at https://finnhub.io — leave blank to rely on the built-in
# recurring-event schedule in news_calendar.py
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")

# --- Events this bot trades ---
TRADED_EVENTS = [
    "NFP",
    "CPI",
    "FOMC",
    "GDP",
    "Retail Sales",
    "ISM Manufacturing",
    "ECB Rate Decision",
    "BOE Rate Decision",
]
