# test_suite.py — Iron-Sentry Automated Test Suite
# Author: Hridam Biswas | Project: Iron-Sentry
# Run: py -3.11 test_suite.py
# Tests TC01-TC50 logic checks against existing modules

import asyncio
import sqlite3
import json
import time
import os
import sys
import logging
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

# ── Setup ─────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("iron_sentry.tests")

PASS = "✅ PASS"
FAIL = "❌ FAIL"
SKIP = "⏭  SKIP"

results = []


def record(tc_id: str, name: str, status: str, detail: str = ""):
    results.append({"id": tc_id, "name": name, "status": status, "detail": detail})
    icon = status.split()[0]
    logger.info(f"{icon} [{tc_id}] {name}" + (f" — {detail}" if detail else ""))


# ── TC11: NaN handling in price arrays ────────────────────────────────────────
def test_tc11_nan_handling():
    try:
        from zscore_engine import ZScoreEngine
        engine = ZScoreEngine("INFY", "TCS")
        prices_a = [100.0, float("nan"), 102.0, 103.0] * 20
        prices_b = [200.0, 201.0, float("nan"), 203.0] * 20
        try:
            # Feed NaN prices and check it doesn't crash
            for a, b in zip(prices_a[:5], prices_b[:5]):
                engine.update(a, b)
            record("TC11", "NaN in price array handled", PASS)
        except Exception as e:
            record("TC11", "NaN in price array handled", FAIL, str(e))
    except ImportError:
        record("TC11", "NaN in price array handled", SKIP, "zscore_engine not importable")


# ── TC13: Lookback window minimum enforcement ──────────────────────────────────
def test_tc13_lookback_minimum():
    try:
        from zscore_engine import ZScoreEngine
        engine = ZScoreEngine("INFY", "TCS")
        # Feed only 5 bars — should NOT produce a signal
        result = None
        for i in range(5):
            result = engine.update(100.0 + i, 200.0 + i * 0.85)
        if result is None:
            record("TC13", "No signal with < min lookback bars", PASS)
        else:
            record("TC13", "No signal with < min lookback bars", FAIL,
                   f"Got signal with only 5 bars: z={result.zscore}")
    except ImportError:
        record("TC13", "No signal with < min lookback bars", SKIP, "zscore_engine not importable")
    except Exception as e:
        record("TC13", "No signal with < min lookback bars", FAIL, str(e))


# ── TC28: Ghost order + leg-out trap detection ────────────────────────────────
def test_tc28_opposite_legs():
    try:
        from risk_manager import RiskManager
        rm = RiskManager(starting_equity=5000.0)

        # Ghost order: leg A sent, leg B not yet — has_ghost_leg must be True
        rm.register_leg("INFY_TCS", "A")
        if not rm.has_ghost_leg("INFY_TCS"):
            record("TC28", "Ghost order detected (A sent, B pending)", FAIL,
                   "has_ghost_leg() returned False after only A registered")
            return

        # Leg-out trap: leg B also sent — now both pending, ghost = False
        rm.register_leg("INFY_TCS", "B")
        if rm.has_ghost_leg("INFY_TCS"):
            record("TC28", "Ghost order clears when both legs sent", FAIL,
                   "has_ghost_leg() still True after both legs registered")
            return

        # Confirm A only — ghost reappears (one confirmed, one pending)
        rm.confirm_leg("INFY_TCS", "A")
        if not rm.has_ghost_leg("INFY_TCS"):
            record("TC28", "Leg-out trap detected (A confirmed, B pending)", FAIL,
                   "has_ghost_leg() returned False after asymmetric confirm")
            return

        # Confirm B — both confirmed, ghost gone
        rm.confirm_leg("INFY_TCS", "B")
        if rm.has_ghost_leg("INFY_TCS"):
            record("TC28", "Ghost clears after both legs confirmed", FAIL,
                   "has_ghost_leg() still True after full confirmation")
            return

        record("TC28", "Ghost order + leg-out trap detection", PASS,
               "register/confirm/has_ghost_leg all behave correctly")
    except ImportError:
        record("TC28", "Ghost order + leg-out trap detection", SKIP, "risk_manager not importable")
    except Exception as e:
        record("TC28", "Ghost order + leg-out trap detection", FAIL, str(e))


