# watchdog_monitor.py — Iron-Sentry 24/7 Fault Monitor
# Author: Hridam Biswas | Project: Iron-Sentry
# Run: py -3.11 watchdog_monitor.py
# This runs SEPARATELY from main.py — open a second terminal window
# It checks for faults every 60 seconds and alerts via Telegram

import asyncio
import sqlite3
import json
import os
import sys
import subprocess
import logging
import logging.handlers
import psutil
from datetime import datetime, timedelta
from pathlib import Path

# ── Setup ─────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            "watchdog.log", maxBytes=5_000_000, backupCount=3
        ),
    ],
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("iron_sentry.watchdog")

# Import config safely
try:
    sys.path.insert(0, str(Path(__file__).parent))
    import config
    TELEGRAM_TOKEN   = config.TELEGRAM_TOKEN
    TELEGRAM_CHAT_ID = config.TELEGRAM_CHAT_ID
except KeyError as e:
    logger.error(f"Missing env var {e} — ensure .env file exists with TELEGRAM_TOKEN and TELEGRAM_CHAT_ID")
    sys.exit(1)
except Exception as e:
    logger.error(f"Cannot load config: {e}")
    sys.exit(1)

# ── Constants ─────────────────────────────────────────────────────────────────
CHECK_INTERVAL_SEC = 60          # Run all checks every 60 seconds
DB_PATH = Path("iron_sentry.db")
LOG_PATH = Path("iron_sentry.log")
MAX_HEARTBEAT_SILENCE_MIN = 20   # Alert if no DB write in 20 min
MAX_LOG_SIZE_MB = 500            # Alert if log exceeds 500MB
MIN_FREE_RAM_MB = 500            # Alert if free RAM below 500MB
MIN_FREE_DISK_MB = 1000          # Alert if free disk below 1GB
MAX_CPU_PCT = 90                 # Alert if CPU > 90% for sustained period
RESTART_MAIN_ON_CRASH = True     # Auto-restart main.py if it dies

# ── State ─────────────────────────────────────────────────────────────────────
alert_cooldowns: dict = {}        # fault_key → last_alert_time
fault_counts: dict = {}           # fault_key → count
main_process_pid: int | None = None


# ── Telegram sender ───────────────────────────────────────────────────────────
async def send_alert(text: str, fault_key: str = "", cooldown_min: int = 15):
    """Send Telegram alert with cooldown to prevent spam."""
    if fault_key:
        now = datetime.now()
        last = alert_cooldowns.get(fault_key)
        if last and (now - last).seconds < cooldown_min * 60:
            return  # Still in cooldown
        alert_cooldowns[fault_key] = now
        fault_counts[fault_key] = fault_counts.get(fault_key, 0) + 1

    import aiohttp
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "Markdown",
            }, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    logger.warning(f"Telegram send failed: {resp.status}")
    except Exception as e:
        logger.error(f"Telegram error: {e}")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── Check 1: Main bot still running ──────────────────────────────────────────
async def check_main_process():
    """Detect if main.py process is alive. Restart if RESTART_MAIN_ON_CRASH=True."""
    global main_process_pid

    main_alive = False
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmd = " ".join(proc.info["cmdline"] or [])
            if "main.py" in cmd and "watchdog" not in cmd:
                main_alive = True
                main_process_pid = proc.info["pid"]
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not main_alive:
        logger.warning("main.py is NOT running")
        await send_alert(
            "🚨 *WATCHDOG ALERT*\n`main.py` is NOT running!\n"
            f"Time: `{_now()}`\nAttempting restart...",
            fault_key="main_dead", cooldown_min=5
        )
        if RESTART_MAIN_ON_CRASH:
            await restart_main()
    else:
        logger.debug(f"main.py alive (PID {main_process_pid})")


