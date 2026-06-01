"""Historical return sourcing + block-bootstrap sampler.

This is the reusable core of the forecast engine (and any future scenario
tooling). Two pieces:

- `fetch_monthly_returns` pulls ~20y of monthly returns for the asset-class
  proxies (`ASSET_PROXIES`) from yfinance, inner-joined on common month-ends and
  disk-cached. Raises `ReturnsUnavailable` on any failure so the caller can fall
  back to a parametric model — the app stays usable offline.
- `BlockBootstrap` resamples contiguous blocks of those returns. The SAME start
  index is used across all asset-class columns in a block, so cross-asset
  correlation (e.g. equity/bond co-movement) is preserved for free.

Pure NumPy; all randomness flows through a caller-supplied `np.random.Generator`
so runs are seedable and tests are deterministic.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

# Asset-class -> historical proxy ticker. Equity uses a global total-market ETF
# (better fit than US-only for a Spain/Chile household); bonds use a broad
# aggregate. Cash is modelled deterministically by the engine (negligible vol),
# so it is intentionally absent here. Swapping a proxy is a one-line change.
ASSET_PROXIES: dict[str, str] = {"equity": "VT", "bonds": "AGG"}

_CACHE_DIR = Path(__file__).resolve().parent / ".forecast_cache"
_CACHE_MAX_AGE_DAYS = 7


class ReturnsUnavailable(Exception):
    """Historical returns could not be fetched (offline / yfinance error)."""


def _cache_path(tickers: tuple[str, ...]) -> Path:
    return _CACHE_DIR / f"returns_{'_'.join(tickers)}.npz"


def _load_cache(tickers: tuple[str, ...]) -> np.ndarray | None:
    path = _cache_path(tickers)
    if not path.exists():
        return None
    try:
        with np.load(path, allow_pickle=False) as data:
            fetched = date.fromisoformat(str(data["fetched"]))
            if (date.today() - fetched).days > _CACHE_MAX_AGE_DAYS:
                return None
            return data["returns"]
    except Exception as e:  # noqa: BLE001 — a corrupt cache should just refetch
        log.warning("Forecast returns cache unreadable (%s); refetching.", e)
        return None


def _save_cache(tickers: tuple[str, ...], returns: np.ndarray) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        np.savez(
            _cache_path(tickers),
            returns=returns,
            fetched=json.dumps(date.today().isoformat()).strip('"'),
        )
    except Exception as e:  # noqa: BLE001 — caching is best-effort
        log.warning("Could not write forecast returns cache (%s).", e)


def fetch_monthly_returns(
    classes: list[str] | None = None, years: int = 20
) -> tuple[np.ndarray, list[str]]:
    """Return `(matrix[T, K], classes)` of monthly returns for the given asset
    classes, inner-joined on common month-ends so each row is one shared period.

    Raises `ReturnsUnavailable` if yfinance is missing/unreachable or returns no
    overlapping history.
    """
    classes = classes or list(ASSET_PROXIES.keys())
    tickers = tuple(ASSET_PROXIES[c] for c in classes)

    cached = _load_cache(tickers)
    if cached is not None and cached.shape[1] == len(classes):
        return cached, classes

    try:
        import pandas as pd
        import yfinance as yf
    except ImportError as e:  # pragma: no cover — guarded by pyproject
        raise ReturnsUnavailable(f"yfinance/pandas not installed: {e}") from e

    try:
        raw = yf.download(
            list(tickers),
            period=f"{years}y",
            interval="1mo",
            auto_adjust=True,
            progress=False,
        )
    except Exception as e:  # noqa: BLE001 — yfinance raises a zoo of errors
        raise ReturnsUnavailable(f"yfinance download failed: {e}") from e

    if raw is None or len(raw) == 0:
        raise ReturnsUnavailable("yfinance returned no data for forecast proxies")

    # `Close` is a frame of [date x ticker] after auto_adjust. Order columns to
    # match `classes`, drop incomplete months, then take pct change.
    try:
        close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
        close = close[list(tickers)].dropna(how="any")
        rets = close.pct_change().dropna(how="any")
    except Exception as e:  # noqa: BLE001
        raise ReturnsUnavailable(f"could not derive returns from yfinance data: {e}") from e

    matrix = np.asarray(rets.to_numpy(), dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] < 24 or matrix.shape[1] != len(classes):
        raise ReturnsUnavailable(
            f"insufficient overlapping history (shape={matrix.shape}) for {classes}"
        )

    _save_cache(tickers, matrix)
    return matrix, classes


class BlockBootstrap:
    """Resamples contiguous, wrap-around blocks from a historical return matrix.

    `returns` is `[T, K]` (months x asset classes). Sampling preserves both
    serial structure (within a block) and cross-asset structure (same time index
    across the K columns).
    """

    def __init__(self, returns: np.ndarray, block_len: int = 6):
        if returns.ndim != 2:
            raise ValueError("returns must be a 2-D [T, K] array")
        if block_len < 1:
            raise ValueError("block_len must be >= 1")
        self.returns = np.asarray(returns, dtype=float)
        self.block_len = block_len
        self.T, self.K = self.returns.shape

    def sample(
        self, n_paths: int, n_months: int, rng: np.random.Generator
    ) -> np.ndarray:
        """Return `[n_paths, n_months, K]` of bootstrapped monthly returns."""
        n_blocks = int(np.ceil(n_months / self.block_len))
        # One random start index per (path, block); blocks wrap around the history.
        starts = rng.integers(0, self.T, size=(n_paths, n_blocks))
        offsets = np.arange(self.block_len)
        # idx[path, block, offset] -> source row in `returns`
        idx = (starts[:, :, None] + offsets[None, None, :]) % self.T
        # -> [n_paths, n_blocks * block_len, K], then trim to n_months
        sampled = self.returns[idx]  # advanced indexing keeps the K axis
        sampled = sampled.reshape(n_paths, n_blocks * self.block_len, self.K)
        return sampled[:, :n_months, :]


def shock_mask(port_returns: np.ndarray, decile: float = 0.1) -> np.ndarray:
    """Boolean mask of path-months whose portfolio return is in the bottom
    `decile` of the realized distribution. ~`decile` of entries fire by
    construction. Returns a mask the same shape as `port_returns`."""
    threshold = np.quantile(port_returns, decile)
    return port_returns < threshold
