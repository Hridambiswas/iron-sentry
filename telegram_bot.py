# telegram_bot.py — Async Telegram Alerts + Heartbeat
# Author: Hridam Biswas | Project: Iron-Sentry

import asyncio
import aiohttp
import logging
from datetime import datetime
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, HEARTBEAT_INTERVAL_SEC, STARTING_CAPITAL, DAILY_MIN_TRADES, FORCED_ENTRY_TIME

logger = logging.getLogger("iron_sentry.telegram")

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


class TelegramBot:
    def __init__(self):
        self._session: aiohttp.ClientSession | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._equity: float = STARTING_CAPITAL
        self._starting: float = STARTING_CAPITAL

    def update_equity(self, equity: float):
        self._equity = equity

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self):
        self._session = aiohttp.ClientSession()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        pnl = self._equity - self._starting
        pnl_pct = (pnl / self._starting) * 100
        direction = "📈" if pnl >= 0 else "📉"
        await self.send(
            f"🟢 *Iron-Sentry ONLINE*\n"
            f"Delivery pairs trading | 2 pairs | ₹0 brokerage\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💰 Capital   : ₹`{self._equity:,.2f}`\n"
            f"🏦 Started   : ₹`{self._starting:,.2f}`\n"
            f"{direction} P&L      : ₹`{pnl:+,.2f}` (`{pnl_pct:+.2f}%`)"
        )
        logger.info("Telegram bot started.")

    async def stop(self):
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        await self.send("🔴 *Iron-Sentry OFFLINE*")
        if self._session:
            await self._session.close()
        logger.info("Telegram bot stopped.")

    # ── Core Send ─────────────────────────────────────────────────────────────

    async def send(self, text: str) -> bool:
        """Send a Markdown message. Returns True on success."""
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession()
        try:
            async with self._session.post(
                f"{BASE_URL}/sendMessage",
                json={
                    "chat_id":    TELEGRAM_CHAT_ID,
                    "text":       text,
                    "parse_mode": "Markdown",
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"Telegram HTTP {resp.status}: {await resp.text()}")
                    return False
                return True
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return False

    # ── Formatted Alert Helpers ───────────────────────────────────────────────

    async def alert_signal(self, pair: tuple, zscore: float, action: str):
        emoji = {"ENTER_LONG_A": "📈", "ENTER_LONG_B": "📉",
                 "EXIT": "🔄", "STOP": "🚨"}.get(action, "ℹ️")
        msg = (
            f"{emoji} *SIGNAL* | `{pair[0]}/{pair[1]}`\n"
            f"Action : `{action}`\n"
            f"Z-Score: `{zscore:+.3f}`\n"
            f"Time   : `{_now()}`"
        )
        await self.send(msg)

    async def alert_trade(self, side: str, symbol: str, qty: int,
                          price: float, paper: bool = True):
        tag = "📝 PAPER" if paper else "✅ LIVE"
        msg = (
            f"{tag} *TRADE FILLED*\n"
            f"{side} `{symbol}` × {qty} @ ₹{price:.2f}\n"
            f"Time: `{_now()}`"
        )
        await self.send(msg)

    async def alert_risk(self, reason: str):
        await self.send(f"⚠️ *RISK ALERT*\n{reason}\nTime: `{_now()}`")

    async def alert_error(self, error: str):
        await self.send(f"❌ *ERROR*\n`{error}`\nTime: `{_now()}`")

    # ── Heartbeat ─────────────────────────────────────────────────────────────

    async def _heartbeat_loop(self):
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)
            pnl = self._equity - self._starting
            pnl_pct = (pnl / self._starting) * 100
            direction = "📈" if pnl >= 0 else "📉"
            await self.send(
                f"💓 *Heartbeat* | Bot alive ✅\n"
                f"🕐 `{_now()}`\n"
                f"━━━━━━━━━━━━━━━\n"
                f"💰 Capital   : ₹`{self._equity:,.2f}`\n"
                f"🏦 Started   : ₹`{self._starting:,.2f}`\n"
                f"{direction} P&L      : ₹`{pnl:+,.2f}` (`{pnl_pct:+.2f}%`)"
            )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── Smoke-test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    async def _test():
        bot = TelegramBot()
        await bot.start()
        await bot.alert_signal(("INFY", "TCS"), zscore=-2.73, action="ENTER_LONG_A")
        await asyncio.sleep(2)
        await bot.stop()

    asyncio.run(_test())