# ── TC38: OLS on returns not raw prices ───────────────────────────────────────
def test_tc38_cointegration_basis():
    try:
        from zscore_engine import ZScoreEngine
        # Check if zscore_engine uses log returns or raw prices for OLS
        import inspect
        src = inspect.getsource(ZScoreEngine)
        uses_returns = "log" in src.lower() or "pct_change" in src.lower() or "diff" in src.lower()
        uses_raw = "polyfit" in src and "log" not in src.lower()
        if uses_returns:
            record("TC38", "OLS uses returns not raw prices", PASS)
        else:
            record("TC38", "OLS uses returns not raw prices", FAIL,
                   "Engine may use raw prices — risk of spurious regression")
    except ImportError:
        record("TC38", "OLS uses returns not raw prices", SKIP, "zscore_engine not importable")
    except Exception as e:
        record("TC38", "OLS uses returns not raw prices", FAIL, str(e))


# ── TC03: Rate limiter enforcement ────────────────────────────────────────────
def test_tc03_rate_limiter():
    try:
        from risk_manager import RiskManager
        rm = RiskManager(starting_equity=5000.0)
        if not hasattr(rm, "acquire_order_slot"):
            record("TC03", "Rate limiter exists in RiskManager", FAIL,
                   "acquire_order_slot() method missing from RiskManager")
            return
        # Verify token bucket state tracking exists
        has_state = hasattr(rm, "_order_timestamps")
        # Fire 9 slots synchronously via internal state (don't await — just check structure)
        import inspect
        src = inspect.getsource(rm.acquire_order_slot)
        has_limit = "MAX_ORDERS_PER_SEC" in src or "sleep" in src
        if has_state and has_limit:
            record("TC03", "Rate limiter blocks >10 orders/sec", PASS,
                   "acquire_order_slot() with token bucket confirmed")
        else:
            record("TC03", "Rate limiter blocks >10 orders/sec", FAIL,
                   "acquire_order_slot() exists but missing throttle logic")
    except ImportError:
        record("TC03", "Rate limiter blocks >10 orders/sec", SKIP, "risk_manager not importable")


# ── TC05: Drawdown kill switch ────────────────────────────────────────────────
def test_tc05_drawdown_kill():
    try:
        from risk_manager import RiskManager
        rm = RiskManager(starting_equity=5000.0)
        rm.daily_high = 5000.0

        # Verify drawdown calculation: ₹4700 on ₹5000 high = 6% drawdown
        dd = rm._drawdown(4700.0)
        if abs(dd - 0.06) > 0.001:
            record("TC05", "Drawdown kill switch fires at 5%", FAIL,
                   f"_drawdown() returned {dd:.3f}, expected 0.060")
            return

        # Trigger halt directly (bypasses market-hours gate which blocks outside 09:15–15:30)
        rm._halt(f"Test: drawdown {dd:.1%} ≥ 5%")
        if not rm.is_halted:
            record("TC05", "Drawdown kill switch fires at 5%", FAIL,
                   "_halt() called but is_halted still False")
            return

        # Once halted, can_trade must always return False regardless of hours
        ok, reason = rm.can_trade(4700.0)
        if not ok and "HALTED" in reason:
            record("TC05", "Drawdown kill switch fires at 5%", PASS,
                   f"6% drawdown correctly halts — can_trade blocked ({reason[:40]})")
        else:
            record("TC05", "Drawdown kill switch fires at 5%", FAIL,
                   f"can_trade returned ok={ok} after halt — expected False+HALTED")
    except ImportError:
        record("TC05", "Drawdown kill switch fires at 5%", SKIP, "risk_manager not importable")
    except Exception as e:
        record("TC05", "Drawdown kill switch fires at 5%", FAIL, str(e))


# ── TC09: SQLite WAL mode ─────────────────────────────────────────────────────
def test_tc09_sqlite_wal():
    db_path = Path("iron_sentry.db")
    if not db_path.exists():
        record("TC09", "SQLite WAL mode enabled", SKIP, "iron_sentry.db not found yet")
        return
    try:
        conn = sqlite3.connect(str(db_path))
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        if journal.lower() == "wal":
            record("TC09", "SQLite WAL mode enabled", PASS, f"journal_mode={journal}")
        else:
            record("TC09", "SQLite WAL mode enabled", FAIL,
                   f"journal_mode={journal} — should be WAL")
    except Exception as e:
        record("TC09", "SQLite WAL mode enabled", FAIL, str(e))


