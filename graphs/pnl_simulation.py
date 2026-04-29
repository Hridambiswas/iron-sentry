"""
Simulated paper-trading P&L curve for both pairs over a 252-day backtest.
Assumes ₹1L position per trade, 0.05% transaction cost, z-score entry/exit rules.
Run: python graphs/pnl_simulation.py
"""
import matplotlib.pyplot as plt
import numpy as np

rng = np.random.default_rng(99)
days = 252
ENTRY_Z = 2.0
EXIT_Z  = 0.5
POSITION = 100_000  # ₹

def simulate_pnl(seed):
    rng2 = np.random.default_rng(seed)
    z = np.zeros(days)
    for i in range(1, days):
        z[i] = 0.97 * z[i - 1] + rng2.normal(0, 0.20)

    daily_ret = rng2.normal(0.0004, 0.012, days)
    pnl = np.zeros(days)
    position = 0
    entry_price = 0.0
    for i in range(1, days):
        if position == 0:
            if z[i] > ENTRY_Z:
                position = -1; entry_price = 1.0
            elif z[i] < -ENTRY_Z:
                position = 1; entry_price = 1.0
        else:
            gross = position * daily_ret[i] * POSITION
            pnl[i] = gross - abs(gross) * 0.0005
            if abs(z[i]) < EXIT_Z:
                position = 0
    return np.cumsum(pnl), z

pnl_sail, z_sail     = simulate_pnl(1)
pnl_ntpc, z_ntpc     = simulate_pnl(5)
t = np.arange(days)

fig, axes = plt.subplots(2, 2, figsize=(13, 8), gridspec_kw={"width_ratios": [3, 1]})

for row, (pnl, z, label, color) in enumerate([
    (pnl_sail, z_sail, "SAIL / NMDC",      "#1976D2"),
    (pnl_ntpc, z_ntpc, "NTPC / POWERGRID", "#388E3C"),
]):
    ax_p = axes[row, 0]
    ax_d = axes[row, 1]

    ax_p.plot(t, pnl / 1000, color=color, linewidth=1.5, zorder=3)
    ax_p.fill_between(t, 0, pnl / 1000, where=pnl >= 0, alpha=0.15, color="#4CAF50")
    ax_p.fill_between(t, 0, pnl / 1000, where=pnl < 0,  alpha=0.15, color="#F44336")
    ax_p.axhline(0, color="grey", linewidth=0.8)
    final = pnl[-1] / 1000
    ax_p.text(days - 5, final, f"₹{final:+.1f}K", ha="right", fontsize=9,
              color="#4CAF50" if final >= 0 else "#F44336", fontweight="bold")
    ax_p.set_title(f"{label} — Cumulative P&L (paper trading)", fontsize=11, fontweight="bold")
    ax_p.set_ylabel("Cumulative P&L (₹K)", fontsize=10)
    ax_p.set_xlabel("Trading Day", fontsize=10)
    ax_p.yaxis.grid(True, linestyle="--", alpha=0.4, zorder=0)
    ax_p.set_axisbelow(True)

    daily_pnl = np.diff(np.concatenate([[0], pnl])) / 1000
    ax_d.hist(daily_pnl, bins=25, orientation="horizontal", color=color, alpha=0.75, edgecolor="white")
    ax_d.axhline(0, color="grey", linewidth=0.8)
    ax_d.set_xlabel("Frequency", fontsize=9)
    ax_d.set_title("Daily P&L\nDistribution", fontsize=10, fontweight="bold")
    ax_d.yaxis.grid(True, linestyle="--", alpha=0.4, zorder=0)
    ax_d.set_axisbelow(True)

plt.suptitle("Iron Sentry — Paper Trading P&L Simulation (252 days, ₹1L/trade)", fontsize=13, fontweight="bold")
plt.tight_layout()
plt.savefig("graphs/pnl_simulation.png", dpi=150, bbox_inches="tight")
plt.show()
print("Saved: graphs/pnl_simulation.png")
