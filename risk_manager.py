# risk_manager.py — Risk Manager
# Author: Hridam Biswas | Project: Iron-Sentry

import logging
import asyncio
from datetime import datetime, time
from config import (
    MAX_DRAWDOWN_PCT, MAX_ORDERS_PER_SEC,
    MARKET_OPEN_IST, MARKET_CLOSE_IST, LAST_ENTRY_TIME, NSE_HOLIDAYS,
)

logger = logging.getLogger("iron_sentry.risk")


class RiskManager:
    """
    Guards:
    1. Daily drawdown halt  → stops all trading if equity drops > MAX_DRAWDOWN_PCT
    2. Order rate limiter   → async token bucket (max 8 orders/sec)
    3. Market hours check   → blocks orders outside NSE session
    4. Ghost order tracker  → flags pairs with unconfirmed legs (leg-out trap)
    5. Z-score stop-loss    → handled in ZScoreEngine, enforced here
    """

    def __init__(self, starting_equity: float):
        self.starting_equity    = starting_equity
        self.daily_high         = starting_equity
        self._halted            = False
        self._halt_reason       = ""

        # Rate limiter state
        self._order_timestamps: list[float] = []

        # Ghost order tracking: pair_id → {"A": bool, "B": bool}
        self._pending_legs: dict[str, dict] = {}

    # ── Pre-trade Checks ──────────────────────────────────────────────────────

    def can_trade(self, current_equity: float) -> tuple[bool, str]:
        """Master gate. Call before every order pair."""
        if self._halted:
            return False, f"HALTED: {self._halt_reason}"
        if self._is_nse_holiday():
            return False, f"NSE holiday — no trading today"
        if not self._market_open():
            return False, "Outside market hours (09:15–15:30 IST)"
        if not self._before_last_entry_cutoff():
            return False, f"Past last entry cutoff ({LAST_ENTRY_TIME} IST)"
        drawdown = self._drawdown(current_equity)
        if drawdown >= MAX_DRAWDOWN_PCT:
            self._halt(f"Daily drawdown {drawdown:.1%} ≥ {MAX_DRAWDOWN_PCT:.1%}")
            return False, self._halt_reason
        return True, "OK"

    async def acquire_order_slot(self):
        """
        Async token bucket — suspends coroutine if > MAX_ORDERS_PER_SEC.
        Always await this before placing any order.
        """
        loop = asyncio.get_event_loop()
        now  = loop.time()
        # Drop timestamps older than 1 second
        self._order_timestamps = [t for t in self._order_timestamps if now - t < 1.0]
        if len(self._order_timestamps) >= MAX_ORDERS_PER_SEC:
            sleep_for = 1.0 - (now - self._order_timestamps[0])
            logger.warning(f"Rate limit hit — sleeping {sleep_for:.3f}s")
            await asyncio.sleep(max(sleep_for, 0.05))
        self._order_timestamps.append(loop.time())

    # ── Leg-Out / Ghost Order Protection ─────────────────────────────────────

    def register_leg(self, pair_id: str, leg: str):
        """Call when leg A or B order is sent."""
        if pair_id not in self._pending_legs:
            self._pending_legs[pair_id] = {"A": False, "B": False}
        self._pending_legs[pair_id][leg] = True

    def confirm_leg(self, pair_id: str, leg: str):
        """Call when fill confirmation received."""
        if pair_id in self._pending_legs:
            self._pending_legs[pair_id][leg] = False

    def has_ghost_leg(self, pair_id: str) -> bool:
        """True if one leg is filled but the other isn't (leg-out trap)."""
        legs = self._pending_legs.get(pair_id, {})
        vals = list(legs.values())
        return len(vals) == 2 and vals[0] != vals[1]

    def clear_pair(self, pair_id: str):
        self._pending_legs.pop(pair_id, None)

    # ── Equity Tracking ───────────────────────────────────────────────────────

    def update_equity(self, equity: float):
        if equity > self.daily_high:
            self.daily_high = equity

    def reset_daily(self):
        """Call at market open each day."""
        self.daily_high = self.starting_equity
        self._halted    = False
        self._halt_reason = ""
        logger.info("Risk manager daily reset.")

    # ── Status ────────────────────────────────────────────────────────────────

    @property
    def is_halted(self) -> bool:
        return self._halted

    def status(self) -> dict:
        return {
            "halted":      self._halted,
            "halt_reason": self._halt_reason,
            "daily_high":  self.daily_high,
            "ghost_pairs": [p for p, l in self._pending_legs.items()
                            if l.get("A") != l.get("B")],
        }

    # ── Internals ─────────────────────────────────────────────────────────────

    def _drawdown(self, current_equity: float) -> float:
        if self.daily_high == 0:
            return 0.0
        return (self.daily_high - current_equity) / self.daily_high

    def _halt(self, reason: str):
        self._halted      = True
        self._halt_reason = reason
        logger.critical(f"TRADING HALTED — {reason}")

    @staticmethod
    def _market_open() -> bool:
        now = datetime.now().time()
        open_t  = time(*map(int, MARKET_OPEN_IST.split(":")))
        close_t = time(*map(int, MARKET_CLOSE_IST.split(":")))
        return open_t <= now <= close_t

    @staticmethod
    def _is_nse_holiday() -> bool:
        today = datetime.now().strftime("%Y-%m-%d")
        return today in NSE_HOLIDAYS

    @staticmethod
    def _before_last_entry_cutoff() -> bool:
        now    = datetime.now().time()
        cutoff = time(*map(int, LAST_ENTRY_TIME.split(":")))
        return now <= cutoff


# ── Smoke-test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    async def _test():
        rm = RiskManager(starting_equity=5000.0)

        ok, msg = rm.can_trade(4900.0)
        print(f"can_trade: {ok} | {msg}")

        # Rate limiter test — fire 10 orders, should throttle
        print("Rate limiting 10 rapid orders...")
        for i in range(10):
            await rm.acquire_order_slot()
            print(f"  Order slot {i+1} acquired")

        # Ghost order test
        rm.register_leg("INFY_TCS", "A")
        print(f"Ghost after A sent: {rm.has_ghost_leg('INFY_TCS')}")
        rm.register_leg("INFY_TCS", "B")
        print(f"Ghost after B sent: {rm.has_ghost_leg('INFY_TCS')}")

    asyncio.run(_test())
