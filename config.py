# config.py — Iron-Sentry Central Configuration
# Author: Hridam Biswas | Project: Iron-Sentry

import os
from typing import List, Tuple
from dotenv import load_dotenv

load_dotenv()

# ─── Telegram ────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN    = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID  = os.environ["TELEGRAM_CHAT_ID"]
HEARTBEAT_INTERVAL_SEC = 900   # 15 min

# ─── Trading Mode ────────────────────────────────────────────────────────────
PAPER_TRADING = True           # Flip to False only after Dhan account is live
STARTING_CAPITAL = 5000.0      # INR

# ─── Pairs ───────────────────────────────────────────────────────────────────
# (leg_A, leg_B) — we go Long A / Short B when spread is low
PAIRS: List[Tuple[str, str]] = [
    ("INFY",        "TCS"),
    ("HDFCBANK",    "ICICIBANK"),
    ("TATAMOTORS",  "M&M"),
]

# ─── Z-Score Engine ──────────────────────────────────────────────────────────
ZSCORE_WINDOW       = 30       # rolling window (bars) for mean/std
ZSCORE_ENTRY        = 2.5      # open position
ZSCORE_EXIT         = 0.0      # close position (mean reversion)
ZSCORE_STOP         = 4.0      # emergency exit — spread blowing out

# ─── Risk ────────────────────────────────────────────────────────────────────
MAX_POSITION_PCT    = 0.20     # max 20 % of capital per pair
MAX_DRAWDOWN_PCT    = 0.05     # halt trading if daily drawdown > 5 %
LEVERAGE            = 1.0      # Month 1-2: no leverage; raise slowly later
ORDER_TYPE          = "LIMIT"  # limit orders ONLY (no market orders)
SLIPPAGE_BPS        = 5        # paper-trade assumption: 5 basis points

# ─── API Rate Limit ──────────────────────────────────────────────────────────
MAX_ORDERS_PER_SEC  = 8        # stay under Dhan's 10/sec hard limit

# ─── Database ────────────────────────────────────────────────────────────────
DB_PATH = "iron_sentry.db"

# ─── Logging ─────────────────────────────────────────────────────────────────
LOG_FILE = "iron_sentry.log"

# ─── Market Hours (IST = UTC+5:30) ───────────────────────────────────────────
MARKET_OPEN_IST  = "09:15"
MARKET_CLOSE_IST = "15:30"
LAST_ENTRY_TIME  = "15:15"   # no new positions after this
FORCE_CLOSE_TIME = "15:15"   # force-close all pairs before weekend

# ─── Execution Safety ────────────────────────────────────────────────────────
MAX_PRICE_AGE_SEC      = 30    # reject stale ticks older than 30 seconds
MIN_PROFIT_THRESHOLD   = 0.003 # 0.3% minimum edge to cover STT + brokerage + GST
MAX_CONCURRENT_PAIRS   = 1     # Month 1: 1 pair max; increase with capital

# ─── NSE Holidays 2026 ───────────────────────────────────────────────────────
NSE_HOLIDAYS: List[str] = [
    "2026-01-26",  # Republic Day
    "2026-02-19",  # Chhatrapati Shivaji Maharaj Jayanti
    "2026-03-14",  # Holi
    "2026-04-10",  # Good Friday
    "2026-04-14",  # Dr. Ambedkar Jayanti
    "2026-05-01",  # Maharashtra Day
    "2026-08-15",  # Independence Day
    "2026-08-27",  # Ganesh Chaturthi
    "2026-10-02",  # Gandhi Jayanti
    "2026-10-21",  # Dussehra
    "2026-11-05",  # Diwali (Laxmi Puja)
    "2026-11-20",  # Gurunanak Jayanti
    "2026-12-25",  # Christmas
]
