# paper_trader.py — Paper Trading Engine
# Author: Hridam Biswas | Project: Iron-Sentry

import sqlite3
import asyncio
import logging
from datetime import datetime
from dataclasses import dataclass
from typing import Optional
from config import DB_PATH, STARTING_CAPITAL, SLIPPAGE_BPS, MAX_POSITION_PCT

logger = logging.getLogger("iron_sentry.paper_trader")


@dataclass
class Order:
    symbol:    str
    side:      str       # "BUY" | "SELL"
    qty:       int
    price:     float     # limit price submitted
    filled_at: float     # simulated fill (with slippage)
    timestamp: str
    pair_id:   str       # e.g. "INFY_TCS"
    leg:       str       # "A" | "B"


class PaperTrader:
    """
    Simulates order fills against last known price + slippage.
    Persists every trade and P&L snapshot to SQLite.
    """

    def __init__(self):
        self.capital        = STARTING_CAPITAL
        self._realised_pnl  = 0.0
        self.positions: dict[str, dict] = {}   # symbol → {qty, avg_price, side}
        self._db = sqlite3.connect(DB_PATH, check_same_thread=False)
        self._init_db()
        self.daily_trade_count: int = 0

    # ── DB Setup ──────────────────────────────────────────────────────────────

    def _init_db(self):
        c = self._db.cursor()
        c.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS trades (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        TEXT,
                pair_id   TEXT,
                leg       TEXT,
                symbol    TEXT,
                side      TEXT,
                qty       INTEGER,
                price     REAL,
                filled_at REAL,
                pnl       REAL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS equity_curve (
                ts      TEXT PRIMARY KEY,
                equity  REAL
            );
        """)
        self._db.commit()

    # ── Core Order ────────────────────────────────────────────────────────────

    async def place_order(
        self,
        symbol: str,
        side: str,
        price: float,
        pair_id: str,
        leg: str,
    ) -> Optional[Order]:
        """
        Size position, apply slippage, record fill.
        Returns filled Order or None if rejected by sizing rules.
        """
        qty = self._size(price)
        if qty == 0:
            logger.warning(f"Position sizing → 0 for {symbol} @ {price:.2f}. Skipping.")
            return None

        filled_at = self._simulate_fill(price, side)
        cost      = filled_at * qty

        # Update capital & positions
        if side == "BUY":
            self.capital -= cost
            self._update_position(symbol, qty, filled_at, "LONG")
        else:
            self.capital += cost
            self._update_position(symbol, -qty, filled_at, "SHORT")

        order = Order(
            symbol    = symbol,
            side      = side,
            qty       = qty,
            price     = price,
            filled_at = filled_at,
            timestamp = _now(),
            pair_id   = pair_id,
            leg       = leg,
        )
        self._persist_trade(order)
        if leg == "A":
            self.daily_trade_count += 1
        self._snapshot_equity()
        logger.info(f"[PAPER] {side} {symbol} x{qty} @ ₹{filled_at:.2f}")
        return order

    async def close_pair(self, pair_id: str, prices: dict[str, float]) -> float:
        """
        Close both legs of a pair. Returns realised P&L for the pair.
        prices = {"INFY": 1800.5, "TCS": 3900.0}
        """
        pnl = 0.0
        for symbol, pos in list(self.positions.items()):
            if pair_id not in symbol and symbol not in pair_id:
                continue
            close_side = "SELL" if pos["side"] == "LONG" else "BUY"
            close_price = prices.get(symbol, pos["avg_price"])
            filled = self._simulate_fill(close_price, close_side)

            if pos["side"] == "LONG":
                trade_pnl = (filled - pos["avg_price"]) * pos["qty"]
                self.capital += filled * pos["qty"]
            else:
                trade_pnl = (pos["avg_price"] - filled) * pos["qty"]
                self.capital -= filled * pos["qty"]

            pnl += trade_pnl
            del self.positions[symbol]
            logger.info(f"[PAPER] CLOSED {symbol} | P&L ₹{trade_pnl:.2f} | pairs today={self.daily_trade_count}")

        self._realised_pnl += pnl
        self._snapshot_equity()
        return round(pnl, 2)

    def get_equity(self) -> float:
        """Mark-to-market equity: cash + open positions valued at avg entry cost."""
        open_value = sum(
            p["qty"] * p["avg_price"] if p["side"] == "LONG" else -p["qty"] * p["avg_price"]
            for p in self.positions.values()
        )
        return round(self.capital + open_value, 2)

    def reset_daily(self):
        self.daily_trade_count = 0

    @property
    def realised_pnl(self) -> float:
        return round(self._realised_pnl, 2)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _size(self, price: float) -> int:
        alloc  = self.capital * MAX_POSITION_PCT
        qty    = int(alloc / price)
        return max(qty, 0)

    def _simulate_fill(self, price: float, side: str) -> float:
        slip = price * SLIPPAGE_BPS / 10_000
        return price + slip if side == "BUY" else price - slip

    def _update_position(self, symbol: str, qty: int, price: float, side: str):
        if symbol in self.positions:
            old = self.positions[symbol]
            total_qty = old["qty"] + abs(qty)
            avg = (old["avg_price"] * old["qty"] + price * abs(qty)) / total_qty
            self.positions[symbol] = {"qty": total_qty, "avg_price": avg, "side": side}
        else:
            self.positions[symbol] = {"qty": abs(qty), "avg_price": price, "side": side}

    def _persist_trade(self, o: Order):
        self._db.execute(
            "INSERT INTO trades (ts,pair_id,leg,symbol,side,qty,price,filled_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (o.timestamp, o.pair_id, o.leg, o.symbol,
             o.side, o.qty, o.price, o.filled_at),
        )
        self._db.commit()

    def _snapshot_equity(self):
        self._db.execute(
            "INSERT OR REPLACE INTO equity_curve (ts, equity) VALUES (?,?)",
            (_now(), self.get_equity()),
        )
        self._db.commit()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── Smoke-test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    async def _test():
        pt = PaperTrader()
        print(f"Starting equity: ₹{pt.get_equity()}")

        o = await pt.place_order("INFY", "BUY", 1800.0, "INFY_TCS", "A")
        print(f"Order: {o}")

        o2 = await pt.place_order("TCS", "SELL", 3900.0, "INFY_TCS", "B")
        print(f"Order: {o2}")

        pnl = await pt.close_pair("INFY_TCS", {"INFY": 1820.0, "TCS": 3880.0})
        print(f"Pair P&L: ₹{pnl}")
        print(f"Closing equity: ₹{pt.get_equity()}")

    asyncio.run(_test())
