# main.py — Iron-Sentry Orchestrator
# Author: Hridam Biswas | Project: Iron-Sentry

import asyncio
import logging
import logging.handlers
from datetime import datetime, time as _dtime
import yfinance as yf
from config import PAIRS, STARTING_CAPITAL, PAPER_TRADING, LOG_FILE, MAX_CONCURRENT_PAIRS, FORCE_CLOSE_TIME, DAILY_MIN_TRADES, FORCED_ENTRY_TIME
from zscore_engine  import ZScoreEngine
from telegram_bot   import TelegramBot
from paper_trader   import PaperTrader
from risk_manager   import RiskManager

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=10_000_000, backupCount=5  # 10MB per file, keep 5
        ),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("iron_sentry.main")


# ─────────────────────────────────────────────────────────────────────────────
#  PRICE FEED  (Month 1: yfinance delayed | Month 2+: Dhan WebSocket)
# ─────────────────────────────────────────────────────────────────────────────

_NSE_SYMBOLS: dict[str, str] = {
    "SAIL":      "SAIL.NS",
    "NMDC":      "NMDC.NS",
    "NTPC":      "NTPC.NS",
    "POWERGRID": "POWERGRID.NS",
}

_last_prices: dict[str, float] = {}  # fallback on network error
_last_bar_date: str = ""             # prevents feeding same daily bar twice


async def get_prices() -> tuple[dict[str, float], str]:
    """
    Fetches daily closing prices from NSE via yfinance.
    Returns (prices, bar_date) — bar_date is the date of the latest close.
    Runs in thread executor so it doesn't block the async loop.
    Month 2+: replace body with Dhan WebSocket LTP call.
    """
    loop = asyncio.get_event_loop()

    def _fetch() -> tuple[dict[str, float], str]:
        ns_syms = list(_NSE_SYMBOLS.values())
        data = yf.download(ns_syms, period="90d", interval="1d",
                           progress=False, auto_adjust=True)
        prices = {}
        bar_date = ""
        for sym, ns_sym in _NSE_SYMBOLS.items():
            try:
                series = data[("Close", ns_sym)].dropna()
                price = float(series.values[-1])
                if price > 0:
                    prices[sym] = price
                    bar_date = str(series.index[-1].date())
            except Exception:
                pass
        return prices, bar_date

    try:
        fresh, bar_date = await asyncio.wait_for(
            loop.run_in_executor(None, _fetch), timeout=30.0
        )
        if fresh:
            _last_prices.update(fresh)
        else:
            logger.warning("yfinance returned empty — using last known prices")
        return dict(_last_prices), bar_date
    except asyncio.TimeoutError:
        logger.warning("yfinance fetch timed out (30s) — using last known prices")
        return dict(_last_prices), ""
    except Exception as e:
        logger.error(f"Price fetch failed: {e} — using last known prices")
        return dict(_last_prices), ""


# ─────────────────────────────────────────────────────────────────────────────
#  PAIR WORKER — runs one pair end-to-end
# ─────────────────────────────────────────────────────────────────────────────