# ── Check 2: DB heartbeat (last write time) ───────────────────────────────────
async def check_db_heartbeat():
    """Ensure SQLite DB is being written to — proves bot is actively trading."""
    if not DB_PATH.exists():
        logger.warning("iron_sentry.db does not exist yet")
        return

    try:
        mtime = datetime.fromtimestamp(DB_PATH.stat().st_mtime)
        age_min = (datetime.now() - mtime).seconds / 60
        if age_min > MAX_HEARTBEAT_SILENCE_MIN:
            await send_alert(
                f"⚠️ *DB SILENCE ALERT*\n"
                f"No DB writes in `{age_min:.0f}` minutes\n"
                f"Bot may be stuck or crashed\nTime: `{_now()}`",
                fault_key="db_silence", cooldown_min=20
            )
        else:
            logger.debug(f"DB last write: {age_min:.1f} min ago — OK")
    except Exception as e:
        logger.error(f"DB heartbeat check failed: {e}")


# ── Check 3: RAM usage ────────────────────────────────────────────────────────
async def check_ram():
    """Alert if available RAM drops too low — TC24 memory leak guard."""
    try:
        mem = psutil.virtual_memory()
        free_mb = mem.available / 1024 / 1024
        used_pct = mem.percent
        if free_mb < MIN_FREE_RAM_MB:
            await send_alert(
                f"⚠️ *RAM ALERT*\n"
                f"Free RAM: `{free_mb:.0f}MB` (below {MIN_FREE_RAM_MB}MB threshold)\n"
                f"Used: `{used_pct:.0f}%` — possible memory leak\nTime: `{_now()}`",
                fault_key="low_ram", cooldown_min=30
            )
        else:
            logger.debug(f"RAM OK: {free_mb:.0f}MB free ({used_pct:.0f}% used)")
    except Exception as e:
        logger.error(f"RAM check failed: {e}")


# ── Check 4: Disk space ───────────────────────────────────────────────────────
async def check_disk():
    """Alert if disk space is critically low — TC29 log growth guard."""
    try:
        disk = psutil.disk_usage(str(Path.home()))
        free_mb = disk.free / 1024 / 1024
        if free_mb < MIN_FREE_DISK_MB:
            await send_alert(
                f"⚠️ *DISK SPACE ALERT*\n"
                f"Free disk: `{free_mb:.0f}MB` — critically low!\n"
                f"Clear logs or old files\nTime: `{_now()}`",
                fault_key="low_disk", cooldown_min=60
            )
        else:
            logger.debug(f"Disk OK: {free_mb:.0f}MB free")
    except Exception as e:
        logger.error(f"Disk check failed: {e}")


# ── Check 5: Log file size ────────────────────────────────────────────────────
async def check_log_size():
    """Alert if iron_sentry.log is getting huge — TC29."""
    if not LOG_PATH.exists():
        return
    try:
        size_mb = LOG_PATH.stat().st_size / 1024 / 1024
        if size_mb > MAX_LOG_SIZE_MB:
            await send_alert(
                f"⚠️ *LOG SIZE ALERT*\n"
                f"`iron_sentry.log` is `{size_mb:.0f}MB`\n"
                f"Rotate or clear logs\nTime: `{_now()}`",
                fault_key="log_size", cooldown_min=120
            )
        else:
            logger.debug(f"Log size OK: {size_mb:.1f}MB")
    except Exception as e:
        logger.error(f"Log size check failed: {e}")


# ── Check 6: CPU sustained high ───────────────────────────────────────────────
async def check_cpu():
    """Alert if CPU is pegged — may indicate runaway loop."""
    try:
        cpu = psutil.cpu_percent(interval=2)
        if cpu > MAX_CPU_PCT:
            await send_alert(
                f"⚠️ *CPU ALERT*\n"
                f"CPU at `{cpu:.0f}%` — possible runaway loop\nTime: `{_now()}`",
                fault_key="high_cpu", cooldown_min=15
            )
        else:
            logger.debug(f"CPU OK: {cpu:.0f}%")
    except Exception as e:
        logger.error(f"CPU check failed: {e}")


