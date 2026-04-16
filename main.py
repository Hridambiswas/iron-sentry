# main.py — Iron-Sentry Orchestrator
# Author: Hridam Biswas | Project: Iron-Sentry

import asyncio
import logging
from datetime import datetime
import yfinance as yf
from config import PAIRS, STARTING_CAPITAL, PAPER_TRADING, LOG_FILE
from zscore_engine  import ZScoreEngine
from telegram_bot   import TelegramBot
from paper_trader   import PaperTrader
from risk_manager   import RiskManager

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("iron_sentry.main")


# ─────────────────────────────────────────────────────────────────────────────
#  PRICE FEED  (Month 1: yfinance delayed | Month 2+: Dhan WebSocket)
# ─────────────────────────────────────────────────────────────────────────────

_NSE_SYMBOLS: dict[str, str] = {
    "INFY":       "INFY.NS",
    "TCS":        "TCS.NS",
    "HDFCBANK":   "HDFCBANK.NS",
    "ICICIBANK":  "ICICIBANK.NS",
    "MARUTI":     "MARUTI.NS",
    "BAJAJ-AUTO": "BAJAJ-AUTO.NS",
}

_last_prices: dict[str, float] = {}   # fallback if fetch fails


async def get_prices() -> dict[str, float]:
    """
    Fetches latest NSE prices via yfinance (15-20 min delayed).
    Runs in a thread executor so it doesn't block the async loop.
    Falls back to last known prices on network error.
    Month 2+: replace body with Dhan WebSocket LTP call.
    """
    loop = asyncio.get_event_loop()

    def _fetch() -> dict[str, float]:
        ns_syms = list(_NSE_SYMBOLS.values())
        data = yf.download(ns_syms, period="1d", interval="1m",
                           progress=False, auto_adjust=True)
        prices = {}
        for sym, ns_sym in _NSE_SYMBOLS.items():
            try:
                price = float(data[("Close", ns_sym)].dropna().values[-1])
                if price > 0:
                    prices[sym] = price
            except Exception:
                pass
        return prices

    try:
        fresh = await loop.run_in_executor(None, _fetch)
        if fresh:
            _last_prices.update(fresh)
            return dict(_last_prices)
        else:
            logger.warning("yfinance returned empty prices — using last known")
            return dict(_last_prices)
    except Exception as e:
        logger.error(f"Price fetch failed: {e} — using last known prices")
        return dict(_last_prices)


# ─────────────────────────────────────────────────────────────────────────────
#  PAIR WORKER — runs one pair end-to-end
# ─────────────────────────────────────────────────────────────────────────────

class PairWorker:
    def __init__(self, leg_a: str, leg_b: str,
                 telegram: TelegramBot, trader: PaperTrader, risk: RiskManager):
        self.leg_a    = leg_a
        self.leg_b    = leg_b
        self.pair_id  = f"{leg_a}_{leg_b}"
        self.engine   = ZScoreEngine(leg_a, leg_b)
        self.telegram = telegram
        self.trader   = trader
        self.risk     = risk
        self.in_trade = False

    async def tick(self, prices: dict[str, float]):
        pa = prices.get(self.leg_a)
        pb = prices.get(self.leg_b)
        if pa is None or pb is None:
            return

        signal = self.engine.update(pa, pb)
        if signal is None:
            return   # still warming up

        logger.info(f"{self.pair_id} | z={signal.zscore:+.4f} | {signal.action}")

        ok, reason = self.risk.can_trade(self.trader.get_equity())
        if not ok:
            logger.warning(f"Trade blocked for {self.pair_id}: {reason}")
            return

        # ── Entry ──────────────────────────────────────────────────────────
        if not self.in_trade and signal.action in ("ENTER_LONG_A", "ENTER_LONG_B"):
            await self._open_pair(signal, prices)

        # ── Exit (mean reversion) ──────────────────────────────────────────
        elif self.in_trade and signal.action in ("EXIT", "STOP"):
            await self._close_pair(signal, prices)

    async def _open_pair(self, signal, prices):
        if signal.action == "ENTER_LONG_A":
            side_a, side_b = "BUY", "SELL"
        else:
            side_a, side_b = "SELL", "BUY"

        # Ghost-order guard: register both legs before sending
        self.risk.register_leg(self.pair_id, "A")
        self.risk.register_leg(self.pair_id, "B")

        await self.risk.acquire_order_slot()
        order_a = await self.trader.place_order(
            self.leg_a, side_a, prices[self.leg_a], self.pair_id, "A")

        await self.risk.acquire_order_slot()
        order_b = await self.trader.place_order(
            self.leg_b, side_b, prices[self.leg_b], self.pair_id, "B")

        if order_a and order_b:
            self.risk.confirm_leg(self.pair_id, "A")
            self.risk.confirm_leg(self.pair_id, "B")
            self.in_trade = True
            await self.telegram.alert_signal(
                (self.leg_a, self.leg_b), signal.zscore, signal.action)
            await self.telegram.alert_trade(
                side_a, self.leg_a, order_a.qty, order_a.filled_at, PAPER_TRADING)
            await self.telegram.alert_trade(
                side_b, self.leg_b, order_b.qty, order_b.filled_at, PAPER_TRADING)
        else:
            # One leg failed → ghost order risk → alert
            await self.telegram.alert_risk(
                f"⚠️ Leg failure on {self.pair_id}. Check ghost orders!")
            self.risk.clear_pair(self.pair_id)

    async def _close_pair(self, signal, prices):
        pnl = await self.trader.close_pair(self.pair_id, prices)
        self.in_trade = False
        self.risk.clear_pair(self.pair_id)
        tag = "🚨 STOP" if signal.action == "STOP" else "🔄 EXIT"
        await self.telegram.send(
            f"{tag} *{self.pair_id}* closed\n"
            f"Z={signal.zscore:+.3f} | Realised P&L: ₹{pnl:.2f}"
        )
        logger.info(f"{self.pair_id} closed | P&L ₹{pnl:.2f}")


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    logger.info("=" * 60)
    logger.info("  Iron-Sentry starting up")
    logger.info(f"  Mode: {'PAPER' if PAPER_TRADING else 'LIVE'}")
    logger.info("=" * 60)

    telegram = TelegramBot()
    trader   = PaperTrader()
    risk     = RiskManager(starting_equity=STARTING_CAPITAL)

    await telegram.start()

    workers = [
        PairWorker(a, b, telegram, trader, risk)
        for a, b in PAIRS
    ]

    try:
        while True:
            prices = await get_prices()
            equity = trader.get_equity()
            risk.update_equity(equity)
            telegram.update_equity(equity)

            # Fan-out: all pair workers tick concurrently
            await asyncio.gather(*[w.tick(prices) for w in workers])

            # TODO: tune tick interval when live feed arrives
            await asyncio.sleep(60)   # 1-minute bars during paper phase

    except asyncio.CancelledError:
        logger.info("Shutdown signal received.")
    except Exception as e:
        logger.exception(f"Unhandled exception: {e}")
        await telegram.alert_error(str(e))
    finally:
        await telegram.stop()
        logger.info("Iron-Sentry stopped.")


if __name__ == "__main__":
    asyncio.run(main())