class PairWorker:
    def __init__(self, leg_a: str, leg_b: str,
                 telegram: TelegramBot, trader: PaperTrader, risk: RiskManager):
        self.leg_a         = leg_a
        self.leg_b         = leg_b
        self.pair_id       = f"{leg_a}_{leg_b}"
        self.engine        = ZScoreEngine(leg_a, leg_b)
        self.telegram      = telegram
        self.trader        = trader
        self.risk          = risk
        self.in_trade      = False
        self._last_bar_date = ""  # skip duplicate daily bars

    async def tick(self, prices: dict[str, float], bar_date: str, open_pairs: int = 0):
        pa = prices.get(self.leg_a)
        pb = prices.get(self.leg_b)
        if pa is None or pb is None:
            return

        # Only feed a new daily bar into the engine — skip duplicates
        if bar_date and bar_date == self._last_bar_date:
            return
        if bar_date:
            self._last_bar_date = bar_date

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
            if open_pairs >= MAX_CONCURRENT_PAIRS:
                logger.info(f"Entry blocked for {self.pair_id} — max concurrent pairs ({MAX_CONCURRENT_PAIRS}) reached")
                return
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

    async def force_close(self, prices: dict[str, float]):
        """Force-close open position — used for Friday EOD and manual halt."""
        if not self.in_trade:
            return
        pnl = await self.trader.close_pair(self.pair_id, prices)
        self.in_trade = False
        self.risk.clear_pair(self.pair_id)
        await self.telegram.send(
            f"🗓 *WEEKEND CLOSE* | `{self.pair_id}`\n"
            f"Force-closed before weekend gap\nRealised P&L: ₹{pnl:.2f}"
        )
        logger.info(f"{self.pair_id} force-closed for weekend | P&L ₹{pnl:.2f}")

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

async def warmup_engines(workers: list) -> str:
    """
    Feed all available historical daily bars into each engine so signals
    are available on the very first tick, instead of waiting 30+ hours.
    Returns the date of the last bar fed.
    """
    loop = asyncio.get_event_loop()

    def _fetch_history():
        ns_syms = list(_NSE_SYMBOLS.values())
        return yf.download(ns_syms, period="90d", interval="1d",
                           progress=False, auto_adjust=True)

    try:
        data = await asyncio.wait_for(
            loop.run_in_executor(None, _fetch_history), timeout=60.0
        )
    except Exception as e:
        logger.error(f"Warmup fetch failed: {e}")
        return ""

    last_bar_date = ""
    n_bars = len(data.index)
    for i, ts in enumerate(data.index):
        bar_date = str(ts.date())
        prices: dict[str, float] = {}
        for sym, ns_sym in _NSE_SYMBOLS.items():
            try:
                price = float(data[("Close", ns_sym)].iloc[i])
                if price > 0 and price == price:  # NaN check without numpy import
                    prices[sym] = price
            except Exception:
                pass

        for w in workers:
            pa = prices.get(w.leg_a)
            pb = prices.get(w.leg_b)
            if pa and pb:
                w.engine.update(pa, pb)
                w._last_bar_date = bar_date
        last_bar_date = bar_date

    logger.info(f"Warmup complete — fed {n_bars} historical bars, last bar={last_bar_date}")
    return last_bar_date


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

    logger.info("Warming up z-score engines with historical data...")
    await warmup_engines(workers)
    logger.info("Engines ready — entering main loop")

    _last_reset_date = ""

    _force_close_time = _dtime(*map(int, FORCE_CLOSE_TIME.split(":")))

    try:
        while True:
            now   = datetime.now()
            today = now.strftime("%Y-%m-%d")

            prices, bar_date = await get_prices()
            equity = trader.get_equity()
            risk.update_equity(equity)
            telegram.update_equity(equity)

            # Daily reset — must happen after equity is fetched so daily_high is correct
            if today != _last_reset_date:
                risk.reset_daily(equity)
                _last_reset_date = today
                logger.info(f"Daily reset — {today}")

            # Count currently open pairs to enforce MAX_CONCURRENT_PAIRS
            open_pairs = sum(1 for w in workers if w.in_trade)

            logger.info(
                f"Heartbeat | equity=Rs.{equity:.2f} | bar={bar_date or 'pending'} | open_pairs={open_pairs}"
            )

            # Friday force-close: prevent carrying open positions over weekend gap
            is_friday = now.weekday() == 4
            if is_friday and now.time() >= _force_close_time:
                for w in workers:
                    if w.in_trade:
                        await w.force_close(prices)
            else:
                # Fan-out: all pair workers tick concurrently
                await asyncio.gather(*[
                    w.tick(prices, bar_date, open_pairs) for w in workers
                ])

            # Daily delivery strategy — check every hour, engine only updates on new bar
            await asyncio.sleep(3600)

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
