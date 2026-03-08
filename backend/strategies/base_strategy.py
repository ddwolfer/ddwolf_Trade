"""
Base Strategy class - all strategies inherit from this.
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from models import OHLCVData, TradeSignal


class BaseStrategy(ABC):
    """
    Base class for all trading strategies.

    To create a new strategy:
    1. Inherit from BaseStrategy
    2. Implement generate_signal()
    3. Implement metadata() classmethod
    4. Register with @StrategyRegistry.register decorator
    """

    def __init__(self, params: Dict[str, Any]):
        self.params = params
        self._indicator_cache: Dict[str, Any] = {}

    @abstractmethod
    def generate_signal(self, ohlcv: OHLCVData, index: int) -> Optional[TradeSignal]:
        """
        Called for each candle during backtesting.

        Args:
            ohlcv: Full OHLCV dataset
            index: Current candle index (0-based)

        Returns:
            TradeSignal with type "BUY" or "SELL", or None for no action.
        """
        pass

    @classmethod
    @abstractmethod
    def metadata(cls) -> Dict[str, Any]:
        """
        Return strategy metadata including parameter schema.

        Returns:
            {
                "name": "Strategy Name",
                "description": "What this strategy does",
                "category": "technical|momentum|mean_reversion",
                "parameters": {
                    "param_name": {
                        "type": "int|float",
                        "default": value,
                        "min": value,
                        "max": value,
                        "description": "What this param controls"
                    }
                }
            }
        """
        pass

    def validate_params(self):
        """Validate parameters against metadata schema."""
        meta = self.__class__.metadata()
        for name, spec in meta.get("parameters", {}).items():
            if name not in self.params:
                self.params[name] = spec["default"]
            val = self.params[name]
            if "min" in spec and val < spec["min"]:
                raise ValueError(f"{name} must be >= {spec['min']}")
            if "max" in spec and val > spec["max"]:
                raise ValueError(f"{name} must be <= {spec['max']}")

    def cache_indicator(self, key: str, compute_fn):
        """Cache indicator computation to avoid recalculating."""
        if key not in self._indicator_cache:
            self._indicator_cache[key] = compute_fn()
        return self._indicator_cache[key]
