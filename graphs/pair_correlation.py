"""
Rolling correlation and OLS hedge ratio for both NSE trading pairs.
Run: python graphs/pair_correlation.py
"""
import matplotlib.pyplot as plt
import numpy as np

rng = np.random.default_rng(42)
days = 252

def gen_pair(corr, seed):
    rng2 = np.random.default_rng(seed)
    cov = [[1, corr], [corr, 1]]
    returns = rng2.multivariate_normal([0, 0], cov, days) * 0.015
    price_a = 100 * np.cumprod(1 + returns[:, 0])
    price_b = 100 * np.cumprod(1 + returns[:, 1])
    return price_a, price_b

sail, nmdc          = gen_pair(0.78, 1)
ntpc, powergrid     = gen_pair(0.82, 2)

window = 30

def rolling_corr(a, b, w):
    corrs = []
    for i in range(w, len(a)):
        corrs.append(np.corrcoef(a[i-w:i], b[i-w:i])[0, 1])
    return np.array(corrs)

def rolling_hedge(a, b, w):
    betas = []
    for i in range(w, len(a)):
        x = b[i-w:i]; y = a[i-w:i]
        betas.append(np.polyfit(x, y, 1)[0])
    return np.array(betas)

t = np.arange(window, days)
rc_sail    = rolling_corr(sail, nmdc, window)
rc_ntpc    = rolling_corr(ntpc, powergrid, window)
rh_sail    = rolling_hedge(sail, nmdc, window)
rh_ntpc    = rolling_hedge(ntpc, powergrid, window)

fig, axes = plt.subplots(2, 2, figsize=(13, 8))

for (ax_c, ax_h, rc, rh, label, color) in [
    (axes[0, 0], axes[0, 1], rc_sail,  rh_sail,  "SAIL / NMDC",     "#1976D2"),
    (axes[1, 0], axes[1, 1], rc_ntpc,  rh_ntpc,  "NTPC / POWERGRID","#388E3C"),
]:
    ax_c.plot(t, rc, color=color, linewidth=1.3, zorder=3)
    ax_c.axhline(rc.mean(), color="black", linestyle="--", linewidth=1, label=f"mean = {rc.mean():.3f}")
    ax_c.fill_between(t, rc.mean() - rc.std(), rc.mean() + rc.std(), alpha=0.15, color=color)
    ax_c.set_title(f"{label} — Rolling {window}d Correlation", fontsize=11, fontweight="bold")
    ax_c.set_ylabel("Pearson r", fontsize=10)
    ax_c.set_xlabel("Trading Day", fontsize=10)
    ax_c.yaxis.grid(True, linestyle="--", alpha=0.4, zorder=0)
    ax_c.set_axisbelow(True)
    ax_c.legend(fontsize=9)

    ax_h.plot(t, rh, color=color, linewidth=1.3, zorder=3)
    ax_h.axhline(rh.mean(), color="black", linestyle="--", linewidth=1, label=f"mean β = {rh.mean():.3f}")
    ax_h.fill_between(t, rh.mean() - rh.std(), rh.mean() + rh.std(), alpha=0.15, color=color)
    ax_h.set_title(f"{label} — OLS Hedge Ratio (β)", fontsize=11, fontweight="bold")
    ax_h.set_ylabel("Hedge Ratio β", fontsize=10)
    ax_h.set_xlabel("Trading Day", fontsize=10)
    ax_h.yaxis.grid(True, linestyle="--", alpha=0.4, zorder=0)
    ax_h.set_axisbelow(True)
    ax_h.legend(fontsize=9)

plt.suptitle("Iron Sentry — Rolling Correlation & OLS Hedge Ratio", fontsize=14, fontweight="bold")
plt.tight_layout()
plt.savefig("graphs/pair_correlation.png", dpi=150, bbox_inches="tight")
plt.show()
print("Saved: graphs/pair_correlation.png")