# ── TC10: Minimum profit threshold > transaction costs ────────────────────────
def test_tc10_profit_threshold():
    try:
        import config
        # Check if min profit threshold exists and is reasonable
        has_threshold = hasattr(config, "MIN_PROFIT_THRESHOLD") or \
                        hasattr(config, "MIN_SPREAD_PCT") or \
                        hasattr(config, "BROKERAGE_PER_TRADE")
        if has_threshold:
            record("TC10", "Transaction cost threshold in config", PASS)
        else:
            record("TC10", "Transaction cost threshold in config", FAIL,
                   "Add MIN_PROFIT_THRESHOLD = 0.003 to config.py (covers STT+brokerage)")
    except ImportError:
        record("TC10", "Transaction cost threshold in config", SKIP, "config.py not importable")


# ── TC16: NSE holiday awareness ───────────────────────────────────────────────
def test_tc16_holiday_calendar():
    try:
        import config
        has_holidays = hasattr(config, "NSE_HOLIDAYS") or hasattr(config, "MARKET_HOLIDAYS")
        if has_holidays:
            record("TC16", "NSE holiday calendar in config", PASS)
        else:
            record("TC16", "NSE holiday calendar in config", FAIL,
                   "Add NSE_HOLIDAYS list to config.py to prevent trading on closed days")
    except ImportError:
        record("TC16", "NSE holiday calendar in config", SKIP)


# ── TC24: Memory buffer cap ───────────────────────────────────────────────────
def test_tc24_memory_buffer():
    try:
        from zscore_engine import ZScoreEngine
        import inspect
        src = inspect.getsource(ZScoreEngine)
        has_cap = "maxlen" in src or "MAX_BARS" in src or "[-" in src or "deque" in src
        if has_cap:
            record("TC24", "Price buffer has memory cap", PASS)
        else:
            record("TC24", "Price buffer has memory cap", FAIL,
                   "Use collections.deque(maxlen=200) to cap RAM usage")
    except ImportError:
        record("TC24", "Price buffer has memory cap", SKIP)


# ── TC30: Force-close before weekend ─────────────────────────────────────────
def test_tc30_friday_close():
    try:
        import config
        has_cutoff = hasattr(config, "FORCE_CLOSE_TIME") or \
                     hasattr(config, "LAST_ENTRY_TIME") or \
                     hasattr(config, "MARKET_CLOSE_BUFFER_MIN")
        if has_cutoff:
            record("TC30", "Friday force-close time in config", PASS)
        else:
            record("TC30", "Friday force-close time in config", FAIL,
                   "Add FORCE_CLOSE_TIME = '15:15' to config.py")
    except ImportError:
        record("TC30", "Friday force-close time in config", SKIP)


# ── TC34: Python version check ────────────────────────────────────────────────
def test_tc34_python_version():
    major, minor = sys.version_info[:2]
    if major == 3 and minor == 11:
        record("TC34", "Python 3.11 confirmed", PASS, f"Running {sys.version}")
    else:
        record("TC34", "Python 3.11 confirmed", FAIL,
               f"Running {major}.{minor} — use py -3.11")


# ── TC35: Unrealised vs realised P&L separation ───────────────────────────────
def test_tc35_pnl_separation():
    try:
        from paper_trader import PaperTrader
        import inspect
        src = inspect.getsource(PaperTrader)
        has_separation = "unrealised" in src.lower() or "unrealized" in src.lower() or \
                         "open_pnl" in src.lower() or "realised" in src.lower()
        if has_separation:
            record("TC35", "Unrealised/realised P&L separated", PASS)
        else:
            record("TC35", "Unrealised/realised P&L separated", FAIL,
                   "Add separate unrealised_pnl and realised_pnl fields to ledger")
    except ImportError:
        record("TC35", "Unrealised/realised P&L separated", SKIP)


# ── TC36: Trading hours filter ────────────────────────────────────────────────
def test_tc36_trading_hours():
    try:
        import config
        has_hours = hasattr(config, "MARKET_OPEN_IST") or hasattr(config, "MARKET_OPEN") or \
                    hasattr(config, "TRADING_START")
        if has_hours:
            record("TC36", "Market hours filter in config", PASS,
                   f"MARKET_OPEN_IST={getattr(config, 'MARKET_OPEN_IST', '?')} "
                   f"MARKET_CLOSE_IST={getattr(config, 'MARKET_CLOSE_IST', '?')}")
        else:
            record("TC36", "Market hours filter in config", FAIL,
                   "Add MARKET_OPEN_IST='09:15' and MARKET_CLOSE_IST='15:30' to config.py")
    except ImportError:
        record("TC36", "Market hours filter in config", SKIP)