# ── Check 7: Open positions vs DB consistency ─────────────────────────────────
async def check_open_positions():
    """Read open trades from DB. Alert if any position open > 3 trading days (TC43)."""
    if not DB_PATH.exists():
        return
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        # Check if trades table exists
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [t["name"] for t in tables]

        if "trades" not in table_names:
            conn.close()
            return

        # Identify open pairs: pairs where leg A and B are both present but
        # BUY count != SELL count (net open). Uses actual schema columns only.
        open_pairs = conn.execute("""
            SELECT pair_id,
                   SUM(CASE WHEN side='BUY'  THEN 1 ELSE 0 END) as buys,
                   SUM(CASE WHEN side='SELL' THEN 1 ELSE 0 END) as sells,
                   MIN(ts) as opened_at
            FROM trades
            GROUP BY pair_id
            HAVING buys != sells
        """).fetchall()
        conn.close()

        for trade in open_pairs:
            opened_at = trade["opened_at"]
            if opened_at:
                age = datetime.now() - datetime.fromisoformat(opened_at)
                if age.days >= 3:
                    await send_alert(
                        f"⚠️ *STALE POSITION ALERT*\n"
                        f"Pair `{trade['pair_id']}` open for `{age.days}` days — TC43 time stop triggered\n"
                        f"Consider manual close\nTime: `{_now()}`",
                        fault_key=f"stale_{trade['pair_id']}", cooldown_min=240
                    )
        if open_pairs:
            logger.debug(f"Open positions: {len(open_pairs)}")
    except Exception as e:
        logger.error(f"Position check failed: {e}")


# ── Check 8: Paper mode guard ─────────────────────────────────────────────────
async def check_paper_mode():
    """Paranoia check — ensure PAPER_TRADING is True unless explicitly overridden (TC50)."""
    try:
        import importlib
        import config as cfg
        importlib.reload(cfg)  # Re-read from disk
        is_paper = getattr(cfg, "PAPER_TRADING", True)
        live_env = os.environ.get("IRON_SENTRY_LIVE", "0")

        if not is_paper and live_env != "1":
            await send_alert(
                "🚨 *PAPER MODE DISABLED WITHOUT ENV FLAG*\n"
                "`PAPER_TRADING=False` but `IRON_SENTRY_LIVE` env var not set!\n"
                "Real orders may fire. Check config.py immediately!\n"
                f"Time: `{_now()}`",
                fault_key="paper_disabled", cooldown_min=5
            )
    except Exception as e:
        logger.error(f"Paper mode check failed: {e}")


# ── Check 9: DB integrity ─────────────────────────────────────────────────────
async def check_db_integrity():
    """SQLite integrity check every hour — TC09."""
    if not DB_PATH.exists():
        return
    try:
        conn = sqlite3.connect(str(DB_PATH))
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        conn.close()
        if result != "ok":
            await send_alert(
                f"🚨 *DB CORRUPTION ALERT*\n"
                f"SQLite integrity check: `{result}`\n"
                f"Backup DB immediately!\nTime: `{_now()}`",
                fault_key="db_corrupt", cooldown_min=60
            )
        else:
            logger.debug("DB integrity OK")
    except Exception as e:
        logger.error(f"DB integrity check failed: {e}")


# ── Check 10: Internet connectivity ───────────────────────────────────────────
async def check_internet():
    """Ping Telegram API to confirm internet is up."""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    logger.debug("Internet OK")
                else:
                    logger.warning(f"Internet check got {resp.status}")
    except Exception:
        logger.warning("Internet connectivity issue detected")
        await send_alert(
            f"⚠️ *INTERNET ALERT*\n"
            f"Cannot reach Telegram API\nBot may be trading blind!\n"
            f"Time: `{_now()}`",
            fault_key="no_internet", cooldown_min=10
        )


# ── Auto-restart main.py ──────────────────────────────────────────────────────
async def restart_main():
    """Restart main.py as a subprocess."""
    try:
        script = Path(__file__).parent / "main.py"
        if not script.exists():
            logger.error("main.py not found — cannot restart")
            return
        proc = subprocess.Popen(
            [sys.executable, str(script)],
            stdout=open("main_restart.log", "a"),
            stderr=subprocess.STDOUT,
        )
        logger.info(f"main.py restarted (PID {proc.pid})")
        await send_alert(
            f"🔄 *AUTO-RESTART*\n"
            f"`main.py` restarted by watchdog\nPID: `{proc.pid}`\n"
            f"Time: `{_now()}`",
            fault_key="restarted"
        )
    except Exception as e:
        logger.error(f"Restart failed: {e}")


