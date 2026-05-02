# zscore_engine.py — Spread & Z-Score Engine
# Author: Hridam Biswas | Project: Iron-Sentry

import numpy as np
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Tuple
from config import ZSCORE_WINDOW, ZSCORE_ENTRY, ZSCORE_EXIT, ZSCORE_STOP


@dataclass
class Signal:
    pair: Tuple[str, str]
    zscore: float
    spread: float
    action: str          # "ENTER_LONG_A", "ENTER_LONG_B", "EXIT", "STOP", "HOLD"
    leg_a: str
    leg_b: str


class ZScoreEngine:
    """
    Rolling z-score engine for a single pair.
    Spread = price_A - hedge_ratio * price_B  (OLS hedge ratio, recomputed each bar)
    """

    def __init__(self, leg_a: str, leg_b: str, window: int = ZSCORE_WINDOW):
        self.leg_a  = leg_a
        self.leg_b  = leg_b
        self.window = window
        self._prices_a: deque = deque(maxlen=window)
        self._prices_b: deque = deque(maxlen=window)
        self._last_signal: Optional[Signal] = None
        self._last_zscore: float = 0.0

    # ── Public API ────────────────────────────────────────────────────────────

    def update(self, price_a: float, price_b: float) -> Optional[Signal]:
        """
        Feed one bar. Returns a Signal once we have enough history, else None.
        """
        self._prices_a.append(price_a)
        self._prices_b.append(price_b)

        if len(self._prices_a) < self.window:
            return None

        hedge_ratio = self._hedge_ratio()
        spread      = price_a - hedge_ratio * price_b
        zscore      = self._zscore(hedge_ratio)
        action      = self._action(zscore)

        signal = Signal(
            pair    = (self.leg_a, self.leg_b),
            zscore  = round(zscore, 4),
            spread  = round(spread, 4),
            action  = action,
            leg_a   = self.leg_a,
            leg_b   = self.leg_b,
        )
        self._last_signal = signal
        self._last_zscore = zscore
        return signal

    @property
    def last_signal(self) -> Optional[Signal]:
        return self._last_signal

    @property
    def last_zscore(self) -> float:
        return self._last_zscore

    def forced_action(self) -> str:
        """Best entry direction based on z-sign, used for forced daily trade."""
        if self._last_zscore >= 0:
            return "ENTER_LONG_B"
        return "ENTER_LONG_A"

    # ── Internals ─────────────────────────────────────────────────────────────

    def _hedge_ratio(self) -> float:
        """OLS on log returns — avoids spurious regression on non-stationary raw prices."""
        ra = np.diff(np.log(np.array(self._prices_a)))
        rb = np.diff(np.log(np.array(self._prices_b)))
        var_b = np.var(rb)
        if var_b == 0:
            return 1.0
        return float(np.cov(ra, rb)[0, 1] / var_b)

    def _zscore(self, hedge_ratio: float) -> float:
        ra = np.diff(np.log(np.array(self._prices_a)))
        rb = np.diff(np.log(np.array(self._prices_b)))
        spreads = ra - hedge_ratio * rb
        std = spreads.std()
        if std == 0:
            return 0.0
        return float((spreads[-1] - spreads.mean()) / std)

    def _action(self, z: float) -> str:
        if z >= ZSCORE_STOP or z <= -ZSCORE_STOP:
            return "STOP"
        if z >= ZSCORE_ENTRY:
            return "ENTER_LONG_B"    # spread high → short A, long B
        if z <= -ZSCORE_ENTRY:
            return "ENTER_LONG_A"    # spread low  → long A, short B
        if abs(z) <= ZSCORE_EXIT:
            return "EXIT"
        return "HOLD"


# ── Quick smoke-test ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import random
    random.seed(42)
    engine = ZScoreEngine("INFY", "TCS", window=10)

    # Simulate 15 bars of correlated prices
    base = 1500.0
    for i in range(15):
        pa = base + random.gauss(0, 10)
        pb = pa * 0.95 + random.gauss(0, 5)
        sig = engine.update(pa, pb)
        if sig:
            print(f"Bar {i:02d} | z={sig.zscore:+.3f} | action={sig.action}")