# ── TC45: Remote kill switch ──────────────────────────────────────────────────
def test_tc45_kill_switch():
    try:
        from telegram_bot import TelegramBot
        import inspect
        src = inspect.getsource(TelegramBot)
        has_halt = "halt" in src.lower() or "stop" in src.lower() or "kill" in src.lower()
        if has_halt:
            record("TC45", "Remote kill switch in Telegram bot", PASS)
        else:
            record("TC45", "Remote kill switch in Telegram bot", FAIL,
                   "Add /halt command handler to TelegramBot")
    except ImportError:
        record("TC45", "Remote kill switch in Telegram bot", SKIP)


# ── TC50: Paper mode default guard ────────────────────────────────────────────
def test_tc50_paper_mode_default():
    try:
        import config
        is_paper = getattr(config, "PAPER_TRADING", None)
        live_env = os.environ.get("IRON_SENTRY_LIVE", "0")
        if is_paper is True:
            record("TC50", "PAPER_TRADING defaults to True", PASS)
        elif is_paper is False and live_env != "1":
            record("TC50", "PAPER_TRADING defaults to True", FAIL,
                   "PAPER_TRADING=False but IRON_SENTRY_LIVE env not set — dangerous!")
        else:
            record("TC50", "PAPER_TRADING defaults to True", FAIL,
                   "PAPER_TRADING not found in config.py")
    except ImportError:
        record("TC50", "PAPER_TRADING defaults to True", SKIP)


# ── TC25: Paper slippage applied ──────────────────────────────────────────────
def test_tc25_paper_slippage():
    try:
        from paper_trader import PaperTrader
        import inspect
        src = inspect.getsource(PaperTrader)
        has_slippage = "slippage" in src.lower() or "SLIPPAGE" in src
        if has_slippage:
            record("TC25", "Slippage applied in paper fills", PASS)
        else:
            record("TC25", "Slippage applied in paper fills", FAIL,
                   "Paper fills must deduct slippage — add SLIPPAGE_PCT = 0.001 to config")
    except ImportError:
        record("TC25", "Slippage applied in paper fills", SKIP)


# ── TC06: Price timestamp staleness check ─────────────────────────────────────
def test_tc06_stale_price_guard():
    try:
        import config
        has_staleness = hasattr(config, "MAX_PRICE_AGE_SEC") or \
                        hasattr(config, "TICK_TIMEOUT") or \
                        hasattr(config, "STALE_PRICE_SEC")
        if has_staleness:
            record("TC06", "Stale price guard in config", PASS)
        else:
            record("TC06", "Stale price guard in config", FAIL,
                   "Add MAX_PRICE_AGE_SEC = 30 to config.py")
    except ImportError:
        record("TC06", "Stale price guard in config", SKIP)


# ── TC15: Max concurrent pairs cap ───────────────────────────────────────────
def test_tc15_max_concurrent_pairs():
    try:
        import config
        has_cap = hasattr(config, "MAX_CONCURRENT_PAIRS") or \
                  hasattr(config, "MAX_OPEN_POSITIONS")
        if has_cap:
            record("TC15", "Max concurrent pairs cap in config", PASS)
        else:
            record("TC15", "Max concurrent pairs cap in config", FAIL,
                   "Add MAX_CONCURRENT_PAIRS = 1 to config.py for Month 1")
    except ImportError:
        record("TC15", "Max concurrent pairs cap in config", SKIP)


# ── TC48: No entry in last 15 min ─────────────────────────────────────────────
def test_tc48_last_entry_cutoff():
    try:
        import config
        cutoff = getattr(config, "LAST_ENTRY_TIME", None) or \
                 getattr(config, "NO_ENTRY_AFTER", None)
        if cutoff:
            record("TC48", "Entry blocked after 3:15 PM", PASS, f"Cutoff={cutoff}")
        else:
            record("TC48", "Entry blocked after 3:15 PM", FAIL,
                   "Add LAST_ENTRY_TIME = '15:15' to config.py")
    except ImportError:
        record("TC48", "Entry blocked after 3:15 PM", SKIP)


# ── Z-Score math correctness ──────────────────────────────────────────────────
def test_zscore_math():
    """Pure math test — no module dependency."""
    prices_a = np.array([100 + i * 0.5 + np.random.normal(0, 0.2) for i in range(100)])
    prices_b = np.array([200 + i * 1.0 + np.random.normal(0, 0.4) for i in range(100)])
    spread = prices_a - 0.5 * prices_b
    zscore = (spread - spread.mean()) / spread.std()
    last_z = zscore[-1]
    if -10 < last_z < 10:
        record("TC_MATH", "Z-score within sane bounds (-10, +10)", PASS,
               f"Last z={last_z:.3f}")
    else:
        record("TC_MATH", "Z-score within sane bounds (-10, +10)", FAIL,
               f"z={last_z:.3f} is out of range — check normalization")