# ── Hourly summary ────────────────────────────────────────────────────────────
async def send_hourly_summary():
    """Send a system health summary every hour."""
    try:
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage(str(Path.home()))
        cpu = psutil.cpu_percent(interval=1)
        db_size = DB_PATH.stat().st_size / 1024 if DB_PATH.exists() else 0
        log_size = LOG_PATH.stat().st_size / 1024 / 1024 if LOG_PATH.exists() else 0

        # Count open positions
        open_count = 0
        if DB_PATH.exists():
            try:
                conn = sqlite3.connect(str(DB_PATH))
                tables = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                if "trades" in tables:
                    open_count = conn.execute("""
                        SELECT COUNT(DISTINCT pair_id) FROM trades
                        GROUP BY pair_id
                        HAVING SUM(CASE WHEN side='BUY' THEN 1 ELSE 0 END) !=
                               SUM(CASE WHEN side='SELL' THEN 1 ELSE 0 END)
                    """).fetchone()
                    open_count = open_count[0] if open_count else 0
                conn.close()
            except Exception:
                pass

        msg = (
            f"📊 *Hourly Health Report*\n"
            f"Time: `{_now()}`\n"
            f"CPU: `{cpu:.0f}%` | RAM free: `{mem.available/1024/1024:.0f}MB`\n"
            f"Disk free: `{disk.free/1024/1024:.0f}MB` | DB: `{db_size:.0f}KB`\n"
            f"Log: `{log_size:.1f}MB` | Open positions: `{open_count}`\n"
            f"Faults detected: `{sum(fault_counts.values())}`"
        )
        await send_alert(msg, fault_key="hourly_summary", cooldown_min=55)
    except Exception as e:
        logger.error(f"Hourly summary failed: {e}")


# ── Run test suite ─────────────────────────────────────────────────────────────
async def run_test_suite_check():
    """Run test_suite.py and alert if new failures found."""
    suite = Path(__file__).parent / "test_suite.py"
    if not suite.exists():
        return
    try:
        result = subprocess.run(
            [sys.executable, str(suite)],
            capture_output=True, text=True, timeout=60
        )
        report_path = Path("test_report.json")
        if report_path.exists():
            with open(report_path) as f:
                report = json.load(f)
            failed = report["summary"]["failed"]
            if failed > 0:
                failed_ids = [r["id"] for r in report["results"] if "FAIL" in r["status"]]
                await send_alert(
                    f"⚠️ *TEST SUITE FAILURES*\n"
                    f"`{failed}` test(s) failing:\n"
                    f"`{'`, `'.join(failed_ids)}`\n"
                    f"Time: `{_now()}`",
                    fault_key="test_failures", cooldown_min=120
                )
    except subprocess.TimeoutExpired:
        logger.warning("test_suite.py timed out")
    except Exception as e:
        logger.error(f"Test suite check failed: {e}")


# ── Main watchdog loop ────────────────────────────────────────────────────────
async def watchdog_loop():
    logger.info("=" * 60)
    logger.info("  Iron-Sentry Watchdog Monitor STARTED")
    logger.info(f"  Checking every {CHECK_INTERVAL_SEC}s")
    logger.info("=" * 60)

    await send_alert(
        f"👁 *Watchdog Monitor ONLINE*\n"
        f"Checking every `{CHECK_INTERVAL_SEC}s`\n"
        f"Time: `{_now()}`"
    )

    tick = 0
    while True:
        tick += 1
        logger.info(f"--- Watchdog tick #{tick} ---")

        # Run all checks
        await check_main_process()
        await check_ram()
        await check_disk()
        await check_log_size()
        await check_cpu()
        await check_paper_mode()
        await check_internet()

        # DB checks every 5 ticks (5 min)
        if tick % 5 == 0:
            await check_db_heartbeat()
            await check_open_positions()

        # Integrity check every 60 ticks (1 hour)
        if tick % 60 == 0:
            await check_db_integrity()
            await send_hourly_summary()

        # Test suite every 720 ticks (12 hours)
        if tick % 720 == 0:
            await run_test_suite_check()

        await asyncio.sleep(CHECK_INTERVAL_SEC)


if __name__ == "__main__":
    # Check psutil installed
    try:
        import psutil
    except ImportError:
        print("Installing psutil...")
        subprocess.run([sys.executable, "-m", "pip", "install", "psutil"], check=True)
        import psutil

    asyncio.run(watchdog_loop())
