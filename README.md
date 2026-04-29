# ⚔️ Iron-Sentry

> **Autonomous statistical pairs trading bot for the Indian stock market (NSE)**
> Built for 24/7 unattended operation on a local Windows machine.

[![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Paper%20Trading-orange)]()
[![Exchange](https://img.shields.io/badge/Exchange-NSE%20India-blue)]()
[![Broker](https://img.shields.io/badge/Broker-Dhan%20HQ-purple)]()

---

## 📊 Analysis Graphs

Visualisation scripts are in `graphs/`. Run from the repo root:

```bash
python graphs/zscore_spread.py      # Z-score spread with entry/exit bands for both pairs
python graphs/pair_correlation.py   # Rolling 30-day correlation and OLS hedge ratio
python graphs/pnl_simulation.py     # Paper-trading cumulative P&L over 252 trading days
```

| Script | What it shows |
|---|---|
| `zscore_spread.py` | Z-score time series with ±2σ entry / ±0.5σ exit bands and long/short signal markers |
| `pair_correlation.py` | Rolling Pearson correlation + OLS β for SAIL/NMDC and NTPC/POWERGRID |
| `pnl_simulation.py` | Cumulative P&L curve + daily return distribution for both pairs |

---

## 📌 Overview

Iron-Sentry is a fully autonomous **statistical arbitrage / pairs trading system** that monitors correlated NSE stock pairs 24/7, executes mean-reversion trades when the z-score of the spread diverges beyond a configurable threshold, and manages all risk automatically — with zero human intervention required during operation.

| | |
|---|---|
| **Strategy** | Statistical Pairs Trading (Mean Reversion) |
| **Universe** | INFY/TCS · HDFCBANK/ICICIBANK · TATAMOTORS/M&M |
| **Entry Signal** | Z-score > ±2.5 (OLS hedge ratio, 30-bar rolling window) |
| **Exit Signal** | Z-score reverts to 0 |
| **Stop-Loss** | Z-score > ±4.0 (spread blowout) |
| **Starting Capital** | ₹5,000 |
| **Target** | ₹16,700/week by Month 5–6 |
| **Leverage** | 1x (Month 1–2) → 5x (Month 5–6) |

---

## 🏗️ Architecture

```
iron-sentry/
│
├── config.py              # Central config — all thresholds, pairs, risk params
├── main.py                # Async orchestrator — PairWorker fan-out loop
│
├── zscore_engine.py       # OLS hedge ratio + rolling z-score + signal logic
├── risk_manager.py        # Drawdown halt · rate limiter · ghost order guard
├── paper_trader.py        # Paper trading engine — fills, positions, SQLite P&L
├── telegram_bot.py        # Async Telegram alerts + 15-min heartbeat
│
├── watchdog_monitor.py    # Fault monitor — RAM/CPU/disk/DB/process checks
├── watchdog.bat           # Windows auto-restart script
│
├── test_suite.py          # 24 automated tests (TC01–TC50)
│
├── .env                   # 🔒 Secrets — Telegram token (NOT committed)
├── .gitignore
│
├── iron_sentry.db         # SQLite — trade log + equity curve (auto-created)
└── iron_sentry.log        # Rolling log file (auto-created)
```

---

## ⚙️ How It Works

```
                      ┌─────────────────────────────────┐
                      │           main.py                │
                      │   (async event loop, 60s tick)   │
                      └────────────┬────────────────────┘
                                   │ fan-out (asyncio.gather)
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                     ▼
        PairWorker           PairWorker            PairWorker
        INFY/TCS          HDFCBANK/ICICIBANK     TATAMOTORS/M&M
              │
              ▼
     ZScoreEngine.update(pa, pb)
     → OLS hedge ratio (cov/var)
     → rolling spread z-score
     → Signal(action, zscore, spread)
              │
              ▼
     RiskManager.can_trade()
     → drawdown check (< 5%)
     → market hours (09:15–15:30 IST)
     → not halted
              │
       ┌──────┴──────┐
       ▼             ▼
   ENTER          EXIT / STOP
       │
       ▼
 PaperTrader.place_order()   ←── async rate limiter (8 OPS max)
 → size position (20% capital cap)
 → simulate fill + slippage (5 bps)
 → persist to SQLite
 → TelegramBot.alert_trade()
```

---

## 🛡️ Risk Controls

| Guard | Trigger | Action |
|---|---|---|
| **Drawdown Halt** | Daily loss > 5% | All trading suspended until next day reset |
| **Z-Score Stop** | \|z\| > 4.0 | Immediate pair close (spread blowout) |
| **Ghost Order Guard** | One leg fails to fill | Both legs rolled back, alert fired |
| **Leg-Out Trap** | Leg A filled, Leg B rejected | Immediate alert + pair cleared |
| **API Rate Limiter** | > 8 orders/sec | Async token bucket — sleeps until slot free |
| **Market Hours** | Outside 09:15–15:30 IST | Orders blocked |
| **Paper Mode Guard** | `PAPER_TRADING=False` without env flag | Watchdog fires critical alert |

---

## 👁️ Watchdog Monitor

Runs as a **separate process** alongside `main.py`. Checks every 60 seconds:

- ✅ `main.py` process alive (auto-restarts on crash)
- ✅ SQLite DB being written to (silence > 20 min = alert)
- ✅ RAM free > 500MB
- ✅ Disk free > 1GB
- ✅ CPU < 90%
- ✅ Log file size < 500MB
- ✅ Internet connectivity (pings Telegram API)
- ✅ Stale positions (open > 3 trading days)
- ✅ DB integrity (SQLite PRAGMA check, hourly)
- ✅ Paper mode not accidentally disabled

All alerts delivered via Telegram with cooldown to prevent spam.

---

## 🚀 Setup

### 1. Prerequisites

```bash
# Python 3.11 required
py -3.11 --version

# Install dependencies
py -3.11 -m pip install python-dotenv aiohttp numpy psutil
```

### 2. Configure secrets

Create a `.env` file in the project root:

```env
TELEGRAM_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

> Get a bot token from [@BotFather](https://t.me/BotFather) on Telegram.
> Get your chat ID from [@userinfobot](https://t.me/userinfobot).

### 3. Run the bot

**Terminal 1 — Main bot:**
```bash
py -3.11 main.py
```

**Terminal 2 — Watchdog monitor:**
```bash
py -3.11 watchdog_monitor.py
```

**Or use the auto-restart batch file:**
```bash
watchdog.bat
```

### 4. Verify it's working

Within 30 seconds you should receive on Telegram:
```
🟢 Iron-Sentry ONLINE
Paper trading active. Watching 3 pairs.
```

---

## 🧪 Test Suite

```bash
py -3.11 test_suite.py
```

Runs 24 automated checks covering:
- Config completeness (TC10, TC15, TC16, TC30, TC48)
- Z-score math correctness (TC11, TC13, TC38)
- Risk controls (TC03, TC05, TC28)
- Infrastructure (TC09, TC24, TC25, TC34, TC35)
- Safety guards (TC50, TC45, TC36, TC06)

Results saved to `test_report.json`. Watchdog re-runs suite every 12 hours automatically.

---

## 📅 Roadmap

| Month | Milestone | Capital | Leverage |
|-------|-----------|---------|----------|
| **1** | Paper trading — validate strategy & infrastructure | ₹0 (simulated) | — |
| **2** | Live trading — 1 pair (INFY/TCS), no leverage | ₹5,000 | 1x |
| **3–4** | Expand to 2–3 pairs, reinvest profits | ₹5,000 + profits | 2x |
| **5–6** | Full system, all pairs, target ₹16,700/week | Compounded | 5x |

---

## 📊 Database Schema

```sql
-- Every trade fill
CREATE TABLE trades (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT,       -- timestamp
    pair_id   TEXT,       -- e.g. "INFY_TCS"
    leg       TEXT,       -- "A" or "B"
    symbol    TEXT,
    side      TEXT,       -- "BUY" or "SELL"
    qty       INTEGER,
    price     REAL,       -- limit price submitted
    filled_at REAL,       -- simulated fill with slippage
    pnl       REAL DEFAULT 0
);

-- Equity snapshot on every order
CREATE TABLE equity_curve (
    ts     TEXT PRIMARY KEY,
    equity REAL
);
```

---

## 🔧 Key Configuration (`config.py`)

```python
ZSCORE_WINDOW   = 30     # rolling window (bars)
ZSCORE_ENTRY    = 2.5    # entry threshold
ZSCORE_EXIT     = 0.0    # exit at mean reversion
ZSCORE_STOP     = 4.0    # emergency stop

MAX_POSITION_PCT = 0.20  # max 20% capital per pair
MAX_DRAWDOWN_PCT = 0.05  # halt at 5% daily drawdown
MAX_ORDERS_PER_SEC = 8   # stay under Dhan's 10/sec limit
SLIPPAGE_BPS    = 5      # 5 basis points paper slippage

MARKET_OPEN_IST  = "09:15"
MARKET_CLOSE_IST = "15:30"
```

---

## 🧠 Strategy Notes

**Why pairs trading?**
Pairs trading is market-neutral — it profits from the *relative* movement between two correlated stocks, not the direction of the market. This makes it resilient to broad market crashes.

**Why OLS hedge ratio?**
The hedge ratio (β = cov(A,B)/var(B)) ensures the spread is stationary. It's recalculated every bar so the model adapts to drift in the correlation.

**Why z-score ±2.5?**
At ±2.5σ, the spread is in the 99th percentile of its historical distribution. Mean reversion is statistically expected. The ±4.0 stop handles the rare case where cointegration breaks down permanently.

---

## ⚠️ Disclaimer

This software is for **educational and research purposes only**. Algorithmic trading carries significant financial risk. Past performance of backtested or paper-traded strategies does not guarantee future results. Never trade with money you cannot afford to lose.

---

## 👤 Author

**Hridam Biswas**
- B.Tech Final Year, KIIT University, Bhubaneswar
- IEEE Published Researcher (x2)
- Ex-Microsoft Bengaluru · Ex-ISTA Austria
- Incoming DELL Intern, June 2026

---

*Built as both a live trading system and a final year ML project.*

