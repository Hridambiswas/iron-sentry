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