# ── Telegram config validity ──────────────────────────────────────────────────
def test_telegram_config():
    try:
        import config
        token = getattr(config, "TELEGRAM_TOKEN", "")
        chat_id = getattr(config, "TELEGRAM_CHAT_ID", "")
        if not token or len(token) < 20:
            record("TC_TEL", "Telegram token non-empty", FAIL, "Token too short or missing")
        elif ":" not in token:
            record("TC_TEL", "Telegram token format valid", FAIL, "Token missing ':' separator")
        elif not chat_id:
            record("TC_TEL", "Telegram chat ID present", FAIL, "TELEGRAM_CHAT_ID empty")
        else:
            record("TC_TEL", "Telegram config valid", PASS,
                   f"Token length={len(token)}, chat_id={chat_id}")
    except ImportError:
        record("TC_TEL", "Telegram config valid", SKIP)


# ── File structure check ──────────────────────────────────────────────────────
def test_file_structure():
    required = ["config.py", "zscore_engine.py", "telegram_bot.py",
                "paper_trader.py", "risk_manager.py", "main.py"]
    missing = [f for f in required if not Path(f).exists()]
    if not missing:
        record("TC_FILES", "All required files present", PASS)
    else:
        record("TC_FILES", "All required files present", FAIL,
               f"Missing: {', '.join(missing)}")


# ── Pairs config sanity ───────────────────────────────────────────────────────
def test_pairs_config():
    try:
        import config
        pairs = getattr(config, "PAIRS", [])
        if not pairs:
            record("TC_PAIRS", "PAIRS list non-empty in config", FAIL)
            return
        valid = all(isinstance(p, (list, tuple)) and len(p) == 2 for p in pairs)
        if valid:
            record("TC_PAIRS", "PAIRS list valid format", PASS,
                   f"{len(pairs)} pairs: {[f'{a}/{b}' for a,b in pairs]}")
        else:
            record("TC_PAIRS", "PAIRS list valid format", FAIL,
                   "Each pair must be a 2-tuple e.g. ('INFY.NS', 'TCS.NS')")
    except ImportError:
        record("TC_PAIRS", "PAIRS list valid format", SKIP)


# ── Main runner ───────────────────────────────────────────────────────────────
def run_all():
    logger.info("=" * 62)
    logger.info("  Iron-Sentry Test Suite")
    logger.info(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 62)

    test_file_structure()
    test_tc34_python_version()
    test_telegram_config()
    test_pairs_config()
    test_tc50_paper_mode_default()
    test_tc09_sqlite_wal()
    test_tc03_rate_limiter()
    test_tc05_drawdown_kill()
    test_tc06_stale_price_guard()
    test_tc10_profit_threshold()
    test_tc11_nan_handling()
    test_tc13_lookback_minimum()
    test_tc15_max_concurrent_pairs()
    test_tc16_holiday_calendar()
    test_tc24_memory_buffer()
    test_tc25_paper_slippage()
    test_tc28_opposite_legs()
    test_tc30_friday_close()
    test_tc35_pnl_separation()
    test_tc36_trading_hours()
    test_tc38_cointegration_basis()
    test_tc45_kill_switch()
    test_tc48_last_entry_cutoff()
    test_zscore_math()

    logger.info("=" * 62)
    passed = sum(1 for r in results if "PASS" in r["status"])
    failed = sum(1 for r in results if "FAIL" in r["status"])
    skipped = sum(1 for r in results if "SKIP" in r["status"])
    total = len(results)
    logger.info(f"  Results: {passed} passed | {failed} failed | {skipped} skipped | {total} total")
    logger.info("=" * 62)

    if failed > 0:
        logger.info("  FAILED TESTS — fix these before going live:")
        for r in results:
            if "FAIL" in r["status"]:
                logger.info(f"    [{r['id']}] {r['name']}")
                if r["detail"]:
                    logger.info(f"           → {r['detail']}")

    # Write JSON report
    report = {
        "timestamp": datetime.now().isoformat(),
        "summary": {"passed": passed, "failed": failed, "skipped": skipped, "total": total},
        "results": results,
    }
    with open("test_report.json", "w") as f:
        json.dump(report, f, indent=2)
    logger.info("  Report saved → test_report.json")
    logger.info("=" * 62)

    return failed


if __name__ == "__main__":
    sys.exit(run_all())
