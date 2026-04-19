from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from darth_schwader.db.repositories.watchlist import WatchlistRepository
from darth_schwader.domain.asset_types import AssetType
from darth_schwader.market.bar_provider import BarProvider
from darth_schwader.market.indicator_engine import (
    MIN_BARS,
    IndicatorEngine,
    IndicatorSet,
)
from darth_schwader.market.setup_detector import SetupDetector, SetupScore

_DEFAULT_LOOKBACK_DAYS = 180


@dataclass(frozen=True, slots=True)
class HeatmapRow:
    symbol: str
    asset_type: AssetType
    indicators: IndicatorSet | None
    setup: SetupScore | None
    error: str | None


class SetupHeatmapService:
    def __init__(
        self,
        *,
        watchlist_repo: WatchlistRepository,
        bar_provider: BarProvider,
        indicator_engine: IndicatorEngine | None = None,
        setup_detector: SetupDetector | None = None,
        lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    ) -> None:
        self._watchlist_repo = watchlist_repo
        self._bar_provider = bar_provider
        self._indicator_engine = indicator_engine or IndicatorEngine()
        self._setup_detector = setup_detector or SetupDetector()
        self._lookback_days = lookback_days

    async def snapshot(self) -> list[HeatmapRow]:
        entries = await self._watchlist_repo.list_all(active_only=True)
        rows: list[HeatmapRow] = []
        for entry in entries:
            rows.append(await self._score_entry(entry.symbol, entry.asset_type))
        return rows

    async def _score_entry(self, symbol: str, asset_type: AssetType) -> HeatmapRow:
        try:
            bars = await self._bar_provider.fetch_daily_bars(symbol, self._lookback_days)
        except Exception as exc:
            return HeatmapRow(
                symbol=symbol,
                asset_type=asset_type,
                indicators=None,
                setup=None,
                error=f"bar fetch failed: {exc}",
            )
        if len(bars) < MIN_BARS:
            return HeatmapRow(
                symbol=symbol,
                asset_type=asset_type,
                indicators=None,
                setup=None,
                error=f"insufficient bars ({len(bars)}/{MIN_BARS})",
            )
        indicators = self._indicator_engine.compute(symbol, bars)
        setup = self._setup_detector.score(indicators)
        return HeatmapRow(
            symbol=symbol,
            asset_type=asset_type,
            indicators=indicators,
            setup=setup,
            error=None,
        )


def heatmap_row_to_dict(row: HeatmapRow) -> dict[str, object]:
    """Serialise a heatmap row to a JSON-friendly dict."""
    if row.indicators is None or row.setup is None:
        return {
            "symbol": row.symbol,
            "asset_type": row.asset_type.value,
            "indicators": None,
            "best_setup": None,
            "best_score": "0",
            "scores": {},
            "error": row.error,
        }
    return {
        "symbol": row.symbol,
        "asset_type": row.asset_type.value,
        "indicators": _indicators_to_dict(row.indicators),
        "best_setup": row.setup.best_setup,
        "best_score": _decimal_str(row.setup.best_score),
        "scores": {name: _decimal_str(score) for name, score in row.setup.scores.items()},
        "error": None,
    }


def _indicators_to_dict(ind: IndicatorSet) -> dict[str, str]:
    return {
        "close": _decimal_str(ind.close),
        "rsi14": _decimal_str(ind.rsi14),
        "ema8": _decimal_str(ind.ema8),
        "ema21": _decimal_str(ind.ema21),
        "atr14": _decimal_str(ind.atr14),
        "adx14": _decimal_str(ind.adx14),
        "bb_width": _decimal_str(ind.bb_width),
        "bb_width_pct": _decimal_str(ind.bb_width_pct),
        "vwap": _decimal_str(ind.vwap),
        "vwap_distance": _decimal_str(ind.vwap_distance),
    }


def _decimal_str(value: Decimal) -> str:
    # Trim noisy trailing zeros while keeping Decimal precision.
    quantized = value.normalize()
    if quantized == quantized.to_integral():
        return str(quantized.quantize(Decimal("1")))
    return format(quantized, "f")


__all__ = ["HeatmapRow", "SetupHeatmapService", "heatmap_row_to_dict"]
