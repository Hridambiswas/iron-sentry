"""
Z-score spread simulation for SAIL/NMDC and NTPC/POWERGRID pairs.
Shows entry/exit signal bands and mean-reversion behaviour.
Run: python graphs/zscore_spread.py
"""
import matplotlib.pyplot as plt
import numpy as np

rng = np.random.default_rng(7)
days = 252

def simulate_zscore(seed_offset=0):
    rng2 = np.random.default_rng(7 + seed_offset)
    z = np.zeros(days)
    for i in range(1, days):
        z[i] = 0.97 * z[i - 1] + rng2.normal(0, 0.18)
    return z

z_sail_nmdc   = simulate_zscore(0)
z_ntpc_power  = simulate_zscore(3)
t = np.arange(days)

ENTRY = 2.0
EXIT  = 0.5

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 8), sharex=True)

for ax, z, pair, color in [
    (ax1, z_sail_nmdc,  "SAIL / NMDC",          "#1976D2"),
    (ax2, z_ntpc_power, "NTPC / POWERGRID",      "#388E3C"),
]:
    ax.plot(t, z, color=color, linewidth=1.2, label="Z-score spread", zorder=3)
    ax.axhline( ENTRY, color="#F44336", linestyle="--", linewidth=1.2, label=f"+{ENTRY} entry (short)")
    ax.axhline(-ENTRY, color="#F44336", linestyle="--", linewidth=1.2, label=f"-{ENTRY} entry (long)")
    ax.axhline( EXIT,  color="#FF9800", linestyle=":",  linewidth=1.0, label=f"+{EXIT} exit")
    ax.axhline(-EXIT,  color="#FF9800", linestyle=":",  linewidth=1.0, label=f"-{EXIT} exit")
    ax.axhline(0, color="grey", linewidth=0.8, linestyle="-")

    long_entries  = np.where(z < -ENTRY)[0]
    short_entries = np.where(z >  ENTRY)[0]
    ax.scatter(t[long_entries],  z[long_entries],  color="#4CAF50", s=18, zorder=4, label="Long signal")
    ax.scatter(t[short_entries], z[short_entries], color="#E91E63", s=18, zorder=4, label="Short signal")

    ax.fill_between(t, -EXIT, EXIT, alpha=0.08, color="grey", label="Exit zone")
    ax.set_ylabel("Z-score", fontsize=11)
    ax.set_title(f"Iron Sentry — {pair} Z-score Spread (252 trading days)", fontsize=12, fontweight="bold")
    ax.yaxis.grid(True, linestyle="--", alpha=0.4, zorder=0)
    ax.set_axisbelow(True)
    ax.legend(fontsize=8, loc="upper right", ncol=3)

ax2.set_xlabel("Trading Day", fontsize=11)
plt.tight_layout()
plt.savefig("graphs/zscore_spread.png", dpi=150, bbox_inches="tight")
plt.show()
print("Saved: graphs/zscore_spread.png")
